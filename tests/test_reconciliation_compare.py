from catalog_json.reconciliation.compare import compare_facts, designation, property_label, unit_identity, value_identity


def fact(side, name, value, **extra):
    return dict(side=side, kind='model_parameter', source_sha256='source',
                physical_pages=[78], owner='C3', name=name, value=value,
                unit='мм', condition='', fact_id=side+name, **extra)


def test_geometry_capitals_and_confusable_codes_stay_distinct():
    assert property_label('D') != property_label('d')
    assert property_label('Диаметр D1, мм', 'мм') != property_label('Диаметр d1, мм', 'мм')
    assert designation('C3') != designation('С3')
    assert designation('Ab') != designation('AB')
    assert unit_identity('МПа') != unit_identity('мПа')


def test_typed_scalar_representation_is_retained_as_a_case():
    left = fact('ours', 'D', 12)
    right = fact('oleg', 'D', '12,0')
    ledger, cases = compare_facts([left, right])
    assert ledger[0]['status'] == 'representation_difference'
    assert cases[0]['ours'][0]['value'] == 12
    assert cases[0]['oleg'][0]['value'] == '12,0'
    assert value_identity('0012') != value_identity(12)


def test_overlapping_observations_are_all_kept_and_disagreement_not_hidden():
    left = fact('ours', 'D', '12')
    right = fact('oleg', 'D', '12')
    duplicate = {**right, 'fact_id': 'second-window', 'value': '13'}
    ledger, cases = compare_facts([left, right, duplicate])
    assert ledger[0]['status'] == 'ambiguous_alignment'
    assert len(cases[0]['oleg']) == 2


def test_empty_source_location_is_not_turned_into_a_fake_page():
    left = fact('ours', 'D', '12')
    right = {**fact('oleg', 'D', '12'), 'physical_pages': []}
    ledger, _ = compare_facts([left, right])
    assert [x['status'] for x in ledger] == ['unmatched_ours_observation', 'unmatched_oleg_observation']
