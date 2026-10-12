"""Fast unit: explicitly pinned old acceptance is historical, never relabelled (<1s/max5s)."""
import hashlib
import json
from types import SimpleNamespace

from catalog_json.schema import PageContent, Review, Check, CHECKS


def test_predecessor_acceptance_requires_both_actual_programs_and_current_source_audit(tmp_path):
    from catalog_json.staged import accepted_profile_agents
    value=PageContent(title='Source',text_blocks=[],tables=[],figures=[])
    review=Review(verdict='pass',checks=[Check(category=c,passed=True,evidence='Synthetic source') for c in CHECKS],issues=[],observed_table_count=0,observed_row_counts=[],observed_column_counts=[])
    programs={r:{'package_version':'old','source_code_sha256':r} for r in ('extractor','reviewer')}
    previous=SimpleNamespace(extractor='m',reviewer='r',contract_digest='combined-old',role_contracts={'extractor':'x','reviewer':'y'},role_runtimes={r:{'program':programs[r]} for r in programs})
    current=SimpleNamespace(extractor='m',reviewer='r',contract_digest='combined-new',role_contracts={'extractor':'new','reviewer':'y'},accepted_predecessor_profiles=[previous])
    events=[];digests={}
    for role,artifact,filename,tool in [('extractor',value,'candidate-0.json','save_page_json'),('reviewer',review,'review-0.json','save_review')]:
        path=tmp_path/filename;path.write_text(artifact.model_dump_json());digest=hashlib.sha256(path.read_bytes()).hexdigest();digests[role]=digest
        events.append({'tool':tool,'role':role,'page':1,'attempt':0,'source_sha256':'source','model':getattr(previous,role),'contract_sha256':previous.role_contracts[role],'sha256':digest,'time':10})
        call=tmp_path/'calls'/role;call.mkdir(parents=True);execution={'program':programs[role],'source_sha256':'source','physical_page':1,'attempt':0,'role':role,'model':getattr(previous,role),'contract_sha256':previous.role_contracts[role],'artifact_sha256':digest,'started_at':9,'finished_at':11}
        (call/'result.json').write_text(json.dumps({'status':'completed','execution':execution}))
    log=tmp_path/'tools.jsonl';log.write_text(''.join(json.dumps(e)+'\n' for e in events))
    old={'status':'accepted','pdf_page':1,'source_sha256':'source','extractor':'m','reviewer':'r','contract_sha256':'combined-old','role_contracts':previous.role_contracts,'next_attempt':0,'candidate_sha256':digests['extractor'],'review_sha256':digests['reviewer'],'content':value.model_dump()}
    assert accepted_profile_agents(tmp_path,old,current,'source',1) is previous
    assert old['contract_sha256']=='combined-old'
    for key,bad in [('pdf_page',2),('source_sha256','other'),('extractor','other'),('candidate_sha256','other')]:
        assert accepted_profile_agents(tmp_path,{**old,key:bad},current,'source',1) is None
    previous.role_runtimes['extractor']['program']={'package_version':'wrong'}
    assert accepted_profile_agents(tmp_path,old,current,'source',1) is None
    previous.role_runtimes['extractor']['program']=programs['extractor']
    current.accepted_predecessor_profiles=[]
    assert accepted_profile_agents(tmp_path,old,current,'source',1) is None
    current.accepted_predecessor_profiles=[previous]
    for superseded in events:
        log.write_text(''.join(json.dumps(e)+'\n' for e in events)+json.dumps({**superseded,'contract_sha256':'new','sha256':'newer','time':12})+'\n')
        assert accepted_profile_agents(tmp_path,old,current,'source',1) is None
    log.write_text(''.join(json.dumps(e)+'\n' for e in events))
    (tmp_path/'candidate-1.json').write_text('{}')
    assert accepted_profile_agents(tmp_path,old,current,'source',1) is None
    (tmp_path/'candidate-1.json').unlink()
    (tmp_path/'external-audit.json').write_text(json.dumps({'source_sha256':'source','pdf_page':1,'findings':['new source lead']}))
    assert accepted_profile_agents(tmp_path,old,current,'source',1) is None
    assert accepted_profile_agents(tmp_path,{**old,'status':'needs_review'},current,'source',1) is None
