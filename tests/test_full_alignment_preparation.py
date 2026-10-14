"""Fast unit: full scope cannot silently turn into a hand-picked sample.

Expected1s, emergency10s; preparation never invokes a model or approves a match.
"""
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('full_alignment', Path(__file__).resolve().parents[1]/
    'ops/catalogue_delivery/prepare_full_alignment.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def write_rows(file, rows):
    with gzip.open(file, 'wt') as stream:
        for row in rows: stream.write(json.dumps(row)+'\n')


def test_all_pages_facts_unlocated_and_ledger_rows_survive(tmp_path):
    facts = []
    for fid, side, pages, value in [('O1','ours',[1],None), ('L1','oleg',[1,2],''),
                                    ('L2','oleg',[],'–')]:
        facts.append({'fact_id':fid,'side':side,'catalog':'opn','kind':'model_parameter',
            'pointer':fid,'owner':'A','name':'D','unit':'мм','condition':None,
            'physical_pages':pages,'source_sha256':'a'*64,'value':value,'raw':'literal raw text'})
    f=tmp_path/'facts.gz'; l=tmp_path/'ledger.gz'
    write_rows(f,facts)
    ledger=[{'ours_fact_id':'O1','oleg_fact_ids':['L1'],'status':'ambiguous_alignment'},
            {'ours_fact_id':None,'oleg_fact_ids':['L2'],'status':'unmatched_oleg_observation'}]
    write_rows(l,ledger)
    out=tmp_path/'work'; result=module.prepare(f,l,{'a'*64:{'page_count':3}},out)
    assert result['physical_pages']==3
    assert result['unlocated_work_packets']==1
    assert result['unique_original_facts']==3
    assert result['ledger_rows']==2
    assert result['unmatched_or_ambiguous_our_model_parameters']==1
    packets=[json.loads((out/i['path']).read_text()) for i in result['pages']]
    assert sorted(r['ledger_ordinal'] for p in packets for r in p['ledger_rows'])==[1,2]
    assert {f['fact_id'] for p in packets for f in p['facts']}=={'O1','L1','L2'}
    assert next(f['value'] for p in packets for f in p['facts'] if f['fact_id']=='O1') is None
    assert result['preparation_accepts_no_facts'] is True
    assert all(p['owner']=='zcode' for p in packets)
    assert any('literal raw text' in p['contexts'].values() for p in packets)


def test_missing_original_fact_is_not_hidden(tmp_path):
    f=tmp_path/'facts.gz';l=tmp_path/'ledger.gz';write_rows(f,[])
    write_rows(l,[{'ours_fact_id':'missing','oleg_fact_ids':[],'status':'unmatched_ours_observation'}])
    with pytest.raises((ValueError,KeyError)):
        module.prepare(f,l,{},tmp_path/'work')
