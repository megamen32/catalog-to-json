"""Compact review scopes over a retained alignment ledger, without new matches.

A scope groups questions for review, not product identities. Every observation
and ledger occurrence survives. Candidate edges are input edges only; agreement
classes describe the ledger, never verification against the PDF. Fact values,
complete headers and conditions remain in the immutable facts store by pointer.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path


class AlignmentError(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()[:24]


def _rows(value):
    if isinstance(value, (str, Path)):
        path = Path(value)
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)
    elif isinstance(value, dict):
        yield from value.values()
    else:
        yield from value


def _location(fact, window_ranges):
    pages = fact.get('physical_pages', [])
    if not isinstance(pages, list) or any(type(p) is not int or p < 1 for p in pages):
        raise AlignmentError('Invalid physical_pages')
    if pages:
        return {'kind': 'evidence_pages', 'physical_pages': sorted(set(pages))}
    declared = fact.get('declared_window_range') or window_ranges.get(fact.get('window_id'))
    if declared:
        start, end = declared.get('start_page'), declared.get('end_page')
        if type(start) is not int or type(end) is not int or not 1 <= start <= end:
            raise AlignmentError('Invalid declared window range')
        if declared.get('source_sha256', fact['source_sha256']) != fact['source_sha256']:
            raise AlignmentError('Window range source mismatch')
        return {'kind': 'declared_window_fallback', 'physical_pages': [],
                'start_page': start, 'end_page': end, 'window_id': fact.get('window_id')}
    return {'kind': 'unlocated', 'physical_pages': [], 'window_id': fact.get('window_id')}


def _context(fact, location):
    if fact['side'] == 'ours' and 'row_index' in fact:
        return {'side': 'ours', 'location': location,
                'table_index': fact.get('table_index'), 'row_index': fact['row_index']}
    if fact['side'] == 'oleg':
        raw = fact.get('raw')
        raw = raw if isinstance(raw, dict) else {}
        return {'side': 'oleg', 'location': location, 'window_id': fact.get('window_id'),
                'product_id': fact.get('product_id') or (fact.get('observation_id') if fact.get('kind') == 'model_designation' else None),
                'group_id': fact.get('group_id'), 'row_evidence': raw.get('row_evidence'),
                'row_evidence_present': 'row_evidence' in raw}
    return {'side': fact['side'], 'location': location, 'pointer': fact.get('pointer')}


def _index(facts, window_ranges):
    index = {}
    contexts = {}
    for fact in _rows(facts):
        fid = fact['fact_id']
        if fid in index:
            raise AlignmentError(f'Duplicate fact ID: {fid}')
        if fact.get('side') not in ('ours', 'oleg') or not fact.get('source_sha256'):
            raise AlignmentError(f'Missing source/side: {fid}')
        location = _location(fact, window_ranges)
        context = _context(fact, location)
        cid = 'CTX-' + _hash([fact['source_sha256'], context])
        contexts.setdefault(cid, context)
        # No raw blobs, repeated row_values, headers or conditions in this index.
        # Their exact typed values/presence are recoverable from the fact record.
        index[fid] = {'fact_id': fid, 'side': fact['side'],
                      'source_sha256': fact['source_sha256'], 'catalog': fact.get('catalog'),
                      'pointer': fact.get('pointer'), 'model_raw': fact.get('owner'),
                      'kind': fact.get('kind'), 'context_id': cid, 'location': location,
                      'observation_id': fact.get('observation_id'),
                      'value_type': fact.get('raw_value_type'),
                      'value_present': fact.get('raw_value_present', 'value' in fact)}
    return index, contexts


def group_alignment(facts, ledger, *, window_ranges=None):
    """Yield full scopes, including exact ledger rows, in first-seen order.

    Inputs may be JSONL paths, iterables, or fact-ID mappings. IDs refer to the
    original facts; ``input_row_index`` is zero-based among nonblank ledger rows.
    A repeated identical ledger row receives its own occurrence ID. Literal
    model text is not casefolded, normalized or treated as a unique SKU.
    ``window_ranges`` is optional authoritative declaration metadata, not evidence.
    """
    index, contexts = _index(facts, window_ranges or {})
    scopes = {}
    represented = set()
    candidate_contexts = defaultdict(set)
    for ordinal, row in enumerate(_rows(ledger)):
        ours = row.get('ours_fact_id')
        candidates = row.get('oleg_fact_ids', [])
        if not isinstance(candidates, list) or len(candidates) != len(set(candidates)):
            raise AlignmentError('Duplicate or invalid candidate IDs in ledger row')
        ids = ([ours] if ours is not None else []) + candidates
        if not ids or any(fid not in index for fid in ids):
            raise AlignmentError(f'Unknown/empty ledger references at row {ordinal}')
        if ours is not None and index[ours]['side'] != 'ours':
            raise AlignmentError('ours_fact_id references wrong side')
        if any(index[fid]['side'] != 'oleg' for fid in candidates):
            raise AlignmentError('oleg_fact_ids references wrong side')
        sources = {index[fid]['source_sha256'] for fid in ids}
        if len(sources) != 1:
            raise AlignmentError('Cross-source candidate edge')
        anchor = index[ours or candidates[0]]
        # Conflicting evidence locations stay in the member refs; never assign
        # the candidate to the anchor page or infer a page from a window range.
        key = _json([anchor['source_sha256'], anchor['location'], anchor['model_raw']])
        scope = scopes.setdefault(key, {'scope_id': 'SCP-' + _hash(key),
            'source_sha256': anchor['source_sha256'], 'catalog': anchor['catalog'],
            'location': anchor['location'], 'model_raw': anchor['model_raw'], 'members': []})
        status = row.get('status')
        if status not in {'exact_agreement', 'representation_difference', 'ambiguous_alignment',
                          'value_or_applicability_conflict', 'unmatched_ours_observation',
                          'unmatched_oleg_observation'}:
            raise AlignmentError(f'Unknown ledger status: {status}')
        member = {'member_ledger_id': 'LGR-' + _hash([ordinal, row]),
                  'input_row_index': ordinal, 'input_status': status,
                  'ours_fact_id': ours, 'oleg_fact_ids': list(candidates)}
        scope['members'].append(member)
        if ours:
            for fid in candidates:
                candidate_contexts[fid].add(index[ours]['context_id'])
        represented.update(ids)
    missing = set(index) - represented
    if missing:
        raise AlignmentError(f'{len(missing)} facts absent from ledger; first={min(missing)}')
    for scope in scopes.values():
        members = scope['members']
        scope_ambiguous = any(len(candidate_contexts[fid]) > 1
                              for m in members for fid in m['oleg_fact_ids'])
        classifications = Counter()
        ids = set()
        for m in members:
            status = m['input_status']
            linked = m['oleg_fact_ids']
            if not m['ours_fact_id'] or not linked:
                classification = 'unmatched'
            elif scope_ambiguous or len(linked) > 1 or status == 'ambiguous_alignment':
                classification = 'ambiguous_one_to_many'
            elif status == 'exact_agreement':
                classification = 'exact'
            elif status == 'representation_difference':
                classification = 'representation'
            else:
                classification = 'conflict'
            m['classification'] = classification
            m['review_required'] = classification != 'exact'
            classifications[classification] += 1
            ids.update(linked)
            if m['ours_fact_id']:
                ids.add(m['ours_fact_id'])
        scope['classification'] = ('ambiguous_one_to_many' if scope_ambiguous or classifications['ambiguous_one_to_many']
                                   else next(iter(classifications)) if len(classifications) == 1 else 'mixed')
        scope['classification_counts'] = dict(classifications)
        scope['fact_refs'] = {fid: index[fid] for fid in sorted(ids)}
        cids = {index[fid]['context_id'] for fid in ids}
        scope['row_contexts'] = {cid: contexts[cid] for cid in sorted(cids)}
        scope['semantic_verdict'] = None
        scope['grouping_is_identity_merge'] = False
        scope['candidate_pairs_basis'] = 'input_ledger_edges_only'
        scope['scope_note'] = 'Review scope only; headers, scope, conditions and row linkage require original facts/PDF.'
        yield scope


def _fragment(scope, members):
    ids = {fid for m in members for fid in m['oleg_fact_ids']}
    ids.update(m['ours_fact_id'] for m in members if m['ours_fact_id'])
    # Source/location/model and raw metadata already have authoritative owners.
    refs = {fid: {k: v for k, v in scope['fact_refs'][fid].items()
                  if k not in ('source_sha256', 'catalog', 'location', 'model_raw')}
            for fid in sorted(ids)}
    cids = {ref['context_id'] for ref in refs.values()}
    locations = [scope['row_contexts'][cid]['location'] for cid in cids]
    source_bound = all(loc['kind'] == 'evidence_pages' for loc in locations)
    known_pages = sorted({p for loc in locations for p in loc['physical_pages']})
    return {k: v for k, v in scope.items() if k not in ('members', 'fact_refs', 'row_contexts', 'classification_counts')} | {
        'case_id': 'GRP-' + _hash([scope['scope_id'], [m['member_ledger_id'] for m in members]]),
        'kind': 'alignment_scope' if source_bound else 'unresolved_alignment',
        'physical_pages': known_pages if source_bound else [],
        'known_evidence_pages': known_pages, 'source_bound': source_bound,
        'ours': [fid for fid in sorted(ids) if refs[fid]['side'] == 'ours'],
        'oleg': [fid for fid in sorted(ids) if refs[fid]['side'] == 'oleg'],
        'members': members, 'fact_refs': refs,
        'row_contexts': {cid: scope['row_contexts'][cid] for cid in sorted(cids)}}


def _pack(cases):
    row_ids = [m['member_ledger_id'] for c in cases for m in c['members']]
    return {'schema_version': 'alignment-review-pack/1',
            'pack_id': 'PACK-' + _hash(row_ids), 'cases': cases,
            'coverage': {'ledger_members': len(row_ids),
                         'open_input_members': sum(m['input_status'] != 'exact_agreement' for c in cases for m in c['members']),
                         'fact_ids': sorted({fid for c in cases for fid in c['fact_refs']})},
            'semantic_verdict': None, 'requires_fact_hydration': True,
            'executable_adjudication': False}


def build_review_packs(facts, ledger, *, max_cases, max_bytes, window_ranges=None):
    """Yield JSON-serializable bounded packs, normally confined to one page set.

    Every original open ledger occurrence is present exactly once. Closed exact
    rows are included only if their row mapping is ambiguous. Large scopes split
    into fragments with the same scope_id, never dropping candidates to fit.
    ``max_bytes`` includes UTF-8 compact JSON plus one newline. A single member
    that cannot fit raises AlignmentError rather than silently truncating it.
    No files are written. Raw values/header paths live at referenced facts IDs.
    These are compact review indexes, not executable provider inputs: ours/oleg
    contain fact IDs requiring hydration. Unlocated members also need source
    alignment; declared ranges never satisfy executable page evidence.
    """
    if type(max_cases) is not int or max_cases < 1 or type(max_bytes) is not int or max_bytes < 1:
        raise AlignmentError('Positive integer max_cases/max_bytes required')
    pending = []
    pending_location = None

    def fit(scope, members):
        fragment = _fragment(scope, members)
        if len(_json(_pack([fragment])).encode()) + 1 <= max_bytes:
            yield fragment
        elif len(members) > 1:
            mid = len(members) // 2
            yield from fit(scope, members[:mid])
            yield from fit(scope, members[mid:])
        else:
            raise AlignmentError(f'Single ledger member exceeds max_bytes: {members[0]["member_ledger_id"]}')

    for scope in group_alignment(facts, ledger, window_ranges=window_ranges):
        members = [m for m in scope['members'] if m['review_required'] or m['input_status'] != 'exact_agreement']
        if not members:
            continue
        location = _json([scope['source_sha256'], scope['location']])
        for fragment in fit(scope, members):
            if pending and (location != pending_location or len(pending) >= max_cases or
                            len(_json(_pack(pending + [fragment])).encode()) + 1 > max_bytes):
                yield _pack(pending)
                pending = []
            pending.append(fragment)
            pending_location = location
    if pending:
        yield _pack(pending)
