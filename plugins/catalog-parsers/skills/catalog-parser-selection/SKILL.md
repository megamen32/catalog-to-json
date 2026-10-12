---
name: catalog-parser-selection
description: Choose complementary catalogue parsers from measured strengths, preserve raw evidence, and escalate rotated headers, units, merges and drawings to source Vision.
---
# Choose evidence for the page

Call parser_capabilities first. Use only explicitly available backends; an unavailable GPU/backend is a reported failure, not permission for a hidden device or provider fallback. All tools are bound to this source and physical page. inspect_pdf_page returns inventory/headers, not body cell values. After any successful parser call, read its canonical rows with read_parser_artifact, following next_offset through every needed row. Replies are bounded by serialized bytes, so the returned chunk may be shorter than requested length. Advance only by returned next_offset, never by requested length. A shortened SDK result must be retrieved in smaller ranges; do not infer its missing middle. For disputed blanks/merges also read raw spans. A successful receipt or header inventory is not proof that you have seen body values; keep receipts.

## Measured complementary roles

- **Docling** is the default table/layout evidence. It was the strongest overall standalone parser in our 15-page, 500-fact CPU experiment (266/500). It can retain separate tables and explicit cell spans. On rotated headers it can still collapse columns or omit a parameter: its output requires comparison with the original.
- **img2table** is a useful independent geometry check for visibly ruled tables, especially simpler native-text grids. It recovered facts missed by Docling in small/armature/isolator examples and used about 19 seconds for 15 pages. Compare raw cell boxes for actual merge coverage. It has no guaranteed semantic header roles; a fast empty value is not source evidence for a blank.
- **gmft** supplies independently detected table regions and hierarchical header structure. It beat Docling on two innovation-table examples, despite a lower overall score. Use it when a detected table or header hierarchy looks incomplete. It does not reliably resolve interior body merges or individually rotated labels; inspect its geometry/outliers and original image.
- **PyMuPDF4LLM** remains another native text/layout view. Do not adopt collapsed composite engineering columns merely because numbers are present; its joint-fact accuracy on these stress pages was low.
- **LiteParse** is fast spatial text/block evidence; our difficult table fact score was very low. It is not a default table substitute. No bounding box or zero-area padding means unknown, not a confirmed blank.
- **MinerU/Paddle** are optional local OCR/layout experiments. Metal/Vulkan/CUDA availability and the exact tier/device are explicit. Their OCR output may change Cyrillic/Latin identities or omit rotated table headers. Use them as supplementary evidence only when present; no engineering accuracy advantage is assumed from GPU execution or upstream claims.

These limited examples suggest routing, not a universally validated classifier. Scores cover selected engineering facts, not complete pages. Never choose by a benchmark answer or case ID. Use visible source properties and actual parser disagreements.

## Inspection and escalation

Start with AnyDoc/native extraction. For a complex table get Docling evidence; for a ruled grid compare img2table; for a questionable detected region or nested header compare gmft. Do not call every parser on every page by default. If one parser fails or omits a table, explicitly select another available backend or original-image Vision.

Table-count/physical-column mismatches, collapsed independent parameters, missing units/conditions, incorrect merge propagation, unexplained empty values, altered tolerances and unread rotated labels require source-image verification. Use view_region with rotation, read_source_layout for codepoints, and read_source_table for directly supported merge geometry. Before writing blank, distinguish a source blank from unknown and from a value owned by a merged cell spanning that row. Reconstruct the whole parent/child condition including negation (for example «не менее»), and bind each unit to its own parameter. An adjacent current unit cannot supply a voltage unit. Majority agreement does not prove correctness.

Retain literal source spelling, including source typos. Never invent a value, repair from gold, translate a Latin/Cyrillic lookalike or confuse letter З with digit 3. Drawings still require original-image inspection of all views, labels, hole counts and tolerances. A source limitation confirmed by zoom belongs in source_notes; unresolved technical unknowns remain uncertainties and block acceptance.

Save through the catalogue tools, then use a fresh independent reviewer for every cell and all other page content. Record actual backend/package/adapter versions, options, device, raw output, timing and source/candidate hashes. Keep direct-parser, first-pass agent and reviewed conversion measurements separate.
