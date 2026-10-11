"""Compare independently tool-recorded source observations with the candidate."""
import re
import unicodedata
from .schema import PageContent


def text_key(value):
    text=unicodedata.normalize('NFKC',value).casefold()
    return re.sub(r'[^\w+±-]','',text)


def figure_key(value):
    # Image observations cannot disambiguate identical Latin/Cyrillic glyph shapes.
    return text_key(value.translate(str.maketrans('АВЕКМНОРСТХавекмнорстх','ABEKMHOPCTXabekmhopctx')))


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
            for attr in ('unit','qualifier'):
                if text_key(getattr(sc,attr) or '')!=text_key(getattr(cc,attr) or ''):add(cp+'.'+attr,getattr(sc,attr),getattr(cc,attr))
            combined=' '.join(x for x in (cc.group,cc.label,cc.unit,cc.qualifier) if x)
            if text_key(sc.label) not in text_key(combined):add(cp+'.label',sc.label,cc.label)
            if sc.group and text_key(sc.group) not in text_key(combined):add(cp+'.group',sc.group,cc.group)
        for ri,(sr,cr) in enumerate(zip(source.rows,table.rows)):
            sv={c.column_id:c for c in sr.cells};cv={c.column_id:c for c in cr.cells}
            for ci,(sc,cc) in enumerate(zip(source.columns,table.columns)):
                a=sv[sc.id];b=cv[cc.id];path=prefix+f'.rows[{ri}].cells[column={ci}]'
                if a.state!=b.state:add(path+'.state',a.state,b.state)
                if a.value is None and b.value is None:continue
                if str(a.value)!=str(b.value):add(path+'.value',a.value,b.value)
    all_text=text_key(' '.join(b.text for b in candidate.text_blocks))
    for i,block in enumerate(observed.text_blocks):
        if text_key(block.text) not in all_text:add(f'text_blocks[source={i}]',block.text,'missing or changed wording')
    if len(observed.figures)!=len(candidate.figures):add('figures',len(observed.figures),len(candidate.figures))
    for i,(sf,cf) in enumerate(zip(observed.figures,candidate.figures)):
        combined=figure_key(cf.description+' '+' '.join(cf.labels))
        for label in sf.labels:
            if figure_key(label) not in combined:add(f'figures[{i}].labels',label,'missing or changed label/tolerance')
    return differences
