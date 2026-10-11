# catalog-to-json
Canonical checkout: this directory; default branch main. Preserve foreign changes.
JSON is the sole canonical output; Markdown is an AnyDoc intermediary only.
Never hand-edit extracted catalog values or accept an unchecked model result.
Use FastAgent native APIs, explicit provider/model selections, fresh extractor/reviewer contexts.
A page is accepted only after a complete original-image review with no unresolved extraction defects.
Keep drafts, reviews, routing reasons and checkpoints. Never call timeouts or partial output success.
Runtime credentials are supplied by the caller's protected environment/config; none are bundled.
Private/user PDFs, images, output, and diagnostic scripts belong in ignored .tmp/, never in Git.
Tests: fast unit; focused integration; slow nightly. Ordinary combined verification max 180 seconds.
Finite sequential model calls; default per-call 90 s, job deadline 180 s. Resume retains verified work.
