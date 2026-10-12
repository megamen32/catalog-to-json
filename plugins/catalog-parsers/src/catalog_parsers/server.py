"""Agent Plugin 1.0 MCP surface, scoped to source/page when invoked by an extractor."""
import argparse
import hashlib
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .parser import parse,available

ARTIFACT_RESPONSE_BYTES=12000  # Below FastAgent 0.10.43's 16000-byte model-history cap.


def artifact_chunk(text,offset,length):
    """Bound the serialized response, not character count; never skip trimmed text."""
    end=min(len(text),offset+length)
    def payload(stop):
        return {'text':text[offset:stop],'total_characters':len(text),'next_offset':stop}
    low=min(offset,len(text));high=end
    while low<high:
        middle=(low+high+1)//2
        # ASCII escaping is a conservative bound for either MCP JSON serializer.
        size=len(json.dumps(payload(middle),ensure_ascii=True,indent=2).encode('utf-8'))
        if size<=ARTIFACT_RESPONSE_BYTES:low=middle
        else:high=middle-1
    return payload(low)


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
        """Parse one source page and return table inventory/headers, NOT body cell values. After success read_parser_artifact(kind="canonical") supplies rows; read kind="raw" for merge/geometry evidence. Source review remains required."""
        selected=Path(source or source_path).resolve();number=page or physical_page
        if source and source_path and Path(source_path).resolve()!=Path(source).resolve():raise ValueError('Source differs from this MCP session')
        if page and physical_page and physical_page!=page:raise ValueError('Page differs from this MCP session')
        if not selected.is_file() or not number:raise ValueError('Provide source PDF and physical page')
        versions=available();from .dispatch import executors
        contract=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest()
        identity={'contract':contract,'executor':executors().get(backend),'source':hashlib.sha256(selected.read_bytes()).hexdigest(),'page':number,'backend':backend,'version':versions.get(backend)}
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();output=root/key
        r=parse(selected,number,backend,output,resume=output.exists())
        if r['status']!='completed':return {'receipt':r,'artifact_id':key,'instruction':'Native conversion/adaptation failed. Retained raw evidence may be read with kind=raw; verify the original image or explicitly choose another backend.'}
        candidate=json.loads((output/'candidate.json').read_text())
        return {'receipt':r,'tables':[{'id':t['id'],'rows':len(t['rows']),'columns':len(t['columns']),'headers':t['columns']} for t in candidate['tables']],
                'artifact_id':key,'canonical_path':str(output/'candidate.json'),'raw_path':str(output/'raw.json'),
                'instruction':'This response has inventory and headers only, not body cells. Read artifact_id with read_parser_artifact(kind="canonical"), continuing by next_offset until every relevant row is read. For blanks/merges also inspect kind="raw" spans. Compare actual rows, parameter/unit/condition paths and span ownership with original images. Never infer a blank from missing inventory data or split ambiguous combined fields by guess.'}

    @mcp.tool()
    def read_parser_artifact(artifact_id:str,kind:str='canonical',offset:int=0,length:int=16000)->dict:
        """Read actual canonical body rows or raw geometry/spans in byte-bounded chunks. length is a maximum character request; replies can be shorter to avoid SDK truncation. Always continue by returned next_offset until needed rows are covered; retain original-image verification."""
        if len(artifact_id)!=64 or any(c not in '0123456789abcdef' for c in artifact_id):raise ValueError('Invalid artifact identity')
        if kind not in ['canonical','raw','receipt'] or offset<0 or not 1<=length<=24000:raise ValueError('Invalid chunk selection')
        name={'canonical':'candidate.json','raw':'raw.json','receipt':'receipt.json'}[kind]
        directory=root/artifact_id
        receipt=json.loads((directory/'receipt.json').read_text())
        if source and receipt.get('source_sha256')!=hashlib.sha256(Path(source).read_bytes()).hexdigest():raise ValueError('Artifact belongs to another source')
        if page and receipt.get('physical_page')!=page:raise ValueError('Artifact belongs to another page')
        if kind=='raw' and not (directory/name).exists():name=receipt.get('native_raw_artifact','native-raw.json')
        if name not in ('candidate.json','raw.json','receipt.json','native-raw.json'):raise ValueError('Invalid retained artifact filename')
        path=directory/name
        expected=receipt.get({'candidate.json':'candidate_sha256','raw.json':'raw_sha256','native-raw.json':'native_raw_sha256'}.get(name,''))
        if kind!='receipt' and (not expected or hashlib.sha256(path.read_bytes()).hexdigest()!=expected):raise ValueError('Retained artifact digest mismatch')
        return artifact_chunk(path.read_text(),offset,length)
    return mcp


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--page',type=int);p.add_argument('--cache-root',type=Path)
    a=p.parse_args();build_server(a.source,a.page,a.cache_root).run(transport='stdio')
