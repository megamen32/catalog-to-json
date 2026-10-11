"""Local, per-role catalog MCP tools. Documents and output stay outside the plugin."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import pymupdf
from pydantic import ValidationError
from mcp.server.mcpserver import MCPServer, Image
from .schema import PageContent, Review, Issue, CHECKS
from .direct import inspect_page
from .audit import compare_source

SKILLS = Path(__file__).parent / 'skills'
if not SKILLS.exists():
    SKILLS = Path(__file__).resolve().parents[2] / 'skills'


def write_json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    pending=path.with_suffix(path.suffix+'.pending')
    pending.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    pending.replace(path)


class CatalogTools:
    def __init__(self, source=None, output=None, role='extractor', page=None, attempt=0):
        self.role=role;self.page=page;self.attempt=attempt;self.seen={};self.source=None;self.output=None
        if source and output:self.open(source,output)

    def open(self,source,output):
        source=Path(source).resolve();output=Path(output).resolve()
        if output==source or source.parent==output:raise ValueError('Choose a separate output directory')
        with pymupdf.open(source) as doc:count=len(doc)
        self.source=source;self.output=output;output.mkdir(parents=True,exist_ok=True);self.seen={}
        return {'filename':source.name,'page_count':count,'role':self.role,'output':str(output)}

    def work(self,page):
        if not self.source:raise ValueError('Call open_catalog first')
        if self.page is not None and page!=self.page:raise ValueError('This worker is assigned a different page')
        with pymupdf.open(self.source) as doc:
            if page<1 or page>len(doc):raise ValueError('Page out of range')
        work=self.output/f'page-{page:04d}';work.mkdir(exist_ok=True);return work

    def log(self,page,tool,**metadata):
        self.seen.setdefault(page,set()).add(tool)
        with (self.work(page)/'tools.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'time':time.time(),'role':self.role,'attempt':self.attempt,'page':page,'tool':tool,**metadata},ensure_ascii=False)+'\n')

    def render(self,page,box=None,rotation=0):
        work=self.work(page)
        if box is not None and (len(box)!=4 or not all(0<=v<=1 for v in box) or box[0]>=box[2] or box[1]>=box[3]):raise ValueError('Box must be [x0,y0,x1,y1] normalized to 0..1')
        if rotation not in (0,90,180,270):raise ValueError('Rotation must be 0,90,180,270')
        with pymupdf.open(self.source) as doc:
            p=doc[page-1]
            clip=None if box is None else pymupdf.Rect(box[0]*p.rect.width,box[1]*p.rect.height,box[2]*p.rect.width,box[3]*p.rect.height)
            # Images remain bounded even with malformed or very large PDF media boxes.
            rect=clip or p.rect;scale=min(3.5 if box else 2.5,2400/max(rect.width,rect.height))
            pix=p.get_pixmap(matrix=pymupdf.Matrix(scale,scale).prerotate(rotation),clip=clip)
            data=pix.tobytes('png')
        name='source.png' if box is None else 'region-'+hashlib.sha256(json.dumps([box,rotation]).encode()).hexdigest()[:12]+'.png'
        (work/name).write_bytes(data)
        self.log(page,'view_page' if box is None else 'view_region',box=box,rotation=rotation,image=name)
        return Image(data=data,format='png')

    def direct(self,page):
        work=self.work(page)
        with pymupdf.open(self.source) as doc:
            single=pymupdf.open();single.insert_pdf(doc,from_page=page-1,to_page=page-1)
            pdf_bytes=single.tobytes();single.close()
            candidate,hint,reasons=inspect_page(doc[page-1],pdf_bytes)
        (work/'source.pdf').write_bytes(pdf_bytes);(work/'anydoc.md').write_text(hint,encoding='utf-8')
        data={'candidate':candidate.model_dump() if candidate else None,'routing_reasons':reasons,'markdown_hint':hint}
        write_json(work/'direct.json',data);self.log(page,'extract_direct',routing_reasons=reasons)
        return data

    def read(self,page,kind):
        if self.role=='reviewer' and kind=='page' and 'save_source_observation' not in self.seen.get(page,set()):
            raise ValueError('First independently inspect the original and save_source_observation BEFORE seeing the candidate')
        filename=f'candidate-{self.attempt}.json' if kind=='page' else f'review-{self.attempt}.json'
        path=self.work(page)/filename
        if not path.exists():
            alternatives=sorted(self.work(page).glob('candidate-*.json' if kind=='page' else 'review-*.json'))
            if not alternatives:raise ValueError(f'No {kind} artifact saved')
            path=alternatives[-1]
        self.log(page,'read_page_json' if kind=='page' else 'read_review',file=path.name)
        data=json.loads(path.read_text())
        if self.role=='reviewer' and kind=='page':
            observed=PageContent.model_validate_json((self.work(page)/f'source-observation-{self.attempt}.json').read_text())
            return {'candidate':data,'independent_comparison':compare_source(observed,PageContent.model_validate(data))}
        return data

    def save(self,page,json_text,kind):
        work=self.work(page)
        expected='extractor' if kind=='page' else 'reviewer'
        if self.role!=expected:return {'saved':False,'error':f'{self.role} cannot write {kind} artifacts'}
        required={'view_page','extract_direct'} if kind=='page' else {'view_page'} if kind=='observation' else {'view_page','read_page_json','save_source_observation'}
        with pymupdf.open(self.source) as doc:
            rotated=any(abs(line.get('dir',(1,0))[1])>.05 for block in doc[page-1].get_text('dict')['blocks'] for line in block.get('lines',[]))
        if rotated:required.add('view_region')
        missing=required-self.seen.get(page,set())
        if missing:return {'saved':False,'error':'Inspect the actual source before saving','missing_tools':sorted(missing)}
        if kind=='observation' and 'read_page_json' in self.seen.get(page,set()):return {'saved':False,'error':'Source observations are frozen after candidate disclosure; start a fresh review to reinspect'}
        try:
            model=(PageContent if kind in ('page','observation') else Review).model_validate_json(json_text)
            if kind=='review':
                disclosed=self.read(page,'page')
                if model.verdict=='pass' and disclosed['independent_comparison']:
                    return {'saved':False,'error':'Independent source observations contradict the claimed pass. Report ALL differences and any additional findings.', 'differences':disclosed['independent_comparison']}
            if kind=='review' and model.verdict!='pass':
                existing={issue.path for issue in model.issues}
                for diff in disclosed['independent_comparison']:
                    if diff['path'] not in existing:
                        model.issues.append(Issue(severity='error',path=diff['path'],message='Независимая запись оригинала: '+json.dumps(diff['source_observation'],ensure_ascii=False)+'; в кандидате: '+json.dumps(diff['candidate'],ensure_ascii=False)))
            if kind=='review' and model.verdict=='pass' and not model.accepts(PageContent.model_validate(disclosed['candidate'])):
                return {'saved':False,'error':'Claimed pass contradicts checks, issues, counts or candidate uncertainties; submit revise/uncertain or complete the review'}
        except ValidationError as exc:
            return {'saved':False,'validation_errors':json.loads(exc.json(include_input=False,include_url=False))}
        filename=f'candidate-{self.attempt}.json' if kind=='page' else f'source-observation-{self.attempt}.json' if kind=='observation' else f'review-{self.attempt}.json'
        write_json(work/filename,model.model_dump())
        self.log(page,'save_page_json' if kind=='page' else 'save_source_observation' if kind=='observation' else 'save_review',file=filename,sha256=hashlib.sha256((work/filename).read_bytes()).hexdigest())
        return {'saved':True,'file':str(work/filename)}

    def section(self,page,section,index,json_text):
        if self.role!='extractor':return {'saved':False,'error':'Only extractor writes page sections'}
        if section not in ('text_blocks','tables','figures'):raise ValueError('Unknown section')
        if index<0 or index>999:raise ValueError('Index out of range')
        from .schema import TextBlock,Table,Figure
        try:model={'text_blocks':TextBlock,'tables':Table,'figures':Figure}[section].model_validate_json(json_text)
        except ValidationError as exc:return {'saved':False,'validation_errors':json.loads(exc.json(include_input=False,include_url=False))}
        path=self.work(page)/f'sections-{self.attempt}'/section/f'{index:04d}.json'
        write_json(path,model.model_dump());self.log(page,'save_section',section=section,index=index)
        return {'saved':True,'section':section,'index':index}

    def finalize(self,page,title,printed_page=None,source_notes=None,uncertainties=None):
        data={'title':title,'printed_page':printed_page,'source_notes':source_notes or [],'uncertainties':uncertainties or []}
        for section in ('text_blocks','tables','figures'):
            paths=sorted((self.work(page)/f'sections-{self.attempt}'/section).glob('*.json'))
            indexes=[int(p.stem) for p in paths]
            if indexes!=list(range(len(indexes))):return {'saved':False,'error':f'{section} indices must be contiguous starting at 0'}
            data[section]=[json.loads(p.read_text()) for p in paths]
        return self.save(page,json.dumps(data,ensure_ascii=False),'page')


def server(context):
    mcp=MCPServer('catalog-tools',version='1.0.0',log_level='ERROR')
    @mcp.tool()
    def open_catalog(source_path: str,output_directory: str) -> dict:
        """Open a user-specified local PDF and separate output folder. Not needed in an assigned CLI job."""
        if context.source:raise ValueError('Already assigned; start another job to change source')
        return context.open(source_path,output_directory)
    @mcp.tool()
    def load_skill() -> str:
        """Read the registered native skill for this worker role before extracting/reviewing."""
        if context.page is not None:context.log(context.page,'load_skill')
        return (SKILLS/f'catalog-{context.role.replace("extractor","extract").replace("reviewer","review")}'/'SKILL.md').read_text()
    @mcp.tool()
    def get_json_schema(kind: str='page') -> dict:
        """Get the exact saved-file schema. Chat responses need not be JSON. kind: page or review."""
        if kind not in ('page','review'):raise ValueError('kind must be page or review')
        return {'schema':(PageContent if kind=='page' else Review).model_json_schema(),'required_review_checks':sorted(CHECKS)}
    @mcp.tool(structured_output=False)
    def view_page(page: int):
        """See the original PDF page as an image. Physical page number is one-based."""
        return context.render(page)
    @mcp.tool(structured_output=False)
    def view_region(page: int,box: list[float],rotation: int=0):
        """Zoom a chosen source region. box=[left,top,right,bottom], fractions 0..1. rotation clockwise degrees 0/90/180/270."""
        return context.render(page,box,rotation)
    @mcp.tool()
    def extract_direct(page: int) -> dict:
        """Run local AnyDoc; return structured candidate, fallible text and reasons for Vision. No credentials or cloud upload."""
        return context.direct(page)
    @mcp.tool()
    def read_page_json(page: int) -> dict:
        """Read saved candidate for independent review or source-grounded repair."""
        return context.read(page,'page')
    @mcp.tool()
    def read_review(page: int) -> dict:
        """Read the latest reviewer findings before repairing the candidate."""
        return context.read(page,'review')
    if context.role=='extractor':
        @mcp.tool()
        def save_page_json(page: int,json_text: str) -> dict:
            """Validate and atomically save a complete page JSON. Errors are returned to the agent for correction."""
            return context.save(page,json_text,'page')
        @mcp.tool()
        def save_section(page: int,section: str,index: int,json_text: str) -> dict:
            """Validate/save ONE table, figure or text block; section=tables/figures/text_blocks. index starts at 0. Useful for long pages."""
            return context.section(page,section,index,json_text)
        @mcp.tool()
        def finalize_page(page: int,title: str,printed_page: str|None=None,source_notes: list[str]|None=None,uncertainties: list[str]|None=None) -> dict:
            """Assemble saved sections into complete page JSON and validate it. Use same attempt; all indices contiguous."""
            return context.finalize(page,title,printed_page,source_notes,uncertainties)
    else:
        @mcp.tool()
        def save_source_observation(page: int,json_text: str) -> dict:
            """Save independent complete source-page transcription (PageContent schema) BEFORE reading candidate. Frozen after candidate disclosure."""
            return context.save(page,json_text,'observation')
        @mcp.tool()
        def save_review(page: int,json_text: str) -> dict:
            """Save strict source-grounded review. Incomplete or contradictory claimed passes return errors."""
            return context.save(page,json_text,'review')
    return mcp


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--role',choices=['extractor','reviewer'],default='extractor');p.add_argument('--page',type=int);p.add_argument('--attempt',type=int,default=0)
    args=p.parse_args()
    if bool(args.source)!=bool(args.output):p.error('--source and --output must be supplied together')
    server(CatalogTools(args.source,args.output,args.role,args.page,args.attempt)).run()

if __name__=='__main__':main()
