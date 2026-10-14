from pathlib import Path
import json,hashlib,datetime
from catalog_json.schema import PageContent
from catalog_json.tools import write_json
r=Path.cwd();o=r/'.tmp/root-tail-review-20261014';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();rows=[]
from completed_pages import completed
for row in completed(r):
 if True:

  pg=row['physical_page'];rp=Path(row.get('receipt',row.get('source_review')));rp=rp if rp.is_absolute() else r/rp;cp=Path(row.get('content',row.get('output')));cp=cp if cp.is_absolute() else r/cp
  expected=row.get('receipt_sha256',row.get('source_review_sha256'));assert sha(rp)==expected,(pg,'receipt changed')
  proof=json.loads(rp.read_text());assert proof['physical_page']==pg;assert sha(cp)==proof['output']['sha256'];content=PageContent.model_validate_json(cp.read_bytes());w=r/'.tmp/full-digitization/staged-best-v1.4.8'/row['catalog']/f'page-{pg:04d}';basis=proof['basis_candidate'];assert basis['producer']['status']=='receipt_verified';assert any(sha(p)==basis['sha256'] for p in w.glob('candidate-*.json')),(pg,'native bytes unavailable');
  if proof['unchanged_native_candidate'] and not proof.get('corrections'):continue # genuinely unchanged source reviews use their original receipt
  a=w/'external-audit.json';data=json.loads(a.read_text()) if a.exists() else {'pdf_page':pg,'source_sha256':proof['source_sha256'],'findings':[]};assert data['source_sha256']==proof['source_sha256'];case=f'root-tail-full-source-correction-{pg}-20261014';ref=w/'root-reference-tail-20261014-r1.json';prov=w/'root-reference-tail-20261014-r1.provenance.json';existing=next((x for x in data['findings'] if isinstance(x,dict) and x.get('case_id')==case),None)
  if existing and existing.get('reference_sha256')!=proof['output']['sha256']:
   old_digest=existing['reference_sha256'];assert sha(ref)==old_digest
   retained=w/f'root-reference-retained-{old_digest}.json';retained.write_bytes(ref.read_bytes());retained.with_suffix('.provenance.json').write_bytes(prov.read_bytes())
   data.setdefault('retained_author_reference_revisions',[]).append({'sha256':old_digest,'reference':retained.name,'superseded_by':proof['output']['sha256'],'reason':'Author finalized a newer source-bound output; previous exact bytes and provenance retained.'})
   data['findings']=[f for f in data['findings'] if f.get('case_id')!=case];existing=None

  observation='Полный оригинал независимо сверил '+proof['reviewer']['session_id']+'. Готовый авторский PageContent в reference_data. Исправления: '+'; '.join(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False) for x in proof['corrections'])+' Это основа для самостоятельной сверки агентом по оригиналу, не автоматический PASS. Сохранять авторство и точные источник/страницу; изменять значения лишь при подтверждённой ошибке.'
  if not existing:
   ref.write_bytes(cp.read_bytes());write_json(prov,proof);data['findings'].append({'case_id':case,'path':'whole_page','observation':observation,'reference_data':content.model_dump(mode='json'),'reference_sha256':sha(cp),'reference_author':proof['reviewer']});write_json(a,data);action='installed'
  else:
   assert sha(ref)==sha(cp);action='already_present'
   prior_proof=json.loads(prov.read_text())
   material_keys=(set(prior_proof)|set(proof))-{'completed_at','external_audit_sha256'}
   if any(prior_proof.get(k)!=proof.get(k) for k in material_keys):
    # Evidence-only author revisions retain exactly the same PageContent.
    # Preserve the former receipt, refresh its evidence and attribution, and
    # keep the independent report bound to the unchanged content hash.
    old_proof_sha=sha(prov);retained=w/f'root-provenance-retained-{old_proof_sha}.json'
    if retained.exists():assert sha(retained)==old_proof_sha
    else:retained.write_bytes(prov.read_bytes())
    assert PageContent.model_validate(existing['reference_data']).model_dump()==content.model_dump()
    write_json(prov,proof);existing['reference_author']=proof['reviewer'];existing['observation']=observation
    history=data.setdefault('retained_author_provenance_revisions',[])
    entry={'reference_sha256':sha(cp),'prior_proof_sha256':old_proof_sha,'prior_proof':retained.name,'new_proof_sha256':sha(prov),'reason':'Evidence-only author revision; exact content and original producer retained.'}
    if entry not in history:history.append(entry)
    write_json(a,data);action='provenance_refreshed'
  rows.append({'catalog':row['catalog'],'physical_page':pg,'action':action,'author':proof['reviewer'],'reference_sha256':sha(cp),'native_candidate_sha256':basis['sha256'],'independently_accepted':False,'cells_checked':proof['tables']['cells_checked']})
write_json(o/'integration-latest.json',{'time':datetime.datetime.now().astimezone().isoformat(),'references':rows,'pages':len(rows),'native_bytes_preserved':True,'new_model_calls':0});print({'references':len(rows),'installed':[x['physical_page'] for x in rows if x['action']=='installed'],'provenance_refreshed':[f"{x['catalog']}:{x['physical_page']}" for x in rows if x['action']=='provenance_refreshed'],'cells_checked':sum(x['cells_checked'] for x in rows)})
