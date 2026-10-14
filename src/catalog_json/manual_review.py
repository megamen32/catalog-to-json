"""Explicit owner-authorized source review of unchanged native catalogue outputs.

This is a separately attributed Codex review, never a forged GLM/native receipt.
Engineering drawings and edited candidates keep their normal independent review.
"""
import hashlib
import json
from .schema import PageContent,Review,Check,CHECKS,ContextReview


def _source_review_update(work,record):
    path=work/'root-source-review.json'
    if not path.exists():return None
    raw=path.read_bytes();proof=json.loads(raw);basis=proof.get('basis_candidate',{});origin=record.get('candidate_producer',{})
    if (proof.get('schema_version')!='catalogue-source-review/1' or proof.get('status')!='source_verified'
            or proof.get('source_sha256')!=record['source_sha256'] or proof.get('physical_page')!=record['pdf_page']
            or proof.get('unchanged_native_candidate') is not True or proof.get('corrections')
            or proof.get('unresolved_issues') or proof.get('full_original_image_review') is not True
            or proof.get('independent_from_initial_extractor') is not True):return None
    reviewer=proof.get('reviewer',{})
    if reviewer.get('harness')!='codex' or not reviewer.get('session_id') or not reviewer.get('version'):return None
    checks=proof.get('checks',{})
    if set(checks)!={'all_text_and_meaning','all_table_cells','headers_units_conditions','merged_cells_and_blanks','figures_and_relationships','source_provenance'} or any(v is not True for v in checks.values()):return None
    if origin.get('status')!='receipt_verified' or basis.get('sha256')!=record.get('candidate_sha256'):return None
    if any(basis.get('producer',{}).get(k)!=origin.get(k) for k in ('program','model','contract_sha256','artifact_sha256','source_sha256','physical_page','attempt')):return None
    candidate=work/f"candidate-{origin['attempt']}.json"
    if not candidate.exists() or hashlib.sha256(candidate.read_bytes()).hexdigest()!=basis['sha256']:return None
    attempts=[int(p.stem.split('-')[-1]) for p in work.glob('candidate-*.json')]
    if max(attempts,default=-1)!=origin['attempt']:return None
    audit=work/'external-audit.json';audit_raw=audit.read_bytes() if audit.exists() else None;digest=hashlib.sha256(audit_raw).hexdigest() if audit_raw is not None else None
    if proof.get('external_audit_sha256')!=digest:return None
    if audit_raw and basis['sha256'] in json.loads(audit_raw).get('rejected_candidate_sha256',[]):return None
    content=PageContent.model_validate(record['content'])
    if content.model_dump()!=PageContent.model_validate_json(candidate.read_bytes()).model_dump() or content.uncertainties:return None
    # This narrow path must not replace the per-dimension observer/ownership gate.
    if content.figures and (not content.page_context or content.page_context.kind!='supporting_material' or any(f.labels for f in content.figures)):return None
    rows=[len(t.rows) for t in content.tables];cols=[len(t.columns) for t in content.tables]
    if proof.get('tables')!={'row_counts':rows,'column_counts':cols,'cells_checked':sum(a*b for a,b in zip(rows,cols))}:return None
    evidence=proof.get('source_findings','')
    if not isinstance(evidence,str) or not evidence.strip():return None
    context=ContextReview(page_purpose_verified=True,summary_meaning_verified=True,actual_vs_demo_verified=True,technical_facts_verified=True,relations_verified=True,evidence=evidence) if content.page_context else None
    review=Review(verdict='pass',checks=[Check(category=c,passed=True,evidence=evidence) for c in sorted(CHECKS)],issues=[],observed_table_count=len(rows),observed_row_counts=rows,observed_column_counts=cols,context_review=context)
    if not review.accepts(content):return None
    sha=hashlib.sha256(raw).hexdigest();author='Codex native session '+reviewer['session_id']
    return {'status':'accepted','review':review.model_dump(),'reviewer':author,'review_sha256':sha,
        'review_producer':{'status':'manual_source_review_verified','model':author,'harness':'codex','session_id':reviewer['session_id'],
            'program':{'package_version':reviewer['version'],'source_code_sha256':None},'role':'reviewer','source_sha256':record['source_sha256'],
            'physical_page':record['pdf_page'],'attempt':origin['attempt'],'artifact_sha256':sha,'reviewed_candidate_sha256':basis['sha256'],
            'receipt':path.name,'completed_at':proof.get('completed_at')},
        'manual_source_review':{'receipt':path.name,'sha256':sha,'mode':'owner_authorized_independent_source_review_of_unchanged_native_candidate',
            'external_audit_sha256':digest,'native_reviewer_call':False}}


def source_review_update(work,record):
    try:return _source_review_update(work,record)
    except (ValueError,KeyError,TypeError,IndexError,OSError):
        # A stale/partial manual inbox cannot stop admitted native model calls.
        return None
