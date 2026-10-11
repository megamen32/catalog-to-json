# Catalog extraction benchmark

Use the same original page across every project/model arm. Keep golden annotations private and out of extractor inputs. Quality comes from deterministic comparisons with independently checked source facts, not a model's own approval.

## Find difficult cases

```bash
catalog-json benchmark scan catalog-a.pdf catalog-b.pdf \
  --output .tmp/benchmark/inventory --per-catalog 3 \
  --anchor catalog-a.pdf:78
```

This inventories every physical PDF page, saves resumable records and renders candidate contact sheets. Rankings use rotated text, dense vector tables, tiny text and dimension labels. They are complexity heuristics, not quality measurements. Visually curate the candidates; exclude covers and mark duplicated product families. Record printed page numbers separately from physical indices. Unannotated candidates cannot receive accuracy scores.

## Compare fresh model outputs

```bash
catalog-json benchmark extract catalog-a.pdf --page 78 \
  --model 'zai.glm-5.3-flash?reasoning=low' \
  --config fast-agent.config.example.yaml --output .tmp/benchmark/glm-repeat-1
catalog-json benchmark extract catalog-a.pdf --page 78 \
  --model 'anthropic.MiniMax-M3.1-Flash-Preview?reasoning=medium' \
  --config fast-agent.config.example.yaml --output .tmp/benchmark/minimax-repeat-1
```

This native adapter runs only first-pass extraction, without reviewer feedback, a golden fixture or repairs. Every repeat needs a fresh output directory. `run.json` records source hash, physical page, project revision, explicit model/reasoning selection, status and elapsed time. Tokens and cost remain unknown when not reported; they are never guessed. Failed/time-limited runs remain failures. Compare first-pass arms with first-pass arms; label a complete extraction/review/repair pipeline separately.

## Score saved artifacts

External result archives can join the comparison even when their executable is unavailable:

```bash
catalog-json benchmark import-jsonl \
  --products products.jsonl --characteristics characteristics.jsonl \
  --families families.jsonl --document-id src03 --page 78 \
  --output .tmp/benchmark/external-page-78
```

This adapter preserves reported product identities, table coordinates, composite headers,
units, blank states and Unicode values. It never repairs them from the PDF or gold, never
expands merged values, and marks missing/conflicting coordinates unknown. Raw JSONL inputs
remain the authoritative evidence; their hashes and the adapter hash accompany the import.
Unlocated characteristics are counted separately and retained in the raw input, not guessed
into cells. Drawing structure and merge geometry are not represented by this format.
`import.json` labels the stage `imported_result`, with unverified runtime and unknown model,
time, tokens and cost. A sender's description of a model belongs in a separate witness note.
Do not call an import a fresh model run, or compare its import duration with extraction time.

The positional cell scorer also reports shape differences. An imported transposed or
collapsed table must not be treated as an equivalent table merely because some numbers
are present. For cross-format comparisons, additionally verify product identity, the exact
parameter/qualifier and its unit together. A value-only score is not a semantic fact score.
Selected partial assertions are not whole-page ground truth. Source typos must be retained
with notes; visually identical alphabet choices should be reported separately from numeric
or engineering errors. Report family-level coverage when multiple cases share one template.

```bash
catalog-json benchmark score --fixture .tmp/benchmark/case-78.json \
  --candidate .tmp/benchmark/glm-repeat-1/page-0078/candidate-0.json \
  --output .tmp/benchmark/glm-score.json
```

A fixture records independently verified table cells, physical merge spans, selected header assertions and diagram-label alternatives. Never copy a model's unverified output into the gold. User files and annotations are not bundled in the public repository.

Scores distinguish literal cell accuracy, numeric-equivalent accuracy, true blanks, merged cells, header assertions and figure labels. Decimal commas can be numerically equivalent while differing literally. Cyrillic/Latin identities and technical symbols remain distinct; diagram aliases are allowed only when explicitly annotated from genuinely ambiguous source glyphs. The tolerance ±2 never matches =2 or ±20. Extra/missing tables, rows and columns are reported independently.

Coverage is explicit: this initial scorer does not grade all prose, reading order, or diagram relationships. A perfect score on verified assertions does not mean the entire page is perfect. Reuse results only with matching source, fixture, model, project revision and artifact hashes. Run multiple fresh repeats before interpreting differences as stable model performance.

Additional projects need thin deterministic adapters to the page schema. Keep their raw outputs; no extra LLM may repair or normalize an arm during scoring. Adapter selection awaits the user's project links.

## Project/model matrix

`catalog-json benchmark run suite.json --output .tmp/benchmark/experiment-1` dispatches one isolated command-adapter run per project, model, case and repeat. `--resume` reuses matching completed artifacts and regrades them without another model call. Failed runs and interrupted runs with unknown completion are retained without replay; use a deliberately new repeat/experiment for a new invocation.

A manifest has this shape (paths relative to the manifest):

```json
{
  "cases": [{"id": "page78", "source": "catalog.pdf", "page": 78, "fixture": "gold/page78.json"}],
  "projects": [{
    "id": "catalog-to-json", "version": "pinned-project-revision",
    "cwd": "/path/to/catalog-to-json",
    "command": [".venv/bin/catalog-json", "benchmark", "extract", "{source}", "--page", "{page}", "--model", "{model}", "--config", "/path/to/fast-agent.yaml", "--output", "{run_dir}/result"],
    "artifact": "result/page-0078/candidate-0.json",
    "model_receipt": "result/run.json", "stage": "first_pass"
  }],
  "models": ["zai.glm-5.3-flash?reasoning=low", "anthropic.MiniMax-M3.1-Flash-Preview?reasoning=medium"],
  "repeats": 1, "timeout_seconds": 300, "deadline_seconds": 900
}
```

Commands are argv arrays, executed without a shell. The selected model must be passed explicitly through `{model}`. When a runtime receipt is supplied, the runner checks the actual adapter-reported model, source hash and page before grading. Each adapter must emit the canonical page JSON; project-specific parsing is deterministic and versioned, with the original output retained. Never introduce an additional LLM during normalization. Project/model receipts are isolated from the golden fixture. The runner records source revisions, command-file hashes, statuses, elapsed time, artifact hashes and grader/fixture hashes. Unsupported or invalid output is a failed arm, not a passing parse.

The initial scorer accepts punctuation differences such as `d1, 4 отв.` and `d1 (4 отв.)` while retaining numeric bounds; it still rejects `H=2` or `H±20` for `H±2`. This is label coverage, not a semantic judgment of the full drawing description.
