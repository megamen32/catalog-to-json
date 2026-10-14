"""The same original-page tools and bounded work packet for every page owner.

One stdio instance belongs to one immutable page and trusted caller identity.
Staging never accepts a page; finish requires complete accounting and an actual
original image call. Final independent review remains explicitly pending.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource

from ..operator_tools import OperatorTools, server
from .page_work import baseline_seed_groups, save_page_work, validate_page_work


class PageWorkTools:
    def __init__(self, packet, sources, identity, output):
        self.path = Path(packet).resolve()
        self.raw = self.path.read_bytes()
        self.packet = json.loads(self.raw)
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.identity = dict(identity)
        if self.packet['owner'] != identity['role']:
            raise ValueError('Page belongs to another owner')
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.sources = OperatorTools(sources, self.output / 'source-evidence')
        self.seeds = baseline_seed_groups(self.packet)
        self.seeded = {i for g in self.seeds for i in g['fact_indices']}
        self.groups = []
        self.evidence = []
        self.viewed = False

    def unchanged(self):
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.sha:
            raise ValueError('Immutable work packet changed')

    def summary(self):
        self.unchanged()
        return {'catalog':self.packet['catalog'], 'physical_page':self.packet['physical_page'],
            'source_sha256':self.packet['source_sha256'], 'work_packet_sha256':self.sha,
            'owner':self.packet['owner'], 'facts':len(self.packet['facts']),
            'ledger_rows':len(self.packet['ledger_rows']), 'contexts':list(self.packet.get('contexts',{})),
            'reused_exact_fact_indices':sorted(self.seeded),
            'remaining_fact_indices':sorted(set(range(len(self.packet['facts']))) - self.seeded -
                {i for g in self.groups for i in g['fact_indices']}),
            'staged_groups':len(self.groups), 'evidence':self.evidence,
            'independent_final_review_complete':False}

    def read(self, kind, offset=0, limit=10, remaining_only=False, context_id=None):
        self.unchanged()
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 40:
            raise ValueError('Use offset>=0 and limit1..40')
        if kind == 'contexts':
            if context_id not in self.packet.get('contexts',{}):
                raise ValueError('Choose a context_id from the page summary/facts')
            value = self.packet['contexts'][context_id]
            raw = json.dumps(value,ensure_ascii=False,allow_nan=False)
            # Context paging is an exact serialization, never a summary/truncation.
            length = min(limit*200,8000)
            return {'context_id':context_id,'serialization':'JSON','offset':offset,
                'text':raw[offset:offset+length], 'total_characters':len(raw),
                'next_offset':offset+length if offset+length<len(raw) else None}
        if kind not in ('facts','ledger_rows'):
            raise ValueError('kind must be facts, ledger_rows, or contexts')
        items = list(enumerate(self.packet[kind]))
        if remaining_only:
            if kind != 'facts':raise ValueError('remaining_only applies to facts')
            used = self.seeded | {i for g in self.groups for i in g['fact_indices']}
            items = [(i,v) for i,v in items if i not in used]
        # Do not let an SDK silently truncate a large fact. Return an explicit
        # retained context reference when available; original values stay exact.
        chosen = []; size = 0
        for index,value in items[offset:offset+limit]:
            entry = {'index':index,'value':value}
            length = len(json.dumps(entry,ensure_ascii=False))
            if length > 10000:
                raise ValueError('One input exceeds10000characters; use read_work_text for exact character paging')
            if chosen and size+length > 10000:break
            chosen.append(entry);size+=length
        end = offset+len(chosen)
        return {'kind':kind,'offset':offset,'items':chosen,'total_items':len(items),
            'next_offset':end if end<len(items) else None,'complete_slice':True}

    def read_text(self, fact_index, offset=0, length=6000):
        self.unchanged()
        if type(fact_index) is not int or not 0 <= fact_index < len(self.packet['facts']):
            raise ValueError('Unknown fact index')
        if type(offset) is not int or offset<0 or type(length) is not int or not 1<=length<=8000:
            raise ValueError('Bounded character slice required')
        raw=json.dumps(self.packet['facts'][fact_index],ensure_ascii=False,allow_nan=False)
        return {'fact_index':fact_index,'serialization':'JSON','text':raw[offset:offset+length],
            'offset':offset,'total_characters':len(raw),
            'next_offset':offset+length if offset+length<len(raw) else None}

    def stage(self, groups):
        self.unchanged()
        if not isinstance(groups,list) or not groups or len(groups)>40:
            raise ValueError('Stage1..40groups; this does not finish the page')
        seen=self.seeded | {i for g in self.groups for i in g['fact_indices']}
        for group in groups:
            indices=group.get('fact_indices')
            if not isinstance(indices,list) or not indices or any(type(i) is not int or not 0<=i<len(self.packet['facts']) for i in indices):
                raise ValueError('Existing integer fact_indices required')
            if len(set(indices))!=len(indices) or seen.intersection(indices):
                raise ValueError('A fact is already reused or staged; do not repeat tool calls')
            seen.update(indices)
        # Reject a malformed group before persisting it, so a model can repair
        # its arguments in this same context. Placeholder remainder is checked
        # only in memory, never saved or treated as an actual source decision.
        rest=sorted(set(range(len(self.packet['facts'])))-seen)
        pending=([{'fact_indices':rest,'relation':'source_unresolved','keep':'unresolved',
            'reason':'Validation-only remainder; not saved','evidence_refs':[0]}] if rest else [])
        validate_page_work(self.packet,{'work_packet_sha256':self.sha,
            'source_sha256':self.packet['source_sha256'],'physical_page':self.packet['physical_page'],
            'source_evidence':self.evidence,'reuse_exact_agreements':True,
            'groups':self.groups+groups+pending},packet_sha256=self.sha,identity=self.identity)
        # Persist an append-only step before acknowledging model work.
        path=self.output/f'stage-{len(self.groups):06d}.json'
        with path.open('x') as stream:json.dump(groups,stream,ensure_ascii=False,allow_nan=False)
        self.groups.extend(groups)
        return {'staged_groups':len(self.groups), 'remaining_facts':len(self.packet['facts'])-len(seen)}

    def finish(self):
        if not self.viewed:raise ValueError('View the original physical page before finishing')
        proposal={'work_packet_sha256':self.sha,'source_sha256':self.packet['source_sha256'],
            'physical_page':self.packet['physical_page'],'source_evidence':self.evidence,
            'reuse_exact_agreements':True,'groups':self.groups}
        result=save_page_work(self.path,proposal,identity=self.identity,output=self.output/'result.json')
        return {'saved':True,'work_sha256':result['work_sha256'],
            'facts_accounted_for':len(self.packet['facts']),
            'independent_final_review_complete':False}


def work_server(context):
    mcp=server(context.sources)
    # Source operations remain the exact shared implementation. Track actual
    # image delivery, rather than a model's claim to have viewed a page.
    original_run=context.sources.run
    def run(digest,page,action):
        if digest!=context.packet['source_sha256'] or page!=context.packet['physical_page']:
            raise ValueError('This worker owns one physical page')
        result=original_run(digest,page,action)
        if hasattr(result,'data') and isinstance(result.data,bytes) and result.data.startswith(b'\x89PNG'):
            context.viewed=True
        return result
    context.sources.run=run

    @mcp.tool()
    def get_work_page() -> dict:
        """Immutable input summary, source page, exact reused indices and remaining work."""
        return context.summary()

    @mcp.tool()
    def read_work_items(kind:str,offset:int=0,limit:int=10,remaining_only:bool=False,context_id:str|None=None) -> dict:
        """Read exact indexed facts or ledger_rows; follow next_offset. contexts pages JSON characters by context_id. Nothing is silently truncated."""
        return context.read(kind,offset,limit,remaining_only,context_id)

    @mcp.tool()
    def read_work_text(fact_index:int,offset:int=0,length:int=6000) -> dict:
        """Exact JSON character paging for unusually large original facts."""
        return context.read_text(fact_index,offset,length)

    @mcp.tool()
    def add_source_evidence(bbox:list[float],observation:str) -> dict:
        """Record an observed original region; returns the evidence_refs index used by groups."""
        if not context.viewed:raise ValueError('View original first')
        if len(bbox)!=4 or not (0<=bbox[0]<bbox[2]<=1 and 0<=bbox[1]<bbox[3]<=1) or not observation.strip():
            raise ValueError('Normalized source region and concrete observation required')
        context.evidence.append({'bbox':bbox,'observation':observation})
        return {'evidence_index':len(context.evidence)-1}

    @mcp.tool()
    def stage_work_groups(groups:list[dict]) -> dict:
        """Stage1..40groups with fact_indices,relation,keep,reason,evidence_refs. All original indices exactly once; reused exact indices already handled. No replacement values. This is NOT page completion."""
        return context.stage(groups)

    @mcp.tool()
    def finish_page_work() -> dict:
        """Save complete owner work, verifying all input facts accounted for. Final independent audit explicitly remains pending."""
        return context.finish()
    return mcp


def main():
    p=argparse.ArgumentParser()
    for key in ('packet','sources','identity','output'):p.add_argument('--'+key,type=Path,required=True)
    args=p.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    work_server(PageWorkTools(args.packet,args.sources,json.loads(args.identity.read_text()),args.output)).run()


if __name__=='__main__':main()
