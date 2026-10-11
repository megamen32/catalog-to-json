"""Direct PDF table-body grids with geometry-backed merged-cell expansion."""
import contextlib
import sys
import unicodedata
import pymupdf


def table_grids(page,box):
    if len(box)!=4 or not all(0<=v<=1 for v in box) or box[0]>=box[2] or box[1]>=box[3]:raise ValueError('Normalized box must be [left,top,right,bottom]')
    width,height=page.rect.width,page.rect.height
    clip=pymupdf.Rect(box[0]*width,box[1]*height,box[2]*width,box[3]*height)
    xs=set()
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0]!='l':continue
            a,b=item[1:]
            if abs(a.y-b.y)<.2 and clip.y0<=a.y<=clip.y1 and abs(a.x-b.x)>3:
                xs.update(round(x,1) for x in (a.x,b.x) if clip.x0-2<=x<=clip.x1+2)
            elif abs(a.x-b.x)<.2 and min(a.y,b.y)<=clip.y1 and max(a.y,b.y)>=clip.y0 and clip.x0<=a.x<=clip.x1:
                xs.add(round(a.x,1))
    if len(xs)<2:return {'tables':[],'note':'No vector grid; use Vision or a larger body region.'}
    # PyMuPDF may print a layout advisory; stdout belongs exclusively to MCP.
    with contextlib.redirect_stdout(sys.stderr):
        found=page.find_tables(clip=clip,vertical_strategy='explicit',vertical_lines=sorted(xs),horizontal_strategy='lines',snap_tolerance=1,intersection_tolerance=2)
    tables=[]
    for table in found.tables:
        raw=table.extract();cells=[r.cells for r in table.rows];expanded=[];unknown=[];covered={}
        row_ranges=[]
        for row in cells:
            rects=[r for r in row if r]
            row_ranges.append((max(r[1] for r in rects),min(r[3] for r in rects)))
        col_ranges=[]
        for ci in range(table.col_count):
            rect=next(row[ci] for row in cells if row[ci] is not None)
            col_ranges.append((rect[0],rect[2]))
        for ri,row in enumerate(cells):
            y=sum(row_ranges[ri])/2;values=[]
            for ci,rect in enumerate(row):
                owner=ri
                if rect is None:
                    x=sum(col_ranges[ci])/2
                    owners=[k for k in range(ri) if cells[k][ci] and cells[k][ci][0]-1<=x<=cells[k][ci][2]+1 and cells[k][ci][1]-.1<=y<=cells[k][ci][3]+.1]
                    if not owners:
                        values.append(None);unknown.append({'row':ri,'column':ci,'reason':'No geometry-backed owner; inspect original'});continue
                    owner=owners[-1];covered.setdefault((owner,ci),[owner]).append(ri)
                value=raw[owner][ci]
                # Directional formatting marks are not printed catalog characters.
                values.append(''.join(c for c in (value or '') if unicodedata.category(c)!='Cf').strip())
            expanded.append(values)
        tables.append({'row_count':table.row_count,'column_count':table.col_count,'raw_rows':raw,'expanded_rows':expanded,
                       'column_ranges':[[round(x0/width,4),round(x1/width,4)] for x0,x1 in col_ranges],
                       'row_ranges':[[round(y0/height,4),round(y1/height,4)] for y0,y1 in row_ranges],
                       'merged_cells':[{'owner':[r,c],'covered_rows':rows,'box':[round(cells[r][c][0]/width,4),round(cells[r][c][1]/height,4),round(cells[r][c][2]/width,4),round(cells[r][c][3]/height,4)]} for (r,c),rows in covered.items()],
                       'unknown_cells':unknown})
    return {'tables':tables,'note':'Direct text-layer data; vertical bounds inferred from vector lines. Use a body-only box and inspect the image. Empty text may be a scan/outline, not a true blank. Headers and diagrams need separate inspection.'}
