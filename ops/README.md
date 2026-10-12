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
Changed program contracts require a separately labelled output; never relabel old
JSON as a new producer. The service does not bypass the CLI's independent review.

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
