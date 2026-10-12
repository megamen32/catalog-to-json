"""Full source inventory as explicitly unreviewed native JSON, never accepted data."""
import hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
import pymupdf
from .direct import inspect_page
from .tools import write_json
from .provenance import program_version


def native_batch(manifest,output,deadline_seconds=3600):
    manifest=Path(manifest).resolve();output=Path(output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('Native evidence is immutable; choose a fresh directory')
    output.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();version=program_version();state={'stage':'native_draft','tested_program':version,'started_at':datetime.now(timezone.utc).isoformat(),'complete':False,'reviewed':False,'catalogs':[]}
    for item in json.loads(manifest.read_text())['catalogs']:
        source=(manifest.parent/item['source']).resolve();digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest!=item['source_sha256']:raise ValueError('Native draft source hash mismatch')
        target=output/item['id'];target.mkdir(exist_ok=True)
        catalog={'stage':'native_draft','tested_program':version,'source':{'filename':source.name,'sha256':digest},'complete_for_selection':False,'reviewed':False,'pages':[]}
        with pymupdf.open(source) as doc:
            catalog['source']['page_count']=len(doc)
            for n,page in enumerate(doc,1):
                if time.monotonic()-started>=deadline_seconds:break
                page_started=time.monotonic();single=pymupdf.open();single.insert_pdf(doc,from_page=n-1,to_page=n-1)
                candidate,hint,reasons=inspect_page(page,single.tobytes());single.close()
                raw={'source_sha256':digest,'physical_page':n,'text':page.get_text(),'words':page.get_text('words'),'images':[{'bbox':list(i['bbox']),'width':i['width'],'height':i['height'],'xref':i.get('xref')} for i in page.get_image_info(xrefs=True)],'routing_reasons':reasons,'markdown_hint':hint}
                path=target/f'page-{n:04d}.json';write_json(path,raw)
                catalog['pages'].append({'pdf_page':n,'status':'native_draft','reviewed':False,'content':candidate.model_dump() if candidate else None,'raw_artifact':path.name,'raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'elapsed_seconds':round(time.monotonic()-page_started,3),'routing_reasons':reasons})
                write_json(target/'catalog.json',catalog)
        catalog['complete_for_selection']=len(catalog['pages'])==catalog['source']['page_count'];catalog['elapsed_seconds']=round(sum(p['elapsed_seconds'] for p in catalog['pages']),3);write_json(target/'catalog.json',catalog)
        state['catalogs'].append({'id':item['id'],'pages':len(catalog['pages']),'source_pages':catalog['source']['page_count'],'output':str(target/'catalog.json'),'native_complete':catalog['complete_for_selection']});write_json(output/'batch.json',state)
    state.update(complete=len(state['catalogs'])==len(json.loads(manifest.read_text())['catalogs']) and all(c['native_complete'] for c in state['catalogs']),elapsed_seconds=round(time.monotonic()-started,3),finished_at=datetime.now(timezone.utc).isoformat());write_json(output/'batch.json',state);return state
