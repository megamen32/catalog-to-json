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
