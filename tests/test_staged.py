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


def test_candidate_binding_requires_source_page_model_and_saved_hash(tmp_path):
    work=tmp_path/'page-0001';work.mkdir()
    value=PageContent(title='old',text_blocks=[],tables=[],figures=[])
    path=work/'candidate-0.json';write_json(path,value.model_dump())
    event={'tool':'save_page_json','attempt':0,'role':'extractor','page':1,'model':'minimax-test','source_sha256':'a'*64,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (work/'tools.jsonl').write_text(json.dumps(event)+'\n')
    assert validated_candidate(work,'a'*64,1,'minimax-test')
    assert validated_candidate(work,'b'*64,1,'minimax-test') is None
    assert validated_candidate(work,'a'*64,2,'minimax-test') is None
    assert validated_candidate(work,'a'*64,1,'another-extractor') is None
    event.pop('source_sha256');(work/'tools.jsonl').write_text(json.dumps(event)+'\n')
    assert validated_candidate(work,'a'*64,1,'minimax-test') is None


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
