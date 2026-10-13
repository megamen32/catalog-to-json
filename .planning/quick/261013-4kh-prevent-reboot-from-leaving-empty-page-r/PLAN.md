---
mode: quick
files_modified: [src/catalog_json/tools.py, tests/test_persistence.py, pyproject.toml, plugin.json, .codex-plugin/plugin.json, .claude-plugin/plugin.json]
autonomous: true
---

# Durable catalogue persistence after reboot

The server rebooted at 02:27 Moscow on 2026-10-13. An empty isolators122 review and three NUL journal tails prevented resume. Preserve corrupted receipts and valid prefixes; restart only the owned queue, without changing catalogue values or frozen benchmark inputs.

1. Reproduce the storage failure with a fault-injected fsync failure. Existing writer wrongly replaces the old complete snapshot and acknowledges it.
2. Flush and sync JSON before rename; sync directory entries and journal appends before acknowledging tool evidence. Preserve exact JSON fields and reviewer rules.
3. Run focused fast-unit and native stdioMCP integration checks within 180 seconds; retain results, provenance and limits. Publish source on main, then prepare a separately pinned runtime migration; do not rewrite active/frozen installations.

Acceptance: failed flush cannot grant saved output/inspection; actual page35 save/section/finalize retains every field; queue and three benchmark rounds remain running. Full980-page completion and three fresh benchmark rounds remain pending until real saved results exist.
