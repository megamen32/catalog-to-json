# Catalog to JSON

PDF product catalogs become versioned, schema-valid JSON. AnyDoc handles direct text extraction; difficult/rotated/scanned/diagram pages go to FastAgent Vision. A separate strict reviewer compares against the original; bounded automatic repair handles defects. Only JSON is canonical. Excel/HTML are deterministic exports.

Owner approved a new public repository on 2026-10-11. Current model is GLM 5.3 Flash for both roles with independent histories; MiniMax is the preferred second model when quota permits. No manual catalog-value corrections.

Inputs and model results remain private ignored artifacts. First live acceptance uses the provided catalog's page 78, containing rotated headers, merged data cells, two tables and labeled diagrams.

Initial version is a PDF CLI, not a hosted app. Different catalogs use a generic table/text/figure schema; no hardcoded page-78 product data.
