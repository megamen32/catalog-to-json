"""Local PDF complexity inventory; heuristic ranks are never quality scores."""
import hashlib
import json
import inspect
import math
import re
import time
from collections import defaultdict
from pathlib import Path

import pymupdf

from .tools import write_json


def page_features(page):
    blocks = page.get_text('dict')['blocks']
    lines = [line for block in blocks for line in block.get('lines', [])]
    spans = [span for line in lines for span in line['spans'] if span['text'].strip()]
    words = page.get_text('words')
    rotated = sum(abs(line.get('dir', (1, 0))[1]) > .1 for line in lines)
    tiny = sum((s['bbox'][3] - s['bbox'][1]) / page.rect.height < .012 for s in spans)
    horizontal = vertical = vectors = 0
    for drawing in page.get_drawings():
        for item in drawing['items']:
            vectors += 1
            if item[0] == 'l':
                a, b = item[1:]
                horizontal += abs(a.y - b.y) < .3 and abs(a.x - b.x) > 3
                vertical += abs(a.x - b.x) < .3 and abs(a.y - b.y) > 3
            elif item[0] == 're':
                horizontal += 2
                vertical += 2
    area = page.rect.width * page.rect.height
    images = [b for b in blocks if b['type'] == 1]
    image_fraction = min(1, sum(pymupdf.Rect(b['bbox']).get_area() for b in images) / area)
    labels = sum(bool(re.search(r'[±Ø□⌀]|^[A-Za-zА-Яа-я]{1,2}\d{0,2}$', w[4])) for w in words)
    numeric = sum(bool(re.search(r'\d', w[4])) for w in words)
    tags = []
    if rotated: tags.append('rotated_text')
    if horizontal >= 15 and vertical >= 8: tags.append('ruled_tables')
    if len(words) >= 400: tags.append('dense_text')
    if tiny >= 15: tags.append('small_text')
    if labels >= 12 and vectors >= 80: tags.append('dimensioned_diagrams')
    if image_fraction >= .65 and len(words) < 30: tags.append('possible_scan_or_cover')
    if len(images) >= 5: tags.append('many_images')
    score = (min(rotated, 50) * 1.5 + math.log1p(horizontal + vertical) * 8
             + min(len(words), 1500) / 20 + min(tiny, 200) / 5
             + min(labels, 120) / 4 + math.log1p(vectors) * 2)
    if len(words) < 30 and 'possible_scan_or_cover' not in tags: score *= .3
    title = ' '.join(s['text'] for s in spans[:4])[:180]
    return {'word_count': len(words), 'rotated_lines': rotated,
            'horizontal_rules': horizontal, 'vertical_rules': vertical,
            'vector_segments': vectors, 'tiny_spans': tiny,
            'dimension_tokens': labels, 'numeric_tokens': numeric,
            'image_count': len(images), 'image_area_fraction': round(image_fraction, 3),
            'page_rotation': page.rotation, 'title_hint': title,
            'score': round(score, 2), 'tags': tags}


def select_cases(records, per_catalog=3, anchors=None):
    if per_catalog < 1: raise ValueError('per_catalog must be positive')
    anchors = anchors or set()
    found = {(r['source'], r['page']) for r in records}
    if not anchors <= found: raise ValueError('An anchor is missing from the scanned sources')
    grouped = defaultdict(list)
    for record in records: grouped[record['source']].append(record)
    selected = []
    for source, candidates in grouped.items():
        chosen = [r for r in candidates if (source, r['page']) in anchors]
        while len(chosen) < per_catalog:
            remaining = [r for r in candidates if r not in chosen]
            if not remaining: break
            seen = {tag for r in chosen for tag in r['tags']}
            def priority(r):
                novelty = len(set(r['tags']) - seen) * 12
                adjacent = any(abs(r['page'] - c['page']) < 3 for c in chosen)
                return r['score'] + novelty - (35 if adjacent else 0), -r['page']
            chosen.append(max(remaining, key=priority))
        selected.extend(sorted(chosen, key=lambda r: r['page']))
    return selected


def scan_catalogs(sources, output, per_catalog=3, anchors=None, deadline=180):
    """Checkpoint one private record per page; resume only identical source bytes."""
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    paths = [Path(s).resolve() for s in sources]
    if len({p.name for p in paths}) != len(paths):
        raise ValueError('Catalog filenames must be unique in an inventory')
    detector_sha256=hashlib.sha256(inspect.getsource(page_features).encode()).hexdigest()
    checkpoint = output / 'inventory.jsonl'
    previous = {}
    if checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            r = json.loads(line); previous[(r['source_sha256'], r['page'], r.get('detector_sha256'),r.get('pymupdf_version'))] = r
    records = []; started = time.monotonic(); complete = True
    for source in paths:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        with pymupdf.open(source) as doc:
            for number in range(1, len(doc) + 1):
                if time.monotonic() - started >= deadline:
                    complete = False; break
                r = previous.get((digest, number, detector_sha256,pymupdf.VersionBind))
                if r is None:
                    r = {'source': source.name, 'source_sha256': digest,
                         'source_path': str(source), 'page': number,
                         'source_page_count': len(doc), 'detector_sha256':detector_sha256, 'pymupdf_version':pymupdf.VersionBind, **page_features(doc[number - 1])}
                    with checkpoint.open('a', encoding='utf-8') as f:
                        f.write(json.dumps(r, ensure_ascii=False) + '\n')
                r={**r,'source':source.name,'source_path':str(source)}
                records.append(r)
        if not complete: break
    result = {'schema_version': '1.0', 'complete': complete,
              'scanned_pages': len(records), 'catalogs': len(paths), 'detector_sha256':detector_sha256,
              'ranking_method': 'heuristic structural complexity; requires visual curation',
              'pages': records,
              'candidates': select_cases(records, per_catalog, anchors) if complete else []}
    write_json(output / 'inventory.json', result)
    return result


def render_contacts(cases, output):
    """Render originals together for visual curation, preserving PDF content."""
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(list)
    for case in cases: grouped[case['source']].append(case)
    results = []
    for i, (source, records) in enumerate(grouped.items(), 1):
        canvas = pymupdf.open()
        page = canvas.new_page(width=600 * len(records), height=880)
        with pymupdf.open(records[0]['source_path']) as original:
            for column, record in enumerate(records):
                x = column * 600
                page.insert_text((x + 15, 24), f"Page {record['page']} | complexity {record['score']}", fontsize=13)
                page.show_pdf_page(pymupdf.Rect(x + 8, 40, x + 592, 870), original, record['page'] - 1)
        path = output / f'contact-{i:02d}.png'
        page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(path)
        canvas.close()
        results.append({'source': source, 'image': str(path.resolve()),
                        'pages': [r['page'] for r in records]})
    write_json(output / 'contacts.json', results)
    return results
