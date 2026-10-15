"""Fast unit / focused integration: reviewed closure keeps history and types.

Detect stale-base replay, dropped unresolved facts, wrong-page evidence and
unverified workbook closure. Expected 3s; emergency 30s. No model calls.
"""
import copy
import hashlib
import json

import pytest

from ops.catalogue_delivery.source_revision import digest, revise
from ops.catalogue_delivery.canonical_export import export
from ops.catalogue_delivery.verify_canonical import verify


def fixture():
    original = [{"catalog": "test", "physical_page": 1,
                 "fact": {"fact_id": f"old-{i}", "value": "1121"}} for i in range(42)]
    record = dict(id="C-a", catalog="test", page=1, kind="drawing_annotation",
                  model="A", parameter="Габарит", part=None, condition=None,
                  value="1121", unit=None, state="value", source_fact_ids=["O-1"],
                  producer_ref="original")
    doc = dict(schema="canonical-catalogue/1", sources=[dict(id="test", page_count=1,
                filename="original.pdf", sha256="a"*64)], pages=[dict(catalog="test", page=1)],
               producers={"original": {"actual_version": "old"}}, records=[record],
               unresolved=original, metadata={"input_archive_sha256": "b"*64,
                                               "selected_table_source_fact_ids": ["O-1"]})
    ev = [dict(catalog="test", page=1, source_sha256="a"*64, region=[0, 0, 10, 10])]
    pack = dict(schema="canonical-source-review/1", input_sha256="base", reviewers=["source-viewer"],
                review_scope="one source page", actions=[], closures=[dict(fact_id=u["fact"]["fact_id"],
                before_sha256=digest(u), disposition="closed", reason="Misread in old extraction",
                evidence=ev, record_ids=["C-a"]) for u in original])
    corrected = {**record, "value": "1211"}
    pack["actions"].append(dict(op="replace", id="C-a", before_sha256=digest(record),
                                record=corrected, reason="Source crop reviewed", evidence=ev))
    return doc, pack


def test_changed_value_and_original_facts_remain_in_separate_history():
    doc, pack = fixture()
    before = copy.deepcopy(doc)
    out, ledger = revise(doc, pack, input_sha256="base", builder={"version": "test"})
    assert doc == before
    assert out["unresolved"] == []
    assert out["records"][0]["value"] == "1211"
    assert ledger["original_unresolved"] == before["unresolved"]
    assert ledger["record_changes"][0]["before"]["value"] == "1121"
    assert out["producers"] == before["producers"]


@pytest.mark.parametrize("failure", ["stale_base", "dropped_fact", "duplicate_fact", "wrong_page", "wrong_before"])
def test_unreviewed_or_mismatched_closure_is_rejected(failure):
    doc, pack = fixture()
    if failure == "stale_base": pack["input_sha256"] = "different"
    if failure == "dropped_fact": pack["closures"].pop()
    if failure == "duplicate_fact": pack["closures"].append(pack["closures"][0])
    if failure == "wrong_page": pack["actions"][0]["evidence"][0]["page"] = 2
    if failure == "wrong_before": pack["actions"][0]["before_sha256"] = "different"
    with pytest.raises(ValueError):
        revise(doc, pack, input_sha256="base", builder={})


def test_readback_requires_unchanged_closure_ledger(tmp_path):
    doc, pack = fixture()
    out, ledger = revise(doc, pack, input_sha256="base", builder={"version": "test"})
    source = tmp_path / "revised.json"
    source.write_text(json.dumps(out, ensure_ascii=False))
    ref = tmp_path / "original42.json"
    ref.write_text(json.dumps(doc["unresolved"]))
    led = tmp_path / "review.json"
    led.write_text(json.dumps(ledger))
    delivery = export(source, tmp_path / "delivery")
    kwargs = dict(unresolved_reference=ref, closure_ledger=led, expected_table_ids=["O-1"],
                  expected_page_counts={"test": 1}, archive=delivery["catalogues-unified.zip"],
                  manifest=delivery["manifest.json"])
    result = verify(delivery["catalogue.json"], delivery["catalogue.xlsx"], **kwargs)
    assert result["ok"], result
    ledger["closures"][0]["reason"] = "changed after review"
    led.write_text(json.dumps(ledger))
    result = verify(delivery["catalogue.json"], delivery["catalogue.xlsx"], **kwargs)
    assert not result["ok"]
    assert "closure_ledger_identity" in {x["code"] for x in result["failures"]}


def test_readback_detects_undeclared_deletion_outside_selected_tables(tmp_path):
    doc, pack = fixture()
    doc["records"].append({**doc["records"][0], "id": "C-unlisted",
                           "source_fact_ids": ["O-unlisted"]})
    out, ledger = revise(doc, pack, input_sha256="base", builder={"version": "test"})
    out["records"] = [r for r in out["records"] if r["id"] != "C-unlisted"]
    source = tmp_path / "tampered.json"
    source.write_text(json.dumps(out))
    ref = tmp_path / "original42.json"
    ref.write_text(json.dumps(doc["unresolved"]))
    led = tmp_path / "review.json"
    led.write_text(json.dumps(ledger))
    delivery = export(source, tmp_path / "delivery")
    result = verify(delivery["catalogue.json"], delivery["catalogue.xlsx"],
                    unresolved_reference=ref, closure_ledger=led,
                    expected_table_ids=["O-1"], expected_page_counts={"test": 1})
    assert not result["ok"]
    assert "reviewed_recordset_mismatch" in {x["code"] for x in result["failures"]}
