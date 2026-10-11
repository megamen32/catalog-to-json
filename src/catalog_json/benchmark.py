"""Independent catalog fixture scoring. No model judges and no output-derived gold."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Literal

from pydantic import Field, model_validator
from .schema import Model, PageContent


class Merge(Model):
    column: int = Field(ge=0)
    rows: list[int]


class GoldTable(Model):
    rows: list[list[str | int | float | None]]
    merges: list[Merge] = Field(default_factory=list)

    @model_validator(mode='after')
    def rectangular(self):
        if not self.rows or not self.rows[0] or any(len(r) != len(self.rows[0]) for r in self.rows):
            raise ValueError('Golden tables must be nonempty and rectangular')
        for merge in self.merges:
            if merge.column >= len(self.rows[0]) or not merge.rows or len(set(merge.rows)) != len(merge.rows):
                raise ValueError('Invalid golden merge')
            if any(r < 0 or r >= len(self.rows) for r in merge.rows): raise ValueError('Merge outside golden table')
        return self


class HeaderAssertion(Model):
    table: int = Field(ge=0)
    column: int = Field(ge=0)
    field: Literal['label', 'group', 'unit', 'qualifier']
    expected: str | None
    mode: Literal['exact', 'contains', 'unit'] = 'exact'


class BenchmarkCase(Model):
    schema_version: Literal['1.0'] = '1.0'
    id: str
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    page: int = Field(ge=1)
    provenance: str = Field(min_length=1)
    tables: list[GoldTable]
    headers: list[HeaderAssertion] = Field(default_factory=list)
    figure_labels: list[list[str]] = Field(default_factory=list)
    forbidden_figure_labels: list[list[str]] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_assertions(self):
        if not self.tables: raise ValueError('At least one independently checked table is required')
        for h in self.headers:
            if h.table >= len(self.tables) or h.column >= len(self.tables[h.table].rows[0]):
                raise ValueError('Header assertion outside golden table')
        if any(not labels or any(not label.strip() for label in labels) for labels in self.figure_labels + self.forbidden_figure_labels):
            raise ValueError('Figure assertions require nonempty source-grounded alternatives')
        return self


def literal(value):
    if value is None: return None
    return ' '.join(unicodedata.normalize('NFC', str(value)).split())


def numeric(value):
    text = literal(value)
    if text is not None and re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?', text):
        return Decimal(text.replace(',', '.'))
    return text


def metric(correct, expected):
    return {'correct': correct, 'expected': expected,
            'percent': round(100 * correct / expected, 2) if expected else None}


def label_present(alternatives, content):
    labels = [literal(label) for figure in content.figures for label in figure.labels]
    descriptions = [figure.description for figure in content.figures]
    for label in alternatives:
        if literal(label) in labels: return True
        # Allow prose punctuation/spacing, never H±20 for H±2 or D12 for D1.
        parts = [re.escape(c) for c in label if not c.isspace() and c not in ',.']
        pattern = r'(?<!\w)' + r'[\s,.()]*'.join(parts) + r'(?!\w)'
        if any(re.search(pattern, description) for description in descriptions): return True
    return False


def score_content(case, content):
    differences = []
    literal_correct = numeric_correct = blank_correct = blank_total = merged_correct = merged_total = expected_cells = 0
    header_correct = figure_correct = 0
    structure = {'expected_tables': len(case.tables), 'observed_tables': len(content.tables),
                 'extra_tables': max(0, len(content.tables) - len(case.tables)), 'tables': []}
    for ti, golden in enumerate(case.tables):
        table = content.tables[ti] if ti < len(content.tables) else None
        observed = []
        if table:
            for row in table.rows:
                cells = {c.column_id: c for c in row.cells}
                observed.append([cells[c.id] for c in table.columns])
        structure['tables'].append({'expected_rows': len(golden.rows), 'expected_columns': len(golden.rows[0]),
                                    'observed_rows': len(observed), 'observed_columns': len(table.columns) if table else 0})
        merged = {(ri, merge.column) for merge in golden.merges for ri in merge.rows}
        for ri, row in enumerate(golden.rows):
            for ci, want in enumerate(row):
                expected_cells += 1
                cell = observed[ri][ci] if ri < len(observed) and ci < len(observed[ri]) else None
                state = 'blank' if want is None else 'value'
                exact = bool(cell and cell.state == state and literal(cell.value) == literal(want))
                equivalent = bool(cell and cell.state == state and numeric(cell.value) == numeric(want))
                literal_correct += exact; numeric_correct += equivalent
                if want is None: blank_total += 1; blank_correct += exact
                if (ri, ci) in merged: merged_total += 1; merged_correct += exact
                if not exact:
                    differences.append({'category': 'cell', 'table': ti, 'row': ri, 'column': ci,
                                        'expected': want, 'expected_state': state,
                                        'observed': cell.value if cell else None,
                                        'observed_state': cell.state if cell else 'missing',
                                        'numeric_equivalent': equivalent})
    for assertion in case.headers:
        column = content.tables[assertion.table].columns[assertion.column] if assertion.table < len(content.tables) and assertion.column < len(content.tables[assertion.table].columns) else None
        actual = getattr(column, assertion.field) if column else None
        passed = column is not None and literal(actual) == literal(assertion.expected)
        if column and assertion.mode == 'contains' and assertion.expected is not None:
            passed = literal(assertion.expected).casefold() in literal(actual or '').casefold()
        if column and assertion.mode == 'unit' and assertion.expected:
            unit = assertion.expected.replace('•', '·')
            explicit = (actual or '').replace('•', '·')
            combined = ' '.join(x for x in (column.group, column.label) if x).replace('•', '·')
            # An explicit conflicting unit must not be rescued by a unit in prose.
            passed = explicit == unit if explicit else bool(re.search(r'(?<!\w)' + re.escape(unit) + r'(?!\w)', combined))
        header_correct += passed
        if not passed: differences.append({'category': 'header', **assertion.model_dump(), 'observed': actual})
    for alternatives in case.figure_labels:
        passed = label_present(alternatives, content); figure_correct += passed
        if not passed: differences.append({'category': 'figure_label', 'expected_alternatives': alternatives})
    # Check declared labels, not prose that may mention a label's absence.
    declared = {literal(label) for figure in content.figures for label in figure.labels}
    forbidden_absent = 0
    for alternatives in case.forbidden_figure_labels:
        found = sorted(declared.intersection(literal(label) for label in alternatives))
        forbidden_absent += not found
        if found: differences.append({'category': 'invented_figure_label', 'source_absent_alternatives': alternatives, 'observed': found})
    metrics = {'cells_literal': metric(literal_correct, expected_cells),
               'cells_numeric_equivalent': metric(numeric_correct, expected_cells),
               'blank_cells': metric(blank_correct, blank_total),
               'merged_cells': metric(merged_correct, merged_total),
               'header_assertions': metric(header_correct, len(case.headers)),
               'figure_labels': metric(figure_correct, len(case.figure_labels)),
               'forbidden_label_absence': metric(forbidden_absent, len(case.forbidden_figure_labels))}
    shape_ok = structure['expected_tables'] == structure['observed_tables'] and all(t['expected_rows'] == t['observed_rows'] and t['expected_columns'] == t['observed_columns'] for t in structure['tables'])
    return {'schema_version': '1.0', 'case_id': case.id, 'metrics': metrics, 'structure': structure,
            'all_verified_checks_passed': shape_ok and not differences,
            'coverage': {'full_page_ground_truth': False, 'text_blocks_scored': False,
                         'diagram_relationships_scored': False,
                         'header_assertions': len(case.headers), 'figure_label_assertions': len(case.figure_labels),
                         'forbidden_declared_label_assertions': len(case.forbidden_figure_labels),
                         'all_invented_labels_scored': False},
            'differences': differences}


def score_file(fixture, candidate):
    fixture = Path(fixture); candidate = Path(candidate)
    case = BenchmarkCase.model_validate_json(fixture.read_text())
    data = json.loads(candidate.read_text())
    binding = 'caller-selected plain page artifact'
    if 'pages' in data:
        if data.get('source', {}).get('sha256') != case.source_sha256: raise ValueError('Candidate belongs to a different source PDF')
        pages = [p for p in data['pages'] if p['pdf_page'] == case.page]
        if len(pages) != 1: raise ValueError('Candidate does not uniquely contain the fixture page')
        data = pages[0]['content']; binding = 'source hash and physical page verified'
    result = score_content(case, PageContent.model_validate(data))
    result.update(fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                  candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                  source_binding=binding,grader_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return result


async def extract_native(source, page, output, config, model, timeout=300):
    """Fresh first-pass arm. The fixture/grader is deliberately absent from its inputs."""
    import importlib.metadata
    import subprocess
    import time
    import pymupdf
    from .agents import AgentPair
    from .tools import write_json
    source = Path(source).resolve(); output = Path(output).resolve()
    if output.exists() and any(output.iterdir()): raise ValueError('Benchmark run output must be fresh; choose a new repeat directory')
    with pymupdf.open(source) as doc:
        if not 1 <= page <= len(doc): raise ValueError('Benchmark page is out of range')
    output.mkdir(parents=True, exist_ok=True)
    package_root = Path(__file__).resolve().parents[2]
    revision = None
    if (package_root / '.git').exists():
        revision = subprocess.check_output(['git', '-C', str(package_root), 'rev-parse', 'HEAD'], text=True).strip()
    started = time.monotonic()
    agents = AgentPair(Path(config), model, model, timeout=timeout)
    receipt = {'schema_version': '1.0', 'project': 'catalog-to-json', 'project_revision': revision,
               'package_version': importlib.metadata.version('catalog-to-json'),
               'contract_sha256': agents.contract_digest, 'stage': 'first_pass', 'model': model,
               'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'physical_page': page,
               'timeout_seconds': timeout, 'tokens': None, 'cost': None,
               'usage_note': 'Not reported by this adapter; never inferred from elapsed time.'}
    try:
        content = await agents.run('extractor', source, output, page, 0)
        path = output / f'page-{page:04d}' / 'candidate-0.json'
        receipt.update(status='completed', candidate=str(path), candidate_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    except Exception as exc:
        receipt.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    receipt['elapsed_seconds'] = round(time.monotonic() - started, 3)
    write_json(output / 'run.json', receipt)
    return receipt
