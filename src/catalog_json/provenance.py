"""Execution metadata without credentials or conversational transcripts."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys


def artifact_origin(work,path,source_sha256,page,attempt,role,model,contract_sha256):
    """Bind a producer receipt to saved bytes; a runner label is never a fallback."""
    work=Path(work);path=Path(path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    identity={'role':role,'page':page,'attempt':attempt,'source_sha256':source_sha256,
              'model':model,'contract_sha256':contract_sha256}
    log=work/'tools.jsonl'
    events=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    tool='save_page_json' if role=='extractor' else 'save_review'
    saves=[event for event in events if event.get('tool')==tool and all(event.get(k)==v for k,v in identity.items())]
    latest=saves[-1] if saves else None
    bound=bool(digest and latest and latest.get('sha256')==digest)
    result={'status':'producer_unknown','program':None,'artifact_sha256':digest,
            'source_bound_save':bound,'source_sha256':source_sha256,'physical_page':page,
            'attempt':attempt,'role':role,'model':model,'contract_sha256':contract_sha256}
    if not bound:return result
    receipts=[]
    for receipt in (work/'calls').glob('*/result.json'):
        data=json.loads(receipt.read_text());execution=data.get('execution',{})
        expected={**identity,'physical_page':page,'artifact_sha256':digest};expected.pop('page')
        if (data.get('status')=='completed' and execution.get('program')
                and all(execution.get(k)==v for k,v in expected.items())
                and execution.get('started_at',float('inf'))<=latest.get('time',0)<=execution.get('finished_at',-1)):
            receipts.append((execution['finished_at'],receipt,execution))
    if receipts:
        _,receipt,execution=max(receipts,key=lambda item:item[0])
        result.update(status='receipt_verified',program=execution['program'],
                      receipt=str(receipt.relative_to(work)),started_at=execution['started_at'],
                      finished_at=execution['finished_at'])
    return result


def program_version():
    root=Path(__file__).resolve().parents[2]
    has_checkout=(root/'.git').exists()
    git=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,timeout=5) if has_checkout else None
    status=subprocess.run(['git','-C',str(root),'status','--porcelain'],capture_output=True,text=True,timeout=5) if has_checkout else None
    files=sorted(Path(__file__).parent.rglob('*.py'))+sorted((Path(__file__).parent/'skills').rglob('SKILL.md'))
    return {'package_version':importlib.metadata.version('catalog-to-json'),
            'git_revision':git.stdout.strip() if git is not None and git.returncode==0 else None,
            'dirty':bool(status.stdout.strip()) if status is not None and status.returncode==0 else None,
            'source_code_sha256':hashlib.sha256(b''.join(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes() for p in files)).hexdigest(),
            'python_version':sys.version.split()[0]}
