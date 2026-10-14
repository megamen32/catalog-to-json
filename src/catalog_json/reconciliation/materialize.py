"""Materialize a unanimously chosen input side through explicit caller-owned bindings.

This creates a compatibility proof, never new votes or a replacement strict consensus.
Pointers in bindings refer to selected_value and the immutable pack respectively.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from .consensus import REQUIRED_ROLES, build_consensus, canonical_json, case_sha256, write_exclusive


def _tokens(pointer):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("Expected an RFC6901 JSON pointer")
    if not pointer:
        return ()
    pieces = pointer[1:].split("/")
    if any(re.search(r"~(?![01])", piece) for piece in pieces):
        raise ValueError("Invalid JSON pointer escape")
    return tuple(piece.replace("~1", "/").replace("~0", "~") for piece in pieces)


def _resolve(value, tokens):
    for token in tokens:
        if type(value) is dict and token in value:
            value = value[token]
        elif type(value) is list and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ValueError("JSON pointer does not resolve exactly")
    return value


def _leaves(value, path=()):
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("JSON object keys must be strings")
        if value:
            return {p: leaf for key, item in value.items() for p, leaf in _leaves(item, path + (key,)).items()}
    elif type(value) is list and value:
        return {p: leaf for i, item in enumerate(value) for p, leaf in _leaves(item, path + (str(i),)).items()}
    elif type(value) not in (dict, list, str, int, float, bool, type(None)):
        raise ValueError("Only JSON values can be materialized")
    # Empty containers are leaves too: they must not evade coverage.
    return {path: value}


def _keys(value, path=()):
    """Object keys can carry technical facts, e.g. wire sections in a row map."""
    if type(value) is dict:
        result = {path + (key,): key for key in value}
        for key, item in value.items():
            result.update(_keys(item, path + (key,)))
        return result
    if type(value) is list:
        return {p: key for i, item in enumerate(value) for p, key in _keys(item, path + (str(i),)).items()}
    return {}


def _resolve_key(value, tokens):
    parent = _resolve(value, tokens[:-1]) if tokens else None
    if type(parent) is not dict or tokens[-1] not in parent:
        raise ValueError("Key binding must identify an existing JSON object member")
    return tokens[-1]


def _same(left, right):
    _leaves(left)
    _leaves(right)
    return type(left) is type(right) and canonical_json(left) == canonical_json(right)


def _fields(value, expected, description):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f"{description} requires exactly {sorted(expected)}")


def materialize_side(pack: dict, votes: list[dict], bindings: dict) -> dict:
    """Refuse unless all four validated votes choose the same side for every case.

    Nonidentical selected_value requires exhaustive value-leaf AND object-key
    bindings into that case's chosen side. A binding has role, selected_pointer,
    pack_pointer and optional selected_kind/pack_kind (value by default, or key).
    Binding documents must be supplied by the trusted
    caller, never generated implicitly from a model's value or inferred by search.
    """
    strict = build_consensus(pack, votes)  # Validate every original receipt first.
    if not strict["complete"] or len(votes) != len(REQUIRED_ROLES):
        raise ValueError("All four independent receipts are required")
    round_numbers = [vote.get("round_number", 1) for vote in votes]
    if any(type(n) is not int or n < 1 for n in round_numbers):
        raise ValueError("A positive integer deliberation round is required")
    rounds = set(round_numbers)
    _fields(bindings, {"schema_version", "pack_sha256", "cases"}, "Binding document")
    if bindings["schema_version"] != "catalogue-side-bindings/1" or bindings["pack_sha256"] != case_sha256(pack):
        raise ValueError("Binding schema or immutable pack SHA mismatch")
    if type(bindings["cases"]) is not list:
        raise ValueError("Binding cases must be a complete list")
    by_case = {}
    for entry in bindings["cases"]:
        _fields(entry, {"case_id", "case_sha256", "side", "bindings"}, "Case binding")
        case_id = entry["case_id"]
        if type(case_id) is not str or case_id in by_case:
            raise ValueError("Unknown or duplicate binding case")
        by_case[case_id] = entry
    if set(by_case) != {case["case_id"] for case in pack["cases"]}:
        raise ValueError("Bindings must cover exactly all pack cases")
    roles = {vote["identity"]["role"]: vote for vote in votes}
    results = []
    for i, case in enumerate(pack["cases"]):
        entry = by_case[case["case_id"]]
        opinions = {role: next(v for v in vote["payload"]["verdicts"] if v["case_id"] == case["case_id"])
                    for role, vote in roles.items()}
        sides = {opinion["decision"] for opinion in opinions.values()}
        if len(sides) != 1 or not sides <= {"ours", "oleg"}:
            raise ValueError("Every voice must choose the same input side; unresolved/conflict refused")
        side = next(iter(sides))
        if entry["case_sha256"] != case_sha256(case) or entry["side"] != side:
            raise ValueError("Binding case SHA or chosen side mismatch")
        if type(entry["bindings"]) is not list:
            raise ValueError("Leaf bindings must be a list")
        maps = {role: {} for role in REQUIRED_ROLES}
        prefix = ("cases", str(i), side)
        for item in entry["bindings"]:
            required = {"role", "selected_pointer", "pack_pointer"}
            if type(item) is not dict or not required <= set(item) or set(item) - required - {"selected_kind", "pack_kind"}:
                raise ValueError("Binding requires role, selected_pointer, pack_pointer; only optional selected_kind/pack_kind")
            role = item["role"]
            if type(role) is not str or role not in maps:
                raise ValueError("Unknown binding voter")
            selected = _tokens(item["selected_pointer"])
            target = _tokens(item["pack_pointer"])
            if target[:3] != prefix:
                raise ValueError("Binding target must remain inside this case's chosen side")
            selected_kind, pack_kind = item.get("selected_kind", "value"), item.get("pack_kind", "value")
            if selected_kind not in ("value", "key") or pack_kind not in ("value", "key"):
                raise ValueError("Binding kind must be value or key")
            if pack_kind == "key" and len(target) <= len(prefix):
                raise ValueError("A key binding must remain inside the chosen atom list")
            slot = (selected_kind, selected)
            if slot in maps[role]:
                raise ValueError("Duplicate/conflicting leaf binding")
            maps[role][slot] = _resolve_key(pack, target) if pack_kind == "key" else _resolve(pack, target)
        checked = {}
        for role, opinion in opinions.items():
            mapping = maps[role]
            if "selected_value" not in opinion or _same(opinion["selected_value"], case[side]):
                if mapping:
                    raise ValueError("Unused binding for omitted or exact selected_value")
                checked[role] = {"mode": "omitted" if "selected_value" not in opinion else "exact_side", "bound_leaves": 0, "bound_keys": 0}
                continue
            leaves = _leaves(opinion["selected_value"])
            keys = _keys(opinion["selected_value"])
            facts = {("value", path): value for path, value in leaves.items()}
            facts.update({("key", path): key for path, key in keys.items()})
            if set(mapping) != set(facts):
                raise ValueError("Every selected_value leaf and object key needs exactly one binding; no extras")
            if any(not _same(value, mapping[slot]) for slot, value in facts.items()):
                raise ValueError("Bound selected_value conflicts with the exact pack type/value")
            checked[role] = {"mode": "compatible_projection", "bound_leaves": len(leaves), "bound_keys": len(keys)}
        results.append({"case_id": case["case_id"], "case_sha256": case_sha256(case),
                        "source_sha256": case["source_sha256"], "physical_pages": case["physical_pages"],
                        "accepted_side": side, "reason": "compatible_projection", "materialized_atoms": case[side],
                        "compatibility": checked, "original_opinions": opinions})
    proof = {"schema_version": "catalogue-side-materialization/1", "pack_id": pack["pack_id"],
             "pack_sha256": case_sha256(pack), "round_number": next(iter(rounds)),
             "reason": "compatible_projection", "is_new_vote": False,
             "binding_sha256": case_sha256(bindings), "bindings": bindings,
             "receipt_sha256": {role: roles[role]["receipt_sha256"] for role in REQUIRED_ROLES},
             "original_votes": [roles[role] for role in REQUIRED_ROLES], "strict_consensus": strict, "cases": results}
    # Snapshot caller inputs so later mutation cannot change a returned proof.
    proof = json.loads(canonical_json(proof))
    proof["proof_sha256"] = case_sha256(proof)
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--votes", required=True, nargs="+", type=Path)
    parser.add_argument("--bindings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    proof = materialize_side(load(args.pack), [load(path) for path in args.votes], load(args.bindings))
    write_exclusive(args.output, proof)
    print(json.dumps({"proof_sha256": proof["proof_sha256"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
