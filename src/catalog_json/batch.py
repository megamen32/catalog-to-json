"""Serial bounded full-catalogue queue with durable per-catalogue checkpoints."""
import asyncio
import hashlib
import json
from pathlib import Path
import time
import pymupdf
from .pipeline import convert
from .tools import write_json
from .provenance import program_version


async def convert_batch(manifest, output, agents, resume=False, deadline_seconds=86400):
    manifest=Path(manifest).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    entries=json.loads(manifest.read_text())['catalogs']
    ids=[e['id'] for e in entries]
    if len(ids)!=len(set(ids)) or not ids:raise ValueError('Catalogue queue requires unique IDs')
    jobs=[]
    for e in entries:
        if not e['id'].replace('-','').replace('_','').isalnum():raise ValueError('Unsafe catalogue ID')
        source=(manifest.parent/e['source']).resolve()
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest!=e['source_sha256']:raise ValueError('Queue source digest mismatch')
        with pymupdf.open(source) as pdf:count=len(pdf)
        jobs.append({**e,'source':str(source),'pages':count})
    started=time.monotonic()
    state={'schema_version':'1.0','tested_program':program_version(),'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
           'models':{'extractor':agents.extractor,'reviewer':agents.reviewer},'deadline_seconds':deadline_seconds,
           'catalogs':[{**e,'status':'queued','output':str(output/e['id']/'catalog.json')} for e in jobs], 'complete':False}
    write_json(output/'batch.json',state)
    for item in state['catalogs']:
        remaining=deadline_seconds-(time.monotonic()-started)
        if remaining<=0:break
        item['status']='running';write_json(output/'batch.json',state)
        job=await convert(Path(item['source']),output/item['id'],list(range(1,item['pages']+1)),agents,resume=resume,deadline_seconds=remaining)
        item.update(status='complete' if job['catalog_complete'] else 'incomplete',
                    accepted_pages=sum(p['status']=='accepted' for p in job['pages']),processed_pages=len(job['pages']),elapsed_seconds=job['elapsed_seconds'])
        state['elapsed_seconds']=round(time.monotonic()-started,3);write_json(output/'batch.json',state)
        # A deadline checkpoint preserves subsequent queue entries; it never fabricates completion.
        if time.monotonic()-started>=deadline_seconds:break
    state['complete']=all(c['status']=='complete' for c in state['catalogs'])
    write_json(output/'batch.json',state)
    return state
