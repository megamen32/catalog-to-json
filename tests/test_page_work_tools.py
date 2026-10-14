"""Focused integration: source image and complete owner work, no provider calls.

Expected5s, emergency50s. Reject partial/duplicated/unseen or stale input.
"""
import asyncio
import hashlib
import json
import pymupdf
import pytest
from catalog_json.reconciliation.page_work_tools import PageWorkTools,work_server


@pytest.fixture
def context(tmp_path):
    pdf=tmp_path/'source.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((30,50),'AB12 240 mm')
        doc.save(pdf)
    sha=hashlib.sha256(pdf.read_bytes()).hexdigest()
    sources=tmp_path/'sources.json';sources.write_text(json.dumps([{'sha256':sha,'path':str(pdf)}]))
    packet=tmp_path/'page.json'
    packet.write_text(json.dumps({'catalog':'fixture','owner':'codex','source_sha256':sha,'physical_page':1,
        'facts':[{'fact_id':'O1','side':'ours','value':'240'}, {'fact_id':'L1','side':'oleg','value':'240'}],
        'ledger_rows':[], 'contexts':{'R':'original context'}}))
    return PageWorkTools(packet,sources,{'role':'codex','model':'fixture','session_id':'fixture','runtime':'test'},tmp_path/'out')


def group(**kw):
    return dict(fact_indices=[0,1],relation='same_fact',keep='ours',reason='Source original240mm',evidence_refs=[0],**kw)


def test_real_mcp_original_zoom_and_complete_save(context):
    mcp=work_server(context)
    names={t.name for t in asyncio.run(mcp.list_tools())}
    assert {'view_region','read_source_table','get_work_page','read_work_items','stage_work_groups','finish_page_work'}<=names
    with pytest.raises(ValueError,match='original'):context.finish()
    sha=context.packet['source_sha256']
    image=context.sources.run(sha,1,lambda c:c.region(1,[0,0,1,.3]))
    assert image.data.startswith(b'\x89PNG') and context.viewed
    context.evidence=[{'bbox':[0,0,1,.3],'observation':'AB12 240 mm'}]
    context.stage([group()]);receipt=context.finish()
    assert receipt['saved'] and receipt['facts_accounted_for']==2
    assert receipt['independent_final_review_complete'] is False
    with pytest.raises(FileExistsError):context.finish()


def test_bad_group_can_be_repaired_before_staging(context):
    context.evidence=[{'bbox':[0,0,1,1],'observation':'240mm'}]
    with pytest.raises(ValueError,match='unbound'):context.stage([group(new_value='999')])
    assert not context.groups
    context.stage([group()])
    with pytest.raises(ValueError,match='already'):context.stage([group()])


def test_paging_retains_exact_values_and_source_binding(context):
    got=context.read('facts',0,1)
    assert got['next_offset']==1 and got['items'][0]['value']['value']=='240'
    assert json.loads(context.read('contexts',0,40,context_id='R')['text'])=='original context'
    assert json.loads(context.read_text(1)['text'])==context.packet['facts'][1]
    with pytest.raises(ValueError):context.read('facts',0,0)
    context.path.write_text('{}')
    with pytest.raises(ValueError,match='changed'):context.summary()


def test_incomplete_work_never_finishes(context):
    context.viewed=True;context.evidence=[{'bbox':[0,0,1,1],'observation':'240mm'}]
    with pytest.raises(ValueError,match='partial'):context.finish()
    assert not (context.output/'result.json').exists()
