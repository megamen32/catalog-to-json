# Source delivered; model comparison pending

Native parser descriptions and selection skill now explicitly distinguish inventory/header metadata from canonical body rows and raw merge evidence. Agent instruction requires reading relevant rows after successful parsing and inspecting blanks/merge ownership against source images. Version1.4.2, parser plugin0.2.1.

Independent review found a double-resume provenance defect: a failed new-contract attempt could unlock a prior candidate. Save events now bind producer contract; a new contract must produce its own candidate. Installed artifacts no longer discover a Git revision in an ancestor checkout. Historical candidates and production1.4.1 remain unchanged.

Verification: nativeMCP read of retained page78 Docling evidence returned14 rows/136 cells in2 canonical chunks and raw spans in12 chunks; zero provider/parser calls. This verifies delivery, not quality. Plugin11 tests passed. Core60 tests and build passed in9.74s; independent delta-review identified the fixed double-resume defect. The new explicit source-contract event is exercised through native MCP save/read validation. New15-page quality comparison is pending; do not claim improvement yet.
