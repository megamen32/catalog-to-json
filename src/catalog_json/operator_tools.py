"""Project operator access to the same PDF evidence tools used by FastAgent.

This adapter exposes original sources, never page acceptance or voter identity.
It runs as one project-local GPTAdmin child, with no provider/model calls.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import threading

from mcp.server.mcpserver import MCPServer
from .tools import CatalogTools
from .reconciliation.consensus import load_sources
from .reconciliation.source_layout import SourceLayout


class OperatorTools:
    def __init__(self, sources, output, *, disk_bytes=256 * 1024**2):
        self.sources_path = Path(sources).resolve()
        self.sources = load_sources(self.sources_path)
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.disk_bytes = disk_bytes
        self.contexts = {}
        self.lock = threading.Lock()
        # An explicit original-page whitelist; these are not adjudication cases.
        pack = {'schema_version': 'catalogue-discrepancy-pack/1',
                'pack_id': 'operator-source-inspection', 'cases': [
                    {'case_id': digest, 'kind': 'source-inspection',
                     'source_sha256': digest,
                     'physical_pages': list(range(1, source['page_count'] + 1)),
                     'ours': [], 'oleg': []}
                    for digest, source in self.sources.items()]}
        path = self.output / 'source-inspection-pack.json'
        path.write_text(json.dumps(pack))
        self.geometry = SourceLayout(pack_path=path, sources_path=self.sources_path)

    def run(self, digest, page, action):
        with self.lock:
            if digest not in self.sources or type(page) is not int or not 1 <= page <= self.sources[digest]['page_count']:
                raise ValueError('Choose a source and physical page from list_catalogs')
            self.geometry._unchanged_sources()
            used = sum(p.stat().st_size for p in self.output.rglob('*') if p.is_file())
            # Reserve one bounded render/result before starting another operation.
            if used + 16 * 1024**2 > self.disk_bytes:
                raise ValueError('Operator scratch budget reached; retained source evidence was not deleted')
            if digest not in self.contexts:
                self.contexts[digest] = CatalogTools(self.sources[digest]['path'], self.output / digest,
                                                    role='operator', model='native operator; no model call')
            try:
                return action(self.contexts[digest])
            finally:
                self.geometry._unchanged_sources()


def server(context):
    mcp = MCPServer('catalogue-source-tools')

    @mcp.tool()
    def list_catalogs() -> list[dict]:
        """List verified original PDFs and their one-based physical page counts."""
        return [{'source_sha256': k, 'filename': Path(v['path']).name, 'page_count': v['page_count']}
                for k, v in context.sources.items()]

    @mcp.tool(structured_output=False)
    def view_page(source_sha256: str, page: int):
        """See the original physical PDF page. No inferred or extracted overlay."""
        return context.run(source_sha256, page, lambda c: c.render(page))

    @mcp.tool(structured_output=False)
    def view_region(source_sha256: str, page: int, box: list[float], rotation: int = 0):
        """Magnify an original region; box=[left,top,right,bottom] in0..1, rotation0/90/180/270. Inspect fine codes and full merged-cell boundaries, not just a model's text band."""
        return context.run(source_sha256, page, lambda c: c.region(page, box, rotation))

    @mcp.tool()
    def inspect_layout(source_sha256: str, page: int, bbox: list[float] | None = None) -> dict:
        """Exact native words and stroked vector dividers in a crop. A limit returns NO partial evidence and requests smaller regions. Geometry alone does not infer ownership or a verdict."""
        return context.run(source_sha256, page, lambda c: context.geometry.inspect_layout(source_sha256, page, bbox))

    @mcp.tool()
    def read_source_layout(source_sha256: str, page: int, box: list[float] | None = None) -> dict:
        """Read original words, positions and short-code Unicode identities; scanned/outlined labels still require the original image."""
        return context.run(source_sha256, page, lambda c: c.source_payload(page, 'layout', c.layout(page, box)))

    @mcp.tool()
    def read_source_table(source_sha256: str, page: int, box: list[float]) -> dict:
        """Direct native table geometry with expanded rows and physical merge spans. Inspect headers and full source boundaries before assigning values."""
        from .grid import table_grids
        import pymupdf
        def read(c):
            with pymupdf.open(c.source) as doc:
                data = table_grids(doc[page-1], box)
            c.log(page, 'read_source_table', box=box)
            return c.source_payload(page, 'table', data)
        return context.run(source_sha256, page, read)

    @mcp.tool()
    def read_source_artifact(source_sha256: str, page: int, artifact_id: str, offset: int = 0, length: int = 16000) -> dict:
        """Read complete retained evidence in chunks; follow next_offset to total_characters. Offsets are characters, no silent truncation."""
        return context.run(source_sha256, page, lambda c: c.source_artifact(page, artifact_id, offset, length))

    @mcp.tool()
    def inspect_drawing_geometry(source_sha256: str, page: int, box: list[float], offset: int = 0, limit: int = 20, path_kind: str = 'stroke') -> dict:
        """Bounded native drawing path index. Fill-only glyph outlines are excluded by default; all/fill remain available. Check visible contours and both dimension endpoints."""
        return context.run(source_sha256, page, lambda c: c.drawing_geometry(page, box, offset, limit, path_kind))

    @mcp.tool()
    def read_drawing_paths(source_sha256: str, page: int, box: list[float], path_ids: list[str]) -> dict:
        """Exact native endpoints and styles for1..40 selected paths in the same source crop; large results use retained artifacts."""
        return context.run(source_sha256, page, lambda c: c.drawing_paths(page, box, path_ids))

    @mcp.tool()
    def trace_dimension_candidates(source_sha256: str, page: int, box: list[float], label: str) -> dict:
        """Heuristic nearby shafts/tips for one literal dimension. Not certified arrows or ownership: verify using view_region and exact paths."""
        return context.run(source_sha256, page, lambda c: c.dimension_candidates(page, box, label))

    @mcp.tool()
    def extract_direct(source_sha256: str, page: int) -> dict:
        """Run the existing local AnyDoc path on one page. It supplies evidence, never an accepted catalogue or independent review; no provider calls."""
        return context.run(source_sha256, page, lambda c: c.source_payload(page, 'direct', c.direct(page)))

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    server(OperatorTools(args.sources, args.output)).run()


if __name__ == '__main__':
    main()
