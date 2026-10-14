"""Prepare ALL retained facts and ledger rows for disjoint catalogue owners.

Preparation never accepts facts, resolves matches, or changes source values.
One native worker owns each complete catalogue; independent audit is a later stage.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource

from catalog_json.reconciliation.consensus import case_sha256, load_sources

OWNERS = {'opn': 'zcode', 'small': 'zcode', 'armature': 'minimax',
          'innovations': 'codex', 'isolators': 'codex'}


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(facts_file, ledger_file, sources, output, *, max_output_bytes=256*1024**2):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    pages = {}; meta = {}; original_counts = collections.Counter()
    required = ('fact_id', 'side', 'catalog', 'kind', 'pointer', 'owner', 'name',
                'value', 'unit', 'condition', 'physical_pages')
    with gzip.open(facts_file, 'rt') as stream:
        for line_number, line in enumerate(stream, 1):
            fact = json.loads(line); fid = fact['fact_id']; sha = fact['source_sha256']
            if fid in meta or sha not in sources:
                raise ValueError('Duplicate fact ID or unknown original source')
            catalog = fact['catalog']; owner = OWNERS[catalog]
            locations = fact['physical_pages'] or [0]
            if any(type(n) is not int or n < 0 or n > sources[sha]['page_count'] for n in locations):
                raise ValueError('Fact location outside original PDF')
            meta[fid] = (sha, locations, catalog, fact['side'], fact['kind'])
            original_counts[fact['side']+':'+fact['kind']] += 1
            for n in locations:
                key = (sha, n)
                page = pages.setdefault(key, {'catalog': catalog, 'source_sha256': sha,
                    'physical_page': n, 'owner': owner, 'facts': [], 'contexts': {},
                    'ledger_rows': [], 'external_fact_refs': {}})
                compact = {k: fact[k] for k in required}
                compact['input_fact_sha256'] = case_sha256(fact)
                compact['input_line'] = line_number
                # Keep exact row/header/manufacturer/drawing context, shared
                # once rather than repeated in every cell of the same row.
                extra = {k: v for k, v in fact.items()
                         if k not in required and k != 'source_sha256'}
                row = extra.pop('row_values', None)
                if row is not None:
                    rid = 'row-'+case_sha256([extra.get('table_index'), extra.get('row_index'), row])
                    page['contexts'][rid] = {'row_values': row}
                    compact['row_context'] = rid
                raw = extra.pop('raw', None)
                if raw is not None:
                    # Raw value/name/unit are already typed above. All other
                    # original context remains available without abbreviation.
                    raw_context = ({k: v for k, v in raw.items()
                                    if k not in ('raw_value', 'name', 'unit', 'condition')}
                                   if isinstance(raw, dict) else raw)
                    cid = 'raw-'+case_sha256(raw_context)
                    page['contexts'][cid] = raw_context
                    compact['raw_context'] = cid
                compact['metadata'] = extra
                page['facts'].append(compact)
    # Include the ENTIRE source set, including pages with no extracted facts.
    catalog_by_sha = {v[0]: v[2] for v in meta.values()}
    for sha, source in sources.items():
        catalog = catalog_by_sha[sha]
        for n in range(1, source['page_count']+1):
            pages.setdefault((sha, n), {'catalog': catalog, 'source_sha256': sha,
                'physical_page': n, 'owner': OWNERS[catalog], 'facts': [],
                'contexts': {}, 'ledger_rows': [], 'external_fact_refs': {}})
    ledger_counts = collections.Counter(); residual_model_ids = set(); total_rows = 0
    with gzip.open(ledger_file, 'rt') as stream:
        for ordinal, line in enumerate(stream, 1):
            row = json.loads(line)
            ids = ([row['ours_fact_id']] if row['ours_fact_id'] else []) + row['oleg_fact_ids']
            if not ids or any(fid not in meta for fid in ids):
                raise ValueError('Ledger references missing original facts')
            first = meta[ids[0]]; home = (first[0], first[1][0])
            if any(meta[fid][0] != home[0] for fid in ids):
                raise ValueError('Cross-source alignment cannot be silently merged')
            page = pages[home]
            page['ledger_rows'].append({'ledger_ordinal': ordinal, **row})
            local = {f['fact_id'] for f in page['facts']}
            for fid in ids:
                if fid not in local:
                    sha, locations, catalog, side, kind = meta[fid]
                    page['external_fact_refs'][fid] = {'source_sha256': sha,
                        'physical_pages': locations, 'catalog': catalog, 'side': side, 'kind': kind}
            ledger_counts[row['status']] += 1; total_rows += 1
            fid = row['ours_fact_id']
            if fid and meta[fid][4] == 'model_parameter' and row['status'] in (
                    'unmatched_ours_observation', 'ambiguous_alignment'):
                residual_model_ids.add(fid)
    manifest = {'schema_version': 'catalogue-full-alignment-work/1',
        'phase': 'disjoint-author-work; independent final audit deferred by owner',
        'input_fact_store_sha256': file_sha(facts_file),
        'input_ledger_sha256': file_sha(ledger_file),
        'owners': OWNERS, 'preparation_accepts_no_facts': True,
        'unique_original_facts': len(meta), 'facts_by_side_kind': dict(original_counts),
        'ledger_rows': total_rows, 'ledger_counts': dict(ledger_counts),
        'unmatched_or_ambiguous_our_model_parameters': len(residual_model_ids),
        'pages': []}
    retained = set(); written = 0
    for key, page in sorted(pages.items(), key=lambda kv: (kv[1]['catalog'], kv[0][1])):
        page['input_fact_store_sha256'] = manifest['input_fact_store_sha256']
        page['input_ledger_sha256'] = manifest['input_ledger_sha256']
        retained.update(f['fact_id'] for f in page['facts'])
        name = page['catalog']+'-'+str(page['physical_page']).zfill(4)+'.json'
        data = (json.dumps(page, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode()
        written += len(data)
        if written > max_output_bytes:
            raise ValueError('Finite work-packet storage budget exceeded; retain partial preparation')
        (output/name).write_bytes(data)
        residual = sum(f['fact_id'] in residual_model_ids for f in page['facts'])
        manifest['pages'].append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(),
            'catalog': page['catalog'], 'physical_page': page['physical_page'], 'owner': page['owner'],
            'source_sha256': page['source_sha256'], 'facts': len(page['facts']),
            'ledger_rows': len(page['ledger_rows']), 'residual_model_parameters': residual,
            'open_ledger_rows': sum(r['status'] != 'exact_agreement' for r in page['ledger_rows'])})
    if retained != set(meta): raise ValueError('Preparation lost original facts')
    manifest['physical_pages'] = sum(x['physical_page'] > 0 for x in manifest['pages'])
    manifest['unlocated_work_packets'] = sum(x['physical_page'] == 0 for x in manifest['pages'])
    manifest['written_bytes'] = written
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    folder = args.task/'comparison-property-scope-safe'
    result = prepare(folder/'facts.jsonl.gz', folder/'alignment-ledger.jsonl.gz',
        load_sources(args.task/'all-sources.json'), args.output)
    print(json.dumps({k: result[k] for k in ('physical_pages', 'unique_original_facts',
        'ledger_rows', 'unmatched_or_ambiguous_our_model_parameters', 'written_bytes')}))


if __name__ == '__main__': main()
