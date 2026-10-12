"""One native FastAgent call in an isolated process; no cross-role global context."""
import argparse
import asyncio
from pathlib import Path
from .agents import AgentPair
from .tools import write_json


def main():
    p=argparse.ArgumentParser()
    for name in ('config','source','output','result'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('extractor','reviewer','role'):p.add_argument('--'+name,required=True)
    p.add_argument('--page',type=int,required=True);p.add_argument('--attempt',type=int,required=True)
    p.add_argument('--timeout',type=int,required=True);p.add_argument('--max-tokens',type=int,required=True)
    args=p.parse_args()
    try:
        agents=AgentPair(args.config,args.extractor,args.reviewer,args.timeout,args.max_tokens)
        artifact=asyncio.run(agents.run(args.role,args.source,args.output,args.page,args.attempt,feedback=args.role=='extractor' and args.attempt>0))
        write_json(args.result,{'status':'completed','artifact':artifact.model_dump()})
        return 0
    except (Exception,SystemExit) as exc:
        write_json(args.result,{'status':'failed','error':f'{type(exc).__name__}: {exc}'})
        return 2


if __name__=='__main__':raise SystemExit(main())
