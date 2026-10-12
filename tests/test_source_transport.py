"""Focused integration: long source grids must reach SDK intact; expected2s/max15s."""
import json
import pytest
from catalog_json.tools import CatalogTools, source_chunk
from test_tools import pdf


def test_source_chunk_reassembles_cyrillic_without_skipping():
    text=json.dumps({'expanded_rows':[['Ток при импульсе 8/20, мкс']*12]*80},ensure_ascii=False)
    offset=0;parts=[]
    while offset<len(text):
        r=source_chunk(text,offset,16000)
        assert len(json.dumps(r,ensure_ascii=True,indent=2).encode())<=12000
        assert r['next_offset']>offset
        parts.append(r['text']);offset=r['next_offset']
    assert ''.join(parts)==text
    with pytest.raises(ValueError):source_chunk(text,-1,100)


def test_large_source_payload_is_immutable_paged_evidence(tmp_path):
    t=CatalogTools(pdf(tmp_path),tmp_path/'out')
    data={'tables':[{'expanded_rows':[['МПа']*20]*200}]}
    inventory=t.source_payload(1,'table',data)
    assert inventory['paged'] and 'tables' not in inventory
    offset=0;parts=[]
    while offset<inventory['total_characters']:
        chunk=t.source_artifact(1,inventory['artifact_id'],offset,16000)
        assert len(json.dumps(chunk,ensure_ascii=True,indent=2).encode())<=12000
        parts.append(chunk['text']);offset=chunk['next_offset']
    assert json.loads(''.join(parts))==data
    with pytest.raises(ValueError):t.source_artifact(1,'../bad',0,100)
