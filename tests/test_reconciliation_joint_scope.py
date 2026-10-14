"""Fast unit: prevent lossy option-list merges; expected1s, maximum10s."""
import copy
import pytest
from catalog_json.reconciliation.joint_scope import make_variant_proposal, validate_variant_proposal


def records():
    option = {'fact_id': 'L-list', 'side': 'oleg', 'owner': 'C3', 'name': 'Wire',
              'value': 'AC25\nAC35', 'unit': None, 'condition': None}
    result = []
    for i, value in enumerate(['AC25', 'AC35']):
        atom = {'fact_id': f'O-{i}', 'side': 'ours', 'owner': 'C3', 'name': 'Wire',
                'value': value, 'pointer': f'/rows/{i}', 'unit': None, 'condition': None}
        result.append({'complete': True, 'pack_sha256': str(i)*64,
            'case': {'case_id': f'C-{i}', 'source_sha256': 'a'*64,
                     'physical_pages': [118], 'ours': [atom], 'oleg': [option]}})
    return result


def test_exact_members_preserve_every_variant_and_original_case():
    rows = records(); before = copy.deepcopy(rows)
    pack = make_variant_proposal(rows, pack_id='joint')
    proposal = validate_variant_proposal(pack, rows)
    assert rows == before
    assert len(proposal['covered_original_cases']) == 2
    raw = pack['cases'][0]['oleg'][0]['value']
    assert [raw[x['member_start']:x['member_end']] for x in proposal['bindings'][0]['members']] == ['AC25', 'AC35']
    assert [a['value'] for a in pack['cases'][0]['ours']] == ['AC25', 'AC35']


@pytest.mark.parametrize('defect', ['missing_variant', 'different_model', 'changed_member', 'ambiguous_duplicate'])
def test_unproven_membership_is_refused(defect):
    rows = records()
    if defect == 'missing_variant': rows.pop()
    if defect == 'different_model': rows[1]['case']['ours'][0]['owner'] = 'С3'
    if defect == 'changed_member': rows[1]['case']['ours'][0]['value'] = 'AC350'
    if defect == 'ambiguous_duplicate':
        duplicate = copy.deepcopy(rows[0]); duplicate['case']['ours'][0]['fact_id'] = 'O-another';rows.append(duplicate)
    with pytest.raises(ValueError): make_variant_proposal(rows, pack_id='joint')


def test_changed_proposal_cannot_borrow_earlier_review():
    rows = records(); pack = make_variant_proposal(rows, pack_id='joint')
    pack['cases'][0]['proposal']['bindings'][0]['members'][0]['member_end'] += 1
    with pytest.raises(ValueError): validate_variant_proposal(pack, rows)
