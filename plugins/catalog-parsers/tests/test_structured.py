"""Fast unit: native span and missing-evidence regression, expected 1s/max 5s."""
from catalog_parsers.structured import html_tables, from_liteparse


def test_native_text_headers_outside_html_are_retained_without_inventing_column_links():
    from catalog_parsers.structured import from_html_blocks
    raw={'blocks':[{'type':'text','content':[{'type':'text','content':'Номинальное напряжение, кВ'}]},{'type':'table_body','content':'<table><tr><td>A</td></tr><tr><td>150</td></tr></table>'}]}
    out=from_html_blocks(raw,'native')
    assert out['text_blocks']==[{'kind':'paragraph','text':'Номинальное напряжение, кВ'}]
    assert out['tables'][0]['columns'][0]['label']=='A'


def test_failed_adaptation_retains_native_source_evidence(tmp_path):
    import json,pytest
    from catalog_parsers.native import retained
    raw={'table_html':'malformed native table'}
    def broken(*args):raise ValueError('overlapping native spans')
    with pytest.raises(ValueError):retained(raw,tmp_path,broken)
    assert json.loads((tmp_path/'native-raw.json').read_text())==raw


def test_html_spans_do_not_turn_missing_cell_into_blank():
    t=html_tables('<table><tr><th>Name</th><th>Voltage, kV</th><th>Note</th></tr><tr><td>A</td><td rowspan="2">10</td><td></td></tr><tr><td>B</td></tr></table>')[0]
    assert [r['cells'][1]['value'] for r in t['rows']]==['10','10']
    assert t['rows'][0]['cells'][2]['state']=='blank'
    assert t['rows'][1]['cells'][2]['state']=='unknown'


def test_liteparse_padding_does_not_claim_source_blank():
    t=from_liteparse({'pages':[{'blocks':[{'kind':'table','header':[{'text':'Name'},{'text':'Value'}],'rows':[[{'text':'A','bbox':{'width':2,'height':2}},{'text':'','bbox':None}]]}]}]})['tables'][0]
    assert t['rows'][0]['cells'][1]['state']=='unknown'


def test_native_thead_with_td_keeps_both_header_rows():
    t=html_tables('<table><thead><tr><td rowspan="2">Name</td><td>Voltage</td></tr><tr><td>kV</td></tr></thead><tbody><tr><td>A</td><td>10</td></tr></tbody></table>')[0]
    assert len(t['rows'])==1
    assert t['columns'][1]['group']=='Voltage'
    assert t['columns'][1]['label']=='kV'


def test_row_headers_in_body_remain_body():
    t=html_tables('<table><thead><tr><th>Model</th><th>Voltage</th></tr></thead><tbody><tr><th scope="row">A</th><td>10</td></tr><tr><th scope="row">B</th><td>20</td></tr></tbody></table>')[0]
    assert len(t['rows'])==2
    assert t['columns'][0]['label']=='Model'


def test_missing_multiindex_level_stays_null():
    from catalog_parsers.structured import header_levels
    assert header_levels((float('nan'),'Name'))==[None,'Name']
