"""Source-preserving adapters shared by independently executed native parsers."""
from .adapter import page_base, matrix_table


def rectangular(headers, rows):
    width = max([len(headers)] + [len(row) for row in rows])
    return headers + [''] * (width - len(headers)), [row + [None] * (width - len(row)) for row in rows]


def html_tables(html):
    """Expand only reported HTML spans. Holes remain unknown; empty td is blank."""
    from bs4 import BeautifulSoup
    result = []
    for node in BeautifulSoup(html, 'html.parser').find_all('table'):
        native_rows = [r for r in node.find_all('tr') if r.find_parent('table') is node]
        cells = {}
        flags = []
        for ri, row in enumerate(native_rows):
            ci = 0
            items = row.find_all(['td', 'th'], recursive=False)
            flags.append(any(c.name == 'th' for c in items))
            for cell in items:
                while (ri, ci) in cells: ci += 1
                rs, cs = int(cell.get('rowspan', 1)), int(cell.get('colspan', 1))
                if not 1 <= rs <= 1000 or not 1 <= cs <= 1000:
                    raise ValueError('Invalid native HTML span')
                value = cell.get_text(' ', strip=True)
                for rr in range(ri, ri + rs):
                    for cc in range(ci, ci + cs):
                        if (rr, cc) in cells: raise ValueError('Overlapping native HTML spans')
                        cells[rr, cc] = value
                ci += cs
        if not cells: continue
        height = max(r for r, _ in cells) + 1
        width = max(c for _, c in cells) + 1
        first_body = 0
        while first_body < len(flags) and flags[first_body]: first_body += 1
        if not first_body: first_body = 1
        headers, groups = [], []
        for ci in range(width):
            vals = list(dict.fromkeys(cells.get((ri, ci), '') for ri in range(first_body)))
            headers.append(vals[-1]); groups.append(' '.join(vals[:-1]) or None)
        rows = [[cells.get((ri, ci)) for ci in range(width)] for ri in range(first_body, height)]
        result.append(matrix_table(f't{len(result)}', headers, rows, groups))
    return result


def from_liteparse(raw):
    out = page_base('LiteParse spatial page')
    for page in raw['pages']:
        if page.get('text'): out['text_blocks'].append({'kind': 'paragraph', 'text': page['text']})
        for block in page.get('blocks') or []:
            if block['kind'] != 'table': continue
            def value(cell):
                box = cell.get('bbox')
                if not box or box.get('width', 0) <= 0 or box.get('height', 0) <= 0:
                    return None
                return cell.get('text')
            heads = [c.get('text', '') for c in block.get('header') or []]
            rows = [[value(c) for c in row] for row in block.get('rows') or []]
            if not heads and rows: heads, rows = rows[0], rows[1:]
            heads, rows = rectangular(heads, rows)
            if heads: out['tables'].append(matrix_table(f't{len(out["tables"])}', heads, rows))
    out['source_notes'].append('Native layout blocks only. Padding/zero-area cell boxes are unknown; no inferred span filling. Coordinates and rotation remain in raw JSON.')
    return out


def from_matrices(raw, title):
    out = page_base(title)
    for table in raw['tables']:
        rows = table['data']
        if not rows: continue
        heads, groups = table.get('headers'), table.get('groups')
        if heads is None: heads, rows = rows[0], rows[1:]
        heads, rows = rectangular(heads, rows)
        if heads: out['tables'].append(matrix_table(f't{len(out["tables"])}', heads, rows, groups))
    out['source_notes'].append('Native matrix output; first row is an explicit header convention when roles are absent. Missing cells stay unknown. Geometry, spans and formatter transformations remain in raw JSON.')
    return out


def from_html_blocks(raw, title):
    out = page_base(title)
    def visit(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ('pred_html', 'table_html') and isinstance(v, str):
                    out['tables'].extend(html_tables(v))
                elif value.get('type') == 'table_body' and k == 'content' and isinstance(v, str):
                    out['tables'].extend(html_tables(v))
                else: visit(v)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(raw)
    for i, table in enumerate(out['tables']):table['id'] = f't{i}';table['title'] = f't{i}'
    out['source_notes'].append('Only parser-emitted HTML table geometry is expanded; absent cells are unknown. No benchmark/source-derived repairs. Caption and figure evidence remains in raw JSON.')
    return out
