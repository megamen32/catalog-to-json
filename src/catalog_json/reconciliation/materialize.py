"""Materialize a unanimously chosen input side through explicit caller-owned bindings.

This creates a compatibility proof, never new votes or a replacement strict consensus.
Pointers in bindings refer to selected_value and the immutable pack respectively.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

from .consensus import build_consensus, canonical_json, case_sha256, write_exclusive


DEFAULT_REQUIRED_ROLES = ("codex", "zcode", "minimax")
LEGACY_REQUIRED_ROLES = ("codex", "zcode", "glm", "minimax")


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


def _decimal_scalar(value):
    # Deliberately narrower than general numeric parsing: no IDs with leading
    # zeros, Unicode digits, whitespace, exponents, ranges or embedded units.
    if type(value) not in (str, int, float):
        raise ValueError("decimal_numeric requires a plain numeric scalar")
    text = str(value)
    if not re.fullmatch(r"[+-]?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?", text, re.ASCII):
        raise ValueError("decimal_numeric requires ASCII plain numbers without leading zeros")
    number = Decimal(text.replace(",", "."))
    if not number.is_finite():
        raise ValueError("decimal_numeric requires finite numbers")
    return number


def _decimal_target(pack, target, prefix, selected_kind, pack_kind):
    if selected_kind != "value" or pack_kind != "value" or target[4:] not in (("value",), ("raw", "value")):
        raise ValueError("decimal_numeric only binds value to a model_parameter value")
    if len(target) < 5 or target[:3] != prefix:
        raise ValueError("decimal_numeric target must identify a parameter fact")
    fact = _resolve(pack, target[:4])
    if type(fact) is not dict or fact.get("kind") != "model_parameter":
        raise ValueError("decimal_numeric target must be a model_parameter fact")


def _materialize_cases(pack, votes, bindings, required_roles):
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
        maps = {role: {} for role in required_roles}
        prefix = ("cases", str(i), side)
        for item in entry["bindings"]:
            required = {"role", "selected_pointer", "pack_pointer"}
            if type(item) is not dict or not required <= set(item) or set(item) - required - {"selected_kind", "pack_kind", "comparison"}:
                raise ValueError("Binding requires role, selected_pointer, pack_pointer; only optional selected_kind/pack_kind/comparison")
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
            comparison = item.get("comparison", "exact")
            if comparison not in ("exact", "decimal_numeric"):
                raise ValueError("Binding comparison must be exact or decimal_numeric")
            if comparison == "decimal_numeric":
                _decimal_target(pack, target, prefix, selected_kind, pack_kind)
            slot = (selected_kind, selected)
            if slot in maps[role]:
                raise ValueError("Duplicate/conflicting leaf binding")
            value = _resolve_key(pack, target) if pack_kind == "key" else _resolve(pack, target)
            maps[role][slot] = (value, comparison)
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
            for slot, value in facts.items():
                target_value, comparison = mapping[slot]
                same = (_same(value, target_value) if comparison == "exact"
                        else _decimal_scalar(value) == _decimal_scalar(target_value))
                if not same:
                    raise ValueError("Bound selected_value conflicts with the exact pack type/value")
            checked[role] = {"mode": "compatible_projection", "bound_leaves": len(leaves), "bound_keys": len(keys)}
        results.append({"case_id": case["case_id"], "case_sha256": case_sha256(case),
                        "source_sha256": case["source_sha256"], "physical_pages": case["physical_pages"],
                        "accepted_side": side, "reason": "compatible_projection", "materialized_atoms": case[side],
                        "compatibility": checked, "original_opinions": opinions})
    return roles, results


def materialize_side(pack: dict, votes: list[dict], bindings: dict, *,
                     required_roles=DEFAULT_REQUIRED_ROLES) -> dict:
    """Refuse unless all required validated votes choose the same side for every case.

    New calls default to Codex, native ZCode and MiniMax. Historical four-role
    strict proofs require explicit required_roles=LEGACY_REQUIRED_ROLES.

    Nonidentical selected_value requires exhaustive value-leaf AND object-key
    bindings into that case's chosen side. A binding has role, selected_pointer,
    pack_pointer and optional selected_kind/pack_kind (value by default, or key).
    Optional comparison=decimal_numeric explicitly permits equal plain numeric
    scalars only at a model_parameter fact's value/raw.value; default is exact.
    Binding documents must be supplied by the trusted
    caller, never generated implicitly from a model's value or inferred by search.
    """
    required = _selected_profile(required_roles)
    strict = build_consensus(pack, votes, required_roles=required)  # Validate originals first.
    if not strict["complete"] or len(votes) != len(required):
        raise ValueError("Every required independent receipt is required")
    round_numbers = [vote.get("round_number", 1) for vote in votes]
    if any(type(n) is not int or n < 1 for n in round_numbers):
        raise ValueError("A positive integer deliberation round is required")
    rounds = set(round_numbers)
    roles, results = _materialize_cases(pack, votes, bindings, required)
    proof = {"schema_version": "catalogue-side-materialization/1", "pack_id": pack["pack_id"],
             "pack_sha256": case_sha256(pack), "round_number": next(iter(rounds)),
             "reason": "compatible_projection", "is_new_vote": False,
             "binding_sha256": case_sha256(bindings), "bindings": bindings,
             "receipt_sha256": {role: roles[role]["receipt_sha256"] for role in required},
             "original_votes": [roles[role] for role in required], "strict_consensus": strict, "cases": results}
    # Snapshot caller inputs so later mutation cannot change a returned proof.
    proof = json.loads(canonical_json(proof))
    proof["proof_sha256"] = case_sha256(proof)
    return proof



def _selected_profile(required_roles):
    if not isinstance(required_roles, (list, tuple, set, frozenset)):
        raise ValueError("Explicit current-three or historical-four role profile required")
    roles = tuple(required_roles)
    if any(not isinstance(role, str) for role in roles):
        raise ValueError("Required role names must be strings")
    if len(roles) != len(set(roles)):
        raise ValueError("Required role profile cannot contain duplicates")
    for profile in (DEFAULT_REQUIRED_ROLES, LEGACY_REQUIRED_ROLES):
        if len(roles) == len(profile) and set(roles) == set(profile):
            return profile
    raise ValueError("Only current-three or explicit historical-four profiles are supported")


def _selected_receipts(pack, votes, required_roles):
    required = _selected_profile(required_roles)
    if not isinstance(votes, (list, tuple)) or len(votes) != len(required):
        raise ValueError("Exactly one explicitly selected original receipt per required role is required")
    roles, sessions, cohorts = {}, set(), {}
    for vote in votes:
        if type(vote) is not dict or type(vote.get("identity")) is not dict:
            raise ValueError("Original validated receipt envelopes are required")
        identity = vote["identity"]
        role, session = identity.get("role"), identity.get("session_id")
        if role not in required or role in roles or not isinstance(session, str) or not session.strip() or session in sessions:
            raise ValueError("Required roles and actual sessions must be distinct across all selected rounds")
        number = vote.get("round_number")
        if type(number) is not int or number < 1:
            raise ValueError("Every selected receipt needs its real positive integer opinion round")
        if vote.get("pack_id") != pack.get("pack_id"):
            raise ValueError("Selected receipt must retain the exact pack identity")
        roles[role] = vote
        sessions.add(session)
        cohorts.setdefault(number, []).append(vote)
    # Each cohort goes through the unchanged historical strict validator.
    # Partial cohort results are evidence, never a fabricated combined strict vote.
    strict = {str(number): build_consensus(pack, cohorts[number], required_roles=required) for number in sorted(cohorts)}
    required_sources = {case["source_sha256"] for case in pack["cases"]}
    source_bindings = None
    for role in required:
        manifest = roles[role].get("source_manifest")
        if type(manifest) is not list:
            raise ValueError("Selected receipt source manifest must be a list")
        sources = {}
        for item in manifest:
            if (type(item) is not dict or set(item) != {"sha256", "page_count"}
                    or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                    or type(item["page_count"]) is not int or item["page_count"] < 1
                    or item["sha256"] in sources):
                raise ValueError("Source bindings must contain distinct SHA256s and real positive page counts")
            sources[item["sha256"]] = item
        if not required_sources <= set(sources):
            raise ValueError("Every case source must remain explicitly bound")
        selected = [sources[digest] for digest in sorted(required_sources)]
        if source_bindings is not None and canonical_json(selected) != canonical_json(source_bindings):
            raise ValueError("Selected receipts disagree on the immutable source binding")
        source_bindings = selected
    return required, roles, strict, source_bindings


def materialize_selected_votes(pack: dict, explicit_votes: list[dict], bindings: dict, *,
                               required_roles=DEFAULT_REQUIRED_ROLES) -> dict:
    """Materialize explicitly selected real opinions without rewriting their rounds.

    Default participants are Codex, native ZCode and MiniMax. Historical four-
    role inputs require an explicit LEGACY_REQUIRED_ROLES profile. There is no
    receipt discovery/latest selection and no synthetic/resealed vote. Different
    actual claims still fail the exact shared leaf AND object-key reducer.
    """
    required, roles, strict, sources = _selected_receipts(pack, explicit_votes, required_roles)
    _, results = _materialize_cases(pack, explicit_votes, bindings, required)
    proof = {"schema_version": "catalogue-selected-votes-materialization/1", "pack_id": pack["pack_id"],
             "pack_sha256": case_sha256(pack), "required_roles": list(required),
             "opinion_rounds_by_role": {role: roles[role]["round_number"] for role in required},
             "strict_by_actual_round": strict, "source_bindings": sources,
             "reason": "compatible_projection", "is_new_vote": False,
             "binding_sha256": case_sha256(bindings), "bindings": bindings,
             "receipt_sha256": {role: roles[role]["receipt_sha256"] for role in required},
             "original_votes": [roles[role] for role in required], "cases": results}
    proof = json.loads(canonical_json(proof))
    proof["proof_sha256"] = case_sha256(proof)
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--votes", required=True, nargs="+", type=Path)
    parser.add_argument("--bindings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--role-profile", choices=("current3", "legacy4"), default="current3",
                        help="New three-participant consensus; legacy4 is explicit historical audit only")
    parser.add_argument("--selected-votes", action="store_true",
                        help="Explicitly selected original opinions may have different real rounds")
    args = parser.parse_args(argv)
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    required = DEFAULT_REQUIRED_ROLES if args.role_profile == "current3" else LEGACY_REQUIRED_ROLES
    materialize = materialize_selected_votes if args.selected_votes else materialize_side
    proof = materialize(load(args.pack), [load(path) for path in args.votes], load(args.bindings),
                        required_roles=required)
    write_exclusive(args.output, proof)
    print(json.dumps({"proof_sha256": proof["proof_sha256"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
