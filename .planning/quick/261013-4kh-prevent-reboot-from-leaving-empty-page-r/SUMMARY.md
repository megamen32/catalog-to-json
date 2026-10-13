# Durable catalogue persistence, source delivery

Confirmed reboot failure: one empty review and three NUL journal tails. Original corrupt artifacts are retained under ignored root-audit/reboot-20261013; only validated journal tails were removed, and no catalogue value was edited. Native full queue resumed; benchmark owner separately checkpoint-restored the original15→17 three-round cohort.

Version1.4.25 flushes/syncs JSON before atomic replace, directories after creation/replace and journals before tool evidence acknowledgment. Both audit content and its read receipt now use the same byte snapshot. Source review cannot become accepted while the latest external lead remains unread. A local immediate completion yields to the event loop, so deadlines remain effective. Unchanged whole-catalogue snapshots are not rewritten.

Fault-injected storage flush and atomic audit-replacement tests reproduced the original failures.151 focused unit/integration checks passed in21.91s;11 explicit role-composition checks in0.23s. Queue timing fixtures exclude physical fsync latency; dedicated persistence/native transport checks use real disk I/O. Retained original OPN35 native MCP save→figure section→finalize preserved all fields:64 table cells and12 text blocks,2.31s, no provider calls. Independent source/code review findings are resolved.

Actual reviewed OPN35candidate6 corrects147,5 but misassignsØ500 to ribs. Two agents inspected the original ring extension lines; an exact candidate-byte veto was added to the existing source lead. Native review6 independently returnedREVISE; the page is not accepted. Values remain model-produced.

Source delivery does not finish the980-page catalogue or the three benchmark rounds. Installed runtime migration and fresh native review canary are separate pending consumer gates. Frozen benchmark profiles and old producer/version receipts are preserved.
