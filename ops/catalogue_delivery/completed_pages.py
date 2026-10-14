from pathlib import Path
import json,hashlib,datetime

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def completed(root):
 root=Path(root);out=root/'.tmp/root-tail-review-20261014';selected={}
 for index in [*sorted(out.glob('index*.json')),*sorted(out.glob('shard-mod*/index*.json'))]:
  try:rows=json.loads(index.read_text()).get('pages',[])
  except (ValueError,OSError):continue
  for row in rows:
   rp=row.get('receipt',row.get('source_review'));cp=row.get('content',row.get('output'))
   if not rp or not cp:continue
   rp=Path(rp);cp=Path(cp);rp=rp if rp.is_absolute() else root/rp;cp=cp if cp.is_absolute() else root/cp
   proof=json.loads(rp.read_text());assert sha(rp)==row.get('receipt_sha256',row.get('source_review_sha256')),(index,'receipt SHA');assert sha(cp)==proof['output']['sha256']
   normal={**row,'catalog':proof.get('catalog','armature'),'physical_page':proof['physical_page'],'receipt':str(rp),'content':str(cp),'receipt_sha256':sha(rp),'content_sha256':sha(cp),'changed':bool(proof.get('corrections')),'cells_checked':proof['tables']['cells_checked'],'proof':proof}
   time=proof.get('completed_at',proof.get('reviewed_at',''));key=(normal['catalog'],normal['physical_page']);rank=(datetime.datetime.fromisoformat(time).timestamp() if time else 0,str(index))
   if key not in selected or rank>selected[key][0]:selected[key]=(rank,normal)
 return [v[1] for k,v in sorted(selected.items())]
