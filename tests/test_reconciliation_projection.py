from copy import deepcopy

import pytest

from catalog_json.reconciliation.consensus import case_sha256, validate_vote, build_consensus
from catalog_json.reconciliation.projection import project_vote


def inputs():
    sha = 'a' * 64
    cases = [{'case_id': name, 'kind': 'numeric', 'source_sha256': sha,
              'physical_pages': [1], 'ours': [{'value': 12}], 'oleg': [{'value': 13}]}
             for name in ('one', 'two')]
    pack = {'schema_version': 'test/1', 'pack_id': 'parent', 'cases': cases}
    payload = {'pack_id': 'parent', 'verdicts': [
        {'case_id': c['case_id'], 'case_sha256': case_sha256(c), 'decision': 'unresolved',
         'reason': 'Uncertain original; no value was selected.', 'source_evidence': []} for c in cases]}
    vote = validate_vote(pack, payload, identity={'role': 'codex', 'session_id': 'original-session',
                         'model': 'actual-native-model', 'runtime': 'native'},
                         sources={sha: {'sha256': sha, 'page_count': 2}})
    vote['round_number'] = 2
    vote.pop('receipt_sha256'); vote['receipt_sha256'] = case_sha256(vote)
    child = {'schema_version': 'test/1', 'pack_id': 'child', 'cases': [deepcopy(cases[0])]}
    return pack, vote, child


def test_projection_preserves_actual_opinion_identity_round_and_uncertainty():
    parent, vote, child = inputs()
    before = deepcopy(vote)
    result = project_vote(parent, vote, child)
    assert vote == before
    assert result['identity'] == vote['identity']
    assert result['round_number'] == 2
    assert result['payload']['verdicts'] == [vote['payload']['verdicts'][0]]
    assert result['projection']['parent_receipt_sha256'] == vote['receipt_sha256']
    assert result['projection']['new_model_calls'] == 0
    assert not result['projection']['new_independent_voice']
    assert build_consensus(child, [result])['cases'][0]['decision'] == 'unresolved'


@pytest.mark.parametrize('changed', ['value', 'page', 'question', 'case_id'])
def test_changed_input_cannot_reuse_an_old_opinion(changed):
    parent, vote, child = inputs()
    c = child['cases'][0]
    if changed == 'value': c['ours'][0]['value'] = 99
    elif changed == 'page': c['physical_pages'] = [2]
    elif changed == 'question': c['question'] = 'A different question'
    else: c['case_id'] = 'not-reviewed'
    with pytest.raises(ValueError, match='identical case'):
        project_vote(parent, vote, child)


def test_tampered_parent_is_refused():
    parent, vote, child = inputs()
    vote['payload']['verdicts'][0]['decision'] = 'ours'
    with pytest.raises(ValueError, match='receipt'):
        project_vote(parent, vote, child)


def test_historical_glm_projection_requires_explicit_legacy_profile():
    from catalog_json.reconciliation.consensus import LEGACY_REQUIRED_ROLES, PROVIDER_MODELS
    parent, vote, child = inputs()
    vote['identity'].update(role='glm', model=PROVIDER_MODELS['glm'])
    vote.pop('receipt_sha256')
    vote['receipt_sha256'] = case_sha256(vote)
    with pytest.raises(ValueError):
        project_vote(parent, vote, child)
    result = project_vote(parent, vote, child, required_roles=LEGACY_REQUIRED_ROLES)
    assert result['identity'] == vote['identity']
    assert result['round_number'] == vote['round_number']
    assert result['projection']['new_model_calls'] == 0
