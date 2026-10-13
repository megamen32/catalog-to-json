"""Focused integration: drawing lines/words must align with the viewer, not guess a part.

Detects zero-width line loss and rotated coordinate mismatch; expected 2s/max10s.
"""
import json
import pytest
import pymupdf
from catalog_json.tools import CatalogTools


@pytest.mark.parametrize('rotation',[0,90])
def test_actual_source_line_endpoints_survive_rotation_and_box_selection(tmp_path,rotation):
    source=tmp_path/'source.pdf'
    with pymupdf.open() as document:
        p=document.new_page(width=400,height=600)
        p.draw_line((60,200),(240,200));p.insert_text((95,190),'500')
        p.set_rotation(rotation);document.save(source)
    tools=CatalogTools(source,tmp_path/'output')
    box=[.1,.28,.7,.36] if not rotation else [.63,.1,.73,.7]
    inventory=tools.drawing_geometry(1,box)
    result=tools.drawing_paths(1,box,[p['id'] for p in inventory['path_index']])
    assert inventory['words']['words'][0]['text']=='500'
    lines=[i['points'] for path in result['paths'] for i in path['items'] if i['kind']=='l']
    expected=[[.15,1/3],[.6,1/3]] if not rotation else [[2/3,.15],[2/3,.6]]
    assert any(all(point==pytest.approx(want) for point,want in zip(line,expected)) for line in lines)
    again=tools.drawing_geometry(1,box)
    assert [p['id'] for p in result['paths']]==[p['id'] for p in again['path_index']]
    assert 'inferred_feature_name' not in result
    layout=tools.layout(1,box)
    assert layout['words'][0]['text']=='500'
    assert layout['words'][0]['box']==pytest.approx(inventory['words']['words'][0]['box'],abs=.0001)


def test_rotated_native_table_axes_require_image_fallback(tmp_path):
    from catalog_json.grid import table_grids
    with pymupdf.open() as document:
        p=document.new_page();p.set_rotation(90)
        result=table_grids(p,[0,0,1,1])
    assert not result['tables'] and 'rotated' in result['note']


def test_many_separate_solid_segments_reach_agent_without_silent_truncation(tmp_path):
    source=tmp_path/'source.pdf'
    with pymupdf.open() as document:
        p=document.new_page(width=400,height=600)
        for i in range(160):p.draw_line((50+i,150),(50+i,151))
        document.save(source)
    tools=CatalogTools(source,tmp_path/'output')
    paths=[];offset=0
    while offset<160:
        inventory=tools.drawing_geometry(1,[0,0,1,1],offset)
        data=tools.drawing_paths(1,[0,0,1,1],[p['id'] for p in inventory['path_index']])
        if data.get('paged'):
            text='';start=0
            while start<data['total_characters']:
                chunk=tools.source_artifact(1,data['artifact_id'],start);text+=chunk['text'];start=chunk['next_offset']
            data=json.loads(text)
        paths+=data['paths'];offset=inventory['next_offset']
    assert len(paths)==160 and all(path['dashes']=='[] 0' for path in paths)
