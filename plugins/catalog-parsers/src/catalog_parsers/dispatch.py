"""Explicit optional executors, isolated dependencies, source-bound retained evidence."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys
from .native import PACKAGES


def executors():
    path=os.environ.get('CATALOG_PARSER_EXECUTORS')
    if not path:return {}
    specs=json.loads(Path(path).read_text())
    for name,spec in specs.items():
        if spec.get('backend',name) not in PACKAGES:raise ValueError(f'Unsupported executor backend: {name}')
        if not isinstance(spec.get('version'),str):raise ValueError('Executor needs a locked version')
        if not 1<=spec.get('timeout_seconds',600)<=1200:raise ValueError('Executor timeout outside 1..1200')
        if not spec.get('python') and not spec.get('remote'):raise ValueError('Executor needs a Python interpreter or explicit remote transport')
    return specs


def capabilities():
    return {name:spec['version'] for name,spec in executors().items()}


def parse_external(source,page,backend,output,model='not-applicable',resume=False):
    from .remote import run_remote
    spec=executors()[backend];source=Path(source).resolve();output=Path(output).resolve()
    identity={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'physical_page':page,'backend':backend,'executor':spec,'gateway_sha256':hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest()}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    if (output/'gateway.json').exists():
        old=json.loads((output/'gateway.json').read_text())
        if not resume or old['cache_key']!=key:raise ValueError('Changed/immutable executor cache cannot be replayed')
        receipt=json.loads((output/'receipt.json').read_text())
        for filename,field in [('candidate.json','candidate_sha256'),('raw.json','raw_sha256')]:
            p=output/filename
            if receipt.get('status')!='completed' or not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=receipt.get(field):raise ValueError('Incomplete/tampered executor artifact cannot be reused')
        return receipt
    if output.exists() and any(output.iterdir()):raise ValueError('Use a fresh executor output directory')
    timeout=spec.get('timeout_seconds',600);device=spec.get('device','cpu');native=spec.get('backend',backend)
    if spec.get('remote'):
        receipt=run_remote(source,page,native,output,spec['remote'],device,model,timeout,spec.get('env',{}))
    else:
        output.mkdir(parents=True)
        env={**os.environ,**spec.get('env',{}),'PYTHONPATH':str(Path(__file__).parent.parent)}
        args=[spec['python'],'-m','catalog_parsers.experiment','--source',str(source),'--page',str(page),'--backend',native,'--device',device,'--deadline',str(timeout),'--output',str(output),'--model',model]
        # The native runner rejects nonempty output directories. Keep its launch
        # log alongside the directory until the child has initialized its receipt.
        log_path=output.with_name(output.name+'.executor.log')
        try:
            with log_path.open('w') as log:subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout+15,check=False)
        finally:
            if log_path.exists():log_path.replace(output/'executor.log')
        receipt=json.loads((output/'receipt.json').read_text())
    if receipt.get('status')=='completed':
        if receipt.get('source_sha256')!=identity['source_sha256'] or receipt.get('physical_page')!=page or receipt.get('package_version')!=spec['version']:raise ValueError('Executor receipt mismatches source/page/locked backend version')
    (output/'gateway.json').write_text(json.dumps({'cache_key':key,'requested_backend':backend,'device':device,'executor_config_sha256':hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()},indent=2))
    return receipt
