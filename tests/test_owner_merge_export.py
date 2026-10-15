"""Focused tests for the whole-owner page-work exporter.

Builds a synthetic mini-manifest (packets + receipts + transfers) in a tmp tree
and exercises the validation and lossless-export contract end to end, plus one
real-canary export over already-saved pages of the actual task tree (no models,
no extraction, explicitly partial).
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


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=1).encode()
    path.write_bytes(data)
    return sha_bytes(data)


def make_fact(side, i, value, kind='model_parameter'):
    return {'fact_id': f'{"L" if side == "oleg" else "O"}-{side}{i:04d}', 'side': side,
            'catalog': 'small', 'kind': kind, 'pointer': f'{side}:{i}',
            'owner': f'M-{i}', 'name': f'Параметр {i}', 'value': value,
            'unit': 'мм', 'condition': '', 'physical_pages': [7],
            'input_fact_sha256': sha_bytes(f'{side}{i}{value}'.encode())}


def make_packet(tmp, page=7, facts=None):
    facts = facts or [make_fact('ours', 1, '10'), make_fact('oleg', 1, '10'),
                      make_fact('ours', 2, None), make_fact('oleg', 2, '–')]
    packet = {'catalog': 'small', 'source_sha256': SOURCE_SHA, 'physical_page': page,
              'owner': 'zcode', 'facts': facts, 'contexts': {}, 'ledger_rows': [],
              'external_fact_refs': [], 'input_fact_store_sha256': '0' * 64,
              'input_ledger_sha256': '0' * 64}
    path = tmp / 'full-alignment-work-v2' / f'small-{page:04d}.json'
    sha = write(path, packet)
    return packet, path, sha


def make_receipt(packet, role='zcode', *, selected=None, unresolved=None, owner=None,
                 saved_at='2026-10-15T03:00:00+00:00', session='sess_test'):
    receipt = {'schema_version': bom.RECEIPT_SCHEMA,
               'work_packet_sha256': None,  # bound by caller
               'source_sha256': packet['source_sha256'], 'physical_page': packet['physical_page'],
               'catalog': packet['catalog'],
               'identity': {'role': owner or role, 'session_id': session, 'model': f'model::{role}'},
               'source_evidence': [{'bbox': [0, 0, 1, 1], 'observation': 'verify row'}],
               'groups': [], 'selected_fact_indices': selected or [],
               'source_unresolved_fact_indices': unresolved or [],
               'all_input_facts_accounted_for': True, 'owner_work_complete': True,
               'independent_final_review_complete': False,
               'original_alternatives_retained': True, 'saved_at': saved_at, 'work_sha256': ''}
    return receipt


BASELINE_MEMBER = 'all-catalogues-980-pages.json'


def make_tree(tmp, pages):
    """pages: list of (page, owner, receipts{role: receipt}) with packet+receipts written."""
    manifest_pages = []
    if not pages:
        packet, path, sha = make_packet(tmp, 7)
        receipts = {}
        pages = [(7, 'zcode', receipts)]
        write(tmp / 'reviews' / 'placeholder', 'x') if False else None
    for page, owner, receipts in pages:
        packet, path, sha = make_packet(tmp, page)
        manifest_pages.append({'path': path.name, 'sha256': sha, 'catalog': 'small',
                               'physical_page': page, 'owner': owner, 'facts': len(packet['facts']),
                               'ledger_rows': 0, 'residual_model_parameters': 0, 'open_ledger_rows': 0,
                               'source_sha256': SOURCE_SHA})
        for role, receipt in receipts.items():
            receipt['work_packet_sha256'] = sha
            receipt['selected_fact_indices'] = list(range(len(packet['facts'])))
            receipt['work_sha256'] = case_sha256({k: v for k, v in receipt.items() if k != 'work_sha256'})
            if role == 'zcode':
                p = tmp / 'reviews/zcode/full-work' / f'small-{page:04d}-page-work.json'
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(receipt))
            elif role == 'codex':
                p = tmp / 'reviews/codex/full-work' / f'small-{page:04d}.json'
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(receipt))
            else:
                p = tmp / 'reviews/minimax/full-work' / f'small-{page:04d}' / 'result.json'
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(receipt))
    manifest = {'schema_version': 'full-alignment-work/2', 'phase': 'disjoint-owner-work',
                'owners': {'small': 'zcode'}, 'pages': manifest_pages,
                'unlocated_work_packets': [], 'physical_pages': [p['physical_page'] for p in manifest_pages]}
    write(tmp / 'full-alignment-work-v2' / 'manifest.json', manifest)
    (tmp / 'input' / 'oleg').mkdir(parents=True, exist_ok=True)
    return manifest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Synthetic task tree + a one-page baseline zip + cwd switch."""
    monkeypatch.chdir(tmp_path)
    make_tree(tmp_path, [(7, 'zcode', {'zcode': make_receipt(make_packet(tmp_path, 7)[0])})])
    baseline = {'catalogs': [{'id': 'small', 'pages': [
        {'catalog': 'small', 'pdf_page': 7, 'source_sha256': SOURCE_SHA, 'status': 'accepted',
         'columns': [{'id': 'c1', 'label': 'П'}], 'rows': [],
         'content': {'title': 'Т', 'text_blocks': [], 'tables': [], 'figures': [],
                     'source_notes': [], 'uncertainties': []},
         'content_canonical_sha256': 'x',
         'texts': [], 'drawings': [], 'source_notes': []}]},
        {'id': 'opn', 'pages': []}]}
    (tmp_path / 'examples/catalogs/all-pages-2026-10-14T172333Z').mkdir(parents=True)
    import zipfile
    zip_path = tmp_path / 'examples/catalogs/all-pages-2026-10-14T172333Z/all-catalogues-980-pages.zip'
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.writestr(BASELINE_MEMBER, json.dumps(baseline))
    # The exporter pins the real baseline SHA; tests point the pin at the
    # synthetic archive without weakening the production check.
    monkeypatch.setattr(bom, 'BASELINE_SHA256', sha_bytes(zip_path.read_bytes()))
    (tmp_path / 'input').mkdir(exist_ok=True)
    (tmp_path / 'input' / 'forenergo-our-extraction.zip').write_bytes(b'PK\x05\x06' + b'\x00' * 18)
    return tmp_path


def run_export(env, out='out', **kwargs):
    return bom.export(env, env / 'full-alignment-work-v2' / '..' / 'full-alignment-work-v2' / '..'
                      if False else env, env / 'out', **kwargs)


def test_happy_export_lossless(env):
    packet = json.loads((env / 'full-alignment-work-v2' / 'small-0007.json').read_text())
    receipt_file = env / 'reviews/zcode/full-work/small-0007-page-work.json'
    receipt = json.loads(receipt_file.read_text())
    receipt['selected_fact_indices'] = list(range(len(packet['facts'])))
    receipt['work_sha256'] = case_sha256({k: v for k, v in receipt.items() if k != 'work_sha256'})
    receipt_file.write_text(json.dumps(receipt))
    receipt = bom.export(env, env, env / 'out', allow_partial=True, only_pages={'small-0007.json'})
    assert receipt['pages_with_owner_receipts'] == 1
    import zipfile
    with zipfile.ZipFile(env / 'out' / 'catalogues-unified.zip') as z:
        data = json.loads(z.read('catalogue.json'))
    page = data['catalogs'][0]['pages'][0]
    rec = page['owner_reconciliation']
    packet = json.loads((env / 'full-alignment-work-v2' / 'small-0007.json').read_text())
    assert rec['typed_facts'] == packet['facts']  # typed lossless roundtrip
    assert all(f['side'] == 'oleg' for f in rec['typed_facts'] if str(f['fact_id']).startswith('L-'))
    # Oleg-only facts are not lost: the oleg-side empty/dash fact is embedded
    assert any(f['side'] == 'oleg' and f['value'] == '–' for f in rec['typed_facts'])
    # Rejected/unselected values do not touch canonical cells
    assert page['content']['tables'] == [] and 'reconciliation' not in page
    assert data['owner_reconciliation_summary']['canonical_cells_changed'] == 0


def test_invalid_owner_rejected(env):
    # A minimax receipt on a zcode-owned page must not count/validate.
    packet, _, sha = make_packet(env, 8)
    receipt = make_receipt(packet, role='minimax')
    receipt['work_packet_sha256'] = sha
    receipt['work_sha256'] = case_sha256({k: v for k, v in receipt.items() if k != 'work_sha256'})
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
    receipt = make_receipt(packet)
    receipt['work_packet_sha256'] = 'f' * 64
    receipt['work_sha256'] = case_sha256({k: v for k, v in receipt.items() if k != 'work_sha256'})
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


def test_invalid_work_hash_rejected(env):
    packet, _, sha = make_packet(env, 10)
    receipt = make_receipt(packet)
    receipt['work_packet_sha256'] = sha
    receipt['work_sha256'] = 'e' * 64
    p = env / 'reviews/zcode/full-work/small-0010-page-work.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt))
    manifest = json.loads((env / 'full-alignment-work-v2' / 'manifest.json').read_text())
    manifest['pages'].append({'path': 'small-0010.json', 'sha256': sha, 'catalog': 'small',
                              'physical_page': 10, 'owner': 'zcode', 'facts': len(packet['facts']),
                              'ledger_rows': 0, 'residual_model_parameters': 0, 'open_ledger_rows': 0,
                              'source_sha256': SOURCE_SHA})
    (env / 'full-alignment-work-v2' / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='work_sha256'):
        bom.export(env, env, env / 'out10', allow_partial=True)


def test_partial_coverage_rejected_and_reported(env):
    # Fact index 3 is accounted neither as selected nor unresolved.
    packet, _, sha = make_packet(env, 11)
    receipt = make_receipt(packet, selected=[0, 1])
    receipt['work_packet_sha256'] = sha
    receipt['work_sha256'] = case_sha256({k: v for k, v in receipt.items() if k != 'work_sha256'})
    p = env / 'reviews/zcode/full-work/small-0011-page-work.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt))
    manifest = json.loads((env / 'full-alignment-work-v2' / 'manifest.json').read_text())
    manifest['pages'].append({'path': 'small-0011.json', 'sha256': sha, 'catalog': 'small',
                              'physical_page': 11, 'owner': 'zcode', 'facts': len(packet['facts']),
                              'ledger_rows': 0, 'residual_model_parameters': 0, 'open_ledger_rows': 0,
                              'source_sha256': SOURCE_SHA})
    (env / 'full-alignment-work-v2' / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='coverage is partial'):
        bom.export(env, env, env / 'out11', allow_partial=True)


def test_transfer_binds_new_packet_and_owner(env):
    # armature-style transfer: original minimax packet, new codex packet+receipt.
    packet_new, _, sha_new = make_packet(env, 12)
    (env / 'ownership-transfers').mkdir(parents=True, exist_ok=True)
    transfer = {'transfers': [{'catalog': 'small', 'physical_page': 12,
                               'original_packet': 'full-alignment-work-v2/small-0012.json',
                               'original_packet_sha256': sha_new,
                               'packet': 'ownership-transfers/small-0012-codex.json',
                               'packet_sha256': sha_new,
                               'previous_owner': 'minimax', 'owner': 'codex',
                               'fact_store_unchanged': True,
                               'previous_execution': 'runtime/x'}]}
    (env / 'ownership-transfers' / 'index.json').write_text(json.dumps(transfer))
    (env / 'ownership-transfers' / 'small-0012-codex.json').write_bytes(
        (env / 'full-alignment-work-v2' / 'small-0012.json').read_bytes())
    receipt = make_receipt(packet_new, role='codex')
    receipt['work_packet_sha256'] = sha_new
    receipt['selected_fact_indices'] = list(range(len(packet_new['facts'])))
    receipt['work_sha256'] = case_sha256({k: v for k, v in receipt.items() if k != 'work_sha256'})
    p = env / 'reviews/codex/full-work/small-0012.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt))
    manifest = json.loads((env / 'full-alignment-work-v2' / 'manifest.json').read_text())
    manifest['pages'].append({'path': 'small-0012.json', 'sha256': sha_new, 'catalog': 'small',
                              'physical_page': 12, 'owner': 'minimax', 'facts': len(packet_new['facts']),
                              'ledger_rows': 0, 'residual_model_parameters': 0, 'open_ledger_rows': 0,
                              'source_sha256': SOURCE_SHA})
    (env / 'full-alignment-work-v2' / 'manifest.json').write_text(json.dumps(manifest))
    bom.export(env, env, env / 'out12', allow_partial=True)
    # Tampered transfer packet must fail.
    (env / 'ownership-transfers' / 'small-0012-codex.json').write_text('{"facts": []}')
    with pytest.raises(ValueError, match='Transfer packet changed'):
        bom.export(env, env, env / 'out12b', allow_partial=True)


def test_revision_latest_saved_at_wins(env):
    # An older base receipt plus a newer sem2 revision: the newest must be used.
    packet, path, sha = make_packet(env, 7)
    base = make_receipt(packet, saved_at='2026-10-15T01:00:00+00:00')
    base['work_packet_sha256'] = sha
    base['selected_fact_indices'] = list(range(len(packet['facts'])))
    base['work_sha256'] = case_sha256({k: v for k, v in base.items() if k != 'work_sha256'})
    newer = make_receipt(packet, saved_at='2026-10-15T02:00:00+00:00')
    newer['work_packet_sha256'] = sha
    newer['selected_fact_indices'] = list(range(len(packet['facts'])))
    newer['work_sha256'] = case_sha256({k: v for k, v in newer.items() if k != 'work_sha256'})
    (env / 'reviews/zcode/full-work/small-0007-page-work.json').write_text(json.dumps(base))
    (env / 'reviews/zcode/full-work/small-0007-page-work-sem2.json').write_text(json.dumps(newer))
    receipt = bom.export(env, env, env / 'out13', allow_partial=True, only_pages={'small-0007.json'})
    import zipfile
    with zipfile.ZipFile(env / 'out13' / 'catalogues-unified.zip') as z:
        data = json.loads(z.read('catalogue.json'))
    roles = data['catalogs'][0]['pages'][0]['owner_reconciliation']['receipts']
    assert roles['zcode']['saved_at'] == newer['saved_at']


def test_final_requires_full_coverage(env):
    with pytest.raises(ValueError, match='Final delivery refused'):
        bom.export(env, env, env / 'out14')


def test_excel_reopen_roundtrip(env):
    receipt = bom.export(env, env, env / 'out15', allow_partial=True, only_pages={'small-0007.json'})
    assert receipt['excel_rows_roundtrip_checked'] >= 1
    assert receipt['archive_crc'] == 'passed'
    assert receipt['manifest_all_members_verified'] is True


@pytest.mark.slow
def test_real_canary_on_saved_pages():
    """Real canary over already-saved task pages; explicitly partial, no models."""
    root = Path(__file__).resolve().parents[1]
    task = root / '.tmp/oleg-consensus-20261014'
    manifest_path = task / 'full-alignment-work-v2' / 'manifest.json'
    if not manifest_path.exists():
        pytest.skip('real task tree not present')
    manifest = json.loads(manifest_path.read_text())
    saved = []
    reviews = task / 'reviews'
    for entry in manifest['pages']:
        if entry['owner'] != 'zcode':
            continue
        stem = f"{entry['catalog']}-{entry['physical_page']:04d}"
        for suffix in ('-page-work-sem2.json', '-page-work-revised.json', '-page-work.json'):
            if (reviews / 'zcode' / 'full-work' / f'{stem}{suffix}').exists():
                saved.append(entry['path'])
                break
    if not saved:
        pytest.skip('no saved zcode pages')
    subset = sorted(saved)[:3]
    out = task / 'owner-export' / 'canary'
    if out.exists():
        import shutil
        shutil.rmtree(out)
    receipt = bom.export(root, task, out, allow_partial=True, only_pages=set(subset))
    assert receipt['pages_with_owner_receipts'] == len(subset)
    assert receipt['final_delivery'] is False  # canary is never the final ZIP
    assert receipt['model_calls'] == 0
    assert receipt['owner_typed_facts_roundtrip'] > 0
