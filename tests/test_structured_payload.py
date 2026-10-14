"""Focused MCP integration: encoded-string failure shield, expected5s/max50s."""
import asyncio,json,os,sys
from pathlib import Path
import pymupdf
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from catalog_json.schema import CHECKS


def test_native_file_tools_accept_objects_and_retain_guards(tmp_path):
    source=tmp_path/'source.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((30,50),'Source')
        doc.save(source)
    out=tmp_path/'out'
    data={'title':'Source','text_blocks':[{'kind':'heading','text':'Source'}],
          'tables':[],'figures':[],'source_notes':[],'uncertainties':[]}
    def payload(result):
        texts=[x.text for x in result.content if x.type=='text']
        assert texts and texts[0].startswith('{'),texts
        return json.loads(texts[0])
    async def run(role):
        params=StdioServerParameters(command=sys.executable,args=['-m','catalog_json.tools',
            '--source',str(source),'--output',str(out),'--role',role,'--page','1'],env=dict(os.environ))
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as s:
                await s.initialize();names={x.name:x for x in (await s.list_tools()).tools}
                name='save_page_json' if role=='extractor' else 'save_source_observation'
                assert 'data' in names[name].input_schema['properties']
                await s.call_tool('load_skill',{});await s.call_tool('view_page',{'page':1})
                if role=='extractor':await s.call_tool('extract_direct',{'page':1})
                both=payload(await s.call_tool(name,{'page':1,'data':data,'json_text':json.dumps(data)}))
                assert both['saved'] is False and 'exactly one' in both['error']
                bad=payload(await s.call_tool(name,{'page':1,'data':{**data,'invented_field':True}}))
                assert not bad['saved'] and bad['validation_errors']
                broken=payload(await s.call_tool(name,{'page':1,'json_text':'{"title":"unfinished"'}))
                assert not broken['saved'] and broken['validation_errors']
                assert not (out/'page-0001'/('candidate-0.json' if role=='extractor' else 'source-observation-0.json')).exists()
                saved=payload(await s.call_tool(name,{'page':1,'data':data}));assert saved['saved']
                assert payload(await s.call_tool(name,{'page':1,'json_text':json.dumps(data)}))['saved']
                if role=='extractor':
                    assert payload(await s.call_tool('save_section',{'page':1,'section':'text_blocks','index':0,'data':data['text_blocks'][0]}))['saved']
                else:
                    await s.call_tool('read_page_json',{'page':1})
                    # Native blind-disclosure and strict PASS guards still run.
                    frozen=payload(await s.call_tool(name,{'page':1,'data':data}));assert not frozen['saved'] and 'frozen' in frozen['error']
                    assert not payload(await s.call_tool('record_dimension_review',{'page':1,'data':{}}))['saved']
                    assert not payload(await s.call_tool('record_dimension_reviews',{'page':1,'data':{'shared':{},'records':[{}]}}))['saved']
                    invalid=payload(await s.call_tool('save_review',{'page':1,'data':{'verdict':'pass'}}));assert not invalid['saved']
                    await s.call_tool('view_region',{'page':1,'box':[0.,0.,1.,1.]})
                    revised=payload(await s.call_tool('correct_source_observation',{'page':1,'data':data,'reason':'Fresh original confirms Source heading'}));assert revised['saved']
                    review={'verdict':'pass','checks':[{'category':c,'passed':True,'evidence':'Compared the original plain heading'} for c in sorted(CHECKS)],'issues':[],
                            'observed_table_count':0,'observed_row_counts':[],'observed_column_counts':[]}
                    assert payload(await s.call_tool('save_review',{'page':1,'data':review}))['saved']
    asyncio.run(run('extractor'));asyncio.run(run('reviewer'))
