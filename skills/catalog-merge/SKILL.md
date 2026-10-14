---
name: catalog-merge
description: Reconcile two existing technical catalogue extractions against original PDF pages, retaining exact input facts and source provenance. Use for catalogue page alignment and merge, not a new extraction or benchmark.
---

Work on the assigned catalogue/page only. The current owner split is recorded in
the task's full-alignment manifest. There are three logical participants: native
Codex, native ZCode GLM5.3Flash through CodingPlan, and FastAgent MiniMaxM3.1FlashPreview.
Current work is split among them; independent final checks happen later.

Use the same evidence helpers everywhere. Through GPTAdmin discover
`CatalogSourceTools`, select its explicit target, fetch the exact tool schema,
then execute. The configured child is project-local, no model API calls.
An image can arrive in the completed job's `result.content` as an image block;
inspect that actual image, rather than base64 text or a delivery acknowledgement.

- Start with `view_page`. `view_region` uses a normalized `[left,top,right,bottom]`
  box, optional rotation0/90/180/270. Magnify a specific ambiguous region.
- `read_source_layout` helps literal symbols; `inspect_layout` gives complete
  native words and stroked dividers. `read_source_table` helps merged cells.
  Look across the entire merged cell, not one model's text band.
- For an ambiguous dimension, use `inspect_drawing_geometry`, selected
  `read_drawing_paths`, and `trace_dimension_candidates`. Candidates alone do
  not establish the size's owning component; verify arrows and contour visually.
- Read long evidence with `read_source_artifact`, following every `next_offset`.

A one-page work MCP adds `get_work_page`, `read_work_items`, `read_work_text`,
`add_source_evidence`, `stage_work_groups`, and `finish_page_work` to those same
source tools. Read the exact original fact indices and contexts. Stage bounded
groups, referencing observed source regions. Every fact must occur exactly once;
frozen exact-agreement indices can be reused. The host binds identity and input
hashes, never the model. Completion preserves alternatives and explicitly says
`independent_final_review_complete=false`.

Distinguish one property expressed in different headers from actual value
conflicts; preserve variants and separate contexts. D/d, marks, numbers, units,
conditions, and dimension ownership remain strict. Do not call every unmatched
fact a new property without looking for its counterpart. Do not invent a scalar
to replace a list, or silently drop unresolved source facts.

Native Codex/ZCode may call the same Python helpers locally with their own
trusted identity if their current MCP wrapper cannot display images. Reuse the
existing source whitelist and immutable page packets, not fresh extraction.
Never claim a tool or visual check succeeded based only on registration.
