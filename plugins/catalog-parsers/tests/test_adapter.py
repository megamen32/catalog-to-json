"""Fast unit: preserve composite fields, parser spans and missing evidence; expected <1s, max 5s."""
from catalog_parsers.adapter import from_pymupdf,from_docling


def test_missing_is_unknown_and_composite_header_is_not_repaired():
    r=from_pymupdf({'pages':[{'boxes':[{'table':{'col_count':2,'extract':[['Name','Height / mass'],['A',None],['B','']]}}]}]})
    t=r['tables'][0]
    assert t['columns'][1]['label']=='Height / mass'
    assert t['rows'][0]['cells'][1]['state']=='unknown'
    assert t['rows'][1]['cells'][1]['state']=='blank'


def test_docling_reported_span_expands_only_existing_cell_text():
    def c(text,r0,r1,c0,c1,header=False):return {'text':text,'start_row_offset_idx':r0,'end_row_offset_idx':r1,'start_col_offset_idx':c0,'end_col_offset_idx':c1,'column_header':header}
    r=from_docling({'tables':[{'data':{'num_rows':3,'num_cols':2,'table_cells':[c('Name',0,1,0,1,True),c('Voltage, kV',0,1,1,2,True),c('A',1,2,0,1),c('B',2,3,0,1),c('10',1,3,1,2)]}}]})
    assert [row['cells'][1]['value'] for row in r['tables'][0]['rows']]==['10','10']
    assert r['tables'][0]['columns'][1]['unit'] is None
