"""Bounded local parser execution with raw outputs and versioned cache identity."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
from . import __version__
from .adapter import from_pymupdf,from_docling


def available():
    result={}
    for package in ['pymupdf4llm','docling']:
        try:result[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:result[package]=None
    from .dispatch import capabilities
    result.update(capabilities())
    return result


def parse(source,page,backend,output,model='not-applicable',resume=False):
    import pymupdf
    source=Path(source).resolve();output=Path(output).resolve()
    if backend not in ['pymupdf4llm','docling']:
        from .dispatch import parse_external
        return parse_external(source,page,backend,output,model,resume)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    version=available()[backend]
    if version is None:raise ValueError(f'Optional parser {backend} is not installed')
    options={'ocr':False,'cpu_threads':2,'page':page,'adapter_version':__version__}
    identity={'source_sha256':digest,'physical_page':page,'backend':backend,'version':version,'options':options}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    receipt_path=output/'receipt.json';candidate=output/'candidate.json'
    if receipt_path.exists():
        saved=json.loads(receipt_path.read_text())
        if not resume:raise ValueError('Parser output already exists; use a fresh directory or explicit resume')
        if saved['cache_key']!=key or saved['status']!='completed' or not candidate.exists() or hashlib.sha256(candidate.read_bytes()).hexdigest()!=saved.get('candidate_sha256'):
            raise ValueError('Changed/incomplete parser cache cannot be reused')
        return saved
    if output.exists() and any(output.iterdir()):raise ValueError('Parser output directory must be fresh')
    output.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    with pymupdf.open(source) as doc:
        if not 1<=page<=len(doc):raise ValueError('Physical page outside source')
    receipt={**identity,'cache_key':key,'plugin_version':__version__,'package_version':version,'project_revision':None,
             'contract_sha256':hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest(),
             'stage':'direct_parser','model':model,'status':'running','tokens':None,'cost':None}
    receipt_path.write_text(json.dumps(receipt,indent=2))
    try:
        if backend=='pymupdf4llm':
            import pymupdf4llm
            raw=json.loads(pymupdf4llm.to_json(str(source),pages=[page-1],use_ocr=False,show_progress=False))
            content=from_pymupdf(raw)
        else:
            from docling.document_converter import DocumentConverter,PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.datamodel.accelerator_options import AcceleratorOptions,AcceleratorDevice
            options=PdfPipelineOptions(do_ocr=False,do_table_structure=True)
            options.accelerator_options=AcceleratorOptions(num_threads=2,device=AcceleratorDevice.CPU)
            result=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=options)}).convert(str(source),page_range=(page,page))
            raw=result.document.export_to_dict();content=from_docling(raw)
            receipt['parser_status']=str(result.status)
        (output/'raw.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
        candidate.write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf-8')
        receipt.update(status='completed',candidate=str(candidate),candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),raw_sha256=hashlib.sha256((output/'raw.json').read_bytes()).hexdigest())
    except Exception as exc:
        receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
    receipt['elapsed_seconds']=round(time.monotonic()-started,3)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    return receipt
