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


def test_resume_gate_retains_saturated_limit_and_cooldown_without_active_calls():
    """Fast unit: delivery restart cannot flood a saturated provider; <1s/max5s."""
    gate=ProviderGate(8,30,initial=4)
    gate.restore({'configured_maximum':8,'current_limit':1,'active_calls':4,'rate_limit_count':40,'rate_limit_waves':2,'backoff_remaining_seconds':60},elapsed=15)
    assert gate.limit==1 and gate.active==0 and gate.rate_limit_count==40 and gate.rate_limit_waves==2
    assert 44<gate.snapshot()['backoff_remaining_seconds']<=45
    reduced=ProviderGate(2,30);reduced.restore({'configured_maximum':8,'current_limit':5,'rate_limit_count':1,'rate_limit_waves':1,'backoff_remaining_seconds':0},elapsed=0)
    assert reduced.limit==2


def test_operator_quota_hold_paces_future_admission_but_keeps_other_provider_running():
    """Focused integration: account quota pauses only future calls; <1s/max5s."""
    import time
    async def run():
        a=ProviderGate(8,.01);b=ProviderGate(8,.01);await a.hold_until(time.time()+.04)
        admitted=[]
        async def first():
            async with a:admitted.append('held')
        waiter=asyncio.create_task(first());await asyncio.sleep(.01)
        assert not admitted and a.active==0
        async with b:admitted.append('other')
        assert admitted==['other']
        await waiter;assert admitted==['other','held'] and a.active==0
    asyncio.run(run())


def test_operator_hold_rejects_wrong_model_provider_and_nonfinite_deadline(tmp_path):
    """Fast unit: unbound or malformed operator control cannot govern a model; <1s/max5s."""
    from types import SimpleNamespace
    import time,pytest
    from catalog_json.staged import operator_holds
    a=SimpleNamespace(extractor='anthropic.test',reviewer='zai.test');providers={'extractor':'anthropic','reviewer':'zai'};p=tmp_path/'holds.json'
    hold={'schema_version':'1.0','providers':{'anthropic':{'model':a.extractor,'not_before_unix':time.time()+60}}};p.write_text(json.dumps(hold))
    assert operator_holds(p,a,providers)[0]['anthropic']>time.time()
    for model,until in [('other',time.time()+60),(a.extractor,float('nan')),(a.extractor,True),(a.extractor,time.time()+90000)]:
        p.write_text(json.dumps({'schema_version':'1.0','providers':{'anthropic':{'model':model,'not_before_unix':until}}}))
        with pytest.raises(ValueError):operator_holds(p,a,providers)
    p.write_text(json.dumps({'schema_version':'1.0','providers':{'unknown':{'model':a.extractor,'not_before_unix':0}}}))
    with pytest.raises(ValueError):operator_holds(p,a,providers)
