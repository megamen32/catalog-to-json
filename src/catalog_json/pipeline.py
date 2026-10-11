import asyncio
import hashlib
import json
import time
from pathlib import Path
import pymupdf
from .tools import write_json
from .schema import PageContent,Review


async def convert(source: Path,out: Path,pages: list[int],agents,max_repairs=1,resume=False,deadline_seconds=180):
    source=source.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    job={'schema_version':'1.0','source':{'filename':source.name,'sha256':digest},'selection':pages,'models':{'extractor':agents.extractor,'reviewer':agents.reviewer},'pages':[],'complete_for_selection':False,'catalog_complete':False}
    with pymupdf.open(source) as doc:count=len(doc)
    job['source']['page_count']=count;started=time.monotonic()
    prior_job=json.loads((out/'catalog.json').read_text()) if resume and (out/'catalog.json').exists() else None
    if not pages or len(set(pages))!=len(pages) or any(n<1 or n>count for n in pages):raise ValueError('Page selection is empty, repeated, or out of range')
    for n in pages:
        work=out/f'page-{n:04d}';work.mkdir(exist_ok=True)
        key=hashlib.sha256(json.dumps({'source':digest,'page':n,'models':job['models'],'contract':agents.contract_digest,'repairs':max_repairs},sort_keys=True).encode()).hexdigest()
        receipt=work/'result.json'
        previous=None
        if resume and receipt.exists():
            prev=json.loads(receipt.read_text())
            if prev.get('cache_key')==key:
                if prev.get('status')=='accepted':job['pages'].append(prev);continue
                previous=prev
            elif prior_job and prior_job.get('source',{}).get('sha256')==digest and prior_job.get('models',{}).get('extractor')==agents.extractor:
                # A changed reviewer/contract must re-audit; a validated source-bound extraction remains a useful candidate.
                candidates=sorted(work.glob('candidate-*.json'),key=lambda p:int(p.stem.split('-')[-1]))
                if candidates:
                    latest=int(candidates[-1].stem.split('-')[-1])
                    previous={'next_stage':'reviewer','next_attempt':latest}
        # Incomplete runs keep their artifacts, but are never silently reused as accepted.
        record={'pdf_page':n,'cache_key':key,'status':'pending','attempts':[]}
        def remaining():
            seconds=deadline_seconds-(time.monotonic()-started)
            if seconds<=0:raise TimeoutError('Job deadline exhausted; retained checkpoint')
            return seconds
        try:
            start_attempt=previous.get('next_attempt',0) if previous else 0
            for attempt in range(start_attempt,max_repairs+1):
                record['next_attempt']=attempt
                cached=work/f'candidate-{attempt}.json'
                if previous and previous.get('next_stage')=='reviewer' and cached.exists():
                    candidate=PageContent.model_validate_json(cached.read_text())
                    events=[json.loads(l) for l in (work/'tools.jsonl').read_text().splitlines()]
                    if not any(e['tool']=='save_page_json' and e['attempt']==attempt and e.get('sha256')==hashlib.sha256(cached.read_bytes()).hexdigest() for e in events):raise ValueError('Resume candidate lacks a validated tool save')
                    previous=None
                else:
                    candidate=await asyncio.wait_for(agents.run('extractor',source,out,n,attempt,feedback=attempt>0),remaining())
                record.update(content=candidate.model_dump(),status='awaiting_review',next_stage='reviewer')
                write_json(receipt,record);write_json(out/'catalog.json',{**job,'pages':job['pages']+[record]})
                report=await asyncio.wait_for(agents.run('reviewer',source,out,n,attempt),remaining())
                record['attempts'].append({'candidate':f'candidate-{attempt}.json','review':f'review-{attempt}.json'})
                record.update(review=report.model_dump(),status='accepted' if report.accepts(candidate) else 'needs_review')
                if record['status']=='accepted':record['next_stage']='done';break
                record.update(next_stage='extractor',next_attempt=attempt+1)
                write_json(receipt,record)
        except Exception as exc:record.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        write_json(receipt,record);job['pages'].append(record);write_json(out/'catalog.json',job)
        if time.monotonic()-started>=deadline_seconds:break
    job['complete_for_selection']=len(job['pages'])==len(pages) and all(p['status']=='accepted' for p in job['pages'])
    job['catalog_complete']=job['complete_for_selection'] and set(pages)==set(range(1,count+1))
    write_json(out/'catalog.json',job);return job
