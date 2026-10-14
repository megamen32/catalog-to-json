"""Compare retained observations without conflating duplicate windows with SKUs.

Matching is intentionally conservative. An unmatched observation is an open
alignment question, not a claim that the other extractor missed the fact.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, Counter
from decimal import Decimal, InvalidOperation
import hashlib
import gzip
import json
from pathlib import Path
import re
import unicodedata
import zipfile


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def label(value):
    return ' '.join(unicodedata.normalize('NFC', str(value or '')).casefold().split())


def designation(value):
    # Never map visually similar Cyrillic and Latin characters.
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', str(value or ''))).translate(str.maketrans({'–': '-', '‑': '-'}))


def unit_identity(value):
    # SI prefix case is significant: МПа and мПа are not interchangeable.
    return ' '.join(unicodedata.normalize('NFC', str(value or '')).split())


def property_label(name, unit=''):
    symbols = re.findall(r'(?<!\w)[A-Za-zНнДдФф](?:[0-9₀-₉]*)(?!\w)', str(name or ''))
    text = label(name)
    suffix = label(unit)
    if suffix:
        text = re.sub(r'[\s,;([]*' + re.escape(suffix) + r'[\s)\]]*$', '', text)
    return text.strip(' ,;') + ('|symbols:' + json.dumps(symbols, ensure_ascii=False) if symbols else '')


def value_identity(value):
    """A comparison key only; never replaces the retained typed raw value."""
    if isinstance(value, bool) or value is None:
        return (type(value).__name__, json.dumps(value))
    if isinstance(value, (int, float)):
        return ('decimal', str(Decimal(str(value)).normalize()))
    if isinstance(value, str):
        s = ' '.join(unicodedata.normalize('NFC', value).split())
        if re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?', s):
            # Only plain scalar numbers. Signs, ranges, bounds and codes retain
            # their identity; leading zeros are kept distinct as possible IDs.
            digits = s.lstrip('+-').split(',')[0].split('.')[0]
            if len(digits) == 1 or not digits.startswith('0'):
                try:
                    return ('decimal', str(Decimal(s.replace(',', '.')).normalize()))
                except InvalidOperation:
                    pass
        return ('string', s)
    return (type(value).__name__, digest(value))


def _evidence_pages(raw):
    return sorted({int(e['page']) for e in raw.get('evidence', [])
                   if isinstance(e, dict) and type(e.get('page')) is int and e['page'] > 0})


def _rows(path):
    with Path(path).open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def load_facts(oleg_dir, ours_zip):
    """Retain all material claims; byte/record roundtrips live in formats.py."""
    oleg_dir = Path(oleg_dir)
    sources = {s['id']: s for s in json.loads((oleg_dir/'sources.json').read_text())['sources']}
    models = {m['id']: m for m in _rows(oleg_dir/'products.jsonl')}
    groups = {g['id']: g for g in _rows(oleg_dir/'product_groups.jsonl')}
    with zipfile.ZipFile(ours_zip) as z:
        ours = json.loads(z.read('all-catalogues-980-pages.json'))
    catalogue_ids = {c['source']['sha256']: c['id'] for c in ours['catalogs']}
    assert {s['sha256'] for s in sources.values()} == set(catalogue_ids), 'Different PDF source sets'
    known_names = defaultdict(set)
    facts = []

    def add(side, source_sha, pages, kind, pointer, owner, name, value, unit='', condition='', **extra):
        item = {'side': side, 'source_sha256': source_sha, 'catalog': catalogue_ids[source_sha],
                'physical_pages': pages, 'kind': kind, 'pointer': pointer, 'owner': owner,
                'name': name, 'value': value, 'raw_value_type': type(value).__name__,
                'unit': unit, 'condition': condition, **extra}
        item['fact_id'] = ('O-' if side == 'ours' else 'L-') + digest([source_sha, pointer])[:24]
        facts.append(item)

    for n, product in enumerate(models.values(), 1):
        raw = product['raw']; source_sha = sources[product['source_id']]['sha256']
        pages = _evidence_pages(raw)
        add('oleg', source_sha, pages, 'model_designation',
            f'products.jsonl:{n}/raw/designation', raw.get('designation', ''),
            'designation', raw.get('designation'), observation_id=product['id'],
            window_id=product['window_id'], group_id=product['group_id'], raw=raw)

    for filename in ['characteristics.jsonl', 'group_characteristics.jsonl']:
        for n, row in enumerate(_rows(oleg_dir/filename), 1):
            raw = row['raw']; source_sha = sources[row['source_id']]['sha256']
            product = models.get(row.get('product_id'), {})
            group = groups[row['group_id']]
            owner = product.get('raw', {}).get('designation', '')
            pages = _evidence_pages(raw) or _evidence_pages(product.get('raw', {})) or _evidence_pages(group['raw'])
            for page in pages:
                if owner:
                    known_names[source_sha, page].add(designation(owner))
            add('oleg', source_sha, pages, 'model_parameter' if product else 'group_parameter',
                f'{filename}:{n}/raw', owner, raw.get('name', ''), raw.get('raw_value'),
                raw.get('unit', ''), raw.get('condition', ''), observation_id=row['id'],
                window_id=row['window_id'], group_id=row['group_id'], product_id=row.get('product_id'),
                group_title=group['raw'].get('title'), raw=raw,
                raw_value_present='raw_value' in raw)

    for ci, catalogue in enumerate(ours['catalogs']):
        source_sha = catalogue['source']['sha256']
        for pi, page in enumerate(catalogue['pages']):
            number = page['pdf_page']; content = page['content']
            prefix = f'/catalogs/{ci}/pages/{pi}/content'
            for ti, table in enumerate(content.get('tables', [])):
                cols = table['columns']; matrix = [{c['column_id']: c for c in row['cells']} for row in table['rows']]
                names = known_names[source_sha, number]
                header_hits = [designation(c['label']) in names for c in cols]
                transposed = sum(header_hits) >= 2 and sum(header_hits) >= len(cols)-2
                column_hits = [sum(designation(row.get(c['id'], {}).get('value')) in names for row in matrix) for c in cols]
                primary = max(range(len(cols)), key=lambda i: column_hits[i]) if cols else 0
                if cols and not column_hits[primary]:
                    primary = next((i for i, c in enumerate(cols) if any(t in label(c['label']) for t in ('наименование', 'марка', 'обозначение', 'тип изделия'))), 0)
                for ri, row in enumerate(matrix):
                    owner = row.get(cols[primary]['id'], {}).get('value', '') if cols else ''
                    for cj, col in enumerate(cols):
                        cell = row.get(col['id'])
                        if cell is None:
                            continue
                        if transposed and cj:
                            owner_value, prop = col['label'], row.get(cols[0]['id'], {}).get('value', '')
                        else:
                            owner_value, prop = owner, col['label']
                        kind = 'model_designation' if (not transposed and cj == primary) or (transposed and cj == 0) else 'model_parameter'
                        add('ours', source_sha, [number], kind,
                            f'{prefix}/tables/{ti}/rows/{ri}/cells/{next(i for i,c in enumerate(table["rows"][ri]["cells"]) if c["column_id"]==col["id"])}', owner_value,
                            'designation' if kind == 'model_designation' and not transposed else prop,
                            cell.get('value'), col.get('unit'), col.get('qualifier'),
                            table_index=ti, row_index=ri, column_index=cj,
                            table_title=table.get('title'), column=col, raw=cell,
                            row_values=[row.get(c['id'], {}).get('value') for c in cols],
                            candidate_sha256=page['candidate_sha256'],
                            previously_accepted=page['reviewed_current_content'])
            for kind, field in [('page_text','text_blocks'), ('figure','figures'), ('source_note','source_notes'), ('uncertainty','uncertainties')]:
                for i, raw in enumerate(content.get(field, [])):
                    value = raw.get('text') if kind == 'page_text' else raw
                    add('ours', source_sha, [number], kind, f'{prefix}/{field}/{i}', '',
                        raw.get('kind','') if isinstance(raw,dict) else kind, value,
                        raw=raw, candidate_sha256=page['candidate_sha256'],
                        previously_accepted=page['reviewed_current_content'])
    return facts, sources, ours


def compare_facts(facts):
    """Every fact is accounted for; ambiguous/missing matches require a judge."""
    right = defaultdict(list)
    for f in facts:
        if f['side'] == 'oleg' and f['kind'] in ('model_parameter', 'model_designation'):
            for p in f['physical_pages']:
                right[f['source_sha256'], p, designation(f['owner']),
                      property_label(f['name'], f['unit'])].append(f)
    used_oleg = set(); ledger = []; cases = []
    for f in facts:
        if f['side'] != 'ours':
            continue
        matches = []
        if f['kind'] in ('model_parameter', 'model_designation'):
            for p in f['physical_pages']:
                matches += right.get((f['source_sha256'], p, designation(f['owner']), property_label(f['name'], f['unit'])), [])
        distinct = {x['fact_id']: x for x in matches}
        matches = list(distinct.values())
        # Repeated observations remain individually linked; no winner by order.
        identities = {(value_identity(x['value']), unit_identity(x['unit']), unit_identity(x['condition'])) for x in matches}
        identity = value_identity(f['value']), unit_identity(f['unit']), unit_identity(f['condition'])
        if matches and identities == {identity}:
            status = 'exact_agreement' if all(type(x['value']) is type(f['value']) and x['value'] == f['value'] for x in matches) else 'representation_difference'
        elif matches:
            status = 'value_or_applicability_conflict' if len(identities) == 1 else 'ambiguous_alignment'
        else:
            status = 'unmatched_ours_observation'
        used_oleg.update(x['fact_id'] for x in matches)
        entry = {'ours_fact_id': f['fact_id'], 'oleg_fact_ids': [x['fact_id'] for x in matches], 'status': status}
        ledger.append(entry)
        if status not in ('exact_agreement',):
            cases.append({'kind': status, 'source_sha256': f['source_sha256'],
                          'physical_pages': f['physical_pages'], 'ours': [f], 'oleg': matches})
    for f in facts:
        if f['side'] == 'oleg' and f['fact_id'] not in used_oleg:
            ledger.append({'ours_fact_id': None, 'oleg_fact_ids': [f['fact_id']], 'status': 'unmatched_oleg_observation'})
            cases.append({'kind': 'unmatched_oleg_observation', 'source_sha256': f['source_sha256'],
                          'physical_pages': f['physical_pages'], 'ours': [], 'oleg': [f]})
    for case in cases:
        case['case_id'] = 'D-' + digest(case)[:24]
    return ledger, cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--oleg', type=Path, required=True)
    parser.add_argument('--ours', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compact', action='store_true',
                        help='Gzip fact store and ledger; cases reference immutable fact IDs rather than repeat raw records')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    facts, sources, ours = load_facts(args.oleg, args.ours)
    ledger, cases = compare_facts(facts)
    case_rows = cases
    if args.compact:
        case_rows = ({**{k:v for k,v in case.items() if k not in ('ours','oleg')},
                      'ours_fact_ids':[f['fact_id'] for f in case['ours']],
                      'oleg_fact_ids':[f['fact_id'] for f in case['oleg']]} for case in cases)
    for name, rows in [('facts.jsonl', facts), ('alignment-ledger.jsonl', ledger), ('cases.jsonl', case_rows)]:
        path = args.output/(name+'.gz' if args.compact else name)
        # Retain previous diagnostics; a new run must use a fresh output directory.
        opener = gzip.open if args.compact else open
        with opener(path, 'xt', encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
    summary = {'source_sha256_sets_equal': True, 'source_count': len(sources),
               'ours_physical_pages': sum(len(c['pages']) for c in ours['catalogs']),
               'facts_by_side_kind': dict(Counter(f"{f['side']}:{f['kind']}" for f in facts)),
               'alignment_counts': dict(Counter(x['status'] for x in ledger)),
               'case_count': len(cases), 'semantic_alignment_complete': False,
               'all_unmatched_facts_retained': True, 'consensus_votes': 0,
               'comparison_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'input_ours_zip_sha256': hashlib.file_digest(args.ours.open('rb'), 'sha256').hexdigest(),
               'compact_fact_references': args.compact,
               'warning': 'Unmatched and ambiguous are questions, not proven extraction errors. No four-party consensus yet.'}
    (args.output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
