"""Focused integration: real subprocess matrix and no-replay resume. Expected <2 s, max 15 s."""
import json,hashlib,sys
from pathlib import Path
from test_benchmark import fixture,candidate
from catalog_json.bench_runner import run_suite


def test_matrix_executes_and_resumes_without_replay(tmp_path):
    source=tmp_path/'source.pdf';source.write_bytes(b'synthetic source binding')
    gold=fixture();gold.source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path/'gold.json').write_text(gold.model_dump_json())
    (tmp_path/'page.json').write_text(candidate().model_dump_json())
    adapter=tmp_path/'adapter.py';adapter.write_text('import shutil,sys\nfrom pathlib import Path\np=Path(sys.argv[1]);p.parent.mkdir(exist_ok=True);shutil.copyfile(sys.argv[2],p)\n')
    manifest=tmp_path/'suite.json';manifest.write_text(json.dumps({
      'cases':[{'id':'sample','source':str(source),'page':1,'fixture':'gold.json'}],
      'projects':[{'id':p,'version':'synthetic-v1','cwd':str(tmp_path),'command':[sys.executable,str(adapter),'{run_dir}/candidate.json',str(tmp_path/'page.json'),'{model}'],'artifact':'candidate.json'} for p in ['one','two']],
      'models':['synthetic-a','synthetic-b'],'timeout_seconds':5,'deadline_seconds':15}))
    import subprocess
    subprocess.run(['git','init',str(tmp_path)],check=True,capture_output=True)
    (tmp_path/'.gitignore').write_text('out/\n')
    subprocess.run(['git','-C',str(tmp_path),'add','source.pdf','gold.json','page.json','adapter.py','suite.json','.gitignore'],check=True)
    subprocess.run(['git','-C',str(tmp_path),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','synthetic baseline'],check=True,capture_output=True)
    out=tmp_path/'out';first=run_suite(manifest,out)
    assert first['complete'] and len(first['runs'])==4 and all(r['score']['all_verified_checks_passed'] for r in first['runs'])
    # Changed grader/fixtures can reuse original output; the adapter stays frozen.
    (tmp_path/'page.json').write_text(candidate().model_dump_json())
    resumed=run_suite(manifest,out,resume=True)
    assert all(r['status']=='completed' for r in resumed['runs'])
    artifact=next(out.glob('*/candidate.json'));artifact.write_text('{}')
    changed=run_suite(manifest,out,resume=True)
    assert sum(r['status']=='artifact_unverified' for r in changed['runs'])==1


def test_missing_adapter_is_recorded_as_failed_not_running(tmp_path):
    """Focused integration: missing binary must not leave an ambiguous external action. Expected <1 s, max 5 s."""
    source=tmp_path/'source.pdf';source.write_bytes(b'fixture source')
    gold=fixture();gold.source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path/'gold.json').write_text(gold.model_dump_json())
    manifest=tmp_path/'suite.json';manifest.write_text(json.dumps({'cases':[{'id':'sample','source':str(source),'page':1,'fixture':'gold.json'}],
      'projects':[{'id':'missing','version':'v1','cwd':str(tmp_path),'command':['/does-not-exist/catalog-adapter','{model}'],'artifact':'candidate.json'}],
      'models':['synthetic'],'timeout_seconds':1,'deadline_seconds':5}))
    result=run_suite(manifest,tmp_path/'out')
    assert result['complete'] and result['runs'][0]['status']=='failed'
