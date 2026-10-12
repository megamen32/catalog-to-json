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
