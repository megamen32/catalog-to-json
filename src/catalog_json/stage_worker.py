"""One native FastAgent call in an isolated process; no cross-role global context."""
import argparse
import asyncio
import hashlib
import time
from contextlib import contextmanager
import json
from pathlib import Path
from .agents import AgentPair
from .tools import write_json
from .provenance import program_version


@contextmanager
def provider_retry_observer(callback):
    """Observe pinned FastAgent retry telemetry without changing its retry behavior."""
    from fast_agent.llm import fastagent_llm
    from openai._base_client import BaseClient as OpenAIBaseClient
    from anthropic._base_client import BaseClient as AnthropicBaseClient
    original=fastagent_llm.provider_retry
    retry_methods={cls:cls._should_retry for cls in (OpenAIBaseClient,AnthropicBaseClient)}
    def observed(error,*args,**kwargs):
        if getattr(error,'status_code',None)==429 or type(error).__name__=='RateLimitError':callback()
        return original(error,*args,**kwargs)
    fastagent_llm.provider_retry=observed
    # The underlying provider SDK can retry a429 and return success before
    # FastAgent receives an error. Keep each SDK's existing retry decision.
    def wrap(method):
        def should_retry(client,response):
            if response.status_code==429:callback()
            return method(client,response)
        return should_retry
    for cls,method in retry_methods.items():cls._should_retry=wrap(method)
    try:yield
    finally:
        fastagent_llm.provider_retry=original
        for cls,method in retry_methods.items():cls._should_retry=method


def main():
    p=argparse.ArgumentParser()
    for name in ('config','source','output','result'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('extractor','reviewer','role'):p.add_argument('--'+name,required=True)
    p.add_argument('--page',type=int,required=True);p.add_argument('--attempt',type=int,required=True)
    p.add_argument('--timeout',type=int,required=True);p.add_argument('--max-tokens',type=int,required=True)
    args=p.parse_args()
    started=time.time();program=program_version();rate_limit_events=[]
    def rate_limited():
        event={'catalog_worker_event':'provider_rate_limit','time':time.time(),'role':args.role,'http_status':429}
        rate_limit_events.append(event);print(json.dumps(event),flush=True)
    try:
        agents=AgentPair(args.config,args.extractor,args.reviewer,args.timeout,args.max_tokens)
        with provider_retry_observer(rate_limited):
            artifact=asyncio.run(agents.run(args.role,args.source,args.output,args.page,args.attempt,feedback=args.role=='extractor' and args.attempt>0))
        current=program_version()
        if current!=program:raise RuntimeError('Worker program changed during the native call')
        filename=f'candidate-{args.attempt}.json' if args.role=='extractor' else f'review-{args.attempt}.json'
        execution={'program':program,'source_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(),
                   'physical_page':args.page,'attempt':args.attempt,'role':args.role,
                   'model':getattr(agents,args.role),'contract_sha256':agents.contract_digest,
                   'artifact_sha256':hashlib.sha256((args.output/f'page-{args.page:04d}'/filename).read_bytes()).hexdigest(),
                   'started_at':started,'finished_at':time.time(),'provider_rate_limit_events':len(rate_limit_events)}
        write_json(args.result,{'status':'completed','artifact':artifact.model_dump(),'execution':execution})
        return 0
    except (Exception,SystemExit) as exc:
        write_json(args.result,{'status':'failed','error':f'{type(exc).__name__}: {exc}'})
        return 2


if __name__=='__main__':raise SystemExit(main())
