"""Bounded native PDF layout evidence for an optional read-only MCP tool.

No OCR, inferred cells, merged-cell classification, value recovery or verdicts.
Coordinates are relative to the displayed page, matching its original rotation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .consensus import canonical_json, case_sha256, load_sources, validate_pack

AXIS_TOLERANCE_POINTS = 1e-6
HARD_LIMITS = {"words": 1024, "segments": 4096, "bytes": 262144}


def _bbox(value):
    if (type(value) is not list or len(value) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
            or not (0 <= value[0] < value[2] <= 1 and 0 <= value[1] < value[3] <= 1)):
        raise ValueError("bbox must be a positive normalized rectangle")
    return list(value)


def _edges(item):
    """Only edges explicitly present in native drawing primitives."""
    kind = item[0]
    if kind == "l":
        yield item[1], item[2], "line"
    elif kind == "re":
        rect = item[1]
        points = [rect.tl, rect.tr, rect.br, rect.bl]
        for i in range(4):
            yield points[i], points[(i + 1) % 4], f"rectangle_edge_{i}"
    elif kind == "qu":
        quad = item[1]
        points = [quad.ul, quad.ur, quad.lr, quad.ll]
        for i in range(4):
            yield points[i], points[(i + 1) % 4], f"quad_edge_{i}"


def _visible_segment(start, end, box, orientation):
    axis, cross = (0, 1) if orientation == "horizontal" else (1, 0)
    if not box[cross] <= start[cross] <= box[cross + 2]:
        return None
    low = max(min(start[axis], end[axis]), box[axis])
    high = min(max(start[axis], end[axis]), box[axis + 2])
    if low >= high:
        return None
    first, last = list(start), list(end)
    first[axis], last[axis] = (low, high) if start[axis] < end[axis] else (high, low)
    return first, last


class SourceLayout:
    def __init__(self, *, pack_path, sources_path, max_words=256, max_segments=1024, max_bytes=131072):
        self.limits = {"words": max_words, "segments": max_segments, "bytes": max_bytes}
        for name, value in self.limits.items():
            minimum = 2048 if name == "bytes" else 1
            if type(value) is not int or not minimum <= value <= HARD_LIMITS[name]:
                raise ValueError(f"{name} limit must be an integer in {minimum}..{HARD_LIMITS[name]}")
        self.pack = validate_pack(json.loads(Path(pack_path).read_text(encoding="utf-8")))
        self.sources = load_sources(sources_path)
        self.allowed = {(case["source_sha256"], page) for case in self.pack["cases"] for page in case["physical_pages"]}
        if any(digest not in self.sources or page > self.sources[digest]["page_count"] for digest, page in self.allowed):
            raise ValueError("Pack source/page outside verified whitelist")
        self.snapshots = {digest: Path(source["path"]).stat() for digest, source in self.sources.items()}

    def _unchanged_sources(self):
        for digest, old in self.snapshots.items():
            new = Path(self.sources[digest]["path"]).stat()
            if (new.st_dev, new.st_ino, new.st_size, new.st_mtime_ns) != (old.st_dev, old.st_ino, old.st_size, old.st_mtime_ns):
                raise ValueError("Whitelisted source changed after SHA verification")

    def _limited(self, base, name, observed):
        x0, y0, x1, y1 = base["bbox"]
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        return {**base, "complete": False, "status": "limit_exceeded", "limit": name,
                "observed_at_least": observed,
                "instruction": "No partial words/segments were returned. Request a smaller relevant bbox; these four subregions cover the requested area. This is native layout evidence, not a cell or verdict.",
                "suggested_subregions": [[x0, y0, xm, ym], [xm, y0, x1, ym], [x0, ym, xm, y1], [xm, ym, x1, y1]]}

    def inspect_layout(self, source_sha256, page, bbox=None):
        """Return complete bounded evidence or an explicit smaller-crop response.

        Words retain their full original token and bbox if intersecting the crop.
        Segment endpoints retain the original native path extent; visible_start/
        visible_end additionally identify its geometric intersection with the crop.
        Curves and implicit path-closing edges are not reconstructed. Absence here
        cannot establish absence of every possible rendered PDF stroke.
        """
        import pymupdf
        if type(source_sha256) is not str or type(page) is not int or (source_sha256, page) not in self.allowed:
            raise ValueError("Source/page is outside this pack and verified whitelist")
        box = _bbox([0., 0., 1., 1.] if bbox is None else bbox)
        self._unchanged_sources()
        base = {"schema_version": "catalogue-native-layout/1", "pack_sha256": case_sha256(self.pack),
                "source_sha256": source_sha256, "physical_page": page, "bbox": box, "limits": dict(self.limits)}
        try:
            with pymupdf.open(self.sources[source_sha256]["path"]) as doc:
                p = doc[page - 1]
                rect, matrix = p.rect, p.rotation_matrix

                def normalized(point):
                    point = point * matrix
                    return [(point.x - rect.x0) / rect.width, (point.y - rect.y0) / rect.height]

                result = {**base, "complete": True, "status": "ok", "coordinate_frame": "displayed_page_normalized",
                          "page_size_points": [rect.width, rect.height], "page_rotation_degrees": p.rotation,
                          "word_scope": "Full native words whose bboxes intersect the crop; bboxes can extend past crop boundaries.",
                          "segment_scope": "Explicit line primitives and rectangle/quad edges only; curves, fills and implicit path closings are not reconstructed. Original and crop-intersection endpoints are distinct.",
                          "axis_tolerance_points": AXIS_TOLERANCE_POINTS, "words": [], "segments": []}
                # Bound accumulated response size without serializing an entire growing
                # result for each item. Final exact canonical byte size is checked too.
                used_bytes = len(canonical_json(result))
                for word in p.get_text("words", sort=False):
                    word_rect = pymupdf.Rect(word[:4]) * matrix
                    bounds = [(word_rect.x0 - rect.x0) / rect.width, (word_rect.y0 - rect.y0) / rect.height,
                              (word_rect.x1 - rect.x0) / rect.width, (word_rect.y1 - rect.y0) / rect.height]
                    if bounds[0] >= box[2] or bounds[2] <= box[0] or bounds[1] >= box[3] or bounds[3] <= box[1]:
                        continue
                    entry = {"text": word[4], "bbox": bounds, "native_bbox_points": list(word[:4]),
                             "native_word_id": list(word[5:8])}
                    result["words"].append(entry)
                    if len(result["words"]) > self.limits["words"]:
                        return self._limited(base, "words", len(result["words"]))
                    used_bytes += len(canonical_json(entry)) + (len(result["words"]) > 1)
                    if used_bytes > self.limits["bytes"]:
                        return self._limited(base, "bytes", used_bytes)
                for path_index, drawing in enumerate(p.get_drawings()):
                    # A fill-only path can outline a rectangle but is not a stroked
                    # vector divider. Do not turn it into a fabricated boundary.
                    if drawing.get("type") not in {"s", "fs"}:
                        continue
                    for item_index, item in enumerate(drawing["items"]):
                        for first, last, primitive in _edges(item):
                            start, end = normalized(first), normalized(last)
                            dx, dy = abs(start[0] - end[0]) * rect.width, abs(start[1] - end[1]) * rect.height
                            if dy <= AXIS_TOLERANCE_POINTS and dx > AXIS_TOLERANCE_POINTS:
                                orientation = "horizontal"
                            elif dx <= AXIS_TOLERANCE_POINTS and dy > AXIS_TOLERANCE_POINTS:
                                orientation = "vertical"
                            else:
                                continue
                            visible = _visible_segment(start, end, box, orientation)
                            if visible is None:
                                continue
                            entry = {"orientation": orientation, "start": start, "end": end,
                                     "visible_start": visible[0], "visible_end": visible[1],
                                     "native_start_points": list(first), "native_end_points": list(last),
                                     "path_index": path_index, "item_index": item_index, "primitive": primitive}
                            result["segments"].append(entry)
                            if len(result["segments"]) > self.limits["segments"]:
                                return self._limited(base, "segments", len(result["segments"]))
                            used_bytes += len(canonical_json(entry)) + (len(result["segments"]) > 1)
                            if used_bytes > self.limits["bytes"]:
                                return self._limited(base, "bytes", used_bytes)
                # Count bytes in exactly the canonical UTF-8 representation, including
                # the count field itself. No response is silently truncated.
                result["serialized_bytes"] = 0
                for _ in range(3):
                    result["serialized_bytes"] = len(canonical_json(result))
                if result["serialized_bytes"] > self.limits["bytes"]:
                    return self._limited(base, "bytes", result["serialized_bytes"])
                return result
        finally:
            self._unchanged_sources()
