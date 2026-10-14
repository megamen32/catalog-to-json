"""Focused integration, expected 4s/max40s: corrected bytes close duplicate calls.

Detects stale/same-author/partial proof acceptance while preserving native data.
"""
import copy,hashlib,json,asyncio
from pathlib import Path
import pytest
from catalog_json.manual_completion import independent_completion_update,queue_complete,STATUS,CHECKS
from catalog_json.schema import PageContent,TextBlock
from catalog_json.tools import write_json


def case(base):
    w=base/'test/page-0001';w.mkdir(parents=True)
    native=PageContent(title='Native error',text_blocks=[],tables=[],figures=[]).model_dump()
    content=PageContent(title='Correct title',text_blocks=[TextBlock(kind='paragraph',text='Original checked')],tables=[],figures=[]).model_dump()
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    write_json(w/'candidate-0.json',native);basis=digest(w/'candidate-0.json')
    author={'harness':'codex','session_id':'author','version':'author-v1'}
    producer={'program':{'package_version':'actual-native-v1'},'role':'extractor','model':'anthropic.test','contract_sha256':'b'*64,'status':'receipt_verified','source_sha256':'a'*64,'physical_page':1,'attempt':0,'artifact_sha256':basis}
    write_json(w/'root-reference-tail-20261014-r1.json',content);sha=digest(w/'root-reference-tail-20261014-r1.json')
    write_json(w/'root-reference-tail-20261014-r1.provenance.json',{'schema_version':'catalogue-source-review/1','status':'source_verified','source_sha256':'a'*64,'physical_page':1,'catalog':'test','corrections':['Corrected from source'],'output':{'sha256':sha},'full_original_image_review':True,'reviewer':author,'checks':{k:True for k in CHECKS},'basis_candidate':{'sha256':basis,'producer':producer},'tables':{'row_counts':[],'column_counts':[],'cells_checked':0}})
    frozen=w/'frozen.json';write_json(frozen,content);image=w/'original.png';image.write_bytes(b'exact retained source image fixture')
    report={'schema_version':'catalogue-independent-source-review/1','independent_author':'other','origin_author':'author','catalog':'test','source_sha256':'a'*64,'physical_page':1,'verdict':'pass','full_original_image_review':True,'reviewed_json_sha256':sha,'reviewed_input_frozen':str(frozen),'original_image':str(image),'original_image_sha256':digest(image),'checks':{k:{'passed':True,'evidence':'Complete original checked'} for k in CHECKS},'observed_row_counts':[],'observed_column_counts':[],'total_cells_checked':0,'issues':[]}
    write_json(w/'independent.json',report)
    audit={'source_sha256':'a'*64,'pdf_page':1,'findings':[{'reference_sha256':sha,'reference_author':author,'reference_data':content,'independent_source_review':{'verdict':'pass','issues':[],'reviewed_reference_sha256':sha,'full_original_image_review':True,'provider_model_call':False,'report':'independent.json','report_sha256':digest(w/'independent.json'),'author':'other'}}]}
    write_json(w/'external-audit.json',audit)
    write_json(w/'calls/native/result.json',{'status':'completed','execution':{**producer,'started_at':1,'finished_at':3}})
    (w/'tools.jsonl').write_text(json.dumps({'tool':'save_page_json','role':'extractor','page':1,'attempt':0,'source_sha256':'a'*64,'model':producer['model'],'contract_sha256':producer['contract_sha256'],'sha256':basis,'time':2})+'\n')
    record={'source_sha256':'a'*64,'pdf_page':1,'content':native,'candidate_sha256':basis,'candidate_producer':producer,'status':'awaiting_review'}
    return w,record,report,audit


def test_exact_independent_revision_closes_queue_without_accepting_old_native_bytes(tmp_path):
    w,record,_,_=case(tmp_path);before=copy.deepcopy(record);native=(w/'candidate-0.json').read_bytes()
    update=independent_completion_update(w,record)
    assert update and update['status']==STATUS and queue_complete({**record,**update})
    assert record==before and (w/'candidate-0.json').read_bytes()==native
    assert not update['independent_revision_completion']['native_candidate_accepted']
    assert 'content' not in update and 'review_producer' not in update


@pytest.mark.parametrize('bad',['same_author','source','page','revise','uncertainty','missing_check','wrong_rows','missing_image','changed_frozen','changed_reference','missing_provenance','new_audit_revision','broken_native_receipt','author_source_uncertainty'])
def test_incomplete_or_changed_proof_reopens_work_even_after_cached_pass(tmp_path,bad):
    w,record,report,audit=case(tmp_path);assert independent_completion_update(w,record)
    if bad=='same_author':report['independent_author']='author';audit['findings'][0]['independent_source_review']['author']='author'
    if bad=='source':report['source_sha256']='c'*64
    if bad=='page':report['physical_page']=2
    if bad=='revise':report['verdict']='revise'
    if bad=='uncertainty':report['uncertainties']=['Unresolved source glyph']
    if bad=='missing_check':report['checks'].pop('figures_and_relationships')
    if bad=='wrong_rows':report['observed_row_counts']=[1]
    if bad=='missing_image':(w/'original.png').unlink()
    if bad=='changed_frozen':(w/'frozen.json').write_text('{}')
    if bad=='changed_reference':(w/'root-reference-tail-20261014-r1.json').write_text('{}')
    if bad=='missing_provenance':(w/'root-reference-tail-20261014-r1.provenance.json').unlink()
    if bad=='broken_native_receipt':(w/'calls/native/result.json').write_text('{}')
    if bad=='author_source_uncertainty':
        pp=w/'root-reference-tail-20261014-r1.provenance.json';proof=json.loads(pp.read_text());proof['unresolved_issues']=['Unknown actual model number'];write_json(pp,proof)
    if bad=='new_audit_revision':audit['findings'][0]['reference_sha256']='d'*64
    write_json(w/'independent.json',report);audit['findings'][0]['independent_source_review']['report_sha256']=hashlib.sha256((w/'independent.json').read_bytes()).hexdigest();write_json(w/'external-audit.json',audit)
    assert independent_completion_update(w,record) is None


def test_real_staged_loop_skips_provider_calls_for_verified_revisions(tmp_path,monkeypatch):
    import pymupdf
    import catalog_json.staged as staged
    from types import SimpleNamespace
    queue=tmp_path/'queue.json';source=tmp_path/'source.pdf'
    with pymupdf.open() as d:d.new_page();d.save(source)
    sha=hashlib.sha256(source.read_bytes()).hexdigest();out=tmp_path/'out';w,record,report,audit=case(out)
    # Rebind the fixture to the actual PDF that staged_batch hashes.
    for path in [w/'root-reference-tail-20261014-r1.provenance.json',w/'independent.json',w/'external-audit.json',w/'calls/native/result.json',w/'tools.jsonl']:
        raw=path.read_text().replace('a'*64,sha);path.write_text(raw)
    audit=json.loads((w/'external-audit.json').read_text());audit['findings'][0]['independent_source_review']['report_sha256']=hashlib.sha256((w/'independent.json').read_bytes()).hexdigest();write_json(w/'external-audit.json',audit)
    write_json(queue,{'catalogs':[{'id':'test','source':str(source),'source_sha256':sha}]})
    monkeypatch.setattr(staged,'validated_candidate',lambda *a:(0,PageContent.model_validate(record['content'])))
    monkeypatch.setattr(staged,'artifact_origin',lambda *a:{**record['candidate_producer'],'source_sha256':sha})
    async def no_call(*args):raise AssertionError('A completed manual revision must not call a provider')
    agents=SimpleNamespace(extractor='anthropic.test',reviewer='zai.test',contract_digest='b'*64,timeout=1,max_tokens=1024)
    result=asyncio.run(staged.staged_batch(queue,out,agents,resume=True,deadline_seconds=2,call=no_call))
    rows=json.loads((out/'test/catalog.json').read_text())
    assert result['complete'] and result['catalogs'][0]['accepted_pages']==0
    assert result['catalogs'][0]['independently_verified_revision_pages']==1
    assert rows['pages'][0]['content']==record['content'] and rows['external_revision_selection_required']
    assert not rows['complete_for_selection']


def test_workflow_wait_is_resolved_by_real_second_author_not_source_uncertainty(tmp_path):
    w,record,_,_=case(tmp_path)
    p=w/'root-reference-tail-20261014-r1.provenance.json';d=json.loads(p.read_text())
    d['status']='author_source_review_complete_pending_independent_review'
    d['unresolved_issues']=['Нужна независимая проверка авторского разбора и инженерных отношений.']
    write_json(p,d)
    result=independent_completion_update(w,record)
    assert result and result['independent_revision_completion']['author_workflow_wait_resolved_by_report']==d['unresolved_issues']


@pytest.mark.parametrize('field',['errors','uncertainties'])
def test_empty_alias_cannot_hide_real_issue(tmp_path,field):
    w,record,report,audit=case(tmp_path)
    report['unresolved_issues']=[];report[field]=['Actual defect']
    write_json(w/'independent.json',report)
    audit['findings'][0]['independent_source_review']['report_sha256']=hashlib.sha256((w/'independent.json').read_bytes()).hexdigest();write_json(w/'external-audit.json',audit)
    assert independent_completion_update(w,record) is None


def test_changed_audit_cannot_be_reclosed_by_same_manual_report(tmp_path):
    w,record,_,audit=case(tmp_path);record.update(independent_completion_update(w,record))
    audit['findings'].append({'observation':'New source defect to inspect'})
    write_json(w/'external-audit.json',audit)
    assert independent_completion_update(w,record) is None
    record['status']='awaiting_review'
    assert independent_completion_update(w,record) is None


def test_empty_dimension_group_cannot_certify_a_real_size_label(tmp_path):
    w,record,report,audit=case(tmp_path)
    ref=w/'root-reference-tail-20261014-r1.json';content=json.loads(ref.read_text());content['figures']=[{'title':'Drawing','description':'Actual size17','labels':['17']}]
    write_json(ref,content);sha=hashlib.sha256(ref.read_bytes()).hexdigest();write_json(w/'frozen.json',content)
    p=w/'root-reference-tail-20261014-r1.provenance.json';proof=json.loads(p.read_text());proof['output']['sha256']=sha;write_json(p,proof)
    report['reviewed_json_sha256']=sha;report['dimension_ownership']=[{}];write_json(w/'independent.json',report)
    lead=audit['findings'][0];lead['reference_sha256']=sha;lead['reference_data']=content;lead['independent_source_review']['reviewed_reference_sha256']=sha;lead['independent_source_review']['report_sha256']=hashlib.sha256((w/'independent.json').read_bytes()).hexdigest();write_json(w/'external-audit.json',audit)
    assert independent_completion_update(w,record) is None
    report['dimension_ownership']=[{'literal':'17','actual_target':'Actual gap','source_bbox':[.1,.2,.3,.4]}];write_json(w/'independent.json',report);lead['independent_source_review']['report_sha256']=hashlib.sha256((w/'independent.json').read_bytes()).hexdigest();write_json(w/'external-audit.json',audit)
    assert independent_completion_update(w,record)


def test_native_receipt_change_between_origin_validation_and_read_never_caches_pass(tmp_path,monkeypatch):
    import catalog_json.manual_completion as module
    w,record,_,_=case(tmp_path);original=module.artifact_origin
    def raced(*args):
        value=original(*args);(w/'calls/native/result.json').write_text('{}');return value
    monkeypatch.setattr(module,'artifact_origin',raced)
    assert independent_completion_update(w,record) is None
    assert independent_completion_update(w,record) is None
