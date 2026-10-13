"""Literal PDF drawing evidence in the same coordinates as the page viewer.

PyMuPDF returns unrotated geometry; apply Page.rotation_matrix before normalizing.
https://pymupdf.readthedocs.io/en/latest/page.html#Page.rotation_matrix
No geometry, part names or dimension ownership are inferred from the text.
"""
import math
import re
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


def dimension_candidates(page,box,label,source_sha256=None):
    """Shortlist literal line endpoints beside a numeric label, without naming a part."""
    label=label.strip()
    if not re.fullmatch(r'[φØø⌀]?\s*\d+(?:[.,]\d+)?',label):raise ValueError('Use one printed numeric dimension, optionally with its diameter glyph')
    def key(text):return re.sub(r'^[φØø⌀]\s*','',text.strip()).replace(',','.')
    data=drawing_geometry(page,box,source_sha256);width,height=page.rect.width,page.rect.height
    def native(point):return [point[0]*width,point[1]*height]
    triangles=[]
    for triangle in data['small_filled_triangles']:
        vertices=[native(v) for v in triangle['vertices']]
        edges=sorted((math.dist(vertices[a],vertices[b]),a,b) for a,b in ((0,1),(1,2),(0,2)))
        tip=None
        if edges[0][0]<edges[1][0]*.5:
            tip=next(i for i in range(3) if i not in edges[0][1:])
        triangles.append((triangle['path_id'],vertices,None if tip is None else triangle['vertices'][tip]))
    lines=[]
    for path in data['paths']:
        if path['stroke'] is None:continue
        for item in path['items']:
            if item['kind']!='l':continue
            a,b=[native(p) for p in item['points']];dx=b[0]-a[0];dy=b[1]-a[1];length=math.hypot(dx,dy)
            if length<.2:continue
            attached=[]
            for end in (a,b):
                attached.append([{'path_id':identifier,'tip_candidate':tip} for identifier,vertices,tip in triangles if min(math.dist(end,v) for v in vertices)<=1.5])
            if not all(attached):continue
            lines.append((path,item,a,b,dx/length,dy/length,length,attached))
    labels=[]
    for word in data['words']:
        if key(word['text'])!=key(label):continue
        if word['direction'] is None:continue
        x0,y0,x1,y1=word['box'];center=native([(x0+x1)/2,(y0+y1)/2]);direction=word['direction'];candidates=[]
        for path,item,a,b,ux,uy,length,attached in lines:
            if abs(ux*direction[1]-uy*direction[0])>.04:continue
            vx=center[0]-a[0];vy=center[1]-a[1];projection=vx*ux+vy*uy;distance=abs(vx*uy-vy*ux)
            margin=max((x1-x0)*width,(y1-y0)*height)/2
            if not -margin<=projection<=length+margin or distance>40:continue
            candidates.append({'path_id':path['id'],'item_index':item['index'],'endpoints':item['points'],
                               'length_pdf_points':length,'label_distance_pdf_points':distance,
                               'nearby_filled_triangles_at_each_end':attached})
        candidates.sort(key=lambda c:c['label_distance_pdf_points'])
        labels.append({'label':word,'candidate_count':len(candidates),'candidates':candidates[:6],
                       'selection_limit':6,'selection':'nearest parallel source lines with small filled triangles near both ends; these are candidates, not certified dimension lines'})
    return {'physical_page':page.number+1,'source_sha256':source_sha256,'box':list(box),'query':label,
            'coordinate_system':data['coordinate_system'],'matching_labels':labels,
            'limits':'Literal shaft endpoints; no measured-feature name, physical length or unit is inferred. A narrow triangle vertex opposite its uniquely short base is returned as a tip candidate, not a certified arrow. Shaft ends can lie at arrowhead bases: inspect tip candidates and extension lines, not just shaft ends. Marks can be unrelated; ranking is a heuristic and drawings need not be to scale. Verify the original. Empty candidates can mean a scan, outlined text, callout, different arrowhead geometry or unresolved evidence; use Vision/full geometry index. All source paths remain accessible through read_drawing_paths.'}
