"""Fast unit: standard plugin MCP/skill contribution keeps scoped source and version; expected <1s, max 5s."""
from pathlib import Path
import json
import tomllib
from catalog_json.plugin_inputs import load_plugins,plugin_servers


def test_portable_plugin_loads_and_binds_page_without_copying_skills(tmp_path):
    root=Path(__file__).parents[1]
    plugins=load_plugins({'agent_plugins':[{'path':'plugins/catalog-parsers'}]},root)
    assert plugins[0]['name']=='catalog-parsers' and plugins[0]['version']=='0.2.2'
    assert len(plugins[0]['sha256'])==64
    server=plugin_servers(plugins,tmp_path/'source.pdf',78,tmp_path)['catalog-parsers']
    assert '${PLUGIN_ROOT}' not in ' '.join(server['args'])
    assert server['args'][-4:-2]==['--page','78']
    assert str((root/'plugins/catalog-parsers').resolve()) in server['args']


def test_public_plugin_manifests_describe_the_same_release_version():
    """Fast unit: portable manifest20 mislabelled package22, expected<1s/max5s."""
    root=Path(__file__).parents[1]
    version=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
    assert json.loads((root/'plugin.json').read_text())['version']==version
    assert json.loads((root/'.claude-plugin/plugin.json').read_text())['version']==version
    assert json.loads((root/'.codex-plugin/plugin.json').read_text())['version']==version
