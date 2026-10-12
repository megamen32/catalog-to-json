"""Fast unit: account recovery must not inherit a lifetime retry exponent; <1s/max5s."""
import asyncio
import pytest
from catalog_json.staged import ProviderGate


def test_clean_recovery_keeps_diagnostics_but_next_wave_starts_short_backoff(monkeypatch):
    clock=[100.0];monkeypatch.setattr('catalog_json.staged.time.monotonic',lambda:clock[0])
    async def run():
        gate=ProviderGate(8,30,4)
        for _ in range(8):await gate.rate_limited();clock[0]=gate.cooldown+1
        for _ in range(4):await gate.succeeded()
        assert gate.rate_limit_count==gate.rate_limit_waves==8
        await gate.rate_limited()
        assert gate.rate_limit_waves==9 and gate.cooldown-clock[0]==30
    asyncio.run(run())


def test_recovered_sdk_retries_do_not_reset_streak_or_ramp(monkeypatch):
    clock=[100.0];monkeypatch.setattr('catalog_json.staged.time.monotonic',lambda:clock[0])
    async def run():
        gate=ProviderGate(8,30,4);before=gate.rate_limit_count
        await gate.rate_limited();clock[0]=gate.cooldown+1
        for _ in range(4):await gate.succeeded(rate_limit_count=before)
        assert gate.backoff_streak==1 and gate.limit==2 and gate.clean_successes==0
        await gate.rate_limited();assert gate.cooldown-clock[0]==60
    asyncio.run(run())


def test_later_wave_between_completion_and_capacity_callback_is_not_clean(monkeypatch):
    clock=[100.0];monkeypatch.setattr('catalog_json.staged.time.monotonic',lambda:clock[0])
    async def run():
        gate=ProviderGate(8,30,4)
        for _ in range(3):await gate.succeeded(rate_limit_count=0)
        await gate.rate_limited();await gate.succeeded(rate_limit_count=0)
        assert gate.backoff_streak==1 and gate.clean_successes==0
    asyncio.run(run())


def test_recovery_checkpoint_retains_pause_and_clean_progress(monkeypatch):
    clock=[100.0];monkeypatch.setattr('catalog_json.staged.time.monotonic',lambda:clock[0])
    state={'configured_maximum':8,'current_limit':2,'rate_limit_count':98,'rate_limit_waves':8,'backoff_streak':0,'clean_successes':4,'backoff_remaining_seconds':150}
    gate=ProviderGate(8,30,4);gate.restore(state,10)
    assert gate.snapshot()['backoff_remaining_seconds']==140
    assert gate.backoff_streak==0 and gate.rate_limit_waves==8
    for field,value in [('backoff_streak',9),('clean_successes',True),('clean_successes',5)]:
        with pytest.raises(ValueError):gate.restore({**state,field:value})
    legacy={k:v for k,v in state.items() if k not in ['backoff_streak','clean_successes']};gate.restore(legacy)
    assert gate.backoff_streak==8 and gate.clean_successes==0
