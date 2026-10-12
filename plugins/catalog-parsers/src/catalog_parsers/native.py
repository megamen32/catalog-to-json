"""Optional native engines. Each is installed and executed in its own interpreter."""
import dataclasses
import json
from pathlib import Path
import subprocess
import sys
from .structured import from_liteparse, from_matrices, from_html_blocks

PACKAGES = {'liteparse':'liteparse','img2table':'img2table','camelot-lattice':'camelot-py','camelot-stream':'camelot-py','gmft':'gmft','paddle':'paddleocr','mineru-standard':'mineru','mineru-advanced':'mineru','mineru-basic':'mineru'}


def settings(backend):
    base={'cpu_threads':2,'adapter_header_convention':'first row if native header roles absent'}
    if backend=='liteparse':return {**base,'ocr':False,'extract_blocks':True,'preserve_small_text':True,'geometry':True}
    if backend=='img2table':return {**base,'ocr':False,'pdf_text_extraction':True,'detect_rotation':True,'max_workers':1}
    if backend.startswith('camelot'):return {**base,'ocr':False,'flavor':backend.split('-')[1],'parallel':False,'backend':'pdfium'}
    if backend=='gmft':return {**base,'ocr':False,'device':'cpu','enable_multi_header':True,'semantic_spanning_cells':True}
    if backend=='paddle':return {**base,'ocr':True,'lang':'ru','dpi':200,'device':'cpu','enable_mkldnn':False,'page_orientation':True,'textline_orientation':True,'unwarping':False,'formula':False,'seal':False,'chart':False,'region_detection':False}
    return {**base,'tier':backend.split('-')[1],'ocr_mode':'auto','vlm_engine':'llama-cpp','remote':False,'process_cpu_affinity':2}


def convert(source, page, backend, output):
    if backend=='liteparse':
        from liteparse import LiteParse
        raw=dataclasses.asdict(LiteParse(target_pages=str(page),output_format='json',extract_blocks=True,extract_text_metadata=True,extract_vector_graphics=True,preserve_very_small_text=True,keep_headers_footers=True,ocr_enabled=False,num_workers=1,quiet=True).parse(str(source)))
        return raw,from_liteparse(raw)
    if backend=='img2table':
        from img2table.document import PDF
        tables=PDF(str(source),pages=[page-1],detect_rotation=True,pdf_text_extraction=True).extract_tables(ocr=None,max_workers=1)
        raw={'tables':[]}
        for original_page, tabs in tables.items():
            for t in tabs:
                rows=list(t.content.values())
                raw['tables'].append({'page_index':original_page,'bbox':dataclasses.asdict(t.bbox),'title':t.title,'data':[[c.value for c in row] for row in rows],'cells':[[{'bbox':dataclasses.asdict(c.bbox),'value':c.value} for c in row] for row in rows]})
        return raw,from_matrices(raw,'img2table native tables')
    if backend.startswith('camelot'):
        import camelot
        flavor=backend.split('-')[1]
        options={'backend':'pdfium'} if flavor=='lattice' else {}
        tables=camelot.read_pdf(str(source),pages=str(page),flavor=flavor,parallel=False,cpu_count=1,suppress_stdout=True,**options)
        raw={'tables':[{'page':t.page,'rotation':t.rotation,'bbox':t._bbox,'data':t.df.values.tolist(),'parsing_report':t.parsing_report,'cells':[[{k:getattr(c,k) for k in ['text','x1','y1','x2','y2','left','right','top','bottom','hspan','vspan']} for c in row] for row in t.cells]} for t in tables]}
        return raw,from_matrices(raw,f'Camelot {flavor} native tables')
    if backend=='gmft':
        import torch
        torch.set_num_threads(2)
        from gmft.auto import AutoTableDetector,AutoTableFormatter,AutoFormatConfig,TATRDetectorConfig
        from gmft.pdf_bindings import PyPDFium2Document
        detect=AutoTableDetector(config=TATRDetectorConfig(torch_device='cpu'))
        fmt=AutoTableFormatter(config=AutoFormatConfig(torch_device='cpu',enable_multi_header=True,semantic_spanning_cells=True))
        doc=PyPDFium2Document(str(source));raw={'tables':[]}
        try:
            for crop in detect.extract(doc[page-1]):
                table=fmt.extract(crop);df=table.df();heads=[];groups=[]
                for h in df.columns.tolist():
                    parts=[str(v) for v in h] if isinstance(h,tuple) else [str(h)]
                    heads.append(parts[-1]);groups.append(' '.join(parts[:-1]) or None)
                values=df.astype(object).where(df.notna(),None).values.tolist()
                values=[[str(v) if v is not None else None for v in row] for row in values]
                raw['tables'].append({'crop':crop.to_dict(),'structure':table.to_dict(),'headers':heads,'groups':groups,'data':values})
        finally:doc.close()
        return raw,from_matrices(raw,'gmft native table formatter')
    if backend=='paddle':
        import pymupdf
        from paddleocr import PPStructureV3
        image=output/'input-page.png'
        with pymupdf.open(source) as doc:doc[page-1].get_pixmap(dpi=200).save(image)
        p=PPStructureV3(lang='ru',ocr_version='PP-OCRv5',device='cpu',cpu_threads=2,enable_mkldnn=False,use_doc_orientation_classify=True,use_doc_unwarping=False,use_textline_orientation=True,use_table_recognition=True,use_seal_recognition=False,use_formula_recognition=False,use_chart_recognition=False,use_region_detection=False)
        raw={'results':[r.json for r in p.predict(str(image))]}
        return raw,from_html_blocks(raw,'PaddleOCR PP-StructureV3 native layout')
    if backend.startswith('mineru'):
        target=output/'native-middle.json'
        executable=Path(sys.executable).parent/'mineru-kit'
        args=[str(executable),'parse',str(source),'--pages',str(page),'--tier',backend.split('-')[1],'--format','middle_json','--ocr-mode','auto','--output',str(target)]
        with (output/'native.log').open('w') as log:subprocess.run(args,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=850)
        raw=json.loads(target.read_text());return raw,from_html_blocks(raw,'MinerU native middle JSON')
    raise ValueError('Unknown native backend')
