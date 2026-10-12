"""Compose portable Agent Plugin 1.0 MCP/skill contributions through native FastAgent APIs."""
import hashlib
import json
from pathlib import Path


def load_plugins(config,base):
    entries=config.get('agent_plugins',[]);plugins=[]
    for entry in entries:
        root=(Path(base)/entry['path']).resolve()
        manifest=json.loads((root/'plugin.json').read_text())
        mcp=json.loads((root/'mcp.json').read_text())
        if manifest.get('$schema')!='https://agent-plugins.org/schemas/1.0.0/plugin.schema.json' or mcp.get('$schema')!='https://agent-plugins.org/schemas/1.0.0/mcp.schema.json':raise ValueError('Expected portable Agent Plugin 1.0 manifests')
        files=[root/'plugin.json',root/'mcp.json',*sorted((root/'skills').rglob('SKILL.md')),*sorted((root/'src').rglob('*.py'))]
        digest=hashlib.sha256(b''.join(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes() for p in files)).hexdigest()
        plugins.append({'root':root,'name':manifest['name'],'version':manifest.get('version'),'sha256':digest,'servers':mcp['mcpServers']})
    if len({p['name'] for p in plugins})!=len(plugins):raise ValueError('Duplicate plugin names')
    return plugins


def plugin_servers(plugins,source,page,output):
    result={}
    for plugin in plugins:
        root=plugin['root'];data=Path(output).resolve()/'.plugin-data'/plugin['name']
        def expand(value):return str(value).replace('${PLUGIN_ROOT}',str(root)).replace('${PLUGIN_DATA}',str(data))
        for name,spec in plugin['servers'].items():
            if name=='catalog' or name in result:raise ValueError('Plugin MCP server name collision')
            if spec.get('type')!='stdio':raise ValueError('Only explicitly configured local stdio plugins are supported by this extractor')
            args=[expand(v) for v in spec.get('args',[])];env={k:expand(v) for k,v in spec.get('env',{}).items()}
            # Source/page scoping is the catalogue-parser plugin's supported native CLI contract.
            if plugin['name']=='catalog-parsers':args+=['--source',str(Path(source).resolve()),'--page',str(page),'--cache-root',str(data/'cache')]
            server={'command':expand(spec['command']),'args':args,'env':env}
            if spec.get('cwd'):server['cwd']=expand(spec['cwd'])
            result[name]=server
    return result
