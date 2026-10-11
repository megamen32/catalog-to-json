"""Deterministic import of externally supplied JSONL results, without inference or repairs."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from .schema import Cell, Column, PageContent, Row, Table, TextBlock


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:
        for number,line in enumerate(stream,1):
            if not line.strip():continue
            record=json.loads(line)
            if not isinstance(record,dict):raise ValueError(f'JSONL line {number} must be an object')
            yield record


def import_page(products,characteristics,families,document_id,page):
    if page<1:raise ValueError('Physical page must be positive')
    products=[p for p in products if p.get('source_document_id')==document_id]
    by_id={p['product_id']:p for p in products}
    selected=[c for c in characteristics if c.get('source_document_id')==document_id and c.get('physical_page')==page]
    groups=defaultdict(list);unlocated=0;conflicts=0
    for record in selected:
        e=record.get('source_evidence_reference') or {}
        if (e.get('table_id') and type(e.get('row')) is int and e['row']>=0
                and type(e.get('column')) is int and e['column']>0):
            groups[e['table_id']].append(record)
        else:unlocated+=1
    tables=[];uncertainties=[];table_coordinates=[]
    natural=lambda s:[(1,int(p)) if p.isdigit() else (0,p) for p in re.split(r'(\d+)',s)]
    for table_id,records in sorted(groups.items(),key=lambda item:natural(item[0])):
        coordinates=defaultdict(list)
        for record in records:
            e=record['source_evidence_reference'];coordinates[e['row'],e['column']].append(record)
        row_ids=sorted({r for r,c in coordinates});max_column=max(c for r,c in coordinates)
        if max_column>256 or len(row_ids)>10000:raise ValueError('Unsupported external table dimensions')
        columns=[Column(id='c0',label='Наименование')]
        for col in range(1,max_column+1):
            matching=[v for (r,c),items in coordinates.items() if c==col for v in items]
            labels=list(dict.fromkeys(v.get('characteristic_name') or '' for v in matching))
            units=list(dict.fromkeys(v.get('unit_of_measurement') for v in matching))
            columns.append(Column(id=f'c{col}',label='\n'.join(labels),unit=units[0] if len(units)==1 else None))
            if len(units)>1:uncertainties.append(f'{table_id} column {col}: conflicting reported units {units!r}')
        rows=[]
        for ri in row_ids:
            row_records=[v for (r,c),items in coordinates.items() if r==ri for v in items]
            names=set()
            for record in row_records:
                product=by_id.get(record.get('product_id'))
                if product:
                    # Prefer the reported designation for this exact observation;
                    # never recover row identities from characteristic names or gold.
                    observations=[o for o in product.get('observations',[]) if o.get('physical_page')==page
                        and (o.get('evidence') or {}).get('table_id')==table_id
                        and (o.get('evidence') or {}).get('row')==ri]
                    names.update(o['raw_designation'] for o in observations if o.get('raw_designation'))
                    if not observations and product.get('product_name'):names.add(product['product_name'])
            name=next(iter(names)) if len(names)==1 else None
            cells=[Cell(column_id='c0',value=name,state='value' if name is not None else 'unknown')]
            for ci in range(1,max_column+1):
                entries=coordinates.get((ri,ci),[])
                values={(v.get('raw_value'),v.get('value_state')) for v in entries}
                value=None;state='unknown'
                if len(values)==1:
                    value,value_state=next(iter(values))
                    if value_state=='source_blank' and value in ('',None):value=None;state='blank'
                    elif value not in ('',None):state='value'
                    else:value=None
                elif len(values)>1:
                    conflicts+=1;uncertainties.append(f'{table_id} row {ri} column {ci}: conflicting records')
                cells.append(Cell(column_id=f'c{ci}',value=value,state=state))
            rows.append(Row(cells=cells))
        tables.append(Table(id=table_id,title=table_id,columns=columns,rows=rows))
        table_coordinates.append({'table_id':table_id,'source_rows_in_candidate_order':row_ids,
            'source_value_columns_in_candidate_order':list(range(1,max_column+1)),
            'candidate_identity_column':0,
            'identity_method':'matching product observations, otherwise reported product name; no source/gold recovery'})
    relevant_families=[f for f in families if f.get('source_document_id')==document_id and page in f.get('physical_pages',[])]
    texts=list(dict.fromkeys(f['description_raw'] for f in relevant_families if f.get('description_raw')))
    labels={str(c['printed_page_label']) for c in selected if c.get('printed_page_label') is not None}
    content=PageContent(title=next((c.get('catalogue_title') or '' for c in selected),document_id),
        printed_page=next(iter(labels)) if len(labels)==1 else None,
        text_blocks=[TextBlock(kind='paragraph',text=t) for t in texts],tables=tables,figures=[],
        source_notes=['Imported saved results; no extraction, repair, source-driven merge expansion or model call.',
                      'Drawing structure is not supplied by this JSONL format. Raw input records remain authoritative.'],
        uncertainties=uncertainties)
    metadata={'stage':'imported_result','runtime_verified':False,'model':None,'elapsed_seconds':None,
              'tokens':None,'cost':None,'source_binding':'external document ID and physical page; PDF hash not supplied',
              'document_id':document_id,'physical_page':page,'selected_characteristics':len(selected),
              'unlocated_characteristics':unlocated,'conflicting_coordinates':conflicts,
              'table_coordinates':table_coordinates,
              'unsupported_coverage':['drawing_structure','source_merge_geometry']}
    return content,metadata


def import_jsonl(products,characteristics,families,document_id,page,output):
    paths={'products':Path(products),'characteristics':Path(characteristics),'families':Path(families)}
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise ValueError('Saved result import requires a fresh output directory')
    # Hash the exact byte streams being parsed; a modified file invalidates the import.
    before={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    content,metadata=import_page(*(read_jsonl(paths[k]) for k in ('products','characteristics','families')),document_id,page)
    after={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    if before!=after:raise ValueError('JSONL inputs changed while being imported')
    output.mkdir(parents=True,exist_ok=True)
    candidate=output/'candidate.json';candidate.write_text(content.model_dump_json(indent=2),encoding='utf-8')
    metadata.update(inputs_sha256=before,candidate=str(candidate.resolve()),candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'import.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    return metadata
