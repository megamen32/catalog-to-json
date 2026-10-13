"""Fast unit: contradictory feedback cannot erase tables. Expected 1s, max 5s."""
from catalog_json.schema import PageContent, Review, Check
from catalog_json.review_consistency import structural_disagreements


def test_passed_counts_cannot_disagree_with_observer():
    observation=PageContent(title='specification',text_blocks=[],tables=[],figures=[])
    report=Review(verdict='revise',checks=[Check(category='table_count',passed=True,evidence='Four tables verified')],
                  issues=[],observed_table_count=4,observed_row_counts=[24,2,2,2],observed_column_counts=[9,3,3,3])
    conflicts=structural_disagreements(observation,report)
    assert {c['category'] for c in conflicts}=={'table_count','row_coverage','column_coverage'}
    report.checks[0].passed=False
    assert structural_disagreements(observation,report)==conflicts


def test_corrected_observation_can_save_without_weakening_real_mismatch(tmp_path):
    from test_tools import pdf,content,review
    from catalog_json.tools import CatalogTools
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1)
    assert t.save(1,content().model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    wrong=content();wrong.tables=[]
    assert r.save(1,wrong.model_dump_json(),'observation')['saved'];r.read(1,'page')
    report=review();report.verdict='revise'
    refused=r.save(1,report.model_dump_json(),'review')
    assert not refused['saved'] and refused['review_disagreements']
    assert not (r.work(1)/'review-0.json').exists()
    r.render(1,[0,0,1,1]);assert r.correct_observation(1,content().model_dump_json(),'Original crop confirms table')['saved']
    assert r.save(1,review().model_dump_json(),'review')['saved']
