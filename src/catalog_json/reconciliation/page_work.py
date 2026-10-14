"""A single owner's complete page merge; independent final review stays pending.

All selections reference immutable typed input facts. This is work output, never
a fabricated three-party verdict or permission to erase original alternatives.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .consensus import case_sha256, validate_identity

RELATIONS = {'same_fact', 'variant_options', 'separate_contexts',
             'duplicate_observations', 'ours_only', 'oleg_only', 'source_unresolved'}


def baseline_seed_groups(packet):
    """Reuse only the frozen matcher's exact pairs, with all originals retained."""
    lookup = {f['fact_id']: i for i, f in enumerate(packet['facts'])}
    parents = {}
    def top(i):
        parents.setdefault(i, i)
        if parents[i] != i: parents[i] = top(parents[i])
        return parents[i]
    for row in packet['ledger_rows']:
        if row['status'] != 'exact_agreement': continue
        ids = [row['ours_fact_id'], *row['oleg_fact_ids']]
        if not all(fid in lookup for fid in ids): continue
        facts = [packet['facts'][lookup[fid]] for fid in ids]
        if any(type(f['value']) is not type(facts[0]['value']) or f['value'] != facts[0]['value'] for f in facts):
            raise ValueError('Frozen exact agreement no longer has exact typed values')
        indices = [lookup[fid] for fid in ids]; root = top(indices[0])
        for i in indices[1:]: parents[top(i)] = root
    sets = {}
    for i in parents: sets.setdefault(top(i), []).append(i)
    return [{'fact_indices':sorted(indices), 'relation':'same_fact','keep':'ours',
        'reason':'Reused frozen exact_agreement, unchanged original values and provenance; final independent review pending',
        'evidence_refs':[0]} for indices in sets.values()]


def validate_page_work(packet, proposal, *, packet_sha256, identity):
    validate_identity(identity)
    if identity['role'] != packet['owner']:
        raise ValueError('This catalogue belongs to another owner')
    if proposal.get('work_packet_sha256') != packet_sha256:
        raise ValueError('Proposal does not bind the exact immutable page input')
    if proposal.get('source_sha256') != packet['source_sha256'] or proposal.get('physical_page') != packet['physical_page']:
        raise ValueError('Source or physical page differs')
    evidence = proposal.get('source_evidence')
    if not isinstance(evidence, list) or (packet['physical_page'] and not evidence):
        raise ValueError('Owner must inspect and cite the original page')
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get('observation'), str) or not item['observation'].strip():
            raise ValueError('Source-grounded observation required')
        box = item.get('bbox')
        if not isinstance(box, list) or len(box) != 4 or any(type(n) not in (int,float) for n in box) or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            raise ValueError('Evidence needs an original normalized source region')
    groups = proposal.get('groups')
    if not isinstance(groups, list): raise ValueError('Complete page groups required')
    if proposal.get('reuse_exact_agreements') is True:
        groups = baseline_seed_groups(packet) + groups
    covered = set(); chosen = []; unresolved = []; retained_groups = []
    for number, group in enumerate(groups):
        indices = group.get('fact_indices'); relation = group.get('relation'); keep = group.get('keep')
        if not isinstance(indices,list) or not indices or any(type(i) is not int or i < 0 or i >= len(packet['facts']) for i in indices):
            raise ValueError('Group must reference existing exact fact indices')
        if len(set(indices)) != len(indices) or covered.intersection(indices):
            raise ValueError('A fact was assigned twice')
        covered.update(indices)
        if relation not in RELATIONS or keep not in {'ours','oleg','both','unresolved'}:
            raise ValueError('Explicit relation and retained side required')
        if not isinstance(group.get('reason'),str) or not group['reason'].strip():
            raise ValueError('Semantic context/reason required')
        refs = group.get('evidence_refs')
        if not isinstance(refs,list) or (packet['physical_page'] and not refs) or any(type(i) is not int or not 0 <= i < len(evidence) for i in refs):
            raise ValueError('Each group needs source evidence references')
        sides = {packet['facts'][i]['side'] for i in indices}
        if relation in {'same_fact','variant_options','separate_contexts'} and sides != {'ours','oleg'}:
            raise ValueError('A two-sided relation needs both original sides')
        if relation == 'ours_only' and (sides != {'ours'} or keep != 'ours'):
            raise ValueError('Only-ours group must preserve our source facts')
        if relation == 'oleg_only' and (sides != {'oleg'} or keep != 'oleg'):
            raise ValueError('Only-Oleg group must preserve Oleg source facts')
        if relation == 'separate_contexts' and keep != 'both':
            raise ValueError('Different source contexts cannot erase each other')
        if relation == 'source_unresolved' and keep != 'unresolved':
            raise ValueError('Unresolved source cannot become a selected value')
        if keep in ('ours','oleg') and keep not in sides:
            raise ValueError('Selected side has no input in this group')
        # No model-authored replacement strings enter this path. Corrections
        # outside the two existing inputs remain explicit source questions.
        if set(group) - {'fact_indices','relation','keep','reason','evidence_refs'}:
            raise ValueError('Unknown group fields; no unbound replacement values')
        for i in indices:
            if keep == 'unresolved': unresolved.append(i)
            elif keep == 'both' or packet['facts'][i]['side'] == keep: chosen.append(i)
        retained_groups.append(copy.deepcopy(group))
    if covered != set(range(len(packet['facts']))):
        raise ValueError('Page is partial: some original facts were not handled')
    result = {'schema_version':'catalogue-single-owner-page-work/1',
        'work_packet_sha256':packet_sha256, 'source_sha256':packet['source_sha256'],
        'physical_page':packet['physical_page'], 'catalog':packet['catalog'],
        'identity':copy.deepcopy(identity), 'source_evidence':copy.deepcopy(evidence),
        'groups':retained_groups, 'selected_fact_indices':chosen,
        'source_unresolved_fact_indices':unresolved, 'all_input_facts_accounted_for':True,
        'owner_work_complete':True, 'independent_final_review_complete':False,
        'original_alternatives_retained':True,
        'saved_at':datetime.now(timezone.utc).isoformat()}
    result['work_sha256'] = case_sha256(result)
    return result


def save_page_work(packet_path, proposal, *, identity, output):
    packet_path = Path(packet_path); raw = packet_path.read_bytes()
    result = validate_page_work(json.loads(raw), proposal,
        packet_sha256=hashlib.sha256(raw).hexdigest(), identity=identity)
    output = Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    # Every actual revision is preserved. Never overwrite another author's work.
    with output.open('x') as stream:
        stream.write(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return result
