# Refuse schema probes as extraction deliverables

Native isolators47 attempt30 saved only `title=probe` and one `heading=probe`, losing the page's actual content at the extraction completion boundary. The page was not independently accepted. Version1.5.20 refuses empty/heading-only saves without inspected page context, preserves any previous candidate and directs schema experiments to `get_json_schema`. Purposeful blank/title-only source pages can still provide explicit inspected context; historical JSON remains readable.

135 focused checks passed in27.37s (expected30s, emergency300s). Native stdio MCP replay on the exact retained artifact:1.5.19 saved it in2.108s;1.5.20 refused it in3.314s. Both replays made zero model calls and changed no production candidate bytes. Individual receipt files retain actual producer/source/artifact identities.

This directory proves the narrow tool fix, not a new extraction accuracy score. At source publication the full queue still runs immutable1.5.19 with config revision19-r2. No runtime is relabelled1.5.20. Promotion needs an explicit pinned transition and a real production receipt; it is pending while current reviews continue.
