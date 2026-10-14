"""Local, per-role catalog MCP tools. Documents and output stay outside the plugin."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import pymupdf
from pydantic import ValidationError
from mcp.server.mcpserver import MCPServer, Image
from mcp.types import TextContent
from .schema import PageContent, Review, Issue, CHECKS
from .direct import inspect_page
from .audit import compare_source,align_tables,independent_software_demonstration
from .observation_quotes import branding_quote_evidence
from .review_consistency import structural_disagreements
from .dimension_review import DimensionReview,dimension_targets,missing_dimension_evidence

SKILLS = Path(__file__).parent / 'skills'
if not SKILLS.exists():
    SKILLS = Path(__file__).resolve().parents[2] / 'skills'


def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def durable_directory(path):
    path=Path(path);missing=[];ancestor=path
    while not ancestor.exists():
        missing.append(ancestor);ancestor=ancestor.parent
    path.mkdir(parents=True,exist_ok=True)
    for created in reversed(missing):sync_directory(created.parent)


def write_json(path, data):
    path=Path(path);durable_directory(path.parent)
    pending=path.with_suffix(path.suffix+'.pending')
    with pending.open('w',encoding='utf-8') as stream:
        stream.write(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        stream.flush();os.fsync(stream.fileno())
    pending.replace(path)
    sync_directory(path.parent)


SOURCE_RESPONSE_BYTES=12000


def source_chunk(text,offset,length):
    if offset<0 or offset>len(text) or length<1:raise ValueError('Invalid source artifact range')
    def payload(stop):return {'text':text[offset:stop],'total_characters':len(text),'next_offset':stop}
    low=offset;high=min(len(text),offset+length)
    while low<high:
        middle=(low+high+1)//2
        if len(json.dumps(payload(middle),ensure_ascii=True,indent=2).encode())<=SOURCE_RESPONSE_BYTES:low=middle
        else:high=middle-1
    return payload(low)


def review_contract():
    return {'schema':Review.model_json_schema(),'required_review_checks':sorted(CHECKS),
            'source_observation_example':{'title':'[actual source title]',
                'page_context':{'kind':'software_demonstration','summary':'[actual demonstrated software function, not example product offers]',
                    'source_evidence':[{'kind':'software_demonstration','box':[.1,.1,.9,.9],'observation':'[actual visible contextual evidence]','transcription':'contextual_summary'}]},
                'printed_page':None,'text_blocks':[],'tables':[],'figures':[],'source_notes':[],'uncertainties':[]},
            'source_observation_instruction':'Это только пример ФОРМЫ для подтверждённой демонстрации ПО. Самостоятельно выберите назначение реальной страницы; не копируйте классификацию, рамки и заглушки. page_context должен быть объектом. Для настоящей таблицы получите get_json_schema(page), заполните все реальные ячейки; blank требует value:null. Для pure software_demonstration сохраняйте tables=[], а не OCR таблицу примера.',
            'example':{'verdict':'uncertain','checks':[{'category':c,'passed':False,'evidence':'Replace with concrete original-image comparison'} for c in sorted(CHECKS)],
                       'context_review':{'page_purpose_verified':False,'summary_meaning_verified':False,'actual_vs_demo_verified':False,'technical_facts_verified':False,'relations_verified':False,'evidence':'Замените независимым обоснованием по оригиналу: назначение страницы, смысл пересказа, реальные данные/демонстрация, технические факты и связи изделия, параметра, единицы, условия и элемента чертежа.'},
                       'issues':[{'severity':'error','path':'replace_with_actual_path','message':'Replace with source-grounded finding'}],
                       'observed_table_count':0,'observed_row_counts':[],'observed_column_counts':[]},
            'instruction':'Это только пример структуры. Укажите фактические числа строк/столбцов в сопоставленном порядке кандидата и конкретные результаты проверки оригинала. Для PASS страницы с page_context нужны все пять true в context_review и независимое смысловое обоснование. Верный пересказ допустим; технические факты и связи проверяются по оригиналу, а не по сходству строк. Legacy без контекста сохраняет одиннадцать обычных checks. Не копируйте текст-заглушку.'}


class CatalogTools:
    def __init__(self, source=None, output=None, role='extractor', page=None, attempt=0,model=None,contract_sha256=None):
        self.model=model;self.contract_sha256=contract_sha256;self.region_evidence={};self.branding_figure_quotes={};self.dimension_reviews={}
        self.role=role;self.page=page;self.attempt=attempt;self.seen={};self.disclosed={};self.latest_zoom={};self.corrections={};self.grids={};self.source_artifacts={};self.region_reads={};self.edit_baselines={};self.invalid_edit_baselines=set();self.source=None;self.output=None
        if source and output:self.open(source,output)

    def open(self,source,output):
        self.dimension_reviews={}
        source=Path(source).resolve();output=Path(output).resolve()
        if output==source or source.parent==output:raise ValueError('Choose a separate output directory')
        with pymupdf.open(source) as doc:count=len(doc)
        durable_directory(output)
        self.source=source;self.source_digest=hashlib.sha256(source.read_bytes()).hexdigest();self.output=output;self.seen={};self.source_artifacts={};self.region_reads={};self.region_evidence={};self.branding_figure_quotes={};self.edit_baselines={};self.invalid_edit_baselines=set();self.grids={};self.disclosed={};self.latest_zoom={};self.corrections={}
        return {'filename':source.name,'page_count':count,'role':self.role,'output':str(output)}

    def work(self,page):
        if not self.source:raise ValueError('Call open_catalog first')
        if self.page is not None and page!=self.page:raise ValueError('This worker is assigned a different page')
        with pymupdf.open(self.source) as doc:
            if page<1 or page>len(doc):raise ValueError('Page out of range')
        work=self.output/f'page-{page:04d}';durable_directory(work);return work

    def log(self,page,tool,**metadata):
        journal=self.work(page)/'tools.jsonl'
        with journal.open('a',encoding='utf-8') as f:
            f.write(json.dumps({'time':time.time(),'role':self.role,'model':self.model,'source_sha256':self.source_digest,'contract_sha256':self.contract_sha256,'attempt':self.attempt,'page':page,'tool':tool,**metadata},ensure_ascii=False)+'\n')
            f.flush();os.fsync(f.fileno())
        sync_directory(journal.parent)
        self.seen.setdefault(page,set()).add(tool)

    def render(self,page,box=None,rotation=0):
        work=self.work(page)
        if box is not None and (len(box)!=4 or not all(0<=v<=1 for v in box) or box[0]>=box[2] or box[1]>=box[3]):raise ValueError('Box must be [x0,y0,x1,y1] normalized to 0..1')
        if rotation not in (0,90,180,270):raise ValueError('Rotation must be 0,90,180,270')
        with pymupdf.open(self.source) as doc:
            p=doc[page-1]
            clip=None if box is None else pymupdf.Rect(box[0]*p.rect.width,box[1]*p.rect.height,box[2]*p.rect.width,box[3]*p.rect.height)
            # Images remain bounded even with malformed or very large PDF media boxes.
            rect=clip or p.rect;scale=min(6 if box else 2.5,2400/max(rect.width,rect.height))
            pix=p.get_pixmap(matrix=pymupdf.Matrix(scale,scale).prerotate(rotation),clip=clip)
            data=pix.tobytes('png')
        name='source.png' if box is None else 'region-'+hashlib.sha256(json.dumps([box,rotation]).encode()).hexdigest()[:12]+'.png'
        (work/name).write_bytes(data)
        if box is not None:
            self.latest_zoom[page]=time.monotonic();self.region_evidence[(page,tuple(box),rotation)]=self.latest_zoom[page]
        self.log(page,'view_page' if box is None else 'view_region',box=box,rotation=rotation,image=name)
        return Image(data=data,format='png')

    def region(self,page,box,rotation=0):
        image=self.render(page,box,rotation)
        key=(page,tuple(box),rotation)
        count=self.region_reads.get(key,0)+1;self.region_reads[key]=count
        if count==1:return image
        self.log(page,'repeat_region',box=box,rotation=rotation,identical_reads=count)
        return [image,TextContent(type='text',text='This exact source region is unchanged and has already been viewed. Another identical crop adds no evidence. Compare the already read rows/headers and save completed sections now; explicitly record remaining uncertainty rather than repeating the same inspection. The image remains available and there is no inspection-count limit.')]

    def source_payload(self,page,kind,data,maximum_bytes=SOURCE_RESPONSE_BYTES):
        text=json.dumps(data,ensure_ascii=False,indent=2)
        if len(json.dumps(data,ensure_ascii=True,indent=2).encode())<=maximum_bytes:return data
        digest=hashlib.sha256(text.encode()).hexdigest()
        self.source_artifacts[(page,digest)]=text
        (self.work(page)/f'source-{kind}-{digest}.json').write_text(text,encoding='utf-8')
        self.log(page,'source_artifact_created',kind=kind,artifact_id=digest,total_characters=len(text))
        return {'paged':True,'kind':kind,'artifact_id':digest,'source_sha256':self.source_digest,'physical_page':page,'total_characters':len(text),'sha256':digest,'instruction':'Full source evidence is retained without truncation. Call read_source_artifact(page, artifact_id, offset=0) and follow next_offset to total_characters; chunks include rows, physical merges and headers. Do not infer values from this inventory.'}

    def source_artifact(self,page,artifact_id,offset=0,length=16000):
        self.work(page)
        key=(page,artifact_id)
        if key not in self.source_artifacts:raise ValueError('Unknown artifact for this source/page/tool context')
        result=source_chunk(self.source_artifacts[key],offset,length)
        self.log(page,'read_source_artifact',artifact_id=artifact_id,offset=offset,next_offset=result['next_offset'])
        return result

    def drawing_geometry(self,page,box,offset=0,limit=20,path_kind='stroke'):
        from .drawing_geometry import drawing_geometry
        if offset<0 or not 1<=limit<=20 or path_kind not in {'stroke','fill','all'}:raise ValueError('Invalid drawing index range/kind')
        self.work(page)
        with pymupdf.open(self.source) as doc:result=drawing_geometry(doc[page-1],box,self.source_digest)
        self.log(page,'inspect_drawing_geometry',box=box,paths=len(result['paths']),words=len(result['words']))
        selected=[p for p in result['paths'] if path_kind=='all' or (p['stroke'] is not None if path_kind=='stroke' else p['fill'] is not None)]
        if offset>len(selected):raise ValueError('Drawing index offset is past the end')
        paths=[{k:p[k] for k in ('id','box','type','line_width_pdf_points','dashes')}|{'item_count':len(p['items'])} for p in selected[offset:offset+limit]]
        return {'physical_page':page,'source_sha256':self.source_digest,'box':box,'pdf_rotation':result['pdf_rotation'],
                'coordinate_system':result['coordinate_system'],'words':self.source_payload(page,'drawing-words',{'words':result['words']},3000),
                'counts':{'all_paths':len(result['paths']),'selected_paths':len(selected),'words':len(result['words']),'small_filled_triangles':len(result['small_filled_triangles'])},
                'path_kind':path_kind,'path_index':paths,'next_offset':min(offset+limit,len(selected)),
                'triangle_path_ids_in_index':[t['path_id'] for t in result['small_filled_triangles'] if t['path_id'] in {p['id'] for p in paths}],
                'instruction':'Index only; read_drawing_paths retrieves literal endpoints for chosen IDs. Default index contains stroked paths, excluding fill-only glyph outlines explicitly; use path_kind=all or fill for those. Follow next_offset through selected_paths as needed. Words may be a paged source artifact. All paths remain available; neither index nor geometry infers ownership.',
                'limits':result['limits']}

    def drawing_paths(self,page,box,path_ids):
        from .drawing_geometry import drawing_geometry
        if not path_ids or len(path_ids)>40 or len(set(path_ids))!=len(path_ids):raise ValueError('Choose 1..40 unique path IDs')
        self.work(page)
        with pymupdf.open(self.source) as doc:result=drawing_geometry(doc[page-1],box,self.source_digest)
        paths={p['id']:p for p in result['paths']}
        if any(identifier not in paths for identifier in path_ids):raise ValueError('Path ID is outside this source region')
        self.log(page,'read_drawing_paths',box=box,path_ids=path_ids)
        return self.source_payload(page,'drawing-paths',{'physical_page':page,'source_sha256':self.source_digest,'box':box,
                                  'coordinate_system':result['coordinate_system'],'paths':[paths[i] for i in path_ids]})

    def dimension_candidates(self,page,box,label):
        from .drawing_geometry import dimension_candidates
        self.work(page)
        with pymupdf.open(self.source) as doc:result=dimension_candidates(doc[page-1],box,label,self.source_digest)
        self.log(page,'trace_dimension_candidates',box=box,label=label,matching_labels=len(result['matching_labels']))
        return self.source_payload(page,'dimension-candidates',result)

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

    def dimension_inventory(self,page):
        candidate=PageContent.model_validate(self.read(page,'page')['candidate'])
        observation_file=self.work(page)/(f'verified-source-observation-{self.attempt}.json' if 'correct_source_observation' in self.seen.get(page,set()) else f'source-observation-{self.attempt}.json')
        observed=PageContent.model_validate_json(observation_file.read_text())
        return {'candidate_targets':dimension_targets(candidate),'source_targets':dimension_targets(observed),'instruction':'Map each independently observed source figure/label to its own candidate figure/label. Moving dimensions only into descriptions does not cover source targets. Inspect each repeated variant/view separately. Coverage is not proof of geometry correctness.'}

    def record_dimension(self,page,json_text):
        if self.role!='reviewer':return {'saved':False,'error':'Only reviewer records dimension evidence'}
        try:record=DimensionReview.model_validate_json(json_text)
        except ValidationError as exc:return {'saved':False,'validation_errors':json.loads(exc.json(include_input=False,include_url=False))}
        disclosed=self.read(page,'page');candidate=PageContent.model_validate(disclosed['candidate'])
        if record.figure_index>=len(candidate.figures):return {'saved':False,'error':'Unknown candidate figure'}
        figure=candidate.figures[record.figure_index]
        if record.label_index>=len(figure.labels):return {'saved':False,'error':'Unknown candidate label'}
        observation_file=self.work(page)/(f'verified-source-observation-{self.attempt}.json' if 'correct_source_observation' in self.seen.get(page,set()) else f'source-observation-{self.attempt}.json')
        observed=PageContent.model_validate_json(observation_file.read_text())
        if record.source_figure_index>=len(observed.figures) or record.source_label_index>=len(observed.figures[record.source_figure_index].labels):return {'saved':False,'error':'Unknown independently observed source dimension'}
        from .audit import figure_key
        import re
        source_label=observed.figures[record.source_figure_index].labels[record.source_label_index]
        if record.agrees_with_candidate and re.sub(r'\s+','',figure_key(source_label))!=re.sub(r'\s+','',figure_key(figure.labels[record.label_index])):
            return {'saved':False,'error':'Different source/candidate labels cannot certify the same dimension; report a blocking mismatch rather than borrowing another source label'}
        if record.candidate_feature_quote not in figure.description and not (record.relation=='annotation' and record.candidate_feature_quote in figure.labels[record.label_index]):return {'saved':False,'error':'Quote the actual candidate description for this feature; do not invent a corrected association'}
        box=record.source_box;feature=record.feature_box
        import math
        def valid_box(b):return all(math.isfinite(v) and 0<=v<=1 for v in b) and b[0]<b[2] and b[1]<b[3]
        def inside(p):return len(p)==2 and all(math.isfinite(v) for v in p) and box[0]<=p[0]<=box[2] and box[1]<=p[1]<=box[3]
        if not valid_box(box) or not valid_box(feature) or not inside(feature[:2]) or not inside(feature[2:]):return {'saved':False,'error':'Source crop must contain the measured feature box'}
        if record.relation=='annotation' and any(s in figure.labels[record.label_index] for s in ('Ø','ø','φ','⌀','∅','±')):return {'saved':False,'error':'Diameter/tolerance labels cannot be classified as non-dimensional annotation'}
        if not all(inside(p) for p in record.tip_points) or (record.relation in ('linear','diameter') and (len(record.tip_points)!=2 or record.tip_points[0]==record.tip_points[1])) or (record.relation=='leader' and not record.tip_points):
            return {'saved':False,'error':'Follow two distinct tips for a linear/diameter dimension; a leader may have one tip. All tips must lie in the inspected crop.'}
        if not any(p==page and tuple(box)==b for p,b,rotation in self.region_evidence):return {'saved':False,'error':'First view_region on this exact original crop including both tips and contour'}
        if record.path_ids:
            self.drawing_paths(page,box,record.path_ids)
            from .drawing_geometry import drawing_geometry
            with pymupdf.open(self.source) as doc:
                p=doc[page-1];native=drawing_geometry(p,box,self.source_digest)
                points=[point for path in native['paths'] if path['id'] in record.path_ids for item in path['items'] for point in item['points']]
                if any(not any(math.hypot((tip[0]-point[0])*p.rect.width,(tip[1]-point[1])*p.rect.height)<=1.5 for point in points) for tip in record.tip_points):
                    return {'saved':False,'error':'Claimed tips do not match selected native path vertices; inspect arrowhead paths rather than guessing coordinates'}
        work=self.work(page);path=work/f'candidate-{self.attempt}.json'
        if not path.exists():return {'saved':False,'error':'Evidence requires an exact candidate for this attempt'}
        payload=record.model_dump()|{'candidate_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'observation_sha256':hashlib.sha256(observation_file.read_bytes()).hexdigest(),'source_label':observed.figures[record.source_figure_index].labels[record.source_label_index],'source_figure_title':observed.figures[record.source_figure_index].title,'source_sha256':self.source_digest,'physical_page':page,'attempt':self.attempt,'candidate_label':figure.labels[record.label_index],'figure_title':figure.title,'basis':'native_geometry_and_vision' if record.path_ids else 'vision','limits':'Source-grounded reviewer assertion; coordinate coverage does not certify semantic ownership.'}
        existing=self.dimension_reviews.setdefault(page,{}).get((record.figure_index,record.label_index))
        if existing and existing!=payload and not record.correction_reason.strip():return {'saved':False,'error':'Explain the new source evidence before replacing this dimension assertion; previous negative evidence stays in history'}
        self.dimension_reviews[page][record.figure_index,record.label_index]=payload
        records=list(self.dimension_reviews[page].values());evidence_file=work/f'dimension-review-{self.attempt}.json'
        if evidence_file.exists():write_json(work/'.history'/evidence_file.stem/(hashlib.sha256(evidence_file.read_bytes()).hexdigest()+'.json'),json.loads(evidence_file.read_text()))
        write_json(evidence_file,{'source_sha256':self.source_digest,'candidate_sha256':payload['candidate_sha256'],'physical_page':page,'attempt':self.attempt,'relations':records})
        self.log(page,'record_dimension_review',file=evidence_file.name,sha256=hashlib.sha256(evidence_file.read_bytes()).hexdigest(),figure_index=record.figure_index,label_index=record.label_index,agrees_with_candidate=record.agrees_with_candidate)
        return {'saved':True,'agrees_with_candidate':record.agrees_with_candidate,'instruction':'A false association must be reported as a blocking figures issue. Preserve the source crop and fix only that relationship.'}

    def record_dimensions(self,page,json_text):
        """Same per-relation validation, fewer model/tool round trips.

        Successful entries remain durable; report every failed index explicitly.
        Partial batches never bypass save_review's complete coverage gate.
        """
        if self.role!='reviewer':return {'saved':False,'error':'Only reviewer records dimension evidence'}
        try:records=json.loads(json_text)
        except (TypeError,ValueError):return {'saved':False,'error':'Expected a JSON array of dimension records'}
        if not isinstance(records,list) or not 1<=len(records)<=100 or any(not isinstance(r,dict) for r in records):
            return {'saved':False,'error':'Provide 1..100 dimension record objects'}
        failures=[];saved=0
        for index,record in enumerate(records):
            result=self.record_dimension(page,json.dumps(record,ensure_ascii=False))
            if result.get('saved'):saved+=1
            else:failures.append({'index':index,**result})
        return {'saved':not failures,'saved_count':saved,'failures':failures,'instruction':'All individual source/candidate, crop, tip, path and correction checks still apply. Partial successes are retained. Every failed record and every missing relation must be resolved before figures PASS.'}

    def read(self,page,kind):
        if self.role=='reviewer' and kind=='page' and 'save_source_observation' not in self.seen.get(page,set()):
            raise ValueError('First independently inspect the original and save_source_observation BEFORE seeing the candidate')
        filename=f'candidate-{self.attempt}.json' if kind=='page' else f'review-{self.attempt}.json'
        path=self.work(page)/filename
        if not path.exists():
            alternatives=sorted(self.work(page).glob('candidate-*.json' if kind=='page' else 'review-*.json'),key=lambda p:int(p.stem.split('-')[-1]))
            if not alternatives:raise ValueError(f'No {kind} artifact saved')
            path=alternatives[-1]
        if self.role=='reviewer' and kind=='page':self.disclosed.setdefault(page,time.monotonic())
        self.log(page,'read_page_json' if kind=='page' else 'read_review',file=path.name)
        raw=path.read_bytes();data=json.loads(raw)
        if self.role=='extractor' and kind=='page':
            attempt=int(path.stem.split('-')[-1]);digest=hashlib.sha256(raw).hexdigest();event_path=self.work(page)/'tools.jsonl'
            events=[json.loads(l) for l in event_path.read_text().splitlines()] if event_path.exists() else []
            saves=[e for e in events if e.get('tool')=='save_page_json' and all(e.get(k)==v for k,v in {'page':page,'attempt':attempt,'role':'extractor','source_sha256':self.source_digest,'model':self.model,'contract_sha256':self.contract_sha256}.items())]
            if attempt<=self.attempt and saves and saves[-1].get('sha256')==digest:
                self.edit_baselines[page]={'file':path.name,'sha256':digest};self.invalid_edit_baselines.discard(page)
            else:
                self.edit_baselines.pop(page,None);self.invalid_edit_baselines.add(page)
        if self.role=='reviewer' and kind=='page':
            observed_file=self.work(page)/(f'verified-source-observation-{self.attempt}.json' if 'correct_source_observation' in self.seen.get(page,set()) else f'source-observation-{self.attempt}.json')
            observed=PageContent.model_validate_json(observed_file.read_text())
            candidate=PageContent.model_validate(data);pairs,left,right=align_tables(observed,candidate)
            return {'candidate':data,'independent_comparison':compare_source(observed,candidate,self.branding_figure_quotes.get(page)),
                    'table_alignment':{'pairs':[{'source_index':i,'candidate_index':j} for i,j in pairs],'unmatched_source_indices':left,'unmatched_candidate_indices':right}}
        return data

    def external_audit(self,page):
        path=self.work(page)/'external-audit.json'
        if not path.exists():return {'present':False}
        if self.role=='reviewer' and 'save_source_observation' not in self.seen.get(page,set()):raise ValueError('Save independent source observation before reading external audit leads')
        raw=path.read_bytes();data=json.loads(raw)
        if data.get('pdf_page')!=page or data.get('source_sha256')!=hashlib.sha256(self.source.read_bytes()).hexdigest():raise ValueError('External audit belongs to another source/page')
        self.log(page,'read_external_audit',sha256=hashlib.sha256(raw).hexdigest())
        return {'present':True,'findings':data['findings'],'instruction':'These are independent audit leads, not authority. Verify each against the original; never invent a missing value or accept a source claim blindly.'}

    def grid_differences(self,page,model):
        differences=[]
        def demonstration(grid):
            box=grid.get('inspected_box')
            return box is not None and model.page_context is not None and any(
                e.transcription=='contextual_summary' and e.box[0]<=box[0] and e.box[1]<=box[1] and e.box[2]>=box[2] and e.box[3]>=box[3]
                and any(p==page and b==tuple(e.box) for p,b,rotation in self.region_evidence)
                for e in model.page_context.source_evidence)
        grids=[g for g in self.grids.get(page,[]) if not demonstration(g)]
        if not model.tables and any(g['row_count']>=2 and g['column_count']>=2 and not g['unknown_cells'] and any(cell for row in g['expanded_rows'] for cell in row) for g in grids):
            return [{'path':'tables','direct_value':'Inspected readable source grid','candidate_value':[]}]
        for grid in grids:
            matches=[]
            for i,t in enumerate(model.tables):
                if len(t.columns)!=grid['column_count']:continue
                offset=grid['row_count']-len(t.rows)
                if offset<0 or offset>3:continue
                if offset:
                    names=['' if r.cells[0].value is None else str(r.cells[0].value) for r in t.rows]
                    if names!=[row[0] for row in grid['expanded_rows'][offset:]]:continue
                matches.append((i,t,offset))
            # Shape alone is ambiguous when a page has repeated identical layouts.
            if len(matches)!=1:continue
            ti,table,offset=matches[0]
            if any(c['row']>=offset for c in grid['unknown_cells']):continue
            for ri,(row,expected) in enumerate(zip(table.rows,grid['expanded_rows'][offset:])):
                cells={c.column_id:c for c in row.cells}
                for ci,column in enumerate(table.columns):
                    cell=cells[column.id];want=expected[ci]
                    actual='' if cell.value is None else str(cell.value)
                    if actual!=want or cell.state!=('blank' if want=='' else 'value'):
                        differences.append({'path':f'tables[{ti}].rows[{ri}].cells[column={ci}]','direct_value':want,'candidate_value':cell.value,'merged_spans':grid['merged_cells']})
        return differences

    def context_errors(self,page,model,after=0):
        if model.page_context is None:return []
        return [{'path':f'page_context.source_evidence[{i}].box','error':'View this exact original demonstration region before summarizing; a summary does not establish product data'}
                for i,e in enumerate(model.page_context.source_evidence) if e.transcription=='contextual_summary'
                and not any(p==page and b==tuple(e.box) and seen>after for (p,b,rotation),seen in self.region_evidence.items())]

    def save(self,page,json_text,kind,literal_quotes=None):
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
            if kind in ('page','observation'):
                errors=self.context_errors(page,model)
                if errors:return {'saved':False,'context_errors':errors}
            if kind=='observation':
                quotes,errors=branding_quote_evidence(self,page,model,literal_quotes)
                if errors:
                    refused=self.source_payload(page,'observation-quotes',{'saved':False,'quote_errors':errors,'quote_evidence':quotes})
                    if refused.get('paged'):refused.update(saved=False,error='Source observation was NOT saved. Read the retained quote errors before correcting the literal quotes.')
                    return refused
            if kind in ('page','observation'):
                differences=self.grid_differences(page,model)
                if differences:return {'saved':False,'error':'Saved table contradicts the directly inspected PDF grid. Reinspect source/merge spans and preserve expanded_rows; use a fresh Vision-only context for genuinely unreliable grids.','direct_grid_differences':differences}
            if kind=='review':
                disclosed=self.read(page,'page')
                observation_file=work/(f'verified-source-observation-{self.attempt}.json' if 'correct_source_observation' in self.seen.get(page,set()) else f'source-observation-{self.attempt}.json')
                observation=PageContent.model_validate_json(observation_file.read_text())
                candidate=PageContent.model_validate(disclosed['candidate'])
                if model.verdict=='pass' and candidate.page_context is not None and (model.context_review is None or not model.context_review.accepts()):
                    return {'saved':False,'error':'Для PASS нужен независимый смысловой context_review по оригиналу: назначение страницы, смысл пересказа, реальные данные/демонстрация, технические факты и связи изделия/параметра/условия/элемента чертежа. Все пять проверок должны быть true с конкретным обоснованием. Буквальное совпадение обычных предложений не требуется.','required_context_review':review_contract()['example']['context_review']}
                pairs,left,right=align_tables(observation,candidate)
                aligned=observation.model_copy(update={'tables':[observation.tables[i] for i,j in sorted(pairs,key=lambda pair:pair[1])]}) if not left and not right else observation
                conflicts=structural_disagreements(aligned,model)
                if conflicts:
                    self.log(page,'review_disagreement',conflicts=conflicts,
                             candidate_content_sha256=hashlib.sha256(json.dumps(disclosed['candidate'],sort_keys=True).encode()).hexdigest())
                    return {'saved':False,'error':'Final review contradicts its independent source observation. Do NOT tell the extractor to delete tables or duplicate table rows into figure labels. Reinspect the original region; correct_source_observation with source evidence if the observation classified a table as a figure, or correct the final counts/checks if they were wrong. Then save_review again. No candidate data was changed.',
                            'review_disagreements':conflicts}
                if (model.verdict=='pass' or any(c.category=='figures' and c.passed for c in model.checks)) and not independent_software_demonstration(observation,candidate):
                    candidate=PageContent.model_validate(disclosed['candidate']);candidate_file=work/f'candidate-{self.attempt}.json'
                    candidate_sha=hashlib.sha256(candidate_file.read_bytes()).hexdigest() if candidate_file.exists() else None
                    records=list(self.dimension_reviews.get(page,{}).values())
                    supporting_annotations=bool(model.context_review and model.context_review.accepts() and model.context_review.supporting_annotations_verified
                        and all(c.page_context is not None and c.page_context.kind=='supporting_material' and not c.tables
                                and all(e.kind=='supporting_material' and e.transcription=='literal' for e in c.page_context.source_evidence)
                                for c in (observation,candidate)))
                    missing=missing_dimension_evidence(candidate,records,candidate_sha,observation,hashlib.sha256(observation_file.read_bytes()).hexdigest(),supporting_annotations=supporting_annotations)
                    if missing:return {'saved':False,'error':'A blanket figures PASS cannot certify dimension ownership. Enable labels helpers to record already inspected relationships in a batch; enable drawings only for ambiguous engineering geometry. Inspect each source view/variant and its own tips/contour. False or unresolved relationships require figures failed. Never borrow a label from another view.', 'missing_dimension_relations':missing}
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
        prior=work/filename
        if prior.exists():write_json(work/'.history'/prior.stem/(hashlib.sha256(prior.read_bytes()).hexdigest()+'.json'),json.loads(prior.read_text()))
        write_json(work/filename,model.model_dump())
        quote_metadata={}
        if kind=='review' and self.dimension_reviews.get(page):
            dimension_file=work/f'dimension-review-{self.attempt}.json'
            quote_metadata={'dimension_file':dimension_file.name,'dimension_sha256':hashlib.sha256(dimension_file.read_bytes()).hexdigest()}
        if kind=='observation':
            quote_file=work/f'source-observation-quotes-{self.attempt}.json'
            if quote_file.exists():write_json(work/'.history'/quote_file.stem/(hashlib.sha256(quote_file.read_bytes()).hexdigest()+'.json'),json.loads(quote_file.read_text()))
            write_json(quote_file,{'source_sha256':self.source_digest,'physical_page':page,'attempt':self.attempt,'quotes':quotes})
            quote_metadata={'quote_file':quote_file.name,'quote_sha256':hashlib.sha256(quote_file.read_bytes()).hexdigest()}
        if kind=='page':self.invalid_edit_baselines.discard(page)
        self.log(page,'save_page_json' if kind=='page' else 'save_source_observation' if kind=='observation' else 'save_review',file=filename,sha256=hashlib.sha256((work/filename).read_bytes()).hexdigest(),**quote_metadata)
        if kind=='observation':self.bind_branding_figures(page,quotes)
        return {'saved':True,'file':str(work/filename)}

    def bind_branding_figures(self,page,quotes):
        bound={}
        for quote in quotes:
            if quote.get('source_kind')=='branding' and 'figure_index' in quote:
                bound.setdefault(quote['figure_index'],set()).add(quote['visible_quote'])
        self.branding_figure_quotes[page]=bound

    def correct_observation(self,page,json_text,reason,literal_quotes=None):
        if self.role!='reviewer' or page not in self.disclosed:return {'saved':False,'error':'Only a reviewer can revise its own observation after comparison'}
        if self.latest_zoom.get(page,0)<=self.disclosed[page]:return {'saved':False,'error':'Reinspect the disputed source with view_region first'}
        if not reason.strip():return {'saved':False,'error':'Explain the source evidence before revising the observation'}
        try:model=PageContent.model_validate_json(json_text)
        except ValidationError as exc:return {'saved':False,'validation_errors':json.loads(exc.json(include_input=False,include_url=False))}
        errors=self.context_errors(page,model,after=self.disclosed[page])
        if errors:return {'saved':False,'context_errors':errors}
        quotes,errors=branding_quote_evidence(self,page,model,literal_quotes,after=self.disclosed[page])
        if errors:
            refused=self.source_payload(page,'observation-quotes',{'saved':False,'quote_errors':errors,'quote_evidence':quotes})
            if refused.get('paged'):refused.update(saved=False,error='Source observation correction was NOT saved. Read the retained quote errors first.')
            return refused
        differences=self.grid_differences(page,model)
        if differences:return {'saved':False,'error':'Correction contradicts inspected direct grid/merge geometry','direct_grid_differences':differences}
        revision=self.corrections.get(page,0)+1;self.corrections[page]=revision
        work=self.work(page);write_json(work/f'source-observation-{self.attempt}-revision-{revision}.json',{'reason':reason,'content':model.model_dump()})
        quote_file=work/f'source-observation-quotes-{self.attempt}-revision-{revision}.json'
        write_json(quote_file,{'source_sha256':self.source_digest,'physical_page':page,'attempt':self.attempt,'quotes':quotes})
        write_json(work/f'verified-source-observation-{self.attempt}.json',model.model_dump())
        self.log(page,'correct_source_observation',revision=revision,reason=reason,quote_file=quote_file.name,quote_sha256=hashlib.sha256(quote_file.read_bytes()).hexdigest())
        self.bind_branding_figures(page,quotes)
        self.disclosed[page]=time.monotonic()
        return {'saved':True,'revision':revision,'original_blind_observation_retained':True}

    def layout(self,page,box=None):
        self.work(page)
        if box is not None and (len(box)!=4 or not all(0<=v<=1 for v in box) or box[0]>=box[2] or box[1]>=box[3]):raise ValueError('Normalized box must be [left,top,right,bottom]')
        with pymupdf.open(self.source) as doc:
            p=doc[page-1];result=[]
            for x0,y0,x1,y1,text,*_ in p.get_text('words'):
                visible=pymupdf.Rect(x0,y0,x1,y1)*p.rotation_matrix
                rect=[round(visible.x0/p.rect.width,4),round(visible.y0/p.rect.height,4),round(visible.x1/p.rect.width,4),round(visible.y1/p.rect.height,4)]
                if box and not (box[0]<=(rect[0]+rect[2])/2<=box[2] and box[1]<=(rect[1]+rect[3])/2<=box[3]):continue
                word={'text':text,'box':rect}
                if len(text)<=12 and any(c in 'ABCEHKMOPTXYАВСЕНКМОРТХУ' for c in text):
                    word['codepoints']=[f'{c}: U+{ord(c):04X}' for c in text if c.isalnum()]
                result.append(word)
        self.log(page,'read_source_layout',box=box)
        return {'words':result,'note':'Original PDF text and normalized positions, not an interpreted table. Outlined/scanned labels need Vision.'}

    def section(self,page,section,index,json_text):
        if self.role!='extractor':return {'saved':False,'error':'Only extractor writes page sections'}
        if section not in ('text_blocks','tables','figures'):raise ValueError('Unknown section')
        if index<0 or index>999:raise ValueError('Index out of range')
        from .schema import TextBlock,Table,Figure
        try:model={'text_blocks':TextBlock,'tables':Table,'figures':Figure}[section].model_validate_json(json_text)
        except ValidationError as exc:return {'saved':False,'validation_errors':json.loads(exc.json(include_input=False,include_url=False))}
        path=self.work(page)/f'sections-{self.attempt}'/section/f'{index:04d}.json'
        write_json(path,model.model_dump());self.log(page,'save_section',section=section,index=index,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        return {'saved':True,'section':section,'index':index}

    def finalize(self,page,title,printed_page=None,source_notes=None,uncertainties=None,preserve_existing=True,page_context=None):
        work=self.work(page);events=[];all_events=[]
        path=work/'tools.jsonl'
        if path.exists():
            for position,line in enumerate(path.read_text().splitlines()):
                event=json.loads(line)
                all_events.append(event)
                if all(event.get(k)==v for k,v in {'page':page,'attempt':self.attempt,'role':'extractor','source_sha256':self.source_digest,'model':self.model,'contract_sha256':self.contract_sha256}.items()):events.append((position,event))
        full=work/f'candidate-{self.attempt}.json';base_position=-1
        full_saves=[(position,e) for position,e in events if e['tool']=='save_page_json']
        if preserve_existing and full_saves and not full.exists():return {'saved':False,'error':'Latest complete page is missing; do not revive an older candidate. Make a fresh full save or explicitly rebuild all sections with preserve_existing=False'}
        if preserve_existing and page in self.invalid_edit_baselines:return {'saved':False,'error':'Read candidate is unbound or from a future attempt; make a fresh full save, or rebuild ALL source sections and finalize with preserve_existing=False'}
        if preserve_existing and not full.exists() and page in self.edit_baselines:
            baseline=self.edit_baselines[page];full=work/baseline['file']
            if hashlib.sha256(full.read_bytes()).hexdigest()!=baseline['sha256']:return {'saved':False,'error':'Read baseline changed; reinspect before editing'}
        data={'text_blocks':[],'tables':[],'figures':[],'printed_page':None,'source_notes':[],'uncertainties':[]}
        if full_saves:base_position=full_saves[-1][0]
        if preserve_existing and full.exists():
            digest=hashlib.sha256(full.read_bytes()).hexdigest()
            saves=[full_saves[-1][0]] if full_saves and full_saves[-1][1].get('sha256')==digest else []
            if full.name!=f'candidate-{self.attempt}.json':
                # Recheck the latest save at finalization as well as at read time:
                # restoring old bytes must not revive a superseded prior baseline.
                prior_attempt=int(full.stem.split('-')[-1])
                prior_saves=[e for e in all_events if e.get('tool')=='save_page_json' and all(e.get(k)==v for k,v in {'page':page,'attempt':prior_attempt,'role':'extractor','source_sha256':self.source_digest,'model':self.model,'contract_sha256':self.contract_sha256}.items())]
                saves=[-1] if prior_attempt<self.attempt and page in self.edit_baselines and prior_saves and prior_saves[-1].get('sha256')==digest else []
            if not saves:return {'saved':False,'error':'Existing full page lacks this source/model/contract validated save; use a fresh full save or new attempt'}
            base_position=max(saves);data=PageContent.model_validate_json(full.read_text()).model_dump()
        # Only edits after the latest full save apply. Older drafts remain retained,
        # but cannot overwrite the complete page with stale rows or missing sections.
        edits={}
        for position,event in events:
            if position>base_position and event['tool']=='save_section':edits[event['section'],event['index']]=event
        for section in ('text_blocks','tables','figures'):
            for index in sorted(i for name,i in edits if name==section):
                path=work/f'sections-{self.attempt}'/section/f'{index:04d}.json'
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=edits[section,index].get('sha256'):
                    return {'saved':False,'error':'Section changed outside its current validated tool save'}
                if index>len(data[section]):return {'saved':False,'error':f'{section} indices must be contiguous starting at 0'}
                value=json.loads(path.read_text())
                if index==len(data[section]):data[section].append(value)
                else:data[section][index]=value
        data['title']=title
        if printed_page is not None:data['printed_page']=printed_page
        if source_notes is not None:data['source_notes']=source_notes
        if uncertainties is not None:data['uncertainties']=uncertainties
        if page_context is not None:data['page_context']=page_context
        return self.save(page,json.dumps(data,ensure_ascii=False),'page')


def server(context):
    basic={'load_skill','get_json_schema','view_page','view_region','read_page_json','read_external_audit',
           'save_source_observation','correct_source_observation','save_review','enable_helpers'}
    if not context.source:basic.add('open_catalog')
    groups={'text':{'read_source_layout','read_source_artifact'},
            'tables':{'read_source_table','read_source_layout','read_source_artifact','extract_direct'},
            'labels':{'inspect_dimension_review_targets','record_dimension_review','record_dimension_reviews'},
            'drawings':{'inspect_drawing_geometry','read_drawing_paths','trace_dimension_candidates',
                        'read_source_layout','read_source_artifact','inspect_dimension_review_targets',
                        'record_dimension_review','record_dimension_reviews'}}
    exposed=set(basic)
    if context.role=='reviewer':
        # FastAgent snapshots tool schemas for one generate() call. MCP's list
        # changed notification refreshes its cache, not that running snapshot.
        # Advertise usable native helpers from the first turn instead of
        # claiming to unlock schemas the model cannot actually call yet.
        exposed.update(name for names in groups.values() for name in names)
    class FocusedCatalogServer(MCPServer):
        async def list_tools(self):
            tools=await super().list_tools()
            return [t for t in tools if t.name in exposed] if context.role=='reviewer' else tools
    mcp=FocusedCatalogServer('catalog-tools',version='1.1.0',log_level='ERROR')
    if context.role=='reviewer':
        from mcp.server.mcpserver import Context
        @mcp.tool()
        async def enable_helpers(group: str,ctx: Context) -> dict:
            """Reveal optional helpers only when needed: text for native glyphs, tables for direct rows/merges, labels for recording inspected source relationships, drawings for ambiguous contours/vector geometry, all for compatibility. Images and save validation remain mandatory."""
            if group not in {*groups,'all'}:return {'enabled':False,'error':'Choose text, tables, labels, drawings or all'}
            additions=groups[group] if group!='all' else {t.name for t in await MCPServer.list_tools(mcp)}
            exposed.update(additions)
            if context.page is not None:context.log(context.page,'enable_helpers',group=group)
            await ctx.session.send_tool_list_changed()
            return {'enabled':True,'group':group,'available_tools':sorted(exposed),'instruction':'Evidence helpers are already callable from the initial tool list. Call the needed tool directly; do not repeat activation. Choose only the evidence needed; full original-image and save validation rules are unchanged.'}
    @mcp.tool()
    def open_catalog(source_path: str,output_directory: str) -> dict:
        """Open a user-specified local PDF and separate output folder. Not needed in an assigned CLI job."""
        if context.source:raise ValueError('Already assigned; start another job to change source')
        return context.open(source_path,output_directory)
    @mcp.tool()
    def load_skill() -> str:
        """Read the registered native skill for this worker role before extracting/reviewing."""
        if context.page is not None:context.log(context.page,'load_skill')
        text=(SKILLS/f'catalog-{context.role.replace("extractor","extract").replace("reviewer","review")}'/'SKILL.md').read_text()
        if context.role=='reviewer':text='Exact review schema and structural example (available before the first save):\n'+json.dumps(review_contract(),ensure_ascii=False,separators=(',',':'))+'\n\n'+text
        return text
    @mcp.tool()
    def get_json_schema(kind: str='page') -> dict:
        """Get the exact saved-file schema. Chat responses need not be JSON. kind: page or review."""
        if kind not in ('page','review'):raise ValueError('kind must be page or review')
        return {'schema':PageContent.model_json_schema(),'required_review_checks':sorted(CHECKS)} if kind=='page' else review_contract()
    @mcp.tool(structured_output=False)
    def view_page(page: int):
        """See the original PDF page as an image. Physical page number is one-based."""
        return context.render(page)
    @mcp.tool(structured_output=False)
    def view_region(page: int,box: list[float],rotation: int=0):
        """Zoom a chosen source region. box=[left,top,right,bottom], fractions 0..1. rotation clockwise degrees 0/90/180/270."""
        return context.region(page,box,rotation)
    @mcp.tool()
    def read_source_table(page: int,box: list[float]) -> dict:
        """Extract a selected table BODY directly from PDF text/vector geometry. Returns expanded rows, true geometry-backed merge spans and column positions. Choose normalized box; inspect headers separately."""
        from .grid import table_grids
        context.work(page)
        with pymupdf.open(context.source) as doc:result=table_grids(doc[page-1],box)
        for grid in result['tables']:
            grid['inspected_box']=result['effective_box']
            if grid not in context.grids.setdefault(page,[]):context.grids[page].append(grid)
        context.log(page,'read_source_table',box=box)
        return context.source_payload(page,'table',result)
    @mcp.tool()
    def read_source_artifact(page: int,artifact_id: str,offset: int=0,length: int=16000) -> dict:
        """Read retained native table/layout source evidence in byte-bounded chunks. Follow next_offset until total_characters; offsets count Python characters."""
        return context.source_artifact(page,artifact_id,offset,length)
    @mcp.tool()
    def read_source_layout(page: int,box: list[float]|None=None) -> dict:
        """Read original text-layer words with normalized positions. Use to resolve column alignment or identical Latin/Cyrillic glyphs; diagrams still need Vision."""
        return context.source_payload(page,'layout',context.layout(page,box))
    @mcp.tool()
    def inspect_drawing_geometry(page: int,box: list[float],offset: int=0,limit: int=20,path_kind: str='stroke') -> dict:
        """Read drawing words/directions and compact path index. Default stroke index explicitly omits fill-only glyph outlines; choose all/fill if needed. Follow next_offset through counts.selected_paths; use read_drawing_paths for chosen IDs. Coordinates match original view_region. Verify both dimension endpoints and visible contours; no inferred ownership. Empty native geometry needs Vision."""
        return context.drawing_geometry(page,box,offset,limit,path_kind)
    @mcp.tool()
    def read_drawing_paths(page: int,box: list[float],path_ids: list[str]) -> dict:
        """Read exact native endpoints/control points, stroke/fill/style for1..40 indexed path IDs in the same original region. Large paths use read_source_artifact pagination; no segment is truncated. Small filled triangles may be arrowheads or other marks: verify the original."""
        return context.drawing_paths(page,box,path_ids)
    @mcp.tool()
    def trace_dimension_candidates(page: int,box: list[float],label: str) -> dict:
        """Find literal shaft endpoints AND separate triangle tip candidates near one numeric dimension in a selected original region. Up to6 nearest parallel lines per label, each with filled triangle marks near both ends. Shaft ends may be head bases; use tip candidates and extension lines. Heuristic, not certified arrows or ownership: check original view_region. Empty results need Vision/full geometry index. Path IDs bind exact PDF and page; no feature names/units inferred."""
        return context.dimension_candidates(page,box,label)
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
    @mcp.tool()
    def read_external_audit(page: int) -> dict:
        """Read source-bound independent audit leads. Reviewer must save blind observations first; leads require original-image verification."""
        return context.external_audit(page)
    if context.role=='extractor':
        @mcp.tool()
        def save_page_json(page: int,json_text: str) -> dict:
            """Validate and atomically save a complete page JSON. Errors are returned to the agent for correction."""
            return context.save(page,json_text,'page')
        @mcp.tool()
        def save_section(page: int,section: str,index: int,json_text: str) -> dict:
            """Validate/save ONE table, figure or text block; index starts at0. After a full save this edits that section while retaining the other sections."""
            return context.section(page,section,index,json_text)
        @mcp.tool()
        def finalize_page(page: int,title: str,printed_page: str|None=None,source_notes: list[str]|None=None,uncertainties: list[str]|None=None,preserve_existing: bool=True,page_context: dict|None=None) -> dict:
            """Assemble validated sections into complete JSON. After a full save, apply only later section edits and retain all untouched tables/text/figures and omitted metadata. Same source/model/contract/attempt; new indices contiguous. An unbound read baseline is refused: rebuild ALL sections and explicitly set preserve_existing=False for a fresh page, or make a full save."""
            return context.finalize(page,title,printed_page,source_notes,uncertainties,preserve_existing,page_context)
    else:
        @mcp.tool()
        def inspect_dimension_review_targets(page: int) -> dict:
            """List minimum candidate dimension relationships requiring separate source-view coverage. Each repeated figure/label has its own identity; nonstandard labels still require full original-image review."""
            return context.dimension_inventory(page)
        @mcp.tool()
        def record_dimension_review(page: int,json_text: str) -> dict:
            """Record source-bound relationship evidence. JSON: source_figure_index,source_label_index,figure_index,label_index,view,relation(linear/diameter/leader/annotation),source_box,feature_box,tip_points,path_ids,source_feature,candidate_feature_quote,agrees_with_candidate,evidence, optional correction_reason. Map independent source and candidate targets separately. First view_region on source_box including tips/extension lines/contour; quote candidate description exactly. annotation classifies actual non-dimensional dates/identifiers after source inspection, with no invented arrows; diameter/tolerance cannot use it. Native path IDs optional for scans. Changed records need correction_reason; all revisions retained. False/unresolved relations prohibit blanket figures PASS."""
            return context.record_dimension(page,json_text)
        @mcp.tool()
        def record_dimension_reviews(page: int,json_text: str) -> dict:
            """Preferred batch form of record_dimension_review: JSON array of 1..100 records with the same fields. First inspect exact crops/tips/contours. All individual validations, history and final coverage rules apply; no implied ownership. Returns compact saved_count and indexed failures. Partial successes stay saved; fix every failure before PASS."""
            return context.record_dimensions(page,json_text)
        @mcp.tool()
        def save_source_observation(page: int,json_text: str,literal_quotes: list[dict]|None=None) -> dict:
            """Save blind PageContent BEFORE candidate. Branding literal_quotes items use {block_index,box,visible_quote,basis:text_layer|vision,conflict:null|source_notes text,rotation:0}. For a nontechnical branding caption represented as a figure label, use {figure_index,label_index,source_kind:branding,...} instead of block_index. View each exact box first. Numbers/operators/diameter/view signs cannot be reclassified. Quote original language. Native text and visible quote remain separate; an actual conflict needs a source note and Vision evidence."""
            return context.save(page,json_text,'observation',literal_quotes)
        @mcp.tool()
        def correct_source_observation(page: int,json_text: str,reason: str,literal_quotes: list[dict]|None=None) -> dict:
            """Revise mistaken source observations only after fresh view_region inspection and a source-grounded reason. Initial blind transcription and every revision stay retained; no revision-count limit."""
            return context.correct_observation(page,json_text,reason,literal_quotes)
        @mcp.tool()
        def save_review(page: int,json_text: str) -> dict:
            """Save strict source-grounded review. Incomplete or contradictory claimed passes return errors."""
            return context.save(page,json_text,'review')
    return mcp


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--role',choices=['extractor','reviewer'],default='extractor');p.add_argument('--page',type=int);p.add_argument('--attempt',type=int,default=0)
    p.add_argument('--model')
    p.add_argument('--contract-sha256')
    args=p.parse_args()
    if bool(args.source)!=bool(args.output):p.error('--source and --output must be supplied together')
    server(CatalogTools(args.source,args.output,args.role,args.page,args.attempt,args.model,args.contract_sha256)).run()

if __name__=='__main__':main()
