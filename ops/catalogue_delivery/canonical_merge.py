"""Materialise one selected record set from immutable observations and decisions.

This is a retained-data merge, never OCR. Original observations and every decision
are written to a separate audit stream. JSON and Excel consume the same records.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import re
import resource
import subprocess
import unicodedata
import zipfile
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

import ijson

SCHEMA = 'canonical-catalogue/1'
INPUT_SHA = '0f4f272a4cc55407ae767b41694fc5f4d822986e8eb84dbe3008049a20aa2726'
CATALOGUES = ('opn', 'isolators', 'small', 'innovations', 'armature')
COUNTS = dict(zip(CATALOGUES, (60, 162, 228, 216, 314)))
UNITS = r'кДж/кВ|кОм|МОм|Ом|мм²|мм2|кН|кВ|кг|мм|мкСм|МПа|мкФ|пФ|см²|мА|Кл|Гц|мкВ|дБ|кА|кДж|Дж|баллов|шт|см|А|м|В|Н'


def js(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(x):
    return hashlib.sha256(js(x).encode()).hexdigest()


def file_sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def program_identity():
    root = Path(__file__).resolve().parents[2]
    try:
        revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        modified = subprocess.run(['git', '-C', str(root), 'diff', '--quiet', 'HEAD', '--',
                                  'ops/catalogue_delivery/canonical_merge.py',
                                  'ops/catalogue_delivery/canonical_export.py',
                                  'ops/catalogue_delivery/verify_canonical.py']).returncode != 0
        tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--error-unmatch',
                                  'ops/catalogue_delivery/canonical_merge.py',
                                  'ops/catalogue_delivery/canonical_export.py',
                                  'ops/catalogue_delivery/verify_canonical.py'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        modified = modified or not tracked
    except (OSError, subprocess.CalledProcessError):
        revision, modified = None, None
    return {'name': 'canonical-merge', 'version': '1.0.0', 'git_revision': revision,
            'source_sha256': file_sha(__file__), 'source_modified': modified}


def norm(x):
    """Representation comparison only; never rewrite an extracted value."""
    if x is None:
        return None
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', str(x))).strip()


def equivalent(a, b, numeric=True):
    if type(a) is type(b) and a == b:
        return True
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return False
    def number(v):
        if not isinstance(v, (int, float, str)):
            return None
        s = str(v).strip()
        if not re.fullmatch(r'[+-]?[0-9]+(?:[.,][0-9]+)?', s):
            return None
        return Decimal(s.replace(',', '.'))
    na, nb = number(a), number(b)
    if numeric and na is not None and nb is not None:
        return na == nb
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    # Whitespace and decimal separators are representation, not new values.
    return norm(a) == norm(b)


def join_scope(*parts):
    out = []
    for p in parts:
        if p is not None and norm(p) and norm(p) not in [norm(x) for x in out]:
            out.append(p)
    return '; '.join(out) or None


def inherited_unit(f, raw):
    if f.get('unit'):
        return f['unit']
    col = f.get('metadata', {}).get('column') or {}
    if col.get('unit'):
        return col['unit']
    for h in reversed(raw.get('header_path', [])):
        if h.get('unit'):
            return h['unit']
    # Only a literal unit after a comma in a stored header; never infer from
    # conditions such as "50 Гц" on a voltage column.
    for text in (f.get('name') or '', col.get('group') or ''):
        m = re.search(r',\s*(' + UNITS + r')(?!\w)', text)
        if m:
            return m[1]
    return None


def row_applicability(f, ctx):
    md = f.get('metadata', {})
    rv = ctx.get(f.get('row_context'), {}).get('row_values', [])
    ci = md.get('column_index')
    if ci is None or not rv:
        return None
    # Concrete conductor/section columns preceding a characteristic define its
    # application. Other numeric columns are not fabricated conditions.
    vals = []
    columns = md.get('_table_columns', {})
    for i, v in enumerate(rv[:ci]):
        col = columns.get(i, {})
        label = join_scope(col.get('group'), col.get('label')) or ''
        if re.search(r'(?i)(сечени|марк[аи]\s+провод|диаметр\s+провода|применяем\w*\s+лапк|наименование\s+зажима)', label) and v not in (None, '', '–', '—', '-'):
            vals.append(f'{label}: {v}')
    return join_scope(*vals)


def prepare_structure(facts, ctx):
    """Recover owners from retained table coordinates, not from model guesses."""
    by_table = collections.defaultdict(list)
    known = {norm(f['owner']) for f in facts if f['side'] == 'oleg' and f['kind'] == 'model_designation' and f.get('owner')}
    for f in facts:
        md = f.get('metadata', {})
        if f['side'] == 'ours' and 'column_index' in md:
            by_table[md['table_index']].append(f)
    for members in by_table.values():
        cols = {f['metadata']['column_index']: f['metadata'].get('column', {}) for f in members}
        transposed = {i: c['label'] for i, c in cols.items() if norm(c.get('label')) in known}
        anchors = collections.defaultdict(set)
        for f in members:
            if norm(f.get('value')) in known:
                anchors[f['metadata']['column_index']].add(f['metadata']['row_index'])
        anchors = sorted(i for i, rows in anchors.items() if len(rows) >= 2)
        for f in members:
            md = f['metadata']; md['_table_columns'] = cols
            rv = ctx.get(f.get('row_context'), {}).get('row_values', [])
            ci = md['column_index']
            if len(transposed) >= 2 and rv:
                if ci in transposed:
                    f['owner'] = transposed[ci]; f['name'] = str(rv[0]); f['kind'] = 'model_parameter'
                elif ci == 0:
                    f['kind'] = 'table_context'
            elif len(anchors) >= 2 and rv:
                prior = [i for i in anchors if i <= ci]
                if prior and rv[max(prior)] not in (None, '', '-', '–', '—'):
                    f['owner'] = rv[max(prior)]
                    if ci == max(prior):
                        f['kind'] = 'model_designation'; f['name'] = 'designation'


def adapt(f, ctx, aliases, producer_ref, patch=None):
    raw = ctx.get(f.get('raw_context'), {})
    raw = raw if isinstance(raw, dict) else {}
    col = f.get('metadata', {}).get('column') or {}
    kind = f['kind']
    part = col.get('group') or None
    if not part and raw.get('header_path'):
        parents = [h.get('raw_text') for h in raw['header_path'][:-1] if h.get('raw_text')]
        part = ' / '.join(parents) or None
    model = aliases.get(norm(f.get('owner')), f.get('owner')) or None
    condition = join_scope(f.get('condition'), col.get('qualifier'), row_applicability(f, ctx))
    # Generic notes and dimensions have an explicit source scope rather than
    # being promoted to an invented product/part.
    if not model:
        part = join_scope(part, f.get('metadata', {}).get('group_title'), raw.get('scope'))
    if kind == 'group_parameter' and raw.get('origin') == 'prose':
        kind = 'supporting_context'
    if raw.get('origin') == 'diagram_dimension' and kind in ('model_parameter', 'group_parameter'):
        kind = 'drawing_annotation'
        part = join_scope(part, raw.get('scope'))
    state = raw.get('value_state') or raw.get('state')
    if state is None:
        state = 'blank' if f.get('value') is None else 'value'
    state = {'printed_value': 'value', 'source_blank': 'blank', 'explicit_dash': 'dash'}.get(state, state)
    rec = dict(catalog=f['catalog'], page=f['physical_pages'][0], kind=kind,
               model=model, parameter=f.get('name') or None, part=part,
               condition=condition, value=f.get('value'), unit=inherited_unit(f, raw),
               state=state, source_fact_ids=[f['fact_id']], producer_ref=producer_ref)
    if kind == 'model_parameter' and re.fullmatch(r'(?i)страниц[аы](?:\s+каталога)?', str(rec['parameter']).strip()):
        rec['kind'] = 'index_entry'
    # Repeated radio columns are different source test settings, not conflicting
    # nominal product values. The adjacent stored voltage determines each dB.
    md = f.get('metadata', {})
    if f.get('side') == 'ours' and 'радиопомех' in (join_scope(col.get('group'), col.get('label'), rec['parameter']) or '').lower():
        ci = md.get('column_index'); rv = ctx.get(f.get('row_context'), {}).get('row_values', [])
        if rec['unit'] == 'кВ':
            rec['kind'] = 'test_condition'; rec['parameter'] = 'Напряжение измерения радиопомех'
        elif rec['unit'] == 'дБ' and isinstance(ci, int) and ci > 0 and len(rv) > ci:
            prior_col = md.get('_table_columns', {}).get(ci - 1, {})
            if prior_col.get('unit') == 'кВ' or 'кВ' in str(prior_col.get('label')):
                rec['parameter'] = 'Уровень радиопомех'
                rec['condition'] = join_scope(rec['condition'], f'При напряжении {rv[ci-1]} кВ')
    if patch:
        # An amendment may choose a scope/state, never manufacture a new value.
        rec.update(patch.get('canonical_scope', {}))
    return rec


def identity(r):
    fields = ('catalog', 'kind', 'model', 'parameter', 'part', 'condition')
    key = [r[k] for k in fields]
    if r['kind'] not in ('model_parameter', 'group_parameter', 'model_designation'):
        # Free text/figure callouts do not claim a scalar physical identity.
        key.extend([r['page'], r['value']])
    return key


def record_value(r):
    return {k: r[k] for k in ('value', 'unit', 'state')}


def unit_norm(unit):
    text = norm(unit)
    return {'мм2': 'мм²', 'мм^2': 'мм²', 'см2': 'см²', 'см^2': 'см²'}.get(text, text)


def pair_scope(records):
    """Fill absent scope from a reviewed pair; never erase explicit differences.

    Equal numbers alone do not license dropping another product, part, test
    condition or unit. Parameter wording may differ in a retained same-fact pair.
    """
    if len({r['kind'] for r in records}) != 1:
        return None
    patch = {}
    for field in ('model', 'part', 'condition', 'unit'):
        normalize = unit_norm if field == 'unit' else norm
        known = {normalize(r.get(field)): r[field] for r in records if normalize(r.get(field))}
        if len(known) > 1:
            return None
        if known and not norm(records[0].get(field)):
            patch[field] = next(iter(known.values()))
    if len({r['state'] for r in records}) != 1:
        return None
    return patch


def load_page_producers(archive):
    result = {}
    with zipfile.ZipFile(archive) as z, z.open('catalogue.json') as f:
        for page in ijson.items(f, 'catalogs.item.pages.item', use_float=True):
            result[(page['source_sha256'], page['pdf_page'])] = {
                'source_filename': page.get('source_filename'),
                'candidate_producer': page.get('candidate_producer'),
                'extractor': page.get('extractor')}
    return result


def write_comparison(output, records, groups, actions):
    """One row per canonical result, with original observations on both sides.

    A rejected claim without a replacement is a separate deletion row. Missing
    observations and different forms are never automatically called errors.
    """
    by_id = {r['id']: r for r in records.values()}
    by_fact = collections.defaultdict(set)
    for r in by_id.values():
        for fid in r['source_fact_ids']:
            by_fact[fid].add(r['id'])
    comparisons = {rid: {'id': rid, 'catalog': r['catalog'], 'page': r['page'],
                        'model': r['model'], 'parameter': r['parameter'],
                        'part': r['part'], 'condition': r['condition'],
                        'ours': {}, 'oleg': {}, 'result': r, 'mapping': set()}
                   for rid, r in by_id.items()}
    deletions = {}
    unpaired = {}
    mapped_facts = set()
    for group in groups:
        result_ids = set(group['result_ids'])
        for side in ('ours', 'oleg'):
            for obs in group[side]:
                fid = obs['fact_id']; target_ids = set(by_fact.get(fid, ()))
                amendment = actions.get(fid, {})
                for ref in amendment.get('replacement_source_fact_ids', []):
                    target_ids.update(by_fact.get(ref, ()))
                method = 'source_observation_reference'
                if not target_ids and len(result_ids) == 1 and group['relation'] == 'same_fact':
                    target_ids = result_ids; method = 'retained_single_characteristic_pair'
                if not target_ids:
                    # A structured group needs a physical-address match, never
                    # a match on a coincidentally equal number alone.
                    for rid in result_ids:
                        r = by_id[rid]
                        if obs.get('semantic_key') == identity(r):
                            target_ids.add(rid); method = 'retained_semantic_address'
                if target_ids:
                    mapped_facts.add(fid)
                    for rid in target_ids:
                        comparisons[rid][side][fid] = obs
                        comparisons[rid]['mapping'].add(method)
                elif amendment.get('action') == 'reject':
                    key = 'REMOVED-' + fid
                    deletions[key] = dict(id=key, catalog=group['catalog'], page=group['page'],
                         model=obs.get('owner'), parameter=obs.get('name'), part=None,
                         condition=obs.get('condition'), ours=[obs] if side == 'ours' else [],
                         oleg=[obs] if side == 'oleg' else [], result=None,
                         classification='rejected_incorrect_claim', amendment=amendment,
                         corrected_selection=True, correction_reasons=[amendment.get('reason')],
                         reason=amendment.get('reason'), mapping=['source_bound_rejection'])
                else:
                    unpaired[fid] = dict(id='UNPAIRED-' + fid, catalog=group['catalog'], page=group['page'],
                         model=obs.get('owner'), parameter=obs.get('name'), part=None,
                         condition=obs.get('condition'), ours=[obs] if side == 'ours' else [],
                         oleg=[obs] if side == 'oleg' else [], result=None,
                         classification='unpaired_source_observation', corrected_selection=False,
                         correction_reasons=[], mapping=['no_proven_characteristic_pair'],
                         reason='Original observation retained in audit; no proven canonical pairing.',
                         original_decision=group.get('decision'), original_relation=group['relation'])
    rows = []
    for r in comparisons.values():
        r['ours'] = list(r['ours'].values()); r['oleg'] = list(r['oleg'].values())
        r['mapping'] = sorted(r['mapping'])
        a, b = r['ours'], r['oleg']
        def signatures(items):
            return {js(x.get('semantic_value', {k: x.get(k) for k in ('value', 'unit', 'condition')})) for x in items}
        if r['result']['state'] == 'source_conflict':
            classification = 'conflicting_source_values'
        elif a and b:
            classification = 'equivalent_selected_observations' if signatures(a) == signatures(b) else 'different_source_representations_or_values'
        else:
            classification = 'only_ours_mapped' if a else 'only_oleg_mapped' if b else 'source_mapping_required'
        r['classification'] = classification
        r['corrected_selection'] = any(x['fact_id'] in actions for x in a + b)
        r['correction_reasons'] = sorted({actions[x['fact_id']]['reason'] for x in a + b
                                          if x['fact_id'] in actions and actions[x['fact_id']].get('reason')})
        r['reason'] = '; '.join(r['correction_reasons']) or None
        rows.append(r)
    rows.extend(deletions.values())
    rows.extend(row for fid, row in unpaired.items() if fid not in mapped_facts and 'REMOVED-' + fid not in deletions)
    with (output / 'comparison.jsonl').open('w') as f, (output / 'comparison.csv').open('w', newline='') as c:
        fields = ['catalog', 'page', 'model', 'parameter', 'part', 'condition', 'ours', 'oleg', 'result', 'classification', 'corrected_selection', 'reason', 'id']
        writer = csv.DictWriter(c, fields); writer.writeheader()
        for row in rows:
            f.write(js(row) + '\n')
            writer.writerow({k: js(row[k]) if isinstance(row[k], (dict, list)) else row[k] for k in fields})
    return {cat: dict(collections.Counter(r['classification'] for r in rows if r['catalog'] == cat)) for cat in CATALOGUES}


def build(pages_dir, packets_dir, archive, amendments_path, unresolved_path, output, scope_paths=()):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    if file_sha(archive) != INPUT_SHA:
        raise ValueError('The immutable input archive differs from the audited snapshot')
    amendment = json.loads(Path(amendments_path).read_text())
    actions = {a['source_fact_id']: a for a in amendment['actions']}
    if len(actions) != len(amendment['actions']):
        raise ValueError('Duplicate amendment IDs')
    scope_overrides = {}
    option_sets = []
    preferred = {}
    source_conflicts = []
    group_exceptions = set()
    scope_input_hashes = {}
    for p in scope_paths:
        scope_input_hashes[Path(p).name] = file_sha(p)
        scopes = json.loads(Path(p).read_text())
        for a in scopes.get('actions', []):
            if a['source_fact_id'] in actions:
                raise ValueError('Conflicting source selections')
            actions[a['source_fact_id']] = a
        for selection in scopes.get('source_selections', []):
            if not selection.get('evidence'):
                raise ValueError('Source selection requires evidence')
            for mode in ('select', 'reject'):
                for fid in selection.get(mode, []):
                    if fid in actions:
                        raise ValueError('Conflicting source selection ' + fid)
                    actions[fid] = dict(source_fact_id=fid, action=mode, reason=selection['reason'], source_proof=selection['evidence'])
        for fid, item in scopes.get('overrides', {}).items():
            patch = item.get('patch', item)
            if any(k not in {'kind', 'model', 'parameter', 'part', 'condition', 'state', 'unit'} for k in patch):
                raise ValueError('Scope adapter may not rewrite extracted values')
            if 'unit' in patch and not item.get('evidence'):
                raise ValueError('Unit scope correction requires retained source evidence')
            if fid in scope_overrides and scope_overrides[fid] != patch:
                raise ValueError('Conflicting scope amendments')
            scope_overrides[fid] = patch
        option_sets.extend(scopes.get('option_sets', []))
        source_conflicts.extend(scopes.get('source_conflict_sets', []))
        group_exceptions.update((s['catalog'], s['page'], s['group']) for s in scopes.get('split_group_exceptions', []))
        for s in scopes.get('list_representation_groups', []):
            target = s.get('preferred_fact_id', s.get('combined_fact_id'))
            if target:
                for fid in s['fact_ids']:
                    preferred[fid] = (target, s['fact_ids'])
        for s in scopes.get('equivalence_sets', []):
            target = s['preferred_fact_id']; refs = sorted(set([target] + s['equivalent_fact_ids']))
            for fid in refs:
                preferred[fid] = (target, refs)
    preferred_targets = {target for target, _ in preferred.values()}
    source_conflict_by_id = {}
    source_conflict_templates = {}
    for i, s in enumerate(source_conflicts):
        for fid in s['fact_ids']:
            source_conflict_by_id[fid] = i
    options_by_fid = {}
    for i, s in enumerate(option_sets):
        for fid in s['fact_ids']:
            if fid in options_by_fid:
                raise ValueError('Observation is in two option sets')
            options_by_fid[fid] = i
    old_unresolved = json.loads(Path(unresolved_path).read_text())['facts']
    unresolved_ids = {x['fact']['fact_id'] for x in old_unresolved}
    if len(old_unresolved) != 42 or unresolved_ids.intersection(actions):
        raise ValueError('Original 42 unresolved observations must stay unchanged')
    page_producers = load_page_producers(archive)
    records = {}; producers = {}; sources = {}; pages = []; comparisons = []
    conflicts = []; groups_audit = []; facts_seen = set(); table_ids = []
    preferred_selected = set(); observation_count = 0
    for path in sorted(Path(pages_dir).glob('*.json'), key=lambda p: (CATALOGUES.index(p.stem.rsplit('-', 1)[0]), p.name)):
        d = json.loads(path.read_text()); cat = d['catalog']; page = d['page']
        packet = json.loads((Path(packets_dir) / path.name).read_text()); ctx = packet['contexts']
        fs = copy.deepcopy(d['facts']); receipt = d['receipt']
        original = {f['fact_id']: copy.deepcopy(f) for f in fs}
        observation_count += len(fs)
        prepare_structure(fs, ctx)
        source_sha = receipt['source_sha256']
        pp = page_producers[(source_sha, page)]
        sources[cat] = dict(id=cat, filename=pp['source_filename'], sha256=source_sha, page_count=COUNTS[cat])
        pages.append(dict(catalog=cat, page=page))
        provenance = {'original_selection': receipt['identity'], 'work_sha256': receipt['work_sha256'],
                      'ours': pp, 'oleg': {'name': 'Oleg supplied extraction', 'model': None,
                                         'artifact': 'originals/oleg-original.zip'}}
        pref = 'P-' + digest(provenance)[:20]; producers[pref] = provenance
        aliases = {}
        for g in receipt['groups']:
            if g['relation'] != 'same_fact':
                continue
            mm = [fs[i] for i in g['fact_indices'] if fs[i]['kind'] == 'model_designation']
            aa = {f['owner'] for f in mm if f['side'] == 'ours' and f.get('owner')}
            bb = {f['owner'] for f in mm if f['side'] == 'oleg' and f.get('owner')}
            if len(aa) == len(bb) == 1:
                target = next(iter(bb if g['keep'] == 'oleg' else aa))
                for s in aa | bb:
                    aliases[norm(s)] = target
        for gi, g in enumerate(receipt['groups']):
            members = [fs[i] for i in g['fact_indices']]
            for f in members:
                facts_seen.add(f['fact_id'])
                a = actions.get(f['fact_id'])
                if a and (('original_value' in a and js(a['original_value']) != js(original[f['fact_id']].get('value'))) or
                          ('input_fact_sha256' in a and a['input_fact_sha256'] != original[f['fact_id']].get('input_fact_sha256'))):
                    raise ValueError('Amendment not bound to immutable observation: ' + f['fact_id'])
            selected = [f for f in members if g['keep'] == 'both' or f['side'] == g['keep']]
            selected = [f for f in selected if actions.get(f['fact_id'], {}).get('action') != 'reject']
            selected += [f for f in members if actions.get(f['fact_id'], {}).get('action') == 'select' and f not in selected]
            selected += [f for f in members if f['fact_id'] in preferred_targets and f not in selected and g['keep'] != 'unresolved']
            if g['keep'] == 'unresolved':
                selected = []
            # A single same-fact pair is represented once. Same-fact is not
            # permission to flatten multi-row variant groups.
            aa = [f for f in selected if f['side'] == 'ours']
            bb = [f for f in selected if f['side'] == 'oleg']
            pair_patches = {}
            def effective(f):
                r = adapt(f, ctx, aliases, pref, actions.get(f['fact_id']))
                r.update(scope_overrides.get(f['fact_id'], {}))
                r.update(pair_patches.get(f['fact_id'], {}))
                return r
            extra_refs = {}
            if (cat, page, gi) not in group_exceptions and g['keep'] == 'both' and g['relation'] in ('same_fact', 'duplicate_observations') and len(aa) == 1 and bb:
                patch = pair_scope([effective(f) for f in aa + bb])
                if patch is not None and all(equivalent(aa[0].get('value'), f.get('value'), numeric=aa[0]['kind'] != 'model_designation') for f in bb):
                    selected = aa
                    pair_patches[aa[0]['fact_id']] = patch
                    extra_refs[aa[0]['fact_id']] = [f['fact_id'] for f in bb]
                elif aa[0]['kind'] == 'model_designation' and all(f['kind'] == 'model_designation' for f in bb):
                    codes = re.split(r',\s*(?=[А-ЯA-Z])', str(aa[0]['value']))
                    if sorted(norm(c) for c in codes) == sorted(norm(f['value']) for f in bb):
                        selected = bb
                        for f in bb:
                            extra_refs[f['fact_id']] = [aa[0]['fact_id']]
                # Otherwise retain independently scoped records. The legacy
                # group label is not a physical identity. The identity collision
                # check below, not the old many-to-many group, rejects genuine
                # incompatible selections.
            results = []
            for f in selected:
                if f['fact_id'] in unresolved_ids:
                    raise ValueError('Unresolved fact selected as canonical')
                rec = effective(f)
                if f['fact_id'] in preferred:
                    target, refs = preferred[f['fact_id']]
                    if f['fact_id'] != target:
                        continue
                    rec['source_fact_ids'] = refs
                    preferred_selected.add(target)
                rec['source_fact_ids'].extend(extra_refs.get(f['fact_id'], []))
                if f['fact_id'] in source_conflict_by_id:
                    ix = source_conflict_by_id[f['fact_id']]
                    if ix not in source_conflict_templates:
                        source_conflict_templates[ix] = {k: rec[k] for k in ('model', 'parameter', 'part', 'condition', 'unit')}
                    rec.update(source_conflict_templates[ix])
                    rec.update(value=None, state='source_conflict', source_fact_ids=source_conflicts[ix]['fact_ids'])
                k = js(identity(rec)); rid = 'C-' + hashlib.sha256(k.encode()).hexdigest()[:24]
                rec['id'] = rid
                if k in records:
                    old = records[k]
                    oids = {options_by_fid.get(fid) for fid in old['source_fact_ids']}
                    nid = options_by_fid.get(f['fact_id'])
                    if nid is not None and nid in oids:
                        # Only an explicit source-reviewed set licenses multiple
                        # permitted values. No arbitrary conflict becomes a list.
                        if not isinstance(old['value'], list):
                            old['value'] = [old['value']]
                        if not any(js(rec['value']) == js(v) for v in old['value']):
                            old['value'].append(rec['value'])
                    elif not (equivalent(old['value'], rec['value'], numeric=rec['kind'] != 'model_designation') or (old['state'] == rec['state'] == 'blank' and old['value'] in (None, '') and rec['value'] in (None, ''))) or (old['unit'] and rec['unit'] and unit_norm(old['unit']) != unit_norm(rec['unit'])):
                        conflicts.append(dict(catalog=cat, page=page, reason='same physical key has different selected values', key=identity(rec), ours=old, other=rec))
                        continue
                    old['source_fact_ids'] = sorted(set(old['source_fact_ids'] + rec['source_fact_ids']))
                    if not old['unit'] and rec['unit']:
                        old['unit'] = rec['unit']
                    if old['producer_ref'] != rec['producer_ref']:
                        refs = []
                        for pr in (old['producer_ref'], rec['producer_ref']):
                            refs.extend(producers[pr].get('contributors', [pr]))
                        refs = sorted(set(refs)); combined = 'P-' + digest(refs)[:20]
                        producers[combined] = {'contributors': refs, 'program': 'canonical-merge/1'}
                        old['producer_ref'] = combined
                else:
                    records[k] = rec
                results.append(rid)
                if (cat, page) in (('isolators', 64), ('armature', 119), ('armature', 120)):
                    table_ids.extend(rec['source_fact_ids'])
            def observation(f):
                obs = {k: original[f['fact_id']].get(k) for k in ('fact_id', 'kind', 'owner', 'name', 'value', 'unit', 'condition', 'pointer')}
                semantic = effective(f)
                obs['semantic_key'] = identity(semantic)
                obs['semantic_value'] = {k: semantic[k] for k in ('value', 'unit', 'state')}
                return obs
            observations = {side: [observation(f) for f in members if f['side'] == side] for side in ('ours', 'oleg')}
            groups_audit.append(dict(catalog=cat, page=page, group=gi, keep=g['keep'], relation=g['relation'], result_ids=sorted(set(results)), input_fact_ids=[f['fact_id'] for f in members], reason=g['reason']))
            comparisons.append(dict(catalog=cat, page=page, group=gi, relation=g['relation'], ours=observations['ours'], oleg=observations['oleg'], result_ids=sorted(set(results)), decision=g['keep'], amendments=[a for f in members if (a := actions.get(f['fact_id']))]))
    if len(pages) != 980 or collections.Counter(x['catalog'] for x in pages) != COUNTS:
        raise ValueError('Expected all five catalogues / 980 pages')
    if set(actions) - facts_seen:
        raise ValueError('Unknown amendment observations')
    if preferred_targets - preferred_selected:
        raise ValueError('A preferred observation was not materialised: ' + str(sorted(preferred_targets - preferred_selected)[:5]))
    data = dict(schema=SCHEMA, sources=list(sources.values()), pages=pages,
                producers=producers, records=sorted(records.values(), key=lambda r: (CATALOGUES.index(r['catalog']), r['page'], r['id'])),
                unresolved=old_unresolved, metadata={'builder': program_identity(), 'input_archive_sha256': INPUT_SHA,
                 'review_scope': 'Retained merge decisions plus explicit source-bound amendments; not a new independent review of every PDF page.',
                 'selected_table_source_fact_ids': sorted(set(table_ids)), 'new_audit_issues': amendment.get('new_audit_issues', []),
                 'source_conflicts': source_conflicts, 'amendments_sha256': file_sha(amendments_path),
                 'scope_inputs_sha256': scope_input_hashes})
    for name, rows in (('observation-comparison.jsonl', comparisons), ('decisions.jsonl', groups_audit), ('conflicts.jsonl', conflicts)):
        with (output / name).open('w') as f:
            for r in rows:
                f.write(js(r) + '\n')
    report = dict(records=len(records), pages=len(pages), original_unresolved=len(old_unresolved), conflicts=len(conflicts), source_observations=len(facts_seen), source_observation_occurrences=observation_count, amendments=len(actions), source_conflicts=len(source_conflicts))
    (output / 'build-report.json').write_text(js(report) + '\n')
    if conflicts:
        raise ValueError(f'{len(conflicts)} unresolved canonical conflicts; see conflicts.jsonl')
    report['comparison'] = write_comparison(output, records, comparisons, actions)
    (output / 'catalogue.json').write_text(js(data) + '\n')
    (output / 'build-report.json').write_text(js(report) + '\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pages', type=Path, required=True); p.add_argument('--packets', type=Path, required=True)
    p.add_argument('--archive', type=Path, required=True); p.add_argument('--amendments', type=Path, required=True)
    p.add_argument('--unresolved', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scope', type=Path, action='append', default=[])
    a = p.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    print(js(build(a.pages, a.packets, a.archive, a.amendments, a.unresolved, a.output, a.scope)))


if __name__ == '__main__':
    main()
