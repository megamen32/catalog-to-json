import asyncio
import hashlib
import json
import time
from pathlib import Path
import pymupdf
from .tools import write_json


async def convert(source: Path,out: Path,pages: list[int],agents,max_repairs=1,resume=False,deadline_seconds=180):
    source=source.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    job={'schema_version':'1.0','source':{'filename':source.name,'sha256':digest},'selection':pages,'models':{'extractor':agents.extractor,'reviewer':agents.reviewer},'pages':[],'complete_for_selection':False,'catalog_complete':False}
    with pymupdf.open(source) as doc:count=len(doc)
    job['source']['page_count']=count;started=time.monotonic()
    if not pages or len(set(pages))!=len(pages) or any(n<1 or n>count for n in pages):raise ValueError('Page selection is empty, repeated, or out of range')
    for n in pages:
        work=out/f'page-{n:04d}';work.mkdir(exist_ok=True)
        key=hashlib.sha256(json.dumps({'source':digest,'page':n,'models':job['models'],'contract':agents.contract_digest,'repairs':max_repairs},sort_keys=True).encode()).hexdigest()
        receipt=work/'result.json'
        if resume and receipt.exists():
            prev=json.loads(receipt.read_text())
            if prev.get('cache_key')==key and prev.get('status')=='accepted':job['pages'].append(prev);continue
        # Incomplete runs keep their artifacts, but are never silently reused as accepted.
        record={'pdf_page':n,'cache_key':key,'status':'pending','attempts':[]}
        def remaining():
            seconds=deadline_seconds-(time.monotonic()-started)
            if seconds<=0:raise TimeoutError('Job deadline exhausted; retained checkpoint')
            return seconds
        try:
            for attempt in range(max_repairs+1):
                candidate=await asyncio.wait_for(agents.run('extractor',source,out,n,attempt,feedback=attempt>0),remaining())
                record.update(content=candidate.model_dump(),status='awaiting_review')
                write_json(receipt,record);write_json(out/'catalog.json',{**job,'pages':job['pages']+[record]})
                report=await asyncio.wait_for(agents.run('reviewer',source,out,n,attempt),remaining())
                record['attempts'].append({'candidate':f'candidate-{attempt}.json','review':f'review-{attempt}.json'})
                record.update(review=report.model_dump(),status='accepted' if report.accepts(candidate) else 'needs_review')
                if record['status']=='accepted':break
        except Exception as exc:record.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        write_json(receipt,record);job['pages'].append(record);write_json(out/'catalog.json',job)
        if time.monotonic()-started>=deadline_seconds:break
    job['complete_for_selection']=len(job['pages'])==len(pages) and all(p['status']=='accepted' for p in job['pages'])
    job['catalog_complete']=job['complete_for_selection'] and set(pages)==set(range(1,count+1))
    write_json(out/'catalog.json',job);return job
