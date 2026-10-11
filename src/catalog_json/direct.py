"""AnyDoc is an input adapter. Markdown never becomes the canonical output."""
import re
import anydoc
import pymupdf
from .schema import PageContent, TextBlock, Table, Column, Row, Cell


def parse_anydoc(markdown: str) -> PageContent:
    lines=markdown.splitlines();blocks=[];tables=[];i=0;title=""
    while i<len(lines):
        line=lines[i].strip()
        if line.startswith("|") and i+1<len(lines) and re.search(r"\|\s*:?-{2,}",lines[i+1]):
            labels=[s.strip() for s in line.strip("|").split("|")]
            columns=[Column(id=f"c{j+1}",label=s,unit=(re.search(r",\s*([^,]+)$",s).group(1) if re.search(r",\s*([^,]+)$",s) else None)) for j,s in enumerate(labels)]
            rows=[];i+=2
            while i<len(lines) and lines[i].strip().startswith("|"):
                values=[s.strip() for s in lines[i].strip().strip("|").split("|")]
                if len(values)!=len(columns):raise ValueError("AnyDoc emitted a ragged table")
                rows.append(Row(cells=[Cell(column_id=c.id,value=v or None,state="value" if v else "blank") for c,v in zip(columns,values)]));i+=1
            tables.append(Table(id=f"t{len(tables)+1}",title="",columns=columns,rows=rows))
            continue
        if line:
            text=line.lstrip("# ") if line.startswith("#") else line
            kind="heading" if line.startswith("#") else "paragraph"
            if not title and kind=="heading":title=text
            blocks.append(TextBlock(kind=kind,text=text))
        i+=1
    return PageContent(title=title,text_blocks=blocks,tables=tables,figures=[])


def inspect_page(page: pymupdf.Page, pdf_bytes: bytes):
    reasons=[]
    try:
        markdown=anydoc.to_markdown_bytes(pdf_bytes)
        candidate=parse_anydoc(markdown)
    except (anydoc.ConvertError, ValueError) as exc:
        return None,"",[f"anydoc:{type(exc).__name__}"]
    if len(page.get_text().strip())<80:reasons.append("thin_or_scanned_text")
    if any(abs(line.get("dir",(1,0))[1])>.05 for block in page.get_text("dict")["blocks"] for line in block.get("lines",[])):
        reasons.append("rotated_text")
    if page.get_images() or len(page.get_drawings())>8:reasons.append("images_or_vector_layout")
    if re.search(r"\b(?:Наименование|Обозначение|Масса|Размеры)\b",markdown,re.I) and not candidate.tables:
        reasons.append("table_structure_not_preserved")
    return candidate,markdown,reasons
