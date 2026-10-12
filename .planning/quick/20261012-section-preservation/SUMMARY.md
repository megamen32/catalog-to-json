# Section-preserving page repair — v1.4.6

Confirmed defect: in the immutable v1.4.4 third benchmark round on innovations PDF page78, an initial full save contained two tables/140 cells and eleven text blocks. A subsequent figure-only section edit followed by finalization overwrote the full page with empty tables/text. The published failed final output remains unchanged; no earlier good save is substituted into benchmark results.

Finalization now preserves a provenance-validated complete page and omitted metadata, applying only newer validated section edits. Explicit reads can adopt an earlier attempt from the same source/model/contract; future/unbound candidates, modified sections and superseded full-save bytes are rejected. An explicit fresh reconstruction remains available. Inspected readable grids also reject omission of every table. Source reopening resets evidence state.

Drawing comparisons accept an isolated Cyrillic Ф/ф diameter glyph before a number, with word-boundary and exact numeric guards. Table product identifiers remain literal. Skills require dimension endpoints/feature association and prohibit unsupported material, section-designation and product-variant claims.

Validation categories: fast unit (105 tests, expected20s/max90s; observed11.85s); focused integration (native stdioMCP2 retained original page78 full save→original figure edit→finalize, expected15s/max25s). Both source tables/all140 cells, eleven text blocks and omitted metadata survive; only the figure changes. This diagnostic has zero model/provider calls and is not a new accuracy cohort. Build passed inside the ordinary180s release deadline.

The public benchmark has three frozen rounds per v1.4.2/v1.4.4: 90 attempts/84 actual final JSON, graded with released0.2.4. v1.4.6 requires fresh model runs before any claim of improved accuracy. Full980-page reviewed conversion remains incomplete. The old immutable1.4.1 worker is still active; independent drawing findings on OPN38/39 remain awaiting source-grounded repair.

Independent delta review: PASS, eleven adversarial guards and a second native MCP2 replay of original page78. The reviewer independently confirmed source bytes unchanged and all140 cells/text/metadata retained. Missing current full saves cannot revive earlier candidates. Neither native replay involved model calls or changed historical/live outputs.
