"""Fast unit + focused integration; expected 3s, emergency 30s; no API/PDF job.

Detect false agreement from omitted vs projected selected_value, incomplete or
misbound projection, type coercion and unvalidated/partial voter envelopes.
"""
import copy
import json
from pathlib import Path

import pytest

from catalog_json.reconciliation.consensus import (
    PROVIDER_MODELS, build_consensus, case_sha256, validate_vote,
)
from catalog_json.reconciliation.materialize import main, materialize_side, LEGACY_REQUIRED_ROLES

# Existing fixtures deliberately retain the historical four-participant input.
REQUIRED_ROLES = LEGACY_REQUIRED_ROLES


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


def numeric_scenario(selected=2, target="2", *, path=("value",), kind="model_parameter"):
    """Synthetic scalar111-shaped fixture; no production opinions are read."""
    fact = {"kind": kind}
    owner = fact
    for token in path[:-1]:
        owner[token] = {}; owner = owner[token]
    owner[path[-1]] = target
    case = {"case_id": "numeric-representation", "kind": "value_conflict", "source_sha256": "a"*64,
            "physical_pages": [111], "ours": [fact], "oleg": []}
    pack = {"schema_version": "catalogue-discrepancy-pack/1", "pack_id": "numeric-fixture", "cases": [case]}
    votes = []
    for role in ("codex", "zcode", "minimax"):
        verdict = {"case_id": case["case_id"], "case_sha256": case_sha256(case), "decision": "ours",
                   "reason": "Fixture numeric representation", "source_evidence": [
                       {"source_sha256": "a"*64, "page": 111, "observation": "Fixture parameter"}]}
        if role == "minimax": verdict["selected_value"] = selected
        vote = validate_vote(pack, {"pack_id": pack["pack_id"], "verdicts": [verdict]},
                             identity={"role": role, "session_id": "numeric-fixture-"+role,
                                       "model": PROVIDER_MODELS.get(role, "native-fixture"), "runtime": "fixture"},
                             sources={"a"*64: {"page_count": 111}})
        vote["round_number"] = 2 if role == "minimax" else 1
        reseal(vote); votes.append(vote)
    bindings = {"schema_version": "catalogue-side-bindings/1", "pack_sha256": case_sha256(pack), "cases": [
        {"case_id": case["case_id"], "case_sha256": case_sha256(case), "side": "ours", "bindings": [
            {"role": "minimax", "selected_pointer": "", "pack_pointer": "/cases/0/ours/0/"+"/".join(path),
             "comparison": "decimal_numeric"}]}]}
    return pack, votes, bindings


@pytest.mark.parametrize("selected,target,path", [(2,"2",("value",)), (2,"2",("raw","value")),
    ("-2,50",-2.5,("value",)), ("+2.00","2,0",("raw","value")), (0,"0.0",("value",))])
def test_explicit_decimal_parameter_binding_preserves_original_types(selected, target, path):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings = numeric_scenario(selected,target,path=path)
    before = copy.deepcopy((pack,votes,bindings))
    proof = materialize_selected_votes(pack,votes,bindings)
    assert proof["bindings"] == bindings
    assert proof["original_votes"] == votes
    assert proof["cases"][0]["materialized_atoms"] == pack["cases"][0]["ours"]
    assert (pack,votes,bindings) == before
    assert proof["opinion_rounds_by_role"]["minimax"] == 2
    assert type(proof["original_votes"][-1]["payload"]["verdicts"][0]["selected_value"]) is type(selected)


def test_decimal_mode_is_never_implicit_or_a_relaxed_strict_consensus():
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings = numeric_scenario()
    for mode in (None,"exact"):
        trial = copy.deepcopy(bindings)
        if mode is None: trial["cases"][0]["bindings"][0].pop("comparison")
        else: trial["cases"][0]["bindings"][0]["comparison"] = mode
        with pytest.raises(ValueError,match="type/value"): materialize_selected_votes(pack,votes,trial)
    with pytest.raises(ValueError,match="rounds"): materialize_side(pack,votes,bindings)
    for vote in votes: vote["round_number"] = 1; reseal(vote)
    assert materialize_side(pack,votes,bindings)["cases"][0]["accepted_side"] == "ours"


@pytest.mark.parametrize("selected,target", [(2,"1"), (True,"1"), (2,True), ("02",2), (2,"02"),
    ("2 mm",2), ("2-3",2), ("2e0",2), ("２",2), (" 2",2), ("2\n",2),
    ("NaN",2), (float("inf"),2), ({"x":2},"2"), ([2],"2"), (None,"2")])
def test_decimal_binding_refuses_non_plain_numbers_and_different_values(selected,target):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    # Nonfinite values cannot even enter the immutable JSON envelope.
    with pytest.raises(ValueError):
        pack,votes,bindings = numeric_scenario(selected,target)
        materialize_selected_votes(pack,votes,bindings)


@pytest.mark.parametrize("kind,path", [("model_designation",("value",)), ("table_cell",("value",)),
    ("model_parameter",("unit",)), ("model_parameter",("raw","raw_value")),
    ("model_parameter",("raw","nested","value"))])
def test_decimal_binding_is_limited_to_parameter_value_fields(kind,path):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings = numeric_scenario(kind=kind,path=path)
    with pytest.raises(ValueError,match="model_parameter|parameter fact"):
        materialize_selected_votes(pack,votes,bindings)


@pytest.mark.parametrize("field,value", [("selected_kind","key"), ("pack_kind","key"), ("comparison","fuzzy")])
def test_decimal_binding_never_coerces_keys_or_unknown_comparison(field,value):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings = numeric_scenario()
    bindings["cases"][0]["bindings"][0][field] = value
    with pytest.raises(ValueError): materialize_selected_votes(pack,votes,bindings)


def test_retained_row_shape_materializes_without_rewriting_votes(scenario, tmp_path, capsys):
    pack, votes, bindings = scenario
    before = copy.deepcopy((pack, votes, bindings))
    assert not build_consensus(pack, votes, required_roles=LEGACY_REQUIRED_ROLES)["all_resolved"]
    proof = materialize_side(pack, votes, bindings, required_roles=LEGACY_REQUIRED_ROLES)
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
    args = ["--role-profile", "legacy4", "--pack", paths[0], "--bindings", paths[1], "--votes", *paths[2:], "--output", str(output)]
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
    with pytest.raises(ValueError): materialize_side(pack, votes, bindings, required_roles=LEGACY_REQUIRED_ROLES)


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
    with pytest.raises(ValueError): materialize_side(pack, votes, bindings, required_roles=LEGACY_REQUIRED_ROLES)


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
    with pytest.raises(ValueError, match="type/value"): materialize_side(pack, votes, bindings, required_roles=LEGACY_REQUIRED_ROLES)
    pack["cases"][0]["ours"][0]["raw"]["typed"] = selected
    bindings["pack_sha256"] = case_sha256(pack)
    bindings["cases"][0]["case_sha256"] = case_sha256(pack["cases"][0])
    for vote in votes:
        vote["pack_sha256"] = case_sha256(pack)
        vote["payload"]["verdicts"][0]["case_sha256"] = case_sha256(pack["cases"][0]); reseal(vote)
    assert materialize_side(pack, votes, bindings, required_roles=LEGACY_REQUIRED_ROLES)["cases"][0]["accepted_side"] == "ours"


def test_exact_side_needs_no_bindings_but_unused_bindings_refused(scenario):
    pack, votes, bindings = scenario
    votes[-1]["payload"]["verdicts"][0]["selected_value"] = copy.deepcopy(pack["cases"][0]["ours"])
    reseal(votes[-1])
    with pytest.raises(ValueError, match="Unused"): materialize_side(pack, votes, bindings, required_roles=LEGACY_REQUIRED_ROLES)
    bindings["cases"][0]["bindings"] = []
    assert materialize_side(pack, votes, bindings, required_roles=LEGACY_REQUIRED_ROLES)["cases"][0]["compatibility"]["minimax"]["mode"] == "exact_side"


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
    proof = materialize_side(pack, votes, bindings, required_roles=LEGACY_REQUIRED_ROLES)
    assert proof["cases"][0]["accepted_side"] == "oleg"
    assert proof["cases"][0]["materialized_atoms"] == pack["cases"][0]["oleg"]


def test_real_retained_four_receipts_when_available():
    root = Path(__file__).resolve().parents[1]
    base = root / ".tmp/oleg-consensus-20261014/adjudication/4dd213e5e4f0b66ef59ca2248f00663bea9de5667004d1ae5bc0b9aff619b58f/round2"
    if not base.exists(): pytest.skip("Private retained pilot is not part of public fixtures")
    pack = json.loads((base / "runtime/minimax/pack.json").read_text())
    votes = [json.loads((base / "receipts" / f"{role}.json").read_text()) for role in REQUIRED_ROLES]
    assert case_sha256(pack) == "4dd213e5e4f0b66ef59ca2248f00663bea9de5667004d1ae5bc0b9aff619b58f"
    assert not build_consensus(pack, votes, required_roles=LEGACY_REQUIRED_ROLES)["all_resolved"]
    proof = materialize_side(pack, votes, row_bindings(pack), required_roles=LEGACY_REQUIRED_ROLES)
    assert proof["cases"][0]["materialized_atoms"] == pack["cases"][0]["ours"]
    assert proof["cases"][0]["compatibility"]["minimax"]["bound_leaves"] == 3


def selected_rounds(votes):
    # Unit fixtures only: simulate three retained opinions and one correction.
    for vote in votes:
        vote['round_number'] = 2 if vote['identity']['role'] == 'minimax' else 1
        reseal(vote)


def test_selected_real_rounds_preserve_strict_api_and_original_envelopes(scenario):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings=scenario
    votes=[v for v in votes if v['identity']['role']!='glm']
    selected_rounds(votes)
    before=copy.deepcopy((pack,votes,bindings))
    with pytest.raises(ValueError,match='rounds'):materialize_side(pack,votes,bindings)
    proof=materialize_selected_votes(pack,votes,bindings)
    assert proof['schema_version']=='catalogue-selected-votes-materialization/1'
    assert proof['opinion_rounds_by_role']==dict(codex=1,zcode=1,minimax=2)
    assert set(proof['strict_by_actual_round'])=={'1','2'}
    assert all(not r['complete'] for r in proof['strict_by_actual_round'].values())
    assert 'round_number' not in proof and 'strict_consensus' not in proof
    assert proof['required_roles']==['codex','zcode','minimax']
    assert proof['original_votes']==votes and not proof['is_new_vote']
    assert proof['receipt_sha256']=={v['identity']['role']:v['receipt_sha256'] for v in votes}
    assert proof['cases'][0]['materialized_atoms']==pack['cases'][0]['ours']
    assert proof['cases'][0]['compatibility']['minimax']['bound_keys']==3
    assert proof['source_bindings']==[{'sha256':'a'*64,'page_count':169}]
    assert proof['proof_sha256']==case_sha256({k:v for k,v in proof.items() if k!='proof_sha256'})
    assert (pack,votes,bindings)==before
    votes[0]['payload']['verdicts'].clear()
    assert proof['original_votes'][0]['payload']['verdicts']


@pytest.mark.parametrize('mutation',[
    'missing-role','extra','unexpected-glm','tampered','pack-sha','case-sha','same-role','same-session-across-rounds',
    'missing-round','float-round','bool-round','zero-round','string-round',
    'source-sha','source-pages','source-duplicate','source-page-bool',
    'unresolved','disagree','different-selected-value','missing-key-binding','wrong-value-binding',
])
def test_selected_rounds_never_bypass_identity_source_or_claim_guards(scenario,mutation):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings=scenario
    votes=[v for v in votes if v['identity']['role']!='glm']
    selected_rounds(votes)
    corrected=next(v for v in votes if v['identity']['role']=='minimax')
    if mutation=='missing-role':votes.pop(0)
    if mutation=='extra':votes.append(copy.deepcopy(votes[0]))
    if mutation=='unexpected-glm':
        extra=copy.deepcopy(votes[0]);extra['identity'].update(role='glm',session_id='fixture-extra-glm',model=PROVIDER_MODELS['glm']);reseal(extra);votes.append(extra)
    if mutation=='tampered':corrected['payload']['verdicts'][0]['reason']='unsealed change'
    if mutation=='pack-sha':corrected['pack_sha256']='b'*64;reseal(corrected)
    if mutation=='case-sha':corrected['payload']['verdicts'][0]['case_sha256']='b'*64;reseal(corrected)
    if mutation=='same-role':corrected['identity']['role']='codex';corrected['identity']['model']='native-fixture';reseal(corrected)
    if mutation=='same-session-across-rounds':corrected['identity']['session_id']=votes[0]['identity']['session_id'];reseal(corrected)
    if mutation=='missing-round':corrected.pop('round_number');reseal(corrected)
    if mutation=='float-round':corrected['round_number']=2.0;reseal(corrected)
    if mutation=='bool-round':corrected['round_number']=True;reseal(corrected)
    if mutation=='zero-round':corrected['round_number']=0;reseal(corrected)
    if mutation=='string-round':corrected['round_number']='2';reseal(corrected)
    if mutation=='source-sha':corrected['source_manifest'][0]['sha256']='b'*64;reseal(corrected)
    if mutation=='source-pages':corrected['source_manifest'][0]['page_count']=170;reseal(corrected)
    if mutation=='source-duplicate':corrected['source_manifest'].append(copy.deepcopy(corrected['source_manifest'][0]));reseal(corrected)
    if mutation=='source-page-bool':corrected['source_manifest'][0]['page_count']=True;reseal(corrected)
    if mutation in ('unresolved','disagree'):
        corrected['payload']['verdicts'][0]['decision']='unresolved' if mutation=='unresolved' else 'oleg';reseal(corrected)
    if mutation=='different-selected-value':
        votes[-1]['payload']['verdicts'][0]['selected_value']['150/34']='НАС-150-99Б';reseal(votes[-1])
    if mutation=='missing-key-binding':bindings['cases'][0]['bindings'].pop(1)
    if mutation=='wrong-value-binding':bindings['cases'][0]['bindings'][-2]['pack_pointer']=bindings['cases'][0]['bindings'][0]['pack_pointer']
    with pytest.raises(ValueError):materialize_selected_votes(pack,votes,bindings)


def test_same_round_strict_proof_has_identical_prechange_hash(scenario):
    pack,votes,bindings=scenario
    for vote in votes:
        vote['saved_at']='2000-01-01T00:00:00+00:00'
        reseal(vote)
    assert case_sha256([pack,votes,bindings])=='8629fa75da869707a4d411e8e21feaf323d4711d429e98e5aa600d72a72d5390'
    assert materialize_side(pack,votes,bindings,required_roles=LEGACY_REQUIRED_ROLES)['proof_sha256']=='a12fda689de15525e79543fcbd2d0269ad33bf32fbeead64c2aa6377f3c30db0'


def test_legacy_four_selected_profile_requires_explicit_opt_in(scenario):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings=scenario
    selected_rounds(votes)
    with pytest.raises(ValueError):materialize_selected_votes(pack,votes,bindings)
    proof=materialize_selected_votes(pack,votes,bindings,required_roles=('codex','zcode','glm','minimax'))
    assert proof['required_roles']==list(REQUIRED_ROLES)
    assert proof['original_votes']==votes


@pytest.mark.parametrize('roles',[('codex','minimax'),('codex','zcode','glm'),('codex','zcode','minimax','bogus'),('codex','zcode','zcode')])
def test_selected_required_profile_cannot_drop_a_current_participant(scenario,roles):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings=scenario
    votes=[v for v in votes if v['identity']['role']!='glm']
    with pytest.raises(ValueError):materialize_selected_votes(pack,votes,bindings,required_roles=roles)


def test_strict_default_and_cli_use_three_participants(scenario,tmp_path):
    pack,votes,bindings=scenario
    votes=[v for v in votes if v['identity']['role']!='glm']
    proof=materialize_side(pack,votes,bindings)
    assert proof['strict_consensus']['required_roles']==['codex','zcode','minimax']
    assert len(proof['original_votes'])==3
    paths=[]
    for i,item in enumerate([pack,bindings,*votes]):
        p=tmp_path/f'{i}.json';p.write_text(json.dumps(item));paths.append(str(p))
    output=tmp_path/'strict3.json'
    assert main(['--pack',paths[0],'--bindings',paths[1],'--votes',*paths[2:],'--output',str(output)])==0
    assert json.loads(output.read_text())==proof


def test_cli_mixed_round_selection_is_explicit_and_three_role_default(scenario,tmp_path):
    from catalog_json.reconciliation.materialize import materialize_selected_votes
    pack,votes,bindings=scenario
    votes=[v for v in votes if v['identity']['role']!='glm'];selected_rounds(votes)
    proof=materialize_selected_votes(pack,votes,bindings)
    paths=[]
    for i,item in enumerate([pack,bindings,*votes]):
        p=tmp_path/f'{i}.json';p.write_text(json.dumps(item));paths.append(str(p))
    output=tmp_path/'selected3.json'
    args=['--pack',paths[0],'--bindings',paths[1],'--votes',*paths[2:],'--output',str(output)]
    with pytest.raises(ValueError,match='rounds'):main(args)
    assert not output.exists()
    assert main(['--selected-votes',*args])==0
    assert json.loads(output.read_text())==proof
