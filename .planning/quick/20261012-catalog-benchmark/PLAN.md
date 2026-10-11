# Difficult catalog page benchmark

Owner: this task; canonical main checkout. Preserve accepted extraction and private source files.

1. Inventory all 980 pages locally with finite runs and checkpoints; visually curate diverse difficult pages from every supplied PDF, always including page 78.
2. Build an independent fixture/scorer for the verified page-78 cells and labels. Do not use the accepted model output as an independent golden transcript. Report coverage explicitly.
3. Compare first-pass extraction with GLM 5.3 Flash and MiniMax M3.1 Flash Preview, keeping raw outputs, model identity, source/project revision and elapsed time. Evaluate repaired pipelines separately.
4. Add other project adapters after the promised repository links arrive; do not label an absent arm as tested.

Tests: fast unit (<5 s each), focused CLI integration (<30 s), ordinary combined checks <=180 s. Real proof: complete inventory, original-image curation, scorer detects source-grounded wrong cells/labels, saved independent model runs receive deterministic scores. Documents, fixtures and outputs remain private .tmp artifacts.
