"""Whole-owner exporter that MATERIALIZES the latest authored page-work.

The latest page-work receipt of every role selects typed input facts. This
exporter builds the PRIMARY delivery from the selected facts: values chosen by
the page owner (including Oleg-side values and Oleg-only facts) become the
canonical content, with verified before/after corrections on the baseline
cells; Oleg-only selected facts are materialised into a new canonical per-page
fact section with full provenance. Facts that were neither selected nor marked
unresolved go to the archive section only; source-unresolved facts stay
explicitly visible and marked. null / blank / dash / 0 stay distinct typed
values end to end.

Inputs: immutable full-alignment packets, actual owner receipts written through
``page_work.save_page_work`` (one shared schema for codex/zcode/minimax) and
recorded ownership transfers. Every packet/owner/work hash and the exact index
coverage are validated before anything is exported. The final delivery
hard-requires all 980 pages with receipts; a snapshot below full coverage is
emitted only with ``--allow-partial`` and is explicitly marked not final.
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
from catalog_json.export import to_xlsx
from catalog_json.reconciliation.formats import exact_json_equal
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


def load(path):
    return json.loads(Path(path).read_text())


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def receipt_candidates(reviews, catalog, page, role):
    """Known on-disk receipt locations for one role/page, oldest layout first."""
    stem = f'{catalog}-{page:04d}'
    if role == 'zcode':
        names = [f'{stem}-page-work.json', f'{stem}-page-work-sem2.json', f'{stem}-page-work-revised.json']
        folder = reviews / 'zcode' / 'full-work'
        return [folder / n for n in names]
    if role == 'codex':
        return [reviews / 'codex' / 'full-work' / f'{stem}.json']
    return [reviews / 'minimax' / 'full-work' / f'{stem}' / 'result.json']


def norm(v):
    return re.sub(r'\s+', ' ', str(v)).strip() if v is not None else None


def latest_receipt(reviews, catalog, page, role):
    """Latest authored receipt by saved_at among existing candidates."""
    best = None
    for path in receipt_candidates(reviews, catalog, page, role):
        if not path.exists():
            continue
        receipt = load(path)
        if receipt.get('schema_version') != RECEIPT_SCHEMA:
            raise ValueError(f'{path}: unexpected receipt schema {receipt.get("schema_version")!r}')
        if best is None or receipt['saved_at'] > best[1]['saved_at']:
            best = (path, receipt)
    return best


def validate_receipt(receipt, path, packet, packet_sha256, owner):
    if receipt.get('work_packet_sha256') != packet_sha256:
        raise ValueError(f'{path}: work_packet_sha256 does not bind the exact immutable packet')
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
    selected = receipt.get('selected_fact_indices')
    unresolved = receipt.get('source_unresolved_fact_indices')
    total = len(packet['facts'])
    for name, indices in (('selected', selected), ('unresolved', unresolved)):
        if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < total for i in indices):
            raise ValueError(f'{path}: {name} indices out of range')
    if len(set(selected)) != len(selected) or len(set(unresolved)) != len(unresolved):
        raise ValueError(f'{path}: duplicate fact indices')
    if set(selected) & set(unresolved):
        raise ValueError(f'{path}: a fact is both selected and unresolved')
    if len(selected) + len(unresolved) != total:
        raise ValueError(f'{path}: coverage is partial: {len(selected)}+{len(unresolved)} of {total}')


def load_transfers(task):
    path = task / 'ownership-transfers' / 'index.json'
    transfers = {}
    if path.exists():
        for item in load(path)['transfers']:
            key = (item['catalog'], item['physical_page'])
            if key in transfers:
                raise ValueError(f'Duplicate ownership transfer for {key}')
            candidates = [task / item['packet'], task.parent / item['packet'], Path(item['packet'])]
            packet_path = next((p for p in candidates if p.exists()), candidates[0])
            if sha(packet_path) != item['packet_sha256']:
                raise ValueError(f'Transfer packet changed for {key}')
            if not item.get('fact_store_unchanged'):
                raise ValueError(f'Transfer for {key} claims changed facts')
            transfers[key] = {'packet_path': str(packet_path), 'packet_sha256': item['packet_sha256'],
                              'owner': item['owner'], 'previous_owner': item['previous_owner'],
                              'original_packet_sha256': item['original_packet_sha256']}
    return transfers


def collect_receipts(task, reviews, manifest, transfers, only_pages=None):
    """Latest validated receipt per (page, role). Returns per-page records."""
    pages = {}
    for entry in manifest['pages']:
        key = (entry['catalog'], entry['physical_page'])
        if only_pages is not None and entry['path'] not in only_pages:
            continue
        transfer = transfers.get(key)
        owner = transfer['owner'] if transfer else entry['owner']
        if transfer and transfer['original_packet_sha256'] != entry['sha256']:
            raise ValueError(f'Transfer for {key} does not bind the manifest packet')
        packet_path = transfer['packet_path'] if transfer else task / 'full-alignment-work-v2' / entry['path']
        packet_sha = transfer['packet_sha256'] if transfer else entry['sha256']
        packet = load(packet_path)
        if sha(packet_path) != packet_sha:
            raise ValueError(f'Immutable packet changed for {key}')
        if packet.get('physical_page') != entry['physical_page'] or packet.get('catalog') != entry['catalog']:
            raise ValueError(f'Packet identity mismatch for {key}')
        roles = {}
        for role in ROLES:
            found = latest_receipt(reviews, entry['catalog'], entry['physical_page'], role)
            if found is None:
                continue
            path, receipt = found
            # A receipt must carry the page's CURRENT owner, not just any role.
            validate_receipt(receipt, path, packet, packet_sha, owner)
            roles[role] = {'path': str(path), 'saved_at': receipt['saved_at'],
                           'work_sha256': receipt['work_sha256'],
                           'identity': {'role': role, 'session_id': receipt['identity']['session_id'],
                                        'model': receipt['identity']['model']},
                           'selected_fact_indices': receipt['selected_fact_indices'],
                           'source_unresolved_fact_indices': receipt['source_unresolved_fact_indices']}
        pages[entry['path']] = {'catalog': entry['catalog'], 'physical_page': entry['physical_page'],
                                'source_sha256': entry['source_sha256'], 'owner': owner,
                                'packet_path': str(packet_path), 'packet_sha256': packet_sha,
                                'facts': packet['facts'], 'receipts': roles}
    return pages


def resolve_cell_pointer(fact, packet_facts, baseline_page):
    """Canonical cell pointer for a selected OLEG fact: the unique OURS fact
    with the same owner+name provides the verified pointer; the baseline cell
    must still hold exactly the ours typed value."""
    if fact.get('pointer', '').startswith('/catalogs/') and '/cells/' in fact.get('pointer', ''):
        return fact['pointer']
    candidates = [f for f in packet_facts
                  if f['side'] == 'ours' and f.get('owner') == fact.get('owner')
                  and norm(f.get('name')) == norm(fact.get('name'))
                  and f.get('pointer', '').startswith('/catalogs/')]
    if len(candidates) != 1:
        return None
    return candidates[0]['pointer']


def materialize_page(record, baseline_page):
    """Build primary/archive/corrections for one page from its latest receipt.

    Returns (page_primary, archived_facts, corrections). Canonical cells on the
    baseline page are updated only for selected OLEG facts with a unique
    verified pointer whose baseline value still equals the OURS typed value.
    """
    packet_facts = record['facts']
    receipt = next(r for r in sorted(record['receipts'].values(), key=lambda r: r['saved_at'], reverse=True))
    selected = set(receipt['selected_fact_indices'])
    unresolved_idx = set(receipt['source_unresolved_fact_indices'])
    # A selected OLEG fact claims its cell: the OURS fact at the same pointer
    # becomes an archived alternative (both were selected by keep=oleg/both).
    claimed_pointers = set()
    for i in selected:
        f = packet_facts[i]
        if f['side'] == 'oleg':
            p = resolve_cell_pointer(f, packet_facts, None)
            if p:
                claimed_pointers.add(p)
    primary, unresolved, archived, corrections = [], [], [], []
    for i, fact in enumerate(packet_facts):
        entry = {'fact_id': fact.get('fact_id'), 'side': fact['side'], 'kind': fact.get('kind'),
                 'owner': fact.get('owner'), 'name': fact.get('name'),
                 'unit': fact.get('unit'), 'condition': fact.get('condition'),
                 'value': fact.get('value'),
                 'value_state': (fact.get('raw', {}) or {}).get('value_state')
                 or (fact.get('raw_semantic_context', {}) or {}).get('value_state'),
                 'pointer': fact.get('pointer'),
                 'provenance': {'input_fact_sha256': fact.get('input_fact_sha256'),
                                'selected_by_role': receipt['identity']['role'],
                                'work_sha256': receipt['work_sha256']}}
        if i in selected and fact['side'] == 'ours' and fact.get('pointer') in claimed_pointers:
            archived.append({**entry, 'archived_reason': 'alternative: oleg-side value materialized for this cell'})
            continue
        if i in selected:
            primary.append(entry)
            if fact['side'] == 'oleg':
                pointer = resolve_cell_pointer(fact, packet_facts, baseline_page)
                counterpart = next((f for f in packet_facts
                                    if f['side'] == 'ours' and f.get('pointer') == pointer), None) if pointer else None
                if pointer and counterpart is not None:
                    parts = pointer.strip('/').split('/')
                    cell = (baseline_page['content']['tables'][int(parts[6])]['rows'][int(parts[8])]
                            ['cells'][int(parts[10])])
                    before = copy.deepcopy(cell)
                    if norm(cell.get('value')) != norm(counterpart.get('value')):
                        raise ValueError(f'Baseline drift at {pointer}: '
                                         f'{cell.get("value")!r} != ours fact {counterpart.get("value")!r}')
                    if not exact_json_equal(norm(cell.get('value')), norm(fact.get('value'))):
                        after = copy.deepcopy(cell)
                        after['value'] = fact.get('value')
                        state = (fact.get('raw', {}) or {}).get('value_state') or                                 (fact.get('raw_semantic_context', {}) or {}).get('value_state')
                        after['state'] = 'blank' if state == 'source_blank' and fact.get('value') in (None, '') else 'value'
                        cell['value'] = after['value']
                        cell['state'] = after['state']
                        corrections.append({'catalog': record['catalog'],
                                            'physical_page': record['physical_page'],
                                            'json_pointer': pointer,
                                            'owner': fact.get('owner'), 'name': fact.get('name'),
                                            'before': before, 'after': after,
                                            'selected_fact_id': fact.get('fact_id'),
                                            'archived_fact_id': counterpart.get('fact_id'),
                                            'selected_by_role': receipt['identity']['role'],
                                            'work_sha256': receipt['work_sha256']})
        elif i in unresolved_idx:
            e = dict(entry)
            e['source_unresolved'] = True
            unresolved.append(e)
        else:
            archived.append(entry)
    return primary, unresolved, archived, corrections


def _git(root, args, check=True):
    try:
        out = subprocess.run(['git', '-C', str(root), *args], check=check,
                             capture_output=True, text=True)
        return out.stdout.strip() if check else out.returncode
    except (subprocess.CalledProcessError, FileNotFoundError):
        if check:
            return 'unknown'
        return -1


def _git_modified(root):
    return _git(root, ['diff', '--quiet', 'HEAD', '--', 'ops/catalogue_delivery/build_owner_merge.py'],
                check=False) != 0


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


def export(root, task, out, *, allow_partial=False, only_pages=None):
    started = time.monotonic()
    out = Path(out)
    if out.exists():
        raise ValueError(f'Output directory already exists: {out}')
    check_capacity(out)
    manifest = load(task / 'full-alignment-work-v2' / 'manifest.json')
    transfers = load_transfers(task)
    records = collect_receipts(task, task / 'reviews', manifest, transfers, only_pages)
    covered_pages = sum(1 for rec in records.values() if rec['receipts'])
    uncovered = sorted(path for path, rec in records.items() if not rec['receipts'])
    full = covered_pages == TOTAL_PAGES and not uncovered
    if not full and not allow_partial:
        raise ValueError(f'Final delivery refused: {covered_pages}/{TOTAL_PAGES} pages have owner receipts '
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
    # Materialize: selected typed facts become primary; selected Oleg-side
    # values are written into verified baseline cells with before/after;
    # Oleg-only selected facts form the new canonical per-page fact section;
    # unselected facts go to the per-page archive; unresolved stay explicit.
    corrections = []
    materialized = 0
    for path, record in sorted(records.items()):
        if not record['receipts']:
            continue
        key = (record['catalog'], record['physical_page'])
        page = baseline_by_page.get(key)
        primary, unresolved, archived, page_corrections = materialize_page(record, page) if page else             ([], [], [], [])
        corrections.extend(page_corrections)
        record['primary_facts'] = primary
        record['unresolved_facts'] = unresolved
        record['archived_facts'] = archived
        if page is not None:
            page['merged_primary'] = {
                'owner': record['owner'],
                'packet_sha256': record['packet_sha256'],
                'receipts': {role: {'saved_at': r['saved_at'], 'work_sha256': r['work_sha256'],
                                    'identity': r['identity'],
                                    'selected_fact_indices': r['selected_fact_indices'],
                                    'source_unresolved_fact_indices': r['source_unresolved_fact_indices']}
                             for role, r in record['receipts'].items()},
                'primary_facts': primary,
                'source_unresolved_facts': unresolved,
            }
            page['owner_archive'] = {'archived_facts': archived,
                                     'note': 'Не отобранные владельцем исходные факты; только архив, не первичные данные.'}
            PageContent.model_validate(page['content'])
            materialized += 1
    per_role = {role: sum(1 for rec in records.values() if role in rec['receipts']) for role in ROLES}
    summary = {'schema_version': 'owner-reconciliation-snapshot/1',
               'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'final_delivery': full, 'allow_partial_used': allow_partial,
               'required_roles': list(ROLES),
               'total_pages': TOTAL_PAGES, 'pages_with_owner_receipts': covered_pages,
               'pages_without_receipts': len(uncovered),
               'pages_materialized': materialized,
               'receipts_per_role': per_role,
               'facts_total': sum(len(rec['facts']) for rec in records.values()),
               'primary_facts': sum(len(rec.get('primary_facts', [])) for rec in records.values()),
               'source_unresolved_facts': sum(len(rec.get('unresolved_facts', [])) for rec in records.values()),
               'archived_facts': sum(len(rec.get('archived_facts', [])) for rec in records.values()),
               'canonical_corrections_applied': len(corrections),
               'baseline_zip_sha256': BASELINE_SHA256,
               'oleg_input_zip_sha256': sha(task / 'input' / 'forenergo-our-extraction.zip'),
               'builder_source_sha256': sha(__file__),
               'builder_git_commit': _git(root, ['rev-parse', 'HEAD']),
               'builder_source_modified': _git_modified(root),
               'model_calls_during_export': 0,
               'uncovered_pages_first': uncovered[:20]}
    bundle['baseline_independently_accepted_pages'] = bundle.get('independently_accepted_pages')
    bundle['snapshot_stage'] = 'owner_merge_complete' if full else 'owner_merge_partial'
    bundle['owner_merge_summary'] = summary
    out.mkdir(parents=True, exist_ok=False)
    workbook_paths = []
    for catalog in bundle['catalogs']:
        file = out / (catalog['id'] + '.xlsx')
        to_xlsx(catalog, file, allow_unverified=True)
        book = load_workbook(file)
        tab = book.create_sheet('Первичные данные')
        tab.append(['Страница PDF', 'Сторона', 'Владелец', 'Параметр', 'Значение (типизировано; '
                    'структуры — строкой JSON)', 'Единица', 'Условие', 'Источник решения', 'work_sha256'])

        def xlsx_value(v):
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, separators=(',', ':'))
            return v

        for path, record in sorted(records.items()):
            if record['catalog'] != catalog['id']:
                continue
            for entry in record.get('primary_facts', []):
                tab.append([record['physical_page'], entry['side'], entry.get('owner'),
                            entry.get('name'), xlsx_value(entry.get('value')), entry.get('unit'),
                            xlsx_value(entry.get('condition')), entry['provenance']['selected_by_role'],
                            entry['provenance']['work_sha256']])
            for entry in record.get('unresolved_facts', []):
                tab.append([record['physical_page'], 'SOURCE_UNRESOLVED', entry.get('owner'),
                            entry.get('name'), xlsx_value(entry.get('value')), entry.get('unit'),
                            'SOURCE_UNRESOLVED', '—', '—'])
        tab2 = book.create_sheet('Исправления до-после')
        tab2.append(['Страница PDF', 'Владелец', 'Параметр', 'JSON-указатель', 'До', 'После',
                     'Сторона решения', 'work_sha256'])
        for ch in corrections:
            if ch['catalog'] != catalog['id']:
                continue
            tab2.append([ch['physical_page'], ch.get('owner'), ch.get('name'), ch['json_pointer'],
                         ch['before'].get('value'), ch['after'].get('value'),
                         ch['selected_by_role'], ch['work_sha256']])
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
                if not record['receipts']:
                    continue
                if not first_page:
                    put(b',')
                first_page = False
                put(json.dumps(path).encode() + b':')
                put(b'{"packet_sha256":' + json.dumps(record['packet_sha256']).encode()
                    + b',"receipts":' + json.dumps(record['receipts'], ensure_ascii=False,
                                                    separators=(',', ':'), allow_nan=False).encode()
                    + b',"facts":[')
                for k, fact in enumerate(record['facts']):
                    if k:
                        put(b',')
                    put(json.dumps(fact, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())
                    facts_written += 1
                put(b']}')
            put(b'}}')
        manifest_files['catalogue.json'] = {'sha256': h.hexdigest(), 'bytes': size,
                                            'owner_typed_fact_pages': sum(1 for rec in records.values() if rec['receipts']),
                                            'owner_typed_facts': facts_written}
        reports = {
            'corrections.json': {'schema_version': 'owner-merge-corrections/1',
                                 'note': 'Фактические before/after канонических ячеек из selected typed facts; '
                                         'не выбранные факты — только в архиве (owner_archive/owner_typed_facts).',
                                 'corrections': corrections},
            'reconciliation-report.json': {'summary': summary, 'uncovered_pages': uncovered,
                                           'ownership_transfers': [t for k, t in sorted(transfers.items())
                                                                   if k in {(e['catalog'], e['physical_page'])
                                                                            for e in manifest['pages']}]},
            'README.txt': ('Единый снимок пяти каталогов (980 физических страниц), материализованный из '
                           'author page-work receipts.\n'
                           + ('Полное покрытие: все 980 страниц имеют receipts; primary построен из выбранных фактов.\n'
                              if full else
                              f'ВНИМАНИЕ: промежуточный снимок (--allow-partial): покрытие {covered_pages}/{TOTAL_PAGES}. '
                              'Не является финальным ZIP.\n')
                           + 'catalogue.json — страницы с materialized primary (merged_primary), исходные typed факты '
                             'обеих сторон (owner_typed_facts) и архив неотобранных фактов (owner_archive).\n'
                             'null / пустая строка / прочерк / 0 сохраняются как различные типизированные значения.\n'),
        }
        for nm, value in reports.items():
            data = value.encode() if isinstance(value, str) else dump(value).encode()
            z.writestr(nm, data)
            manifest_files[nm] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        z.writestr('manifest.json', dump({'schema_version': 'owner-reconciliation-manifest/1',
                                          'summary': summary, 'files': manifest_files}))
    del bundle
    gc.collect()
    # Consumer readback: CRC, every manifest digest, page coverage, typed-fact
    # lossless roundtrip against the immutable packets, Excel reopen.
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
        emitted = decoded['owner_typed_facts']
        for path, record in sorted(emitted.items()):
            packet = load(task / 'full-alignment-work-v2' / path)
            if record['packet_sha256'] != hashlib.sha256(
                    (task / 'full-alignment-work-v2' / path).read_bytes()).hexdigest():
                raise ValueError(f'{path}: emitted packet hash changed')
            if record['facts'] != packet['facts']:
                raise ValueError(f'{path}: typed facts lost or altered in export')
            # Receipt work hashes were validated against the immutable packets
            # during collection; the emitted copy is checked by the manifest
            # digest of catalogue.json above.
        checked = 0
        for catalog in decoded['catalogs']:
            if not any(rec['catalog'] == catalog['id'] and rec['receipts'] for rec in records.values()):
                continue
            book = load_workbook(io.BytesIO(z.read(catalog['id'] + '.xlsx')), read_only=True, data_only=False)
            rows = list(book['Первичные данные'].iter_rows(min_row=2, values_only=True))
            def xlsx_value(v):
                if isinstance(v, (dict, list)):
                    return json.dumps(v, ensure_ascii=False, separators=(',', ':'))
                return v
            expected = []
            for rec in records.values():
                if rec['catalog'] != catalog['id']:
                    continue
                for fact in rec.get('primary_facts', []):
                    expected.append((rec['physical_page'], fact['side'],
                                     (None if fact.get('value') in ('', None) else xlsx_value(fact.get('value')))))
                for fact in rec.get('unresolved_facts', []):
                    expected.append((rec['physical_page'], 'SOURCE_UNRESOLVED',
                                     (None if fact.get('value') in ('', None) else xlsx_value(fact.get('value')))))
            actual = [(r[0], r[1], (None if r[4] in ('', None) else str(r[4]))) for r in rows]
            key = lambda t: (t[0], t[1], t[2] is None, t[2] or '')
            expected.sort(key=key)
            actual.sort(key=key)
            if actual != expected:
                mismatch = [(e, a) for e, a in zip(expected, actual) if e != a][:3]
                raise ValueError(f'Excel lost materialized primary facts for {catalog["id"]}: {mismatch}')
            checked += len(actual)
            book.close()
    if full and count != TOTAL_PAGES:
        raise ValueError('Final delivery refused: baseline lost pages')
    receipt_out = {'archive': str(archive.resolve()), 'sha256': sha(archive),
                   'bytes': archive.stat().st_size,
                   'page_count': count if only_pages else TOTAL_PAGES,
                   'pages_with_owner_receipts': covered_pages, 'final_delivery': full,
                   'receipts_per_role': per_role, 'excel_rows_roundtrip_checked': checked,
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
    parser.add_argument('--pages', nargs='*', help='canary subset of packet paths (e.g. opn-0059.json)')
    parser.add_argument('--no-limits', action='store_true', help='tests only')
    args = parser.parse_args()
    if not args.no_limits:
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    print(dump(export(Path.cwd(), args.task, args.output,
                      allow_partial=args.allow_partial, only_pages=set(args.pages) or None)))


if __name__ == '__main__':
    main()
