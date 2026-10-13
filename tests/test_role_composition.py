"""Fast unit: pinned cross-version tools must be explicit and source-bound; expected<1s/max5s."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
import yaml
from catalog_json.schema import PageContent,Review

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('catalog_composition_test',ROOT/'ops/catalog-tool-runtime.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)

class LegacyPair:
    def __init__(self,*args,**kwargs):self.contract_digest='unchanged-legacy-contract'
    async def run(self,role,*args,**kwargs):return 'unchanged logic'

def fixture(monkeypatch,tmp_path):
    schemas={c.__name__:hashlib.sha256(json.dumps(c.model_json_schema(),sort_keys=True).encode()).hexdigest() for c in (PageContent,Review)}
    tools={'package_version':'fixed','source_code_sha256':'tools-one','python_version':'3.12'}
    legacy={'package_version':'legacy','source_code_sha256':'original-agent','python_version':'3.12'}
    component={'legacy_program':legacy,'legacy_skills':str(tmp_path/'native-skills'),'python':'pinned-fixed-python','server_bridge':'pinned-server-bridge','role_worker':'pinned-role-worker','legacy_skill_sha256':{'catalog-extract':'original-skill'}}
    actual={'program':tools,'schemas':schemas}
    monkeypatch.setattr(bridge,'fixed_component',lambda p:(component,actual))
    monkeypatch.setattr(bridge,'digest',lambda p:'bridge-pinned-digest')
    monkeypatch.setattr(sys.modules[__name__],'SKILLS',Path(component['legacy_skills']),raising=False)
    monkeypatch.setattr(sys.modules[__name__],'FastAgent',lambda *a,**k:yaml.safe_load(Path(k['config_path']).read_text()),raising=False)
    adapter=SimpleNamespace(AgentPair=LegacyPair,program_version=lambda:dict(legacy),__file__='native-adapter')
    return adapter,component,actual

def test_composition_records_both_real_components_and_changes_contract(monkeypatch,tmp_path):
    adapter,component,actual=fixture(monkeypatch,tmp_path);old_pair=adapter.AgentPair;old_program=adapter.program_version
    with bridge.composed_runtime(adapter,tmp_path/'descriptor'):
        first=adapter.AgentPair();program=adapter.program_version()
        assert first.contract_digest!='unchanged-legacy-contract'
        assert program['package_version']=='1.4.15'
        assert program['components']['agent_logic']==old_program()
        assert program['components']['catalog_tools']==actual['program']
        old_hash=first.contract_digest;actual['program']={**actual['program'],'source_code_sha256':'tools-two'}
        assert adapter.AgentPair().contract_digest!=old_hash
        assert asyncio.run(first.run('extractor'))=='unchanged logic'
        with pytest.raises(ValueError,match='extractor-only'):asyncio.run(first.run('reviewer'))
    assert adapter.AgentPair is old_pair and adapter.program_version is old_program

def test_only_generated_catalog_command_is_replaced_other_servers_and_skills_stay(monkeypatch,tmp_path):
    adapter,component,actual=fixture(monkeypatch,tmp_path);descriptor=tmp_path/'descriptor';path=tmp_path/'generated.yaml'
    config={'mcp':{'servers':{'catalog':{'command':'original-agent-python','args':['-m','catalog_json.tools','--source','physical.pdf','--contract-sha256','fresh-contract']},'parser':{'command':'original-parser','args':['same']}}},'provider':{'api_key':'${PROTECTED_KEY}'}}
    path.write_text(yaml.safe_dump(config));prior_parser=dict(config['mcp']['servers']['parser'])
    with bridge.composed_runtime(adapter,descriptor):
        changed=FastAgent(config_path=path)
    catalog=changed['mcp']['servers']['catalog']
    assert catalog['command']==component['python']
    assert catalog['args']==[component['server_bridge'],'--composition',str(descriptor.resolve()),'--source','physical.pdf','--contract-sha256','fresh-contract']
    assert changed['mcp']['servers']['parser']==prior_parser and changed['provider']==config['provider']
    assert component['legacy_skill_sha256']['catalog-extract']=='original-skill'

def test_schema_mismatch_refuses_before_monkeypatching_native_program(monkeypatch,tmp_path):
    adapter,_,actual=fixture(monkeypatch,tmp_path);old=adapter.AgentPair;actual['schemas']['PageContent']='different'
    with pytest.raises(ValueError,match='schemas differ'):
        with bridge.composed_runtime(adapter,tmp_path/'descriptor'):pass
    assert adapter.AgentPair is old

def test_tampered_component_pin_is_rejected_before_runtime_probe(tmp_path):
    tracked=tmp_path/'component.py';tracked.write_text('original');p=tmp_path/'descriptor.json'
    p.write_text(json.dumps({'schema_version':'1.0','profile_version':'1.4.15','role':'extractor','file_sha256':{str(tracked):hashlib.sha256(b'original').hexdigest()}}))
    tracked.write_text('changed')
    with pytest.raises(ValueError,match='input changed'):bridge.fixed_component(p)

def test_unexpected_native_server_command_cannot_be_silently_composed(monkeypatch,tmp_path):
    adapter,_,_=fixture(monkeypatch,tmp_path);path=tmp_path/'generated.yaml';path.write_text(yaml.safe_dump({'mcp':{'servers':{'catalog':{'command':'python','args':['-m','unknown.tools']}}}}))
    with bridge.composed_runtime(adapter,tmp_path/'descriptor'):
        with pytest.raises(ValueError,match='Unexpected native catalog command'):FastAgent(config_path=path)


def test_declared_legacy_program_cannot_label_another_agent_runtime(monkeypatch,tmp_path):
    adapter,component,_=fixture(monkeypatch,tmp_path);component['legacy_program']={**component['legacy_program'],'source_code_sha256':'another-core'}
    with pytest.raises(ValueError,match='Legacy agent program'):
        with bridge.composed_runtime(adapter,tmp_path/'descriptor'):pass


def test_delivery_continuation_profile_keeps_exact_declared_agent_and_fixed_tools(monkeypatch,tmp_path):
    """Fast unit: explicit143 continuation composition is a new producer, not15; <1s/max5s."""
    adapter,component,actual=fixture(monkeypatch,tmp_path);component['profile_version']='1.4.22'
    with bridge.composed_runtime(adapter,tmp_path/'descriptor'):
        assert adapter.program_version()['package_version']=='1.4.22'
        assert adapter.program_version()['components']['agent_logic']==component['legacy_program']
        assert adapter.program_version()['components']['catalog_tools']==actual['program']


def test_continuation_profile_cannot_claim_single_generation142(tmp_path):
    """Fast unit: refuse a misleading delivery profile before any runtime/provider call; <1s/max5s."""
    descriptor=tmp_path/'descriptor.json'
    descriptor.write_text(json.dumps({'schema_version':'1.0','profile_version':'1.4.22','role':'extractor',
        'legacy_program':{'package_version':'1.4.2'},'file_sha256':{}}))
    with pytest.raises(ValueError,match='continuation profile'):bridge.fixed_component(descriptor)


def test_continuation_profile_refuses_unfixed_native_tools(tmp_path):
    """Fast unit: new continuation cannot restore the known destructive finalizer; <1s/max5s."""
    descriptor=tmp_path/'descriptor.json'
    descriptor.write_text(json.dumps({'schema_version':'1.0','profile_version':'1.4.22','role':'extractor',
        'legacy_program':{'package_version':'1.4.3'},'program':{'package_version':'1.4.2'},'file_sha256':{}}))
    with pytest.raises(ValueError,match='fixed catalog tools'):bridge.fixed_component(descriptor)


@pytest.mark.parametrize('agent,tools',[('1.4.3','1.4.25'),('1.4.2','1.4.8')])
def test_durable_composition_refuses_mislabeled_components(tmp_path,agent,tools):
    descriptor=tmp_path/'descriptor.json'
    descriptor.write_text(json.dumps({'schema_version':'1.0','profile_version':'1.4.25','role':'extractor',
        'legacy_program':{'package_version':agent},'program':{'package_version':tools},'file_sha256':{}}))
    with pytest.raises(ValueError,match='Durable composition'):bridge.fixed_component(descriptor)
