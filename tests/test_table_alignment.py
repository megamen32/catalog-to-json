"""Fast unit/focused integration: positional table false diffs; expected2s/max20s.

Reproduces small4-style spec9 vs panel4 reorder; ambiguous identity blocks.
"""
from catalog_json.audit import compare_source,align_tables
from catalog_json.schema import Table,Column,Row,Cell
from catalog_json.tools import CatalogTools
from test_contract import content,review
from test_tools import pdf


def table(title,columns,rows=1,value='A'):
    return Table(id='generated',title=title,columns=[Column(id=str(i),label=f'Header {i}') for i in range(columns)],
                 rows=[Row(cells=[Cell(column_id=str(i),value=value) for i in range(columns)]) for _ in range(rows)])


def test_spec9_vs_panel4_reorder_has_no_automatic_cell_differences():
    a=content();a.tables=[table('Project specification',9,3),table('Demo panel',4,2)]
    b=a.model_copy(deep=True);b.tables.reverse()
    assert align_tables(a,b)==([(0,1),(1,0)],[],[])
    assert not compare_source(a,b)
    b.tables[1].rows[1].cells[2].value='wrong'
    differences=compare_source(a,b)
    assert len(differences)==1 and differences[0]['path']=='tables[1].rows[1].cells[column=2].value'


def test_generated_ids_and_position_cannot_disambiguate_identical_layouts():
    a=content();a.tables=[table('',4,value='first'),table('',4,value='second')]
    b=a.model_copy(deep=True);b.tables.reverse()
    differences=compare_source(a,b)
    assert [d['path'] for d in differences]==['tables.alignment']
    assert align_tables(a,b)==([], [0,1], [0,1])


def test_unique_full_headers_align_untitled_tables():
    a=content();a.tables=[table('',3),table('',3)]
    a.tables[1].columns[0].label='Different parameter'
    b=a.model_copy(deep=True);b.tables.reverse()
    assert not compare_source(a,b)


def test_single_table_retains_detailed_wrong_unit_and_cell_checks():
    a=content();b=content();b.tables[0].columns[0].unit='кА';b.tables[0].rows[0].cells[0].value=999
    paths=[d['path'] for d in compare_source(a,b)]
    assert any(p.endswith('.unit') for p in paths) and any(p.endswith('.value') for p in paths)


def test_missing_and_unmatched_table_are_blocking_without_cross_table_cell_noise():
    a=content();a.tables=[table('A',9,3),table('B',4,2)]
    b=a.model_copy(deep=True);b.tables=[table('new',5,1)]
    paths=[d['path'] for d in compare_source(a,b)]
    assert paths==['tables','tables.alignment']


def test_review_counts_use_independently_aligned_candidate_order(tmp_path):
    source=pdf(tmp_path);out=tmp_path/'out'
    observed=content();observed.tables=[table('Spec',9,3),table('Panel',4,2)]
    candidate=observed.model_copy(deep=True);candidate.tables.reverse()
    t=CatalogTools(source,out);t.render(1);t.direct(1)
    assert t.save(1,candidate.model_dump_json(),'page')['saved']
    r=CatalogTools(source,out,role='reviewer');r.render(1)
    assert r.save(1,observed.model_dump_json(),'observation')['saved']
    disclosed=r.read(1,'page');assert not disclosed['independent_comparison']
    report=review();report.observed_table_count=2;report.observed_row_counts=[2,3];report.observed_column_counts=[4,9]
    assert r.save(1,report.model_dump_json(),'review')['saved']
