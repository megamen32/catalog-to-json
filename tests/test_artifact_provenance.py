"""Fast unit: runner identity is not artifact provenance; expected<1s/max5s."""
import hashlib,json
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
