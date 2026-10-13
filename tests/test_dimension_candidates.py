"""Focused integration: distinguish short shafts from arrow tips (expected2s/max15s).

Prevents losing the small45 dimension or substituting a head base for a measured end.
"""
import json
import pytest
import pymupdf
from catalog_json.tools import CatalogTools


def source_pdf(tmp_path,rotation=0,marks=True,ambiguous=False,repeats=1):
    source=tmp_path/'drawing.pdf'
    with pymupdf.open() as doc:
        p=doc.new_page(width=400,height=600)
        for i in range(repeats):
            y=100+i*20
            # Small shaft; actual arrow tips extend beyond its literal endpoints.
            p.draw_line((110,y),(114,y));p.insert_text((106,y-4),'45',fontsize=5)
            if marks:
                for points in ([(110,y-1),(110,y+1),(104,y)],[(114,y-1),(114,y+1),(120,y)]):
                    if ambiguous:
                        x=points[0][0];points=[(x,y-1),(x,y+1),(x+1.7320508,y)]
                    shape=p.new_shape();shape.draw_polyline(points);shape.finish(fill=(0,0,0),color=None,closePath=True);shape.commit()
        p.set_rotation(rotation);doc.save(source)
    return CatalogTools(source,tmp_path/'output')


def unpack(tools,result):
    if not result.get('paged'):return result
    pieces=[];offset=0
    while offset<result['total_characters']:
        chunk=tools.source_artifact(1,result['artifact_id'],offset);pieces.append(chunk['text']);offset=chunk['next_offset']
    return json.loads(''.join(pieces))


@pytest.mark.parametrize('rotation',[0,90])
def test_short_shaft_and_literal_head_tips_are_separate_source_coordinates(tmp_path,rotation):
    tools=source_pdf(tmp_path,rotation)
    result=unpack(tools,tools.dimension_candidates(1,[0,0,1,1],'45'))
    selected=result['matching_labels'][0]['candidates'][0]
    ends=[[.275,1/6],[.285,1/6]] if rotation==0 else [[5/6,.275],[5/6,.285]]
    tips=[[.26,1/6],[.3,1/6]] if rotation==0 else [[5/6,.26],[5/6,.3]]
    for actual,want in zip(selected['endpoints'],ends):assert actual==pytest.approx(want,abs=1e-6)
    for actual,want in zip(selected['nearby_filled_triangles_at_each_end'],tips):assert actual[0]['tip_candidate']==pytest.approx(want,abs=1e-6)
    assert selected['length_pdf_points']==pytest.approx(4)
    assert f's{tools.source_digest}-page1-' in selected['path_id']
    ids=[selected['path_id']]+[side[0]['path_id'] for side in selected['nearby_filled_triangles_at_each_end']]
    raw=unpack(tools,tools.drawing_paths(1,[0,0,1,1],ids))
    for side in selected['nearby_filled_triangles_at_each_end']:
        path=next(p for p in raw['paths'] if p['id']==side[0]['path_id'])
        assert side[0]['tip_candidate'] in [v for item in path['items'] for v in item['points']]
    assert 'not a certified arrow' in result['limits'] and 'physical length or unit' in result['limits']


def test_non_numeric_and_absent_labels_cannot_create_dimension_ownership(tmp_path):
    tools=source_pdf(tmp_path)
    with pytest.raises(ValueError):tools.dimension_candidates(1,[0,0,1,1],'plate width')
    result=unpack(tools,tools.dimension_candidates(1,[0,0,1,1],'145'))
    assert not result['matching_labels'] and 'Vision' in result['limits']


def test_missing_arrow_geometry_is_an_explicit_empty_shortlist(tmp_path):
    tools=source_pdf(tmp_path,marks=False)
    result=unpack(tools,tools.dimension_candidates(1,[0,0,1,1],'45'))
    assert result['matching_labels'][0]['candidate_count']==0


def test_equilateral_marks_have_no_claimed_arrow_tip(tmp_path):
    tools=source_pdf(tmp_path,ambiguous=True)
    result=unpack(tools,tools.dimension_candidates(1,[0,0,1,1],'45'))
    assert result['matching_labels'][0]['candidates']
    for label in result['matching_labels']:
        for line in label['candidates']:
            assert all(mark['tip_candidate'] is None for side in line['nearby_filled_triangles_at_each_end'] for mark in side)


def test_many_repeated_labels_use_full_byte_bounded_evidence(tmp_path):
    tools=source_pdf(tmp_path,repeats=18)
    transport=tools.dimension_candidates(1,[0,0,1,1],'45')
    assert transport['paged']
    result=unpack(tools,transport)
    assert len(result['matching_labels'])==18
    assert all(l['selection_limit']==6 and len(l['candidates'])<=6 for l in result['matching_labels'])
