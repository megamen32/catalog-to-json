"""Apply an explicit, source-reviewed revision without rewriting its history.

The input catalogue stays immutable. Every former unresolved fact is accounted
for, and every changed or removed record is retained in a separate ledger.
This command performs no extraction, inference, or automatic normalization.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path

from .canonical_merge import js, file_sha

VERSION = "1.1.0"
CORE = {"id", "catalog", "page", "kind", "model", "parameter", "part",
        "condition", "value", "unit", "state", "source_fact_ids", "producer_ref"}


def digest(value):
    return hashlib.sha256(js(value).encode()).hexdigest()


def validate_closures(original, decisions):
    """Require an exact partition, including rejected observations and notes."""
    old = {x["fact"]["fact_id"]: x for x in original}
    if len(old) != len(original):
        raise ValueError("Duplicate original unresolved fact")
    ids = [d["fact_id"] for d in decisions]
    if len(set(ids)) != len(ids) or set(ids) != set(old):
        raise ValueError("Closures must account for every original fact exactly once")
    for d in decisions:
        if d.get("disposition") not in {"closed", "retained"}:
            raise ValueError("Unknown closure disposition")
        if d.get("before_sha256") != digest(old[d["fact_id"]]):
            raise ValueError("Original unresolved fact changed")
        if not d.get("reason") or not d.get("evidence"):
            raise ValueError("Source review and reason required")
    closed = {d["fact_id"] for d in decisions if d["disposition"] == "closed"}
    return [x for x in original if x["fact"]["fact_id"] not in closed]


def revise(doc, pack, *, input_sha256, builder):
    if pack.get("schema") != "canonical-source-review/1":
        raise ValueError("Expected a source-review pack")
    if pack.get("input_sha256") != input_sha256:
        raise ValueError("Review belongs to another input catalogue")
    if not pack.get("reviewers") or not pack.get("review_scope"):
        raise ValueError("Actual reviewer identities and scope required")
    sources = {s["id"]: s for s in doc["sources"]}

    def evidence(entries, catalog, page):
        if not entries:
            raise ValueError("Missing source evidence")
        if not any(e.get("catalog") == catalog and e.get("page") == page
                   and e.get("source_sha256") == sources[catalog]["sha256"]
                   and isinstance(e.get("region"), list) and len(e["region"]) == 4
                   for e in entries):
            raise ValueError("Source evidence does not cover the affected page")

    out = copy.deepcopy(doc)
    out["unresolved"] = validate_closures(doc["unresolved"], pack["closures"])
    original_unresolved = {x["fact"]["fact_id"]: x for x in doc["unresolved"]}
    for d in pack["closures"]:
        u = original_unresolved[d["fact_id"]]
        evidence(d["evidence"], u["catalog"], u["physical_page"])

    records = {r["id"]: r for r in out["records"]}
    if len(records) != len(out["records"]):
        raise ValueError("Duplicate input record")
    changed, seen = [], set()
    for action in pack["actions"]:
        ident = action["id"]
        if ident in seen:
            raise ValueError("Record changed more than once")
        seen.add(ident)
        before = records.get(ident)
        op = action["op"]
        if op not in {"add", "replace", "remove"}:
            raise ValueError("Unknown record operation")
        if op == "add":
            if before is not None or action.get("before_sha256") is not None:
                raise ValueError("Addition would overwrite an existing record")
        elif before is None or digest(before) != action.get("before_sha256"):
            raise ValueError("Before record mismatch")
        after = copy.deepcopy(action.get("record")) if op != "remove" else None
        affected = before or after
        evidence(action.get("evidence"), affected["catalog"], affected["page"])
        if not action.get("reason"):
            raise ValueError("Record review reason required")
        if after is not None:
            if set(after) != CORE or after["id"] != ident:
                raise ValueError("Invalid canonical record contract")
            if before and any(after[k] != before[k] for k in ("catalog", "page")):
                raise ValueError("Cannot move a source observation to another page")
            if not after["source_fact_ids"]:
                raise ValueError("Source observation identity required")
            if after["producer_ref"] not in out["producers"]:
                producer = pack.get("producers", {}).get(after["producer_ref"])
                if not producer:
                    raise ValueError("Missing actual review producer")
                out["producers"][after["producer_ref"]] = producer
            records[ident] = after
        else:
            del records[ident]
        changed.append({"op": op, "before": before, "after": after,
                        "reason": action["reason"], "evidence": action["evidence"]})

    # A closure referring to a replacement must point to a real final record.
    for d in pack["closures"]:
        for ident in d.get("record_ids", []):
            if ident not in records:
                raise ValueError("Closure references an absent final record")
    out["records"] = sorted(records.values(), key=lambda r: r["id"])
    metadata_changes = []
    for change in pack.get("metadata_changes", []):
        key = change["key"]
        if key != "new_audit_issues":
            raise ValueError("Cannot rewrite historical producer/input metadata")
        before = out["metadata"].get(key)
        if digest(before) != change.get("before_sha256") or not change.get("reason"):
            raise ValueError("Metadata before/reason mismatch")
        out["metadata"][key] = copy.deepcopy(change["value"])
        metadata_changes.append({"key": key, "before": before,
                                 "after": change["value"], "reason": change["reason"]})
    ledger = {"schema": "canonical-source-review-ledger/1",
              "input_sha256": input_sha256, "review_pack_sha256": digest(pack),
              "original_unresolved": copy.deepcopy(doc["unresolved"]),
              "closures": copy.deepcopy(pack["closures"]),
              "record_changes": changed, "metadata_changes": metadata_changes,
              "output_records_sha256": digest(out["records"]),
              "output_record_count": len(out["records"]),
              "reviewers": pack["reviewers"],
              "review_scope": pack["review_scope"], "builder": builder}
    out["metadata"]["source_review"] = {
        "input_sha256": input_sha256, "ledger_content_sha256": digest(ledger),
        "review_pack_sha256": digest(pack), "builder": builder,
        "original_unresolved_count": len(doc["unresolved"]),
        "closed_count": sum(d["disposition"] == "closed" for d in pack["closures"]),
        "retained_count": len(out["unresolved"]),
        "record_changes": len(changed), "reviewers": pack["reviewers"],
        "scope": pack["review_scope"],
    }
    return out, ledger


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--review", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ledger", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.ledger.exists():
        raise FileExistsError("Refusing to overwrite a revision or its history")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    builder = {"name": "canonical-source-review", "version": VERSION,
               "git_revision": revision, "source_sha256": file_sha(__file__)}
    doc, ledger = revise(json.loads(args.input.read_text()), json.loads(args.review.read_text()),
                         input_sha256=file_sha(args.input), builder=builder)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    args.ledger.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
    args.output.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"records": len(doc["records"]), "unresolved": len(doc["unresolved"]),
                      "changes": len(ledger["record_changes"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
