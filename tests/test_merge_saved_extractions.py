"""Fast unit checks for scoped writes from independently retained decisions.

Purpose: prevent stale or wrongly bound consensus from changing another field.
Expected2s, emergency20s. Full980-page ZIP readback is focused integration.
"""
import copy
import importlib.util
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
