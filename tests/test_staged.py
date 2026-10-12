"""Focused integration: review backoff cannot stop extraction; expected <1s, max 5s."""
import asyncio,hashlib,json
import pymupdf
from catalog_json.schema import PageContent,Review,Check,CHECKS,Issue
from catalog_json.staged import staged_batch
from catalog_json.tools import write_json
from catalog_json.agents import AgentPair


class Agents:
    extractor='minimax-test';reviewer='glm-test';contract_digest='a'*64;timeout=3;max_tokens=1024


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
