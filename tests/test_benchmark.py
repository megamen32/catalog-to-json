"""Fast unit: independently score omissions, blanks, Unicode and numeric formatting. Expected <1 s, max 5 s."""
from catalog_json.benchmark import BenchmarkCase,score_content
from catalog_json.schema import PageContent,Table,Column,Row,Cell,Figure


def fixture():
    return BenchmarkCase.model_validate({'id':'example','source_sha256':'a'*64,'page':1,
        'provenance':'Synthetic independent fixture',
        'tables':[{'rows':[['item-a','2,0',None],['item-b','2,0','Ø127']],
                   'merges':[{'column':1,'rows':[0,1]}]}],
        'headers':[{'table':0,'column':1,'field':'unit','expected':'мм'}],
        'figure_labels':[['H±2','Н±2']]})


def candidate():
    return PageContent(title='',text_blocks=[],figures=[Figure(title='',description='',labels=['H±2'])],
        tables=[Table(id='table',title='',columns=[Column(id='n',label='Name'),Column(id='v',label='H',unit='мм'),Column(id='d',label='D')],
            rows=[Row(cells=[Cell(column_id=c,value=v,state='blank' if v is None else 'value') for c,v in zip(['n','v','d'],row)])
                  for row in [['item-a','2,0',None],['item-b','2,0','Ø127']]])])


def test_semantic_numbers_are_distinct_from_literal_accuracy():
    c=candidate();c.tables[0].rows[0].cells[1].value=2
    r=score_content(fixture(),c)
    assert r['metrics']['cells_literal']['correct']==5
    assert r['metrics']['cells_numeric_equivalent']['correct']==6
    assert r['coverage']['full_page_ground_truth'] is False


def test_false_blank_and_missing_tolerance_are_detected():
    c=candidate();c.tables[0].rows[1].cells[1]=Cell(column_id='v',value=None,state='blank')
    c.figures[0].labels=['H=2']
    r=score_content(fixture(),c)
    assert r['metrics']['merged_cells']['correct']==1
    assert r['metrics']['figure_labels']['correct']==0 and not r['all_verified_checks_passed']


def test_unknown_is_not_a_true_blank_and_extra_tables_are_not_ignored():
    c=candidate();c.tables[0].rows[0].cells[2].state='unknown';c.tables.append(c.tables[0].model_copy(deep=True))
    r=score_content(fixture(),c)
    assert r['metrics']['blank_cells']['correct']==0
    assert r['structure']['extra_tables']==1 and not r['all_verified_checks_passed']


def test_tolerance_two_does_not_match_twenty():
    c=candidate();c.figures[0].labels=['H±20'];c.figures[0].description='Height H±20'
    assert score_content(fixture(),c)['metrics']['figure_labels']['correct']==0
