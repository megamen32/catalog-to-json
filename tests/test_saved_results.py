"""Fast unit: saved imports preserve defects, identity and blanks. Expected <1 s, max 5 s."""
import pytest
from catalog_json.saved_results import import_page


def records():
    products=[{'product_id':'p','product_name':'item','source_document_id':'doc',
               'physical_pages':[2],'printed_page_labels':['1']}]
    chars=[{'product_id':'p','source_document_id':'doc','physical_page':2,
            'characteristic_name':'H, мм','raw_value':'1600','unit_of_measurement':'кВ',
            'value_state':'printed_value','source_evidence_reference':{'table_id':'t1','row':1,'column':1}}]
    return products,chars


def test_unit_and_composite_header_are_not_repaired():
    p,c=records();c[0]['characteristic_name']='Voltage, кВ\nH, мм'
    page,meta=import_page(p,c,[],'doc',2)
    assert page.tables[0].columns[1].label=='Voltage, кВ\nH, мм'
    assert page.tables[0].columns[1].unit=='кВ'
    assert page.tables[0].rows[0].cells[0].value=='item'
    assert not meta['runtime_verified'] and meta['model'] is None


def test_missing_is_unknown_and_explicit_blank_is_blank():
    p,c=records();other=dict(c[0],raw_value='',value_state='source_blank',
                           source_evidence_reference={'table_id':'t1','row':2,'column':2})
    page,_=import_page(p,c+[other],[],'doc',2)
    assert page.tables[0].rows[0].cells[2].state=='unknown'
    assert page.tables[0].rows[1].cells[2].state=='blank'
    assert page.tables[0].rows[1].cells[1].state=='unknown'


def test_conflicting_duplicate_is_not_cherry_picked():
    p,c=records();other=dict(c[0],raw_value='1700')
    page,meta=import_page(p,c+[other],[],'doc',2)
    assert page.tables[0].rows[0].cells[1].state=='unknown'
    assert meta['conflicting_coordinates']==1


def test_source_document_and_page_are_both_filtered():
    p,c=records();wrong=dict(c[0],source_document_id='other',raw_value='wrong')
    page,meta=import_page(p,c+[wrong],[],'doc',2)
    assert page.tables[0].rows[0].cells[1].value=='1600'
    assert meta['selected_characteristics']==1
    with pytest.raises(ValueError):import_page(p,c,[],'doc',0)
