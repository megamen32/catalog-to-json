"""Fast unit: semantic merge failure shields, expected2s/emergency20s."""
import json

from ops.catalogue_delivery.canonical_merge import adapt, equivalent, identity, prepare_structure, write_comparison, pair_scope


def test_blank_empty_zero_stay_distinct():
    assert not equivalent(None, "")
    assert equivalent(0, "0")
    assert not equivalent(0, "0", numeric=False)
    assert not equivalent(False, 0)
    assert not equivalent("105", "10⁵")
    assert equivalent("17,5", "17.5")


def test_header_condition_does_not_spread_between_rows():
    f={"fact_id":"O-a","catalog":"x","physical_pages":[1],"side":"ours","kind":"model_parameter","owner":"A","name":"Clamp","value":None,"unit":None,"condition":None,"raw_context":"r","metadata":{"column":{"label":"Clamp","group":None}}}
    a=adapt(f,{"r":{"state":"blank"}}, {},"p",{"canonical_scope":{"condition":"wire300/48","state":"blank"}})
    b=adapt({**f,"fact_id":"O-b"},{"r":{"state":"blank"}}, {},"p")
    assert a["condition"]=="wire300/48" and b["condition"] is None
    assert a["value"] is None and b["value"] is None


def test_physical_identity_ignores_page_but_preserves_part_and_condition():
    r=dict(catalog="x",page=1,kind="model_parameter",model="A",parameter="D",part="top",condition="dry",value="50")
    assert identity(r)==identity({**r,"page":9})
    assert identity(r)!=identity({**r,"part":"bottom"})
    assert identity(r)!=identity({**r,"condition":"rain"})


def test_frequency_in_condition_cannot_become_voltage_unit():
    f={"fact_id":"O-a","catalog":"x","physical_pages":[1],"kind":"model_parameter","owner":"A","name":"50 Гц под дождем","value":"80","condition":None,"raw_context":"r","metadata":{"column":{"group":"Выдерживаемое напряжение, кВ"}}}
    a=adapt(f,{"r":{}},{},"p")
    assert a["unit"]=="кВ"


def test_free_text_context_is_not_a_dictionary():
    f={"fact_id":"O-a","catalog":"x","physical_pages":[1],"kind":"page_text","owner":"","name":"","value":"text","raw_context":"r"}
    assert adapt(f,{"r":"text"},{},"p")["value"]=="text"


def test_equal_diameter_keeps_concrete_clamp_and_distinct_scope():
    base = dict(kind='model_parameter', model=None, part=None, condition='АС95/16', unit='мм', state='value')
    assert pair_scope([base, {**base, 'model': 'ОАБ70-120'}]) == {'model': 'ОАБ70-120'}
    assert pair_scope([{**base, 'unit': 'мм2'}, {**base, 'unit': 'мм²'}]) == {}
    for field, a, b in [('model', 'A', 'B'), ('part', 'top', 'bottom'),
                         ('condition', 'АС70/11', 'АС95/16'), ('unit', 'м', 'мм')]:
        assert pair_scope([{**base, field:a}, {**base, field:b}]) is None


def test_comparison_accounts_for_unpaired_observations_without_claiming_absence(tmp_path):
    record = dict(id='C-a', catalog='opn', page=1, kind='model_parameter', model='A',
                  parameter='D', part=None, condition=None, value='50', unit='мм',
                  state='value', source_fact_ids=['O-a'], producer_ref='P-a')
    ours = dict(fact_id='O-a', owner='A', name='D', value='50', unit='мм')
    unpaired = dict(fact_id='L-a', owner='A', name='different source label', value='50', unit='мм')
    group = dict(catalog='opn', page=1, relation='structured_overlap', decision='ours',
                 result_ids=['C-a'], ours=[ours], oleg=[unpaired])
    write_comparison(tmp_path, {'key': record}, [group], {})
    rows = [json.loads(line) for line in (tmp_path / 'comparison.jsonl').read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]['classification'] == 'only_ours_mapped'
    assert rows[1]['classification'] == 'unpaired_source_observation'
    assert rows[1]['result'] is None and rows[1]['original_decision'] == 'ours'
    assert {x['fact_id'] for row in rows for side in ('ours', 'oleg') for x in row[side]} == {'O-a', 'L-a'}
