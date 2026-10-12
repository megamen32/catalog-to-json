"""Foreground SSH transport for native parser experiments; no cloud or daemon."""
import argparse,hashlib,json,shlex,subprocess,time,uuid
from pathlib import Path


def run_remote(source,page,backend,output,remote,device,model='not-applicable',timeout=600,env=None):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('Remote experiment output must be fresh')
    output.mkdir(parents=True,exist_ok=True)
    host=remote['host'];port=str(remote.get('port',22));root=remote['root'];python=remote['python']
    ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','-p',port,host];scp=['scp','-q','-P',port]
    digest=hashlib.sha256(source.read_bytes()).hexdigest();selected=f'{root}/sources/{digest}.pdf';destination=f'{root}/runs/{uuid.uuid4().hex}'
    started=time.monotonic()
    def command(args,limit=30):return subprocess.run(ssh+[shlex.join(args)],check=True,capture_output=True,text=True,timeout=limit)
    command(['mkdir','-p',root+'/sources',root+'/runs'])
    verify='import hashlib,sys,pathlib;p=pathlib.Path(sys.argv[1]);print(hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "missing")'
    result=command([python,'-c',verify,selected])
    if result.stdout.strip()!=digest:
        staging=selected+'.'+uuid.uuid4().hex+'.partial'
        subprocess.run(scp+[str(source),host+':'+staging],check=True,timeout=180)
        if command([python,'-c',verify,staging]).stdout.strip()!=digest:raise ValueError('Remote source transfer hash mismatch')
        command(['mv',staging,selected])
    args=['env']+[f'{k}={v}' for k,v in (env or {}).items()]+[python,'-m','catalog_parsers.experiment','--source',selected,'--page',str(page),'--backend',backend,'--device',device,'--deadline',str(timeout),'--output',destination,'--model',model]
    with (output/'transport.log').open('w') as log:
        subprocess.run(ssh+[shlex.join(args)],stdout=log,stderr=subprocess.STDOUT,timeout=timeout+30,check=False)
    # Even failed native runs retain their diagnostics/checkpoint; do not retry them here.
    subprocess.run(scp+[host+':'+destination+'/*',str(output)],check=True,timeout=120)
    receipt=json.loads((output/'receipt.json').read_text())
    if receipt.get('source_sha256')!=digest or receipt.get('physical_page')!=page:raise ValueError('Remote receipt source/page mismatch')
    for filename,field in [('candidate.json','candidate_sha256'),('raw.json','raw_sha256')]:
        p=output/filename
        if receipt.get('status')=='completed' and (not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=receipt.get(field)):raise ValueError('Remote artifact hash mismatch')
    (output/'transport-receipt.json').write_text(json.dumps({'host':host,'port':port,'root':root,'device':device,'native_receipt_sha256':hashlib.sha256((output/'receipt.json').read_bytes()).hexdigest(),'source_sha256':digest,'physical_page':page,'elapsed_seconds':round(time.monotonic()-started,3),'native_elapsed_seconds':receipt.get('elapsed_seconds'),'status':receipt.get('status')},indent=2))
    return receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--page',type=int,required=True);p.add_argument('--backend',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--executor',type=Path,required=True);p.add_argument('--model',default='not-applicable');a=p.parse_args();s=json.loads(a.executor.read_text());r=run_remote(a.source,a.page,a.backend,a.output,s['remote'],s.get('device','cpu'),a.model,s.get('timeout_seconds',600),s.get('env',{}));print(json.dumps(r));return 0 if r['status']=='completed' else 2


if __name__=='__main__':raise SystemExit(main())
