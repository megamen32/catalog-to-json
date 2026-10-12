"""Two bounded provider queues: extraction continues while strict review backs off."""
import asyncio
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid
from itertools import count
import pymupdf
from fast_agent.llm.model_factory import ModelFactory
from .schema import PageContent,Review
from .tools import write_json
from .provenance import program_version
from .processes import OwnedProcessTree


async def isolated_call(agents,role,source,out,page,attempt,worker_command=None):
    call=out/f'page-{page:04d}'/'calls'/uuid.uuid4().hex
    call.mkdir(parents=True);result=call/'result.json'
    args=[sys.executable,'-m','catalog_json.stage_worker','--config',str(agents.config),'--extractor',agents.extractor,'--reviewer',agents.reviewer,'--role',role,'--source',str(source),'--output',str(out),'--page',str(page),'--attempt',str(attempt),'--timeout',str(agents.timeout),'--max-tokens',str(agents.max_tokens),'--result',str(result)]
    args=[sys.executable,'-m','catalog_json.supervise','--deadline',str(agents.timeout+10),'--',*(worker_command or args)]
    with (call/'worker.log').open('w') as log:
        process=await asyncio.create_subprocess_exec(*args,stdout=log,stderr=asyncio.subprocess.STDOUT,start_new_session=True)
        tree=OwnedProcessTree(process.pid);watcher=asyncio.create_task(tree.watch())
        try:await asyncio.wait_for(process.wait(),agents.timeout+30)
        finally:
            tree.capture();watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
            await tree.cleanup();await process.wait()
    if not result.exists():raise RuntimeError(f'{role} worker exited {process.returncode} without a validated result; retained {call}')
    data=json.loads(result.read_text())
    if data['status']!='completed':raise RuntimeError(data['error'])
    return (PageContent if role=='extractor' else Review).model_validate(data['artifact'])


def validated_candidate(work,source_sha256,page,extractor,contract_sha256=None):
    events=work/'tools.jsonl'
    if not events.exists():return None
    saves=[json.loads(line) for line in events.read_text().splitlines()]
    for path in sorted(work.glob('candidate-*.json'),key=lambda p:int(p.stem.split('-')[-1]),reverse=True):
        attempt=int(path.stem.split('-')[-1]);digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if any(e.get('tool')=='save_page_json' and e.get('role')=='extractor' and e.get('model')==extractor and e.get('source_sha256')==source_sha256 and e.get('page')==page and e.get('attempt')==attempt and e.get('sha256')==digest and (contract_sha256 is None or e.get('contract_sha256')==contract_sha256) for e in saves):
            return attempt,PageContent.model_validate_json(path.read_text())
    return None


async def staged_batch(manifest,output,agents,deadline_seconds=86400,resume=False,seed=None,call=isolated_call,retry_delay=30):
    manifest=Path(manifest).resolve();output=Path(output).resolve()
    if output.exists() and any(output.iterdir()) and not resume:raise ValueError('Use a fresh staged queue or explicit resume')
    output.mkdir(parents=True,exist_ok=True)
    entries=json.loads(manifest.read_text())['catalogs'];ids=[e['id'] for e in entries]
    if not ids or len(set(ids))!=len(ids):raise ValueError('Catalogue IDs must be unique')
    version=program_version();started=time.monotonic();pending={};catalogs=[]
    workflow=hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in ('staged.py','stage_worker.py','processes.py','supervise.py'))).hexdigest()
    providers={role:ModelFactory.parse_model_spec(getattr(agents,role)).provider.value for role in ('extractor','reviewer')}
    provider_slots={name:asyncio.Semaphore(1) for name in set(providers.values())}
    extract=asyncio.PriorityQueue();review=asyncio.Queue();sequence=count()
    def enqueue_extraction(item,repair=False):extract.put_nowait((0 if repair else 1,next(sequence),item))
    for entry in entries:
        cid=entry['id']
        if not cid.replace('-','').replace('_','').isalnum():raise ValueError('Unsafe catalogue ID')
        source=(manifest.parent/entry['source']).resolve();digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest!=entry['source_sha256']:raise ValueError('Queue source digest mismatch')
        with pymupdf.open(source) as pdf:page_count=len(pdf)
        if seed and (Path(seed)/cid).exists() and not (Path(seed)/cid/'catalog.json').exists():raise ValueError('Seed catalogue lacks source/model binding')
        if seed and (Path(seed)/cid/'catalog.json').exists():
            seed_job=json.loads((Path(seed)/cid/'catalog.json').read_text())
            if seed_job.get('source',{}).get('sha256')!=digest or seed_job.get('models',{}).get('extractor')!=agents.extractor:
                raise ValueError('Seed candidates differ from source or extractor')
        out=output/cid;out.mkdir(exist_ok=True)
        if resume and (out/'catalog.json').exists():
            old_catalog=json.loads((out/'catalog.json').read_text())
            if old_catalog.get('source',{}).get('sha256')!=digest or old_catalog.get('models',{}).get('extractor')!=agents.extractor:
                raise ValueError('Resume source or extractor changed; retain old output and choose a fresh queue')
        catalog={**entry,'source':str(source),'pages':page_count,'output':str(out/'catalog.json')};catalogs.append(catalog)
        for page in range(1,page_count+1):
            work=out/f'page-{page:04d}'
            prior=Path(seed)/cid/work.name if seed else None
            if not work.exists() and prior and prior.exists():shutil.copytree(prior,work)
            work.mkdir(exist_ok=True)
            audit=work/'external-audit.json'
            key=hashlib.sha256(json.dumps({'workflow':workflow,'source':digest,'page':page,'contract':agents.contract_digest,'extractor':agents.extractor,'reviewer':agents.reviewer,'audit':hashlib.sha256(audit.read_bytes()).hexdigest() if audit.exists() else None},sort_keys=True).encode()).hexdigest()
            old=json.loads((work/'result.json').read_text()) if (work/'result.json').exists() else {}
            record={'pdf_page':page,'cache_key':key,'status':'pending','next_attempt':0,'attempts':[],'tested_program':version,'source_sha256':digest,'extractor':agents.extractor,'reviewer':agents.reviewer,'contract_sha256':agents.contract_digest,'elapsed_seconds':0}
            if old:record['prior_execution']=old
            item={'id':cid,'source':source,'out':out,'work':work,'record':record};pending[cid,page]=item
            if old.get('cache_key')==key and old.get('status')=='accepted':
                candidate=validated_candidate(work,digest,page,agents.extractor,agents.contract_digest);report_path=work/f"review-{old['next_attempt']}.json"
                saves=[json.loads(line) for line in (work/'tools.jsonl').read_text().splitlines()] if (work/'tools.jsonl').exists() else []
                review_hash=hashlib.sha256(report_path.read_bytes()).hexdigest() if report_path.exists() else None
                if candidate and candidate[0]==old['next_attempt'] and review_hash==old.get('review_sha256') and any(e.get('tool')=='save_review' and e.get('role')=='reviewer' and e.get('model')==agents.reviewer and e.get('source_sha256')==digest and e.get('page')==page and e.get('attempt')==old['next_attempt'] and e.get('sha256')==review_hash for e in saves) and Review.model_validate_json(report_path.read_text()).accepts(candidate[1]):
                    record.update(old);continue
            candidate=validated_candidate(work,digest,page,agents.extractor,agents.contract_digest)
            if candidate:
                record.update(content=candidate[1].model_dump(),next_attempt=candidate[0],status='awaiting_review');review.put_nowait(item)
            else:
                # Unbound legacy output is retained as feedback, never minted as
                # a new source/model result merely by asking another reviewer.
                prior_attempts=[int(p.stem.split('-')[-1]) for p in work.glob('candidate-*.json')]
                if prior_attempts:record['next_attempt']=max(prior_attempts)+1
                enqueue_extraction(item,repair=bool(prior_attempts))

    def snapshot():
        for cat in catalogs:
            records=[pending[cat['id'],n]['record'] for n in range(1,cat['pages']+1)]
            accepted=sum(r['status']=='accepted' for r in records)
            cat.update(accepted_pages=accepted,draft_pages=sum('content' in r for r in records),status='complete' if accepted==cat['pages'] else 'running')
            write_json(Path(cat['output']),{'schema_version':'1.0','stage':'reviewed_conversion','tested_program':version,'source':{'filename':Path(cat['source']).name,'sha256':cat['source_sha256'],'page_count':cat['pages']},'models':{'extractor':agents.extractor,'reviewer':agents.reviewer},'pages':records,'catalog_complete':accepted==cat['pages'],'complete_for_selection':accepted==cat['pages']})
        state={'schema_version':'1.0','tested_program':version,'models':{'extractor':agents.extractor,'reviewer':agents.reviewer},'contract_sha256':agents.contract_digest,'workflow_sha256':workflow,'method':{'separate_provider_queues':True,'concurrency_per_provider':1,'call_timeout_seconds':agents.timeout,'max_tokens':agents.max_tokens,'max_repairs':None,'deadline_seconds':deadline_seconds},'catalogs':catalogs,'complete':all(c['status']=='complete' for c in catalogs),'elapsed_seconds':round(time.monotonic()-started,3)}
        write_json(output/'batch.json',state);return state

    def save(item):write_json(item['work']/'result.json',item['record']);snapshot()

    async def worker(role,queue):
        failures=0
        while True:
            task=await queue.get();item=task[2] if role=='extractor' else task
            r=item['record'];attempt=r['next_attempt'];began=time.monotonic()
            try:
                r.update(status='extracting' if role=='extractor' else 'reviewing',active_role=role);save(item)
                if role=='reviewer':
                    previous=item['work']/f'review-{attempt}.json'
                    if previous.exists():
                        history=item['work']/'review-history'/hashlib.sha256(previous.read_bytes()).hexdigest();history.mkdir(parents=True,exist_ok=True);shutil.copy2(previous,history/previous.name)
                async with provider_slots[providers[role]]:
                    artifact=await call(agents,role,item['source'],item['out'],r['pdf_page'],attempt)
                failures=0
                if role=='extractor':
                    r.update(content=artifact.model_dump(),status='awaiting_review');review.put_nowait(item)
                    path=item['work']/f'candidate-{attempt}.json'
                    r['candidate_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    candidate=PageContent.model_validate(r['content']);r['review']=artifact.model_dump()
                    r['attempts'].append({'candidate':f'candidate-{attempt}.json','review':f'review-{attempt}.json'})
                    path=item['work']/f'review-{attempt}.json';r['review_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                    if artifact.accepts(candidate):r['status']='accepted'
                    else:r.update(status='needs_review',next_attempt=attempt+1);enqueue_extraction(item,repair=True)
            except asyncio.CancelledError:
                r['status']='awaiting_review' if role=='reviewer' and 'content' in r else 'pending'
                raise
            except Exception as exc:
                failures+=1;r.update(status='awaiting_review' if role=='reviewer' and 'content' in r else 'pending',last_error=f'{type(exc).__name__}: {exc}')
                r.setdefault('failures',[]).append({'role':role,'attempt':attempt,'error':r['last_error'],'time':datetime.now(timezone.utc).isoformat()})
                # Provider pacing belongs to this worker only; the other keeps running.
                save(item);await asyncio.sleep(min(900,retry_delay*2**min(failures-1,5)))
                if role=='extractor':enqueue_extraction(item,repair=attempt>0)
                else:queue.put_nowait(item)
            finally:
                r['elapsed_seconds']+=round(time.monotonic()-began,3);r.pop('active_role',None);save(item);queue.task_done()

    snapshot();workers=[asyncio.create_task(worker('extractor',extract)),asyncio.create_task(worker('reviewer',review))];interrupted=False
    try:
        async with asyncio.timeout(deadline_seconds):
            while not all(i['record']['status']=='accepted' for i in pending.values()):await asyncio.sleep(.1)
    except TimeoutError:pass
    except asyncio.CancelledError:interrupted=True
    finally:
        for task in workers:task.cancel()
        await asyncio.gather(*workers,return_exceptions=True)
    state=snapshot()
    if not state['complete']:
        for cat in catalogs:
            if cat['status']!='complete':cat['status']='checkpointed'
        state.update(status='checkpointed',interrupted=interrupted);write_json(output/'batch.json',state)
    return state
