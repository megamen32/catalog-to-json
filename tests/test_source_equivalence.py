"""Fast unit: OPN27 false review refusals; expected <1s/max5s.

Keep explicit wrong units, condition units, identifiers and drawing dimensions fatal.
"""
import pytest
from catalog_json.audit import compare_source
from catalog_json.schema import PageContent


def page(label='Напряжение',unit='кВ',group=None,qualifier=None,value='47,5',figure=None):
    return PageContent.model_validate({'title':'Source comparison','text_blocks':[],'tables':[{'id':'t','title':'',
        'columns':[{'id':'c','label':label,'unit':unit,'group':group,'qualifier':qualifier}],
        'rows':[{'cells':[{'column_id':'c','value':value,'state':'value'}]}]}],
        'figures':[{'title':'Drawing','description':figure,'labels':[figure]}] if figure else []})


@pytest.mark.parametrize('observed,candidate',[
    (page(value=47.5),page()),
    (page(label='Напряжение, кВ',unit=None),page()),
    (page(label='Тепловая энергия, кДж/кВ, не менее',unit=None),page(label='Тепловая энергия',unit='кДж/кВ',qualifier='не менее')),
    (page(label='Напряжение (кВ), при импульсе 10 кА длительностью 1/10 мкс',unit=None),page(label='Напряжение при импульсе 10 кА длительностью 1/10 мкс')),
    (page(figure='φ13'),page(figure='φ13 2 отв.')),
    (page(figure='φ98'),page(figure='Ø98')),
    (page(figure='67,5'),page(figure='67.5')),
])
def test_source_equivalent_representation_does_not_block_review(observed,candidate):
    assert not compare_source(observed,candidate)


@pytest.mark.parametrize('observed,candidate',[
    (page(),page(unit='кА')),
    (page(unit='кДж/кВ'),page(unit='кДжкВ')),
    (page(unit='МПа'),page(unit='мПа')),
    (page(label='250 А',unit=None,group='Напряжение (В)'),page(label='250 А',unit='А',group='Напряжение (В)')),
    (page(label='50 кН',unit=None,group='Давление, МПа'),page(label='50 кН',unit='кН',group='Давление, МПа')),
    (page(label='Напряжение (кВ), при импульсе 10 кА',unit=None),page(label='Напряжение (кВ), при импульсе 10 кА',unit='кА')),
    (page(label='Условие 8/20, значение',unit=None),page(label='Условие 8/20 мкс, значение',unit=None)),
    (page(qualifier='не менее'),page(qualifier='не более')),
    (page(qualifier='≥'),page(qualifier='≤')),
    (page(label='Напряжение при токе ≥10 кА'),page(label='Напряжение при токе ≤10 кА')),
    (page(label='Напряжение для частоты <50 Гц'),page(label='Напряжение для частоты >50 Гц')),
    (page(value='127'),page(value='104')),
    (page(label='Обозначение изделия',unit=None,value='001'),page(label='Обозначение изделия',unit=None,value=1)),
    (page(label='Значение',group='Код изделия',unit=None,value=1),page(label='Значение',group='Код изделия',unit=None,value='1,0')),
    (page(figure='φ13'),page(figure='φ130 2 отв.')),
    (page(figure='H±2'),page(figure='H±20')),
    (page(figure='476'),page(figure='47.6')),
])
def test_semantic_changes_still_block_review(observed,candidate):
    assert compare_source(observed,candidate)
