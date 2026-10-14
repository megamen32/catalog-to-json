"""Focused integration: retained isolators47 metadata loop; expected2s/max20s, no API.

The labels reproduce native reviewer32's title-page inventories. The final
revise must remain writable; a confirmed metadata review needs no drawn arrows.
"""
import pytest
from catalog_json.dimension_review import dimension_targets
from catalog_json.schema import Figure,Issue
from catalog_json.tools import CatalogTools
from test_tools import pdf,content,review
from test_page_context import context,semantic_review


def title_pages():
    c=content();c.tables=[];c.page_context=context('supporting_material',transcription='literal')
    c.figures=[Figure(title='Титульный лист типового проекта: одноцепные опоры',
        description='Титул типового проекта; шифр документа и год корректировки, не чертёж.',
        labels=['ФОРЭНЕРГО ИНЖИНИРИНГ','ТИПОВОЙ ПРОЕКТ',
                'ОДНОЦЕПНЫЕ ЖЕЛЕЗОБЕТОННЫЕ ОПОРЫ ВЛЗ 6-20 кВ',
                'Шифр 1.10-20.МИ.15','Корректировка 2023 г.'])]
    observed=c.model_copy(deep=True)
    observed.figures[0].title='Титульный лист типового проекта 1'
    observed.figures[0].labels=['1.10-20.МИ.15','2023']
    return c,observed


def ready(tmp_path):
    c,observed=title_pages();t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1)
    assert t.save(1,c.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    assert r.save(1,observed.model_dump_json(),'observation')['saved'];r.read(1,'page')
    report=review();report.context_review=semantic_review()
    report.observed_table_count=0;report.observed_row_counts=[];report.observed_column_counts=[]
    return c,r,report


def test_title_metadata_refusal_teaches_independent_flag_not_dimension_arrows(tmp_path):
    _,r,report=ready(tmp_path);refused=r.save(1,report.model_dump_json(),'review')
    assert not refused['saved']
    assert refused['required_context_review_fields']=={'supporting_annotations_verified':True}
    assert 'metadata' in refused['error'].lower()


def test_confirmed_title_metadata_needs_no_geometry_or_matching_label_partition(tmp_path):
    c,r,report=ready(tmp_path);report.context_review.supporting_annotations_verified=True
    assert r.save(1,report.model_dump_json(),'review')['saved']
    assert not r.dimension_reviews
    assert c.figures[0].labels[2].endswith('6-20 кВ')  # Extracted facts stay intact.


def test_retained_unreadable_document_revise_does_not_request_final_pass_geometry(tmp_path):
    _,r,report=ready(tmp_path);report.verdict='revise'
    report.issues=[Issue(severity='warning',path='uncertainties',message='Нечитаемые микрореквизиты исходных сканов не проверены.')]
    assert r.save(1,report.model_dump_json(),'review')['saved']


@pytest.mark.parametrize('title',['Чертёж изделия','Титульный лист типового проекта'])
def test_title_metadata_exception_keeps_real_dimensions_strict(title):
    c,_=title_pages();c.figures[0].title=title
    c.figures[0].labels=['2023','Ø98','98','98 +2/-1','12 мм','L₁']
    labels=[t['label'] for t in dimension_targets(c,supporting_annotations=True)]
    assert labels==(['2023'] if title=='Чертёж изделия' else [])+['Ø98','98','98 +2/-1','12 мм','L₁']
