"""Lossless field adaptation of parser output; no source/gold-derived repairs."""
def page_base(title):
    return {'title':title,'printed_page':None,'text_blocks':[],'tables':[],'figures':[],
            'source_notes':[],'uncertainties':[]}


def matrix_table(table_id,headers,rows,groups=None):
    groups=groups or [None]*len(headers)
    columns=[{'id':f'c{i}','label':str(h or ''),'group':groups[i],'unit':None,'qualifier':None} for i,h in enumerate(headers)]
    result=[]
    for row in rows:
        result.append({'cells':[{'column_id':f'c{i}','value':v if v not in ('',None) else None,
                                'state':'value' if v not in ('',None) else 'blank' if v=='' else 'unknown'} for i,v in enumerate(row)]})
    return {'id':table_id,'title':table_id,'columns':columns,'rows':result}


def from_pymupdf(raw):
    output=page_base('PyMuPDF4LLM parsed page')
    for page in raw['pages']:
        for box in page.get('boxes',[]):
            table=box.get('table')
            if table:
                matrix=table.get('extract',[])
                if matrix:
                    width=table['col_count']
                    if any(len(r)!=width for r in matrix):raise ValueError('Parser emitted ragged matrix')
                    output['tables'].append(matrix_table(f't{len(output["tables"])}',matrix[0],matrix[1:]))
            else:
                text='\n'.join(''.join(s.get('text','') for s in line.get('spans',[])) for line in box.get('textlines',[]))
                if text:output['text_blocks'].append({'kind':'paragraph','text':text})
    output['source_notes'].append('Native parser output. Column headers are retained without splitting collapsed engineering fields; null cells stay unknown.')
    return output


def from_docling(raw):
    output=page_base(raw.get('name','Docling parsed page'))
    for item in raw.get('tables',[]):
        table=item['data'];width=table['num_cols'];height=table['num_rows'];cells=table['table_cells']
        # Header flags and spans come only from the parser's document model.
        header_rows=set()
        for cell in cells:
            if cell.get('column_header'):
                header_rows.update(range(cell['start_row_offset_idx'],cell['end_row_offset_idx']))
        first_body=0
        while first_body in header_rows:first_body+=1
        if not first_body and height:first_body=1  # Declared adapter convention; retained raw JSON makes this auditable.
        headers=[];groups=[]
        for ci in range(width):
            matching=sorted([c for c in cells if c['start_col_offset_idx']<=ci<c['end_col_offset_idx'] and c['start_row_offset_idx']<first_body],key=lambda c:c['start_row_offset_idx'])
            values=list(dict.fromkeys(c.get('text','') for c in matching))
            headers.append(values[-1] if values else '')
            groups.append(' '.join(values[:-1]) or None)
        rows=[]
        for ri in range(first_body,height):
            row=[]
            for ci in range(width):
                matching=[c for c in cells if c['start_col_offset_idx']<=ci<c['end_col_offset_idx'] and c['start_row_offset_idx']<=ri<c['end_row_offset_idx']]
                values=set(c.get('text','') for c in matching)
                row.append(next(iter(values)) if len(values)==1 else None)
            rows.append(row)
        output['tables'].append(matrix_table(f't{len(output["tables"])}',headers,rows,groups))
    for text in raw.get('texts',[]):
        if text.get('text'):output['text_blocks'].append({'kind':'paragraph','text':text['text']})
    output['source_notes'].append('Docling-reported cell spans are expanded without adding source-derived values; missing/conflicting cells stay unknown. Header flags come from the parser; absent flags use its first row as an explicit adapter convention.')
    return output
