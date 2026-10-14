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
