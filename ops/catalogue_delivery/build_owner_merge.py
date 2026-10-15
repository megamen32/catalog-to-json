"""Whole-owner exporter: latest authored page-work receipts of all three roles.

Reads the immutable full-alignment packets, the actual owner receipts written
through ``page_work.save_page_work`` (identical ``catalogue-single-owner-page-work/1``
schema for codex/zcode/minimax) and the recorded ownership transfers, validates
packet/owner/work hashes and exact index coverage, then materialises one
lossless delivery: canonical JSON (baseline pages + per-page owner reconciliation
with full typed facts and raw alternatives), five Excel workbooks, and a
corrections/dispositions report. Canonical cells are never rewritten by this
stage; owner selections are exported as explicit dispositions for the deferred
independent final review.

A snapshot below full coverage is emitted only with ``--allow-partial`` and is
explicitly marked as not final. No model calls, no extraction, no benchmark.
"""
from __future__ import annotations

import argparse
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


def page_dispositions(record):
    """Per-fact dispositions from every role receipt on this page."""
    dispositions = []
    for role, receipt in sorted(record['receipts'].items()):
        for i in receipt['selected_fact_indices']:
            dispositions.append({'fact_index': i, 'side': record['facts'][i]['side'],
                                 'fact_id': record['facts'][i].get('fact_id'),
                                 'fact_sha256': record['facts'][i].get('input_fact_sha256'),
                                 'disposition': 'selected', 'role': role,
                                 'work_sha256': receipt['work_sha256']})
        for i in receipt['source_unresolved_fact_indices']:
            dispositions.append({'fact_index': i, 'side': record['facts'][i]['side'],
                                 'fact_id': record['facts'][i].get('fact_id'),
                                 'fact_sha256': record['facts'][i].get('input_fact_sha256'),
                                 'disposition': 'source_unresolved', 'role': role,
                                 'work_sha256': receipt['work_sha256']})
    dispositions.sort(key=lambda d: (d['fact_index'], d['role']))
    return dispositions



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
    covered = {page: any(r['receipts'] for r in [rec]) for page, rec in records.items()}
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
    # Attach per-page owner reconciliation. Canonical cells are NOT rewritten:
    # owner selections are exported as explicit dispositions; raw typed facts and
    # alternatives of both sides are embedded losslessly for the final review.
    attached = 0
    for path, record in sorted(records.items()):
        if not record['receipts']:
            continue
        key = (record['catalog'], record['physical_page'])
        page = baseline_by_page.get(key)
        if page is None:
            # Canary/partial baselines may not carry every synthetic page;
            # the reconciliation record still goes into the streamed JSON.
            continue
        page['owner_reconciliation'] = {
            'owner': record['owner'],
            'packet_sha256': record['packet_sha256'],
            'receipts': record['receipts'],
            'dispositions': page_dispositions(record),
            'typed_facts': record['facts'],
        }
        PageContent.model_validate(page['content'])
        attached += 1
    per_role = {role: sum(1 for rec in records.values() if role in rec['receipts']) for role in ROLES}
    summary = {'schema_version': 'owner-reconciliation-snapshot/1',
               'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'final_delivery': full, 'allow_partial_used': allow_partial,
               'required_roles': list(ROLES),
               'total_pages': TOTAL_PAGES, 'pages_with_owner_receipts': covered_pages,
               'pages_without_receipts': len(uncovered),
               'receipts_per_role': per_role,
               'facts_total': sum(len(rec['facts']) for rec in records.values()),
               'facts_with_selected_disposition': sum(1 for rec in records.values()
                                                      for r in rec['receipts'].values()
                                                      for _ in r['selected_fact_indices']),
               'facts_marked_source_unresolved': sum(1 for rec in records.values()
                                                     for r in rec['receipts'].values()
                                                     for _ in r['source_unresolved_fact_indices']),
               'canonical_cells_changed': 0,
               'canonical_write_policy': 'Не выполняется на этом этапе: выбор владельца экспортируется как явная '
                                         'диспозиция; запись в канонические ячейки возможна только после отложенной '
                                         'независимой финальной проверки.',
               'baseline_zip_sha256': BASELINE_SHA256,
               'oleg_input_zip_sha256': sha(task / 'input' / 'forenergo-our-extraction.zip'),
               'builder_source_sha256': sha(__file__),
               'builder_git_commit': _git(root, ['rev-parse', 'HEAD']),
               'builder_source_modified': _git_modified(root),
               'model_calls_during_export': 0,
               'uncovered_pages_first': uncovered[:20]}
    bundle['baseline_independently_accepted_pages'] = bundle.get('independently_accepted_pages')
    bundle['snapshot_stage'] = 'owner_reconciliation_complete' if full else 'owner_reconciliation_partial'
    bundle['owner_reconciliation_summary'] = summary
    out.mkdir(parents=True, exist_ok=False)
    # Five standard workbooks, texts/drawings/producers preserved by the exporter.
    workbook_paths = []
    for catalog in bundle['catalogs']:
        file = out / (catalog['id'] + '.xlsx')
        to_xlsx(catalog, file, allow_unverified=True)
        book = load_workbook(file)
        tab = book.create_sheet('Сведение владельцев')
        tab.append(['Страница PDF', 'Роль', 'saved_at', 'Выбрано фактов', 'source_unresolved', 'work_sha256'])
        for path, record in sorted(records.items()):
            if record['catalog'] != catalog['id'] or not record['receipts']:
                continue
            for role, receipt in sorted(record['receipts'].items()):
                tab.append([record['physical_page'], role, receipt['saved_at'],
                            len(receipt['selected_fact_indices']),
                            len(receipt['source_unresolved_fact_indices']), receipt['work_sha256']])
        book.save(file)
        del book
        gc.collect()
        workbook_paths.append(file)
    corrections = []
    for path, record in sorted(records.items()):
        if not record['receipts']:
            continue
        for d in page_dispositions(record):
            corrections.append({'catalog': record['catalog'], 'physical_page': record['physical_page'], **d})
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
            'corrections.json': {'schema_version': 'owner-dispositions/1',
                                 'note': 'Диспозиции владельцев по каждому факту; канонические ячейки на этом этапе не переписываются.',
                                 'dispositions': corrections},
            'reconciliation-report.json': {'summary': summary,
                                           'uncovered_pages': uncovered,
                                           'ownership_transfers': [t for k, t in sorted(transfers.items())
                                                                   if k in {(e['catalog'], e['physical_page'])
                                                                            for e in manifest['pages']}]},
            'README.txt': ('Единый снимок пяти каталогов (980 физических страниц) с owner-reconciliation.\n'
                           + ('Полное покрытие: все 980 страниц имеют авторские page-work receipts.\n'
                              if full else
                              f'ВНИМАНИЕ: промежуточный снимок (--allow-partial): покрытие {covered_pages}/{TOTAL_PAGES}.\n')
                           + 'catalogue.json — базовые страницы + owner_reconciliation (receipts, диспозиции) + owner_typed_facts '
                             '(полные типизированные факты обеих сторон с исходными значениями и альтернативами).\n'
                             'Канонические ячейки этим экспортом не переписываются; выбор владельца — явная диспозиция для '
                             'отложенной независимой финальной проверки.\n'),
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
            book = load_workbook(io.BytesIO(z.read(catalog['id'] + '.xlsx')), read_only=True, data_only=False)
            rows = list(book['Сведение владельцев'].iter_rows(min_row=2, values_only=True))
            expected = sorted((rec['physical_page'], role, rec['receipts'][role]['saved_at'],
                               len(rec['receipts'][role]['selected_fact_indices']),
                               len(rec['receipts'][role]['source_unresolved_fact_indices']),
                               rec['receipts'][role]['work_sha256'])
                              for rec in records.values() if rec['catalog'] == catalog['id']
                              for role in rec['receipts'])
            actual = sorted(rows)
            if actual != expected:
                raise ValueError(f'Excel lost owner reconciliation rows for {catalog["id"]}')
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
