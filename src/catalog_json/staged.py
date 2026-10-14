"""Two bounded provider queues: extraction continues while strict review backs off."""
import asyncio
from datetime import datetime,timezone
import hashlib
import json
import re
from pathlib import Path
import shutil
import sys
import time
import uuid
from itertools import count
from collections import deque
from types import SimpleNamespace
import pymupdf
from fast_agent.llm.model_factory import ModelFactory
from .schema import PageContent,Review
from .tools import write_json,durable_directory
from .provenance import program_version,artifact_origin
from .processes import OwnedProcessTree
from .fair_queue import FairWorkQueue,REVIEW_ORDER
from .manual_review import source_review_update


RATE_LIMIT=re.compile(r'(?:HTTP(?:/\d(?:\.\d)?)?[^\n]{0,100}\b429\b|Error\s+code:\s*429\b|RateLimitError|rate[ _-]limit(?:ed| error| exceeded| reached)|Too Many Requests)',re.I)


async def observe_worker_rate_limits(log,receipt,callback,seen=None):
    """Observe exposed SDK retries without exposing logs or replaying successful calls."""
    seen=set() if seen is None else seen
    if not log.exists():return seen
    for number,line in enumerate(log.read_text(errors='replace').splitlines()):
        try:structured=json.loads(line)
        except json.JSONDecodeError:structured={}
        typed=isinstance(structured,dict) and structured.get('catalog_worker_event')=='provider_rate_limit' and structured.get('http_status')==429
        if number not in seen and (typed or RATE_LIMIT.search(line)):
            seen.add(number)
            with receipt.open('a') as stream:
                stream.write(json.dumps({'time':time.time(),'signal':'provider_rate_limit','worker_log_line':number+1,'line_sha256':hashlib.sha256(line.encode()).hexdigest()})+'\n')
            await callback()
    return seen


class ProviderGate:
    """Finite configured capacity with provider-wide pacing after rate limits."""
    def __init__(self,limit,retry_delay,initial=None):
        self.maximum=limit;self.limit=min(limit,initial) if initial is not None else limit;self.retry_delay=retry_delay
        self.active=0;self.cooldown=0;self.operator_not_before=0;self.rate_limit_count=0;self.rate_limit_waves=0;self.backoff_streak=0;self.clean_successes=0;self.successes=0
        self.condition=asyncio.Condition();self.waiters=deque()

    async def __aenter__(self):
        token=object()
        async with self.condition:
            self.waiters.append(token)
            try:
                while True:
                    delay=max(self.cooldown-time.monotonic(),self.operator_not_before-time.time())
                    if self.waiters[0] is token and self.active<self.limit and delay<=0:
                        self.waiters.popleft();self.active+=1;self.condition.notify_all();return self
                    try:await asyncio.wait_for(self.condition.wait(),delay) if delay>0 else await self.condition.wait()
                    except TimeoutError:pass
            except BaseException:
                self.waiters.remove(token);self.condition.notify_all();raise

    async def __aexit__(self,*args):
        async with self.condition:self.active-=1;self.condition.notify_all()

    async def rate_limited(self):
        async with self.condition:
            self.rate_limit_count+=1;self.successes=0;self.clean_successes=0;now=time.monotonic()
            if now>=self.cooldown:
                self.rate_limit_waves+=1;self.backoff_streak+=1;self.limit=max(1,self.limit//2)
                self.cooldown=now+min(900,self.retry_delay*2**min(self.backoff_streak-1,5))
            self.condition.notify_all()

    async def succeeded(self,rate_limit_count=None):
        async with self.condition:
            # A recovered SDK retry is a completed artifact, not evidence of clean capacity.
            if rate_limit_count is not None and rate_limit_count!=self.rate_limit_count:
                self.successes=0;self.clean_successes=0;return
            self.clean_successes=min(4,self.clean_successes+1)
            if self.clean_successes==4:self.backoff_streak=0
            self.successes+=1
            if self.successes>=max(4,self.limit*2):self.limit=min(self.maximum,self.limit+1);self.successes=0
            self.condition.notify_all()

    async def hold_until(self,not_before):
        async with self.condition:
            self.operator_not_before=not_before;self.condition.notify_all()

    def restore(self,state,elapsed=0):
        """Restore admission only; native active calls were checkpointed/cleaned."""
        maximum=state.get('configured_maximum');limit=state.get('current_limit')
        signals=state.get('rate_limit_count',0);waves=state.get('rate_limit_waves',0)
        remaining=state.get('backoff_remaining_seconds',0);streak=state.get('backoff_streak',waves);clean=state.get('clean_successes',0)
        if (any(type(n) is not int for n in (maximum,limit,signals,waves,streak,clean)) or
                not 1<=limit<=maximum<=16 or not 0<=streak<=waves<=signals or not 0<=clean<=4 or (clean==4 and streak!=0) or
                type(remaining) not in (int,float) or not 0<=remaining<=900):
            raise ValueError('Invalid provider pacing checkpoint')
        self.limit=min(self.maximum,limit);self.rate_limit_count=signals;self.rate_limit_waves=waves;self.backoff_streak=streak;self.clean_successes=clean
        self.cooldown=time.monotonic()+max(0,remaining-max(0,elapsed))

    def snapshot(self):
        return {'configured_maximum':self.maximum,'current_limit':self.limit,
                'active_calls':self.active,'waiting_calls':len(self.waiters),'rate_limit_count':self.rate_limit_count,
                'rate_limit_waves':self.rate_limit_waves,'backoff_streak':self.backoff_streak,'clean_successes':self.clean_successes,
                'operator_not_before_unix':self.operator_not_before,
                'operator_hold_remaining_seconds':max(0,round(self.operator_not_before-time.time(),3)),
                'backoff_remaining_seconds':max(0,round(self.cooldown-time.monotonic(),3))}


def operator_holds(path,agents,providers):
    if path is None or not Path(path).exists():return {},None
    raw=Path(path).read_bytes();data=json.loads(raw)
    if not isinstance(data,dict) or data.get('schema_version')!='1.0' or not isinstance(data.get('providers'),dict):
        raise ValueError('Invalid provider hold file')
    result={}
    for name,hold in data['providers'].items():
        if name not in set(providers.values()) or not isinstance(hold,dict):raise ValueError('Unknown held provider')
        models={getattr(agents,role) for role,provider in providers.items() if provider==name}
        until=hold.get('not_before_unix')
        if hold.get('model') not in models:raise ValueError('Provider hold belongs to another model')
        if type(until) not in (int,float) or not 0<=until<=time.time()+86400:raise ValueError('Provider hold must be a finite Unix deadline within 24 hours')
        result[name]=until
    return result,hashlib.sha256(raw).hexdigest()


def role_contract(agents,role):
    return getattr(agents,'role_contracts',{}).get(role,agents.contract_digest)


def load_role_runtimes(agents,path):
    """Explicit pinned native role runtimes; no implicit provider/runtime fallback."""
    routes=json.loads(Path(path).read_text())
    if set(routes.get('roles',{}))!={'extractor','reviewer'}:raise ValueError('Provide both explicit role runtimes')
    def validate(role_routes):
        if set(role_routes)!={'extractor','reviewer'}:raise ValueError('Provide both explicit role runtimes')
        for route in role_routes.values():
            if not route.get('contract_sha256') or not route.get('file_sha256') or not route.get('program',{}).get('source_code_sha256'):
                raise ValueError('Role runtime requires actual program, contract and file pins')
            for name,digest in route['file_sha256'].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise ValueError('Pinned role runtime changed')
    validate(routes['roles'])
    agents.role_runtimes=routes['roles'];agents.role_contracts={r:v['contract_sha256'] for r,v in routes['roles'].items()}
    agents.contract_digest=hashlib.sha256(json.dumps(agents.role_contracts,sort_keys=True).encode()).hexdigest()
    agents.accepted_predecessor_profiles=[]
    agents.candidate_predecessor_profiles=[]
    for destination,previous in [(name,p) for name in ('accepted_predecessor_profiles','candidate_predecessor_profiles') for p in routes.get(name,[])]:
        if previous.get('models')!={'extractor':agents.extractor,'reviewer':agents.reviewer}:
            raise ValueError('Accepted predecessor models must match; no provider fallback')
        validate(previous['roles'])
        contracts={r:v['contract_sha256'] for r,v in previous['roles'].items()}
        getattr(agents,destination).append(SimpleNamespace(extractor=agents.extractor,reviewer=agents.reviewer,
            role_contracts=contracts,role_runtimes=previous['roles'],
            contract_digest=hashlib.sha256(json.dumps(contracts,sort_keys=True).encode()).hexdigest()))
    return agents


def validate_role_receipt(data,work,path,source_sha256,page,attempt,role,model,contract,program=None):
    execution=data.get('execution',{});digest=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    expected={'source_sha256':source_sha256,'physical_page':page,'attempt':attempt,'role':role,
              'model':model,'contract_sha256':contract,'artifact_sha256':digest}
    if not digest or not execution.get('program') or any(execution.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Native role receipt does not match the source-bound saved artifact')
    if program is not None and execution['program']!=program:raise RuntimeError('Native role producer differs from pinned program')
    origin=artifact_origin(work,path,source_sha256,page,attempt,role,model,contract)
    if origin['status']!='receipt_verified':raise RuntimeError('Native role receipt lacks its latest validated save-event')
    schema=PageContent if role=='extractor' else Review
    if schema.model_validate(data['artifact']).model_dump()!=schema.model_validate_json(path.read_text()).model_dump():
        raise RuntimeError('Native worker returned different artifact content')
    return origin


def compatible_reviewed_profile(work,old,agents,source_sha256,page,attempt):
    """Exact paired artifact and audit binding, independent of the review verdict."""
    roles={role:role_contract(agents,role) for role in ('extractor','reviewer')}
    if any(old.get(k)!=v for k,v in {'pdf_page':page,'source_sha256':source_sha256,
            'extractor':agents.extractor,'reviewer':agents.reviewer,'contract_sha256':agents.contract_digest,'role_contracts':roles}.items()):return False
    candidate=work/f'candidate-{attempt}.json';review=work/f'review-{attempt}.json'
    origins={role:artifact_origin(work,path,source_sha256,page,attempt,role,getattr(agents,role),roles[role]) for role,path in [('extractor',candidate),('reviewer',review)]}
    if any(o['status']!='receipt_verified' for o in origins.values()):return False
    candidate_hash=old.get('candidate_sha256')
    if candidate_hash is None and old.get('candidate_producer')==origins['extractor']:
        candidate_hash=origins['extractor']['artifact_sha256']
    if candidate_hash!=origins['extractor']['artifact_sha256'] or old.get('review_sha256')!=origins['reviewer']['artifact_sha256']:return False
    if json.loads(candidate.read_text())!=old.get('content'):return False
    events=[json.loads(l) for l in (work/'tools.jsonl').read_text().splitlines()]
    observed=[e for e in events if e.get('tool')=='read_external_audit' and e.get('role')=='reviewer'
              and e.get('page')==page and e.get('attempt')==attempt and e.get('source_sha256')==source_sha256
              and e.get('model')==agents.reviewer and e.get('contract_sha256')==roles['reviewer']
              and origins['reviewer']['started_at']<=e.get('time',0)<=origins['reviewer']['finished_at']]
    audit=work/'external-audit.json';digest=hashlib.sha256(audit.read_bytes()).hexdigest() if audit.exists() else None
    return (observed[-1].get('sha256') if observed else None)==digest


def compatible_accepted_profile(work,old,agents,source_sha256,page):
    if old.get('status')!='accepted' or type(old.get('next_attempt')) is not int:return False
    if not compatible_reviewed_profile(work,old,agents,source_sha256,page,old['next_attempt']):return False
    digest=hashlib.sha256((work/f"candidate-{old['next_attempt']}.json").read_bytes()).hexdigest()
    return source_audit_rejection(work,source_sha256,page,digest) is None


def accepted_profile_agents(work,old,agents,source_sha256,page):
    """Reuse only explicit historical acceptance; preserve its actual native producers."""
    for profile in [agents,*getattr(agents,'accepted_predecessor_profiles',[])]:
        if not compatible_accepted_profile(work,old,profile,source_sha256,page):continue
        if profile is not agents:
            attempt=old['next_attempt']
            # A newly saved attempt/contract supersedes a historical acceptance,
            # even if someone later restores its old bytes or stale metadata.
            attempts=[int(p.stem.split('-')[-1]) for p in work.glob('candidate-*.json')]
            if not attempts or max(attempts)!=attempt:continue
            events=[json.loads(line) for line in (work/'tools.jsonl').read_text().splitlines()]
            superseded=False
            for role,kind,tool in [('extractor','candidate','save_page_json'),('reviewer','review','save_review')]:
                saves=[e for e in events if e.get('tool')==tool and all(e.get(k)==v for k,v in
                    {'source_sha256':source_sha256,'page':page,'attempt':attempt,'role':role,'model':getattr(agents,role)}.items())]
                digest=hashlib.sha256((work/f'{kind}-{attempt}.json').read_bytes()).hexdigest()
                if not saves or saves[-1].get('contract_sha256')!=role_contract(profile,role) or saves[-1].get('sha256')!=digest:
                    superseded=True;break
            if superseded:continue
            origins={role:artifact_origin(work,work/f'{kind}-{attempt}.json',source_sha256,page,attempt,role,
                    getattr(profile,role),role_contract(profile,role))
                    for role,kind in [('extractor','candidate'),('reviewer','review')]}
            if any(origin['program']!=profile.role_runtimes[role]['program'] for role,origin in origins.items()):continue
        return profile
    return None


def source_audit_rejection(work,source_sha256,page,candidate_sha256):
    """An explicit independent source finding can veto only its exact audited bytes.

    This is a parent decision, not an alteration of the native model's report.
    Different bytes still require all ordinary source and review checks.
    """
    path=work/'external-audit.json'
    if not path.exists():return None
    raw=path.read_bytes();audit=json.loads(raw)
    if not isinstance(audit,dict):raise ValueError('Invalid independent source audit')
    if 'rejected_candidate_sha256' not in audit:return None
    hashes=audit['rejected_candidate_sha256']
    if (audit.get('source_sha256')!=source_sha256 or type(audit.get('pdf_page')) is not int or audit['pdf_page']!=page or
            not isinstance(hashes,list) or not hashes or
            any(not isinstance(h,str) or re.fullmatch(r'[0-9a-f]{64}',h) is None for h in hashes) or
            not isinstance(audit.get('findings'),list) or not audit['findings']):
        raise ValueError('Rejected candidate hashes require exact source/page and nonempty independent findings')
    if candidate_sha256 not in hashes:return None
    return {'candidate_sha256':candidate_sha256,'audit_sha256':hashlib.sha256(raw).hexdigest(),
            'reason':'Independent source audit rejects these exact candidate bytes; native source-bound repair is required'}


def external_audit_digest(work):
    path=work/'external-audit.json'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def reviewed_audit_digest(item,agents):
    """Only a read made during the actual bound review certifies current leads."""
    r=item['record'];origin=r.get('review_producer',{});events=item['work']/'tools.jsonl'
    if origin.get('status')!='receipt_verified' or not events.exists():return None
    matching=[e for e in (json.loads(line) for line in events.read_text().splitlines())
              if e.get('tool')=='read_external_audit' and e.get('role')=='reviewer'
              and e.get('page')==r['pdf_page'] and e.get('attempt')==r['next_attempt']
              and e.get('source_sha256')==r['source_sha256'] and e.get('model')==agents.reviewer
              and e.get('contract_sha256')==role_contract(agents,'reviewer')
              and origin['started_at']<=e.get('time',0)<=origin['finished_at']]
    return matching[-1].get('sha256') if matching else None


async def isolated_call(agents,role,source,out,page,attempt,worker_command=None):
    call=out/f'page-{page:04d}'/'calls'/uuid.uuid4().hex
    call.mkdir(parents=True);result=call/'result.json'
    route=getattr(agents,'role_runtimes',{}).get(role,{})
    for name,digest in route.get('file_sha256',{}).items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise ValueError('Pinned role runtime changed before call')
    timeout=route.get('timeout',agents.timeout)
    prefix=route.get('command_prefix',[sys.executable,'-m','catalog_json.stage_worker'])
    args=[*prefix,'--config',str(route.get('config',agents.config)),'--extractor',agents.extractor,'--reviewer',agents.reviewer,'--role',role,'--source',str(source),'--output',str(out),'--page',str(page),'--attempt',str(attempt),'--timeout',str(timeout),'--max-tokens',str(agents.max_tokens),'--result',str(result)]
    args=[sys.executable,'-m','catalog_json.supervise','--deadline',str(timeout+10),'--',*(worker_command or args)]
    environment=dict(__import__('os').environ)
    for name in route.get('unset_environment',[]):environment.pop(name,None)
    environment.update(route.get('environment',{}))
    with (call/'worker.log').open('w') as log:
        process=await asyncio.create_subprocess_exec(*args,env=environment,stdout=log,stderr=asyncio.subprocess.STDOUT,start_new_session=True)
        tree=OwnedProcessTree(process.pid);watcher=asyncio.create_task(tree.watch())
        rate_seen=set();observer=getattr(agents,'rate_limit_observer',None)
        async def scan_rates():
            nonlocal rate_seen
            if observer:rate_seen=await observe_worker_rate_limits(call/'worker.log',call/'rate-limits.jsonl',lambda:observer(role),rate_seen)
        async def watch_rates():
            while True:await scan_rates();await asyncio.sleep(1)
        rate_watcher=asyncio.create_task(watch_rates())
        try:await asyncio.wait_for(process.wait(),timeout+30)
        finally:
            tree.capture();watcher.cancel();rate_watcher.cancel();await asyncio.gather(watcher,rate_watcher,return_exceptions=True)
            await scan_rates()
            await tree.cleanup();await process.wait()
    if not result.exists():raise RuntimeError(f'{role} worker exited {process.returncode} without a validated result; retained {call}')
    data=json.loads(result.read_text())
    if data['status']!='completed':raise RuntimeError(data['error'])
    if route:
        artifact=out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json')
        validate_role_receipt(data,artifact.parent,artifact,hashlib.sha256(Path(source).read_bytes()).hexdigest(),page,attempt,role,getattr(agents,role),role_contract(agents,role),route.get('program'))
    return (PageContent if role=='extractor' else Review).model_validate(data['artifact'])


def validated_candidate(work,source_sha256,page,extractor,contract_sha256=None):
    events=work/'tools.jsonl'
    if not events.exists():return None
    saves=[json.loads(line) for line in events.read_text().splitlines()]
    for path in sorted(work.glob('candidate-*.json'),key=lambda p:int(p.stem.split('-')[-1]),reverse=True):
        attempt=int(path.stem.split('-')[-1]);digest=hashlib.sha256(path.read_bytes()).hexdigest()
        bound=[e for e in saves if e.get('tool')=='save_page_json' and e.get('role')=='extractor' and e.get('model')==extractor and e.get('source_sha256')==source_sha256 and e.get('page')==page and e.get('attempt')==attempt and (contract_sha256 is None or e.get('contract_sha256')==contract_sha256)]
        if bound and bound[-1].get('sha256')==digest:
            return attempt,PageContent.model_validate_json(path.read_text())
    return None


async def staged_batch(manifest,output,agents,deadline_seconds=86400,resume=False,seed=None,call=isolated_call,retry_delay=30,extractor_workers=1,reviewer_workers=1,initial_provider_concurrency=None,resume_compatible_profile=False,provider_holds=None):
    if any(type(n) is not int or n<1 or n>16 for n in (extractor_workers,reviewer_workers)):
        raise ValueError('Role workers must be integers from 1 to 16; choose them within the measured job budget')
    if initial_provider_concurrency is not None and (type(initial_provider_concurrency) is not int or not 1<=initial_provider_concurrency<=16):
        raise ValueError('Initial provider concurrency must be an integer from 1 to 16')
    manifest=Path(manifest).resolve();output=Path(output).resolve()
    if output.exists() and any(output.iterdir()) and not resume:raise ValueError('Use a fresh staged queue or explicit resume')
    durable_directory(output)
    pacing_path=output/'batch.json'
    pacing_state=json.loads(pacing_path.read_text()) if resume and resume_compatible_profile and pacing_path.exists() else None
    pacing_modified=pacing_path.stat().st_mtime if pacing_state else None
    entries=json.loads(manifest.read_text())['catalogs'];ids=[e['id'] for e in entries]
    if not ids or len(set(ids))!=len(ids):raise ValueError('Catalogue IDs must be unique')
    version=program_version();started=time.monotonic();pending={};catalogs=[]
    workflow=hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in ('staged.py','stage_worker.py','processes.py','supervise.py','fair_queue.py'))).hexdigest()
    providers={role:ModelFactory.parse_model_spec(getattr(agents,role)).provider.value for role in ('extractor','reviewer')}
    role_counts={'extractor':extractor_workers,'reviewer':reviewer_workers}
    provider_slots={name:ProviderGate(max(role_counts[role] for role in providers if providers[role]==name),retry_delay,initial_provider_concurrency) for name in set(providers.values())}
    async def observe_rate_limit(role):await provider_slots[providers[role]].rate_limited()
    agents.rate_limit_observer=observe_rate_limit
    policy_path=output/'queue-policy.json'
    if policy_path.exists():
        policy=json.loads(policy_path.read_text())
        if type(policy.get('seed')) is not str or not policy['seed']:raise ValueError('Invalid queue random seed')
    else:
        policy={'seed':uuid.uuid4().hex,'order':REVIEW_ORDER};write_json(policy_path,policy)
    extract=FairWorkQueue(ids);review=FairWorkQueue(ids,seed=policy['seed']);sequence=count()
    def enqueue_extraction(item,repair=False,fresh=False):
        extract.put_nowait((2 if fresh else 0 if repair else 1,next(sequence),item))
    def enqueue_review(item,audit=False,fresh=False):
        repair=audit or bool(item['record'].get('review') or item['record'].get('attempts') or item.get('has_prior_review'))
        review.put_nowait((2 if fresh else 0 if repair else 1,next(sequence),item))
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
            record={'pdf_page':page,'cache_key':key,'status':'pending','next_attempt':0,'attempts':[],'tested_program':version,'source_sha256':digest,'extractor':agents.extractor,'reviewer':agents.reviewer,'contract_sha256':agents.contract_digest,'role_contracts':{role:role_contract(agents,role) for role in providers},'elapsed_seconds':0}
            if old:record['prior_execution']=old
            item={'id':cid,'source':source,'out':out,'work':work,'record':record,'reviewed_audit':external_audit_digest(work),
                  'has_prior_review':bool(old.get('review') or old.get('attempts') or list(work.glob('review-*.json')))};pending[cid,page]=item
            accepted_profile=accepted_profile_agents(work,old,agents,digest,page) if not old.get('manual_source_review') and old.get('status')=='accepted' and (old.get('cache_key')==key or resume_compatible_profile) else None
            if accepted_profile is not None:
                candidate=validated_candidate(work,digest,page,agents.extractor,role_contract(accepted_profile,'extractor'));report_path=work/f"review-{old['next_attempt']}.json"
                saves=[json.loads(line) for line in (work/'tools.jsonl').read_text().splitlines()] if (work/'tools.jsonl').exists() else []
                review_hash=hashlib.sha256(report_path.read_bytes()).hexdigest() if report_path.exists() else None
                if candidate and candidate[0]==old['next_attempt'] and review_hash==old.get('review_sha256') and artifact_origin(work,report_path,digest,page,old['next_attempt'],'reviewer',agents.reviewer,role_contract(accepted_profile,'reviewer'))['source_bound_save'] and Review.model_validate_json(report_path.read_text()).accepts(candidate[1]):
                    record.update(old)
                    record['candidate_producer']=artifact_origin(work,work/f'candidate-{candidate[0]}.json',digest,page,candidate[0],'extractor',agents.extractor,role_contract(accepted_profile,'extractor'))
                    record['review_producer']=artifact_origin(work,report_path,digest,page,old['next_attempt'],'reviewer',agents.reviewer,role_contract(accepted_profile,'reviewer'))
                    record['candidate_sha256']=record['candidate_producer']['artifact_sha256']
                    record['cache_key']=key
                    record['runner_resume']={'program':version,'primary_contract_sha256':agents.contract_digest,
                        'accepted_artifact_contract_sha256':accepted_profile.contract_digest,'fresh_model_call':False}
                    continue
            candidate=validated_candidate(work,digest,page,agents.extractor,role_contract(agents,'extractor'))
            candidate_profile=agents
            if candidate is None and resume_compatible_profile:
                for previous in getattr(agents,'candidate_predecessor_profiles',[]):
                    retained=validated_candidate(work,digest,page,agents.extractor,role_contract(previous,'extractor'))
                    if retained is None:continue
                    path=work/f'candidate-{retained[0]}.json'
                    origin=artifact_origin(work,path,digest,page,retained[0],'extractor',agents.extractor,role_contract(previous,'extractor'))
                    if origin['status']=='receipt_verified' and origin['program']==previous.role_runtimes['extractor']['program']:
                        candidate=retained;candidate_profile=previous;break
            if candidate:
                record.update(content=candidate[1].model_dump(),next_attempt=candidate[0],status='awaiting_review')
                record['candidate_producer']=artifact_origin(work,work/f'candidate-{candidate[0]}.json',digest,page,candidate[0],'extractor',agents.extractor,role_contract(candidate_profile,'extractor'))
                if candidate_profile is not agents:
                    record['role_contracts']['extractor']=role_contract(candidate_profile,'extractor')
                    record['contract_sha256']=hashlib.sha256(json.dumps(record['role_contracts'],sort_keys=True).encode()).hexdigest()
                    record['retained_extraction']={'fresh_model_call':False,'extractor_contract_sha256':role_contract(candidate_profile,'extractor'),
                        'review_required':True,'reason':'Explicit receipt-verified predecessor extraction; current independent reviewer must verify it'}
                record['candidate_sha256']=record['candidate_producer']['artifact_sha256']
                root_review=source_review_update(work,record)
                if root_review is not None:
                    record.update(root_review);continue
                rejection=source_audit_rejection(work,digest,page,record['candidate_sha256'])
                if rejection:
                    record.update(status='needs_review',next_attempt=candidate[0]+1,source_audit_rejection=rejection,
                                  attempts=[dict(a) for a in old.get('attempts',[])])
                    enqueue_extraction(item,repair=True,fresh=True);continue
                if (resume_compatible_profile and old.get('status')!='accepted' and
                        type(old.get('next_attempt')) is int and old.get('next_attempt')==candidate[0]+1 and
                        compatible_reviewed_profile(work,old,agents,digest,page,candidate[0])):
                    report_path=work/f'review-{candidate[0]}.json';feedback=Review.model_validate_json(report_path.read_text())
                    if not feedback.accepts(candidate[1]):
                        record.update(status='needs_review',next_attempt=candidate[0]+1,review=feedback.model_dump(),
                                      review_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
                                      review_producer=artifact_origin(work,report_path,digest,page,candidate[0],'reviewer',agents.reviewer,role_contract(agents,'reviewer')),
                                      attempts=[dict(a) for a in old.get('attempts',[])],repair_feedback_reused=True)
                        enqueue_extraction(item,repair=True,fresh=True);continue
                # A candidate written after the last completed review is a
                # fresh repair even after a process/version handover.
                cp=work/f'candidate-{candidate[0]}.json'
                previous_reviews=list(work.glob('review-*.json'))
                fresh=bool(candidate[0]>0 and previous_reviews and cp.stat().st_mtime>max(p.stat().st_mtime for p in previous_reviews))
                enqueue_review(item,audit=audit.exists(),fresh=fresh or audit.exists())
            else:
                # Unbound legacy output is retained as feedback, never minted as
                # a new source/model result merely by asking another reviewer.
                prior_attempts=[int(p.stem.split('-')[-1]) for p in work.glob('candidate-*.json')]
                if prior_attempts:record['next_attempt']=max(prior_attempts)+1
                enqueue_extraction(item,repair=bool(prior_attempts))

    if pacing_state:
        identity=lambda entries:{(c['id'],c['source_sha256']) for c in entries}
        allowed_contracts={p.contract_digest for p in [agents,*getattr(agents,'accepted_predecessor_profiles',[])]}
        if (pacing_state.get('contract_sha256') in allowed_contracts and
                pacing_state.get('models')=={'extractor':agents.extractor,'reviewer':agents.reviewer} and
                identity(pacing_state.get('catalogs',[]))==identity(catalogs)):
            for name,state in pacing_state.get('method',{}).get('provider_pacing',{}).items():
                if name in provider_slots:provider_slots[name].restore(state,time.time()-pacing_modified)

    holds_digest=None;snapshot_digests={}

    def snapshot():
        for cat in catalogs:
            records=[pending[cat['id'],n]['record'] for n in range(1,cat['pages']+1)]
            accepted=sum(r['status']=='accepted' for r in records)
            cat.update(accepted_pages=accepted,draft_pages=sum('content' in r for r in records),status='complete' if accepted==cat['pages'] else 'running')
            payload={'schema_version':'1.0','stage':'reviewed_conversion','tested_program':version,'source':{'filename':Path(cat['source']).name,'sha256':cat['source_sha256'],'page_count':cat['pages']},'models':{'extractor':agents.extractor,'reviewer':agents.reviewer},'pages':records,'catalog_complete':accepted==cat['pages'],'complete_for_selection':accepted==cat['pages']}
            digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()
            if snapshot_digests.get(cat['id'])!=digest:
                write_json(Path(cat['output']),payload);snapshot_digests[cat['id']]=digest
        state={'schema_version':'1.0','tested_program':version,'models':{'extractor':agents.extractor,'reviewer':agents.reviewer},'contract_sha256':agents.contract_digest,'workflow_sha256':workflow,'method':{'separate_provider_queues':True,'review_order':REVIEW_ORDER,'queue_random_seed':policy['seed'],'concurrency_per_provider':max(role_counts.values()),'role_workers':role_counts,'provider_pacing':{name:slot.snapshot() for name,slot in provider_slots.items()},'operator_holds_sha256':holds_digest,'call_timeout_seconds':agents.timeout,'max_tokens':agents.max_tokens,'max_repairs':None,'deadline_seconds':deadline_seconds},'catalogs':catalogs,'complete':all(c['status']=='complete' for c in catalogs),'elapsed_seconds':round(time.monotonic()-started,3)}
        write_json(output/'batch.json',state);return state

    def save(item):write_json(item['work']/'result.json',item['record']);snapshot()


    async def refresh_holds():
        nonlocal holds_digest
        holds,digest=operator_holds(provider_holds,agents,providers)
        if digest!=holds_digest:
            for name,slot in provider_slots.items():await slot.hold_until(holds.get(name,0))
            holds_digest=digest;snapshot()

    async def worker(role,queue):
        failures=0
        while True:
            task=await queue.get();item=task[2]
            r=item['record'];attempt=r['next_attempt'];began=time.monotonic()
            try:
                if r['status']=='accepted':continue
                r.update(status='awaiting_provider_admission',active_role=role);save(item)
                async with provider_slots[providers[role]]:
                    preferred=queue.at_admission(task)
                    if preferred is not task:
                        r.update(status='awaiting_review' if role=='reviewer' else 'needs_review' if 'content' in r else 'pending');r.pop('active_role',None)
                        r['elapsed_seconds']+=round(time.monotonic()-began,3);save(item)
                        task=preferred;item=task[2];r=item['record'];attempt=r['next_attempt'];began=time.monotonic()
                        r['active_role']=role
                    if r['status']=='accepted':continue
                    if role=='reviewer':
                        root_review=source_review_update(item['work'],r)
                        if root_review is not None:
                            r.update(root_review);item['reviewed_audit']=external_audit_digest(item['work']);continue
                        rejection=source_audit_rejection(item['work'],r['source_sha256'],r['pdf_page'],r.get('candidate_sha256'))
                        if rejection:
                            r['attempts'].append({'candidate':f'candidate-{attempt}.json','review':None,
                                'source_audit_rejected':True,'review_skipped':True})
                            r.update(status='needs_review',next_attempt=attempt+1,source_audit_rejection=rejection)
                            enqueue_extraction(item,repair=True,fresh=True)
                            continue  # Reject known bad bytes before spending a reviewer call.
                        previous=item['work']/f'review-{attempt}.json'
                        if previous.exists():
                            history=item['work']/'review-history'/hashlib.sha256(previous.read_bytes()).hexdigest();history.mkdir(parents=True,exist_ok=True);shutil.copy2(previous,history/previous.name)
                    r['status']='extracting' if role=='extractor' else 'reviewing'
                    r['last_admission']={'role':role,'lane':'fresh_repair' if task[0]==2 else 'repair' if task[0]==0 else 'first_pass',
                        'selected_unix':time.time(),'queue_random_seed':policy['seed'] if role=='reviewer' else None}
                    save(item)
                    rate_before=provider_slots[providers[role]].rate_limit_count
                    artifact=await call(agents,role,item['source'],item['out'],r['pdf_page'],attempt)
                await provider_slots[providers[role]].succeeded(rate_limit_count=rate_before)
                failures=0
                if role=='extractor':
                    r.update(content=artifact.model_dump(),status='awaiting_review',tested_program=version,
                        contract_sha256=agents.contract_digest,role_contracts={role:role_contract(agents,role) for role in providers})
                    r.pop('runner_resume',None);enqueue_review(item,fresh=attempt>0)
                    path=item['work']/f'candidate-{attempt}.json'
                    r['candidate_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                    r['candidate_producer']=artifact_origin(item['work'],path,r['source_sha256'],r['pdf_page'],attempt,role,agents.extractor,role_contract(agents,'extractor'))
                else:
                    candidate=PageContent.model_validate(r['content']);r['review']=artifact.model_dump()
                    r['reviewer']=agents.reviewer;r.pop('manual_source_review',None)
                    rejection=source_audit_rejection(item['work'],r['source_sha256'],r['pdf_page'],r['candidate_sha256'])
                    r['attempts'].append({'candidate':f'candidate-{attempt}.json','review':f'review-{attempt}.json',
                                         'source_audit_rejected':rejection is not None})
                    path=item['work']/f'review-{attempt}.json';r['review_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                    r['review_producer']=artifact_origin(item['work'],path,r['source_sha256'],r['pdf_page'],attempt,role,agents.reviewer,role_contract(agents,'reviewer'))
                    dimension_evidence=r['review_producer'].get('dimension_evidence')
                    if dimension_evidence:
                        r['dimension_review']=json.loads((item['work']/dimension_evidence['file']).read_text())
                    else:r.pop('dimension_review',None)
                    if artifact.accepts(candidate) and rejection is None:
                        item['reviewed_audit']=reviewed_audit_digest(item,agents)
                        if external_audit_digest(item['work'])!=item['reviewed_audit']:
                            r['status']='awaiting_review';r['external_audit_changed_at']=datetime.now(timezone.utc).isoformat()
                            enqueue_review(item,audit=True)
                        else:r['status']='accepted';r.pop('source_audit_rejection',None)
                    else:
                        if rejection:r['source_audit_rejection']=rejection
                        else:r.pop('source_audit_rejection',None)
                        r.update(status='needs_review',next_attempt=attempt+1);enqueue_extraction(item,repair=True,fresh=True)
            except asyncio.CancelledError:
                r['status']='awaiting_review' if role=='reviewer' and 'content' in r else 'pending'
                raise
            except Exception as exc:
                failures+=1;r.update(status='awaiting_review' if role=='reviewer' and 'content' in r else 'pending',last_error=f'{type(exc).__name__}: {exc}')
                if RATE_LIMIT.search(r['last_error']):
                    await provider_slots[providers[role]].rate_limited()
                r.setdefault('failures',[]).append({'role':role,'attempt':attempt,'error':r['last_error'],'time':datetime.now(timezone.utc).isoformat()})
                # Provider pacing belongs to this worker only; the other keeps running.
                save(item);await asyncio.sleep(min(900,retry_delay*2**min(failures-1,5)))
                if role=='extractor':enqueue_extraction(item,repair=attempt>0,fresh=task[0]==2)
                else:enqueue_review(item,fresh=task[0]==2)
            finally:
                r['elapsed_seconds']+=round(time.monotonic()-began,3);r.pop('active_role',None);save(item);queue.task_done()
            # A cached/local completion can return without yielding. Honor the
            # deadline and other queues even while immediately rechecking leads.
            await asyncio.sleep(0)

    await refresh_holds();snapshot();workers=[asyncio.create_task(worker(role,extract if role=='extractor' else review)) for role,n in role_counts.items() for _ in range(n)];interrupted=False
    try:
        async with asyncio.timeout(deadline_seconds):
            while True:
                await refresh_holds()
                # A new, changed or removed independent source lead reopens only
                # the affected accepted page. Retain its exact extractor bytes.
                for item in pending.values():
                    r=item['record']
                    if r['status']!='accepted' and not r.get('active_role'):
                        root_review=source_review_update(item['work'],r)
                        if root_review is not None:
                            r.update(root_review);item['reviewed_audit']=external_audit_digest(item['work']);save(item)
                    if r['status']=='accepted' and external_audit_digest(item['work'])!=item['reviewed_audit']:
                        rejection=source_audit_rejection(item['work'],r['source_sha256'],r['pdf_page'],r['candidate_sha256'])
                        r['external_audit_changed_at']=datetime.now(timezone.utc).isoformat()
                        if rejection:
                            r.update(status='needs_review',next_attempt=r['next_attempt']+1,source_audit_rejection=rejection)
                            enqueue_extraction(item,repair=True,fresh=True)
                        else:
                            r['status']='awaiting_review';enqueue_review(item,audit=True)
                        save(item)
                if all(i['record']['status']=='accepted' for i in pending.values()):break
                await asyncio.sleep(.1)
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
