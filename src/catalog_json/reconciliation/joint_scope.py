"""Explicit, lossless bindings between variant cells and model option lists.

Construction proves character membership, not source correctness. Only a fresh
three-reviewer vote on the ENTIRE proposal can approve its engineering scope.
"""
from __future__ import annotations

import copy
from .consensus import build_consensus, case_sha256, validate_pack
from .formats import exact_json_equal


def make_variant_proposal(records, *, pack_id, option_delimiter='\n', property_aliases=None):
    if option_delimiter not in ('\n', '; '):
        raise ValueError('Only an explicitly retained newline or semicolon-space delimiter is supported')
    aliases = property_aliases or {}
    if not isinstance(aliases, dict) or any(type(k) is not str or type(v) is not str or not k or not v for k, v in aliases.items()):
        raise ValueError('Property aliases must be explicit original header pairs')
    if not records or not all(r['complete'] for r in records):
        raise ValueError('Discuss only cases with all initial voices retained')
    cases = [r['case'] for r in records]
    locations = {(c['source_sha256'], tuple(c['physical_pages'])) for c in cases}
    if len(locations) != 1 or len(cases[0]['physical_pages']) != 1:
        raise ValueError('A joint proposal covers one original physical page')
    atoms = {side: {} for side in ('ours', 'oleg')}
    for c in cases:
        for side in atoms:
            for atom in c[side]:
                fid = atom['fact_id']
                if fid in atoms[side] and not exact_json_equal(atoms[side][fid], atom):
                    raise ValueError('Conflicting retained input for a fact ID')
                atoms[side][fid] = atom
    bindings = []
    for fid, option in atoms['oleg'].items():
        raw = option['value']
        if type(raw) is not str or option_delimiter not in raw:
            raise ValueError('An explicit original delimited option list is required')
        members = []; offset = 0
        lines = raw.splitlines(keepends=True) if option_delimiter == '\n' else raw.split(option_delimiter)
        for line in lines:
            value = line.rstrip('\r\n') if option_delimiter == '\n' else line
            if not value: raise ValueError('Empty option needs separate source adjudication')
            members.append((value, offset, offset + len(value)))
            offset += len(line) + (len(option_delimiter) if option_delimiter != '\n' else 0)
        matches = [a for a in atoms['ours'].values()
                   if exact_json_equal(a['owner'], option['owner'])
                   and (a['name'] == option['name'] or aliases.get(a['name']) == option['name'])]
        chosen = []
        for value, start, end in members:
            row = [a for a in matches if exact_json_equal(a['value'], value)]
            if len(row) != 1:
                raise ValueError('Every option must have exactly one explicitly retained variant cell')
            chosen.append({'variant_fact_id': row[0]['fact_id'],
                           'member_start': start, 'member_end': end})
        if len(chosen) != len(matches):
            raise ValueError('Every retained variant must be represented, no extra row is dropped')
        bindings.append({'model': option['owner'], 'property': option['name'],
                         'option_list_fact_id': fid, 'members': chosen})
    bound = {b['variant_fact_id'] for x in bindings for b in x['members']}
    if bound != set(atoms['ours']):
        raise ValueError('Proposal must cover every original variant fact')
    fields = ('fact_id', 'side', 'pointer', 'owner', 'name', 'value', 'unit', 'condition',
              'source_sha256', 'physical_pages', 'kind', 'full_input_fact_sha256')
    compact = lambda a: {k: copy.deepcopy(a[k]) for k in fields if k in a}
    proposal = {'schema_version': 'catalogue-variant-option-bindings/1',
                'canonical_action': 'Keep every original variant cell unchanged; expose the other original list ONLY as model-level options. Never copy the whole list into an individual variant cell.',
                'bindings': bindings,
                'covered_original_cases': [{'case_id': r['case']['case_id'],
                    'case_sha256': case_sha256(r['case']), 'pack_sha256': r['pack_sha256'],
                    'ours_fact_ids': [a['fact_id'] for a in r['case']['ours']],
                    'oleg_fact_ids': [a['fact_id'] for a in r['case']['oleg']]}
                    for r in records]}
    c = {'kind': 'joint-variant-and-model-options',
         'source_sha256': cases[0]['source_sha256'], 'physical_pages': cases[0]['physical_pages'],
         'ours': [compact(a) for a in atoms['ours'].values()],
         'oleg': [compact(a) for a in atoms['oleg'].values()], 'proposal': proposal,
         'question': 'Post-independent source discussion. Judge this ENTIRE proposed joint representation, not a competition between a row and a model. Inspect the original table, all listed models and variants. If BOTH the individual variant cells and their explicit model-option bindings are supported, choose both and explain that the canonical variant rows remain unchanged. If any member/scope/order is wrong, use unresolved/neither with the exact defect. Retaining the full list is not permission to copy it into one variant cell. No proposed engineering value is invented.'}
    c['case_id'] = 'J-' + case_sha256(c)[:24]
    pack = {'schema_version': 'catalogue-discrepancy-pack/1', 'pack_id': pack_id,
            'reviewer_policy': {'required_roles': ['codex', 'zcode', 'minimax'], 'standalone_glm': False},
            'cases': [c]}
    if option_delimiter != '\n' or aliases:
        pack['proposal_construction'] = {'option_delimiter': option_delimiter,
                                         'property_aliases': copy.deepcopy(aliases)}
    return validate_pack(pack)


def validate_variant_proposal(pack, records):
    construction = pack.get('proposal_construction', {})
    if not isinstance(construction, dict) or set(construction) - {'option_delimiter', 'property_aliases'}:
        raise ValueError('Unsupported proposal construction rules')
    expected = make_variant_proposal(records, pack_id=pack['pack_id'], **construction)
    if not exact_json_equal(pack, expected):
        raise ValueError('Joint scope proposal differs from its exact original facts/bindings')
    return expected['cases'][0]['proposal']


def approve_variant_proposal(pack, votes, records):
    proposal = validate_variant_proposal(pack, records)
    consensus = build_consensus(pack, votes)
    if not consensus['complete'] or not consensus['all_resolved'] or consensus['cases'][0]['decision'] != 'both':
        raise ValueError('All three must actually approve both scoped representations')
    if any('selected_value' in v['payload']['verdicts'][0] for v in votes):
        raise ValueError('Replacement values need a separate explicit proposal')
    return {'schema_version': 'catalogue-joint-scope-approval/1',
            'pack_sha256': case_sha256(pack), 'proposal_sha256': case_sha256(proposal),
            'covered_original_case_ids': [r['case']['case_id'] for r in records],
            'proposal': proposal, 'consensus': consensus,
            'original_votes': copy.deepcopy(votes), 'new_model_opinions': True,
            'catalogue_values_changed': False}
