"""Reuse an existing opinion only for byte-identical canonical case inputs.

Projection is not another model run or another independent voice. The original
role, session, model, round and authored timestamp remain attributable.
"""
from copy import deepcopy

from .consensus import build_consensus, case_sha256, validate_pack, validate_vote


def project_vote(parent_pack, parent_vote, child_pack):
    # Reuses all receipt, identity, source and complete-batch validation gates.
    build_consensus(parent_pack, [parent_vote])
    validate_pack(child_pack)
    originals = {c['case_id']: c for c in parent_pack['cases']}
    for case in child_pack['cases']:
        if case['case_id'] not in originals or case_sha256(case) != case_sha256(originals[case['case_id']]):
            raise ValueError('Projection requires identical case IDs and exact complete case SHAs')
    selected = {c['case_id'] for c in child_pack['cases']}
    payload = {'pack_id': child_pack['pack_id'],
               'verdicts': [deepcopy(v) for v in parent_vote['payload']['verdicts'] if v['case_id'] in selected]}
    sources = {s['sha256']: s for s in parent_vote['source_manifest']}
    result = validate_vote(child_pack, payload, identity=deepcopy(parent_vote['identity']), sources=sources)
    result['round_number'] = parent_vote.get('round_number', 1)
    result['projection'] = {
        'parent_pack_sha256': case_sha256(parent_pack),
        'parent_receipt_sha256': parent_vote['receipt_sha256'],
        'original_opinion_saved_at': parent_vote['saved_at'],
        'case_sha256': {c['case_id']: case_sha256(c) for c in child_pack['cases']},
        'new_model_calls': 0,
        'new_independent_voice': False,
    }
    result.pop('receipt_sha256')
    result['receipt_sha256'] = case_sha256(result)
    return result
