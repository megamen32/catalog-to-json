"""Focused integration: complete source-bound queue and execution receipts; expected <1s, max 5s."""
import asyncio
import hashlib
import json
from pathlib import Path
import pymupdf
from catalog_json.pipeline import convert
from catalog_json.batch import convert_batch
from catalog_json.schema import PageContent,Review,Check,CHECKS


class Agents:
    extractor='minimax-test';reviewer='glm-test';contract_digest='a'*64;timeout=1200;max_tokens=16384
    async def run(self,role,source,out,page,attempt,feedback=False):
        if role=='extractor':return PageContent(title=f'Page {page}',tables=[],figures=[],text_blocks=[])
        return Review(verdict='pass',checks=[Check(category=c,passed=True,evidence='Synthetic independently checked source') for c in sorted(CHECKS)],issues=[],observed_table_count=0,observed_row_counts=[],observed_column_counts=[])


def make_pdf(path,count):
    with pymupdf.open() as doc:
        for _ in range(count):doc.new_page()
        doc.save(path)


def test_whole_queue_includes_every_physical_page_and_version_time(tmp_path):
    source=tmp_path/'source.pdf';make_pdf(source,3)
    manifest=tmp_path/'queue.json';manifest.write_text(json.dumps({'catalogs':[{'id':'first','source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}))
    result=asyncio.run(convert_batch(manifest,tmp_path/'out',Agents(),deadline_seconds=10))
    assert result['complete'] and result['catalogs'][0]['accepted_pages']==3
    catalog=json.load(open(tmp_path/'out/first/catalog.json'))
    assert catalog['catalog_complete'] and [p['pdf_page'] for p in catalog['pages']]==[1,2,3]
    assert catalog['tested_program']['package_version']
    assert catalog['tested_program']['source_code_sha256']
    assert catalog['elapsed_seconds']>=0
    assert all(p['elapsed_seconds']>=0 for p in catalog['pages'])
    assert catalog['test_method']['max_repairs'] is None
    assert catalog['test_method']['call_timeout_seconds']==1200


def test_accepted_resume_keeps_original_execution_metadata(tmp_path):
    source=tmp_path/'source.pdf';make_pdf(source,1)
    first=asyncio.run(convert(source,tmp_path/'out',[1],Agents(),deadline_seconds=10))
    old=first['pages'][0]['tested_program'];old_time=first['pages'][0]['elapsed_seconds']
    second=asyncio.run(convert(source,tmp_path/'out',[1],Agents(),resume=True,deadline_seconds=10))
    assert second['pages'][0]['tested_program']==old
    assert second['pages'][0]['elapsed_seconds']==old_time
