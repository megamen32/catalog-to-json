"""Compare independently tool-recorded source observations with the candidate."""
import re
import unicodedata
import hashlib
from collections import Counter
from decimal import Decimal,InvalidOperation
from .schema import PageContent
from .observation_quotes import is_branding_caption


def text_key(value):
    text=unicodedata.normalize('NFKC',value).casefold()
    return re.sub(r'[^\w+±-]','',text)


def branding_words(value):
    # Layout order may differ between independent logo blocks. Preserve entire
    # words, internal hyphens and multiplicity; never use this for engineering.
    return Counter(re.findall(r'\w+(?:-\w+)*',unicodedata.normalize('NFKC',value).casefold()))


def branding_present(value,blocks):
    return is_branding_caption(value) and bool(branding_words(value)) and not (branding_words(value)-branding_words(' '.join(blocks)))


def header_key(value):
    text=unicodedata.normalize('NFKC',value).casefold()
    text=re.sub(r'(?<=\d)[.,](?=\d)','decimalpoint',text)
    return re.sub(r'[^\w+±<>=≤≥/·^*-]','',text)


def figure_key(value):
    # Image observations cannot disambiguate identical Latin/Cyrillic glyph shapes.
    text=unicodedata.normalize('NFKC',value.translate(str.maketrans('АВЕКМНОРСТХавекмнорстх','ABEKMHOPCTXabekmhopctx'))).casefold()
    text=re.sub(r'(?<!\w)[φфø⌀](?=\s*\d)','⌀',text)
    text=re.sub(r'(?<=\d),(?=\d)','.',text)
    return re.sub(r'[^\w+±.,⌀\s-]','',text)


def figure_pattern(value):
    # Preserve whole numbers and decimal points; spacing must not turn 13 into 132.
    parts=re.findall(r'\d+(?:[.,]\d+)?|[^\s]',figure_key(value))
    return r'(?<!\w)'+r'\s*'.join(re.escape(p) for p in parts)+r'(?![0-9]|[.,][0-9])'


def component_pattern(value):
    return r'(?<![\w/])'+r'\s*'.join(re.escape(p) for p in value.split())+r'(?![\w/])'


def primary_header(text):
    # A unit in a current/time condition cannot become the voltage parameter unit.
    return re.split(r'\b(?:при|для|with|at)\b',text or '',maxsplit=1,flags=re.I)[0]


# SI spelling aliases only. Case/prefixes and compound operators retain meaning.
# Latin B is deliberately not a volt alias: it may mean bytes rather than В.
UNIT_ALIASES={'A':'А','kA':'кА','mA':'мА','MA':'МА','V':'В','kV':'кВ','mV':'мВ','MV':'МВ',
    'N':'Н','kN':'кН','J':'Дж','kJ':'кДж','Pa':'Па','kPa':'кПа','MPa':'МПа','mPa':'мПа',
    'm':'м','mm':'мм','cm':'см','g':'г','kg':'кг','s':'с','ms':'мс','us':'мкс','µs':'мкс','μs':'мкс',
    'S':'См','mS':'мСм','MS':'МСм','uS':'мкСм','µS':'мкСм','μS':'мкСм','Hz':'Гц','kHz':'кГц'}
UNIT_ALIASES.update({value:value for value in list(UNIT_ALIASES.values())})
IDENTITY_HEADER=r'\b(?:тип\w*|артикул\w*|марк\w*|обознач\w*|код\w*|наименован\w*|назван\w*|модел\w*|модификац\w*|исполнен\w*|product|identity|designation|model|variant|name)\b'
CONDITION_START=r'\b(?:при|для|with|at)\b'
QUANTITY=re.compile(r'(?<![\w.])([+-]?(?:0|[1-9]\d*)(?:[.,]\d+)?)\s*('+ '|'.join(re.escape(k) for k in sorted(UNIT_ALIASES,key=len,reverse=True))+r')(?!\w)')


def unit_key(value):
    text=re.sub(r'\s+','',unicodedata.normalize('NFKC',value or ''))
    return re.sub(r'[A-Za-zА-Яа-яµμ]+',lambda m:UNIT_ALIASES.get(m[0],m[0]),text)


def physical_column(column):
    text=' '.join(x for x in (column.group,column.label,column.qualifier) if x)
    if re.search(IDENTITY_HEADER,text,re.I):return False
    conditional_quantity=bool(QUANTITY.search(text) and re.search(CONDITION_START+r'|не\s+(?:менее|более)|[<>=≤≥]',text,re.I))
    return bool(column.unit or conditional_quantity or re.search(r'напряжени|ток|сил[аы]|давлен|масс|длин|диаметр|частот|энерги|проводим|температур|voltage|current|force|pressure|mass|length|diameter|frequency|energy|conductivity|temperature',text,re.I))


def physical_text(value,column):
    if not physical_column(column):return value or ''
    # Opaque comparison tokens preserve SI case when header words are case-folded.
    context=' '.join(x for x in (column.group,column.label,column.qualifier) if x)
    def token(m):
        canonical=unit_key(m[2])
        condition=bool(re.search(CONDITION_START+r'|не\s+(?:менее|более)|[<>=≤≥]',context,re.I))
        current=canonical in {'А','кА','мА','МА'} and bool(re.search(r'ток|current|amper',context,re.I))
        if not (condition or current or canonical==unit_key(column.unit)):return m[0]
        # Keep decimal boundaries as well as prefixes: header_key removes punctuation.
        fingerprint=hashlib.sha256((m[1].replace(',','.')+'|'+canonical).encode()).hexdigest()
        return m[1]+' physicalquantity'+fingerprint
    return QUANTITY.sub(token,unicodedata.normalize('NFKC',value or ''))


def column_key(value,column):return header_key(physical_text(value,column))


def same_header_partition(a,b):
    """Exact comma clauses may move between label/qualifier in one column.

    Keep units and parent ownership fixed. Do not split decimal commas, sort
    words, change case/prefixes, or infer a missing condition.
    """
    if not a.unit or not b.unit or unit_key(a.unit)!=unit_key(b.unit) or a.group!=b.group:return False
    split=r'(?<!\d),|,(?!\d)'
    def exact(text):return re.sub(r'\s+','',unicodedata.normalize('NFKC',text))
    if exact(re.split(split,a.label)[0])!=exact(re.split(split,b.label)[0]):return False
    def clauses(column):
        return Counter(exact(part)
                       for value in (column.label,column.qualifier) if value
                       for part in re.split(split,value) if part.strip())
    return clauses(a)==clauses(b)


def unit_pattern(value):
    parts=[]
    for part in re.findall(r'[A-Za-zА-Яа-яµμ]+|[^\s]',value):
        aliases=[k for k in UNIT_ALIASES if unit_key(k)==unit_key(part)] if part in UNIT_ALIASES else [part]
        parts.append('(?:'+'|'.join(re.escape(k) for k in aliases)+')')
    return r'(?<![\w/])'+r'\s*'.join(parts)+r'(?![\w/])'


def condition_keys(column):
    # A leaf may repeat its exact parent for standalone readability. It does not
    # create a second physical condition; retain every nonmatching leaf byte.
    group=column.group or ''
    label=column.label or ''
    if (group and label.startswith(group) and
            (not re.search(r'\w$',group) or not re.match(r'\w',label[len(group):]))):
        label=label[len(group):].lstrip()
    text=' '.join(x for x in (group,label) if x)
    if column.qualifier and re.search(CONDITION_START,column.qualifier,re.I):
        if column_key(column.qualifier,column) not in column_key(text,column):text+=' '+column.qualifier
    tail=text[len(primary_header(text)):]
    return {column_key(tail,column)} if tail else set()


def header_has(column,value,attr):
    if attr=='qualifier':
        return bool(re.search(component_pattern(physical_text(value,column)),physical_text(' '.join(x for x in (column.group,column.label) if x),column),re.I))
    pattern=unit_pattern(value)
    flags=0 if attr=='unit' else re.I
    group=primary_header(column.group)
    if re.search(pattern,group,flags):return True
    # Never infer a parent parameter unit from a child condition. If a generic
    # group omits evidence, the reviewer must record the printed unit explicitly.
    if column.group:return False
    return bool(re.search(pattern,primary_header(column.label),flags))


def header_without(text,components,column=None):
    head=primary_header(text);tail=(text or '')[len(head):]
    for attr,component in components:
        if component and attr=='unit':head=re.sub(unit_pattern(component),'',head,count=1)
    result=physical_text(head+tail,column) if column is not None else head+tail
    for attr,component in components:
        if component and attr=='qualifier':result=re.sub(component_pattern(physical_text(component,column) if column else component),'',result,count=1,flags=re.I)
    return result


def same_value(a,b,identity=False):
    if str(a)==str(b):return True
    # PDF cell wrapping is layout, not a changed product code. Keep every
    # non-whitespace character and boundary: '12 34' must not become '1234'.
    if isinstance(a,str) and isinstance(b,str) and re.sub(r'\s+',' ',a).strip()==re.sub(r'\s+',' ',b).strip():return True
    if identity or isinstance(a,bool) or isinstance(b,bool):return False
    values=[]
    for value in (a,b):
        raw=str(value).replace(',','.')
        if not re.fullmatch(r'[+-]?(?:0|[1-9]\d*)(?:\.\d+)?',raw):return False
        try:values.append(Decimal(raw))
        except InvalidOperation:return False
    return values[0]==values[1]


def align_tables(observed,candidate):
    """Use mutual unique source signals, never positional zip on multi-table pages.

    Generated IDs are not source evidence. Titles, full headers and finally
    unique shapes establish identity; cells are compared only after alignment.
    """
    left=set(range(len(observed.tables)));right=set(range(len(candidate.tables)));pairs=[]
    if len(left)==len(right)==1:return [(0,0)],[],[]
    def headers(table):
        return tuple(header_key(' '.join(x for x in (c.group,c.label,c.unit,c.qualifier) if x)) for c in table.columns)
    signals=[lambda t:text_key(t.title),headers,lambda t:(len(t.columns),len(t.rows))]
    for signal in signals:
        # Matching by a weaker signal is unsafe when either side has repeats.
        a={i:signal(observed.tables[i]) for i in left};b={j:signal(candidate.tables[j]) for j in right}
        for i in sorted(left):
            key=a[i]
            if not key or sum(v==key for v in a.values())!=1:continue
            matches=[j for j,v in b.items() if v==key]
            if len(matches)==1:
                j=matches[0];pairs.append((i,j));left.remove(i);right.remove(j)
    return sorted(pairs),sorted(left),sorted(right)


def box_overlap(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union else 0


def context_differences(observed,candidate):
    a=observed.page_context;b=candidate.page_context
    if a is None and b is None:return []
    def diff(path,source,actual):return {'path':path,'source_observation':source,'candidate':actual}
    if a is None or b is None:
        return [diff('page_context',a.model_dump() if a else None,b.model_dump() if b else None)]
    differences=[]
    if a.kind!=b.kind:differences.append(diff('page_context.kind',a.kind,b.kind))
    # Independent readers may split the same source into different regions.
    # Boxes locate evidence, not semantic identity: matching their count/IoU
    # would turn valid paraphrases back into mechanical OCR differences.
    # Preserve scope disagreements; meaning and facts require ContextReview.
    source=a.source_evidence;actual=b.source_evidence
    source_scopes={e.kind for e in source};actual_scopes={e.kind for e in actual}
    # An extra unclassified evidence box (for example empty cover whitespace)
    # is not itself a missing engineering fact. Keep all concrete scope changes
    # strict, and never grant demo summarization through an unknown region.
    if a.kind==b.kind and a.kind not in {'software_demonstration','unknown'}:
        source_scopes.discard('unknown');actual_scopes.discard('unknown')
    if source_scopes!=actual_scopes:
        differences.append(diff('page_context.source_evidence',[e.model_dump() for e in source],[e.model_dump() for e in actual]))
    return differences


def independent_software_demonstration(observed,candidate):
    return all(page.page_context is not None and page.page_context.kind=='software_demonstration'
               and all(e.kind=='software_demonstration' for e in page.page_context.source_evidence)
               for page in (observed,candidate))


def compare_source(observed: PageContent,candidate: PageContent,branding_figure_quotes=None):
    differences=context_differences(observed,candidate)
    semantic_narrative=observed.page_context is not None and candidate.page_context is not None and not differences
    def add(path,expected,actual):
        differences.append({'path':path,'source_observation':expected,'candidate':actual})
    if observed.uncertainties:add('source_observation.uncertainties',[],observed.uncertainties)
    if len(observed.tables)!=len(candidate.tables):add('tables',len(observed.tables),len(candidate.tables))
    pairs,unmatched_source,unmatched_candidate=align_tables(observed,candidate)
    if unmatched_source or unmatched_candidate:
        add('tables.alignment',{'unmatched_source_indices':unmatched_source},
            {'unmatched_candidate_indices':unmatched_candidate,'reason':'Missing or ambiguous source table identity; reinspect before cell comparison'})
    for si,ti in pairs:
        source=observed.tables[si];table=candidate.tables[ti]
        prefix=f'tables[{ti}]'
        if len(source.columns)!=len(table.columns):add(prefix+'.columns',len(source.columns),len(table.columns))
        if len(source.rows)!=len(table.rows):add(prefix+'.rows',len(source.rows),len(table.rows))
        for ci,(sc,cc) in enumerate(zip(source.columns,table.columns)):
            cp=prefix+f'.columns[{ci}]'
            if same_header_partition(sc,cc):continue
            if condition_keys(sc)!=condition_keys(cc):
                add(cp+'.conditions',{'group':sc.group,'label':sc.label,'qualifier':sc.qualifier},
                    {'group':cc.group,'label':cc.label,'qualifier':cc.qualifier})
            components=[]
            for attr in ('unit','qualifier'):
                a=getattr(sc,attr);b=getattr(cc,attr)
                compatible=(unit_key(a)==unit_key(b) if attr=='unit' else column_key(a,sc)==column_key(b,cc)) or bool(a and not b and header_has(cc,a,attr)) or bool(b and not a and header_has(sc,b,attr))
                if attr=='qualifier' and any(x and re.search(CONDITION_START,x,re.I) for x in (a,b)) and condition_keys(sc)!=condition_keys(cc):compatible=False
                if not compatible:add(cp+'.'+attr,a,b)
                else:components.append((attr,a or b))
            combined=' '.join(header_without(x,components,cc) for x in (cc.group,cc.label) if x)
            if header_key(header_without(sc.label,components,sc)) not in header_key(combined):add(cp+'.label',sc.label,cc.label)
            if sc.group and header_key(header_without(sc.group,components,sc)) not in header_key(combined):add(cp+'.group',sc.group,cc.group)
        for ri,(sr,cr) in enumerate(zip(source.rows,table.rows)):
            sv={c.column_id:c for c in sr.cells};cv={c.column_id:c for c in cr.cells}
            for ci,(sc,cc) in enumerate(zip(source.columns,table.columns)):
                a=sv[sc.id];b=cv[cc.id];path=prefix+f'.rows[{ri}].cells[column={ci}]'
                if a.state!=b.state:add(path+'.state',a.state,b.state)
                if a.value is None and b.value is None:continue
                identity=bool(re.search(r'\b(?:тип\w*|артикул\w*|марк\w*|обознач\w*|код\w*|наименован\w*|product|identity|designation)\b',' '.join(x for x in (sc.group,sc.label) if x),re.I))
                if not same_value(a.value,b.value,identity):add(path+'.value',a.value,b.value)
    all_text=text_key(' '.join(b.text for b in candidate.text_blocks))
    branding=[b.text for b in candidate.text_blocks if b.kind=='branding']
    for i,block in enumerate(observed.text_blocks):
        # This is semantic digitization, not sentence-by-sentence OCR. The
        # independent review must explicitly verify technical facts and their
        # relationships before PASS; no regex can certify narrative meaning.
        # Tables, identities in cells and engineering labels stay strict below.
        if semantic_narrative and block.kind in {'heading','paragraph'}:continue
        if block.kind=='branding' and branding_present(block.text,branding):continue
        if text_key(block.text) not in all_text:add(f'text_blocks[source={i}]',block.text,'missing or changed wording')
    # One source drawing can legitimately be represented as several views or
    # one combined figure. Compare labels across figures, retaining numeric bounds.
    labels=[figure_key(label) for f in candidate.figures for label in f.labels]
    descriptions=[figure_key(f.description) for f in candidate.figures]
    for i,sf in enumerate(observed.figures):
        # A pure software demonstration is described and semantically reviewed,
        # not certified by matching every tiny UI label. Mixed pages and actual
        # engineering drawings retain the complete strict label checks below.
        if semantic_narrative and independent_software_demonstration(observed,candidate):continue
        for label in sf.labels:
            key=figure_key(label)
            if key not in labels and not any(re.search(figure_pattern(label),d) for d in labels+descriptions):
                # Only a freshly source-bound, explicitly classified branding
                # quotation may change representation. Engineering labels never
                # inherit evidence from a caption or unrelated prose.
                if (label in (branding_figure_quotes or {}).get(i,set()) and
                        branding_present(label,branding)):continue
                add(f'figures[{i}].labels',label,'missing or changed label/tolerance')
    return differences
