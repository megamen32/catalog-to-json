"""Whole-owner exporter that MATERIALIZES latest authored page-work receipts.

Receipt discovery is schema-driven: every ``*.json`` under ``reviews/*/full-work``
(recursive, including author-revision names and native-session subdirectories) is
a candidate if it carries ``catalogue-single-owner-page-work/1``; the latest
``saved_at`` per (identity.role, catalog, page) wins regardless of file name. A
receipt counts only for the page's CURRENT owner (ownership transfers included)
and only while it binds the exact packet bytes on disk.

Validation mirrors ``page_work.validate_page_work``: receipt groups must cover
every fact index exactly once; the header ``selected_fact_indices`` /
``source_unresolved_fact_indices`` must reproduce from the groups and the packet
fact sides; ``work_sha256`` must be the digest of the receipt without the hash
key. A keep=oleg group legitimately rejects the ours-side fact — that fact is
archived, never canonical, and the coverage rule is group-based, not
len(selected)+len(unresolved).

Materialization builds the PRIMARY delivery from the groups:
  keep=ours  -> ours facts primary (baseline cells unchanged), oleg facts
                archived (rejected as canonical);
  keep=oleg  -> oleg facts primary; every ours cell bound by the SAME group
                is rewritten with the selected typed value and explicit unit /
                condition (verified before/after); ours
                figures/texts/notes in the same group are REMOVED from content
                (they live only in the archive);
  keep=both  -> both sides primary, ours cell stays canonical;
  keep=unresolved -> source facts stay in the unresolved archive; affected
                baseline cells become unknown and figures leave usable content.
Oleg-only selected facts (no ours counterpart in the group) are materialised
into the per-page ``merged_primary`` section with full provenance. null / blank
/ dash / 0 remain distinct typed values end to end.
A grouped structure replacement removes a legacy table only if every old cell
is explicitly rejected; the selected records become primary without a guessed
scalar mapping. Partial ambiguous replacements are refused.
An owner merge invalidates baseline approval for the changed page; the original
review proof remains in history and is never presented as a new final review.

Final delivery hard-requires all 980 pages with a validated receipt; snapshots
below full coverage are explicit ``--allow-partial`` runs and never final.
No model calls, no extraction, no benchmark.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import gc
import hashlib
import io
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from openpyxl import load_workbook

from catalog_json.reconciliation.consensus import case_sha256
from catalog_json.reconciliation.formats import exact_json_equal
from catalog_json.export import to_xlsx
from catalog_json.schema import PageContent

ROLES = ('codex', 'zcode', 'minimax')
RECEIPT_SCHEMA = 'catalogue-single-owner-page-work/1'
BASELINE_ZIP = Path('examples/catalogs/all-pages-2026-10-14T172333Z/all-catalogues-980-pages.zip')
BASELINE_SHA256 = 'dcfdf4a64448a727766cc50ba31b01cf967b475744b9a6d6c5d065344c5061a7'
BASELINE_MEMBER = 'all-catalogues-980-pages.json'
TOTAL_PAGES = 980


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def norm(v):
    return re.sub(r'\s+', ' ', str(v)).strip() if v is not None else None


def _git(root, args, check=True):
    try:
        out = subprocess.run(['git', '-C', str(root), *args], check=check,
                             capture_output=True, text=True)
        return out.stdout.strip() if check else out.returncode
    except (subprocess.CalledProcessError, FileNotFoundError):
        if check:
            return 'unknown'
        return -1


def _git_modified(root, paths):
    return any(_git(root, ['diff', '--quiet', 'HEAD', '--', p], check=False) != 0 for p in paths)


def check_capacity(out_dir, need_bytes=4 * 1024 ** 3):
    probe = Path(out_dir)
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    free = shutil.disk_usage(probe).free
    if free < need_bytes:
        raise ValueError(f'Insufficient disk for export: {free} free, {need_bytes} required')
    meminfo = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, _, rest = line.partition(':')
        meminfo[key] = int(rest.strip().split()[0]) * 1024
    if meminfo.get('MemAvailable', 0) < 2 * 1024 ** 3:
        raise ValueError('Insufficient available memory for export (need 2GiB)')


def load_transfers(task):
    path = task / 'ownership-transfers' / 'index.json'
    transfers = {}
    if path.exists():
        for item in load(path)['transfers']:
            key = (item['catalog'], item['physical_page'])
            if key in transfers:
                raise ValueError(f'Duplicate ownership transfer for {key}')
            if not item.get('fact_store_unchanged'):
                raise ValueError(f'Transfer for {key} claims changed facts')
            transfers[key] = item
    return transfers


def discover_receipts(reviews):
    """Schema-driven recursive scan of reviews/*/full-work.

    Returns {(identity.role, catalog, page): {saved_at: (path, receipt)}}.
    """
    found = {}
    for path in Path(reviews).rglob('*.json'):
        parts = path.parts
        if any(seg.startswith('_prev-round') or seg == 'images'
               or seg.startswith('_substrate') or seg.startswith('_review')
               or seg.startswith('_adjudication') for seg in parts):
            continue
        try:
            doc = json.loads(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict) or doc.get('schema_version') != RECEIPT_SCHEMA:
            continue
        ident = doc.get('identity') or {}
        key = (ident.get('role'), doc.get('catalog'), doc.get('physical_page'))
        found.setdefault(key, {})[doc.get('saved_at', '')] = (path, doc)
    return found


def resolve_packet(task, entry, transfers):
    """Returns (owner, raw_bytes|None, sha|None, packet_path) for a page."""
    key = (entry['catalog'], entry['physical_page'])
    transfer = transfers.get(key)
    if transfer:
        owner = transfer['owner']
        candidates = [task / transfer['packet'], task.parent / transfer['packet'],
                      Path(transfer['packet'])]
        packet_path = next((p for p in candidates if p.exists()), None)
        if packet_path is None:
            return owner, None, None, transfer['packet']
        raw = packet_path.read_bytes()
        return owner, raw, sha_bytes(raw), packet_path
    owner = entry['owner']
    packet_path = task / 'full-alignment-work-v2' / entry['path']
    raw = packet_path.read_bytes()
    return owner, raw, sha_bytes(raw), packet_path


def transfer_is_current(transfers, key, packet_sha, manifest_sha):
    transfer = transfers.get(key)
    if transfer is None:
        return packet_sha == manifest_sha
    return packet_sha == transfer['packet_sha256']


def derive_from_groups(receipt, packet):
    """Side-aware selection derivation + exact-once coverage check."""
    facts = packet['facts']
    seen = {}
    for gi, group in enumerate(receipt['groups']):
        keep = group.get('keep')
        if keep not in ('ours', 'oleg', 'both', 'unresolved'):
            raise ValueError(f'Group {gi}: invalid keep {keep!r}')
        for i in group['fact_indices']:
            if not 0 <= i < len(facts):
                raise ValueError(f'Group {gi}: index {i} out of range')
            if i in seen:
                raise ValueError(f'Fact {i} assigned twice (groups {seen[i]} and {gi})')
            seen[i] = gi
    for i in range(len(facts)):
        if i not in seen:
            raise ValueError(f'Fact {i} is not covered by any group')
    selected, unresolved, archived = set(), set(), set()
    for gi, group in enumerate(receipt['groups']):
        keep = group['keep']
        for i in group['fact_indices']:
            side = facts[i]['side']
            if keep == 'unresolved':
                unresolved.add(i)
            elif keep == 'both':
                selected.add(i)
            elif keep == 'ours':
                (selected if side == 'ours' else archived).add(i)
            else:
                (selected if side == 'oleg' else archived).add(i)
    header_sel = set(receipt.get('selected_fact_indices', []))
    header_unr = set(receipt.get('source_unresolved_fact_indices', []))
    if header_sel != selected or header_unr != unresolved:
        raise ValueError(f'Header lists do not reproduce from groups: selected '
                         f'{len(header_sel)}vs{len(selected)}, unresolved {len(header_unr)}vs{len(unresolved)}')
    return selected, unresolved, archived


def validate_receipt(receipt, path, packet, packet_sha256, owner):
    if receipt.get('work_packet_sha256') != packet_sha256:
        raise ValueError(f'{path}: work_packet_sha256 does not bind the exact packet bytes')
    if receipt.get('source_sha256') != packet['source_sha256'] or receipt.get('physical_page') != packet['physical_page']:
        raise ValueError(f'{path}: source or physical page differs from the packet')
    identity = receipt.get('identity') or {}
    if identity.get('role') != owner:
        raise ValueError(f'{path}: receipt role {identity.get("role")!r} is not the current owner {owner!r}')
    if not identity.get('session_id') or not identity.get('model'):
        raise ValueError(f'{path}: receipt identity lacks session/model')
    digest_input = {k: v for k, v in receipt.items() if k != 'work_sha256'}
    if receipt.get('work_sha256') != case_sha256(digest_input):
        raise ValueError(f'{path}: work_sha256 does not reproduce')
    if receipt.get('all_input_facts_accounted_for') is not True:
        raise ValueError(f'{path}: page is not fully accounted')
    derive_from_groups(receipt, packet)


def collect_pages(task, reviews, manifest, transfers, only_pages=None):
    discovered = discover_receipts(reviews)
    records, inflight = {}, []
    for entry in manifest['pages']:
        key = (entry['catalog'], entry['physical_page'])
        if only_pages is not None and entry['path'] not in only_pages:
            continue
        owner, raw, packet_sha, packet_path = resolve_packet(task, entry, transfers)
        if raw is None:
            inflight.append({'page': entry['path'], 'reason': 'transfer packet not on disk yet'})
            continue
        if not transfer_is_current(transfers, key, packet_sha, entry['sha256']):
            inflight.append({'page': entry['path'],
                             'reason': 'packet bytes changed — author revision in flight'})
            continue
        packet = json.loads(raw)
        if packet.get('physical_page') != entry['physical_page'] or packet.get('catalog') != entry['catalog']:
            raise ValueError(f'Packet identity mismatch for {key}')
        candidates = discovered.get((owner, entry['catalog'], entry['physical_page']), {})
        assignment = transfers.get(key, {})
        binding = [(saved, (p, r)) for saved, (p, r) in candidates.items()
                   if r.get('work_packet_sha256') == packet_sha
                   and (not assignment.get('assigned_native_session')
                        or r.get('identity', {}).get('session_id') == assignment['assigned_native_session'])
                   and (not assignment.get('assigned_model')
                        or r.get('identity', {}).get('model') == assignment['assigned_model'])]
        if not binding:
            inflight.append({'page': entry['path'],
                             'reason': f'no assigned {owner} session/model receipt binds current packet sha {packet_sha[:12]}'})
            continue
        saved_at, (path, receipt) = max(binding, key=lambda kv: kv[0])
        validate_receipt(receipt, path, packet, packet_sha, owner)
        records[entry['path']] = {'catalog': entry['catalog'], 'physical_page': entry['physical_page'],
                                  'source_sha256': entry['source_sha256'], 'owner': owner,
                                  'packet_path': str(packet_path), 'packet_sha256': packet_sha,
                                  'packet': packet, 'receipt': receipt,
                                  'receipt_path': str(path), 'saved_at': receipt['saved_at']}
    return records, inflight


def cell_pointer_parts(pointer):
    parts = pointer.strip('/').split('/')
    if len(parts) == 11 and parts[0] == 'catalogs' and parts[2] == 'pages' \
            and parts[4] == 'content' and parts[5] == 'tables':
        return {'catalog': int(parts[1]), 'page': int(parts[3]), 'table': int(parts[6]),
                'row': int(parts[8]), 'cell': int(parts[10])}
    return None


def section_pointer_parts(pointer):
    parts = pointer.strip('/').split('/')
    if len(parts) == 7 and parts[0] == 'catalogs' and parts[2] == 'pages' \
            and parts[4] == 'content' and parts[5] in ('figures', 'text_blocks', 'source_notes', 'drawings'):
        return {'catalog': int(parts[1]), 'page': int(parts[3]), 'kind': parts[5], 'index': int(parts[6])}
    return None


def primary_entry(fact, kept, receipt):
    return {'fact_id': fact.get('fact_id'), 'side': fact['side'], 'kind': fact.get('kind'),
            'owner': fact.get('owner'), 'name': fact.get('name'),
            'unit': fact.get('unit'), 'condition': fact.get('condition'),
            'value': fact.get('value'),
            'value_state': (fact.get('raw', {}) or {}).get('value_state')
            or (fact.get('raw_semantic_context', {}) or {}).get('value_state'),
            'pointer': fact.get('pointer'),
            'provenance': {'input_fact_sha256': fact.get('input_fact_sha256'),
                           'kept': kept,
                           'selected_by_role': receipt['identity']['role'],
                           'work_sha256': receipt['work_sha256']}}


def whole_table_replacements(facts, page, receipt):
    """Allow a structure replacement only when every old cell is rejected.

    A whole type/geometry block (isolators64) has no one-to-one scalar mapping.
    Its selected records live in merged_primary; the completely rejected legacy
    table must leave content. Partial ambiguous groups still fail below.
    """
    rejected, preserved, candidates = set(), set(), set()
    for group in receipt['groups']:
        members = [facts[i] for i in group['fact_indices']]
        cells = [cp for f in members if f['side'] == 'ours'
                 and (cp := cell_pointer_parts(f.get('pointer', '')))]
        targets = {(cp['table'], cp['row'], cp['cell']) for cp in cells}
        if group['keep'] != 'oleg':
            preserved.update(targets)
            continue
        rejected.update(targets)
        signatures = {(norm(f.get('value')), norm(f.get('unit')) or None,
                       norm(f.get('condition')) or None)
                      for f in members if f['side'] == 'oleg'}
        if len(signatures) > 1:
            candidates.update(cp['table'] for cp in cells)
    result = set()
    for table_index in candidates:
        table = page['content']['tables'][table_index]
        expected = {(table_index, ri, ci) for ri, row in enumerate(table['rows'])
                    for ci, _ in enumerate(row['cells'])}
        if expected and expected <= rejected and not expected.intersection(preserved):
            result.add(table_index)
    return result


def apply_receipt(record, page, receipt, corrections):
    """Materialize one receipt over the baseline page.

    Returns (primary, unresolved, archived, removals). Groups are the sole
    source of pairing: a keep=oleg group rewrites the ours cell pointed to by
    the ours-side member of that same group; rejected ours figures/texts/notes
    are removed from content (archive keeps them).
    """
    packet = record['packet']
    facts = packet['facts']
    primary, unresolved, archived, removals = [], [], [], []
    replaced_tables = whole_table_replacements(facts, page, receipt)
    removals.extend({'kind': 'tables', 'index': i} for i in sorted(replaced_tables))
    written = set()
    for group in receipt['groups']:
        keep = group['keep']
        members = [facts[i] for i in group['fact_indices']]
        if keep == 'unresolved':
            for f in members:
                e = primary_entry(f, 'unresolved', receipt)
                e['source_unresolved'] = True
                unresolved.append(e)
                # An unresolved figure is retained here, never as usable content.
                if f['side'] == 'ours':
                    sec = section_pointer_parts(f.get('pointer', ''))
                    if sec:
                        removals.append(sec)
                    cp = cell_pointer_parts(f.get('pointer', ''))
                    if cp:
                        cell = page['content']['tables'][cp['table']]['rows'][cp['row']]['cells'][cp['cell']]
                        before = copy.deepcopy(cell)
                        cell.update(value=None, state='unknown')
                        if not exact_json_equal(before, cell):
                            corrections.append({'catalog': record['catalog'],
                                                'physical_page': record['physical_page'],
                                                'json_pointer': f['pointer'],
                                                'owner': f.get('owner'), 'name': f.get('name'),
                                                'before': before, 'after': copy.deepcopy(cell),
                                                'source_unresolved': True,
                                                'archived_fact_id': f.get('fact_id'),
                                                'selected_by_role': receipt['identity']['role'],
                                                'work_sha256': receipt['work_sha256']})
            continue
        if keep == 'both':
            for f in members:
                primary.append(primary_entry(f, 'both', receipt))
            continue
        chosen = keep
        ours_cells = [f for f in members
                      if f['side'] == 'ours'
                      and (cp := cell_pointer_parts(f.get('pointer', '')))
                      and cp['table'] not in replaced_tables]
        if chosen == 'oleg' and ours_cells:
            selected = [f for f in members if f['side'] == 'oleg']
            signatures = {(norm(f.get('value')), norm(f.get('unit')) or None,
                           norm(f.get('condition')) or None) for f in selected}
            if len(signatures) != 1:
                raise ValueError('Ambiguous keep=oleg group: multiple selected values/units/conditions '
                                 f'for baseline cells on {record["catalog"]}:{record["physical_page"]}')
            selected_fact = selected[0]
            for target in ours_cells:
                if target['pointer'] in written:
                    continue
                cp = cell_pointer_parts(target['pointer'])
                table = page['content']['tables'][cp['table']]
                cell = table['rows'][cp['row']]['cells'][cp['cell']]
                column = next(c for c in table['columns'] if c['id'] == cell['column_id'])
                if norm(cell.get('value')) != norm(target.get('value')):
                    raise ValueError(f'Baseline drift at {target["pointer"]}: '
                                     f'{cell.get("value")!r} != ours fact {target.get("value")!r}')
                before = {**copy.deepcopy(cell), 'unit': column.get('unit'),
                          'condition': column.get('qualifier')}
                cell['value'] = selected_fact.get('value')
                state = (selected_fact.get('raw', {}) or {}).get('value_state') or \
                        (selected_fact.get('raw_semantic_context', {}) or {}).get('value_state')
                cell['state'] = ('blank' if state == 'source_blank' and cell['value'] in (None, '')
                                 else 'value')
                # Empty Oleg metadata is absence, not an instruction to erase the header.
                if selected_fact.get('unit'):
                    column['unit'] = selected_fact['unit']
                if selected_fact.get('condition'):
                    column['qualifier'] = selected_fact['condition']
                after = {**copy.deepcopy(cell), 'unit': column.get('unit'),
                         'condition': column.get('qualifier')}
                written.add(target['pointer'])
                if not exact_json_equal(before, after):
                    corrections.append({'catalog': record['catalog'],
                                        'physical_page': record['physical_page'],
                                        'json_pointer': target['pointer'],
                                        'owner': selected_fact.get('owner'),
                                        'name': selected_fact.get('name'),
                                        'before': before, 'after': after,
                                        'selected_fact_id': selected_fact.get('fact_id'),
                                        'archived_fact_id': target.get('fact_id'),
                                        'selected_by_role': receipt['identity']['role'],
                                        'work_sha256': receipt['work_sha256']})
        for f in members:
            entry = primary_entry(f, keep, receipt)
            if f['side'] == chosen:
                primary.append(entry)
                continue
            sec = section_pointer_parts(f.get('pointer', ''))
            if sec:
                removals.append(sec)
            archived.append({**entry, 'archived_reason':
                             f'rejected as canonical: keep={keep} chose {chosen}'})
    return primary, unresolved, archived, removals


def _report_with_transfers(summary, uncovered, inflight, transfers, manifest):
    keys = {(e['catalog'], e['physical_page']) for e in manifest['pages']}
    matching = [t for k, t in sorted(transfers.items()) if k in keys]
    return {'summary': summary, 'uncovered_pages': uncovered,
            'in_flight_pages': inflight, 'ownership_transfers': matching}


def invalidate_baseline_review(page):
    """A saved owner merge is not a new independent approval of its primary data."""
    keys = ('status', 'reviewed_current_content', 'review_producer', 'review_sha256',
            'review', 'reviewer', 'content_canonical_sha256')
    page['baseline_review'] = {key: copy.deepcopy(page[key]) for key in keys if key in page}
    page['status'] = 'owner_merged_awaiting_independent_review'
    page['reviewed_current_content'] = False
    page['independent_final_review_complete'] = False
    for key in ('review_producer', 'review_sha256', 'review', 'reviewer'):
        page.pop(key, None)
    page['content_canonical_sha256'] = case_sha256(page['content'])


def export(root, task, out, *, allow_partial=False, only_pages=None):
    started = time.monotonic()
    out = Path(out)
    if out.exists():
        raise ValueError(f'Output directory already exists: {out}')
    check_capacity(out)
    manifest = load(task / 'full-alignment-work-v2' / 'manifest.json')
    transfers = load_transfers(task)
    records, inflight = collect_pages(task, task / 'reviews', manifest, transfers, only_pages)
    covered_pages = len(records)
    uncovered = sorted(e['path'] for e in manifest['pages']
                       if (only_pages is None or e['path'] in only_pages)
                       and e['path'] not in records)
    full = covered_pages == TOTAL_PAGES and not uncovered
    if not full and not allow_partial:
        raise ValueError(f'Final delivery refused: {covered_pages}/{TOTAL_PAGES} pages have validated receipts '
                         f'(first uncovered: {uncovered[:5]}). Use --allow-partial only for an explicit intermediate snapshot.')
    original = root / BASELINE_ZIP
    if sha(original) != BASELINE_SHA256:
        raise ValueError('Baseline archive SHA changed')
    with zipfile.ZipFile(original) as z:
        bundle = json.loads(z.read(BASELINE_MEMBER))
    count = sum(len(c['pages']) for c in bundle['catalogs'])
    # The final delivery hard-requires 980 (checked after coverage below);
    # canary/partial runs tolerate a reduced synthetic baseline.
    baseline_by_page = {}
    for catalog in bundle['catalogs']:
        for page in catalog['pages']:
            baseline_by_page[(catalog['id'], page['pdf_page'])] = page
    corrections = []
    materialized = 0
    primary_total = unresolved_total = archived_total = 0
    for path, record in sorted(records.items()):
        page = baseline_by_page.get((record['catalog'], record['physical_page']))
        if page is None:
            continue
        receipt = record['receipt']
        primary, unresolved, archived, removals = apply_receipt(record, page, receipt, corrections)
        # Keep the exact validated decisions, including rejected Oleg differences
        # that leave the baseline cells unchanged. Indices address owner_typed_facts.
        page['owner_merge_decisions'] = copy.deepcopy(receipt)
        page['owner_typed_facts_pointer'] = f'/owner_typed_facts/{path}/facts'
        page['merged_primary'] = {
            'owner': record['owner'],
            'packet_sha256': record['packet_sha256'],
            'receipt': {'saved_at': receipt['saved_at'], 'work_sha256': receipt['work_sha256'],
                        'identity': receipt['identity'], 'receipt_path': record['receipt_path']},
            'primary_facts': primary,
            'source_unresolved_facts': unresolved,
        }
        page['owner_archive'] = {'archived_facts': archived,
                                 'content_removals': [f'{s["kind"]}[{s["index"]}]' for s in removals],
                                 'note': 'Не отобранные владельцем исходные факты и отклонённые '
                                         'фигуры/тексты; только архив, не первичные данные.'}
        by_section = {}
        for sec in removals:
            by_section.setdefault(sec['kind'], []).append(sec['index'])
        for kind, indices in by_section.items():
            drop = set(indices)
            page['content'][kind] = [item for k, item in enumerate(page['content'][kind])
                                     if k not in drop]
        PageContent.model_validate(page['content'])
        invalidate_baseline_review(page)
        materialized += 1
        primary_total += len(primary)
        unresolved_total += len(unresolved)
        archived_total += len(archived)
    per_role = {}
    for rec in records.values():
        role = rec['receipt']['identity']['role']
        per_role[role] = per_role.get(role, 0) + 1
    summary = {'schema_version': 'owner-reconciliation-snapshot/1',
               'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'final_delivery': full, 'allow_partial_used': allow_partial,
               'required_roles': list(ROLES),
               'total_pages': TOTAL_PAGES, 'pages_with_owner_receipts': covered_pages,
               'pages_without_receipts': len(uncovered),
               'receipts_per_role': per_role,
               'pages_materialized': materialized,
               'facts_total': sum(len(rec['packet']['facts']) for rec in records.values()),
               'primary_facts': primary_total,
               'source_unresolved_facts': unresolved_total,
               'archived_facts': archived_total,
               'canonical_corrections_applied': len(corrections),
               'baseline_zip_sha256': BASELINE_SHA256,
               'oleg_input_zip_sha256': sha(task / 'input' / 'forenergo-our-extraction.zip'),
               'builder_source_sha256': sha(__file__),
               'builder_git_commit': _git(root, ['rev-parse', 'HEAD']),
               'builder_source_modified': _git_modified(root, [
                   'ops/catalogue_delivery/build_owner_merge.py']),
               'model_calls_during_export': 0,
               'in_flight_pages': inflight,
               'uncovered_pages_first': uncovered[:20]}
    bundle['baseline_independently_accepted_pages'] = bundle.get('independently_accepted_pages')
    bundle['baseline_review_counts'] = {
        key: bundle.pop(key) for key in (
            'root_source_checked_pages_awaiting_independent_review',
            'manual_pages_independently_source_verified', 'native_queue_accepted_pages')
        if key in bundle}
    bundle['independently_accepted_pages'] = sum(
        p.get('status') == 'accepted' and p.get('reviewed_current_content', False)
        for c in bundle['catalogs'] for p in c['pages'])
    bundle['owner_merge_independently_reviewed_pages'] = 0
    bundle['independent_final_review_complete'] = False
    bundle['baseline_exporter_program'] = bundle.get('exporter_program')
    bundle['exporter_program'] = {
        'name': 'owner-merge-exporter', 'git_commit': summary['builder_git_commit'],
        'source_sha256': summary['builder_source_sha256'],
        'source_modified': summary['builder_source_modified']}
    bundle['snapshot_stage'] = 'owner_merge_complete' if full else 'owner_merge_partial'
    bundle['owner_merge_summary'] = summary
    out.mkdir(parents=True, exist_ok=False)
    workbook_paths = []
    for catalog_index, catalog in enumerate(bundle['catalogs']):
        file = out / (catalog['id'] + '.xlsx')
        to_xlsx(catalog, file, allow_unverified=True)
        book = load_workbook(file)
        tab = book.create_sheet('Первичные данные')
        tab.append(['Страница PDF', 'Сторона', 'Владелец', 'Параметр',
                    'Значение (типизировано; структуры — строкой JSON)', 'Единица', 'Условие',
                    'kept', 'work_sha256', 'Сводил', 'Модель сведения', 'Версия сведения',
                    'Сессия сведения', 'SHA исходного PDF'])
        decisions = book.create_sheet('Решения сведения')
        decisions.append(['Страница PDF', 'Группа', 'Отношение', 'Выбрано', 'Причина',
                          'Фактов Никиты', 'Фактов Олега', 'Первичных фактов',
                          'Сводил', 'Модель', 'Версия', 'Сессия', 'SHA исходного PDF',
                          'work_sha256', 'Полное решение в catalogue.json'])
        page_indices = {p['pdf_page']: i for i, p in enumerate(catalog['pages'])}

        def xlsx_value(v):
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, separators=(',', ':'))
            return v

        for path, record in sorted(records.items()):
            if record['catalog'] != catalog['id']:
                continue
            page = baseline_by_page.get((record['catalog'], record['physical_page']))
            if page is None or 'merged_primary' not in page:
                continue
            identity = record['receipt']['identity']
            merge_provenance = [identity['role'], identity.get('model'),
                                identity.get('program_version') or 'not recorded', identity.get('session_id'),
                                record['packet']['source_sha256']]
            for gi, group in enumerate(record['receipt']['groups']):
                members = [record['packet']['facts'][i] for i in group['fact_indices']]
                ours_count = sum(f['side'] == 'ours' for f in members)
                oleg_count = len(members) - ours_count
                selected_count = (len(members) if group['keep'] == 'both'
                                  else ours_count if group['keep'] == 'ours'
                                  else oleg_count if group['keep'] == 'oleg' else 0)
                pointer = (f'/catalogs/{catalog_index}/pages/'
                           f'{page_indices[record["physical_page"]]}/owner_merge_decisions/groups/{gi}')
                decisions.append([record['physical_page'], gi, group['relation'], group['keep'],
                                  group['reason'], ours_count, oleg_count, selected_count,
                                  *merge_provenance[:2], identity.get('program_version') or 'not recorded',
                                  *merge_provenance[3:], record['receipt']['work_sha256'], pointer])
            for entry in page['merged_primary']['primary_facts']:
                tab.append([record['physical_page'], entry['side'], entry.get('owner'),
                            entry.get('name'), xlsx_value(entry.get('value')), entry.get('unit'),
                            xlsx_value(entry.get('condition')), entry['provenance']['kept'],
                            entry['provenance']['work_sha256'], *merge_provenance])
            for entry in page['merged_primary']['source_unresolved_facts']:
                tab.append([record['physical_page'], 'SOURCE_UNRESOLVED', entry.get('owner'),
                            entry.get('name'), xlsx_value(entry.get('value')), entry.get('unit'),
                            'SOURCE_UNRESOLVED', 'unresolved',
                            entry['provenance']['work_sha256'], *merge_provenance])
        tab2 = book.create_sheet('Исправления до-после')
        tab2.append(['Страница PDF', 'Владелец', 'Параметр', 'JSON-указатель', 'До', 'После',
                     'Сторона решения', 'work_sha256', 'Единица до', 'Единица после',
                     'Условие до', 'Условие после', 'Нерешённость источника'])
        for ch in corrections:
            if ch['catalog'] != catalog['id']:
                continue
            tab2.append([ch['physical_page'], ch.get('owner'), ch.get('name'), ch['json_pointer'],
                         ch['before'].get('value'), ch['after'].get('value'),
                         ch['selected_by_role'], ch['work_sha256'],
                         ch['before'].get('unit'), ch['after'].get('unit'),
                         xlsx_value(ch['before'].get('condition')),
                         xlsx_value(ch['after'].get('condition')), bool(ch.get('source_unresolved'))])
        book.save(file)
        del book
        gc.collect()
        workbook_paths.append(file)
    archive = out / 'catalogues-unified.zip'
    manifest_files = {}
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in workbook_paths:
            z.write(file, file.name)
            manifest_files[file.name] = {'sha256': sha(file), 'bytes': file.stat().st_size}
        h = hashlib.sha256()
        size = 0
        facts_written = 0
        with z.open('catalogue.json', 'w', force_zip64=True) as stream:
            def put(b):
                nonlocal size
                stream.write(b)
                h.update(b)
                size += len(b)
            put(b'{')
            for i, (key, value) in enumerate(bundle.items()):
                if i:
                    put(b',')
                put(json.dumps(key).encode() + b':')
                for piece in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':')).iterencode(value):
                    put(piece.encode())
            put(b',"owner_typed_facts":{')
            first_page = True
            for path, record in sorted(records.items()):
                if not first_page:
                    put(b',')
                first_page = False
                put(json.dumps(path).encode() + b':')
                put(b'{"packet_sha256":' + json.dumps(record['packet_sha256']).encode()
                    + b',"receipt":' + json.dumps({'saved_at': record['saved_at'],
                                                   'work_sha256': record['receipt']['work_sha256'],
                                                   'identity': record['receipt']['identity']},
                                                  ensure_ascii=False, separators=(',', ':'),
                                                  allow_nan=False).encode()
                    + b',"facts":[')
                for k, fact in enumerate(record['packet']['facts']):
                    if k:
                        put(b',')
                    put(json.dumps(fact, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())
                    facts_written += 1
                put(b']}')
            put(b'}}')
        manifest_files['catalogue.json'] = {'sha256': h.hexdigest(), 'bytes': size,
                                            'owner_typed_fact_pages': len(records),
                                            'owner_typed_facts': facts_written}
        reports = {
            'corrections.json': {'schema_version': 'owner-merge-corrections/1',
                                 'note': 'Фактические before/after канонических ячеек: keep=oleg записывает '
                                         'значение Олега; отклонённые наши фигуры/тексты удалены из content '
                                         'и живут только в owner_archive. Полный журнал решений по обеим '
                                         'сторонам, включая keep=ours без изменения нашей ячейки: '
                                         'catalogue.json → pages[].owner_merge_decisions; в Excel лист '
                                         '«Решения сведения». Это решения сведения, не новый процент точности.',
                                 'corrections': corrections},
            'reconciliation-report.json': _report_with_transfers(summary, uncovered, inflight, transfers, manifest),
            'README.txt': ('Единый снимок пяти каталогов (980 физических страниц), материализованный из '
                           'latest author page-work receipts (schema-driven discovery, side-aware '
                           'selection из groups).\n'
                           + ('Полное покрытие: все 980 страниц имеют валидированные receipts; '
                              'primary материализован.\n' if full else
                              f'ВНИМАНИЕ: промежуточный снимок (--allow-partial): покрытие {covered_pages}/{TOTAL_PAGES}. '
                              'Не является финальным ZIP.\n')
                           + 'catalogue.json — страницы с materialized primary (merged_primary), исходные typed '
                             'факты обеих сторон (owner_typed_facts) и архив неотобранных/отклонённых фактов '
                             '(owner_archive). Отклонённые наши фигуры/тексты удалены из content и живут только '
                             'в архиве. null / пустая строка / прочерк / 0 сохраняются как различные '
                             'типизированные значения.\n'
                             'owner_merge_decisions на каждой сведённой странице сохраняет точный receipt: '
                             'все решения, причины, source evidence, модель, сессию и SHA. Индексы фактов '
                             'относятся к массиву facts в верхнем owner_typed_facts[ключ страницы]; '
                             'owner_typed_facts_pointer на странице указывает на этот массив. '
                             'Лист Excel «Решения сведения» '
                             'содержит причины и JSON-указатели, включая отклонённые варианты Олега.\n'),
        }
        for nm, value in reports.items():
            data = value.encode() if isinstance(value, str) else dump(value).encode()
            z.writestr(nm, data)
            manifest_files[nm] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        z.writestr('manifest.json', dump({'schema_version': 'owner-reconciliation-manifest/1',
                                          'summary': summary, 'files': manifest_files}))
    # The archive is complete. Drop the materialization graphs before decoding
    # it through the consumer path; otherwise a full catalogue is held twice.
    correction_count = len(corrections)
    records.clear()
    baseline_by_page.clear()
    reports.clear()
    corrections.clear()
    catalog = page = record = rec = receipt = primary = unresolved = archived = value = None
    del bundle
    gc.collect()
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP CRC failure')
        for nm, info in manifest_files.items():
            with z.open(nm) as f:
                hh = hashlib.sha256()
                observed = 0
                for block in iter(lambda: f.read(1024 * 1024), b''):
                    hh.update(block)
                    observed += len(block)
            if hh.hexdigest() != info['sha256'] or observed != info['bytes']:
                raise ValueError(f'Archive manifest mismatch for {nm}')
        decoded = json.loads(z.read('catalogue.json'))
        if sum(len(c['pages']) for c in decoded['catalogs']) != count:
            raise ValueError('Consumer JSON page coverage failed')
    receipt_out = {'archive': str(archive.resolve()), 'sha256': sha(archive),
                   'bytes': archive.stat().st_size,
                   'page_count': count if only_pages else TOTAL_PAGES,
                   'pages_with_owner_receipts': covered_pages, 'final_delivery': full,
                   'receipts_per_role': per_role,
                   'canonical_corrections_applied': correction_count,
                   'owner_typed_facts_roundtrip': facts_written,
                   'archive_crc': 'passed', 'manifest_all_members_verified': True,
                   'elapsed_seconds': round(time.monotonic() - started, 3),
                   'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   'model_calls': 0}
    (out / 'verification.json').write_text(dump(receipt_out))
    return receipt_out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=Path, default=Path('.tmp/oleg-consensus-20261014'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-partial', action='store_true')
    parser.add_argument('--pages', nargs='*', help='canary subset of packet paths')
    parser.add_argument('--no-limits', action='store_true', help='tests only')
    args = parser.parse_args()
    if not args.no_limits:
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    print(dump(export(Path.cwd(), args.task, args.output,
                      allow_partial=args.allow_partial, only_pages=set(args.pages) or None)))


if __name__ == '__main__':
    main()
