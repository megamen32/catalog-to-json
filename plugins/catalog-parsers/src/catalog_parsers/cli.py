import argparse
import json
from pathlib import Path
from .parser import parse


def main():
    p=argparse.ArgumentParser(description='Direct parser benchmark adapter; canonical output and raw JSON are retained')
    p.add_argument('--source',type=Path,required=True);p.add_argument('--page',type=int,required=True)
    p.add_argument('--backend',choices=['docling','pymupdf4llm'],required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',default='not-applicable');p.add_argument('--resume',action='store_true')
    a=p.parse_args();r=parse(a.source,a.page,a.backend,a.output,a.model,a.resume)
    print(json.dumps(r,ensure_ascii=False));return 0 if r['status']=='completed' else 2
