import json
from collections import Counter

import pytest

from catalog_json.reconciliation.alignment import AlignmentError, build_review_packs, group_alignment


def fact(fid, side='ours', *, model='ШСИП', row=0, page=169, value='150/19', **kw):
    d = dict(fact_id=fid, side=side, source_sha256='pdf-a', catalog='armature',
             physical_pages=[] if page is None else [page], pointer='/'+fid,
             owner=model, kind='model_parameter', value=value, raw_value_type=type(value).__name__,
             raw={'header_path': [{'raw_text': 'Сечение', 'condition': 'только А'}],
                  'scope': 'model', 'row_evidence': [{'page': page, 'region': [.1,.704,.8,.742]}]})
    if side == 'ours':
        d.update(table_index=0, row_index=row)
    else:
        d.update(product_id='P1', group_id='G1', window_id='W1', observation_id=fid)
    d.update(kw)
    return d


def edge(ours, *oleg, status='ambiguous_alignment'):
    return dict(ours_fact_id=ours, oleg_fact_ids=list(oleg), status=status)


def test_subrows_are_one_scope_without_inventing_bijection():
    facts = [fact('O1'),fact('O2',row=1,value='150/24'),fact('O3',row=2,value='150/34'),
             fact('L1','oleg'),fact('L2','oleg',value='150/24'),fact('L3','oleg',value='150/34'),
             fact('L4','oleg',value='НАС-150-1Б'),fact('L5','oleg',value='НАС-150-2Б')]
    ledger = [edge('O1','L1','L2','L3','L4','L5'),edge('O2','L1','L2','L3'),edge('O3','L1','L2','L3')]
    scopes = list(group_alignment(facts, ledger))
    assert len(scopes) == 1
    s = scopes[0]
    assert s['classification'] == 'ambiguous_one_to_many'
    assert len(s['members']) == 3 and len(s['fact_refs']) == 8
    assert len([x for x in s['row_contexts'].values() if x['side']=='ours']) == 3
    assert s['members'][0]['oleg_fact_ids'] == ledger[0]['oleg_fact_ids']
    assert s['semantic_verdict'] is None and s['grouping_is_identity_merge'] is False
    assert 'raw' not in s['fact_refs']['L1']  # full exact variants remain in facts
    assert facts[3]['raw']['header_path'][0]['condition'] == 'только А'


def test_shared_candidate_downgrades_even_exact_rows():
    scopes = list(group_alignment([fact('O1'),fact('O2',row=1),fact('L1','oleg')],
                                 [edge('O1','L1',status='exact_agreement'),edge('O2','L1',status='exact_agreement')]))
    assert all(m['classification']=='ambiguous_one_to_many' for m in scopes[0]['members'])
    assert len(list(build_review_packs([fact('O1'),fact('O2',row=1),fact('L1','oleg')],
               [edge('O1','L1',status='exact_agreement'),edge('O2','L1',status='exact_agreement')],max_cases=2,max_bytes=20000))) == 1


def test_repeated_windows_remain_distinct_candidates():
    f = [fact('O'),fact('L1','oleg'),fact('L2','oleg',window_id='W2',product_id='P2')]
    s = next(group_alignment(f,[edge('O','L1','L2',status='exact_agreement')]))
    assert s['members'][0]['classification']=='ambiguous_one_to_many'
    assert len(s['row_contexts'])==3


def test_exact_representation_conflict_unmatched_and_literal_codes():
    f=[]; l=[]
    for i,(model,status) in enumerate([('D','exact_agreement'),('d','representation_difference'),
                                      ('А','value_or_applicability_conflict'),('A','unmatched_ours_observation')]):
        f.append(fact('O'+str(i),model=model))
        if i<3:
            f.append(fact('L'+str(i),'oleg',model=model));l.append(edge('O'+str(i),'L'+str(i),status=status))
        else:l.append(edge('O3',status=status))
    s=list(group_alignment(f,l))
    assert [x['classification'] for x in s]==['exact','representation','conflict','unmatched']
    assert [x['model_raw'] for x in s]==['D','d','А','A']
    packs=list(build_review_packs(f,l,max_cases=8,max_bytes=20000))
    assert sum(p['coverage']['ledger_members'] for p in packs)==3


def test_missing_evidence_uses_only_declared_range():
    f=[fact('L','oleg',page=None)]
    s=next(group_alignment(f,[edge(None,'L',status='unmatched_oleg_observation')],
        window_ranges={'W1': {'source_sha256':'pdf-a','start_page':167,'end_page':169}}))
    assert s['location']==dict(kind='declared_window_fallback',physical_pages=[],start_page=167,end_page=169,window_id='W1')
    assert s['fact_refs']['L']['location']['physical_pages']==[]
    unknown=next(group_alignment(f,[edge(None,'L',status='unmatched_oleg_observation')]))
    assert unknown['location']['kind']=='unlocated'
    with pytest.raises(AlignmentError,match='source mismatch'):
        list(group_alignment(f,[edge(None,'L',status='unmatched_oleg_observation')],
             window_ranges={'W1':dict(source_sha256='other',start_page=1,end_page=2)}))


def test_bounded_fragments_cover_every_occurrence_once(tmp_path):
    f=[fact('L','oleg')]+[fact('O'+str(i),row=i) for i in range(24)]
    l=[edge('O'+str(i),'L') for i in range(24)]
    l.append(dict(l[0]))  # a repeated ledger occurrence must survive
    fp=tmp_path/'facts.jsonl';lp=tmp_path/'ledger.jsonl'
    fp.write_text('\n'.join(json.dumps(x) for x in f));lp.write_text('\n'.join(json.dumps(x) for x in l))
    packs=list(build_review_packs(fp,lp,max_cases=2,max_bytes=6000))
    assert len(packs)>1
    assert all(len(json.dumps(p,ensure_ascii=False,separators=(',',':')).encode())+1<=6000 for p in packs)
    assert all(len(p['cases'])<=2 for p in packs)
    members=[m for p in packs for c in p['cases'] for m in c['members']]
    assert Counter(m['input_row_index'] for m in members)==Counter(range(25))
    assert len({m['member_ledger_id'] for m in members})==25
    assert len({c['scope_id'] for p in packs for c in p['cases']})==1
    assert all(m['oleg_fact_ids']==['L'] for m in members)


def test_page_packs_and_cross_page_candidates_are_not_relocated():
    f=[fact('O1',page=1),fact('O2',page=2),fact('L1','oleg',page=3),fact('L2','oleg',page=2)]
    packs=list(build_review_packs(f,[edge('O1','L1'),edge('O2','L2')],max_cases=10,max_bytes=20000))
    assert len(packs)==2
    case=packs[0]['cases'][0]
    assert case['row_contexts'][case['fact_refs']['L1']['context_id']]['location']['physical_pages']==[3]
    assert case['physical_pages']==[1,3]
    assert packs[0]['executable_adjudication'] is False


@pytest.mark.parametrize('f,l,message',[
    ([fact('O')],[edge('O','missing')],'Unknown'),
    ([fact('O'),fact('O')],[edge('O')],'Duplicate fact'),
    ([fact('O'),fact('L','oleg',source_sha256='other')],[edge('O','L')],'Cross-source'),
    ([fact('O'),fact('L','oleg')],[edge('O','L','L')],'Duplicate or invalid'),
    ([fact('O'),fact('L','oleg')],[edge('O')],'facts absent'),
    ([fact('L','oleg')],[edge('L')],'wrong side'),
])
def test_invalid_coverage_never_silently_drops_records(f,l,message):
    with pytest.raises(AlignmentError,match=message):list(group_alignment(f,l))


def test_oversized_single_member_fails_without_truncation():
    with pytest.raises(AlignmentError,match='Single ledger member'):
        list(build_review_packs([fact('O')],[edge('O',status='unmatched_ours_observation')],max_cases=1,max_bytes=100))


def test_shared_candidate_across_literal_model_scopes_stays_ambiguous():
    f=[fact('O1',model='D',row=0),fact('O2',model='D ',row=1),fact('L','oleg',model='D')]
    groups=list(group_alignment(f,[edge('O1','L',status='exact_agreement'),edge('O2','L',status='exact_agreement')]))
    assert len(groups)==2
    assert all(g['classification']=='ambiguous_one_to_many' for g in groups)


def test_fallback_index_cannot_be_executed_as_adjudication_pack():
    packs=list(build_review_packs([fact('L','oleg',page=None)],
        [edge(None,'L',status='unmatched_oleg_observation')],max_cases=1,max_bytes=10000,
        window_ranges={'W1':dict(start_page=167,end_page=169)}))
    c=packs[0]['cases'][0]
    assert c['physical_pages']==[] and c['kind']=='unresolved_alignment'
    assert c['source_bound'] is False
    assert c['location']['start_page']==167
    assert packs[0]['executable_adjudication'] is False
    assert packs[0]['requires_fact_hydration'] is True


def test_gzip_inputs_preserve_all_ledger_occurrences(tmp_path):
    import gzip
    f=[fact('O1'),fact('O2',row=1),fact('L','oleg')]
    l=[edge('O1','L'),edge('O2','L')]
    fp=tmp_path/'facts.jsonl.gz';lp=tmp_path/'ledger.jsonl.gz'
    for path, records in [(fp,f),(lp,l)]:
        with gzip.open(path,'wt',encoding='utf-8') as stream:
            for record in records:stream.write(json.dumps(record,ensure_ascii=False)+'\n')
    groups=list(group_alignment(fp,lp))
    assert [m['input_row_index'] for m in groups[0]['members']]==[0,1]
    assert groups[0]['classification']=='ambiguous_one_to_many'
    assert len(groups[0]['fact_refs'])==3
