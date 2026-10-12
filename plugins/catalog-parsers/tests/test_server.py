"""Focused integration: source/page binding and failed raw evidence, expected <1s/max 5s."""
import asyncio,hashlib,json
import pytest
from catalog_parsers.server import build_server


def test_read_rejects_other_page_and_accepts_hashed_failed_native_raw(tmp_path):
    source=tmp_path/'source.pdf';source.write_bytes(b'source')
    key='a'*64;directory=tmp_path/'cache'/key;directory.mkdir(parents=True)
    raw=directory/'native-raw.json';raw.write_text('{"native":"preserved"}')
    receipt={'status':'failed','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'physical_page':2,'native_raw_artifact':raw.name,'native_raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest()}
    (directory/'receipt.json').write_text(json.dumps(receipt))
    async def check():
        server=build_server(source,1,tmp_path/'cache')
        with pytest.raises(Exception,match='another page'):await server.call_tool('read_parser_artifact',{'artifact_id':key,'kind':'raw'})
        server=build_server(source,2,tmp_path/'cache')
        value=await server.call_tool('read_parser_artifact',{'artifact_id':key,'kind':'raw'})
        assert 'preserved' in str(value)
        raw.write_text('altered')
        with pytest.raises(Exception,match='digest mismatch'):await server.call_tool('read_parser_artifact',{'artifact_id':key,'kind':'raw'})
    asyncio.run(check())


def test_unicode_reader_fits_sdk_budget_without_losing_middle(tmp_path):
    """Focused integration: Cyrillic/escapes were cut by SDK; expected <1s/max 5s."""
    key='b'*64;directory=tmp_path/'cache'/key;directory.mkdir(parents=True)
    text=json.dumps({'rows':['Проводимость 😀\\\"\n'*4000,'LAST-ROW']},ensure_ascii=False)
    candidate=directory/'candidate.json';candidate.write_text(text)
    (directory/'receipt.json').write_text(json.dumps({'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest()}))
    async def check():
        server=build_server(cache_root=tmp_path/'cache');offset=0;chunks=[]
        while offset<len(text):
            result=await server.call_tool('read_parser_artifact',{'artifact_id':key,'offset':offset,'length':24000})
            content=result[0] if isinstance(result,tuple) else result
            block=next(b for b in content if b.type=='text')
            assert len(block.text.encode())<=12000
            payload=json.loads(block.text)
            assert payload['next_offset']>offset
            assert payload['next_offset']==offset+len(payload['text'])
            chunks.append(payload['text']);offset=payload['next_offset']
        assert ''.join(chunks)==text
    asyncio.run(check())
