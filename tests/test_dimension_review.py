"""Fast unit and focused integration: require source-bound per-view relations. Expected 2s, max20s."""
import json
from catalog_json.dimension_review import dimension_targets,missing_dimension_evidence
from catalog_json.schema import Figure

def drawing_content():
    from test_tools import content
    c=content();c.figures=[Figure(title='Drawing III',description='Diameter of upper cylinder 98',labels=['Ø98']),
                          Figure(title='Drawing IV',description='Diameter of upper skirt 126',labels=['Ø126'])]
    return c

def test_same_numeral_in_other_view_cannot_cover_relation():
    c=drawing_content();c.figures[1].labels=['Ø98']
    records=[{'figure_index':0,'label_index':0,'candidate_sha256':'sha','agrees_with_candidate':True}]
    assert missing_dimension_evidence(c,records,'sha')==[t|{'inventory':'candidate'} for t in dimension_targets(c)[1:]]
    assert len(missing_dimension_evidence(c,records,'changed'))==2
    records[0]['agrees_with_candidate']=False
    assert len(missing_dimension_evidence(c,records,'sha'))==2


def test_blocking_uncertainty_surfaces_before_geometry_and_revise_can_checkpoint(tmp_path):
    """Focused integration: retained cert47 could not PASS even after costly geometry;1s/max10s."""
    from test_tools import pdf,review
    from catalog_json.tools import CatalogTools
    from catalog_json.schema import Issue
    c=drawing_content();c.uncertainties=['Source identifier still unresolved']
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1)
    assert t.save(1,c.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    assert r.save(1,c.model_dump_json(),'observation')['saved'];r.read(1,'page')
    report=review();refused=r.save(1,report.model_dump_json(),'review')
    assert refused['candidate_uncertainties']==c.uncertainties and 'missing_dimension_relations' not in refused
    report.verdict='revise';report.issues=[Issue(severity='error',path='uncertainties',message='Resolve original identifier first')]
    assert r.save(1,report.model_dump_json(),'review')['saved'] and not report.accepts(c)
    # Resolving the unrelated uncertainty does not waive actual drawing evidence.
    c.uncertainties=[];assert t.save(1,c.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    assert r.save(1,c.model_dump_json(),'observation')['saved'];r.read(1,'page')
    report.verdict='pass';report.issues=[]
    refused=r.save(1,report.model_dump_json(),'review')
    assert 'missing_dimension_relations' in refused, refused


def test_compact_annotation_batch_keeps_inspection_and_diameter_refusal(tmp_path):
    from test_tools import pdf
    from catalog_json.tools import CatalogTools
    c=drawing_content();c.figures=[Figure(title='Scanned metadata and actual dimension',description='Source labels',labels=['2018 г.','Ø98'])]
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1)
    assert t.save(1,c.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    assert r.save(1,c.model_dump_json(),'observation')['saved'];r.read(1,'page')
    shared={'relation':'annotation','tip_points':[],'source_figure_index':0,'figure_index':0,'source_box':[0,0,1,1],
        'feature_box':[.1,.1,.9,.9],'view':'Document region','source_feature':'Date field',
        'agrees_with_candidate':True,'evidence':'Read original document date; no dimension arrows for date'}
    batch={'shared':shared,'records':[{'source_label_index':0,'label_index':0,'candidate_feature_quote':'2018 г.'},
        {'source_label_index':1,'label_index':1,'candidate_feature_quote':'Ø98'}]}
    assert r.record_dimensions(1,json.dumps(batch))['saved_count']==0
    r.render(1,[0,0,1,1]);result=r.record_dimensions(1,json.dumps(batch))
    assert not result['saved'] and result['saved_count']==1 and result['failures'][0]['index']==1
    assert 'Diameter/tolerance' in result['failures'][0]['error']

def test_candidate_names_and_prose_cannot_hide_dimensions():
    c=drawing_content();c.figures[0].title='Вид А';c.figures[0].description='Внешняя геометрия изделия'
    c.figures[0].labels=['Диаметр Ø98','∅98 — верхний контур','98 +2/-1']
    assert len(dimension_targets(c))==4


def test_v_lock_symbolic_and_subscript_dimensions_cannot_bypass_coverage():
    """Fast unit; expected1s/max10s. Retained arm27 PASS covered only Rz8/angle."""
    c=drawing_content();c.figures=[Figure(title='V-образный замок',description='Original drawing',labels=[
        'L₁','L','L₂','L₃','L₄','F₁','F₂','F₃','F₄','F₅','R','R₁','R₂','R₃','Rz8','V','S','T','А','А–А','38°–50°'])]
    old_records=[{'figure_index':0,'label_index':i,'candidate_sha256':'sha','agrees_with_candidate':True} for i in (14,20)]
    missing=missing_dimension_evidence(c,old_records,'sha',c,'source-sha')
    assert {t['label'] for t in dimension_targets(c)}==set(c.figures[0].labels)-{'А','А–А'}
    assert {'L₁','L','F₂','R','R₃','V','S','T'}<={t['label'] for t in missing}
    assert c.figures[0].labels[0]=='L₁'  # Only coverage normalizes; extracted source text stays intact.


def test_confirmed_document_metadata_is_not_drawing_geometry():
    c=drawing_content();c.figures=[Figure(title='Certificate',description='Scanned certificate',labels=[
        '2018 г.','Протокол №29-10 от24.04.2018','ТУ3493-004-99267582-2009','457040, ул.Строителей1б',
        'Ø98','98','98 +2/-1','12 мм'])]
    assert len(dimension_targets(c))==8
    assert [t['label'] for t in dimension_targets(c,supporting_annotations=True)]==['Ø98','98','98 +2/-1','12 мм']


def test_supporting_annotation_exception_requires_independent_context_and_flag(tmp_path):
    from test_tools import pdf,review
    from test_page_context import context,semantic_review
    from catalog_json.tools import CatalogTools
    c=drawing_content();c.figures=[Figure(title='Certificate',description='Certificate from2018',labels=['2018 г.'])]
    c.tables=[]
    c.page_context=context('supporting_material',transcription='literal')
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1)
    assert t.save(1,c.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    assert r.save(1,c.model_dump_json(),'observation')['saved'];r.read(1,'page')
    report=review();report.context_review=semantic_review()
    report.observed_table_count=0;report.observed_row_counts=[];report.observed_column_counts=[]
    assert not r.save(1,report.model_dump_json(),'review')['saved']
    report.context_review.supporting_annotations_verified=True
    assert r.save(1,report.model_dump_json(),'review')['saved']


def test_supporting_flag_cannot_waive_mixed_real_drawing(tmp_path):
    from test_tools import pdf,review
    from test_page_context import context,semantic_review
    from catalog_json.tools import CatalogTools
    c=drawing_content();c.page_context=context('mixed',transcription='literal')
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1)
    assert t.save(1,c.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    assert r.save(1,c.model_dump_json(),'observation')['saved'];r.read(1,'page')
    report=review();report.context_review=semantic_review();report.context_review.supporting_annotations_verified=True
    refused=r.save(1,report.model_dump_json(),'review');assert len(refused['missing_dimension_relations'])==4

def test_description_only_numbers_cannot_hide_independent_source_targets():
    source=drawing_content();candidate=source.model_copy(deep=True)
    for f in candidate.figures:f.description+=' '+', '.join(f.labels);f.labels=[]
    from catalog_json.audit import compare_source
    assert not compare_source(source,candidate)
    missing=missing_dimension_evidence(candidate,[],'sha',source,'observation-sha')
    assert len(missing)==2 and all(t['inventory']=='source' for t in missing)

def test_whitespace_evidence_is_not_evidence():
    from catalog_json.dimension_review import DimensionReview
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):DimensionReview(figure_index=0,label_index=0,view=' ',relation='diameter',source_box=[0,0,1,1],feature_box=[.2,.2,.8,.8],tip_points=[[.2,.5],[.8,.5]],source_feature=' ',candidate_feature_quote=' ',agrees_with_candidate=True,evidence=' ')

def test_uninspected_crop_invalid_tips_and_false_association_cannot_pass(tmp_path):
    from test_tools import pdf,review
    from catalog_json.tools import CatalogTools
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1);c=drawing_content();assert t.save(1,c.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1);assert r.save(1,c.model_dump_json(),'observation')['saved'];r.read(1,'page')
    refused=r.save(1,review().model_dump_json(),'review');assert len(refused['missing_dimension_relations'])==4
    data=dict(source_figure_index=0,source_label_index=0,figure_index=0,label_index=0,view='III',relation='diameter',source_box=[0,0,1,1],feature_box=[.2,.2,.8,.8],tip_points=[[.2,.5],[.8,.5]],source_feature='outer skirt',candidate_feature_quote='upper cylinder',agrees_with_candidate=False,evidence='Original endpoints enclose the wide skirt, not the cylinder')
    assert not r.record_dimension(1,json.dumps(data))['saved']
    r.render(1,[0,0,1,1]);data['tip_points']=[[.2,.5]]
    assert not r.record_dimension(1,json.dumps(data))['saved']
    data['tip_points']=[[.2,.5],[.8,.5]];assert r.record_dimension(1,json.dumps(data))['saved']
    data['agrees_with_candidate']=True
    assert not r.record_dimension(1,json.dumps(data))['saved']
    data['correction_reason']='New source inspection of the extension lines';assert r.record_dimension(1,json.dumps(data))['saved']
    previous=list((r.work(1)/'.history/dimension-review-0').glob('*.json'))
    assert previous and json.loads(previous[0].read_text())['relations'][0]['agrees_with_candidate'] is False
    data['agrees_with_candidate']=False;data['correction_reason']='Reconfirmed wrong contour';assert r.record_dimension(1,json.dumps(data))['saved']
    assert len(r.save(1,review().model_dump_json(),'review')['missing_dimension_relations'])==4

    # Legitimately report the wrong relation; do not fabricate geometry coverage.
    report=review();report.verdict='revise'
    for check in report.checks:
        if check.category=='figures':check.passed=False
    from catalog_json.schema import Issue
    report.issues=[Issue(severity='error',path='figures[0].description',message='Wrong measured contour')]
    assert r.save(1,report.model_dump_json(),'review')['saved']
    from catalog_json.provenance import artifact_origin
    before=artifact_origin(r.work(1),r.work(1)/'review-0.json',r.source_digest,1,0,'reviewer',None,None)
    assert before['source_bound_save'] and before['dimension_evidence']
    (r.work(1)/'dimension-review-0.json').write_text('{}')
    after=artifact_origin(r.work(1),r.work(1)/'review-0.json',r.source_digest,1,0,'reviewer',None,None)
    assert not after['source_bound_save']


def test_batch_keeps_all_individual_checks_and_reports_partial_failure(tmp_path):
    from test_tools import pdf,review
    from catalog_json.tools import CatalogTools
    from catalog_json.schema import Issue
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1);c=drawing_content();assert t.save(1,c.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1);assert r.save(1,c.model_dump_json(),'observation')['saved'];r.read(1,'page');r.render(1,[0,0,1,1])
    base=dict(source_figure_index=0,source_label_index=0,figure_index=0,label_index=0,view='III',relation='diameter',source_box=[0,0,1,1],feature_box=[.2,.2,.8,.8],tip_points=[[.2,.5],[.8,.5]],source_feature='upper cylinder',candidate_feature_quote='upper cylinder',agrees_with_candidate=True,evidence='Both original tips inspected in this view')
    bad={**base,'source_figure_index':1,'figure_index':1,'view':'IV','candidate_feature_quote':'upper skirt','tip_points':[[.2,.5]]}
    result=r.record_dimensions(1,json.dumps([base,bad]));assert not result['saved'] and result['saved_count']==1 and result['failures'][0]['index']==1
    assert not r.save(1,review().model_dump_json(),'review')['saved']
    bad['tip_points']=[[.2,.5],[.8,.5]]
    result=r.record_dimensions(1,json.dumps([bad]));assert result['saved'] and result['saved_count']==1
    assert r.save(1,review().model_dump_json(),'review')['saved']
    assert not r.record_dimensions(1,'{}')['saved']
    assert not r.record_dimensions(1,json.dumps([base]*101))['saved']
    assert not t.record_dimensions(1,json.dumps([base]))['saved']
