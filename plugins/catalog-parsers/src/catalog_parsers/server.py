"""Agent Plugin 1.0 MCP surface, scoped to source/page when invoked by an extractor."""
import argparse
import hashlib
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .parser import parse,available


def build_server(source=None,page=None,cache_root=None):
    mcp=FastMCP('catalog-parsers')
    root=Path(cache_root or '.catalog-parser-cache').resolve()

    @mcp.tool()
    def parser_capabilities()->dict:
        """List installed backend versions; no parser weights load until conversion."""
        return {'backends':available(),'outputs':['raw JSON','unreviewed canonical page','version/time/hash receipt'],
                'scoped_source':str(source) if source else None,'scoped_physical_page':page}

    @mcp.tool()
    def inspect_pdf_page(backend:str,source_path:str='',physical_page:int=0)->dict:
        """Parse one source page with Docling/PyMuPDF4LLM. Results are evidence requiring source review."""
        selected=Path(source or source_path).resolve();number=page or physical_page
        if source and source_path and Path(source_path).resolve()!=Path(source).resolve():raise ValueError('Source differs from this MCP session')
        if page and physical_page and physical_page!=page:raise ValueError('Page differs from this MCP session')
        if not selected.is_file() or not number:raise ValueError('Provide source PDF and physical page')
        versions=available();identity={'source':hashlib.sha256(selected.read_bytes()).hexdigest(),'page':number,'backend':backend,'version':versions.get(backend)}
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();output=root/key
        r=parse(selected,number,backend,output,resume=output.exists())
        if r['status']!='completed':return r
        candidate=json.loads((output/'candidate.json').read_text())
        return {'receipt':r,'tables':[{'id':t['id'],'rows':len(t['rows']),'columns':len(t['columns']),'headers':t['columns']} for t in candidate['tables']],
                'artifact_id':key,'canonical_path':str(output/'candidate.json'),'raw_path':str(output/'raw.json'),
                'instruction':'Compare all fields/spans against original images. Do not split ambiguous combined fields or replace source typos using guessed meaning.'}

    @mcp.tool()
    def read_parser_artifact(artifact_id:str,kind:str='canonical',offset:int=0,length:int=16000)->dict:
        """Read a bounded chunk of this session's retained parser JSON, without a model transcript."""
        if len(artifact_id)!=64 or any(c not in '0123456789abcdef' for c in artifact_id):raise ValueError('Invalid artifact identity')
        if kind not in ['canonical','raw','receipt'] or offset<0 or not 1<=length<=24000:raise ValueError('Invalid chunk selection')
        name={'canonical':'candidate.json','raw':'raw.json','receipt':'receipt.json'}[kind]
        text=(root/artifact_id/name).read_text();return {'text':text[offset:offset+length],'total_characters':len(text),'next_offset':min(len(text),offset+length)}
    return mcp


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--page',type=int);p.add_argument('--cache-root',type=Path)
    a=p.parse_args();build_server(a.source,a.page,a.cache_root).run(transport='stdio')
