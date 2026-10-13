# catalog-to-json
Canonical checkout: this directory; default branch main. Preserve foreign changes.
JSON is the sole canonical output; Markdown is an AnyDoc intermediary only.
Never hand-edit extracted catalog values or accept an unchecked model result.
Use FastAgent native APIs, explicit provider/model selections, fresh extractor/reviewer contexts.
A page is accepted only after a complete original-image review with no unresolved extraction defects.
The output is an engineering catalogue with meaning, not an OCR facsimile. Classify the page and preserve the role of each fact: catalogue product, project specification, software demonstration or supporting context. Do not promote demonstration/UI rows into catalogue offers or let decorative typography dominate product verification. True product IDs, units, conditions, project quantities and drawing ownership remain strict. Classification must be independently reviewed against the source; it is not permission to hide difficult engineering content.
Immediately register discovered failure examples in the owning /home/roomhacker/apps/catalog-extraction-benchmark regression corpus with source/page, exact retained output, actual producer/version and expected behavior. Use its regressions capture command; uncertain glyphs start pending and never become automatic gold. Keep frozen old datasets and scores available separately. Registration/regrading retained evidence requires no model rerun.
Keep drafts, reviews, routing reasons and checkpoints. Never call timeouts or partial output success.
Runtime credentials are supplied by the caller's protected environment/config; none are bundled.
Private inputs, credentials, images, logs and diagnostics belong in ignored .tmp/. The user explicitly authorizes public catalogue JSON snapshots in examples/catalogs/; retain actual producer version, source hashes and review status, remove local runtime paths, and never describe drafts as verified. Small JSON belongs in Git; large JSON belongs on Yandex Disk with a versioned link/manifest.
Tests: fast unit; focused integration; slow nightly. Ordinary combined verification max 180 seconds.
Finite model calls. Single convert defaults: per-call 90 s, job deadline 180 s. Full convert-batch: per-call 1200 s, queue deadline 24 h. With --parallel-stages, one isolated process per provider role can run concurrently; each provider remains sequential and backs off independently. Resume retains verified work and archives earlier reviews before re-audit. Parser plugins are source evidence, never an independently accepted result.
