"""Keep visible branding quotes distinct from text-layer and Vision evidence."""
import math
import re
import unicodedata
import pymupdf


def quote_key(text):
    # Typography may use small capitals; no translations/operator substitutions.
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text).casefold())


def is_branding_caption(text):
    normalized=unicodedata.normalize('NFKC',text)
    return (not any(c.isnumeric() for c in text) and
            not re.search(r'\d|[+±<>=≤≥⌀φΦøØ∅−°^*]',normalized) and
            not re.fullmatch(r'[IVXLCDM]+',re.sub(r'\s+','',normalized),re.I) and
            not re.search(r'\s-\s',normalized) and
            len(re.findall(r'[^\W\d_]',normalized))>=3)


def branding_quote_evidence(context,page,model,proofs,after=0):
    indices={i for i,b in enumerate(model.text_blocks) if b.kind=='branding'}
    proofs=[] if proofs is None else proofs
    if not isinstance(proofs,list):return [],['literal_quotes must be a list']
    records=[];errors=[];seen=set();figure_seen=set()
    with pymupdf.open(context.source) as doc:
        source=doc[page-1]
        for item in proofs:
            if not isinstance(item,dict) or set(item)-{'block_index','figure_index','label_index','source_kind','box','visible_quote','basis','conflict','rotation'}:
                errors.append('Unknown or malformed literal quote evidence');continue
            index=item.get('block_index');box=item.get('box');rotation=item.get('rotation',0)
            if 'figure_index' in item or 'label_index' in item:
                fi=item.get('figure_index');li=item.get('label_index')
                if ('block_index' in item or item.get('source_kind')!='branding' or type(fi) is not int or type(li) is not int or
                        not 0<=fi<len(model.figures) or not 0<=li<len(model.figures[fi].labels) or (fi,li) in figure_seen):
                    errors.append('A figure branding caption needs unique figure_index/label_index, source_kind=branding and no block_index');continue
                expected=model.figures[fi].labels[li]
                if not is_branding_caption(expected):
                    errors.append('Engineering numbers, operators, diameter signs and short view letters cannot be reclassified as branding');continue
                figure_seen.add((fi,li))
            else:
                if type(index) is not int or index not in indices or index in seen or item.get('source_kind','branding')!='branding':
                    errors.append('Every branding block needs one unique exact integer block_index');continue
                seen.add(index);expected=model.text_blocks[index].text
            if (not isinstance(box,list) or len(box)!=4 or
                    any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in box) or
                    box[0]>=box[2] or box[1]>=box[3] or type(rotation) is not int or rotation not in (0,90,180,270)):
                errors.append('Invalid literal quote source region');continue
            if context.region_evidence.get((page,tuple(box),rotation),0)<=after:
                errors.append('View the exact quoted source region before recording this quote');continue
            visible=item.get('visible_quote');basis=item.get('basis');conflict=item.get('conflict')
            if visible!=expected or not isinstance(visible,str) or not visible.strip():
                errors.append('visible_quote must equal the literal branding block, without added description');continue
            if basis not in ('text_layer','vision') or (conflict is not None and not isinstance(conflict,str)):
                errors.append('Quote basis must be text_layer or vision, with a textual conflict if needed');continue
            rect=pymupdf.Rect(box[0]*source.rect.width,box[1]*source.rect.height,box[2]*source.rect.width,box[3]*source.rect.height)
            native=source.get_text('text',clip=rect,sort=True)
            status='unavailable' if not native.strip() else 'agree' if quote_key(visible)==quote_key(native) else 'conflict'
            records.append({**item,'rotation':rotation,'text_layer_quote':native,'status':status})
            if status=='agree' and conflict:
                errors.append('The text layer agrees; do not invent a conflict')
            elif status=='unavailable' and basis!='vision':
                errors.append('No text-layer quote in this box: use independently inspected Vision evidence, not an invented native quote')
            elif status=='conflict' and (basis!='vision' or not conflict or not conflict.strip() or conflict not in model.source_notes):
                errors.append('Literal branding differs from this text-layer box. Reinspect the original; retain its original language. A confirmed visible/text-layer conflict must be separately stated in source_notes with Vision evidence, never silently translated or overwritten')
    if seen!=indices:errors.append('Provide literal quote evidence for every branding block only')
    return records,errors
