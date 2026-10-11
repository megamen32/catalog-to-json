"""Focused integration: real MCP transport/images and artifact validation; expected 4 s, max 20 s."""
import asyncio
import json
from pathlib import Path
import sys
import pymupdf
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from catalog_json.tools import CatalogTools
from test_contract import content,review


def pdf(tmp_path):
    source=tmp_path/'source.pdf'
    with pymupdf.open() as d:
        p=d.new_page();p.insert_text((70,70),'Catalog example');d.save(source)
    return source


def test_save_requires_inspection_and_returns_errors(tmp_path):
    t=CatalogTools(pdf(tmp_path),tmp_path/'output')
    assert not t.save(1,content().model_dump_json(),'page')['saved']
    t.render(1);t.direct(1)
    bad=t.save(1,'{"title":1}','page')
    assert not bad['saved'] and bad['validation_errors']
    assert t.save(1,content().model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1)
    assert r.save(1,content().model_dump_json(),'observation')['saved'];r.read(1,'page')
    incomplete=review();incomplete.checks.pop()
    assert not r.save(1,incomplete.model_dump_json(),'review')['saved']
    assert not r.save(1,content().model_dump_json(),'page')['saved']
    assert r.save(1,review().model_dump_json(),'review')['saved']


def test_native_mcp_image_roundtrip(tmp_path):
    source=pdf(tmp_path)
    async def run():
        params=StdioServerParameters(command=sys.executable,args=['-m','catalog_json.tools','--source',str(source),'--output',str(tmp_path/'out')])
        async with stdio_client(params) as (reader,writer):
            async with ClientSession(reader,writer) as client:
                await client.initialize();listed=await client.list_tools()
                assert 'save_page_json' in [t.name for t in listed.tools]
                skill=await client.call_tool('load_skill',{});assert 'Fidelity rules' in skill.content[0].text
                result=await client.call_tool('view_page',{'page':1})
                assert not result.is_error
                assert any(b.type=='image' for b in result.content)
                result=await client.call_tool('get_json_schema',{'kind':'page'})
                assert not result.is_error
    asyncio.run(asyncio.wait_for(run(),20))


def test_json_exports_keep_units_qualifiers_and_full_page(tmp_path):
    """Fast unit: exports must not drop header conditions or drawings; expected <1 s, max 5 s."""
    from catalog_json.schema import Figure,TextBlock
    from catalog_json.export import to_html,to_xlsx
    from openpyxl import load_workbook
    d=content();d.tables[0].columns[0].label='Масса';d.tables[0].columns[0].unit='кг';d.tables[0].columns[0].qualifier='не более'
    d.figures=[Figure(title='Вид А',description='Высота Н±2',labels=['Н±2'])];d.text_blocks=[TextBlock(kind='footer',text='Контакты')]
    catalog={'complete_for_selection':True,'pages':[{'pdf_page':1,'status':'accepted','content':d.model_dump()}]}
    to_html(catalog,tmp_path/'page.html');html=(tmp_path/'page.html').read_text();assert 'не более' in html and 'кг' in html and 'Н±2' in html
    to_xlsx(catalog,tmp_path/'page.xlsx');book=load_workbook(tmp_path/'page.xlsx');assert book['Стр 1 таб 1']['A1'].value=='Масса, кг; не более'
    assert any('Н±2' in str(row) for row in book['Текст и чертежи'].values)


def test_bundled_skills_native_discovery():
    """Fast unit: prevent silently running without the user's native skill; expected <1 s, max 5 s."""
    from fast_agent.skills.registry import SkillRegistry
    from catalog_json.tools import SKILLS
    assert {m.name for m in SkillRegistry(directories=[SKILLS]).load_manifests()}=={'catalog-extract','catalog-review'}


def test_interrupted_review_resumes_without_reextracting(tmp_path):
    """Focused integration: don't repeat extraction after a review timeout; expected <1 s, max 5 s."""
    from catalog_json.pipeline import convert
    from catalog_json.tools import write_json
    class Workers:
        extractor=reviewer='test-model';contract_digest='test-contract';fail=True;calls=[]
        async def run(self,role,source,out,page,attempt,feedback=False):
            self.calls.append(role)
            if role=='reviewer':
                if self.fail:raise TimeoutError('review interrupted')
                return review()
            t=CatalogTools(source,out,page=page,attempt=attempt);t.render(page);t.direct(page)
            assert t.save(page,content().model_dump_json(),'page')['saved']
            return content()
    workers=Workers();source=pdf(tmp_path);out=tmp_path/'output'
    first=asyncio.run(convert(source,out,[1],workers));assert first['pages'][0]['status']=='failed'
    workers.fail=False
    final=asyncio.run(convert(source,out,[1],workers,resume=True))
    assert final['complete_for_selection'] and workers.calls==['extractor','reviewer','reviewer']


def test_false_pass_cannot_override_independent_values(tmp_path):
    """Fast unit: a confident judge must not certify mismatching cells; expected <1 s, max 5 s."""
    import pytest
    source=pdf(tmp_path);out=tmp_path/'out'
    t=CatalogTools(source,out);t.render(1);t.direct(1);bad=content();bad.tables[0].rows[0].cells[0].value=999
    assert t.save(1,bad.model_dump_json(),'page')['saved']
    r=CatalogTools(source,out,role='reviewer');r.render(1)
    with pytest.raises(ValueError):r.read(1,'page')
    assert r.save(1,content().model_dump_json(),'observation')['saved']
    disclosed=r.read(1,'page');assert disclosed['independent_comparison'][0]['source_observation']==80
    refused=r.save(1,review().model_dump_json(),'review');assert not refused['saved'] and refused['differences']
    assert not r.save(1,bad.model_dump_json(),'observation')['saved']


def test_independent_audit_catches_shift_and_missing_tolerance():
    """Fast unit: same dimensions/counts don't hide shifted values or diagram loss; expected <1 s, max 5 s."""
    from catalog_json.audit import compare_source
    from catalog_json.schema import Figure
    a=content();b=content();a.figures=[Figure(title='View',description='',labels=['H±2'])];b.figures=[Figure(title='View',description='H',labels=['H'])]
    assert any(d['path']=='figures[0].labels' for d in compare_source(a,b))


def test_minimax_preview_keeps_images_and_adaptive_reasoning():
    """Fast unit: prevent FastAgent silently stripping a supported model's image; expected <1 s, max 5 s."""
    from catalog_json.models import register_model_capabilities
    from fast_agent.llm.model_database import ModelDatabase
    register_model_capabilities()
    p=ModelDatabase.get_model_params('anthropic.MiniMax-M3.1-Flash-Preview?reasoning=low')
    assert p is not None and 'image/png' in p.tokenizes
    assert p.reasoning=='anthropic_thinking' and p.reasoning_effort_spec.allowed_efforts==['low','medium','high','xhigh','max']
    assert not p.anthropic_thinking_disable_supported


def test_observer_can_repair_own_error_only_after_new_source_view(tmp_path):
    """Fast unit: keep independence without freezing a mistaken observer forever; expected <1 s, max 5 s."""
    t=CatalogTools(pdf(tmp_path),tmp_path/'out');t.render(1);t.direct(1);assert t.save(1,content().model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1);wrong=content();wrong.tables[0].rows[0].cells[0].value=999
    assert r.save(1,wrong.model_dump_json(),'observation')['saved'];r.read(1,'page')
    assert not r.correct_observation(1,content().model_dump_json(),'Checked source')['saved']
    r.render(1,[0,0,1,1]);assert r.correct_observation(1,content().model_dump_json(),'Fresh source image shows correct value')['saved']
    assert json.loads((r.work(1)/'source-observation-0.json').read_text())['tables'][0]['rows'][0]['cells'][0]['value']==999
    assert not r.read(1,'page')['independent_comparison']
