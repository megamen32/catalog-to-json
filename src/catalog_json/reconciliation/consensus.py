"""Source-bound votes and unanimity; this module never calls a model."""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_ROLES = ("codex", "zcode", "glm", "minimax")
PROVIDER_MODELS = {"glm": "zai.glm-5.3-flash?reasoning=low",
                   "minimax": "anthropic.MiniMax-M3.1-Flash-Preview?reasoning=medium"}
DECISIONS = {"ours", "oleg", "equivalent", "both", "neither", "unresolved"}


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def case_sha256(case: dict) -> str:
    return hashlib.sha256(canonical_json(case)).hexdigest()


def _digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Expected a lowercase SHA256")


def validate_pack(pack: dict) -> dict:
    if not isinstance(pack, dict) or not pack.get("schema_version") or not isinstance(pack.get("pack_id"), str) or not pack["pack_id"]:
        raise ValueError("Pack needs schema_version and pack_id")
    if not isinstance(pack.get("cases"), list) or not pack["cases"]:
        raise ValueError("Pack must contain cases")
    ids = set()
    for case in pack["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"] or case["case_id"] in ids:
            raise ValueError("Missing or duplicate case_id")
        ids.add(case["case_id"])
        _digest(case.get("source_sha256"))
        pages = case.get("physical_pages")
        if not isinstance(pages, list) or not pages or any(type(p) is not int or p < 1 for p in pages) or len(set(pages)) != len(pages):
            raise ValueError("physical_pages must be distinct positive integers")
        if not isinstance(case.get("kind"), str) or not case["kind"] or any(not isinstance(case.get(side), list) for side in ("ours", "oleg")):
            raise ValueError("Case needs kind and both atom lists")
    canonical_json(pack)
    return pack


def load_sources(path: Path | str) -> dict:
    """Hash every whitelisted PDF without loading the entire file into RAM."""
    import pymupdf
    path = Path(path).resolve()
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("--sources must contain a list of {sha256,path}")
    sources = {}
    for item in entries:
        _digest(item.get("sha256"))
        source = Path(item["path"])
        source = (path.parent / source).resolve() if not source.is_absolute() else source.resolve()
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"] or digest in sources:
            raise ValueError("Source hash mismatch or duplicate source")
        with pymupdf.open(source) as doc:
            if not doc.is_pdf or doc.needs_pass:
                raise ValueError("Source must be an accessible PDF")
            sources[digest] = {"sha256": digest, "path": str(source), "page_count": len(doc)}
    return sources


def validate_identity(identity: dict) -> dict:
    if not isinstance(identity, dict) or identity.get("role") not in REQUIRED_ROLES:
        raise ValueError("Unknown actual voter role")
    for key in ("session_id", "model", "runtime"):
        if not isinstance(identity.get(key), str) or not identity[key].strip():
            raise ValueError(f"Actual identity needs {key}")
    if identity["role"] in PROVIDER_MODELS and identity["model"] != PROVIDER_MODELS[identity["role"]]:
        raise ValueError("Unauthorized provider/model identity")
    canonical_json(identity)
    return identity


def _validate_payload(pack, payload, sources):
    validate_pack(pack)
    if not isinstance(payload, dict) or set(payload) != {"pack_id", "verdicts"} or payload["pack_id"] != pack["pack_id"]:
        raise ValueError("Vote payload contains only matching pack_id and verdicts; identity is caller-owned")
    verdicts = payload["verdicts"]
    cases = {c["case_id"]: c for c in pack["cases"]}
    if not isinstance(verdicts, list) or len(verdicts) != len(cases):
        raise ValueError("Partial batch cannot be saved")
    seen = set()
    for verdict in verdicts:
        if not isinstance(verdict, dict) or set(verdict) - {"case_id", "case_sha256", "decision", "selected_value", "reason", "source_evidence"}:
            raise ValueError("Unknown verdict fields")
        case_id = verdict.get("case_id")
        if case_id not in cases or case_id in seen:
            raise ValueError("Unknown or duplicate case_id")
        seen.add(case_id)
        case = cases[case_id]
        if verdict.get("case_sha256") != case_sha256(case):
            raise ValueError("Case SHA does not match exact input")
        if verdict.get("decision") not in DECISIONS or not isinstance(verdict.get("reason"), str) or not verdict["reason"].strip():
            raise ValueError("Decision and source-grounded reason required")
        evidence = verdict.get("source_evidence")
        if not isinstance(evidence, list):
            raise ValueError("source_evidence must be a list")
        if case["kind"] not in {"format", "representation", "provenance"} and verdict["decision"] != "unresolved" and not evidence:
            raise ValueError("Technical adjudication requires source evidence")
        if case["source_sha256"] not in sources:
            raise ValueError("Case source is not whitelisted")
        if any(page > sources[case["source_sha256"]]["page_count"] for page in case["physical_pages"]):
            raise ValueError("Case page is outside source")
        for ev in evidence:
            if not isinstance(ev, dict) or set(ev) - {"source_sha256", "page", "bbox", "observation"}:
                raise ValueError("Invalid source evidence fields")
            # Additional PDFs cannot silently replace this case's declared source.
            if ev.get("source_sha256") != case["source_sha256"] or ev.get("page") not in case["physical_pages"] or type(ev.get("page")) is not int:
                raise ValueError("Evidence source/page is outside this case")
            if not isinstance(ev.get("observation"), str) or not ev["observation"].strip():
                raise ValueError("Evidence observation required")
            if "bbox" in ev:
                b = ev["bbox"]
                if not isinstance(b, list) or len(b) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in b) or not (0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1):
                    raise ValueError("bbox must be a positive normalized rectangle")
    canonical_json(payload)


def validate_vote(pack: dict, payload: dict, *, identity: dict, sources: dict) -> dict:
    """Only trusted runtime/CLI supplies identity; never read identity from model data."""
    validate_identity(identity)
    _validate_payload(pack, payload, sources)
    envelope = {"schema_version": "catalogue-consensus-vote/1", "pack_id": pack["pack_id"],
                "pack_sha256": case_sha256(pack), "identity": dict(identity), "payload": payload,
                "source_manifest": [{"sha256": k, "page_count": v["page_count"]} for k, v in sorted(sources.items())],
                "saved_at": datetime.now(timezone.utc).isoformat()}
    envelope["receipt_sha256"] = case_sha256(envelope)
    return envelope


def receipt_path(pack, output_dir, round_number, role):
    if type(round_number) is not int or round_number < 1 or role not in REQUIRED_ROLES:
        raise ValueError("Invalid round or role")
    return Path(output_dir) / case_sha256(pack) / f"round{round_number}" / "receipts" / f"{role}.json"


def write_exclusive(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL prevents overwriting another voice, round, or an UNKNOWN attempt.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    return path


def save_vote(pack, payload, *, identity, sources, output_dir, round_number=1) -> Path:
    envelope = validate_vote(pack, payload, identity=identity, sources=sources)
    envelope["round_number"] = round_number
    envelope.pop("receipt_sha256")
    envelope["receipt_sha256"] = case_sha256(envelope)
    return write_exclusive(receipt_path(pack, output_dir, round_number, identity["role"]), envelope)


def build_consensus(pack: dict, votes: list[dict]) -> dict:
    validate_pack(pack)
    roles = {}
    sessions = set()
    rounds = set()
    for vote in votes:
        if vote.get("schema_version") != "catalogue-consensus-vote/1":
            raise ValueError("A validated vote envelope is required")
        unsigned = {k: v for k, v in vote.items() if k != "receipt_sha256"}
        if vote.get("receipt_sha256") != case_sha256(unsigned) or vote.get("pack_sha256") != case_sha256(pack):
            raise ValueError("Vote receipt or pack SHA mismatch")
        identity = validate_identity(vote["identity"])
        role = identity["role"]
        if role in roles or identity["session_id"] in sessions:
            raise ValueError("Repeated role/session is not independent consensus")
        sessions.add(identity["session_id"])
        rounds.add(vote.get("round_number", 1))
        sources = {v["sha256"]: v for v in vote["source_manifest"]}
        _validate_payload(pack, vote["payload"], sources)
        roles[role] = vote
    if len(rounds) > 1:
        raise ValueError("Do not combine different deliberation rounds")
    missing = sorted(set(REQUIRED_ROLES) - set(roles))
    results = []
    for case in pack["cases"]:
        opinions = {role: next(v for v in vote["payload"]["verdicts"] if v["case_id"] == case["case_id"]) for role, vote in roles.items()}
        signatures = {canonical_json({k: v for k, v in opinion.items() if k in {"decision", "selected_value"}}) for opinion in opinions.values()}
        agreed = not missing and len(signatures) == 1 and all(v["decision"] != "unresolved" for v in opinions.values())
        result = {"case_id": case["case_id"], "case_sha256": case_sha256(case), "consensus": agreed,
                  "decision": next(iter(opinions.values()))["decision"] if agreed else "unresolved",
                  "missing_roles": missing, "votes": {role: vote["receipt_sha256"] for role, vote in roles.items()}}
        if agreed:
            opinion = next(iter(opinions.values()))
            if "selected_value" in opinion:
                result["selected_value"] = opinion["selected_value"]
            elif opinion["decision"] in {"ours", "equivalent"}:
                result["selected_value"] = case["ours"]
            elif opinion["decision"] == "oleg":
                result["selected_value"] = case["oleg"]
            elif opinion["decision"] == "both":
                result["selected_value"] = {"ours": case["ours"], "oleg": case["oleg"]}
            else:
                result["consensus"] = False; result["decision"] = "unresolved"
                result["reason"] = "Neither input is correct but no common replacement was supplied"
        else:
            result["reason"] = "Missing independent voices" if missing else "Disagreement or unreadable source"
        results.append(result)
    return {"schema_version": "catalogue-consensus/1", "pack_id": pack["pack_id"], "pack_sha256": case_sha256(pack),
            "required_roles": list(REQUIRED_ROLES), "complete": not missing,
            "all_resolved": all(c["consensus"] for c in results), "cases": results}
