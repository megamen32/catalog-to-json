"""Fast unit: runner identity is not artifact provenance; expected<1s/max5s."""
import hashlib,json
import pytest
from catalog_json.provenance import artifact_origin


def test_old_source_bound_save_does_not_invent_a_program_version(tmp_path):
    path=tmp_path/'candidate-0.json';path.write_text('{}')
    event={'tool':'save_page_json','role':'extractor','page':1,'attempt':0,'source_sha256':'source','model':'model','contract_sha256':'contract','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'time':10}
    (tmp_path/'tools.jsonl').write_text(json.dumps(event)+'\n')
    origin=artifact_origin(tmp_path,path,'source',1,0,'extractor','model','contract')
    assert origin['status']=='producer_unknown' and origin['program'] is None
    assert origin['source_bound_save'] and origin['artifact_sha256']==event['sha256']


def test_receipt_binds_actual_program_to_matching_saved_bytes(tmp_path):
    path=tmp_path/'candidate-0.json';path.write_text('{}');digest=hashlib.sha256(path.read_bytes()).hexdigest()
    event={'tool':'save_page_json','role':'extractor','page':1,'attempt':0,'source_sha256':'source','model':'model','contract_sha256':'contract','sha256':digest,'time':10}
    (tmp_path/'tools.jsonl').write_text(json.dumps(event)+'\n')
    execution={'program':{'package_version':'earlier'},'source_sha256':'source','physical_page':1,'attempt':0,'role':'extractor','model':'model','contract_sha256':'contract','artifact_sha256':digest,'started_at':9,'finished_at':11}
    call=tmp_path/'calls'/'x';call.mkdir(parents=True);(call/'result.json').write_text(json.dumps({'status':'completed','execution':execution}))
    origin=artifact_origin(tmp_path,path,'source',1,0,'extractor','model','contract')
    assert origin['status']=='receipt_verified' and origin['program']=={'package_version':'earlier'}
    for key,value in [('model','other'),('source_sha256','other'),('contract_sha256','other'),('artifact_sha256','other'),('started_at',11)]:
        altered={**execution,key:value};(call/'result.json').write_text(json.dumps({'status':'completed','execution':altered}))
        assert artifact_origin(tmp_path,path,'source',1,0,'extractor','model','contract')['program'] is None


def test_no_save_or_superseded_save_cannot_claim_verified_producer(tmp_path):
    path=tmp_path/'candidate-0.json';path.write_text('{}');digest=hashlib.sha256(path.read_bytes()).hexdigest()
    event={'tool':'save_page_json','role':'extractor','page':1,'attempt':0,'source_sha256':'source','model':'model','contract_sha256':'contract','sha256':digest,'time':10}
    (tmp_path/'tools.jsonl').write_text(json.dumps(event)+'\n'+json.dumps({**event,'sha256':'newer','time':11})+'\n')
    assert not artifact_origin(tmp_path,path,'source',1,0,'extractor','model','contract')['source_bound_save']


def test_fresh_routed_native_call_refuses_wrong_receipt_fields(tmp_path):
    from catalog_json.staged import validate_role_receipt
    from catalog_json.schema import PageContent
    value=PageContent(title='Source',text_blocks=[],tables=[],figures=[]);path=tmp_path/'candidate-0.json';path.write_text(value.model_dump_json());digest=hashlib.sha256(path.read_bytes()).hexdigest()
    event={'tool':'save_page_json','role':'extractor','page':1,'attempt':0,'source_sha256':'source','model':'model','contract_sha256':'contract','sha256':digest,'time':10}
    (tmp_path/'tools.jsonl').write_text(json.dumps(event)+'\n');program={'package_version':'earlier','source_code_sha256':'actual'}
    execution={'program':program,'source_sha256':'source','physical_page':1,'attempt':0,'role':'extractor','model':'model','contract_sha256':'contract','artifact_sha256':digest,'started_at':9,'finished_at':11}
    call=tmp_path/'calls/x';call.mkdir(parents=True);data={'status':'completed','execution':execution,'artifact':value.model_dump()};(call/'result.json').write_text(json.dumps(data))
    assert validate_role_receipt(data,tmp_path,path,'source',1,0,'extractor','model','contract',program)['program']==program
    for key,bad in [('source_sha256','other'),('physical_page',2),('attempt',1),('role','reviewer'),('model','other'),('contract_sha256','other'),('artifact_sha256','other'),('program',None)]:
        altered={**data,'execution':{**execution,key:bad}}
        with pytest.raises(RuntimeError):validate_role_receipt(altered,tmp_path,path,'source',1,0,'extractor','model','contract',program)


def test_delivery_only_accepted_reuse_requires_unchanged_current_audit(tmp_path):
    from types import SimpleNamespace
    from catalog_json.staged import compatible_accepted_profile
    from catalog_json.schema import PageContent,Review,Check,CHECKS
    value=PageContent(title='Source',text_blocks=[],tables=[],figures=[])
    review=Review(verdict='pass',checks=[Check(category=c,passed=True,evidence='Synthetic source') for c in CHECKS],issues=[],observed_table_count=0,observed_row_counts=[],observed_column_counts=[])
    events=[];digests={};program={'package_version':'earlier','source_code_sha256':'original'}
    agents=SimpleNamespace(extractor='m',reviewer='r',contract_digest='combined',role_contracts={'extractor':'x','reviewer':'y'})
    for role,artifact,filename,model,contract,tool in [('extractor',value,'candidate-0.json','m','x','save_page_json'),('reviewer',review,'review-0.json','r','y','save_review')]:
        path=tmp_path/filename;path.write_text(artifact.model_dump_json());digest=hashlib.sha256(path.read_bytes()).hexdigest();digests[role]=digest
        events.append({'tool':tool,'role':role,'page':1,'attempt':0,'source_sha256':'source','model':model,'contract_sha256':contract,'sha256':digest,'time':10})
        call=tmp_path/'calls'/role;call.mkdir(parents=True);execution={'program':program,'source_sha256':'source','physical_page':1,'attempt':0,'role':role,'model':model,'contract_sha256':contract,'artifact_sha256':digest,'started_at':9,'finished_at':11};(call/'result.json').write_text(json.dumps({'status':'completed','execution':execution}))
    log=tmp_path/'tools.jsonl';log.write_text(''.join(json.dumps(e)+'\n' for e in events))
    old={'status':'accepted','pdf_page':1,'source_sha256':'source','extractor':'m','reviewer':'r','contract_sha256':'combined','role_contracts':agents.role_contracts,'next_attempt':0,'candidate_sha256':digests['extractor'],'review_sha256':digests['reviewer'],'content':value.model_dump()}
    assert compatible_accepted_profile(tmp_path,old,agents,'source',1)
    assert not compatible_accepted_profile(tmp_path,{**old,'pdf_page':2},agents,'source',1)
    audit=tmp_path/'external-audit.json';audit.write_text('new original-source lead')
    assert not compatible_accepted_profile(tmp_path,old,agents,'source',1)
    event={**events[-1],'tool':'read_external_audit','sha256':hashlib.sha256(audit.read_bytes()).hexdigest()};events.insert(-1,event);log.write_text(''.join(json.dumps(e)+'\n' for e in events))
    assert compatible_accepted_profile(tmp_path,old,agents,'source',1)
    audit.write_text('changed lead');assert not compatible_accepted_profile(tmp_path,old,agents,'source',1)
