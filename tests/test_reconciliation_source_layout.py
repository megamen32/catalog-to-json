"""Fast unit + focused local PDF integration; expected 3s, emergency 30s.

Detect unauthorized pages, fabricated/truncated layout, rotation mistakes and
changed source evidence. No OCR, model calls or live runtime writes.
"""
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from catalog_json.reconciliation.consensus import canonical_json
from catalog_json.reconciliation.source_layout import SourceLayout


@pytest.fixture
def layout_input(tmp_path):
    pdf = tmp_path / "native.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=200)
        for text, point in [("180", (25, 40)), ("200", (110, 40)), ("1", (220, 40)), ("2", (220, 140))]:
            page.insert_text(point, text)
        page.draw_line((20, 100), (260, 100))
        page.draw_line((200, 20), (200, 170))
        page.draw_rect((20, 20, 260, 170))
        page.draw_line((50, 50), (150, 80))  # Diagonal is not an axis divider.
        page.draw_bezier((25, 180), (50, 160), (150, 160), (200, 180))
        page.draw_rect((270, 20, 290, 170), color=None, fill=(0, 0, 0))
        doc.new_page(width=300, height=200).insert_text((20, 40), "Not authorized")
        doc.save(pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps([{"sha256": digest, "path": "native.pdf"}]))
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"schema_version": "catalogue-discrepancy-pack/1", "pack_id": "native-layout-fixture", "cases": [
        {"case_id": "row", "kind": "technical", "source_sha256": digest, "physical_pages": [1], "ours": [], "oleg": []}]}))
    return {"pack_path": pack, "sources_path": sources}, pdf, digest


def test_native_words_and_real_segments_keep_coordinates_and_crop_extent(layout_input):
    args, pdf, digest = layout_input
    before = pdf.read_bytes()
    result = SourceLayout(**args).inspect_layout(digest, 1, [.3, .1, .9, .8])
    assert result["complete"] and result["status"] == "ok"
    assert {w["text"] for w in result["words"]} == {"200", "1", "2"}
    assert result["serialized_bytes"] == len(canonical_json(result)) <= result["limits"]["bytes"]
    assert {s["orientation"] for s in result["segments"]} == {"horizontal", "vertical"}
    line = next(s for s in result["segments"] if s["native_start_points"] == [20., 100.]
                and s["native_end_points"] == [260., 100.])
    assert line["start"] == pytest.approx([20 / 300, .5])
    assert line["end"] == pytest.approx([260 / 300, .5])
    assert line["visible_start"] == pytest.approx([.3, .5])
    assert line["visible_end"] == pytest.approx([260 / 300, .5])
    assert all(s["primitive"] == "line" or s["primitive"].startswith("rectangle_edge") for s in result["segments"])
    assert len(SourceLayout(**args).inspect_layout(digest, 1)["segments"]) == 6
    assert pdf.read_bytes() == before


@pytest.mark.parametrize("page,bbox", [(True, None), ("1", None), (1.0, None), (2, None), (1, [0, 0, 0, 1]),
    (1, [0, 0, 1.1, 1]), (1, [False, 0, 1, 1]), (1, [0, 0, float("nan"), 1])])
def test_scope_and_input_types_fail_closed(layout_input, page, bbox):
    args, _, digest = layout_input
    with pytest.raises(ValueError): SourceLayout(**args).inspect_layout(digest, page, bbox)
    with pytest.raises(ValueError): SourceLayout(**args).inspect_layout("b"*64, 1)


@pytest.mark.parametrize("limit,kwargs", [("words", {"max_words": 1}), ("segments", {"max_segments": 1}),
                                         ("bytes", {"max_bytes": 2048})])
def test_limits_return_no_partial_layout_and_offer_smaller_regions(layout_input, limit, kwargs):
    args, _, digest = layout_input
    result = SourceLayout(**args, **kwargs).inspect_layout(digest, 1)
    assert result["status"] == "limit_exceeded" and result["complete"] is False
    assert result["limit"] == limit
    assert "words" not in result and "segments" not in result
    assert len(result["suggested_subregions"]) == 4
    assert result["observed_at_least"] > result["limits"][limit]
    assert len(canonical_json(result)) <= result["limits"]["bytes"]


@pytest.mark.parametrize("kwargs", [{"max_words": 0}, {"max_words": True}, {"max_words": 1025},
    {"max_segments": "100"}, {"max_segments": 4097}, {"max_bytes": 2047}, {"max_bytes": 262145}])
def test_limit_configuration_is_finite_and_typed(layout_input, kwargs):
    args, *_ = layout_input
    with pytest.raises(ValueError): SourceLayout(**args, **kwargs)


def test_source_bytes_and_post_verification_mutation_are_refused(layout_input):
    args, pdf, digest = layout_input
    helper = SourceLayout(**args)
    pdf.write_bytes(pdf.read_bytes() + b"\n%changed")
    with pytest.raises(ValueError, match="changed"): helper.inspect_layout(digest, 1)
    with pytest.raises(ValueError, match="hash mismatch"): SourceLayout(**args)


def test_source_rechecked_after_native_read(layout_input, monkeypatch):
    args, pdf, digest = layout_input
    helper = SourceLayout(**args)
    get_text = pymupdf.Page.get_text
    def mutate(page, *pargs, **kwargs):
        result = get_text(page, *pargs, **kwargs)
        pdf.write_bytes(pdf.read_bytes() + b"\n%changed during inspection")
        return result
    monkeypatch.setattr(pymupdf.Page, "get_text", mutate)
    with pytest.raises(ValueError, match="changed"): helper.inspect_layout(digest, 1)


def test_rotated_page_words_and_vectors_share_display_coordinate_frame(layout_input):
    args, pdf, _ = layout_input
    with pymupdf.open(pdf) as doc:
        doc[0].set_rotation(90); doc.saveIncr()
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    sources = json.loads(args["sources_path"].read_text()); sources[0]["sha256"] = digest
    args["sources_path"].write_text(json.dumps(sources))
    pack = json.loads(args["pack_path"].read_text()); pack["cases"][0]["source_sha256"] = digest
    args["pack_path"].write_text(json.dumps(pack))
    result = SourceLayout(**args).inspect_layout(digest, 1)
    assert result["page_rotation_degrees"] == 90 and result["page_size_points"] == [200, 300]
    line = next(s for s in result["segments"] if s["native_start_points"] == [20., 100.]
                and s["native_end_points"] == [260., 100.])
    assert line["orientation"] == "vertical"
    assert line["start"] == pytest.approx([.5, 20 / 300])
    word = next(w for w in result["words"] if w["text"] == "180")
    assert word["bbox"][0] > .7 and word["bbox"][1] == pytest.approx(25/300)


def test_missing_native_text_is_empty_evidence_not_ocr(layout_input, monkeypatch):
    args, _, digest = layout_input
    monkeypatch.setattr(pymupdf.Page, "get_text", lambda *a, **k: [])
    result = SourceLayout(**args).inspect_layout(digest, 1)
    assert result["complete"] and result["words"] == [] and result["segments"]


def test_actual_arm111_execution_band_when_private_source_available(tmp_path):
    pdf = Path('/home/roomhacker/.codex/attachments/bfdf19c7-5403-4bbf-a27a-603838153c54/Katalog-ARMATURA.pdf')
    if not pdf.exists(): pytest.skip("Private native catalogue not part of public test fixtures")
    digest = "c8cb0bf124607d1f5f9de18fc48d467033262b9f43c205a582b01521e5aaab4e"
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"schema_version": "catalogue-discrepancy-pack/1", "pack_id": "arm111-native-layout-canary", "cases": [
        {"case_id": "execution-boundary", "kind": "technical", "source_sha256": digest, "physical_pages": [111], "ours": [], "oleg": []}]}))
    sources = tmp_path / "sources.json"; sources.write_text(json.dumps([{"sha256": digest, "path": str(pdf)}]))
    result = SourceLayout(pack_path=pack, sources_path=sources).inspect_layout(digest, 111, [.08, .62, .80, .84])
    assert result["complete"]
    texts = {word["text"] for word in result["words"]}
    assert {"180", "1", "2", "НМЗ-200-1", "НМЗ-200-2", "НМЗ-200-3"} <= texts
    border = next(s for s in result["segments"] if s["orientation"] == "horizontal"
                  and abs(s["native_start_points"][1] - 599.24548) < .01
                  and abs(s["native_start_points"][0] - 442.31989) < .01
                  and abs(s["native_end_points"][0] - 470.66589) < .01)
    assert border["start"][1] == pytest.approx(599.24548 / result["page_size_points"][1])
