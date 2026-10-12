# Catalogue parser tools

Agent Plugin 1.0 with MCP tools and a skill for comparing source-bound **Docling** and **PyMuPDF4LLM** evidence before an agent saves reviewed catalogue JSON.

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
