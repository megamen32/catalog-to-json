"""Fast unit: block incomplete review and malformed tables. Expected <1 s, max 5 s."""
import pytest
from pydantic import ValidationError
from catalog_json.schema import PageContent,Table,Column,Row,Cell,Review,Check,CHECKS
from catalog_json.direct import parse_anydoc
from catalog_json.cli import parse_pages
from catalog_json.export import to_xlsx


def content():
    return PageContent(title='Example',text_blocks=[],figures=[],tables=[Table(id='t',title='Table',columns=[Column(id='c',label='Масса, кг')],rows=[Row(cells=[Cell(column_id='c',value=80)])])])


def review():
    return Review(verdict='pass',checks=[Check(category=c,passed=True,evidence='Compared against original') for c in sorted(CHECKS)],issues=[],observed_table_count=1,observed_row_counts=[1],observed_column_counts=[1])


def test_review_must_check_every_category():
    r=review();assert r.accepts(content());r.checks.pop();assert not r.accepts(content())


def test_independent_counts_cannot_hide_omissions():
    r=review();r.observed_row_counts=[2];assert not r.accepts(content())


def test_uncertain_cell_cannot_be_accepted():
    d=content();d.tables[0].rows[0].cells[0]=Cell(column_id='c',value=None,state='unknown');assert not review().accepts(d)


def test_ragged_and_duplicate_cells_fail():
    with pytest.raises(ValidationError):Table(id='t',title='t',columns=[Column(id='a',label='a'),Column(id='b',label='b')],rows=[Row(cells=[Cell(column_id='a',value=1)])])


def test_blank_is_not_zero():
    d=parse_anydoc('| Модель | Масса, кг |\n|---|---|\n| A | |\n| B | 0 |')
    assert d.tables[0].rows[0].cells[1].value is None
    assert d.tables[0].rows[1].cells[1].value=='0'


def test_unreviewed_export_refused(tmp_path):
    with pytest.raises(ValueError):to_xlsx({'complete_for_selection':False,'pages':[]},tmp_path/'bad.xlsx')


def test_page_selection_rejects_duplicates():
    with pytest.raises(ValueError):parse_pages('1,1',5)
    assert parse_pages('1,3-4',5)==[1,3,4]
