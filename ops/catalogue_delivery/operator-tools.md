# Original-page tools for the operator

`python -m catalog_json.operator_tools --sources SOURCES.json --output SCRATCH`
serves the same local PDF evidence helpers used by FastAgent. Register it as a
project child through the selected GPTAdmin ShellMCP, then inspect `mcp_tools`
and invoke `mcp_call`. It needs no model key and makes no model calls.

`SOURCES.json` contains `{sha256,path}` entries for original PDFs. The operator
chooses one of these hashes and a physical page. `view_region` magnifies and
rotates a source crop; `inspect_layout` gives complete bounded native words and
stroked dividers. `read_source_table` helps inspect actual merge spans. Drawing
geometry and dimension candidates remain evidence requiring image review.
Large text results use `read_source_artifact` pagination. No acceptance/vote or
catalogue writing tools are registered by this adapter.

The reviewed single-child budget is 1GiB address-space hard limit, one CPU
affinity, serial operations, 256MiB scratch with 16MiB reserved before each call,
within the existing aggregate catalogue budget of14GiB/CPU2/tasks512/swap0.
No new daemon, listening port or per-thread global Codex MCP is required.
Before installation2026-10-14, server100 MemAvailable was39,776,312KiB,
retaining the20GiB SSH/database reserve. Exact native source/image canaries
follow installation. Frozen active adjudication modules are not modified.

Focused integration `tests/test_operator_tools.py` checks original PNG/layout,
source change/page limits, scratch admission, and actual MCP tool registration.
Observed3 checks1.14s; expected10s, emergency100s. This does not establish any
extraction accuracy score or completion of the catalogue reconciliation.

## Current-session access and page-owner work

On2026-10-15 the existing GPTAdmin child `CatalogSourceTools` returned its real
11-tool registry and an original isolators108 PNG crop through the Hub. Native
Codex can use this proxy in its current session; a new native session is not
needed merely to access these tools. ZCode uses the same explicit discovered
target and source whitelist. No specialized global MCP configuration was added.

`python -m catalog_json.reconciliation.page_work_tools --packet PAGE.json
--sources SOURCES.json --identity IDENTITY.json --output OWNER_OUTPUT` adds six
page-work tools to the same11 evidence tools. One instance is bound to one
physical source page and host-supplied owner identity. Exact original facts and
contexts are paginated without silent truncation; bounded group staging can be
repaired before save. Completion requires an actual original image operation,
all input facts exactly once, exact input SHA and a matching owner. It explicitly
defers the independent final audit. Outputs never overwrite prior owner work.

The `catalog-merge` skill is included in the existing Agent Plugin's `skills/`
directory and the Python wheel. It documents the same substrate for Codex,
ZCode and FastAgent, without duplicating a fourth GLM participant.

Full-page work uses the existing aggregate14GiB RAM/CPU2/tasks512/swap0 budget.
One MiniMax provider context initially,2GiB worker plus1GiB evidence child,
one CPU affinity each,1200s emergency page deadline and24h finite job.
Task scratch is explicitly4GiB (formerly2GiB for the smaller case cohort).
Fresh2026-10-14T22:23Z measurements:34,373,308,416bytes available RAM,
1,772,994,354bytes task files,218,873,831,424bytes free filesystem.
This leaves the20GiB host reserve; no cgroup limits or sibling workers are
changed. The additional disk allowance covers full980-page packets and owner
work, not a new benchmark. Admission stops before4GiB or on UNKNOWN/429.
