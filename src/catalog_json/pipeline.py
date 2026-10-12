import asyncio
import hashlib
import json
from itertools import count as attempts
import time
from pathlib import Path
import pymupdf
from .tools import write_json
from .schema import PageContent,Review
from .provenance import program_version
from datetime import datetime, timezone


async def convert(source: Path,out: Path,pages: list[int],agents,max_repairs=None,resume=False,deadline_seconds=180):
    if max_repairs is not None and max_repairs<0:raise ValueError('max_repairs must be nonnegative or None')
    source=source.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    version=program_version()
    method={'stage':'reviewed_conversion','extractor':agents.extractor,'reviewer':agents.reviewer,'call_timeout_seconds':getattr(agents,'timeout',None),'max_tokens':getattr(agents,'max_tokens',None),'max_repairs':max_repairs,'deadline_seconds':deadline_seconds,'resume':resume,'contract_sha256':agents.contract_digest,'agent_plugins':getattr(agents,'plugins_provenance',[])}
    job={'tested_program':version,'test_method':method,'started_at':datetime.now(timezone.utc).isoformat(),'schema_version':'1.0','source':{'filename':source.name,'sha256':digest},'selection':pages,'models':{'extractor':agents.extractor,'reviewer':agents.reviewer},'pages':[],'complete_for_selection':False,'catalog_complete':False}
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
                    previous={**prev,'next_stage':'reviewer','next_attempt':latest}
        # Incomplete runs keep their artifacts, but are never silently reused as accepted.
        page_started=time.monotonic()
        cached=None
        record={'pdf_page':n,'cache_key':key,'status':'pending','attempts':list(previous.get('attempts',[])) if previous else [],'tested_program':version,'test_method':method,'started_at':datetime.now(timezone.utc).isoformat()}
        if previous:
            record['prior_execution']={k:previous.get(k) for k in ('tested_program','elapsed_seconds','status')}
            record['prior_elapsed_seconds']=previous.get('elapsed_seconds')
        def remaining():
            seconds=deadline_seconds-(time.monotonic()-started)
            if seconds<=0:raise TimeoutError('Job deadline exhausted; retained checkpoint')
            return seconds
        try:
            start_attempt=previous.get('next_attempt',0) if previous else 0
            if previous and max_repairs is not None and start_attempt>max_repairs:
                record={**previous,'pdf_page':n,'cache_key':key}
            for attempt in (attempts(start_attempt) if max_repairs is None else range(start_attempt,max_repairs+1)):
                record['next_attempt']=attempt
                cached=work/f'candidate-{attempt}.json'
                if previous and previous.get('next_stage')=='reviewer' and cached.exists():
                    candidate=PageContent.model_validate_json(cached.read_text())
                    events=[json.loads(l) for l in (work/'tools.jsonl').read_text().splitlines()]
                    if not any(e['tool']=='save_page_json' and e['attempt']==attempt and e.get('sha256')==hashlib.sha256(cached.read_bytes()).hexdigest() for e in events):raise ValueError('Resume candidate lacks a validated tool save')
                    record['reused_candidate']=True
                    previous=None
                else:
                    candidate=await asyncio.wait_for(agents.run('extractor',source,out,n,attempt,feedback=attempt>0),remaining())
                record.update(content=candidate.model_dump(),status='awaiting_review',next_stage='reviewer')
                write_json(receipt,record);write_json(out/'catalog.json',{**job,'pages':job['pages']+[record]})
                prior_review=work/f'review-{attempt}.json'
                if prior_review.exists():
                    history=work/'review-history'/hashlib.sha256(prior_review.read_bytes()).hexdigest()
                    history.mkdir(parents=True,exist_ok=True)
                    archived=history/prior_review.name
                    if not archived.exists():archived.write_bytes(prior_review.read_bytes())
                    record.setdefault('retained_prior_reviews',[]).append(str(archived.relative_to(work)))
                report=await asyncio.wait_for(agents.run('reviewer',source,out,n,attempt),remaining())
                record['attempts'].append({'candidate':f'candidate-{attempt}.json','review':f'review-{attempt}.json'})
                record.update(review=report.model_dump(),status='accepted' if report.accepts(candidate) else 'needs_review')
                if record['status']=='accepted':record['next_stage']='done';break
                record.update(next_stage='extractor',next_attempt=attempt+1)
                write_json(receipt,record)
        except Exception as exc:record.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        record['elapsed_seconds']=round(time.monotonic()-page_started,3)
        record['finished_at']=datetime.now(timezone.utc).isoformat()
        record['candidate_sha256']=hashlib.sha256(cached.read_bytes()).hexdigest() if cached is not None and cached.exists() else None
        write_json(receipt,record);job['pages'].append(record);write_json(out/'catalog.json',job)
        if time.monotonic()-started>=deadline_seconds:break
    job['complete_for_selection']=len(job['pages'])==len(pages) and all(p['status']=='accepted' for p in job['pages'])
    job['catalog_complete']=job['complete_for_selection'] and set(pages)==set(range(1,count+1))
    job['elapsed_seconds']=round(time.monotonic()-started,3)
    job['finished_at']=datetime.now(timezone.utc).isoformat()
    write_json(out/'catalog.json',job);return job
