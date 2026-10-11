import asyncio
import hashlib
import json
import time
from pathlib import Path
import pymupdf
from .direct import inspect_page
from .schema import PageContent


def write_json(path: Path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".pending")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)


async def convert(source: Path,out: Path,pages: list[int],agents,max_repairs=1,resume=False,deadline_seconds=180):
    source=source.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    job={"schema_version":"1.0","source":{"filename":source.name,"sha256":digest},"selection":pages,
         "models":{"extractor":agents.extractor,"reviewer":agents.reviewer},"pages":[],"complete_for_selection":False,"catalog_complete":False}
    started=time.monotonic()
    doc=pymupdf.open(source);job['source']['page_count']=len(doc)
    if not pages or len(set(pages))!=len(pages) or any(n<1 or n>len(doc) for n in pages):raise ValueError("Page selection is empty, repeated, or out of range")
    for n in pages:
        work=out/f"page-{n:04d}";work.mkdir(exist_ok=True)
        key={"source_sha256":digest,"page":n,"models":job["models"],"schema":"1.0","max_repairs":max_repairs,"contract":getattr(agents,"contract_digest",None)}
        keyhash=hashlib.sha256(json.dumps(key,sort_keys=True).encode()).hexdigest()
        receipt=work/'result.json'
        if resume and receipt.exists():
            previous=json.loads(receipt.read_text())
            if previous.get('cache_key')==keyhash and previous.get('status')=='accepted':
                job['pages'].append(previous);continue
        record={"pdf_page":n,"cache_key":keyhash,"status":"pending","route":None,"routing_reasons":[],"attempts":[]}
        try:
            page=doc[n-1];single=pymupdf.open();single.insert_pdf(doc,from_page=n-1,to_page=n-1)
            pdf_bytes=single.tobytes();(work/'source.pdf').write_bytes(pdf_bytes)
            image=work/'source.png';page.get_pixmap(matrix=pymupdf.Matrix(2.5,2.5)).save(image)
            images=[image]
            for label,region in [('top',pymupdf.Rect(0,0,page.rect.width,page.rect.height*.55)),('bottom',pymupdf.Rect(0,page.rect.height*.45,page.rect.width,page.rect.height))]:
                tile=work/f'zoom-{label}.png';page.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=region).save(tile);images.append(tile)
            candidate,hint,reasons=inspect_page(page,pdf_bytes)
            (work/'anydoc.md').write_text(hint)
            record.update(route="vision" if reasons else "anydoc",routing_reasons=reasons)
            def remaining():
                seconds=deadline_seconds-(time.monotonic()-started)
                if seconds<=0:raise TimeoutError("Job deadline exhausted; retained checkpoint")
                return seconds
            if reasons:
                candidate=await asyncio.wait_for(agents.extract(images,hint),remaining())
            if getattr(agents,'last_response',None):write_json(work/'extract-model-response.json',agents.last_response)
            assert candidate is not None
            for attempt in range(max_repairs+1):
                write_json(work/f'candidate-{attempt}.json',candidate.model_dump())
                report=await asyncio.wait_for(agents.review(images,candidate),remaining())
                write_json(work/f'review-{attempt}.json',report.model_dump())
                record['attempts'].append({"candidate":f"candidate-{attempt}.json","review":f"review-{attempt}.json"})
                if report.accepts(candidate):
                    record.update(status="accepted",content=candidate.model_dump(),review=report.model_dump());break
                record.update(status="needs_review",content=candidate.model_dump(),review=report.model_dump())
                if attempt<max_repairs:
                    record['route']='vision'
                    candidate=await asyncio.wait_for(agents.extract(images,hint,{"candidate":candidate.model_dump(),"review":report.model_dump()}),remaining())
        except Exception as exc:
            if getattr(agents,"last_response",None):write_json(work/"last-model-response.json",agents.last_response)
            record.update(status="failed",error=f"{type(exc).__name__}: {exc}")
        write_json(receipt,record);job['pages'].append(record)
        write_json(out/'catalog.json',job)
        if time.monotonic()-started>=deadline_seconds:break
    job['complete_for_selection']=len(job['pages'])==len(pages) and all(p['status']=='accepted' for p in job['pages'])
    job['catalog_complete']=job['complete_for_selection'] and set(pages)==set(range(1,len(doc)+1))
    write_json(out/'catalog.json',job)
    return job
