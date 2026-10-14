"""Fast unit regressions for actual loss modes; no provider/model calls."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from catalog_json.reconciliation.formats import (
    FormatError, RawDocument, SOURCE_CATALOGS, TABLES, exact_json_equal,
    load_oleg_export, load_our_snapshot, parse_json, pointer, restore_raw,
    verify_payload_manifest,
)

SHA = next(key for key, value in SOURCE_CATALOGS.items() if value == 'small')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def seal(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['files'] = [
        {'path': str(p.relative_to(root)), 'bytes': p.stat().st_size,
         'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'manifest.json'
    ]
    write_json(root / 'manifest.json', manifest)


@pytest.fixture
def oleg(tmp_path):
    root = tmp_path / 'oleg'
    values = [None, '', False, 0, 1.0, [], {}, '001', '–', '=SUM(A1)', 'М12', 'M12']
    chars = [dict(name='Н / label', **{'raw_value': value}, unit=None,
                  header_path=[{'raw_text': 'Outer', 'condition': ''}, {'raw_text': 'Leaf', 'unit': None}],
                  row_evidence=[{'page': 1, 'region': [0, 0, 1, 1]}]) for value in values]
    chars.append({'name': 'missing', 'header_path': None})
    groups = [{'id': 'native-g', 'title': 'same SKU is not group identity', 'characteristics': [], 'extra': None},
              {'id': 'null-group', 'characteristics': None, 'extra': []}]
    models = [{'designation': 'REPEATED', 'product_id': 'native-g', 'characteristics': chars, 'unknown': {'n': -0.0}},
              {'designation': 'REPEATED', 'product_id': 'native-g', 'characteristics': None},
              {'designation': 'REPEATED', 'product_id': 'native-g'}]
    native = {'schema_version': '2.0-data', 'source': 'inert historical path', 'source_sha256': SHA,
              'products': groups, 'models': models, 'coverage': [{'page': 1}], 'context_pages': [],
              'leading_section': None, 'trailing_section': None, 'artifacts': ['old/path'], 'uncertainties': []}
    draft = root / 'drafts/W-one.json'
    write_json(draft, native)
    rows = {table: [] for table in TABLES}
    for index, group in enumerate(groups):
        rows['product_groups'].append({'id': f'G-{index}', 'source_id': 'S', 'window_id': 'W-one',
                                       'native_index': index, 'raw': {k: v for k, v in group.items() if k != 'characteristics'}})
    for index, model in enumerate(models):
        rows['products'].append({'id': f'P-{index}', 'source_id': 'S', 'window_id': 'W-one', 'group_id': 'G-0',
                                'native_index': index, 'raw': {k: v for k, v in model.items() if k != 'characteristics'}})
    types = Counter()
    from catalog_json.reconciliation.formats import json_type
    for index, char in enumerate(chars):
        kind = json_type(char['raw_value']) if 'raw_value' in char else 'missing'
        types[kind] += 1
        rows['characteristics'].append({'id': f'C-{index}', 'source_id': 'S', 'window_id': 'W-one',
                                       'group_id': 'G-0', 'product_id': 'P-0', 'characteristic_index': index,
                                       'raw_value_type': kind, 'raw': char})
    for table, items in rows.items():
        (root / f'{table}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in items))
    counts = {t: len(rs) for t, rs in rows.items()}
    window = {'id': 'W-one', 'window_id': 'W-one', 'source_id': 'S', 'start_page': 1, 'end_page': 1,
              'status': 'native_accepted', 'reused': False, 'draft_path': 'drafts/W-one.json',
              'draft_sha256': hashlib.sha256(draft.read_bytes()).hexdigest(),
              'counts': {t: counts[t] for t in TABLES if t != 'uncertainties'}}
    write_json(root / 'sources.json', {'sources': [{'id': 'S', 'sha256': SHA, 'page_count': 1}]})
    write_json(root / 'coverage.json', {'windows': [window], 'pages': [{'source_id': 'S', 'page': 1, 'window_ids': ['W-one']}],
                                      'window_observations': [{'source_id': 'S', 'window_id': 'W-one',
                                                               'raw': {k: native[k] for k in ('coverage', 'context_pages', 'leading_section', 'trailing_section', 'uncertainties')}}]})
    write_json(root / 'manifest.json', {'record_counts': counts, 'raw_value_types': dict(types), 'files': []})
    seal(root)
    return root, native


def test_exact_json_distinguishes_every_loss_mode():
    assert not exact_json_equal(True, 1)
    assert not exact_json_equal(1, 1.0)
    assert not exact_json_equal(0.0, -0.0)
    assert not exact_json_equal({'a': 1, 'b': None}, {'b': None, 'a': 1})
    assert not exact_json_equal({}, {'value': None})
    assert not exact_json_equal('М12', 'M12')
    assert pointer('a/b', '~', 0) == '/a~1b/~0/0'
    with pytest.raises(FormatError, match='Duplicate JSON'):
        parse_json('{"same":1,"same":2}')
    with pytest.raises(FormatError, match='finite'):
        parse_json('{"n":NaN}')


def test_raw_byte_roundtrip_retains_whitespace_and_numeric_lexemes():
    data = b'{ "a":1.0, "b":-0.0, "empty": null }\n'
    doc = RawDocument('test', data, parse_json(data))
    assert restore_raw(doc) == data
    doc.raw['a'] = 1
    with pytest.raises(FormatError, match='Lossy restoration'):
        restore_raw(doc)


def test_full_split_roundtrip_null_missing_order_and_duplicate_designations(oleg):
    root, native = oleg
    export = load_oleg_export(root)
    restored = export.reconstruct_window('W-one')
    assert exact_json_equal(restored, native)
    assert export.restore_window_bytes('W-one') == (root / 'drafts/W-one.json').read_bytes()
    assert list(restored['models'][0]) == ['designation', 'product_id', 'characteristics', 'unknown']
    assert restored['models'][1]['characteristics'] is None
    assert 'characteristics' not in restored['models'][2]
    metrics = export.inventory()
    assert metrics['native_roundtrip_windows_checked'] == 1
    assert metrics['duplicate_designation_keys'] == 1
    assert metrics['observations_on_duplicate_designation_keys'] == 3
    atoms = list(export.iter_atoms())
    char_atoms = [a for a in atoms if a['kind'] == 'model_characteristic']
    assert char_atoms[-1]['presence'] is False
    assert char_atoms[-1]['raw_value_type'] == 'missing'
    assert char_atoms[0]['presence'] is True and char_atoms[0]['raw_value_type'] == 'null'
    assert char_atoms[0]['header_path'][1]['unit'] is None
    assert char_atoms[10]['raw_value'] == 'М12' and char_atoms[11]['raw_value'] == 'M12'
    assert all(a['provenance']['source_verified'] is False for a in char_atoms)
    assert char_atoms[0]['provenance']['native_pointer'] == '/models/0/characteristics/0'


def test_manifest_detects_mutation_extra_payload_and_escape(oleg):
    root, _ = oleg
    with (root / 'products.jsonl').open('ab') as f:
        f.write(b' ')
    with pytest.raises(FormatError, match='hash/size'):
        verify_payload_manifest(root)
    seal(root)
    (root / 'unlisted').write_text('extra')
    with pytest.raises(FormatError, match='inventory mismatch'):
        verify_payload_manifest(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['files'][0]['path'] = '../escape'
    write_json(root / 'manifest.json', manifest)
    with pytest.raises(FormatError, match='Unsafe payload'):
        verify_payload_manifest(root)


@pytest.mark.parametrize('failure', ['fk', 'type', 'order', 'value', 'index'])
def test_real_split_corruptions_do_not_pass_roundtrip(oleg, failure):
    root, _ = oleg
    path = root / 'characteristics.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if failure == 'fk':
        rows[0]['product_id'] = 'P-missing'
    elif failure == 'type':
        rows[0]['raw_value_type'] = 'string'
    elif failure == 'order':
        rows[0]['raw'] = dict(reversed(list(rows[0]['raw'].items())))
    elif failure == 'value':
        rows[0]['raw']['raw_value'] = ''
        rows[0]['raw_value_type'] = 'string'
    else:
        rows[1]['characteristic_index'] = 0
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    seal(root)
    with pytest.raises(FormatError):
        load_oleg_export(root).inventory()


def test_group_fact_is_not_copied_into_models(oleg):
    root, _ = oleg
    # Add a fact to the native group and split table, without changing any model.
    path = root / 'drafts/W-one.json'
    native = json.loads(path.read_text())
    char = {'name': 'condition', 'raw_value': 'only group', 'condition': None}
    native['products'][0]['characteristics'] = [char]
    write_json(path, native)
    rec = {'id': 'C-group', 'source_id': 'S', 'window_id': 'W-one', 'group_id': 'G-0',
           'characteristic_index': 0, 'raw_value_type': 'string', 'raw': char}
    (root / 'group_characteristics.jsonl').write_text(json.dumps(rec) + '\n')
    coverage = json.loads((root / 'coverage.json').read_text())
    coverage['windows'][0]['draft_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    coverage['windows'][0]['counts']['group_characteristics'] = 1
    write_json(root / 'coverage.json', coverage)
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['record_counts']['group_characteristics'] = 1
    manifest['raw_value_types']['string'] += 1
    write_json(root / 'manifest.json', manifest)
    seal(root)
    export = load_oleg_export(root)
    assert exact_json_equal(export.reconstruct_window('W-one'), native)
    atoms = list(export.iter_atoms())
    grouped = [a for a in atoms if a['kind'] == 'group_characteristic']
    assert len(grouped) == 1 and grouped[0]['model_raw'] is None
    assert not any(a['kind'] == 'model_characteristic' and a['raw_value'] == 'only group' for a in atoms)


def test_our_zip_roundtrip_and_atoms_keep_cell_context(tmp_path):
    content = {'title': 'Table', 'page_context': None, 'printed_page': 'i', 'tables': [
        {'id': 't', 'title': 'Products', 'columns': [{'id': 'a', 'label': 'Name', 'unit': None},
          {'id': 'b', 'label': 'Load', 'unit': 'кН', 'qualifier': 'не менее', 'group': 'Outer'}],
         'rows': [{'cells': [{'column_id': 'a', 'value': '001', 'state': 'value'},
                            {'column_id': 'b', 'value': None, 'state': 'blank'}]}]}],
        'text_blocks': [{'kind': 'paragraph', 'text': 'literal'}],
        'figures': [{'title': 'One', 'description': '5 belongs here', 'labels': ['5', 'А']}],
        'source_notes': [], 'uncertainties': []}
    raw = {'page_count': 1, 'catalogs': [{'id': 'small', 'source': {'sha256': SHA, 'filename': 'small.pdf', 'page_count': 1},
                                       'pages': [{'pdf_page': 1, 'status': 'awaiting_review', 'content': content}]}]}
    data = json.dumps(raw, ensure_ascii=False).encode()
    manifest = {'files': {'all-catalogues-980-pages.json': {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}}
    path = tmp_path / 'our.zip'
    with ZipFile(path, 'w') as zip:
        zip.writestr('all-catalogues-980-pages.json', data)
        zip.writestr('manifest.json', json.dumps(manifest))
    ours = load_our_snapshot(path)
    assert restore_raw(ours.document) == data
    atoms = list(ours.iter_atoms())
    cell = next(a for a in atoms if a['kind'] == 'table_cell' and a['column_index'] == 1)
    assert cell['presence'] is True and cell['raw_value_type'] == 'null'
    assert cell['unit'] == 'кН' and cell['qualifier'] == 'не менее'
    assert cell['row_values'] == ['001', None] and cell['column_labels'] == ['Name', 'Load']
    assert cell['pointer'].endswith('/tables/0/rows/0/cells/1')
    assert ours.inventory()['atom_counts']['figure_label'] == 2
    mutated = deepcopy(raw)
    mutated['catalogs'][0]['pages'][0]['content']['printed_page'] = None
    with pytest.raises(FormatError):
        restore_raw(ours.document, mutated)


def test_source_counts_and_boolean_indices_are_independently_checked(oleg):
    root, _ = oleg
    sources = json.loads((root / 'sources.json').read_text())
    sources['sources'][0]['counts'] = {'products': 99}
    write_json(root / 'sources.json', sources)
    seal(root)
    with pytest.raises(FormatError, match='Source declared count differs'):
        load_oleg_export(root).inventory()
    sources['sources'][0]['counts']['products'] = 3
    write_json(root / 'sources.json', sources)
    rows = [json.loads(line) for line in (root / 'characteristics.jsonl').read_text().splitlines()]
    rows[0]['characteristic_index'] = False  # Python False == 0 must not pass.
    (root / 'characteristics.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    seal(root)
    with pytest.raises(FormatError, match='Invalid ordered index'):
        load_oleg_export(root)


def test_window_uncertainty_index_is_checked_against_native_field(oleg):
    root, _ = oleg
    draft = root / 'drafts/W-one.json'
    native = json.loads(draft.read_text())
    boundary = {'title': 'continues', 'start_page': 1, 'reason': None}
    native['trailing_section'] = boundary
    write_json(draft, native)
    coverage = json.loads((root / 'coverage.json').read_text())
    coverage['windows'][0]['draft_sha256'] = hashlib.sha256(draft.read_bytes()).hexdigest()
    coverage['window_observations'][0]['raw']['trailing_section'] = boundary
    write_json(root / 'coverage.json', coverage)
    uncertain = {'id': 'U-one', 'source_id': 'S', 'window_id': 'W-one',
                 'level': 'window', 'owner_id': None, 'field': 'trailing_section', 'raw': boundary}
    (root / 'uncertainties.jsonl').write_text(json.dumps(uncertain) + '\n')
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['record_counts']['uncertainties'] = 1
    write_json(root / 'manifest.json', manifest)
    seal(root)
    export = load_oleg_export(root)
    assert exact_json_equal(export.reconstruct_window('W-one'), native)
    uncertain['raw']['reason'] = ''
    (root / 'uncertainties.jsonl').write_text(json.dumps(uncertain) + '\n')
    seal(root)
    with pytest.raises(FormatError, match='Uncertainty index differs'):
        load_oleg_export(root)


def test_pointer_resolves_original_array_order_and_escaped_names():
    from catalog_json.reconciliation.formats import resolve_pointer
    raw = {'a/b': {'~': [None, {'001': 'М12'}]}}
    assert resolve_pointer(raw, pointer('a/b', '~', 1, '001')) == 'М12'
    assert resolve_pointer(raw, '') is raw
    with pytest.raises(FormatError, match='array index'):
        resolve_pointer([1], '/00')
