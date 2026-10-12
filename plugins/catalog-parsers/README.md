# Catalogue parser tools

Agent Plugin 1.0 with MCP tools and a skill for comparing source-bound parser evidence before an agent saves reviewed catalogue JSON. Docling is the strongest measured overall default; img2table and gmft provide complementary table evidence.

```bash
uv run --project plugins/catalog-parsers --extra docling catalog-parsers-mcp
```

Install the plugin using the host's native marketplace mechanism. Its `plugin.json`, `.mcp.json` and `skills/` are the standard contribution surfaces. FastAgent receives the portable package through its native MCP configuration and SkillRegistry; the extractor integration binds source, physical page and private cache directory. Its separate command-plugin marketplace format is not presented as Agent Plugin 1.0.

The base extra-free install includes PyMuPDF4LLM. `--extra docling` adds the local Docling backend. CPU conversion uses two threads, table reconstruction and native text; OCR is explicitly disabled for these text-based catalogue tests. There is no model provider fallback and no cloud conversion. Dependency licenses remain those of their upstream projects.

To measure a direct parser:

```bash
catalog-parsers --source catalogue.pdf --page 78 --backend docling --output results/direct --model not-applicable
```

The adapter retains raw JSON, an unreviewed canonical page and source/page/version/time/hash receipt. It never reads benchmark gold. This is a direct parser arm, not an LLM run; compare it separately from an agent using parser evidence. Missing/conflicting cells are unknown; explicitly emitted empty strings are reported blanks. Multi-parameter header collapse remains visible.

## Isolated optional executors

Set `CATALOG_PARSER_EXECUTORS` to a private JSON file to expose already installed optional backends. The CLI forwards this path to the plugin; no provider credentials are sent to native parser executors.

```json
{
  "img2table": {"python": "/absolute/env/bin/python", "version": "2.0.0", "device": "cpu", "timeout_seconds": 180},
  "gmft": {"python": "/another/env/bin/python", "version": "0.4.4", "device": "cpu", "timeout_seconds": 180}
}
```

Use the virtual environment interpreter path itself, preserving its symlink; resolving it to the base Python loses the installed dependencies. Backend versions are checked against actual execution receipts. `parser_capabilities` lists configured backends; the first call confirms their usability. Native outputs, source binding, hashes, device and time remain in private artifacts. Tampered or changed caches are rejected.

An executor may instead declare `remote: {host, port, root, python}` for an explicitly provisioned SSH host. Transport is foreground SSH/SCP with bounded native deadlines and a separate transport receipt. `metal`/`vulkan` are MinerU's native acceleration options; Paddle and gmft use `cuda`. There is no hidden CPU fallback. Install extras in isolated environments to avoid conflicting OpenCV/Torch requirements. See the measured selection [skill](skills/catalog-parser-selection/SKILL.md).
