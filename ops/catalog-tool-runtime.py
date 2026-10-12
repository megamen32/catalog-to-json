"""Explicitly compose pinned legacy agent logic with another pinned catalog-tool server."""
import contextlib
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

PROFILE_VERSION='1.4.15'
SUPPORTED_PROFILES={PROFILE_VERSION,'1.4.22'}

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fixed_component(path):
    data=json.loads(Path(path).read_text())
    if data.get('schema_version')!='1.0' or data.get('profile_version') not in SUPPORTED_PROFILES or data.get('role')!='extractor':
        raise ValueError('Unsupported catalog tool composition descriptor')
    if data['profile_version']=='1.4.22' and data.get('legacy_program',{}).get('package_version')!='1.4.3':
        raise ValueError('Delivery continuation profile requires the declared1.4.3 agent runtime')
    if data['profile_version']=='1.4.22' and data.get('program',{}).get('package_version')!='1.4.8':
        raise ValueError('Delivery continuation profile requires the declared1.4.8 fixed catalog tools')
    for filename,expected in data['file_sha256'].items():
        if digest(filename)!=expected:raise ValueError('Pinned catalog composition input changed')
    result=subprocess.run([data['python'],'-c',"import json,hashlib;from catalog_json.provenance import program_version;from catalog_json.schema import PageContent,Review;print(json.dumps({'program':program_version(),'schemas':{c.__name__:hashlib.sha256(json.dumps(c.model_json_schema(),sort_keys=True).encode()).hexdigest() for c in (PageContent,Review)}}))"],capture_output=True,text=True,timeout=10,check=True)
    actual=json.loads(result.stdout)
    if actual['program']!=data['program'] or actual['schemas']!=data['schemas']:
        raise ValueError('Catalog tool runtime metadata or schemas changed')
    skills=Path(data['legacy_skills'])
    for name,expected in data['legacy_skill_sha256'].items():
        if digest(skills/name/'SKILL.md')!=expected:raise ValueError('Pinned native legacy skill changed')
    return data,actual

@contextlib.contextmanager
def composed_runtime(adapter,descriptor):
    """Isolated worker only. Original logic/skills remain intact; generated MCP argv is explicit."""
    descriptor=Path(descriptor).resolve();component,actual=fixed_component(descriptor)
    from catalog_json.schema import PageContent,Review
    old_schemas={c.__name__:hashlib.sha256(json.dumps(c.model_json_schema(),sort_keys=True).encode()).hexdigest() for c in (PageContent,Review)}
    if old_schemas!=actual['schemas']:raise ValueError('Legacy and fixed catalog schemas differ')
    old_pair=adapter.AgentPair;old_program=adapter.program_version;agent_module=inspect.getmodule(old_pair)
    if old_program()!=component['legacy_program']:raise ValueError('Legacy agent program does not match declared component')
    if Path(agent_module.SKILLS).resolve()!=Path(component['legacy_skills']).resolve():raise ValueError('Declared legacy skill root differs from the active native agent')
    old_fast=agent_module.FastAgent;bridge_sha=digest(__file__);adapter_sha=digest(adapter.__file__)
    def components():
        _,now=fixed_component(descriptor)
        return {'agent_logic':old_program(),'catalog_tools':now['program'],'legacy_skills':component['legacy_skill_sha256'],
                'catalog_server_bridge_sha256':digest(component['server_bridge']),'role_worker_bridge_sha256':digest(component['role_worker']),'composition_bridge_sha256':bridge_sha,'delivery_adapter_sha256':adapter_sha}
    def program():
        parts=components()
        return {'package_version':component.get('profile_version',PROFILE_VERSION),'git_revision':None,'dirty':None,
                'source_code_sha256':hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest(),
                'python_version':parts['agent_logic']['python_version'],'components':parts}
    class ComposedPair(old_pair):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.contract_digest=hashlib.sha256(json.dumps({'kind':'catalog-tools-composition-v1','legacy_contract':self.contract_digest,
                 'components':components(),'schemas':actual['schemas']},sort_keys=True).encode()).hexdigest()
        async def run(self,role,*args,**kwargs):
            if role!='extractor':raise ValueError('Catalog composition is an extractor-only route')
            return await super().run(role,*args,**kwargs)
    def fast_factory(*args,**kwargs):
        # Rewrite only the worker-generated catalog server entry, never the frozen source/config.
        import yaml
        path=Path(kwargs['config_path']);config=yaml.safe_load(path.read_text())
        server=config['mcp']['servers']['catalog']
        if server.get('args',[])[:2]!=['-m','catalog_json.tools']:raise ValueError('Unexpected native catalog command')
        server['command']=component['python']
        server['args']=[component['server_bridge'],'--composition',str(descriptor),*server['args'][2:]]
        path.write_text(yaml.safe_dump(config),encoding='utf-8')
        return old_fast(*args,**kwargs)
    adapter.AgentPair=ComposedPair;adapter.program_version=program;agent_module.FastAgent=fast_factory
    try:yield
    finally:adapter.AgentPair=old_pair;adapter.program_version=old_program;agent_module.FastAgent=old_fast


def server_main():
    import argparse
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--composition',type=Path,required=True)
    args,remaining=parser.parse_known_args();data,_=fixed_component(args.composition)
    if '--role' not in remaining or remaining[remaining.index('--role')+1]!='extractor':raise ValueError('Composed catalog server is extractor-only')
    # Serve the SAME legacy native skill text, while executing only the pinned fixed tools.
    from catalog_json import tools
    if tools.SKILLS.resolve()==Path(data['legacy_skills']).resolve():raise ValueError('Catalog tool component must be distinct from legacy agent runtime')
    tools.SKILLS=Path(data['legacy_skills']);sys.argv=[sys.argv[0],*remaining]
    return tools.main()

if __name__=='__main__':server_main()
