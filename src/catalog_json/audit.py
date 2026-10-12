"""Compare independently tool-recorded source observations with the candidate."""
import re
import unicodedata
from decimal import Decimal,InvalidOperation
from .schema import PageContent


def text_key(value):
    text=unicodedata.normalize('NFKC',value).casefold()
    return re.sub(r'[^\w+±-]','',text)


def header_key(value):
    return re.sub(r'[^\w+±<>=≤≥/·^*-]','',unicodedata.normalize('NFKC',value).casefold())


def figure_key(value):
    # Image observations cannot disambiguate identical Latin/Cyrillic glyph shapes.
    text=unicodedata.normalize('NFKC',value.translate(str.maketrans('АВЕКМНОРСТХавекмнорстх','ABEKMHOPCTXabekmhopctx'))).casefold()
    text=re.sub(r'[φø⌀](?=\s*\d)','⌀',text)
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


def header_has(column,value,attr):
    pattern=component_pattern(value)
    flags=0 if attr=='unit' else re.I
    group=primary_header(column.group)
    if re.search(pattern,group,flags):return True
    # Never infer a parent parameter unit from a child condition. If a generic
    # group omits evidence, the reviewer must record the printed unit explicitly.
    if column.group:return False
    return bool(re.search(pattern,primary_header(column.label),flags))


def header_without(text,components):
    head=primary_header(text);tail=(text or '')[len(head):]
    for attr,component in components:
        if component:head=re.sub(component_pattern(component),'',head,count=1,flags=0 if attr=='unit' else re.I)
    return head+tail


def same_value(a,b,identity=False):
    if str(a)==str(b):return True
    if identity or isinstance(a,bool) or isinstance(b,bool):return False
    values=[]
    for value in (a,b):
        raw=str(value).replace(',','.')
        if not re.fullmatch(r'[+-]?(?:0|[1-9]\d*)(?:\.\d+)?',raw):return False
        try:values.append(Decimal(raw))
        except InvalidOperation:return False
    return values[0]==values[1]


def compare_source(observed: PageContent,candidate: PageContent):
    differences=[]
    def add(path,expected,actual):
        differences.append({'path':path,'source_observation':expected,'candidate':actual})
    if observed.uncertainties:add('source_observation.uncertainties',[],observed.uncertainties)
    if len(observed.tables)!=len(candidate.tables):add('tables',len(observed.tables),len(candidate.tables))
    for ti,(source,table) in enumerate(zip(observed.tables,candidate.tables)):
        prefix=f'tables[{ti}]'
        if len(source.columns)!=len(table.columns):add(prefix+'.columns',len(source.columns),len(table.columns))
        if len(source.rows)!=len(table.rows):add(prefix+'.rows',len(source.rows),len(table.rows))
        for ci,(sc,cc) in enumerate(zip(source.columns,table.columns)):
            cp=prefix+f'.columns[{ci}]'
            components=[]
            for attr in ('unit','qualifier'):
                a=getattr(sc,attr);b=getattr(cc,attr)
                key=(lambda x:re.sub(r'\s+','',unicodedata.normalize('NFKC',x or ''))) if attr=='unit' else (lambda x:header_key(x or ''))
                compatible=key(a)==key(b) or bool(a and not b and header_has(cc,a,attr)) or bool(b and not a and header_has(sc,b,attr))
                if not compatible:add(cp+'.'+attr,a,b)
                else:components.append((attr,a or b))
            combined=' '.join(header_without(x,components) for x in (cc.group,cc.label) if x)
            if header_key(header_without(sc.label,components)) not in header_key(combined):add(cp+'.label',sc.label,cc.label)
            if sc.group and header_key(header_without(sc.group,components)) not in header_key(combined):add(cp+'.group',sc.group,cc.group)
        for ri,(sr,cr) in enumerate(zip(source.rows,table.rows)):
            sv={c.column_id:c for c in sr.cells};cv={c.column_id:c for c in cr.cells}
            for ci,(sc,cc) in enumerate(zip(source.columns,table.columns)):
                a=sv[sc.id];b=cv[cc.id];path=prefix+f'.rows[{ri}].cells[column={ci}]'
                if a.state!=b.state:add(path+'.state',a.state,b.state)
                if a.value is None and b.value is None:continue
                identity=bool(re.search(r'\b(?:тип\w*|артикул\w*|марк\w*|обознач\w*|код\w*|наименован\w*|product|identity|designation)\b',' '.join(x for x in (sc.group,sc.label) if x),re.I))
                if not same_value(a.value,b.value,identity):add(path+'.value',a.value,b.value)
    all_text=text_key(' '.join(b.text for b in candidate.text_blocks))
    for i,block in enumerate(observed.text_blocks):
        if text_key(block.text) not in all_text:add(f'text_blocks[source={i}]',block.text,'missing or changed wording')
    # One source drawing can legitimately be represented as several views or
    # one combined figure. Compare labels across figures, retaining numeric bounds.
    labels=[figure_key(label) for f in candidate.figures for label in f.labels]
    descriptions=[figure_key(f.description) for f in candidate.figures]
    for i,sf in enumerate(observed.figures):
        for label in sf.labels:
            key=figure_key(label)
            if key not in labels and not any(re.search(figure_pattern(label),d) for d in labels+descriptions):
                add(f'figures[{i}].labels',label,'missing or changed label/tolerance')
    return differences
