"""Fast unit + focused integration; expected 3s, emergency 30s; no API/PDF job.

Detect false agreement from omitted vs projected selected_value, incomplete or
misbound projection, type coercion and unvalidated/partial voter envelopes.
"""
import copy
import json
from pathlib import Path

import pytest

from catalog_json.reconciliation.consensus import (
    PROVIDER_MODELS, REQUIRED_ROLES, build_consensus, case_sha256, validate_vote,
)
from catalog_json.reconciliation.materialize import main, materialize_side


def row_bindings(pack):
    """Caller binds both row-map keys and clamp values; no inference by matching."""
    case = pack["cases"][0]
    items = []
    for i, section in enumerate(("150/19", "150/24", "150/34")):
        pointer = "/" + section.replace("/", "~1")
        items.extend([
            {"role": "minimax", "selected_pointer": pointer, "pack_pointer": f"/cases/0/ours/{i}/raw/cells/4/value"},
            {"role": "minimax", "selected_kind": "key", "selected_pointer": pointer,
             "pack_pointer": f"/cases/0/ours/{i}/raw/cells/1/value"},
        ])
    return {"schema_version": "catalogue-side-bindings/1", "pack_sha256": case_sha256(pack), "cases": [
        {"case_id": case["case_id"], "case_sha256": case_sha256(case), "side": "ours", "bindings": items}]}


@pytest.fixture
def scenario():
    # Small retained169 structure: preserve actual row/cell indexes and Unicode.
    rows = []
    for i, section in enumerate(("150/19", "150/24", "150/34")):
        rows.append({"pointer": f"/catalogs/4/pages/168/content/tables/0/rows/{i+4}", "raw": {"cells": [
            {"column_id": "c1", "value": "ШСИП-110-(16-17,5)-9-L", "state": "value"},
            {"column_id": "c2", "value": section, "state": "value"},
            {"column_id": "c3", "value": "16-17,5", "state": "value"},
            {"column_id": "c4", "value": "А4АБ 150-185", "state": "value"},
            {"column_id": "c5", "value": "НАС-150-1Б" if i < 2 else "НАС-150-2Б", "state": "value"}]}})
    pack = {"schema_version": "catalogue-discrepancy-pack/1", "pack_id": "retained169-shape", "cases": [
        {"case_id": "pilot-arm169-row-context", "kind": "row_relationship", "source_sha256": "a"*64,
         "physical_pages": [169], "ours": rows, "oleg": [{"raw": {"raw_value": "НАС-150-1Б, НАС-150-2Б"}}]}]}
    case = pack["cases"][0]
    votes = []
    for role in REQUIRED_ROLES:
        opinion = {"case_id": case["case_id"], "case_sha256": case_sha256(case), "decision": "ours",
                   "reason": "Fixture of preserved row correspondence", "source_evidence": [
                       {"source_sha256": "a"*64, "page": 169, "observation": "Three rows, two merged clamp labels"}]}
        if role == "minimax":
            opinion["selected_value"] = {"150/19": "НАС-150-1Б", "150/24": "НАС-150-1Б", "150/34": "НАС-150-2Б"}
        vote = validate_vote(pack, {"pack_id": pack["pack_id"], "verdicts": [opinion]},
            identity={"role": role, "session_id": "fixture-"+role, "model": PROVIDER_MODELS.get(role, "native-fixture"),
                      "runtime": "local-fixture"}, sources={"a"*64: {"page_count": 169}})
        vote["round_number"] = 2
        vote["receipt_sha256"] = case_sha256({k: v for k, v in vote.items() if k != "receipt_sha256"})
        votes.append(vote)
    return pack, votes, row_bindings(pack)


def reseal(vote):
    vote["receipt_sha256"] = case_sha256({k: v for k, v in vote.items() if k != "receipt_sha256"})


def test_retained_row_shape_materializes_without_rewriting_votes(scenario, tmp_path, capsys):
    pack, votes, bindings = scenario
    before = copy.deepcopy((pack, votes, bindings))
    assert not build_consensus(pack, votes)["all_resolved"]
    proof = materialize_side(pack, votes, bindings)
    assert proof["cases"][0]["accepted_side"] == "ours"
    assert proof["cases"][0]["materialized_atoms"] == pack["cases"][0]["ours"]
    assert proof["cases"][0]["compatibility"]["minimax"] == {"mode": "compatible_projection", "bound_leaves": 3, "bound_keys": 3}
    assert proof["original_votes"] == votes and not proof["is_new_vote"]
    assert not proof["strict_consensus"]["all_resolved"]
    assert proof["binding_sha256"] == case_sha256(bindings)
    assert proof["receipt_sha256"] == {v["identity"]["role"]: v["receipt_sha256"] for v in votes}
    assert proof["proof_sha256"] == case_sha256({k: v for k, v in proof.items() if k != "proof_sha256"})
    assert (pack, votes, bindings) == before
    paths = []
    for i, item in enumerate([pack, bindings, *votes]):
        path = tmp_path / f"{i}.json"; path.write_text(json.dumps(item)); paths.append(str(path))
    output = tmp_path / "proof.json"
    args = ["--pack", paths[0], "--bindings", paths[1], "--votes", *paths[2:], "--output", str(output)]
    assert main(args) == 0 and json.loads(output.read_text()) == proof
    with pytest.raises(FileExistsError): main(args)
    # Returned proof is a snapshot, not a mutable reference into caller inputs.
    pack["cases"][0]["ours"].clear()
    assert proof["cases"][0]["materialized_atoms"]


@pytest.mark.parametrize("mutation", ["missing-leaf", "missing-key", "extra", "duplicate", "wrong-value", "wrong-key",
    "cross-side", "cross-case", "unresolvable", "bad-escape", "noncanonical-index", "pack-sha", "case-sha", "partial-case"])
def test_refuses_incomplete_conflicting_or_unbound_projection(scenario, mutation):
    pack, votes, bindings = scenario
    entry = bindings["cases"][0]; items = entry["bindings"]
    if mutation == "missing-leaf": items.pop(0)
    if mutation == "missing-key": items.pop(1)
    if mutation == "extra": items.append({**items[0], "selected_pointer": "/invented"})
    if mutation == "duplicate": items.append(copy.deepcopy(items[0]))
    if mutation == "wrong-value": items[-2]["pack_pointer"] = items[0]["pack_pointer"]
    if mutation == "wrong-key": items[1]["pack_pointer"] = items[3]["pack_pointer"]
    if mutation == "cross-side": items[0]["pack_pointer"] = "/cases/0/oleg/0/raw/raw_value"
    if mutation == "cross-case": items[0]["pack_pointer"] = "/cases/1/ours/0/raw/cells/4/value"
    if mutation == "unresolvable": items[0]["pack_pointer"] += "/nope"
    if mutation == "bad-escape": items[0]["selected_pointer"] = "/150~219"
    if mutation == "noncanonical-index": items[0]["pack_pointer"] = "/cases/0/ours/00/raw/cells/4/value"
    if mutation == "pack-sha": bindings["pack_sha256"] = "b"*64
    if mutation == "case-sha": entry["case_sha256"] = "b"*64
    if mutation == "partial-case": bindings["cases"].clear()
    with pytest.raises(ValueError): materialize_side(pack, votes, bindings)


@pytest.mark.parametrize("mutation", ["three", "tampered", "same-session", "same-role", "round", "round-coercion", "unresolved", "disagree", "neither"])
def test_all_receipts_validated_before_compatibility(scenario, mutation):
    pack, votes, bindings = scenario
    if mutation == "three": votes.pop(0)
    if mutation == "tampered": votes[0]["payload"]["verdicts"][0]["reason"] = "tampered"
    if mutation == "same-session": votes[0]["identity"]["session_id"] = votes[1]["identity"]["session_id"]; reseal(votes[0])
    if mutation == "same-role": votes[0] = copy.deepcopy(votes[1])
    if mutation == "round": votes[0]["round_number"] = 3; reseal(votes[0])
    if mutation == "round-coercion": votes[-1]["round_number"] = 2.0; reseal(votes[-1])
    if mutation in {"unresolved", "disagree", "neither"}:
        votes[0]["payload"]["verdicts"][0]["decision"] = {"unresolved": "unresolved", "disagree": "oleg", "neither": "neither"}[mutation]
        reseal(votes[0])
    with pytest.raises(ValueError): materialize_side(pack, votes, bindings)


@pytest.mark.parametrize("selected,target", [(True, 1), (1, 1.0), ("1", 1), (None, "null"), ({}, []), ([], {})])
def test_exact_types_null_and_empty_containers_are_bound(scenario, selected, target):
    pack, votes, bindings = scenario
    pack["cases"][0]["ours"][0]["raw"]["typed"] = target
    bindings["pack_sha256"] = case_sha256(pack)
    bindings["cases"][0]["case_sha256"] = case_sha256(pack["cases"][0])
    bindings["cases"][0]["bindings"] = [{"role": "minimax", "selected_pointer": "", "pack_pointer": "/cases/0/ours/0/raw/typed"}]
    for vote in votes:
        vote["pack_sha256"] = case_sha256(pack)
        vote["payload"]["verdicts"][0]["case_sha256"] = case_sha256(pack["cases"][0])
        reseal(vote)
    votes[-1]["payload"]["verdicts"][0]["selected_value"] = selected; reseal(votes[-1])
    with pytest.raises(ValueError, match="type/value"): materialize_side(pack, votes, bindings)
    pack["cases"][0]["ours"][0]["raw"]["typed"] = selected
    bindings["pack_sha256"] = case_sha256(pack)
    bindings["cases"][0]["case_sha256"] = case_sha256(pack["cases"][0])
    for vote in votes:
        vote["pack_sha256"] = case_sha256(pack)
        vote["payload"]["verdicts"][0]["case_sha256"] = case_sha256(pack["cases"][0]); reseal(vote)
    assert materialize_side(pack, votes, bindings)["cases"][0]["accepted_side"] == "ours"


def test_exact_side_needs_no_bindings_but_unused_bindings_refused(scenario):
    pack, votes, bindings = scenario
    votes[-1]["payload"]["verdicts"][0]["selected_value"] = copy.deepcopy(pack["cases"][0]["ours"])
    reseal(votes[-1])
    with pytest.raises(ValueError, match="Unused"): materialize_side(pack, votes, bindings)
    bindings["cases"][0]["bindings"] = []
    assert materialize_side(pack, votes, bindings)["cases"][0]["compatibility"]["minimax"]["mode"] == "exact_side"


def test_oleg_side_and_object_key_targets_are_supported(scenario):
    pack, votes, bindings = scenario
    for vote in votes:
        opinion = vote["payload"]["verdicts"][0]
        opinion["decision"] = "oleg"
        opinion.pop("selected_value", None)
        reseal(vote)
    entry = bindings["cases"][0]; entry["side"] = "oleg"
    entry["bindings"] = [
        {"role": "minimax", "selected_pointer": "/raw_value", "pack_pointer": "/cases/0/oleg/0/raw/raw_value"},
        {"role": "minimax", "selected_kind": "key", "pack_kind": "key", "selected_pointer": "/raw_value",
         "pack_pointer": "/cases/0/oleg/0/raw/raw_value"}]
    votes[-1]["payload"]["verdicts"][0]["selected_value"] = copy.deepcopy(pack["cases"][0]["oleg"][0]["raw"])
    reseal(votes[-1])
    proof = materialize_side(pack, votes, bindings)
    assert proof["cases"][0]["accepted_side"] == "oleg"
    assert proof["cases"][0]["materialized_atoms"] == pack["cases"][0]["oleg"]


def test_real_retained_four_receipts_when_available():
    root = Path(__file__).resolve().parents[1]
    base = root / ".tmp/oleg-consensus-20261014/adjudication/4dd213e5e4f0b66ef59ca2248f00663bea9de5667004d1ae5bc0b9aff619b58f/round2"
    if not base.exists(): pytest.skip("Private retained pilot is not part of public fixtures")
    pack = json.loads((base / "runtime/minimax/pack.json").read_text())
    votes = [json.loads((base / "receipts" / f"{role}.json").read_text()) for role in REQUIRED_ROLES]
    assert case_sha256(pack) == "4dd213e5e4f0b66ef59ca2248f00663bea9de5667004d1ae5bc0b9aff619b58f"
    assert not build_consensus(pack, votes)["all_resolved"]
    proof = materialize_side(pack, votes, row_bindings(pack))
    assert proof["cases"][0]["materialized_atoms"] == pack["cases"][0]["ours"]
    assert proof["cases"][0]["compatibility"]["minimax"]["bound_leaves"] == 3
