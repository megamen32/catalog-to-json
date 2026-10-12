"""Bounded native-parser benchmark arm with immutable outputs and provenance."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
from .native import PACKAGES, settings, convert


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--page',required=True,type=int);p.add_argument('--backend',required=True,choices=list(PACKAGES));p.add_argument('--output',required=True,type=Path);p.add_argument('--model',default='not-applicable')
    args=p.parse_args();src=args.source.resolve();out=args.output.resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Use a fresh output directory; prior native evidence is immutable')
    out.mkdir(parents=True,exist_ok=True)
    if hasattr(os,'sched_getaffinity'):os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
    os.environ.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',NUMEXPR_NUM_THREADS='2')
    version=importlib.metadata.version(PACKAGES[args.backend]);started=time.monotonic()
    receipt={'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'physical_page':args.page,'backend':args.backend,'package_version':version,'backend_version':version,'options':settings(args.backend),'project_revision':None,'contract_sha256':hashlib.sha256(b''.join(x.read_bytes() for x in sorted(Path(__file__).parent.glob('*.py')))).hexdigest(),'stage':'direct_parser','model':args.model,'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','tokens':None,'cost':None}
    path=out/'receipt.json';path.write_text(json.dumps(receipt,indent=2))
    try:
        raw,candidate=convert(src,args.page,args.backend,out)
        for name,data in [('raw.json',raw),('candidate.json',candidate)]:
            (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        receipt.update(status='completed',candidate=str(out/'candidate.json'),candidate_sha256=hashlib.sha256((out/'candidate.json').read_bytes()).hexdigest(),raw_sha256=hashlib.sha256((out/'raw.json').read_bytes()).hexdigest())
    except Exception as e:receipt.update(status='failed',error=f'{type(e).__name__}: {e}')
    receipt.update(elapsed_seconds=round(time.monotonic()-started,3),finished_at=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2));print(json.dumps(receipt,ensure_ascii=False));return 0 if receipt['status']=='completed' else 2


if __name__=='__main__':raise SystemExit(main())
