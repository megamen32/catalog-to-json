"""Fast unit/focused tool integration: demo meaning vs actual data; expected 3s, max30s.

Detects demo rows becoming offers, one-sided classification and summary bypasses.
No provider/model calls; native limited small4 canary remains the delivery gate.
"""
import json
import pytest
from pydantic import ValidationError
from catalog_json.audit import compare_source
from catalog_json.schema import PageContent,PageContext,Figure,TextBlock,ContextReview
from catalog_json.tools import CatalogTools,review_contract
from test_tools import pdf
from test_contract import content,review


def context(kind='software_demonstration',box=None,transcription='contextual_summary'):
    return PageContext.model_validate({'kind':kind,'summary':'Software creates and exports a sample specification, not a product offer.',
        'source_evidence':[{'kind':'software_demonstration' if transcription=='contextual_summary' else kind,
                            'box':box or [.1,.2,.9,.8],'observation':'Feature prose introduces a DEMO CAD window and example generated report.',
                            'transcription':transcription}]})


def demonstration():
    return PageContent(title='Specification software',page_context=context(),text_blocks=[TextBlock(kind='paragraph',text='Export to Excel and Word.')],tables=[],figures=[])


def semantic_review():
    return ContextReview(page_purpose_verified=True,summary_meaning_verified=True,actual_vs_demo_verified=True,
                         technical_facts_verified=True,relations_verified=True,
                         evidence='The feature prose and DEMO CAD window establish a software example. The candidate accurately describes report generation without offering sample rows as real products.')


def test_legacy_absent_context_stays_literal_and_unmodified():
    old=content().model_dump();old.pop('page_context',None)
    source=PageContent.model_validate(old);candidate=PageContent.model_validate(old)
    assert source.page_context is None and not compare_source(source,candidate)
    candidate.tables[0].rows[0].cells[0].value=999
    assert compare_source(source,candidate)
    assert 'page_context' not in old


def test_summary_requires_independent_semantic_and_region_agreement():
    a=demonstration();b=demonstration()
    b.page_context.summary='The program exports a demonstrated project report.'
    assert not compare_source(a,b)
    b.page_context=None
    assert compare_source(a,b)[0]['path']=='page_context'
    b.page_context=context('mixed')
    assert any(d['path']=='page_context.kind' for d in compare_source(a,b))
    b.page_context=context(box=[.1,.01,.9,.15])
    assert not compare_source(a,b)  # Region coordinates do not certify meaning.


@pytest.mark.parametrize('change',['move','add','kind','transcription'])
def test_evidence_scope_is_checked_without_mechanical_region_alignment(change):
    a=content();a.page_context=context('mixed',transcription='literal')
    b=a.model_copy(deep=True);e=b.page_context.source_evidence[0]
    if change=='move':e.box=[.01,.01,.1,.1]
    elif change=='add':b.page_context.source_evidence.append(e.model_copy(update={'box':[.01,.01,.1,.1]}))
    elif change=='kind':e.kind='project_specification'
    else:e.kind='software_demonstration';e.transcription='contextual_summary'
    differences=compare_source(a,b)
    if change in {'kind','transcription'}:
        assert any(d['path']=='page_context.source_evidence' for d in differences)
    else:assert not differences


def test_independent_narrative_paraphrases_and_region_order_are_valid():
    a=content();a.page_context=context('mixed',transcription='literal')
    a.page_context.source_evidence.append(a.page_context.source_evidence[0].model_copy(update={'kind':'project_specification','box':[.1,.85,.9,.95]}))
    b=a.model_copy(deep=True)
    b.page_context.summary='A genuine project specification is presented with supporting documentation.'
    for e in b.page_context.source_evidence:e.observation='Independently phrased description of the same inspected source region.'
    b.page_context.source_evidence.reverse()
    assert not compare_source(a,b)


def test_extra_unknown_evidence_box_does_not_invent_a_concrete_scope_error():
    a=content();a.page_context=context('catalogue_product_data',transcription='literal')
    b=a.model_copy(deep=True)
    b.page_context.source_evidence.append(b.page_context.source_evidence[0].model_copy(update={
        'kind':'unknown','observation':'Empty space has no drawing or product data.'}))
    assert not compare_source(a,b)
    b.tables[0].rows[0].cells[0].value=999
    assert any('.value' in d['path'] for d in compare_source(a,b))


def test_unknown_evidence_cannot_hide_missing_real_scope_or_grant_demo_mode():
    a=content();a.page_context=context('mixed',transcription='literal')
    b=a.model_copy(deep=True);b.page_context.source_evidence[0].kind='unknown'
    assert any(d['path']=='page_context.source_evidence' for d in compare_source(a,b))
    a=demonstration();b=a.model_copy(deep=True)
    b.page_context.source_evidence.append(b.page_context.source_evidence[0].model_copy(update={
        'kind':'unknown','transcription':'literal'}))
    assert any(d['path']=='page_context.source_evidence' for d in compare_source(a,b))


def test_independent_demo_region_segmentation_is_not_an_extraction_error():
    a=demonstration();b=demonstration()
    b.page_context.source_evidence.append(context(box=[.1,.01,.9,.15]).source_evidence[0])
    b.figures=[Figure(title='Software UI',description='Example report generation',labels=['Example button'])]
    assert not compare_source(a,b)


def test_semantic_narrative_does_not_weaken_drawing_values():
    a=demonstration();b=demonstration()
    a.page_context=context('mixed');b.page_context=context('mixed')
    b.text_blocks=[TextBlock(kind='paragraph',text='The demonstration exports reports to Word and Excel.')]
    assert not compare_source(a,b)
    a.figures=[Figure(title='Real drawing',description='Ø13 outer contour',labels=['Ø13'])]
    b.figures=[Figure(title='Real drawing',description='Ø130 outer contour',labels=['Ø130'])]
    assert any(d['path'].startswith('figures') for d in compare_source(a,b))


def test_contextual_narrative_paraphrase_and_case_inflection_preserve_tables():
    a=content();a.page_context=context('catalogue_product_data',transcription='literal')
    a.text_blocks=[TextBlock(kind='heading',text='Шлейфовые зажимы'),TextBlock(kind='paragraph',text='Для соединения шлейфовых проводов применяются зажимы.')]
    b=a.model_copy(deep=True)
    b.text_blocks=[TextBlock(kind='heading',text='Зажимы шлейфовых проводов'),TextBlock(kind='paragraph',text='Назначение зажимов — соединять шлейфовые провода.')]
    assert not compare_source(a,b) and a.tables==b.tables
    a.page_context=None;b.page_context=None
    assert any(d['path'].startswith('text_blocks') for d in compare_source(a,b))


@pytest.mark.parametrize('changed',['code','unit'])
def test_contextual_paraphrase_never_allows_changed_table_code_or_unit(changed):
    a=content();a.page_context=context('catalogue_product_data',transcription='literal')
    a.tables[0].columns[0].label='Код изделия' if changed=='code' else 'Напряжение'
    a.tables[0].columns[0].unit=None if changed=='code' else 'кВ'
    a.tables[0].rows[0].cells[0].value='ШЗ-001' if changed=='code' else '10'
    b=a.model_copy(deep=True)
    a.text_blocks=[TextBlock(kind='paragraph',text='Параметры изделий приведены ниже.')]
    b.text_blocks=[TextBlock(kind='paragraph',text='Ниже указаны характеристики изделий.')]
    if changed=='code':b.tables[0].rows[0].cells[0].value='ШЗ-002'
    else:b.tables[0].columns[0].unit='мВ'
    differences=compare_source(a,b)
    assert differences and all(d['path'].startswith('tables') for d in differences)


def test_genuine_project_spec_stays_strict_on_mixed_page():
    a=content();b=content();a.page_context=context('mixed');b.page_context=context('mixed')
    b.tables[0].rows[0].cells[0].value=999
    assert any('.value' in d['path'] for d in compare_source(a,b))
    for d in (a,b):d.page_context=context('project_specification',transcription='literal')
    assert compare_source(a,b)


def test_pure_demo_cannot_publish_sample_table_as_catalogue_data():
    a=content().model_dump();a['page_context']=context().model_dump()
    with pytest.raises(ValidationError,match='demonstration rows'):
        PageContent.model_validate(a)


def test_demo_scope_error_precedes_irrelevant_cell_format_repairs():
    a=content().model_dump();a['page_context']=context().model_dump()
    a['tables'][0]['rows'][0]['cells'][0].pop('value',None)
    with pytest.raises(ValidationError,match='do not repair the formatting') as error:
        PageContent.model_validate(a)
    assert not any(e['type']=='missing' for e in error.value.errors())


def test_reviewer_instruction_arrives_without_sdk_middle_truncation():
    from catalog_json.agents import SKILLS
    payload='Exact review schema and structural example (available before the first save):\n'+json.dumps(review_contract(),ensure_ascii=False,separators=(',',':'))+'\n\n'+(SKILLS/'catalog-review/SKILL.md').read_text()
    # Actual FastAgent native history demonstrated a16000-byte tool envelope.
    # Retain every semantic rule inline instead of hiding it in a spilled file.
    assert len(json.dumps({'result':payload},ensure_ascii=False).encode())<16000
    PageContent.model_validate(review_contract()['source_observation_example'])


@pytest.mark.parametrize('kind',['catalogue_product_data','project_specification','supporting_material','unknown'])
def test_summary_mode_cannot_reclassify_real_data(kind):
    value=context().model_dump();value['kind']=kind
    with pytest.raises(ValidationError):PageContext.model_validate(value)
    value=context().model_dump();value['source_evidence'][0]['kind']=kind
    with pytest.raises(ValidationError):PageContext.model_validate(value)


def test_context_requires_visible_evidence_and_valid_boxes():
    for patch in ({'summary':' '},{'source_evidence':[]}):
        value=context().model_dump()|patch
        with pytest.raises(ValidationError):PageContext.model_validate(value)
    with pytest.raises(ValidationError):context(box=[0,.2,1,2])


@pytest.mark.parametrize('context_kind',['software_demonstration','mixed'])
def test_source_bound_summary_save_and_blind_review_gate(tmp_path,context_kind):
    source=pdf(tmp_path);out=tmp_path/'out';a=demonstration()
    a.page_context=context(context_kind)
    a.figures=[Figure(title='Illustrative CAD view',description='Example UI drawing',labels=['Ø13'])]
    extractor=CatalogTools(source,out);extractor.render(1);extractor.direct(1)
    assert not extractor.save(1,a.model_dump_json(),'page')['saved']
    extractor.render(1,a.page_context.source_evidence[0].box)
    assert extractor.save(1,a.model_dump_json(),'page')['saved']
    auditor=CatalogTools(source,out,role='reviewer');auditor.render(1)
    with pytest.raises(ValueError,match='independently'):auditor.read(1,'page')
    assert not auditor.save(1,a.model_dump_json(),'observation')['saved']
    auditor.render(1,a.page_context.source_evidence[0].box)
    assert auditor.save(1,a.model_dump_json(),'observation')['saved']
    assert not auditor.read(1,'page')['independent_comparison']
    r=review();r.observed_table_count=0;r.observed_row_counts=[];r.observed_column_counts=[]
    r.context_review=semantic_review()
    result=auditor.save(1,r.model_dump_json(),'review')
    if context_kind=='software_demonstration':assert result['saved']
    else:assert not result['saved'] and result['missing_dimension_relations']
    assert json.loads((auditor.work(1)/'source-observation-0.json').read_text())['page_context']['kind']==context_kind


def test_context_pass_requires_explicit_complete_semantic_verdict(tmp_path):
    source=pdf(tmp_path);out=tmp_path/'out';a=demonstration()
    t=CatalogTools(source,out);t.render(1);t.direct(1);t.render(1,a.page_context.source_evidence[0].box)
    assert t.save(1,a.model_dump_json(),'page')['saved']
    auditor=CatalogTools(source,out,role='reviewer');auditor.render(1);auditor.render(1,a.page_context.source_evidence[0].box)
    independent=a.model_copy(deep=True);independent.page_context.summary='Demonstrates automatic specification generation and report export.'
    independent.page_context.source_evidence[0].observation='The surrounding feature explanation introduces the shown example project workflow.'
    independent.text_blocks=[TextBlock(kind='paragraph',text='Пример показывает экспорт отчётов в Word и Excel.')]
    assert auditor.save(1,independent.model_dump_json(),'observation')['saved'];auditor.read(1,'page')
    report=review();report.observed_table_count=0;report.observed_row_counts=[];report.observed_column_counts=[]
    for semantic in [None,*(semantic_review().model_copy(update={field:False}) for field in ('page_purpose_verified','summary_meaning_verified','actual_vs_demo_verified','technical_facts_verified','relations_verified')),semantic_review().model_copy(update={'evidence':' '})]:
        report.context_review=semantic
        refused=auditor.save(1,report.model_dump_json(),'review')
        assert not refused['saved'] and 'required_context_review' in refused
    report.context_review=semantic_review()
    assert auditor.save(1,report.model_dump_json(),'review')['saved']


def test_legacy_eleven_check_review_remains_valid_without_context_verdict():
    report=review()
    assert report.context_review is None and len(report.checks)==11 and report.accepts(content())


@pytest.mark.parametrize('blocks',[[],[TextBlock(kind='heading',text='probe')]])
def test_empty_probe_cannot_complete_extraction_or_erase_a_saved_candidate(tmp_path,blocks):
    """Focused tool integration; expected1s/max10s. Native isolators47 saved only 'probe'."""
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1)
    empty=PageContent(title='probe',text_blocks=blocks,tables=[],figures=[])
    assert not t.save(1,empty.model_dump_json(),'page')['saved']
    assert not (t.work(1)/'candidate-0.json').exists()
    assert t.save(1,content().model_dump_json(),'page')['saved']
    before=(t.work(1)/'candidate-0.json').read_bytes()
    assert not t.save(1,empty.model_dump_json(),'page')['saved']
    assert (t.work(1)/'candidate-0.json').read_bytes()==before
    # Legacy files remain readable; purposeful minimal sources can be explicit.
    assert PageContent.model_validate_json(empty.model_dump_json()).page_context is None
    empty.page_context=context('supporting_material',transcription='literal')
    assert t.save(1,empty.model_dump_json(),'page')['saved']


@pytest.mark.parametrize('verdict',['pass','revise','uncertain'])
def test_missing_observer_context_is_its_own_repair_not_candidate_feedback(tmp_path,verdict):
    """Fast tool integration; expected1s/max10s. Reproduces innovations168 false revisions."""
    candidate=content();candidate.page_context=context('catalogue_product_data',transcription='literal')
    candidate.text_blocks=[TextBlock(kind='paragraph',text='Назначение зажимов — соединять шлейфовые провода.')]
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1)
    assert t.save(1,candidate.model_dump_json(),'page')['saved']
    observer=candidate.model_copy(deep=True);observer.page_context=None
    observer.text_blocks=[TextBlock(kind='paragraph',text='Для соединения шлейфовых проводов применяются зажимы.')]
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    assert r.save(1,observer.model_dump_json(),'observation')['saved'];r.read(1,'page')
    candidate_bytes=(r.work(1)/'candidate-0.json').read_bytes()
    blind_bytes=(r.work(1)/'source-observation-0.json').read_bytes()
    report=review();report.verdict=verdict;report.context_review=semantic_review()
    refused=r.save(1,report.model_dump_json(),'review')
    assert not refused['saved'] and refused['repair_observer_context']
    assert not (r.work(1)/'review-0.json').exists()
    assert (r.work(1)/'candidate-0.json').read_bytes()==candidate_bytes
    assert (r.work(1)/'source-observation-0.json').read_bytes()==blind_bytes

    # Independent source correction removes prose/context false positives.
    r.render(1,[0,0,1,1]);observer.page_context=context('catalogue_product_data',transcription='literal')
    assert r.correct_observation(1,observer.model_dump_json(),'Fresh original inspection establishes actual product data.')['saved']
    assert not r.read(1,'page')['independent_comparison']
    report.verdict='pass'
    assert r.save(1,report.model_dump_json(),'review')['saved']
    assert (r.work(1)/'source-observation-0.json').read_bytes()==blind_bytes

    # A real changed numeric value still blocks PASS after context is complete.
    observer.tables[0].rows[0].cells[0].value=81
    r.render(1,[0,0,1,1])
    assert r.correct_observation(1,observer.model_dump_json(),'Fresh source inspection finds mass81, not80.')['saved']
    blocked=r.save(1,report.model_dump_json(),'review')
    assert not blocked['saved'] and any('.value' in d['path'] for d in blocked['differences'])
    report.verdict='revise'
    assert r.save(1,report.model_dump_json(),'review')['saved']
    assert any('.value' in d['path'] for d in json.loads((r.work(1)/'review-0.json').read_text())['issues'])


def test_classification_disagreement_cannot_pass_review(tmp_path):
    source=pdf(tmp_path);out=tmp_path/'out';a=demonstration()
    t=CatalogTools(source,out);t.render(1);t.direct(1);t.render(1,a.page_context.source_evidence[0].box)
    assert t.save(1,a.model_dump_json(),'page')['saved']
    r=CatalogTools(source,out,role='reviewer');r.render(1)
    actual=demonstration();actual.page_context=context('project_specification',transcription='literal')
    assert r.save(1,actual.model_dump_json(),'observation')['saved'];r.read(1,'page')
    report=review();report.observed_table_count=0;report.observed_row_counts=[];report.observed_column_counts=[]
    report.context_review=semantic_review()
    refused=r.save(1,report.model_dump_json(),'review')
    assert not refused['saved'] and any(d['path']=='page_context.kind' for d in refused['differences'])


def test_section_finalization_keeps_page_context(tmp_path):
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1);a=demonstration()
    t.render(1,a.page_context.source_evidence[0].box)
    assert t.finalize(1,a.title,page_context=a.page_context.model_dump())['saved']
    assert t.finalize(1,a.title)['saved']
    assert json.loads((t.work(1)/'candidate-0.json').read_text())['page_context']==a.page_context.model_dump()


def test_early_review_example_is_valid_but_never_an_acceptance():
    contract=review_contract()
    from catalog_json.schema import Review,CHECKS
    example=Review.model_validate(contract['example'])
    assert set(contract['required_review_checks'])==CHECKS
    assert not example.accepts(demonstration())


def test_native_reviewer_gets_review_schema_before_first_save(tmp_path):
    """Focused integration: native MCP discovery; expected3s/max30s; no model calls."""
    import asyncio
    import sys
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    source=pdf(tmp_path)
    async def run():
        params=StdioServerParameters(command=sys.executable,args=['-m','catalog_json.tools','--source',str(source),'--output',str(tmp_path/'out'),'--role','reviewer'])
        async with stdio_client(params) as (reader,writer):
            async with ClientSession(reader,writer) as client:
                await client.initialize()
                skill=await client.call_tool('load_skill',{})
                assert not skill.is_error
                text=skill.content[0].text
                assert text.index('"observed_table_count"')<text.index('# Независимая инженерная проверка')
                assert '"example"' in text and 'page_context' in text
                assert len(text.encode())<16000
                assert 'project_specification/mixed' in text and 'context_review' in text
    asyncio.run(asyncio.wait_for(run(),30))


def test_inspected_genuine_grid_cannot_be_discarded_by_unsupported_context(tmp_path):
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1);a=demonstration()
    t.grids[1]=[{'row_count':2,'column_count':2,'expanded_rows':[['A','1'],['B','2']],
                 'unknown_cells':[],'merged_cells':[],'inspected_box':[.1,.2,.9,.8]}]
    assert t.grid_differences(1,a)  # Declared summary alone is insufficient.
    t.render(1,a.page_context.source_evidence[0].box)
    assert not t.grid_differences(1,a)
    a.page_context=context('project_specification',transcription='literal')
    assert t.grid_differences(1,a)
