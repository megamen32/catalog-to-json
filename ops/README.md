# Managed background catalogue jobs

The operator unit runs one source-bound queue independently of the chat terminal.
It keeps the shared user resource boundary and gives each job a smaller finite
budget:6GiB RAM, zero swap,2 CPU cores,512 tasks and24 hours plus shutdown grace.
It does not restart or silently replay a failed job. SIGINT gives the native CLI its cancellation/cleanup path before the final kill grace. CLI checkpoints stay available. Provider bridges must exec the CLI instead of nesting a subprocess waiter.

Install `catalog-worker@.service` in the user's systemd unit directory. A private
`~/.config/catalog-to-json/jobs/JOB.json` supplies `cwd`, an argv `command`, and
`file_sha256` bindings for the installed program, plugin, source queue and config.
Optional `environment`/`unset_environment` contain nonsecret execution settings.
Keep provider credentials in the existing protected provider bridge/environment;
never commit job descriptors or credentials. Start with
`systemctl --user start catalog-worker@JOB.service` after checking measured capacity.

Use an immutable installed release for each job. Stop only the exact owned prior
invocation, retain its checkpoint, verify it is gone, then resume that same queue.
Changed program contracts must retain separately identified original artifacts; never relabel old
JSON as a new producer. Explicit `--resume-compatible-profile` with pinned
`accepted_predecessor_profiles` may resume the same source-bound queue: validated
historical acceptances keep their actual producers, while changed pending
contracts require fresh numbered extraction/review attempts. Preserve a snapshot
and verify old artifact hashes during this transition. The service does not bypass the CLI's independent review.

Staged jobs default to one worker per role. `--extractor-workers` and
`--reviewer-workers` set finite pool maxima; `--initial-provider-concurrency`
starts each provider below its maximum and raises admission after successful
calls. Every provider has its own gate. A429 reduces future admission and starts
shared backoff; admitted calls finish within their existing deadline. Underlying
provider-SDK retries and FastAgent retries are observed, including recovered429s;
retained receipts contain counts/hashes rather than response bodies. Choose a
job-specific systemd override from measured aggregate memory/CPU/task capacity.
Cancellation releases waiting gates and cleans only owned worker subprocesses.

Each new native worker receipt binds actual program metadata to source, physical
page, role, model, contract, attempt and exact saved bytes. Catalogue records keep
separate `candidate_producer` and `review_producer`. An old save without this
receipt is explicitly `producer_unknown`; `tested_program` names the queue runner.
Source-equivalent seed data is retained as previous-agent feedback. Changed
contracts require a fresh extractor save and independent review, with the old
files retained under their original attempt numbers.

`--role-runtimes private-roles.json` explicitly selects independent pinned
extractor/reviewer runtimes. Both routes declare their actual program metadata,
contract, config, command prefix and file hashes. An external agent interpreter
can run `ops/role-worker.py --adapter /installed/delivery/stage_worker.py`: the
original package owns its AgentPair, tools, prompts and skills; the delivery
adapter adds receipts and rate-limit observation. The parent retains separate
role contracts, validates the exact source/model/page/attempt/artifact receipt,
and caches the combined pair. No route silently falls back to another runtime.
An individually benchmarked extractor does not certify the combined pipeline.

For a delivery-only upgrade, `--resume-compatible-profile` retains an accepted
page only when both native role receipts, physical page, source, saved hashes,
models/contracts and current audit still match. It also restores provider limits
and remaining cooldown from the same source/model/contract checkpoint, without
restoring cancelled active calls or exceeding the new job budget.

During a staged run, a new, changed or removed source-bound external audit reopens
the affected accepted page for fresh independent review. The exact extractor
artifact remains available, and the previous review is archived. A new pass must
consume the current audit within its verified native review receipt. Independent
audit leads require source verification; they are not prepared replacement data.

`--provider-holds private-holds.json` applies explicit account-quota deadlines to
future admissions only. The JSON object has `schema_version:"1.0"` and
`providers`, keyed by the native provider name. Each entry binds the exact model
specification to `not_before_unix` (a finite UTC Unix timestamp within24 hours).
Example: `{"schema_version":"1.0","providers":{"anthropic":{"model":"anthropic.MiniMax-M3.1-Flash-Preview?reasoning=medium","not_before_unix":1791817200}}}`.
Use a freshly verified official usage result; never infer quota exhaustion from
a generic429 alone. The file is private mutable operator state, not a skill or
agent input. Changes are hashed in job metadata and reloaded during the run.
Removing an entry releases only its operator hold; SDK backoff still applies.
Already admitted calls finish normally, the other provider keeps running, and
queue waiting remains outside each native call timeout. The whole job deadline
continues to include waiting. No provider/model fallback is introduced.

Provider admissions follow FIFO order so workers finishing quickly cannot
repeatedly overtake an older waiting review. `waiting_calls` reports queued
admissions; `active_calls` reports actual native work. A page is marked
`awaiting_provider_admission` until its gate grants a slot, then `extracting` or
`reviewing`. Cancelling a waiting page removes only its own admission ticket.

A compatible delivery-only resume also retains a completed revise report when
both native role receipts, saved hashes, source/page/model/contracts and the
current external audit match exactly. It continues extractor repair at the next
attempt instead of paying for a duplicate review of the same candidate. Changed
or newly supplied audit leads still require a fresh reviewer. This reuse never
turns an unresolved report into acceptance.

Retry diagnostics retain lifetime signal and wave counts. The exponential delay
uses a separate consecutive `backoff_streak`, reset after four native completions
with no intervening provider429. Successful SDK retries do not count as clean
recovery. Existing cooldown and in-flight calls are preserved on resume; legacy
checkpoints conservatively retain their former streak until clean recovery.

An experimental extractor composition is explicit: `ops/role-worker.py` accepts
`--catalog-runtime private-component.json`. The descriptor binds the actual
legacy agent program and skill root, fixed tool interpreter/program/schema, and
file hashes. Only the worker-generated catalog MCP command changes; the original
agent logic, native skill text, parser configuration and frozen inputs remain
intact. The receipt records both components and a new combined producer/contract.
This route has its own benchmark identity and inherits no older accuracy score.
The unchanged measured route remains available without this option.

Reviewer1.4.16 adds explicit literal branding quotation evidence: a freshly viewed source box, the visible quote in its original language, and separately retained text-layer agreement/unavailability/conflict. Hidden or missing native text does not substitute for image evidence. This is a new reviewer contract and an experimental quality change; immutable142/148 production roles and existing benchmark cohorts are unchanged.

Reviewer1.4.17 binds nontechnical branding figure captions to their freshly inspected source box and explicit source kind. Only an identical complete candidate branding block can satisfy that caption across representation; default figure checks, engineering values/operators/diameters/view labels and ordinary prose remain strict. It is a new unbenchmarked reviewer contract; existing immutable roles remain separate.

Delivery scheduler1.4.18 reviews catalogues in the manifest order and places repaired candidates and changed source audits ahead of remaining first-pass drafts in that catalogue. Priority is selected again after provider admission waiting; queued jobs are retained and already admitted native calls finish. Accepted compatibility, exact per-role producer profiles, quota holds, cooldowns and strict review remain unchanged. This is an execution-order change, not a newly measured extraction/review accuracy claim.

Delivery scheduler1.4.19 accepts an optional `rejected_candidate_sha256` list in a source-bound `external-audit.json`. A nonempty list requires exact source SHA/page, valid SHA-256 values and independent findings. Only these explicitly audited bytes are rejected even if the model report says pass; that native report remains unchanged. The parent records its own rejection and requests a source-bound native repair, including on cache/resume or a late audit. Different bytes still require the normal strict review. The scheduler changes neither native role profile nor prior accuracy measurements.

### Guarded extraction delivery1.4.20

The full job may explicitly pin composition15 (unchanged1.4.2 agent logic and skill;1.4.8 native tools) with the unchanged1.4.8 reviewer. Section finalization preserves the saved full page: the exact retained page38 diagnostic keeps72 cells and17 text blocks after a figure edit. This is a new producer/profile, not an inherited historical accuracy score. The separate corrected benchmark uses reviewer17 and has separate fresh outputs.

An optional `accepted_predecessor_profiles` list in the role manifest can retain already accepted native pairs under their actual old producers. Both pinned programs, source/page/model/contracts, latest save events, artifact hashes, unchanged consumed audit leads and passing review must verify. Old bytes are never relabelled as new extraction. Superseded attempts/contracts and source-vetoed bytes cannot be reused; new extraction always uses the primary profile. Provider pacing may be retained only for the explicit same-model predecessor profile and identical catalogue sources.

Reviewer1.4.21 compares explicit physical SI spelling aliases (for example A/А and mA/мА) and an exact condition retained in label/group/qualifier without rewriting source or candidate. Unit case/prefixes, compound operators, physical column scope, every condition and numeric decimal boundary remain strict. Product identities, names, standards, owners and drawing labels retain their previous comparison rules. This is a separate unbenchmarked reviewer contract; the live composition15→reviewer148 job and frozen15→17 benchmark remain unchanged.

Composition1.4.22 is an explicit experimental extractor route: unchanged initial1.4.2 instructions/skills through the pinned1.4.3 agent, plus fixed1.4.8 native tools. The only agent delta is continuation after END_TURN/MAX_TOKENS when no fresh source-bound tool deliverable exists, with the existing absolute deadline and cancellation handling. It has a new producer/contract and does not inherit earlier accuracy. Descriptor22 requires the actual1.4.3 agent program; immutable composition15 and existing live/benchmark profiles are preserved. This does not promise to rescue a model that spends its entire deadline inspecting images without saving.

Reviewer1.4.23 corrects a condition-comparison regression in experimental21: a leaf label repeating its exact parent header no longer adds that condition twice. Removal requires a token boundary; changed leaf currents, units, decimal values, operators, missing or extra parent conditions still block review. Retained OPN17/26 source checks demonstrate the formatting equivalence, while OPN35's real147,5→14,75 error remains blocked. Native artifacts are unchanged, unprinted material findings still require source-bound repair, and this is not a new benchmark score or a live profile switch. The portable and Claude plugin manifests now both declare the same package release version; earlier assets remain historical.

Packaging1.4.24 also aligns the Codex plugin manifest with the portable/Claude manifests and the Python package. Version23 source remains historical; its Codex manifest still declared20. Executed Python logic and skills are byte-identical to23, and live/frozen role profiles remain unchanged. Release checks now cover all three manifests.

### Semantic1.5.3 transition

Native small4 MiniMax M3.1 Flash Preview → blind GLM5.3 Flash CodingEndpoint
passed after one repair; see `examples/semantic-review/v1.5.3`. Full reviewer
instructions fit the native16k envelope, helper schemas are usable from the initial
generation, and real/mixed drawing ownership gates remain strict. This is not
a new global accuracy estimate. The shared queue retains historical accepted
producers; it does not relabel them as freshly checked by1.5.3.

The replacement full job reuses the reviewed12GiB MemoryHigh/16GiB MemoryMax,
zero swap,400% CPU,2048 tasks,IOWeight50 and24h budget. Fresh measured capacity
was36GiB available RAM/208GiB free disk; no GPU and no parallel second full job.
Provider pools remain capped at8 per role and back off on429; actual admission
is recorded in the live queue.

Operational storage allocation for this continuation:96GiB total under
`.tmp/full-digitization` (measured31GiB at handoff), leaving at least64GiB
host free-space reserve. Keep source/accepted checkpoints; do not duplicate the
full job or delete live results to reclaim this allocation. CPU/RAM/task/runtime
limits are enforced by the existing unit; storage is the project operating
budget to check on each continuation.

### Delivery1.5.4: fresh repairs and document annotations

Fresh extractor repairs now use lane2 (as fresh reviewer work already did), rather than joining historical migration repairs. Failed fresh calls retain that lane; unchanged old backlog and first passes still receive fair admissions. Native source/candidate dates, document numbers and addresses on independently confirmed supporting pages need no fictional dimension arrows: a new explicit supporting_annotations_verified reviewer flag plus matching pure supporting/literal contexts, no tables, and all five semantic checks are required. Bare numbers, geometry signs, tolerances and length units remain guarded; real/mixed drawings cannot use this exception. All factual/literal/source checks remain.

An explicit candidate_predecessor_profiles role manifest may retain only receipt-verified old extraction from the same source/page/model and pinned actual producer. It requires fresh current review and records the old extractor contract, never relabels bytes. Accepted predecessor pairs (including an explicitly pinned old-extractor/new-reviewer pair) preserve actual producer identities on resume. No automatic model/provider fallback. The same reviewed full-job budget above applies; no second full queue or new large model benchmark.

### Half-hour owner review

Owner requested recurring review every30minutes on14October2026: all five catalogue progress,2–3 fresh native transcripts and original-page checks, focused repairs, optional published version transition, no large paid benchmark. `catalog-review-watch.timer` uses00/30 Europe/Moscow and the existing local Herder native transport; it wakes only the exact idle owner specified by private `~/.config/catalog-to-json/review-watch.env` (`CATALOG_REVIEW_THREAD_ID`). It creates no new chat. Active work, human stop, permission waits, stopped/archived/unknown sessions are left alone. An unknown delivery is retained and never replayed; native receipt and a stable30-minute input ID bind admitted work. User requested this recurring continuation explicitly; no unrelated sessions are contacted.

The producer itself uses no LLM. Fresh probe measured0.23s and17.1MiB peak RSS. On this host35GiB available RAM and221GiB free disk were observed alongside the existing bounded full job. Producer budget:128/256MiB soft/hard,zero swap,oneCPU,32tasks,45s wall,16MiB single-file cap,IOWeight10. State is bounded last.json plus lock under ignored `.tmp/catalog-review-watch/`; reviewed catalogue data/transcripts stay in the existing queue. The resumed owner uses its existing harness budget and the same full-job budget; no new unbounded daemon or second queue.

The prompt records private compact observations, stays quiet during normal progress, and uses NoticePlace for actual automatic incidents. It may release/promote a source-verified fix without a new large benchmark. Stop this timer after all980 reviewed pages and JSON/Excel are actually delivered, or on explicit human cancellation.

### Review delivery1.5.5

Blocking candidate uncertainty, issues, counts or independent-source differences are returned before expensive PASS geometry requests. A revise/uncertain artifact is only a repair checkpoint; it never accepts the page, so it need not collect the final per-dimension certificate first. PASS retains all source/candidate and drawing gates. `record_dimension_reviews` also accepts `{shared:{common fields},records:[{overrides}]}` and expands it through the same individual validator/history; no field or evidence check is waived. Resume prioritizes source-audit-bearing pages as fresh repairs. Full154 certificate47 timeout and arm86 six-vs-four rollers are retained regressions; no new global accuracy percentage.
