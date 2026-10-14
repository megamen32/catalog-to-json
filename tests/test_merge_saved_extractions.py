"""Fast unit checks for scoped writes from independently retained decisions.

Purpose: prevent stale or wrongly bound consensus from changing another field.
Expected2s, emergency20s. Full980-page ZIP readback is focused integration.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('catalogue_merge', Path(__file__).resolve().parents[1] / 'ops/catalogue_delivery/merge_saved_extractions.py')
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)


@pytest.fixture
def inputs():
    pointer = '/catalogs/0/pages/0/content/tables/0/rows/0/cells/0'
    cell = {'column_id': 'code', 'value': 'SH-lll', 'state': 'value'}
    bundle = {'catalogs': [{'id': 'test', 'pages': [{'source_sha256': 'a'*64, 'pdf_page': 3,
                'content_canonical_sha256': 'b'*64, 'reviewed_current_content': True,
                'content': {'tables': [{'rows': [{'cells': [cell]}]}]}}]}]}
    case = {'case_id': 'case', 'source_sha256': 'a'*64, 'physical_pages': [3],
            'ours': [{'fact_id': 'our', 'pointer': pointer, 'value': 'SH-lll'}],
            'oleg': [{'fact_id': 'oleg', 'value': 'SH-III', 'raw_semantic_context': {'value_state': 'literal'}}]}
    opinions = {role: {'decision': 'oleg', 'reason': 'fixture source review'} for role in merge.ROLES}
    record = {'case': case, 'pack_sha256': 'c'*64, 'complete': True, 'accepted': True,
              'decision': 'oleg', 'opinions': opinions, 'actual_rounds': dict.fromkeys(merge.ROLES, 1),
              'votes': {role: {'identity': {'role': role, 'session_id': 'test', 'model': 'fixture'},
                                'round_number': 1, 'receipt_sha256': 'd'*64} for role in merge.ROLES}}
    return bundle, record


def test_changed_field_keeps_original_full_page_review_binding(inputs):
    bundle, record = inputs
    changes, dispositions = merge.apply_accepted(bundle, [record])
    page = bundle['catalogs'][0]['pages'][0]
    assert changes[0]['before']['value'] == 'SH-lll'
    assert changes[0]['after']['value'] == 'SH-III'
    assert page['reconciliation']['original_content_sha256'] == 'b'*64
    assert page['reviewed_current_content'] is False
    assert set(changes[0]['reviewers']) == set(merge.ROLES)
    assert dispositions['oleg'][0]['decision'] == 'oleg'


@pytest.mark.parametrize('defect', ['source', 'page', 'old_value', 'outside_cell'])
def test_refuse_stale_or_wrong_target(inputs, defect):
    bundle, record = inputs
    if defect == 'source': record['case']['source_sha256'] = 'e'*64
    if defect == 'page': record['case']['physical_pages'] = [4]
    if defect == 'old_value': record['case']['ours'][0]['value'] = 'different'
    if defect == 'outside_cell': record['case']['ours'][0]['pointer'] = '/catalogs/0/pages/0/title'
    with pytest.raises(ValueError):
        merge.apply_accepted(bundle, [record])


def test_disagreement_never_changes_source_cell(inputs):
    bundle, record = inputs
    before = copy.deepcopy(bundle)
    record['accepted'] = False
    assert merge.apply_accepted(bundle, [record]) == ([], {})
    assert bundle == before


@pytest.fixture
def joint_inputs(tmp_path):
    from catalog_json.reconciliation.joint_scope import make_variant_proposal
    from catalog_json.reconciliation.consensus import save_vote, PROVIDER_MODELS
    option = {'fact_id': 'L', 'owner': 'C3', 'name': 'wire', 'value': 'AC25\nAC35'}
    records = [{'complete': True, 'accepted': False, 'pack_sha256': str(i)*64,
        'decision': 'unresolved', 'opinions': {'minimax': {'decision': 'oleg'}},
        'case': {'case_id': f'C{i}', 'kind': 'technical', 'source_sha256': 'a'*64,
            'physical_pages': [1], 'ours': [{'fact_id': f'O{i}', 'owner': 'C3',
                'name': 'wire', 'value': value, 'pointer': f'/rows/{i}'}], 'oleg': [option]}}
        for i, value in enumerate(('AC25', 'AC35'))]
    pack = make_variant_proposal(records, pack_id='joint')
    file = tmp_path/'pack.json'; file.write_text(merge.dump(pack))
    manifest = {'required_roles': list(merge.ROLES), 'standalone_glm': False, 'packs': [{
        'path': str(file), 'file_sha256': merge.sha(file), 'pack_sha256': merge.case_sha256(pack),
        'covered_original_cases': ['C0', 'C1'], 'minimax_round': 1,
        'selected_native_opinion_rounds': {'codex': 1, 'zcode': 1}}]}
    (tmp_path/'joint-scope-ready-manifest.json').write_text(merge.dump(manifest))
    payload = {'pack_id': 'joint', 'verdicts': [{'case_id': pack['cases'][0]['case_id'],
        'case_sha256': merge.case_sha256(pack['cases'][0]), 'decision': 'both',
        'reason': 'Both scopes supported by fixture source', 'source_evidence': [{
            'source_sha256': 'a'*64, 'page': 1, 'observation': 'Two separate variant rows'}]}]}
    def voice(role, decision='both'):
        p = copy.deepcopy(payload); p['verdicts'][0]['decision'] = decision
        save_vote(pack, p, identity={'role': role, 'session_id': role+'-fixture',
            'model': PROVIDER_MODELS.get(role, 'fixture'), 'runtime': 'test'},
            sources={'a'*64: {'page_count': 1}}, output_dir=tmp_path/'adjudication', round_number=1)
    return records, voice


def test_joint_resolution_requires_all_three_and_keeps_original_disagreement(tmp_path, joint_inputs):
    records, voice = joint_inputs
    voice('codex'); voice('zcode')
    assert merge.joint_approvals(tmp_path, tmp_path, records) == []
    voice('minimax')
    before = copy.deepcopy(records)
    approvals = merge.joint_approvals(tmp_path, tmp_path, records)
    assert len(approvals) == 1
    dispositions = merge.apply_joint_resolutions(records, approvals)
    for actual, original in zip(records, before):
        assert actual['resolved']
        assert actual['case'] == original['case']
        assert actual['opinions'] == original['opinions']
        assert actual['accepted'] is False
        assert actual['decision'] == 'unresolved'
    assert dispositions['L'][0]['decision'] == 'both'
    records[0]['case']['ours'][0]['value'] = 'AC250'
    with pytest.raises(ValueError): merge.apply_joint_resolutions(records, approvals)


def test_joint_two_against_one_never_resolves(tmp_path, joint_inputs):
    records, voice = joint_inputs
    voice('codex'); voice('zcode'); voice('minimax', 'oleg')
    assert merge.joint_approvals(tmp_path, tmp_path, records) == []
    assert not any(r.get('resolved') for r in records)


def test_fresh_scope_proof_prevents_old_scalar_choice_from_overwriting_variant(inputs):
    bundle, record = inputs
    before = copy.deepcopy(bundle)
    record['joint_resolution'] = {'decision': 'both', 'proof_sha256': 'e'*64}
    assert merge.apply_accepted(bundle, [record]) == ([], {})
    assert bundle == before
