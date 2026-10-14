from pathlib import Path
import json,hashlib,datetime
from completed_pages import completed,sha
from catalog_json.schema import PageContent
from catalog_json.tools import write_json
r=Path.cwd();o=r/'.tmp/root-tail-review-20261014';pages=completed(r);states=[]
reports=[]
for folder in [o/'independent-reviews',*sorted(o.glob('shard-mod*/independent-reviews'))]:
 for f in folder.glob('*review*.json'):
  try:d=json.loads(f.read_text())
  except (OSError,ValueError):continue
  if isinstance(d,dict) and d.get('schema_version')=='catalogue-independent-source-review/1':
   d['reviewed_json_sha256']=d.get('reviewed_json_sha256',d.get('exact_reviewed_sha256',d.get('exact_candidate_sha256')))
   d['reviewed_input_frozen']=d.get('reviewed_input_frozen',d.get('frozen_reviewed_path',d.get('candidate_frozen_file')))
   d['original_image']=d.get('original_image',d.get('original_image_file',d.get('source_image')))
   d['time']=d.get('time',d.get('reviewed_at'));d['issues']=d.get('issues',d.get('errors',[]));d['unresolved_issues']=d.get('unresolved_issues',d.get('uncertainties',[]))
   tables=d.get('observed_tables',{});d['observed_row_counts']=d.get('observed_row_counts',tables.get('row_counts'));d['observed_column_counts']=d.get('observed_column_counts',tables.get('column_counts'));d['total_cells_checked']=d.get('total_cells_checked',d.get('cells_checked',tables.get('cells_checked')))
   evidence=d.get('technical_and_meaning_review',d.get('source_findings',''))
   d['checks']={k:({'passed':v,'evidence':evidence} if isinstance(v,bool) else v) for k,v in d['checks'].items()}
   d['dimension_ownership']=d.get('dimension_ownership',d.get('per_figure_dimension_ownership',[]))
   for group in d['dimension_ownership']:
    for dim in group.get('dimensions',[]):dim['literal']=dim.get('literal',dim.get('literal_label'));dim['actual_target']=dim.get('actual_target',dim.get('target'))
   reports.append((f,d))
for row in pages:
 p=Path(row['content']);content=PageContent.model_validate_json(p.read_bytes());author=row['proof']['reviewer']['session_id'];matches=[]
 for f,d in reports:
  if (d.get('catalog')!=row['catalog'] or d.get('physical_page')!=row['physical_page'] or d.get('source_sha256')!=row['proof']['source_sha256'] or d.get('reviewed_json_sha256')!=sha(p)):continue
  matches.append((d.get('time',''),f,d))
 if not matches:continue
 _,f,d=max(matches,key=lambda x:x[0])
 assert d['independent_author']!=author and d.get('origin_author') in (author,'root'),(f,'independence')
 frozen=Path(d['reviewed_input_frozen']);assert sha(frozen)==sha(p);image=Path(d['original_image']);assert sha(image)==d['original_image_sha256'];assert d['full_original_image_review'] is True
 assert d['observed_row_counts']==[len(t.rows) for t in content.tables] and d['observed_column_counts']==[len(t.columns) for t in content.tables];assert d['total_cells_checked']==sum(len(t.rows)*len(t.columns) for t in content.tables)
 checks=d['checks'];assert set(checks)=={'all_text_and_meaning','all_table_cells','headers_units_conditions','merged_cells_and_blanks','figures_and_relationships','source_provenance'}
 if d['verdict']=='pass':
  assert not d.get('issues') and not d.get('unresolved_issues') and not content.uncertainties
  assert all(v.get('passed') is True and v.get('evidence') for v in checks.values())
  for group in d.get('dimension_ownership',[]):
   for dim in group.get('dimensions',[]):
    assert dim.get('literal') and dim.get('actual_target');box=dim.get('source_bbox');assert len(box)==4 and 0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1
 w=r/'.tmp/full-digitization/staged-best-v1.4.8'/row['catalog']/f"page-{row['physical_page']:04d}";target=w/f'manual-independent-review-{sha(f)}.json';target.write_bytes(f.read_bytes());a=w/'external-audit.json'
 if a.exists():
  data=json.loads(a.read_text());changed=False
  for lead in data.get('findings',[]):
   if lead.get('reference_sha256')==sha(p):
    item={'verdict':d['verdict'],'author':d['independent_author'],'reviewed_reference_sha256':sha(p),'report_sha256':sha(f),'report':target.name,'issues':d.get('issues',[]),'full_original_image_review':True,'provider_model_call':False}
    if lead.get('independent_source_review')!=item:lead['independent_source_review']=item;changed=True
  if changed:write_json(a,data)
 states.append({'catalog':row['catalog'],'physical_page':row['physical_page'],'verdict':d['verdict'],'source_sha256':d['source_sha256'],'content':str(p),'content_sha256':sha(p),'author':author,'reviewer':d['independent_author'],'review':str(f),'review_sha256':sha(f),'cells_checked':d['total_cells_checked'],'native_provider_receipt':False})
write_json(o/'independent-status.json',{'time':datetime.datetime.now().astimezone().isoformat(),'pages':states,'passed':sum(x['verdict']=='pass' for x in states),'revise':sum(x['verdict']=='revise' for x in states),'native_outputs_untouched':True,'model_calls':0});print({'passed':sum(x['verdict']=='pass' for x in states),'revise':sum(x['verdict']=='revise' for x in states),'reports':len(reports)})
