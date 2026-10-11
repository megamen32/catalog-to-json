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

```bash
catalog-json benchmark score --fixture .tmp/benchmark/case-78.json \
  --candidate .tmp/benchmark/glm-repeat-1/page-0078/candidate-0.json \
  --output .tmp/benchmark/glm-score.json
```

A fixture records independently verified table cells, physical merge spans, selected header assertions and diagram-label alternatives. Never copy a model's unverified output into the gold. User files and annotations are not bundled in the public repository.

Scores distinguish literal cell accuracy, numeric-equivalent accuracy, true blanks, merged cells, header assertions and figure labels. Decimal commas can be numerically equivalent while differing literally. Cyrillic/Latin identities and technical symbols remain distinct; diagram aliases are allowed only when explicitly annotated from genuinely ambiguous source glyphs. The tolerance ±2 never matches =2 or ±20. Extra/missing tables, rows and columns are reported independently.

Coverage is explicit: this initial scorer does not grade all prose, reading order, or diagram relationships. A perfect score on verified assertions does not mean the entire page is perfect. Reuse results only with matching source, fixture, model, project revision and artifact hashes. Run multiple fresh repeats before interpreting differences as stable model performance.

Additional projects need thin deterministic adapters to the page schema. Keep their raw outputs; no extra LLM may repair or normalize an arm during scoring. Adapter selection awaits the user's project links.
