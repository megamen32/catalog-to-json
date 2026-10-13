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

def test_candidate_names_and_prose_cannot_hide_dimensions():
    c=drawing_content();c.figures[0].title='Вид А';c.figures[0].description='Внешняя геометрия изделия'
    c.figures[0].labels=['Диаметр Ø98','∅98 — верхний контур','98 +2/-1']
    assert len(dimension_targets(c))==4

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
