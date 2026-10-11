import argparse
import asyncio
import json
from pathlib import Path
from .agents import AgentPair
from .pipeline import convert
from .export import to_html,to_xlsx


def parse_pages(spec,count):
    if spec=='all':return list(range(1,count+1))
    result=[]
    for group in spec.split(','):
        if '-' in group:
            a,b=map(int,group.split('-',1));result.extend(range(a,b+1))
        else:result.append(int(group))
    if not result or len(result)!=len(set(result)) or any(n<1 or n>count for n in result):raise ValueError('Invalid or repeated page selection')
    return result


def main():
    p=argparse.ArgumentParser(description='PDF catalogs → AnyDoc + FastAgent Vision → reviewed JSON')
    sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('convert');c.add_argument('input',type=Path);c.add_argument('--output',type=Path,required=True);c.add_argument('--pages',default='all');c.add_argument('--config',type=Path,required=True)
    c.add_argument('--extractor',default='zai.glm-5.3-flash?reasoning=low');c.add_argument('--reviewer',default='zai.glm-5.3-flash?reasoning=low');c.add_argument('--call-timeout',type=int,default=90);c.add_argument('--max-tokens',type=int,default=16384);c.add_argument('--max-repairs',type=int,default=None,help='Optional repair count for experiments; default: continue until accepted within the run deadline');c.add_argument('--deadline',type=int,default=180);c.add_argument('--resume',action='store_true')
    e=sub.add_parser('export');e.add_argument('input',type=Path);e.add_argument('--format',choices=['html','xlsx'],required=True);e.add_argument('--output',type=Path,required=True);e.add_argument('--allow-unverified',action='store_true')
    b=sub.add_parser('benchmark');bs=b.add_subparsers(dest='benchmark_command',required=True)
    scan=bs.add_parser('scan',help='Inventory every PDF page and render complex-page candidates')
    scan.add_argument('sources',type=Path,nargs='+');scan.add_argument('--output',type=Path,required=True)
    scan.add_argument('--per-catalog',type=int,default=3);scan.add_argument('--anchor',action='append',default=[],help='filename.pdf:physical_page')
    scan.add_argument('--deadline',type=int,default=180)
    args=p.parse_args()
    try:
        if args.command=='benchmark':
            from .difficulty import scan_catalogs,render_contacts
            if args.deadline<=0:raise ValueError('Deadline must be positive')
            anchors=set()
            for anchor in args.anchor:
                name,separator,page=anchor.rpartition(':')
                if not separator:raise ValueError('Anchor must be filename.pdf:physical_page')
                anchors.add((Path(name).name,int(page)))
            result=scan_catalogs(args.sources,args.output,args.per_catalog,anchors,args.deadline)
            contacts=render_contacts(result['candidates'],args.output) if result['complete'] else []
            print(json.dumps({'scanned_pages':result['scanned_pages'],'complete':result['complete'],'candidates':len(result['candidates']),'contacts':len(contacts)},ensure_ascii=False))
            return 0 if result['complete'] else 2
        if args.command=='export':
            data=json.loads(args.input.read_text());args.output.parent.mkdir(parents=True,exist_ok=True)
            (to_html if args.format=='html' else to_xlsx)(data,args.output,args.allow_unverified);print(args.output);return 0
        import pymupdf
        with pymupdf.open(args.input) as doc:pages=parse_pages(args.pages,len(doc))
        if args.deadline<=0 or args.call_timeout<=0:raise ValueError('Timeouts must be positive')
        agents=AgentPair(args.config,args.extractor,args.reviewer,args.call_timeout,args.max_tokens)
        result=asyncio.run(convert(args.input,args.output,pages,agents,args.max_repairs,args.resume,args.deadline))
        print(json.dumps({'output':str(args.output/'catalog.json'),'accepted':sum(p['status']=='accepted' for p in result['pages']),'requested':len(pages),'complete_for_selection':result['complete_for_selection'],'catalog_complete':result['catalog_complete']},ensure_ascii=False))
        return 0 if result['complete_for_selection'] else 2
    except (ValueError,OSError) as exc:
        p.exit(2,f'Error: {exc}\n')

if __name__=='__main__':raise SystemExit(main())
