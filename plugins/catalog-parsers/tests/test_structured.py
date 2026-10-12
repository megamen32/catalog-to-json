"""Fast unit: native span and missing-evidence regression, expected 1s/max 5s."""
from catalog_parsers.structured import html_tables, from_liteparse


def test_html_spans_do_not_turn_missing_cell_into_blank():
    t=html_tables('<table><tr><th>Name</th><th>Voltage, kV</th><th>Note</th></tr><tr><td>A</td><td rowspan="2">10</td><td></td></tr><tr><td>B</td></tr></table>')[0]
    assert [r['cells'][1]['value'] for r in t['rows']]==['10','10']
    assert t['rows'][0]['cells'][2]['state']=='blank'
    assert t['rows'][1]['cells'][2]['state']=='unknown'


def test_liteparse_padding_does_not_claim_source_blank():
    t=from_liteparse({'pages':[{'blocks':[{'kind':'table','header':[{'text':'Name'},{'text':'Value'}],'rows':[[{'text':'A','bbox':{'width':2,'height':2}},{'text':'','bbox':None}]]}]}]})['tables'][0]
    assert t['rows'][0]['cells'][1]['state']=='unknown'
