"""Literal PDF drawing evidence in the same coordinates as the page viewer.

PyMuPDF returns unrotated geometry; apply Page.rotation_matrix before normalizing.
https://pymupdf.readthedocs.io/en/latest/page.html#Page.rotation_matrix
No geometry, part names or dimension ownership are inferred from the text.
"""
import math
import pymupdf


def drawing_geometry(page,box,source_sha256=None):
    if (len(box)!=4 or any(not math.isfinite(v) or not 0<=v<=1 for v in box)
            or box[0]>=box[2] or box[1]>=box[3]):
        raise ValueError('Box must be [left,top,right,bottom] normalized to 0..1')
    prefix=(f's{source_sha256}-' if source_sha256 else '')+f'page{page.number+1}-'
    matrix=page.rotation_matrix;viewport=page.rect
    def point(value):
        p=pymupdf.Point(value)*matrix
        return [(p.x-viewport.x0)/viewport.width,(p.y-viewport.y0)/viewport.height]
    def bounds(value):
        rect=pymupdf.Rect(value);points=[point(rect.tl),point(rect.tr),point(rect.br),point(rect.bl)]
        return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]
    def intersects(a):
        # A native horizontal/vertical line may have a zero-area bounding box.
        return a[0]<=box[2] and a[2]>=box[0] and a[1]<=box[3] and a[3]>=box[1]
    directions={}
    for block_index,block in enumerate(page.get_text('dict')['blocks']):
        for line_index,line in enumerate(block.get('lines',[])):
            x,y=line['dir'];dx=x*matrix.a+y*matrix.c;dy=x*matrix.b+y*matrix.d
            length=math.hypot(dx,dy)
            directions[block.get('number',block_index),line_index]=[dx/length,dy/length]
    words=[]
    for index,word in enumerate(page.get_text('words')):
        b=bounds(word[:4])
        if intersects(b):words.append({'id':f'{prefix}w{index}','text':word[4],'box':b,'direction':directions.get((word[5],word[6]))})
    paths=[];triangles=[]
    for index,path in enumerate(page.get_drawings()):
        b=bounds(path['rect'])
        if not intersects(b):continue
        identifier=f'{prefix}p{index}';items=[];vertices=[]
        for item_index,item in enumerate(path['items']):
            kind=item[0]
            if kind in {'l','c'}:
                points=[point(p) for p in item[1:]]
                if kind=='l':vertices.extend(points)
            elif kind=='re':
                r=pymupdf.Rect(item[1]);points=[point(p) for p in [r.tl,r.tr,r.br,r.bl]]
            elif kind=='qu':
                q=pymupdf.Quad(item[1]);points=[point(p) for p in [q.ul,q.ur,q.lr,q.ll]]
            else:raise ValueError(f'Unsupported native drawing primitive: {kind}')
            record={'index':item_index,'kind':kind,'points':points}
            if kind=='re' and len(item)>2:record['orientation']=item[2]
            items.append(record)
        paths.append({'id':identifier,'sequence':path.get('seqno'),'box':b,'type':path['type'],
                      'stroke':path.get('color'),'fill':path.get('fill'),'line_width_pdf_points':path.get('width'),
                      'dashes':path.get('dashes'),'line_cap':path.get('lineCap'),'line_join':path.get('lineJoin'),
                      'closed':path.get('closePath'),'even_odd':path.get('even_odd'),
                      'fill_opacity':path.get('fill_opacity'),'stroke_opacity':path.get('stroke_opacity'),'items':items})
        unique=list(dict.fromkeys(tuple(p) for p in vertices))
        # Preserve candidate arrowhead geometry, never declare a semantic arrow.
        # Small filled triangles can also be ordinary graphical marks.
        native=pymupdf.Rect(path['rect'])
        if path.get('fill') is not None and len(unique)==3 and max(native.width,native.height)<=14:
            triangles.append({'path_id':identifier,'vertices':[list(p) for p in unique],'box':b})
    return {'physical_page':page.number+1,'pdf_rotation':page.rotation,'box':list(box),
            'coordinate_system':'normalized original page viewer, top-left origin; rotation applied',
            'words':words,'paths':paths,'small_filled_triangles':triangles,
            'limits':'Native source evidence, not inferred feature ownership. Segmented circles may have solid dashes metadata. Hidden text/vector content can differ from the visible original; inspect a zoom containing the label, both endpoints and measured contour. Raster drawings require Vision; empty native paths do not prove an absent drawing.'}
