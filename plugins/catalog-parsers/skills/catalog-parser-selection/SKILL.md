---
name: catalog-parser-selection
description: Use Docling or PyMuPDF4LLM MCP evidence when extracting engineering catalogues, especially rotated/merged tables; compare with source images before adopting fields.
---

Call parser_capabilities, then inspect_pdf_page for the bound physical PDF page. PyMuPDF4LLM is a quick structure/text view; Docling offers a separately reconstructed table model. Read retained canonical/raw artifacts in bounded chunks when their shapes or fields disagree with the original.

Parser outputs are unreviewed source evidence. A table-count mismatch, merged independent parameters, omitted rotated labels, missing unit/condition, changed tolerance or empty cell without evidence requires visual inspection and, where useful, the other backend. Do not convert an extraction failure into a source blank. Preserve source spelling and suspected source typos; do not repair a parser's values using benchmark answers.

Use the existing catalogue extraction tools to save the final schema-validated page and a fresh independent reviewer to audit every table/cell and remaining page content. Retain parser version/options, raw output and receipt so benchmark accuracy/time can be attributed to the actual backend and agent configuration. Benchmark first-pass results separately from reviewed/repaired results. No conversational transcripts are needed.
