# Architecture

AnyDoc supplies PDF text locally. Its pinned Python PDF API exposes Markdown, not the shared document IR. Markdown is a temporary diagnostic intermediary; it is normalized into the project's typed JSON and never used as the output contract.

PyMuPDF splits/renders selected pages and detects rotated text, thin text layers and image/vector layouts. These pages use FastAgent Vision. Direct pages still pass a source-image review. If direct output fails review, repair uses Vision.

Two FastAgent roles have no shared history. Extractor returns PageContent through native structured output. Reviewer returns explicit checks for text completeness, table/row/column coverage, values, units, merged cells, blank cells, rotated labels, figures and provenance. Each category needs positive evidence; independent source table dimensions must match the candidate. Any issue/unknown/uncertainty prevents acceptance. Source typos must remain literal and be described in source_notes.

Failed candidates and every review are retained. Automatic repair receives source image, candidate and defect report; bounded iterations prevent unlimited correction loops. A source filename/SHA256, model selection, routing reasons and page number identify every result. `complete_for_selection` differs from `catalog_complete`: selected-page success never implies the entire PDF was converted.

Tables use named columns and exactly one typed cell per column/row. `blank` means a real source blank; `unknown` means missing/illegible evidence. Symbols such as Ø, □ and Cyrillic/Latin product codes stay literal. Table variants never inherit specifications from another table without source evidence.

The design is informed by megamen32/pdf-markdown-docx (direct/page Vision) and pdf_to_docx_ocr_llm (separate cleanup phase), but the output contract is JSON and extraction values are not hand-edited.
