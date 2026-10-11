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
    r=CatalogTools(t.source,t.output,role='reviewer');r.render(1);r.read(1,'page')
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
