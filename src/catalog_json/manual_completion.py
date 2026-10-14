"""Close duplicate native work after a separately attributed two-author revision.

The native candidate/content/receipt stays unchanged. Completion selects an
external, exact-hash revision; it never certifies the superseded native bytes.
"""
import hashlib
import json
import re
from pathlib import Path
from .schema import PageContent
from .provenance import artifact_origin

STATUS = 'superseded_by_independently_verified_revision'
CHECKS = {'all_text_and_meaning','all_table_cells','headers_units_conditions',
          'merged_cells_and_blanks','figures_and_relationships','source_provenance'}
_CACHE = {}


def queue_complete(record):
    return record.get('status') in ('accepted', STATUS)


def _signature(paths):
    result=[]
    for path in paths:
        try:
            s=path.stat();result.append((str(path),s.st_mtime_ns,s.st_ctime_ns,s.st_size,s.st_ino))
        except OSError:result.append((str(path),None))
    return tuple(result)


def _completion(work,record,dependencies,read_signatures):
    def watch(path):
        path=Path(path);dependencies.add(path);signature=_signature((path,))
        if path in read_signatures and read_signatures[path]!=signature[0]:raise OSError('Completion evidence changed between reads')
        read_signatures[path]=signature[0];return path,signature
    def read(path):
        path,signature=watch(path);raw=path.read_bytes()
        if signature!=_signature((path,)):raise OSError('Completion evidence changed during read')
        read_signatures[path]=signature[0];return raw
    def sha(raw):return hashlib.sha256(raw).hexdigest()
    def local(name):
        if not isinstance(name,str) or Path(name).name!=name:raise ValueError('Nonlocal completion receipt')
        return work/name
    raw=read(work/'external-audit.json');audit=json.loads(raw)
    source=record['source_sha256'];page=record['pdf_page']
    if audit.get('source_sha256')!=source or audit.get('pdf_page')!=page:return None
    reference=read(work/'root-reference-tail-20261014-r1.json');digest=sha(reference)
    if digest in audit.get('rejected_candidate_sha256',[]):return None
    content=PageContent.model_validate_json(reference)
    proof_raw=read(work/'root-reference-tail-20261014-r1.provenance.json');proof=json.loads(proof_raw)
    author=proof.get('reviewer',{})
    if (proof.get('schema_version')!='catalogue-source-review/1' or proof.get('status') not in ('source_verified','source_corrected_pending_independent_review','awaiting_independent_review','author_source_review_complete_pending_independent_review')
            or proof.get('source_sha256')!=source or proof.get('physical_page')!=page
            or proof.get('catalog')!=work.parent.name or not proof.get('corrections')
            or proof.get('output',{}).get('sha256')!=digest or any(x not in ('Нужна независимая проверка авторского разбора и инженерных отношений.','Нужна независимая проверка авторских исправлений и всех инженерных чертежей.','Нужна независимая проверка всех авторских изменений и инженерных чертежей.','Нужна независимая проверка авторских исправлений.') for x in proof.get('unresolved_issues',[]))
            or proof.get('full_original_image_review') is not True or content.uncertainties
            or author.get('harness')!='codex' or not author.get('session_id') or not author.get('version')
            or not CHECKS.issubset(proof.get('checks',{})) or any(proof['checks'][k] is not True for k in CHECKS)):return None
    basis=proof.get('basis_candidate',{});origin=basis.get('producer',{})
    if (origin.get('status')!='receipt_verified' or origin.get('source_sha256')!=source
            or origin.get('physical_page')!=page or basis.get('sha256')!=origin.get('artifact_sha256')
            or type(origin.get('attempt')) is not int
            or sha(read(work/f"candidate-{origin['attempt']}.json"))!=basis['sha256']):return None
    # Revalidate the actual retained native receipt, not just its copied label.
    read(work/'tools.jsonl')
    calls,_=watch(work/'calls')
    for directory in calls.iterdir():
        if directory.is_dir():
            watch(directory);receipt=directory/'result.json'
            if receipt.exists():read(receipt)
            else:watch(receipt)
    native=artifact_origin(work,work/f"candidate-{origin['attempt']}.json",source,page,origin['attempt'],'extractor',origin['model'],origin['contract_sha256'])
    if native['status']!='receipt_verified' or any(native.get(k)!=origin.get(k) for k in ('program','model','contract_sha256','artifact_sha256')):return None
    read(work/native['receipt'])
    rows=[len(t.rows) for t in content.tables];cols=[len(t.columns) for t in content.tables]
    tables={'row_counts':rows,'column_counts':cols,'cells_checked':sum(a*b for a,b in zip(rows,cols))}
    if proof.get('tables')!=tables:return None
    leads=[f for f in audit.get('findings',[]) if isinstance(f,dict) and f.get('reference_sha256')==digest]
    if len(leads)!=1:return None
    lead=leads[0];binding=lead.get('independent_source_review',{})
    if (lead.get('reference_author')!=author or PageContent.model_validate(lead.get('reference_data')).model_dump()!=content.model_dump()
            or binding.get('verdict')!='pass' or binding.get('issues')
            or binding.get('reviewed_reference_sha256')!=digest
            or binding.get('full_original_image_review') is not True or binding.get('provider_model_call') is not False):return None
    report_path=local(binding.get('report'));report_raw=read(report_path);report=json.loads(report_raw)
    reviewer=report.get('independent_author');report_hash=sha(report_raw)
    if (report_hash!=binding.get('report_sha256') or reviewer!=binding.get('author') or not reviewer
            or reviewer==author['session_id'] or report.get('origin_author') not in (author['session_id'],'root')
            or report.get('schema_version')!='catalogue-independent-source-review/1'
            or report.get('catalog')!=proof['catalog'] or report.get('source_sha256')!=source
            or report.get('physical_page')!=page or report.get('verdict')!='pass'
            or report.get('full_original_image_review') is not True or report.get('issues') or report.get('errors')
            or report.get('unresolved_issues') or report.get('uncertainties')):return None
    exact=report.get('reviewed_json_sha256',report.get('exact_reviewed_sha256',report.get('exact_candidate_sha256')))
    frozen=report.get('reviewed_input_frozen',report.get('frozen_reviewed_path',report.get('candidate_frozen_file')))
    image=report.get('original_image',report.get('original_image_file',report.get('source_image')))
    if exact!=digest or not frozen or not image or sha(read(frozen))!=digest or sha(read(image))!=report.get('original_image_sha256'):return None
    checks=report.get('checks',{});evidence=report.get('technical_and_meaning_review',report.get('source_findings',''))
    if set(checks)!=CHECKS:return None
    for check in checks.values():
        if isinstance(check,bool):
            if check is not True or not evidence:return None
        elif not isinstance(check,dict) or check.get('passed') is not True or not check.get('evidence'):return None
    observed=report.get('observed_tables',{})
    if (report.get('observed_row_counts',observed.get('row_counts'))!=rows
            or report.get('observed_column_counts',observed.get('column_counts'))!=cols
            or report.get('total_cells_checked',report.get('cells_checked',observed.get('cells_checked')))!=tables['cells_checked']):return None
    previous=record.get('independent_revision_completion',{})
    if (previous.get('reference_sha256')==digest and previous.get('review_sha256')==report_hash
            and previous.get('external_audit_sha256')!=sha(raw)):return None
    groups=report.get('dimension_ownership',report.get('per_figure_dimension_ownership',[]))
    dimension_label=re.compile(r'(?:[Øø⌀RrDd]?\d+(?:[.,]\d+)?(?:°)?|[A-Za-zА-Яа-я](?:[₀-₉0-9])?)')
    has_dimensions=any(dimension_label.fullmatch(label.strip()) for f in content.figures for label in f.labels)
    count=0
    for group in groups:
        dimensions=[group] if 'literal' in group or 'literal_label' in group else group.get('dimensions',[])
        count+=len(dimensions)
        for dim in dimensions:
            box=dim.get('source_bbox')
            if (not dim.get('literal',dim.get('literal_label')) or not dim.get('actual_target',dim.get('target'))
                    or not isinstance(box,list) or len(box)!=4 or not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1):return None
    if has_dimensions and not count:return None
    return {'status':STATUS,'independent_revision_completion':{
        'reference': 'root-reference-tail-20261014-r1.json','reference_sha256':digest,
        'author':author,'reviewer':reviewer,'review':report_path.name,'review_sha256':report_hash,
        'author_proof_sha256':sha(proof_raw),'source_sha256':source,'physical_page':page,
        'author_workflow_wait_resolved_by_report':proof.get('unresolved_issues',[]),
        'external_audit_sha256':sha(raw),'native_candidate_accepted':False,'new_model_call':False}}


def independent_completion_update(work,record):
    """Validate source-bound evidence, caching only while all exact files persist."""
    work=Path(work).resolve();previous=record.get('independent_revision_completion',{})
    key=(str(work),record.get('source_sha256'),record.get('pdf_page'),previous.get('reference_sha256'),previous.get('review_sha256'),previous.get('external_audit_sha256'))
    cached=_CACHE.get(key)
    if cached and cached[0]==_signature(cached[1]):return cached[2]
    paths={work/'external-audit.json',work/'root-reference-tail-20261014-r1.json',work/'root-reference-tail-20261014-r1.provenance.json'}
    read_signatures={}
    try:result=_completion(work,record,paths,read_signatures)
    except (ValueError,KeyError,TypeError,IndexError,OSError):result=None
    paths=tuple(sorted(paths));signature=_signature(paths)
    if any(read_signatures.get(path,item)!=item for path,item in zip(paths,signature)):return None
    if len(_CACHE)>=4096:_CACHE.clear()
    _CACHE[key]=(signature,paths,result)
    return result
