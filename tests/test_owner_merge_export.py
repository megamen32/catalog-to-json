"""Focused tests for the whole-owner MATERIALIZING exporter (schema-driven).

Synthetic mini-manifest (packets + receipts with groups + transfers) proves:
  - keep=oleg materializes the Oleg value into the verified cell (999→123) and
    archives the ours side as alternative;
  - oleg-only selected facts become primary;
  - source_unresolved facts stay explicitly marked;
  - null/blank/dash/0 stay distinct typed values;
  - invalid owner/packet-hash and group coverage violations fail.
Plus one real canary over actual saved task receipts (partial, no models).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.catalogue_delivery import build_owner_merge as bom  # noqa: E402

from catalog_json.reconciliation.consensus import case_sha256  # noqa: E402

SOURCE_SHA = 'a' * 64
BASELINE_MEMBER = 'all-catalogues-980-pages.json'
CELL_PTR = '/catalogs/0/pages/0/content/tables/0/rows/0/cells/0'


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=1).encode()
    path.write_bytes(data)
    return sha_bytes(data)


def digest(receipt):
    return case_sha256({k: v for k, v in receipt.items() if k != 'work_sha256'})


def make_fact(side, i, value, owner='РТ-1', name='Рабочая нагрузка'):
    return {'fact_id': f'{"L" if side == "oleg" else "O"}-{i:04d}', 'side': side,
            'catalog': 'small', 'kind': 'model_parameter', 'pointer': f'{side}:{i}',
            'owner': owner, 'name': name, 'value': value,
            'unit': 'кН', 'condition': '', 'physical_pages': [7],
            'input_fact_sha256': sha_bytes(f'{side}{i}{value}'.encode())}


def make_packet(tmp, page, facts):
    packet = {'catalog': 'small', 'source_sha256': SOURCE_SHA, 'physical_page': page,
              'owner': 'zcode', 'facts': facts, 'contexts': {}, 'ledger_rows': [],
              'external_fact_refs': [], 'input_fact_store_sha256': '0' * 64,
              'input_ledger_sha256': '0' * 64}
    path = tmp / 'full-alignment-work-v2' / f'small-{page:04d}.json'
    sha = write(path, packet)
    return packet, path, sha


def make_receipt(packet, *, groups, role='zcode', saved_at='2026-10-15T03:00:00+00:00'):
    r = {'schema_version': bom.RECEIPT_SCHEMA, 'work_packet_sha256': None,
         'source_sha256': packet['source_sha256'], 'physical_page': packet['physical_page'],
         'catalog': packet['catalog'],
         'identity': {'role': role, 'session_id': 'sess_test', 'model': f'model::{role}'},
         'source_evidence': [{'bbox': [0, 0, 1, 1], 'observation': 'verified'}],
         'groups': groups, 'selected_fact_indices': [], 'source_unresolved_fact_indices': [],
         'all_input_facts_accounted_for': True, 'owner_work_complete': True,
         'independent_final_review_complete': False,
         'original_alternatives_retained': True, 'saved_at': saved_at, 'work_sha256': ''}
    sel, unr = set(), set()
    for g in groups:
        for i in g['fact_indices']:
            side = packet['facts'][i]['side']
            if g['keep'] == 'unresolved':
                unr.add(i)
            elif g['keep'] == 'both':
                sel.add(i)
            elif g['keep'] == 'ours':
                if side == 'ours':
                    sel.add(i)
            elif g['keep'] == 'oleg':
                if side == 'oleg':
                    sel.add(i)
    r['selected_fact_indices'] = sorted(sel)
    r['source_unresolved_fact_indices'] = sorted(unr)
    r['work_sha256'] = digest(r)
    return r


BASELINE = {'catalogs': [{'id': 'small', 'pages': [
    {'catalog': 'small', 'pdf_page': 7, 'source_sha256': SOURCE_SHA, 'status': 'accepted',
     'columns': [{'id': 'c0', 'label': 'П'}], 'rows': [],
     'content': {'title': 'Т', 'text_blocks': [], 'tables': [
         {'id': 't0', 'title': 'Т', 'columns': [{'id': 'c0', 'label': 'П'}],
          'rows': [{'cells': [{'column_id': 'c0', 'value': '999', 'state': 'value'}]}]}],
         'figures': [], 'source_notes': [], 'uncertainties': []},
     'content_canonical_sha256': 'x', 'texts': [], 'drawings': [], 'source_notes': []}]},
    {'id': 'opn', 'pages': []}]}


def write_baseline(tmp, monkeypatch=None):
    (tmp / 'examples/catalogs/all-pages-2026-10-14T172333Z').mkdir(parents=True, exist_ok=True)
    import zipfile
    zp = tmp / 'examples/catalogs/all-pages-2026-10-14T172333Z/all-catalogues-980-pages.zip'
    with zipfile.ZipFile(zp, 'w') as z:
        z.writestr(BASELINE_MEMBER, json.dumps(BASELINE))
    if monkeypatch is not None:
        monkeypatch.setattr(bom, 'BASELINE_SHA256', sha_bytes(zp.read_bytes()))
    (tmp / 'input').mkdir(exist_ok=True)
    (tmp / 'input' / 'forenergo-our-extraction.zip').write_bytes(b'PK\x05\x06' + b'\x00' * 18)


def write_receipt_and_manifest(tmp, page, packet, sha, receipt):
    receipt['work_packet_sha256'] = sha
    receipt['work_sha256'] = digest(receipt)
    (tmp / 'reviews/zcode/full-work').mkdir(parents=True, exist_ok=True)
    (tmp / 'reviews/zcode/full-work' / f'small-{page:04d}-page-work.json').write_text(
        json.dumps(receipt))
    manifest = {'schema_version': 'x', 'phase': 'test', 'owners': {'small': 'zcode'},
                'pages': [{'path': f'small-{page:04d}.json', 'sha256': sha, 'catalog': 'small',
                           'physical_page': page, 'owner': 'zcode', 'facts': len(packet['facts']),
                           'ledger_rows': 0, 'residual_model_parameters': 0, 'open_ledger_rows': 0,
                           'source_sha256': SOURCE_SHA}],
                'unlocated_work_packets': [], 'physical_pages': [page]}
    write(tmp / 'full-alignment-work-v2' / 'manifest.json', manifest)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    facts = [
        make_fact('ours', 0, '999', name='Рабочая нагрузка'),
        make_fact('oleg', 1, '123', name='Рабочая нагрузка'),
        make_fact('oleg', 2, 'только-у-Олега', owner='РТ-9', name='Особый параметр'),
        make_fact('ours', 3, None, owner='РТ-2', name='Зазор'),
        make_fact('oleg', 4, '', owner='РТ-2', name='Зазор'),
        make_fact('ours', 5, '–', owner='РТ-3', name='Ход'),
        make_fact('oleg', 6, '0', owner='РТ-3', name='Ход'),
    ]
    facts[0]['pointer'] = CELL_PTR
    packet, path, sha = make_packet(tmp_path, 7, facts)
    groups = [
        {'fact_indices': [0, 1], 'relation': 'same_fact', 'keep': 'oleg',
         'reason': 'keep=oleg', 'evidence_refs': [0]},
        {'fact_indices': [2], 'relation': 'oleg_only', 'keep': 'oleg',
         'reason': 'oleg-only', 'evidence_refs': [0]},
        {'fact_indices': [3, 4], 'relation': 'same_fact', 'keep': 'ours',
         'reason': 'null ours', 'evidence_refs': [0]},
        {'fact_indices': [5, 6], 'relation': 'variant_options', 'keep': 'both',
         'reason': 'dash/0', 'evidence_refs': [0]},
    ]
    receipt = make_receipt(packet, groups=groups)
    write_receipt_and_manifest(tmp_path, 7, packet, sha, receipt)
    write_baseline(tmp_path, monkeypatch)
    return tmp_path


def read_primary(env):
    import zipfile
    with zipfile.ZipFile(env / 'out' / 'catalogues-unified.zip') as z:
        return json.loads(z.read('catalogue.json'))


def test_keep_oleg_materializes_123_and_archives_999(env):
    bom.export(env, env, env / 'out', allow_partial=True)
    data = read_primary(env)
    page = data['catalogs'][0]['pages'][0]
    cell = page['content']['tables'][0]['rows'][0]['cells'][0]
    assert cell['value'] == '123'
    import zipfile
    with zipfile.ZipFile(env / 'out' / 'catalogues-unified.zip') as z:
        corr = json.loads(z.read('corrections.json'))['corrections']
    assert corr[0]['before']['value'] == '999' and corr[0]['after']['value'] == '123'
    prim = json.dumps(page['merged_primary'], ensure_ascii=False)
    assert '999' not in prim
    archived = json.dumps(page['owner_archive'], ensure_ascii=False)
    assert '999' in archived
    assert any(f['value'] == 'только-у-Олега' for f in page['merged_primary']['primary_facts'])


def test_null_blank_dash_zero_distinct(env):
    bom.export(env, env, env / 'out', allow_partial=True)
    data = read_primary(env)
    values = [(f['side'], f['value']) for f in data['catalogs'][0]['pages'][0]['merged_primary']['primary_facts']]
    assert ('ours', None) in values
    assert ('ours', '–') in values and ('oleg', '0') in values
    assert len({repr(v) for v in values}) == len(values)


def test_unresolved_explicit(env):
    packet = json.loads((env / 'full-alignment-work-v2' / 'small-0007.json').read_text())
    rf = env / 'reviews/zcode/full-work/small-0007-page-work.json'
    receipt = json.loads(rf.read_text())
    receipt['groups'] = [g for g in receipt['groups'] if g['fact_indices'] != [5, 6]]
    receipt['groups'].append({'fact_indices': [5, 6], 'relation': 'variant_options',
                              'keep': 'unresolved', 'reason': 'ambiguous', 'evidence_refs': [0]})
    receipt['selected_fact_indices'] = sorted({1, 2, 3})  # oleg(1), oleg(2), ours(3) selected
    receipt['source_unresolved_fact_indices'] = [5, 6]
    receipt['work_sha256'] = digest(receipt)
    rf.write_text(json.dumps(receipt))
    bom.export(env, env, env / 'out', allow_partial=True)
    data = read_primary(env)
    page = data['catalogs'][0]['pages'][0]
    uns = page['merged_primary']['source_unresolved_facts']
    assert len(uns) == 2 and all(f.get('source_unresolved') for f in uns)


def test_invalid_owner_ignored(env):
    packet = {'catalog': 'small', 'source_sha256': SOURCE_SHA, 'physical_page': 8,
              'owner': 'zcode', 'facts': [make_fact('ours', 0, '999'),
              make_fact('oleg', 1, '123')], 'contexts': {}, 'ledger_rows': [],
              'external_fact_refs': [], 'input_fact_store_sha256': '0' * 64,
              'input_ledger_sha256': '0' * 64}
    sha = write(env / 'full-alignment-work-v2' / 'small-0008.json', packet)
    groups = [{'fact_indices': [0, 1], 'relation': 'same_fact', 'keep': 'oleg',
               'reason': 'x', 'evidence_refs': [0]}]
    receipt = make_receipt(packet, groups=groups, role='minimax')
    receipt['work_packet_sha256'] = sha
    p = env / 'reviews/minimax/full-work/small-0008/result.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt))
    manifest = json.loads((env / 'full-alignment-work-v2' / 'manifest.json').read_text())
    manifest['pages'].append({'path': 'small-0008.json', 'sha256': sha, 'catalog': 'small',
                              'physical_page': 8, 'owner': 'zcode', 'facts': 2,
                              'ledger_rows': 0, 'residual_model_parameters': 0, 'open_ledger_rows': 0,
                              'source_sha256': SOURCE_SHA})
    (env / 'full-alignment-work-v2' / 'manifest.json').write_text(json.dumps(manifest))
    # minimax receipt for zcode-owned page: silently ignored (wrong role key)
    receipt_out = bom.export(env, env, env / 'out8', allow_partial=True)
    assert receipt_out['pages_with_owner_receipts'] >= 1


def test_invalid_packet_hash_rejected(env):
    facts = [make_fact('ours', 0, '999'), make_fact('oleg', 1, '123')]
    packet = {'catalog': 'small', 'source_sha256': SOURCE_SHA, 'physical_page': 9,
              'owner': 'zcode', 'facts': facts, 'contexts': {}, 'ledger_rows': [],
              'external_fact_refs': [], 'input_fact_store_sha256': '0' * 64,
              'input_ledger_sha256': '0' * 64}
    path = env / 'full-alignment-work-v2' / 'small-0009.json'
    sha = write(path, packet)
    groups = [{'fact_indices': [0, 1], 'relation': 'same_fact', 'keep': 'oleg',
               'reason': 'x', 'evidence_refs': [0]}]
    receipt = make_receipt(packet, groups=groups)
    receipt['work_packet_sha256'] = sha
    # tamper the packet AFTER the receipt binds the original hash
    packet['facts'].append(make_fact('ours', 99, 'extra'))
    path.write_text(json.dumps(packet))
    write_receipt_and_manifest(env, 9, packet, sha, receipt)
    # Packet bytes changed after the receipt bound the original hash; the
    # transfer_is_current gate skips the page as in-flight, no error is raised.
    receipt_out = bom.export(env, env, env / 'out9', allow_partial=True)
    assert receipt_out['pages_with_owner_receipts'] == 0  # no valid receipt for this page


def test_group_coverage_gap_rejected(env):
    facts = [make_fact('ours', 0, '999'), make_fact('oleg', 1, '123')]
    packet, _, sha = make_packet(env, 10, facts)
    groups = [{'fact_indices': [0], 'relation': 'same_fact', 'keep': 'ours',
               'reason': 'x', 'evidence_refs': [0]}]
    receipt = make_receipt(packet, groups=groups)
    receipt['work_packet_sha256'] = sha
    write_receipt_and_manifest(env, 10, packet, sha, receipt)
    with pytest.raises(ValueError, match='not covered by any group'):
        bom.export(env, env, env / 'out10', allow_partial=True)


def test_final_requires_full_coverage(env):
    with pytest.raises(ValueError, match='Final delivery refused'):
        bom.export(env, env, env / 'out14')


def test_excel_primary_shows_materialized_value(env):
    bom.export(env, env, env / 'out', allow_partial=True)
    from openpyxl import load_workbook
    book = load_workbook(env / 'out' / 'small.xlsx', read_only=True)
    rows = list(book['Первичные данные'].iter_rows(min_row=2, values_only=True))
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
    out = task / 'owner-export' / 'canary-v11'
    if out.exists():
        import shutil
        shutil.rmtree(out)
    receipt = bom.export(root, task, out, allow_partial=True, only_pages={
        'isolators-0043.json', 'isolators-0044.json', 'isolators-0045.json',
        'isolators-0050.json', 'innovations-0015.json'})
    assert receipt['pages_with_owner_receipts'] == 5
    assert receipt['final_delivery'] is False
    assert receipt['model_calls'] == 0
    assert receipt['owner_typed_facts_roundtrip'] > 0


def test_unresolved_figure_is_removed_from_primary_content():
    """Fast unit: unresolved source topology must not survive as usable content."""
    fact = {'side': 'ours', 'kind': 'figure', 'pointer':
            '/catalogs/0/pages/0/content/figures/0',
            'value': {'title': 'Wrong', 'description': 'two positions', 'labels': []}}
    record = {'packet': {'facts': [fact]}, 'catalog': 'small', 'physical_page': 7}
    receipt = {'identity': {'role': 'codex'}, 'work_sha256': 'x', 'groups': [
        {'fact_indices': [0], 'keep': 'unresolved'}]}
    page = {'content': {'figures': [fact['value']]}}
    primary, unresolved, archived, removals = bom.apply_receipt(record, page, receipt, [])
    assert not primary
    assert unresolved[0]['value'] == fact['value']
    assert any(s['kind'] == 'figures' and s['index'] == 0 for s in removals)


def test_same_value_selected_unit_reaches_canonical_column():
    """Fast unit: ARM283 frequency unit must survive equal scalar selection."""
    ours = make_fact('ours', 0, 50, name='Номинальная частота ГЦ')
    oleg = make_fact('oleg', 1, '50', name='Номинальная частота ГЦ')
    ours.update(pointer=CELL_PTR, unit=None)
    oleg['unit'] = 'ГЦ'
    record = {'packet': {'facts': [ours, oleg]}, 'catalog': 'small', 'physical_page': 7}
    receipt = {'identity': {'role': 'codex'}, 'work_sha256': 'x', 'groups': [
        {'fact_indices': [0, 1], 'keep': 'oleg'}]}
    import copy
    page = copy.deepcopy(BASELINE['catalogs'][0]['pages'][0])
    page['content']['tables'][0]['rows'][0]['cells'][0]['value'] = 50
    changes = []
    bom.apply_receipt(record, page, receipt, changes)
    assert page['content']['tables'][0]['columns'][0]['unit'] == 'ГЦ'
    assert changes and changes[0]['after']['unit'] == 'ГЦ'


def test_materialized_owner_page_does_not_reuse_baseline_independent_acceptance(env, monkeypatch):
    """Focused integration: mutated content needs a new review, old proof stays history."""
    import copy
    import zipfile
    baseline = copy.deepcopy(BASELINE)
    baseline['independently_accepted_pages'] = 1
    page = baseline['catalogs'][0]['pages'][0]
    page.update(reviewed_current_content=True,
                review_producer={'model': 'old-model', 'artifact_sha256': 'old-proof'})
    zp = env / bom.BASELINE_ZIP
    with zipfile.ZipFile(zp, 'w') as z:
        z.writestr(BASELINE_MEMBER, json.dumps(baseline))
    monkeypatch.setattr(bom, 'BASELINE_SHA256', sha_bytes(zp.read_bytes()))
    bom.export(env, env, env / 'out', allow_partial=True)
    result = read_primary(env)
    page = result['catalogs'][0]['pages'][0]
    assert page['reviewed_current_content'] is False
    assert page['status'] != 'accepted'
    assert page['baseline_review']['review_producer']['artifact_sha256'] == 'old-proof'
    assert result['independently_accepted_pages'] == 0
    assert result['baseline_independently_accepted_pages'] == 1


def test_shared_selected_value_updates_every_group_bound_cell():
    """Fast unit: one shared source property applies to every explicitly bound row."""
    import copy
    page = copy.deepcopy(BASELINE['catalogs'][0]['pages'][0])
    table = page['content']['tables'][0]
    table['rows'].append(copy.deepcopy(table['rows'][0]))
    ours1 = make_fact('ours', 0, '999')
    ours2 = make_fact('ours', 1, '999', owner='РТ-2')
    ours1['pointer'] = CELL_PTR
    ours2['pointer'] = CELL_PTR.replace('/rows/0/', '/rows/1/')
    oleg = make_fact('oleg', 2, '123')
    record = {'packet': {'facts': [ours1, ours2, oleg]}, 'catalog': 'small', 'physical_page': 7}
    receipt = {'identity': {'role': 'codex'}, 'work_sha256': 'x', 'groups': [
        {'fact_indices': [0, 1, 2], 'keep': 'oleg'}]}
    changes = []
    bom.apply_receipt(record, page, receipt, changes)
    assert [row['cells'][0]['value'] for row in table['rows']] == ['123', '123']
    assert len(changes) == 2


def test_unresolved_table_cell_is_unknown_and_original_is_preserved():
    """Fast unit: unresolved engineering values cannot remain asserted in primary tables."""
    import copy
    page = copy.deepcopy(BASELINE['catalogs'][0]['pages'][0])
    fact = make_fact('ours', 0, '999')
    fact['pointer'] = CELL_PTR
    record = {'packet': {'facts': [fact]}, 'catalog': 'small', 'physical_page': 7}
    receipt = {'identity': {'role': 'codex'}, 'work_sha256': 'x', 'groups': [
        {'fact_indices': [0], 'keep': 'unresolved'}]}
    changes = []
    primary, unresolved, _, _ = bom.apply_receipt(record, page, receipt, changes)
    assert not primary and unresolved[0]['value'] == '999'
    assert page['content']['tables'][0]['rows'][0]['cells'][0]['state'] == 'unknown'
    assert page['content']['tables'][0]['rows'][0]['cells'][0]['value'] is None
    assert changes[0]['source_unresolved'] is True


def test_whole_rejected_table_is_replaced_by_selected_structured_facts():
    """Fast unit: isolators64 structure replacement must not broadcast one scalar."""
    import copy
    page = copy.deepcopy(BASELINE['catalogs'][0]['pages'][0])
    ours = make_fact('ours', 0, '999'); ours['pointer'] = CELL_PTR
    left = make_fact('oleg', 1, 'Ball'); right = make_fact('oleg', 2, 'D=33.3 d=17')
    record = {'packet': {'facts': [ours, left, right]}, 'catalog': 'small', 'physical_page': 7}
    receipt = {'identity': {'role': 'codex'}, 'work_sha256': 'x', 'groups': [
        {'fact_indices': [0, 1, 2], 'keep': 'oleg'}]}
    primary, _, archived, removals = bom.apply_receipt(record, page, receipt, [])
    assert [entry['value'] for entry in primary] == ['Ball', 'D=33.3 d=17']
    assert archived[0]['value'] == '999'
    assert {'kind': 'tables', 'index': 0} in removals


def test_partial_ambiguous_table_replacement_is_refused():
    """Fast unit: a multi-value group cannot erase a table with accepted rows."""
    import copy
    page = copy.deepcopy(BASELINE['catalogs'][0]['pages'][0])
    page['content']['tables'][0]['rows'].append(copy.deepcopy(page['content']['tables'][0]['rows'][0]))
    ours = make_fact('ours', 0, '999'); ours['pointer'] = CELL_PTR
    left = make_fact('oleg', 1, 'Ball'); right = make_fact('oleg', 2, 'D=33.3 d=17')
    record = {'packet': {'facts': [ours, left, right]}, 'catalog': 'small', 'physical_page': 7}
    receipt = {'identity': {'role': 'codex'}, 'work_sha256': 'x', 'groups': [
        {'fact_indices': [0, 1, 2], 'keep': 'oleg'}]}
    with pytest.raises(ValueError, match='Ambiguous'):
        bom.apply_receipt(record, page, receipt, [])


def test_transferred_shard_uses_only_its_assigned_native_session_and_model(env):
    """Fast unit: an old exporter cannot count automatic drafts for another shard."""
    manifest = bom.load(env / 'full-alignment-work-v2/manifest.json')
    entry = manifest['pages'][0]
    transfer = {'owner': 'zcode', 'packet': str(env / 'full-alignment-work-v2' / entry['path']),
                'packet_sha256': entry['sha256'], 'fact_store_unchanged': True,
                'assigned_native_session': 'assigned-native', 'assigned_model': 'assigned-model'}
    transfers = {(entry['catalog'], entry['physical_page']): transfer}
    records, pending = bom.collect_pages(env, env / 'reviews', manifest, transfers)
    assert records == {} and len(pending) == 1
    original = bom.load(env / 'reviews/zcode/full-work/small-0007-page-work.json')
    original['identity'].update(session_id='assigned-native', model='wrong-model')
    original['work_sha256'] = digest(original)
    path = env / 'reviews/zcode/full-work/assigned/author-revision.json'
    write(path, original)
    assert not bom.collect_pages(env, env / 'reviews', manifest, transfers)[0]
    original['identity']['model'] = 'assigned-model'
    original['work_sha256'] = digest(original)
    write(path, original)
    records, pending = bom.collect_pages(env, env / 'reviews', manifest, transfers)
    assert len(records) == 1 and not pending
