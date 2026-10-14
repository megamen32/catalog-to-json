"""Fast unit: one owner's work cannot hide omissions or claim a later audit.

Expected1s/emergency10s; no providers, no model benchmark.
"""
import copy
import pytest
from catalog_json.reconciliation.page_work import validate_page_work


@pytest.fixture
def inputs():
    packet={'owner':'codex','catalog':'test','source_sha256':'a'*64,'physical_page':1,
        'facts':[{'side':'ours','fact_id':'O1','value':None},
                 {'side':'oleg','fact_id':'L1','value':'–'}], 'ledger_rows':[]}
    proposal={'work_packet_sha256':'b'*64,'source_sha256':'a'*64,'physical_page':1,
        'source_evidence':[{'bbox':[0,0,1,1],'observation':'Source cell empty, dash belongs to neighbour'}],
        'groups':[{'fact_indices':[0,1],'relation':'same_fact','keep':'ours',
                   'reason':'Same property, original empty cell supported','evidence_refs':[0]}]}
    identity={'role':'codex','session_id':'fixture','model':'fixture','runtime':'test'}
    return packet, proposal, identity


def test_complete_work_retains_source_and_defers_final_audit(inputs):
    packet, proposal, identity=inputs; before=copy.deepcopy(packet)
    result=validate_page_work(packet,proposal,packet_sha256='b'*64,identity=identity)
    assert packet==before
    assert result['selected_fact_indices']==[0]
    assert result['all_input_facts_accounted_for']
    assert result['independent_final_review_complete'] is False
    assert result['original_alternatives_retained']


@pytest.mark.parametrize('defect',['missing','duplicate','wrong-owner','changed-input','unbound-value'])
def test_incomplete_or_unbound_work_refused(inputs,defect):
    packet,proposal,identity=inputs
    if defect=='missing':proposal['groups'][0]['fact_indices']=[0]
    if defect=='duplicate':proposal['groups'][0]['fact_indices']=[0,1,1]
    if defect=='wrong-owner':identity['role']='zcode'
    if defect=='changed-input':proposal['work_packet_sha256']='c'*64
    if defect=='unbound-value':proposal['groups'][0]['new_value']='invented'
    with pytest.raises(ValueError):validate_page_work(packet,proposal,packet_sha256='b'*64,identity=identity)


def test_overlapping_exact_pairs_seed_one_group_without_losing_variants(inputs):
    packet,proposal,identity=inputs
    packet['facts']=[{'side':'ours','fact_id':'O1','value':'12'},
                     {'side':'oleg','fact_id':'L1','value':'12'},
                     {'side':'ours','fact_id':'O2','value':'12'}]
    packet['ledger_rows']=[{'ours_fact_id':fid,'oleg_fact_ids':['L1'],'status':'exact_agreement'} for fid in ['O1','O2']]
    proposal.update(groups=[],reuse_exact_agreements=True)
    result=validate_page_work(packet,proposal,packet_sha256='b'*64,identity=identity)
    assert result['selected_fact_indices']==[0,2]
    assert len(result['groups'])==1
