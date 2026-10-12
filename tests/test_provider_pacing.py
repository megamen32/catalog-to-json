"""Focused integration: bounded parallel calls/backoff; expected<1s/max5s."""
import asyncio
from catalog_json.staged import ProviderGate
from catalog_json.staged import observe_worker_rate_limits
import json


def test_provider_gate_bounds_active_calls_and_reduces_after_429():
    async def run():
        gate=ProviderGate(2,.01);active=0;peak=0
        async def work():
            nonlocal active,peak
            async with gate:
                active+=1;peak=max(peak,active);await asyncio.sleep(.01);active-=1
        await asyncio.gather(*(work() for _ in range(6)))
        assert peak==2
        await gate.rate_limited();assert gate.limit==1 and gate.rate_limit_count==1
        started=asyncio.get_running_loop().time()
        async with gate:pass
        assert asyncio.get_running_loop().time()-started>=.005
        for _ in range(4):await gate.succeeded()
        assert gate.limit==2
    asyncio.run(run())


def test_cancelled_wait_does_not_leak_provider_capacity():
    async def run():
        gate=ProviderGate(1,.01)
        async with gate:
            waiter=asyncio.create_task(gate.__aenter__());await asyncio.sleep(.01)
            waiter.cancel();await asyncio.gather(waiter,return_exceptions=True)
        async with gate:assert gate.active==1
        assert gate.active==0
    asyncio.run(run())


def test_initial_concurrency_ramps_independently_but_never_beyond_budget():
    async def run():
        a=ProviderGate(8,.01,initial=2);b=ProviderGate(8,.01,initial=2)
        for _ in range(4):await a.succeeded()
        assert a.limit==3 and b.limit==2
        for _ in range(100):await a.succeeded()
        assert a.limit==8
        await a.rate_limited();assert a.limit==4 and b.limit==2
    asyncio.run(run())


def test_completed_sdk_retry_is_observed_without_replaying_artifact(tmp_path):
    async def run():
        log=tmp_path/'worker.log';receipt=tmp_path/'rate-limits.jsonl';gate=ProviderGate(4,.01)
        # Source cells and arbitrary numbers must not look like provider HTTP status.
        log.write_text('Source cell value 429\n{"value":429}\n')
        seen=await observe_worker_rate_limits(log,receipt,gate.rate_limited)
        assert not seen and gate.limit==4
        with log.open('a') as stream:stream.write('HTTP Request: POST https://api.example/v4/messages "HTTP/1.1 429 Too Many Requests"\n')
        seen=await observe_worker_rate_limits(log,receipt,gate.rate_limited,seen)
        assert gate.limit==2 and gate.rate_limit_count==1
        await observe_worker_rate_limits(log,receipt,gate.rate_limited,seen)
        assert gate.rate_limit_count==1
        assert len(receipt.read_text().splitlines())==1 and 'api.example' not in receipt.read_text()
        assert json.loads(receipt.read_text())['signal']=='provider_rate_limit'
    asyncio.run(run())


def test_native_sdk_retry_observer_retains_retry_and_restores_hook(monkeypatch):
    from fast_agent.llm import fastagent_llm
    from catalog_json.stage_worker import provider_retry_observer
    sentinel=object();seen=[];received=[]
    def original(error,*args,**kwargs):received.append(error);return sentinel
    monkeypatch.setattr(fastagent_llm,'provider_retry',original)
    class RateError(Exception):status_code=429
    with provider_retry_observer(lambda:seen.append(429)):
        error=RateError('Private provider details')
        assert fastagent_llm.provider_retry(error)==sentinel
        assert fastagent_llm.provider_retry(ValueError('Source value 429'))==sentinel
    assert seen==[429] and len(received)==2 and fastagent_llm.provider_retry is original


def test_underlying_sdk_recovered_429_is_observed(monkeypatch):
    from openai._base_client import BaseClient
    from catalog_json.stage_worker import provider_retry_observer
    from types import SimpleNamespace
    seen=[]
    def original(client,response):return 'unchanged SDK decision'
    monkeypatch.setattr(BaseClient,'_should_retry',original)
    with provider_retry_observer(lambda:seen.append(429)):
        assert BaseClient._should_retry(None,SimpleNamespace(status_code=429))=='unchanged SDK decision'
        assert BaseClient._should_retry(None,SimpleNamespace(status_code=200))=='unchanged SDK decision'
    assert seen==[429] and BaseClient._should_retry is original


def test_rate_limit_wave_is_counted_but_reduces_admission_once():
    async def run():
        gate=ProviderGate(8,.02,initial=4)
        for _ in range(4):await gate.rate_limited()
        assert gate.rate_limit_count==4 and gate.limit==2 and gate.rate_limit_waves==1
        remaining=gate.cooldown-asyncio.get_running_loop().time();assert 0<remaining<=.02
        await asyncio.sleep(.025);await gate.rate_limited()
        assert gate.limit==1 and gate.rate_limit_waves==2 and gate.rate_limit_count==5
    asyncio.run(run())
