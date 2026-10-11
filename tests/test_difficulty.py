"""Fast unit: select varied difficult cases without treating heuristic scores as accuracy. Expected <1 s, max 5 s."""
import pymupdf
from catalog_json.difficulty import page_features,select_cases


def test_rotation_and_grid_are_detected():
    with pymupdf.open() as d:
        p=d.new_page();p.insert_text((80,180),'rotated heading',rotate=90)
        for y in range(200,400,10):p.draw_line((50,y),(500,y))
        for x in range(50,501,30):p.draw_line((x,200),(x,400))
        f=page_features(p)
        assert f['rotated_lines'] and f['horizontal_rules']>=20
        assert 'rotated_text' in f['tags'] and 'ruled_tables' in f['tags']


def test_selection_includes_anchor_and_varied_catalogs():
    records=[{'source':'a.pdf','page':n,'score':100-n,'tags':['ruled_tables']} for n in range(1,8)]
    records += [{'source':'b.pdf','page':1,'score':30,'tags':['rotated_text']}]
    picked=select_cases(records,per_catalog=2,anchors={('a.pdf',7)})
    assert ('a.pdf',7) in {(r['source'],r['page']) for r in picked}
    assert len([r for r in picked if r['source']=='a.pdf'])==2
    assert any(r['source']=='b.pdf' for r in picked)


def test_changed_detector_does_not_reuse_stale_inventory(tmp_path,monkeypatch):
    """Fast unit: corpus ranking cache must follow the detector revision. Expected <1 s, max 5 s."""
    import catalog_json.difficulty as module
    source=tmp_path/'sample.pdf'
    with pymupdf.open() as d:d.new_page();d.save(source)
    monkeypatch.setattr(module,'page_features',lambda page:{'score':1,'tags':[]})
    first=module.scan_catalogs([source],tmp_path/'out')
    monkeypatch.setattr(module,'page_features',lambda page:{'score':2,'tags':[]})
    second=module.scan_catalogs([source],tmp_path/'out')
    assert first['pages'][0]['score']==1 and second['pages'][0]['score']==2
