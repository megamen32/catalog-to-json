"""Focused tests for the whole-owner MATERIALIZING exporter.

Synthetic mini-manifest (packets + receipts + transfers) proves the primary
delivery is built from selected typed facts: keep=oleg writes the Oleg value
into the canonical cell with verified before/after; Oleg-only selected facts
become primary; rejected facts go to the archive only; source-unresolved stay
explicitly marked; null/blank/dash/0 stay distinct typed values. Plus one real
canary over already-saved task pages (explicitly partial, no models).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.catalogue_delivery import build_owner_merge as bom  # noqa: E402

from catalog_json.reconciliation.consensus import case_sha256  # noqa: E402

SOURCE_SHA = 'a' * 64
BASELINE_MEMBER = 'all-catalogues-980-pages.json'


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=1).encode()
    path.write_bytes(data)
    return sha_bytes(data)


def make_fact(side, i, value, owner='M-1', name='Параметр', kind='model_parameter'):
    return {'fact_id': f'{"L" if side == "oleg" else "O"}-{side}{i:04d}', 'side': side,
            'catalog': 'small', 'kind': kind, 'pointer': f'{side}:{i}',
            'owner': owner, 'name': name, 'value': value,
            'unit': 'мм', 'condition': '', 'physical_pages': [7],
            'input_fact_sha256': sha_bytes(f'{side}{i}{value}'.encode())}


def make_packet(tmp, page=7, facts=None):
    facts = facts if facts is not None else [
        make_fact('ours', 1, '999', owner='РТ-1', name='Рабочая нагрузка'),
        make_fact('oleg', 1, '123', owner='РТ-1', name='Рабочая нагрузка'),
        make_fact('oleg', 2, 'только-у-Олега', owner='РТ-9', name='Особый параметр'),
        make_fact('ours', 3, None, owner='РТ-2', name='Зазор'),
        make_fact('oleg', 3, '', owner='РТ-2', name='Зазор'),
        make_fact('ours', 4, '–', owner='РТ-3', name='Ход'),
        make_fact('oleg', 4, '0', owner='РТ-3', name='Ход'),
    ]
    packet = {'catalog': 'small', 'source_sha256': SOURCE_SHA, 'physical_page': page,
              'owner': 'zcode', 'facts': facts, 'contexts': {}, 'ledger_rows': [],
              'external_fact_refs': [], 'input_fact_store_sha256': '0' * 64,
              'input_ledger_sha256': '0' * 64}
    path = tmp / 'full-alignment-work-v2' / f'small-{page:04d}.json'
    sha = write(path, packet)
    return packet, path, sha


def digest(receipt):
    return case_sha256({k: v for k, v in receipt.items() if k != 'work_sha256'})


def make_receipt(packet, *, role='zcode', selected, unresolved=None,
                 saved_at='2026-10-15T03:00:00+00:00', session='sess_test'):
    r = {'schema_version': bom.RECEIPT_SCHEMA, 'work_packet_sha256': None,
         'source_sha256': packet['source_sha256'], 'physical_page': packet['physical_page'],
         'catalog': packet['catalog'],
         'identity': {'role': role, 'session_id': session, 'model': f'model::{role}'},
         'source_evidence': [{'bbox': [0, 0, 1, 1], 'observation': 'row verified'}],
         'groups': [], 'selected_fact_indices': selected,
         'source_unresolved_fact_indices': unresolved or [],
         'all_input_facts_accounted_for': True, 'owner_work_complete': True,
         'independent_final_review_complete': False,
         'original_alternatives_retained': True, 'saved_at': saved_at, 'work_sha256': ''}
    r['work_sha256'] = digest(r)
    return r


def make_tree(tmp, entries):
    """entries: list of dicts {page, owner, packets:{name: packet}, receipts:{role: (name, receipt)}}"""
    manifest_pages = []
    for e in entries:
        for name, packet in e['packets'].items():
            write(tmp / 'full-alignment-work-v2' / name, packet)
        manifest_pages.append({'path': e['manifest_path'], 'sha256': e['manifest_sha'],
                               'catalog': e['catalog'], 'physical_page': e['page'],
                               'owner': e['owner'], 'facts': e['fact_count'],
                               'ledger_rows': 0, 'residual_model_parameters': 0,
                               'open_ledger_rows': 0, 'source_sha256': SOURCE_SHA})
        for role, (fname, receipt) in e['receipts'].items():
            receipt['work_packet_sha256'] = e['receipt_packet_sha']
            receipt['work_sha256'] = digest(receipt)
            if role == 'zcode':
                p = tmp / 'reviews/zcode/full-work' / fname
            elif role == 'codex':
                p = tmp / 'reviews/codex/full-work' / fname
            else:
                p = tmp / 'reviews/minimax/full-work' / fname / 'result.json'
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(receipt))
    manifest = {'schema_version': 'full-alignment-work/2', 'phase': 'disjoint-owner-work',
                'owners': {'small': 'zcode'}, 'pages': manifest_pages,
                'unlocated_work_packets': [], 'physical_pages': [p['physical_page'] for p in manifest_pages]}
    write(tmp / 'full-alignment-work-v2' / 'manifest.json', manifest)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Page 7: ours cell 999 vs oleg 123 (keep=oleg), oleg-only fact, both-empty
    pair (null vs ''), dash-vs-0 pair; baseline cell holds ours value 999."""
    packet, path, sha = make_packet(tmp_path, 7)
    packet['facts'][0]['pointer'] = '/catalogs/0/pages/0/content/tables/0/rows/0/cells/0'
    sha = write(path, packet)  # re-emit after pointer binding, sha matches bytes
    # keep=oleg scenario: both sides of the 999-vs-123 pair are selected; the
    # materializer writes 123 and archives our 999 as the cell alternative.
    receipt = make_receipt(packet, selected=[0, 1, 2, 3, 4, 5, 6])
    make_tree(tmp_path, [dict(page=7, owner='zcode', catalog='small',
                              manifest_path='small-0007.json', manifest_sha=sha,
                              fact_count=len(packet['facts']),
                              packets={'small-0007.json': packet},
                              receipt_packet_sha=sha,
                              receipts={'zcode': ('small-0007-page-work.json', receipt)})])
    baseline = {'catalogs': [{'id': 'small', 'pages': [
        {'catalog': 'small', 'pdf_page': 7, 'source_sha256': SOURCE_SHA, 'status': 'accepted',
         'columns': [{'id': 'c0', 'label': 'П'}], 'rows': [],
         'content': {'title': 'Т', 'text_blocks': [], 'tables': [
             {'id': 't0', 'title': 'Таблица', 'columns': [{'id': 'c0', 'label': 'П'}],
              'rows': [{'cells': [{'column_id': 'c0', 'value': '999', 'state': 'value'}]}]}],
                     'figures': [], 'source_notes': [], 'uncertainties': []},
         'content_canonical_sha256': 'x', 'texts': [], 'drawings': [], 'source_notes': []}]},
        {'id': 'opn', 'pages': []}]}
    (tmp_path / 'examples/catalogs/all-pages-2026-10-14T172333Z').mkdir(parents=True)
    import zipfile
    zip_path = tmp_path / 'examples/catalogs/all-pages-2026-10-14T172333Z/all-catalogues-980-pages.zip'
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.writestr(BASELINE_MEMBER, json.dumps(baseline))
    monkeypatch.setattr(bom, 'BASELINE_SHA256', sha_bytes(zip_path.read_bytes()))
    (tmp_path / 'input').mkdir(exist_ok=True)
    (tmp_path / 'input' / 'forenergo-our-extraction.zip').write_bytes(b'PK\x05\x06' + b'\x00' * 18)
    return tmp_path


def read_primary(env):
    import zipfile
    with zipfile.ZipFile(env / 'out' / 'catalogues-unified.zip') as z:
        return json.loads(z.read('catalogue.json'))


def test_keep_oleg_materializes_123_and_archives_999(env):
    bom.export(env, env, env / 'out', allow_partial=True)
    data = read_primary(env)
    import zipfile
    with zipfile.ZipFile(env / 'out' / 'catalogues-unified.zip') as z:
        corr = json.loads(z.read('corrections.json'))['corrections']
    page = data['catalogs'][0]['pages'][0]
    cell = page['content']['tables'][0]['rows'][0]['cells'][0]
    assert cell['value'] == '123'  # keep=oleg materialized
    correction = corr[0]
    assert correction['before']['value'] == '999' and correction['after']['value'] == '123'
    # ours 999 is NOT primary anywhere; it survives only as archived alternative
    prim = json.dumps(page['merged_primary'], ensure_ascii=False)
    assert '999' not in prim
    archived = json.dumps(page['owner_archive'], ensure_ascii=False)
    assert '999' in archived
    # oleg-only selected fact IS visible in primary
    prim_facts = page['merged_primary']['primary_facts']
    assert any(f['value'] == 'только-у-Олега' and f['side'] == 'oleg' for f in prim_facts)


def test_null_blank_dash_zero_distinct(env):
    bom.export(env, env, env / 'out', allow_partial=True)
    data = read_primary(env)
    page = data['catalogs'][0]['pages'][0]
    values = [(f['side'], f['value']) for f in page['merged_primary']['primary_facts']]
    assert ('ours', None) in values and ('oleg', '') in values  # blank vs null kept
    assert ('ours', '–') in values and ('oleg', '0') in values  # dash vs zero kept
    assert len({repr(v) for v in values}) == len(values)


def test_unresolved_explicit(env):
    packet = json.loads((env / 'full-alignment-work-v2' / 'small-0007.json').read_text())
    receipt_file = env / 'reviews/zcode/full-work/small-0007-page-work.json'
    receipt = json.loads(receipt_file.read_text())
    # select everything except the last pair member; mark it unresolved
    receipt['selected_fact_indices'] = [0, 1, 2, 3, 4, 5]
    receipt['source_unresolved_fact_indices'] = [6]
    receipt['work_sha256'] = digest(receipt)
    receipt_file.write_text(json.dumps(receipt))
    bom.export(env, env, env / 'out', allow_partial=True)
    data = read_primary(env)
    page = data['catalogs'][0]['pages'][0]
    uns = page['merged_primary']['source_unresolved_facts']
    assert len(uns) == 1 and uns[0]['value'] == '0' and uns[0]['source_unresolved'] is True
    summary = data['owner_merge_summary']
    assert summary['source_unresolved_facts'] == 1


def test_rejected_facts_archive_only(env):
    # In keep=oleg the OURS value 999 is rejected as canonical: it must be
    # archive-only (alternative), never primary.
    bom.export(env, env, env / 'out', allow_partial=True)
    data = read_primary(env)
    page = data['catalogs'][0]['pages'][0]
    prim = json.dumps(page['merged_primary'], ensure_ascii=False)
    assert '999' not in prim
    arch = json.dumps(page['owner_archive'], ensure_ascii=False)
    assert '999' in arch and 'archived_facts' in page['owner_archive']


def test_invalid_owner_rejected(env):
    packet, _, sha = make_packet(env, 8)
    receipt = make_receipt(packet, role='minimax', selected=list(range(len(packet['facts']))))
    receipt['work_packet_sha256'] = sha
    p = env / 'reviews/minimax/full-work/small-0008/result.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt))
    manifest = json.loads((env / 'full-alignment-work-v2' / 'manifest.json').read_text())
    manifest['pages'].append({'path': 'small-0008.json', 'sha256': sha, 'catalog': 'small',
                              'physical_page': 8, 'owner': 'zcode', 'facts': len(packet['facts']),
                              'ledger_rows': 0, 'residual_model_parameters': 0, 'open_ledger_rows': 0,
                              'source_sha256': SOURCE_SHA})
    (env / 'full-alignment-work-v2' / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='not the current owner'):
        bom.export(env, env, env / 'out8', allow_partial=True)


def test_invalid_packet_hash_rejected(env):
    packet, _, sha = make_packet(env, 9)
    receipt = make_receipt(packet, selected=list(range(len(packet['facts']))))
    receipt['work_packet_sha256'] = 'f' * 64
    p = env / 'reviews/zcode/full-work/small-0009-page-work.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt))
    manifest = json.loads((env / 'full-alignment-work-v2' / 'manifest.json').read_text())
    manifest['pages'].append({'path': 'small-0009.json', 'sha256': sha, 'catalog': 'small',
                              'physical_page': 9, 'owner': 'zcode', 'facts': len(packet['facts']),
                              'ledger_rows': 0, 'residual_model_parameters': 0, 'open_ledger_rows': 0,
                              'source_sha256': SOURCE_SHA})
    (env / 'full-alignment-work-v2' / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='work_packet_sha256'):
        bom.export(env, env, env / 'out9', allow_partial=True)


def test_baseline_drift_rejected(env):
    packet = json.loads((env / 'full-alignment-work-v2' / 'small-0007.json').read_text())
    # simulate drifted baseline: ours fact says 999 but baseline cell holds 888
    packet['facts'][0]['value'] = '888'
    (env / 'full-alignment-work-v2' / 'small-0007.json').write_text(json.dumps(packet))
    with pytest.raises(ValueError, match='Immutable packet changed'):
        bom.export(env, env, env / 'out16', allow_partial=True)


def test_final_requires_full_coverage(env):
    with pytest.raises(ValueError, match='Final delivery refused'):
        bom.export(env, env, env / 'out14')


def test_excel_primary_shows_materialized_value(env):
    bom.export(env, env, env / 'out', allow_partial=True)
    from openpyxl import load_workbook
    book = load_workbook(env / 'out' / 'small.xlsx', read_only=True)
    rows = list(book['Первичные данные'].iter_rows(min_row=2, values_only=True))
    # primary facts row for РТ-1 must show the MATERIALIZED 123, not 999
    rt1 = [r for r in rows if r[2] == 'РТ-1']
    assert rt1 and rt1[0][4] == '123'
    corr = list(book['Исправления до-после'].iter_rows(min_row=2, values_only=True))
    assert any(r[4] == '999' and r[5] == '123' for r in corr)
    book.close()


@pytest.mark.slow
def test_real_canary_on_saved_pages():
    root = Path(__file__).resolve().parents[1]
    task = root / '.tmp/oleg-consensus-20261014'
    if not (task / 'full-alignment-work-v2' / 'manifest.json').exists():
        pytest.skip('real task tree not present')
    out = task / 'owner-export' / 'canary'
    if out.exists():
        import shutil
        shutil.rmtree(out)
    receipt = bom.export(root, task, out, allow_partial=True, only_pages={
        'opn-0001.json', 'opn-0002.json', 'opn-0003.json'})
    assert receipt['pages_with_owner_receipts'] == 3
    assert receipt['final_delivery'] is False
    assert receipt['model_calls'] == 0
    assert receipt['owner_typed_facts_roundtrip'] > 0
