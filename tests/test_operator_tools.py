import asyncio
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from catalog_json.operator_tools import OperatorTools, server


@pytest.fixture
def context(tmp_path):
    pdf = tmp_path / 'source.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=300)
        page.insert_text((40, 60), 'TKP 12')
        page.draw_line((30, 80), (250, 80))
        doc.save(pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    sources = tmp_path / 'sources.json'
    sources.write_text(json.dumps([{'sha256': digest, 'path': str(pdf)}]))
    return OperatorTools(sources, tmp_path / 'operator'), digest, pdf


def test_original_zoom_and_layout_share_source(context):
    tools, digest, _ = context
    image = tools.run(digest, 1, lambda c: c.region(1, [.05, .05, .95, .4]))
    assert image.data.startswith(b'\x89PNG')
    geometry = tools.run(digest, 1, lambda c: tools.geometry.inspect_layout(digest, 1, [.05, .05, .95, .4]))
    assert geometry['complete']
    assert any(w['text'] == 'TKP' for w in geometry['words'])
    assert any(s['orientation'] == 'horizontal' for s in geometry['segments'])


def test_source_identity_and_scratch_budget(context):
    tools, digest, pdf = context
    with pytest.raises(ValueError, match='physical page'):
        tools.run(digest, 2, lambda c: None)
    tools.disk_bytes = 1
    with pytest.raises(ValueError, match='budget'):
        tools.run(digest, 1, lambda c: None)
    pdf.write_bytes(pdf.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='changed'):
        tools.run(digest, 1, lambda c: None)


def test_real_tool_registry_exposes_evidence_without_verdict_writers(context):
    tools, _, _ = context
    registry = asyncio.run(server(tools).list_tools())
    names = {tool.name for tool in registry}
    assert {'view_page', 'view_region', 'inspect_layout', 'read_source_table',
            'read_source_layout', 'read_source_artifact', 'inspect_drawing_geometry',
            'read_drawing_paths', 'trace_dimension_candidates', 'extract_direct', 'list_catalogs'} == names


def test_fine_region_is_a_readable_zoom(context):
    """Focused integration: narrow labels must enlarge, not remain a tiny crop.

    Detected on armature46: repeated 116px crops could not distinguish6/8.
    Expected2s, emergency20s; no model/provider calls.
    """
    import struct
    tools, digest, _ = context
    image = tools.run(digest, 1, lambda c: c.region(1, [.12, .15, .18, .21]))
    width, height = struct.unpack('>II', image.data[16:24])
    assert 900 <= max(width, height) <= 2402
    rotated = tools.run(digest, 1, lambda c: c.region(1, [.12, .15, .18, .21], 90))
    assert rotated.data.startswith(b'\x89PNG')
