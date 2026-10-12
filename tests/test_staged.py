"""Focused integration: review backoff cannot stop extraction; expected <1s, max 5s."""
import asyncio,hashlib,json
import pymupdf
import pytest
from catalog_json.schema import PageContent,Review,Check,CHECKS,Issue
from catalog_json.staged import staged_batch,validated_candidate
from catalog_json.tools import write_json
from catalog_json.agents import AgentPair


class Agents:
    extractor='anthropic.test-extractor';reviewer='zai.test-reviewer';contract_digest='a'*64;timeout=3;max_tokens=1024


def manifest(tmp_path):
    source=tmp_path/'source.pdf'
    with pymupdf.open() as pdf:
        for _ in range(3):pdf.new_page()
        pdf.save(source)
    path=tmp_path/'queue.json';write_json(path,{'catalogs':[{'id':'test','source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]});return path


def passed():return Review(verdict='pass',checks=[Check(category=c,passed=True,evidence='Independent synthetic source audit') for c in CHECKS],issues=[],observed_table_count=0,observed_row_counts=[],observed_column_counts=[])


def test_rate_limited_reviewer_leaves_extractor_running_and_retains_failures(tmp_path):
    events=[];failed=False
    async def call(agents,role,source,out,page,attempt):
        nonlocal failed
        events.append((role,page,attempt))
        if role=='reviewer' and not failed:failed=True;raise RuntimeError('429 request limit')
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        work=out/f'page-{page:04d}';write_json(work/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump())
        return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),deadline_seconds=3,call=call,retry_delay=.05))
    assert result['complete'] and result['catalogs'][0]['draft_pages']==3
    second_review=next(i for i,e in enumerate(events) if e[:2]==('reviewer',2))
    assert events.index(('extractor',3,0))<second_review
    records=json.loads((tmp_path/'out/test/catalog.json').read_text())['pages']
    assert records[0]['failures'][0]['role']=='reviewer' and all(r['status']=='accepted' for r in records)


def test_reviewer_can_request_more_than_one_repair(tmp_path):
    async def call(agents,role,source,out,page,attempt):
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        if role=='reviewer' and page==1 and attempt<3:
            value.verdict='revise';value.issues=[Issue(severity='error',path='title',message='Synthetic repair request')]
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),deadline_seconds=3,call=call))
    records=json.loads((tmp_path/'out/test/catalog.json').read_text())['pages']
    assert result['complete'] and len(records[0]['attempts'])==4 and result['method']['max_repairs'] is None


def test_native_startup_exit_becomes_checkpointable_exception():
    pair=object.__new__(AgentPair);pair.timeout=1
    async def crash(*args):raise SystemExit(1)
    pair._run=crash
    async def check():
        try:await pair.run('extractor',None,None,1,0)
        except RuntimeError as exc:assert 'startup exited' in str(exc)
        else:raise AssertionError('Expected converted native exit')
    asyncio.run(check())


def test_repairs_are_not_postponed_until_all_catalogues_are_extracted(tmp_path):
    events=[]
    async def call(agents,role,source,out,page,attempt):
        events.append((role,page,attempt));await asyncio.sleep(.01 if role=='extractor' else 0)
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        if role=='reviewer' and page==1 and attempt==0:value.verdict='revise'
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),deadline_seconds=3,call=call))
    assert result['complete']
    assert events.index(('extractor',1,1))<events.index(('extractor',3,0))


def test_repaired_review_precedes_queued_first_reviews(tmp_path):
    events=[]
    async def call(agents,role,source,out,page,attempt):
        events.append((role,page,attempt))
        # First review leaves several fresh candidates queued before its repair.
        await asyncio.sleep(.06 if role=='reviewer' and page==1 and attempt==0 else .03 if role=='reviewer' and page==2 else .005)
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        if role=='reviewer' and page==1 and attempt==0:value.verdict='revise'
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump())
        return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),deadline_seconds=3,call=call))
    assert result['complete']
    assert events.index(('reviewer',1,1))<events.index(('reviewer',3,0))


def test_review_priority_is_reselected_after_provider_admission_wait(tmp_path):
    events=[]
    async def call(agents,role,source,out,page,attempt):
        events.append((role,page,attempt));await asyncio.sleep(.03 if role=='reviewer' and page==1 and attempt==0 else .003)
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        if role=='reviewer' and page==1 and attempt==0:
            # A second worker already holds page2, but cannot yet call its API.
            # The source repair becomes ready during this provider cooldown.
            await agents.rate_limit_observer(role);value.verdict='revise'
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump())
        return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),deadline_seconds=3,call=call,
                                   reviewer_workers=2,initial_provider_concurrency=1,retry_delay=.1))
    assert result['complete']
    assert events.index(('reviewer',1,1))<events.index(('reviewer',2,0))
    assert sorted(e[1:] for e in events if e[0]=='reviewer')==[(1,0),(1,1),(2,0),(3,0)]


def test_later_catalogue_drafts_cannot_bury_earlier_catalogue_repair(tmp_path):
    path=manifest(tmp_path);data=json.loads(path.read_text());first=data['catalogs'][0];data['catalogs']=[{**first,'id':'first'},{**first,'id':'later'}];write_json(path,data)
    events=[]
    async def call(agents,role,source,out,page,attempt):
        events.append((role,out.name,page,attempt))
        await asyncio.sleep(.06 if role=='reviewer' and out.name=='first' and page==1 and attempt==0 else .025 if role=='reviewer' else .003)
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        if role=='reviewer' and out.name=='first' and page==1 and attempt==0:value.verdict='revise'
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    result=asyncio.run(staged_batch(path,tmp_path/'out',Agents(),deadline_seconds=3,call=call))
    assert result['complete']
    assert events.index(('reviewer','first',1,1))<events.index(('reviewer','later',1,0))
    assert [c['accepted_pages'] for c in result['catalogs']]==[3,3]


def test_candidate_binding_requires_source_page_model_and_saved_hash(tmp_path):
    work=tmp_path/'page-0001';work.mkdir()
    value=PageContent(title='old',text_blocks=[],tables=[],figures=[])
    path=work/'candidate-0.json';write_json(path,value.model_dump())
    event={'tool':'save_page_json','attempt':0,'role':'extractor','page':1,'model':'minimax-test','source_sha256':'a'*64,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (work/'tools.jsonl').write_text(json.dumps(event)+'\n')
    assert validated_candidate(work,'a'*64,1,'minimax-test')
    assert validated_candidate(work,'a'*64,1,'minimax-test','current-contract') is None
    event['contract_sha256']='current-contract';(work/'tools.jsonl').write_text(json.dumps(event)+'\n')
    assert validated_candidate(work,'a'*64,1,'minimax-test','current-contract')
    assert validated_candidate(work,'a'*64,1,'minimax-test','other-contract') is None
    assert validated_candidate(work,'b'*64,1,'minimax-test') is None
    assert validated_candidate(work,'a'*64,2,'minimax-test') is None
    assert validated_candidate(work,'a'*64,1,'another-extractor') is None
    event.pop('source_sha256');(work/'tools.jsonl').write_text(json.dumps(event)+'\n')
    assert validated_candidate(work,'a'*64,1,'minimax-test') is None


def test_restoring_superseded_full_bytes_cannot_unlock_resume(tmp_path):
    work=tmp_path/'page-0001';work.mkdir();value=PageContent(title='old',text_blocks=[],tables=[],figures=[])
    path=work/'candidate-0.json';write_json(path,value.model_dump());old=path.read_bytes()
    event={'tool':'save_page_json','attempt':0,'role':'extractor','page':1,'model':'m','source_sha256':'s','contract_sha256':'c','sha256':hashlib.sha256(old).hexdigest()}
    value.title='new';write_json(path,value.model_dump());new={**event,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (work/'tools.jsonl').write_text(json.dumps(event)+'\n'+json.dumps(new)+'\n')
    path.write_bytes(old)
    assert validated_candidate(work,'s',1,'m','c') is None


def test_separate_role_contracts_reuse_only_actual_extractor_contract(tmp_path):
    from catalog_json.tools import CatalogTools
    from pathlib import Path
    queue=manifest(tmp_path);out=tmp_path/'out';source=Path(json.loads(queue.read_text())['catalogs'][0]['source'])
    a=Agents();a.contract_digest='combined';a.role_contracts={'extractor':'extractor-contract','reviewer':'reviewer-contract'}
    for page in range(1,4):
        t=CatalogTools(source,out/'test',page=page,model=a.extractor,contract_sha256='extractor-contract');t.render(page);t.direct(page)
        assert t.save(page,PageContent(title=str(page),text_blocks=[],tables=[],figures=[]).model_dump_json(),'page')['saved']
    calls=[]
    async def call(agents,role,source,out,page,attempt):
        calls.append(role);value=passed();write_json(out/f'page-{page:04d}'/f'review-{attempt}.json',value.model_dump());return value
    result=asyncio.run(staged_batch(queue,out,a,resume=True,call=call))
    assert result['complete'] and calls==['reviewer']*3
    records=json.loads((out/'test/catalog.json').read_text())['pages']
    assert all(r['candidate_producer']['contract_sha256']=='extractor-contract' and r['review_producer']['contract_sha256']=='reviewer-contract' for r in records)


def test_explicit_role_routes_reject_mutated_pins(tmp_path):
    from catalog_json.staged import load_role_runtimes
    p=tmp_path/'runtime.py';p.write_text('pinned')
    route={'program':{'source_code_sha256':'actual'},'contract_sha256':'contract','file_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest()}}
    path=tmp_path/'routes.json';write_json(path,{'roles':{'extractor':route,'reviewer':route}})
    a=load_role_runtimes(Agents(),path);assert a.role_contracts=={'extractor':'contract','reviewer':'contract'}
    p.write_text('changed')
    with pytest.raises(ValueError,match='Pinned role runtime changed'):load_role_runtimes(Agents(),path)


def test_seed_without_catalogue_binding_is_rejected_before_any_provider_call(tmp_path):
    queue=manifest(tmp_path);seed=tmp_path/'seed';(seed/'test/page-0001').mkdir(parents=True)
    async def call(*args):raise AssertionError('No provider call is allowed')
    with pytest.raises(ValueError,match='lacks source/model binding'):
        asyncio.run(staged_batch(queue,tmp_path/'out',Agents(),seed=seed,call=call))


def test_changed_resume_source_is_rejected_without_overwriting_old_output(tmp_path):
    queue=manifest(tmp_path);out=tmp_path/'out/test';out.mkdir(parents=True)
    old={'source':{'sha256':'old source'},'models':{'extractor':'minimax-test'}}
    write_json(out/'catalog.json',old)
    with pytest.raises(ValueError,match='Resume source or extractor changed'):
        asyncio.run(staged_batch(queue,tmp_path/'out',Agents(),resume=True))
    assert json.loads((out/'catalog.json').read_text())==old


def test_same_provider_roles_share_one_active_call_slot(tmp_path):
    class Shared(Agents):extractor='zai.first';reviewer='zai.second'
    active=0;peak=0
    async def call(agents,role,source,out,page,attempt):
        nonlocal active,peak
        active+=1;peak=max(peak,active);await asyncio.sleep(.01);active-=1
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Shared(),deadline_seconds=3,call=call))
    assert result['complete'] and peak==1


def test_parallel_reviewers_keep_every_page_and_provider_bounds(tmp_path):
    active={'extractor':0,'reviewer':0};peak=dict(active)
    async def call(agents,role,source,out,page,attempt):
        active[role]+=1;peak[role]=max(peak[role],active[role]);await asyncio.sleep(.02)
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());active[role]-=1;return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),call=call,extractor_workers=3,reviewer_workers=3,initial_provider_concurrency=2))
    assert result['complete'] and peak=={'extractor':2,'reviewer':2}
    records=json.loads((tmp_path/'out/test/catalog.json').read_text())['pages']
    assert [r['pdf_page'] for r in records]==[1,2,3] and all(r['status']=='accepted' for r in records)
    assert all(r['candidate_producer']['program'] is None for r in records)


def test_cancelled_role_call_cleans_own_child_in_separate_session(tmp_path,monkeypatch):
    import sys,psutil
    from catalog_json.staged import isolated_call
    original=asyncio.create_subprocess_exec;pid_file=tmp_path/'child.pid'
    code="import subprocess,sys,time,pathlib;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(30)"
    async def spawn(*args,**kwargs):return await original(sys.executable,'-c',code,str(pid_file),**kwargs)
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    class Worker(Agents):config=tmp_path/'config.yaml'
    async def check():
        task=asyncio.create_task(isolated_call(Worker(),'extractor',tmp_path/'source.pdf',tmp_path/'out',1,0))
        for _ in range(100):
            if pid_file.exists():break
            await asyncio.sleep(.01)
        assert pid_file.exists();pid=int(pid_file.read_text());await asyncio.sleep(.2)
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status()==psutil.STATUS_ZOMBIE
    asyncio.run(check())


def test_cancelled_batch_records_checkpoint_instead_of_stale_running_state(tmp_path):
    async def call(*args):await asyncio.sleep(30)
    async def check():
        task=asyncio.create_task(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),call=call))
        await asyncio.sleep(.05);task.cancel();result=await task
        assert not result['complete'] and result['status']=='checkpointed' and result['interrupted']
        assert json.loads((tmp_path/'out/batch.json').read_text())['catalogs'][0]['status']=='checkpointed'
    asyncio.run(check())


def test_quick_worker_exit_cannot_orphan_its_separate_session_child(tmp_path):
    import sys,psutil
    from catalog_json.staged import isolated_call
    pid_file=tmp_path/'child.pid'
    code="import subprocess,sys,pathlib;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True);pathlib.Path(sys.argv[1]).write_text(str(p.pid))"
    class Worker(Agents):config=tmp_path/'config.yaml'
    async def check():
        with pytest.raises(RuntimeError,match='without a validated result'):
            await isolated_call(Worker(),'extractor',tmp_path/'source.pdf',tmp_path/'out',1,0,worker_command=[sys.executable,'-c',code,str(pid_file)])
        pid=int(pid_file.read_text())
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status()==psutil.STATUS_ZOMBIE
    asyncio.run(check())


def test_changed_contract_reextracts_instead_of_relabelling_prior_candidate(tmp_path):
    """Focused integration: a new contract must produce its own candidate; expected1s/max5s."""
    from catalog_json.tools import CatalogTools
    from pathlib import Path
    queue=manifest(tmp_path);out=tmp_path/'out';work=out/'test/page-0001'
    source=Path(json.loads(queue.read_text())['catalogs'][0]['source'])
    old=CatalogTools(source,out/'test',page=1,model=Agents.extractor);old.render(1);old.direct(1)
    assert old.save(1,PageContent(title='prior',text_blocks=[],tables=[],figures=[]).model_dump_json(),'page')['saved']
    write_json(work/'result.json',{'contract_sha256':'prior-contract','next_attempt':0,'status':'awaiting_review'})
    calls=[]
    async def call(agents,role,source,out,page,attempt):
        calls.append((role,page,attempt))
        value=PageContent(title='current',text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    asyncio.run(staged_batch(queue,out,Agents(),resume=True,call=call))
    assert ('extractor',1,1) in calls
    assert json.loads((work/'candidate-0.json').read_text())['title']=='prior'


def test_failed_new_contract_attempt_cannot_unlock_old_candidate_on_second_resume(tmp_path):
    """Focused integration: interrupted contract upgrades stay source/version bound; expected1s/max5s."""
    from catalog_json.tools import CatalogTools
    from pathlib import Path
    queue=manifest(tmp_path);out=tmp_path/'out';work=out/'test/page-0001'
    source=Path(json.loads(queue.read_text())['catalogs'][0]['source'])
    old=CatalogTools(source,out/'test',page=1,model=Agents.extractor);old.render(1);old.direct(1)
    assert old.save(1,PageContent(title='prior',text_blocks=[],tables=[],figures=[]).model_dump_json(),'page')['saved']
    write_json(work/'result.json',{'contract_sha256':'prior-contract','next_attempt':0,'status':'awaiting_review'})
    async def failed(*args):raise RuntimeError('Failed before current-contract save')
    asyncio.run(staged_batch(queue,out,Agents(),resume=True,call=failed,retry_delay=.5,deadline_seconds=.08))
    calls=[]
    async def good(agents,role,source,out,page,attempt):
        calls.append((role,page,attempt))
        value=PageContent(title='current',text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    asyncio.run(staged_batch(queue,out,Agents(),resume=True,call=good))
    assert ('extractor',1,1) in calls
    assert ('reviewer',1,0) not in calls
    assert json.loads((work/'candidate-0.json').read_text())['title']=='prior'


def test_current_contract_saved_candidate_survives_stale_result_marker(tmp_path):
    """Focused integration: source-bound saves avoid replay despite stale marker; expected1s/max5s."""
    from catalog_json.tools import CatalogTools
    from pathlib import Path
    queue=manifest(tmp_path);out=tmp_path/'out';work=out/'test/page-0001'
    source=Path(json.loads(queue.read_text())['catalogs'][0]['source'])
    tool=CatalogTools(source,out/'test',page=1,model=Agents.extractor,contract_sha256=Agents.contract_digest);tool.render(1);tool.direct(1)
    assert tool.save(1,PageContent(title='current',text_blocks=[],tables=[],figures=[]).model_dump_json(),'page')['saved']
    write_json(work/'result.json',{'contract_sha256':'stale-marker','next_attempt':0,'status':'awaiting_review'})
    calls=[]
    async def call(agents,role,source,out,page,attempt):
        calls.append((role,page,attempt))
        value=PageContent(title='current',text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    asyncio.run(staged_batch(queue,out,Agents(),resume=True,call=call))
    assert ('extractor',1,0) not in calls and ('reviewer',1,0) in calls


def test_end_turn_without_file_continues_until_confirmed_tool_save():
    """Fast unit: ordinary chat end is not a deliverable; expected1s/max5s."""
    from catalog_json.agents import generate_until_saved
    class Model:
        calls=[]
        async def generate(self,prompt,request_params):
            self.calls.append(prompt);return 'ordinary end turn'
    model=Model()
    result=asyncio.run(generate_until_saved(model,'original source task',object(),lambda:len(model.calls)==5))
    assert result=='ordinary end turn' and len(model.calls)==5
    assert model.calls[0]=='original source task'
    assert all('save' in p for p in model.calls[1:])


def test_missing_deliverable_continuation_still_respects_timeout():
    """Fast unit: no repair count cap, outer finite deadline remains effective; expected1s/max5s."""
    from catalog_json.agents import generate_until_saved
    class Model:
        async def generate(self,*args,**kwargs):await asyncio.sleep(.01);return 'end'
    async def run():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(generate_until_saved(Model(),'source',object(),lambda:False),.03)
    asyncio.run(run())


def test_sdk_swallowed_cancellation_cannot_restart_generation():
    """Fast unit: SDK cancellation-return must retain outer deadline; expected1s/max5s."""
    from catalog_json.agents import generate_until_saved
    from types import SimpleNamespace
    import time
    class Model:
        calls=0
        async def generate(self,*args,**kwargs):
            self.calls+=1
            try:await asyncio.sleep(10)
            except asyncio.CancelledError:return SimpleNamespace(stop_reason='cancelled')
    async def run():
        model=Model();started=time.monotonic()
        with pytest.raises((TimeoutError,asyncio.CancelledError,RuntimeError)):
            await asyncio.wait_for(generate_until_saved(model,'source',object(),lambda:False,deadline=time.monotonic()+.03),.03)
        assert model.calls==1 and time.monotonic()-started<.2
    asyncio.run(run())


def test_sdk_uncancelled_return_still_cannot_exceed_absolute_deadline():
    """Fast unit: SDK uncancel cannot erase elapsed deadline; expected1s/max5s."""
    from catalog_json.agents import generate_until_saved
    from types import SimpleNamespace
    import time
    class Model:
        calls=0
        async def generate(self,*args,**kwargs):
            self.calls+=1
            try:await asyncio.sleep(10)
            except asyncio.CancelledError:
                asyncio.current_task().uncancel()
                return SimpleNamespace(stop_reason='end_turn')
    async def run():
        model=Model()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(generate_until_saved(model,'source',object(),lambda:False,deadline=time.monotonic()+.03),.03)
        assert model.calls==1
    asyncio.run(run())


@pytest.mark.parametrize("change",["add","replace","remove"])
def test_new_external_audit_requeues_accepted_page_without_repeating_extraction(tmp_path,monkeypatch,change):
    """Focused integration: live source lead cannot leave stale accepted status; <1s/max5s."""
    from catalog_json import staged
    calls=[];changed=False
    audit=tmp_path/'out/test/page-0001/external-audit.json'
    if change!='add':
        audit.parent.mkdir(parents=True);write_json(audit,{'pdf_page':1,'findings':['Original lead']})
    monkeypatch.setattr(staged,'reviewed_audit_digest',lambda item,agents: staged.external_audit_digest(item['work']),raising=False)
    async def call(agents,role,source,out,page,attempt):
        nonlocal changed
        calls.append((role,page,attempt))
        if role=='reviewer' and page==2 and not changed:
            changed=True
            if change=='remove':audit.unlink()
            else:write_json(audit,{'pdf_page':1,'findings':[{'message':'Independent source lead'}]})
            await asyncio.sleep(.02)
        if role=='reviewer' and page==3:await asyncio.sleep(.04)
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),deadline_seconds=1,call=call,resume=True))
    assert result['complete']
    assert calls.count(('extractor',1,0))==1
    assert calls.count(('reviewer',1,0))==2
    assert list((tmp_path/'out/test/page-0001/review-history').glob('*/review-0.json'))


def test_reviewed_audit_requires_exact_native_review_receipt_window(tmp_path):
    """Fast unit: stale/wrong-identity audit reads never certify fresh leads; <1s/max5s."""
    from catalog_json.staged import reviewed_audit_digest
    item={'work':tmp_path,'record':{'pdf_page':1,'next_attempt':2,'source_sha256':'s','review_producer':{'status':'receipt_verified','started_at':10,'finished_at':20}}}
    a=Agents();event={'tool':'read_external_audit','role':'reviewer','page':1,'attempt':2,'source_sha256':'s','model':a.reviewer,'contract_sha256':a.contract_digest,'time':15,'sha256':'current'}
    log=tmp_path/'tools.jsonl';log.write_text(json.dumps(event)+'\n')
    assert reviewed_audit_digest(item,a)=='current'
    for key,value in [('role','extractor'),('page',2),('attempt',1),('source_sha256','other'),('model','other'),('contract_sha256','other'),('time',9),('time',21)]:
        log.write_text(json.dumps({**event,key:value})+'\n');assert reviewed_audit_digest(item,a) is None
    log.write_text(json.dumps(event)+'\n');item['record']['review_producer']['status']='producer_unknown'
    assert reviewed_audit_digest(item,a) is None


def test_changed_audit_during_review_requires_actual_fresh_read(tmp_path,monkeypatch):
    """Focused integration: a pass without consuming the changed source lead stays open; <1s/max5s."""
    from catalog_json import staged
    calls=[];reads={}
    monkeypatch.setattr(staged,'reviewed_audit_digest',lambda item,agents:reads.get(item['record']['pdf_page']))
    async def call(agents,role,source,out,page,attempt):
        calls.append((role,page,attempt))
        if role=='reviewer' and page==1:
            if calls.count(('reviewer',1,0))==1:write_json(out/'page-0001/external-audit.json',{'pdf_page':1,'findings':['Late source lead']})
            else:reads[1]=staged.external_audit_digest(out/'page-0001')
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(out/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),deadline_seconds=1,call=call))
    assert result['complete'] and calls.count(('reviewer',1,0))==2 and calls.count(('extractor',1,0))==1


@pytest.mark.parametrize('changed',['none','source','contract','model'])
def test_compatible_resume_restores_pacing_only_for_same_source_and_roles(tmp_path,changed):
    """Focused integration: restart preserves capacity feedback only for its profile; <1s/max5s."""
    queue=manifest(tmp_path);entry=json.loads(queue.read_text())['catalogs'][0];out=tmp_path/'out';out.mkdir()
    prior={'contract_sha256':Agents.contract_digest,'models':{'extractor':Agents.extractor,'reviewer':Agents.reviewer},'catalogs':[entry],'method':{'provider_pacing':{'anthropic':{'configured_maximum':8,'current_limit':1,'rate_limit_count':40,'rate_limit_waves':2,'backoff_remaining_seconds':0}}}}
    if changed=='source':prior['catalogs'][0]={**entry,'source_sha256':'different'}
    if changed=='contract':prior['contract_sha256']='different'
    if changed=='model':prior['models']['extractor']='other'
    write_json(out/'batch.json',prior);active=0;peak=0
    async def call(agents,role,source,directory,page,attempt):
        nonlocal active,peak
        if role=='extractor':active+=1;peak=max(peak,active);await asyncio.sleep(.01);active-=1
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(directory/f'page-{page:04d}'/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    result=asyncio.run(staged_batch(queue,out,Agents(),deadline_seconds=1,call=call,resume=True,resume_compatible_profile=True,extractor_workers=2,reviewer_workers=2,initial_provider_concurrency=2))
    assert result['complete'] and peak==(1 if changed=='none' else 2)
    assert result['method']['provider_pacing']['anthropic']['rate_limit_count']==(40 if changed=='none' else 0)


def test_matching_cache_key_cannot_reuse_unverified_native_review_receipt(tmp_path):
    """Focused integration: ordinary resume cannot bypass native receipt/audit proof; <1s/max5s."""
    queue=manifest(tmp_path);out=tmp_path/'out';calls=[]
    async def call(agents,role,source,directory,page,attempt):
        calls.append(role);work=directory/f'page-{page:04d}'
        value=PageContent(title=str(page),text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        path=work/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json');write_json(path,value.model_dump())
        event={'tool':'save_page_json' if role=='extractor' else 'save_review','role':role,'model':getattr(agents,role),'page':page,'attempt':attempt,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'contract_sha256':agents.contract_digest,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'time':1}
        with (work/'tools.jsonl').open('a') as stream:stream.write(json.dumps(event)+'\n')
        return value
    assert asyncio.run(staged_batch(queue,out,Agents(),call=call))['complete']
    calls.clear()
    assert asyncio.run(staged_batch(queue,out,Agents(),call=call,resume=True))['complete']
    assert calls==['reviewer']*3


def test_operator_quota_hold_expires_job_without_admitting_or_spending_native_call(tmp_path):
    """Focused integration: hold wait stays outside native timeout and preserves checkpoint; <1s/max5s."""
    import time
    queue=manifest(tmp_path);hold=tmp_path/'holds.json';write_json(hold,{'schema_version':'1.0','providers':{'anthropic':{'model':Agents.extractor,'not_before_unix':time.time()+60}}})
    calls=[]
    async def call(*args):calls.append(args);raise AssertionError('Held provider must not call native worker')
    result=asyncio.run(staged_batch(queue,tmp_path/'out',Agents(),deadline_seconds=.04,call=call,provider_holds=hold))
    assert not result['complete'] and not calls
    assert result['method']['provider_pacing']['anthropic']['active_calls']==0
    assert result['method']['provider_pacing']['anthropic']['operator_hold_remaining_seconds']>59
    assert result['method']['operator_holds_sha256']==hashlib.sha256(hold.read_bytes()).hexdigest()


@pytest.mark.parametrize('new_audit',[False,True])
def test_bound_repair_feedback_survives_scheduler_resume_without_rechecking_same_candidate(tmp_path,new_audit):
    """Focused integration: resume continues a proven repair instead of paying for duplicate review; <1s/max5s."""
    import time,uuid
    queue=manifest(tmp_path);out=tmp_path/'out';calls=[];pause=True
    async def call(agents,role,source,directory,page,attempt):
        calls.append((role,page,attempt))
        if pause and role=='extractor' and page==1 and attempt==1:await asyncio.sleep(10)
        work=directory/f'page-{page:04d}';began=time.time()
        value=PageContent(title=f'{page}:{attempt}',text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        if role=='reviewer' and page==1 and attempt==0:
            value.verdict='revise';value.issues=[Issue(severity='error',path='title',message='Source-grounded synthetic repair')]
        path=work/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json');write_json(path,value.model_dump());digest=hashlib.sha256(path.read_bytes()).hexdigest();sha=hashlib.sha256(source.read_bytes()).hexdigest()
        event={'tool':'save_page_json' if role=='extractor' else 'save_review','role':role,'page':page,'attempt':attempt,'source_sha256':sha,'model':getattr(agents,role),'contract_sha256':agents.contract_digest,'sha256':digest,'time':time.time()}
        with (work/'tools.jsonl').open('a') as stream:
            audit=work/'external-audit.json'
            if role=='reviewer' and audit.exists():stream.write(json.dumps({**event,'tool':'read_external_audit','sha256':hashlib.sha256(audit.read_bytes()).hexdigest()})+'\n')
            stream.write(json.dumps(event)+'\n')
        receipt=work/'calls'/uuid.uuid4().hex/'result.json';write_json(receipt,{'status':'completed','execution':{'program':{'package_version':'synthetic','source_code_sha256':'verified-program'},'source_sha256':sha,'physical_page':page,'attempt':attempt,'role':role,'model':getattr(agents,role),'contract_sha256':agents.contract_digest,'artifact_sha256':digest,'started_at':began,'finished_at':time.time()}})
        return value
    assert not asyncio.run(staged_batch(queue,out,Agents(),deadline_seconds=.06,call=call))['complete']
    record=json.loads((out/'test/page-0001/result.json').read_text());assert record['next_attempt']==1 and record['review']['verdict']=='revise'
    if new_audit:write_json(out/'test/page-0001/external-audit.json',{'pdf_page':1,'findings':['New source lead']})
    pause=False;calls.clear()
    result=asyncio.run(staged_batch(queue,out,Agents(),deadline_seconds=1,call=call,resume=True,resume_compatible_profile=True))
    assert result['complete']
    if new_audit:assert calls[:3]==[('reviewer',1,0),('extractor',1,1),('reviewer',1,1)]
    else:assert calls==[('extractor',1,1),('reviewer',1,1)]


def test_source_confirmed_rejected_bytes_cannot_be_reaccepted_by_model_pass(tmp_path):
    """Focused integration: exact source-audited bad bytes require native repair; <1s/max5s."""
    queue=manifest(tmp_path);calls=[]
    async def call(agents,role,source,out,page,attempt):
        calls.append((role,page,attempt));work=out/f'page-{page:04d}'
        value=PageContent(title=f'{page}:{attempt}',text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        path=work/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json');write_json(path,value.model_dump())
        if role=='extractor' and page==1 and attempt==0:
            write_json(work/'external-audit.json',{'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'pdf_page':page,
                       'findings':[{'problem':'Confirmed invented figure description'}],
                       'rejected_candidate_sha256':[hashlib.sha256(path.read_bytes()).hexdigest()]})
        return value
    result=asyncio.run(staged_batch(queue,tmp_path/'out',Agents(),deadline_seconds=1,call=call))
    assert result['complete'] and calls.count(('extractor',1,1))==1
    record=json.loads((tmp_path/'out/test/page-0001/result.json').read_text())
    assert record['status']=='accepted' and record['next_attempt']==1
    assert record['attempts'][0]['source_audit_rejected'] is True
    assert 'source_audit_rejection' not in record
    # The native model report remains truthful; the parent recorded its own veto.
    assert json.loads((tmp_path/'out/test/page-0001/review-0.json').read_text())['verdict']=='pass'


@pytest.mark.parametrize('change',['source','page','page_bool','digest','not_list','empty_findings'])
def test_source_rejection_constraint_requires_exact_source_page_and_valid_hashes(tmp_path,change):
    """Fast unit: wrong/malformed curated source constraint checkpoints, never silently applies; <1s/max5s."""
    from catalog_json.staged import source_audit_rejection
    data={'source_sha256':'a'*64,'pdf_page':1,'findings':[{'problem':'Source-confirmed defect'}],'rejected_candidate_sha256':['b'*64]}
    if change=='source':data['source_sha256']='c'*64
    if change=='page':data['pdf_page']=2
    if change=='page_bool':data['pdf_page']=True
    if change=='digest':data['rejected_candidate_sha256']=['not-a-sha']
    if change=='not_list':data['rejected_candidate_sha256']='b'*64
    if change=='empty_findings':data['findings']=[]
    write_json(tmp_path/'external-audit.json',data)
    with pytest.raises(ValueError):source_audit_rejection(tmp_path,'a'*64,1,'b'*64)


def test_source_rejection_changes_only_exact_curated_candidate(tmp_path):
    """Fast unit: a repaired hash still requires normal review; ordinary leads do not reject bytes; <1s/max5s."""
    from catalog_json.staged import source_audit_rejection
    assert source_audit_rejection(tmp_path,'a'*64,1,'b'*64) is None
    audit=tmp_path/'external-audit.json';data={'source_sha256':'a'*64,'pdf_page':1,'findings':[{'problem':'Source-confirmed defect'}]}
    write_json(audit,data);assert source_audit_rejection(tmp_path,'a'*64,1,'b'*64) is None
    data['rejected_candidate_sha256']=['b'*64];write_json(audit,data)
    assert source_audit_rejection(tmp_path,'a'*64,1,'b'*64)['candidate_sha256']=='b'*64
    assert source_audit_rejection(tmp_path,'a'*64,1,'c'*64) is None


def test_hot_source_rejection_repairs_exact_bytes_without_replaying_passing_review(tmp_path,monkeypatch):
    """Focused integration: a late verified defect routes to repair while other admitted calls finish; <1s/max5s."""
    from catalog_json import staged
    calls=[];changed=False
    monkeypatch.setattr(staged,'reviewed_audit_digest',lambda item,agents: staged.external_audit_digest(item['work']))
    async def call(agents,role,source,out,page,attempt):
        nonlocal changed
        calls.append((role,page,attempt));work=out/f'page-{page:04d}'
        if role=='reviewer' and page==2 and not changed:
            changed=True;first=out/'page-0001';candidate=first/'candidate-0.json'
            write_json(first/'external-audit.json',{'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'pdf_page':1,
                       'findings':[{'problem':'Confirmed original-source error'}],
                       'rejected_candidate_sha256':[hashlib.sha256(candidate.read_bytes()).hexdigest()]})
            await asyncio.sleep(.03)
        value=PageContent(title=f'{page}:{attempt}',text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        write_json(work/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json'),value.model_dump());return value
    result=asyncio.run(staged_batch(manifest(tmp_path),tmp_path/'out',Agents(),deadline_seconds=1,call=call))
    assert result['complete'] and calls.count(('reviewer',1,0))==1
    assert ('extractor',1,1) in calls and ('reviewer',1,1) in calls


def test_rejected_passing_candidate_resume_repairs_without_duplicate_review(tmp_path):
    """Focused integration: bound native pass is retained but cannot waive curated source defect; <1s/max5s."""
    import time,uuid
    queue=manifest(tmp_path);out=tmp_path/'out';calls=[];pause=True
    async def call(agents,role,source,directory,page,attempt):
        calls.append((role,page,attempt));work=directory/f'page-{page:04d}'
        if pause and role=='extractor' and page==1 and attempt==1:await asyncio.sleep(10)
        began=time.time();sha=hashlib.sha256(source.read_bytes()).hexdigest()
        value=PageContent(title=f'{page}:{attempt}',text_blocks=[],tables=[],figures=[]) if role=='extractor' else passed()
        path=work/(f'candidate-{attempt}.json' if role=='extractor' else f'review-{attempt}.json');write_json(path,value.model_dump());digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if role=='extractor' and page==1 and attempt==0:
            write_json(work/'external-audit.json',{'source_sha256':sha,'pdf_page':1,'findings':[{'problem':'Confirmed source defect'}],'rejected_candidate_sha256':[digest]})
        event={'tool':'save_page_json' if role=='extractor' else 'save_review','role':role,'page':page,'attempt':attempt,'source_sha256':sha,'model':getattr(agents,role),'contract_sha256':agents.contract_digest,'sha256':digest,'time':time.time()}
        with (work/'tools.jsonl').open('a') as stream:
            if role=='reviewer' and (work/'external-audit.json').exists():stream.write(json.dumps({**event,'tool':'read_external_audit','sha256':hashlib.sha256((work/'external-audit.json').read_bytes()).hexdigest()})+'\n')
            stream.write(json.dumps(event)+'\n')
        write_json(work/'calls'/uuid.uuid4().hex/'result.json',{'status':'completed','execution':{'program':{'package_version':'synthetic','source_code_sha256':'verified-program'},'source_sha256':sha,'physical_page':page,'attempt':attempt,'role':role,'model':getattr(agents,role),'contract_sha256':agents.contract_digest,'artifact_sha256':digest,'started_at':began,'finished_at':time.time()}})
        return value
    assert not asyncio.run(staged_batch(queue,out,Agents(),deadline_seconds=.06,call=call))['complete']
    first=json.loads((out/'test/page-0001/result.json').read_text());assert first['next_attempt']==1 and first['review']['verdict']=='pass'
    pause=False;calls.clear()
    assert asyncio.run(staged_batch(queue,out,Agents(),deadline_seconds=1,call=call,resume=True,resume_compatible_profile=True))['complete']
    assert calls==[('extractor',1,1),('reviewer',1,1)]
