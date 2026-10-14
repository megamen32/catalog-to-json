"""Lossless inventories and literal atoms; this module never merges observations.

``raw`` is authoritative. Atoms are views with JSON pointers, not another product
schema. Missing/null/empty, object and array order, Unicode and numeric types are
kept. Original byte streams are retained for byte-exact restoration. Split Oleg
records reconstruct groups/models; draft key layouts preserve the position and
presence of the split ``characteristics`` member, not its populated values.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from functools import cached_property
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterator
from zipfile import ZipFile

SOURCE_CATALOGS = {
    "c8cb0bf124607d1f5f9de18fc48d467033262b9f43c205a582b01521e5aaab4e": "armature",
    "4542d9a0146122e5d2dc4d8d73895baa2bb4eb1349d3b439076efe5c2af4a6ee": "innovations",
    "7bd35242d89d74193cf46986b3a0692c982e1629c855ce558d0445c0f0e41d35": "isolators",
    "25b5c21bcc88bfc7c40d707a5907bbed77ba115195fa174e6e1b568d2a5f8e49": "small",
    "300f06a65b18b1656c589e85c94eb29486aaf6d16a5c10b0544dbdc51666adc2": "opn",
}
TABLES = ("product_groups", "products", "characteristics", "group_characteristics", "uncertainties")
_MISSING = object()


class FormatError(ValueError):
    """A broken source invariant, never an inferred correction."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FormatError(f"Duplicate JSON member {key!r}; refusing lossy parsing")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise FormatError(f"Not a finite JSON number: {value}")


def parse_json(data: bytes | str) -> Any:
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=_nonfinite)


def json_type(value: Any = _MISSING) -> str:
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise FormatError(f"Not a JSON value: {type(value).__name__}")


def exact_json_equal(left: Any, right: Any) -> bool:
    """Stricter than Python ==: bool/int/float, -0.0 and member order differ."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return list(left) == list(right) and all(exact_json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(exact_json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, float):
        return left.hex() == right.hex()
    return left == right


def pointer(*parts: Any) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)



def resolve_pointer(raw: Any, ptr: str) -> Any:
    """Resolve an RFC 6901 pointer against a retained decoded document."""
    if ptr == "":
        return raw
    if not ptr.startswith("/"):
        raise FormatError(f"Not an absolute JSON pointer: {ptr!r}")
    value = raw
    for token in ptr[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isdecimal() or str(int(token)) != token:
                raise FormatError(f"Not a canonical array index: {token!r}")
            value = value[int(token)]
        else:
            value = value[token]
    return value


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise FormatError(f"Unsafe payload path: {name!r}")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise FormatError(f"Payload escapes root: {name!r}")
    return path


@dataclass
class RawDocument:
    path: str
    raw_bytes: bytes
    raw: Any
    format: str = "json"

    @cached_property
    def sha256(self) -> str:
        return sha256(self.raw_bytes).hexdigest()


def read_document(path: str | Path, *, jsonl: bool = False) -> RawDocument:
    path = Path(path)
    data = path.read_bytes()
    raw = [parse_json(line) for line in BytesIO(data) if line.strip()] if jsonl else parse_json(data)
    return RawDocument(str(path), data, raw, "jsonl" if jsonl else "json")


def restore_raw(document: RawDocument, reconstructed: Any = _MISSING) -> bytes:
    """Return original bytes only if the supplied/current tree is still exact."""
    current = document.raw if reconstructed is _MISSING else reconstructed
    original = ([parse_json(line) for line in BytesIO(document.raw_bytes) if line.strip()]
                if document.format == "jsonl" else parse_json(document.raw_bytes))
    if not exact_json_equal(original, current):
        raise FormatError(f"Lossy restoration of {document.path}")
    return document.raw_bytes


def verify_payload_manifest(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    manifest = read_document(root / "manifest.json").raw
    entries = manifest["files"]
    if isinstance(entries, dict):
        entries = [dict(meta, path=name) for name, meta in entries.items()]
    names: set[str] = set()
    total = 0
    for entry in entries:
        name = entry["path"]
        if name in names:
            raise FormatError(f"Duplicate manifest payload {name}")
        names.add(name)
        path = _contained(root, name)
        if not path.is_file() or path.stat().st_size != entry["bytes"] or _hash_file(path) != entry["sha256"]:
            raise FormatError(f"Payload hash/size mismatch: {name}")
        total += entry["bytes"]
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    if actual != names | {"manifest.json"}:
        raise FormatError(f"Manifest inventory mismatch: {sorted(actual ^ (names | {'manifest.json'}))}")
    return {"passed": True, "files": len(names), "bytes": total,
            "manifest_sha256": _hash_file(root / "manifest.json")}


def _evidence_pages(raw: Any) -> list[int]:
    pages: set[int] = set()
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if type(value.get("page")) is int:
                pages.add(value["page"])
            for key in ("evidence", "row_evidence", "header_path"):
                if key in value:
                    visit(value[key])
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(raw)
    return sorted(pages)


def _atom(base: dict[str, Any], kind: str, record_id: str, ptr: str, raw: Any,
          value: Any = _MISSING, **metadata: Any) -> dict[str, Any]:
    return {**base, "kind": kind, "record_id": record_id, "pointer": ptr,
            "raw": raw, "raw_value": None if value is _MISSING else value,
            "raw_value_type": json_type(value), "presence": value is not _MISSING,
            **metadata}


class OlegExport:
    def __init__(self, root: str | Path, *, verify_manifest: bool = True):
        self.root = Path(root)
        self.manifest_verification = verify_payload_manifest(self.root) if verify_manifest else {"passed": None}
        self.documents = {name: read_document(self.root / name) for name in ("manifest.json", "sources.json", "coverage.json")}
        self.sources = self._unique(self.documents["sources.json"].raw["sources"], "sources")
        self.coverage = self.documents["coverage.json"].raw
        self.windows = self._unique(self.coverage["windows"], "windows")
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.by_id: dict[str, dict[str, Any]] = {}
        self.locations: dict[str, tuple[str, int]] = {}
        self._by_window: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self._children: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for name in TABLES:
            document = read_document(self.root / f"{name}.jsonl", jsonl=True)
            self.documents[f"{name}.jsonl"] = document
            self.tables[name] = document.raw
            ids = self._unique(document.raw, name)
            for line, record in enumerate(document.raw, 1):
                rid = record["id"]
                # ID identity includes table; characteristics/group-characteristics
                # share a C prefix but all real exported observation IDs are unique.
                if rid in self.by_id:
                    raise FormatError(f"Duplicate observation ID across tables: {rid}")
                self.by_id[rid] = record
                self.locations[rid] = (f"{name}.jsonl", line)
                self._by_window[name, record["window_id"]].append(record)
                if name in ("characteristics", "group_characteristics"):
                    owner = record["product_id"] if name == "characteristics" else record["group_id"]
                    self._children[name, owner].append(record)
            del ids
        self._observations = self._unique(self.coverage["window_observations"], "window observations", "window_id")
        self.validate_foreign_keys()

    @staticmethod
    def _unique(records: list[dict[str, Any]], kind: str, field: str = "id") -> dict[str, Any]:
        result = {}
        for record in records:
            key = record[field]
            if key in result:
                raise FormatError(f"Duplicate {kind} {field}: {key}")
            result[key] = record
        return result

    def validate_foreign_keys(self) -> None:
        for sid, source in self.sources.items():
            if source["sha256"] not in SOURCE_CATALOGS:
                raise FormatError(f"Unmapped source SHA: {sid}")
        for wid, window in self.windows.items():
            if window["source_id"] not in self.sources or window.get("window_id", wid) != wid:
                raise FormatError(f"Bad window/source identity: {wid}")
            source = self.sources[window["source_id"]]
            if not 1 <= window["start_page"] <= window["end_page"] <= source["page_count"]:
                raise FormatError(f"Bad physical window range: {wid}")
            obs = self._observations.get(wid)
            if obs is None or obs["source_id"] != window["source_id"]:
                raise FormatError(f"Missing/wrong window observation: {wid}")
        if set(self._observations) != set(self.windows):
            raise FormatError("Window observation inventory differs")
        owners = {"product_group": "product_groups", "product": "products",
                  "characteristics": "characteristics", "group_characteristics": "group_characteristics"}
        for table, records in self.tables.items():
            allowed = {r["id"] for r in self.tables["product_groups"]}
            for rec in records:
                wid, sid = rec["window_id"], rec["source_id"]
                for key in ("native_index", "characteristic_index"):
                    if key in rec and (type(rec[key]) is not int or rec[key] < 0):
                        raise FormatError(f"Invalid ordered index: {rec['id']}/{key}")
                if wid not in self.windows or self.windows[wid]["source_id"] != sid:
                    raise FormatError(f"Bad window/source FK: {rec['id']}")
                if "group_id" in rec:
                    group = self.by_id.get(rec["group_id"])
                    if rec["group_id"] not in allowed or group["window_id"] != wid or group["source_id"] != sid:
                        raise FormatError(f"Bad group FK: {rec['id']}")
                if table == "characteristics":
                    model = self.by_id.get(rec["product_id"])
                    if model is None or self.locations[model["id"]][0] != "products.jsonl" or any(model[k] != rec[k] for k in ("source_id", "window_id", "group_id")):
                        raise FormatError(f"Bad product FK: {rec['id']}")
                if table in ("characteristics", "group_characteristics"):
                    if rec["raw_value_type"] != json_type(rec["raw"].get("raw_value", _MISSING)):
                        raise FormatError(f"Bad raw_value_type: {rec['id']}")
                if table == "uncertainties":
                    if rec["level"] == "window":
                        if rec["owner_id"] is not None:
                            raise FormatError(f"Window uncertainty has owner: {rec['id']}")
                        raw_owner = self._observations[wid]["raw"]
                    else:
                        parent = self.by_id.get(rec["owner_id"])
                        expected = owners.get(rec["level"])
                        if parent is None or self.locations[parent["id"]][0] != f"{expected}.jsonl" or parent["source_id"] != sid or parent["window_id"] != wid:
                            raise FormatError(f"Bad uncertainty FK: {rec['id']}")
                        raw_owner = parent["raw"]
                    if rec["field"] not in raw_owner or not exact_json_equal(raw_owner[rec["field"]], rec["raw"]):
                        raise FormatError(f"Uncertainty index differs from owner: {rec['id']}")
        actual_pages = {}
        for item in self.coverage["pages"]:
            key = (item["source_id"], item["page"])
            if key in actual_pages:
                raise FormatError(f"Duplicate coverage page: {key}")
            actual_pages[key] = item
            expected_windows = {wid for wid, w in self.windows.items() if w["source_id"] == key[0] and w["start_page"] <= key[1] <= w["end_page"]}
            if not expected_windows or set(item["window_ids"]) != expected_windows:
                raise FormatError(f"Coverage page/window mismatch: {key}")
        expected_pages = {(sid, page) for sid, source in self.sources.items() for page in range(1, source["page_count"] + 1)}
        if set(actual_pages) != expected_pages:
            raise FormatError("Source physical pages and coverage index differ")

    def _owner(self, record: dict[str, Any], native: dict[str, Any], table: str) -> dict[str, Any]:
        raw = record["raw"]
        if list(raw) != [key for key in native if key != "characteristics"]:
            raise FormatError(f"Owner field presence/order mismatch: {record['id']}")
        children = sorted(self._children[table, record["id"]], key=lambda r: r["characteristic_index"])
        if [r["characteristic_index"] for r in children] != list(range(len(children))):
            raise FormatError(f"Characteristic index gap/duplicate: {record['id']}")
        if "characteristics" not in native or native["characteristics"] is None:
            if children:
                raise FormatError(f"Children for absent/null characteristics: {record['id']}")
            return {key: (None if key == "characteristics" else raw[key]) for key in native}
        if not isinstance(native["characteristics"], list):
            raise FormatError(f"Characteristics is not array/null: {record['id']}")
        return {key: ([r["raw"] for r in children] if key == "characteristics" else raw[key]) for key in native}

    def reconstruct_window(self, window_id: str) -> dict[str, Any]:
        window = self.windows[window_id]
        document = read_document(_contained(self.root, window["draft_path"]))
        if document.sha256 != window["draft_sha256"]:
            raise FormatError(f"Draft hash differs: {window_id}")
        native = document.raw
        if native["source_sha256"] != self.sources[window["source_id"]]["sha256"]:
            raise FormatError(f"Draft source hash differs: {window_id}")
        rebuilt: dict[str, Any] = {}
        observations = self._observations[window_id]["raw"]
        for field, table, children in (("products", "product_groups", "group_characteristics"), ("models", "products", "characteristics")):
            records = sorted(self._by_window[table, window_id], key=lambda r: r["native_index"])
            if [r["native_index"] for r in records] != list(range(len(records))):
                raise FormatError(f"Native index gap/duplicate: {window_id}/{table}")
            expected = native.get(field, _MISSING)
            if expected is _MISSING or expected is None:
                if records:
                    raise FormatError(f"Records for missing/null native collection: {window_id}/{field}")
                if expected is None:
                    rebuilt[field] = None
            else:
                if not isinstance(expected, list) or len(records) != len(expected):
                    raise FormatError(f"Native owner count differs: {window_id}/{field}")
                rebuilt[field] = [self._owner(rec, layout, children) for rec, layout in zip(records, expected)]
        for field in observations:
            if field not in native:
                raise FormatError(f"Window observation field missing from draft: {window_id}/{field}")
        result = {key: rebuilt[key] if key in rebuilt else observations[key] if key in observations else value
                  for key, value in native.items()}
        if not exact_json_equal(native, result):
            raise FormatError(f"Native reconstruction differs (type/value/order/presence): {window_id}")
        return result

    def restore_window_bytes(self, window_id: str) -> bytes:
        document = read_document(_contained(self.root, self.windows[window_id]["draft_path"]))
        return restore_raw(document, self.reconstruct_window(window_id))

    def iter_atoms(self) -> Iterator[dict[str, Any]]:
        for table in TABLES:
            for rec in self.tables[table]:
                source = self.sources[rec["source_id"]]
                raw = rec["raw"]
                group = self.by_id.get(rec.get("group_id", rec["id"] if table == "product_groups" else ""))
                model = rec if table == "products" else self.by_id.get(rec.get("product_id", ""))
                owner = model if model is not None else group
                native_ptr = (pointer("products", rec["native_index"]) if table == "product_groups" else
                              pointer("models", rec["native_index"]) if table == "products" else
                              pointer("models" if table == "characteristics" else "products", owner["native_index"], "characteristics", rec["characteristic_index"]) if table in ("characteristics", "group_characteristics") else None)
                filename, line = self.locations[rec["id"]]
                base = {"side": "oleg", "source_sha256": source["sha256"], "catalog": SOURCE_CATALOGS[source["sha256"]],
                        "physical_pages": _evidence_pages(raw), "owner_ids": {k: rec[k] for k in ("source_id", "window_id", "group_id", "product_id") if k in rec},
                        "provenance": {"file": filename, "record_number": line, "file_sha256": self.documents[filename].sha256,
                                       "window_id": rec["window_id"], "draft_path": self.windows[rec["window_id"]]["draft_path"],
                                       "draft_sha256": self.windows[rec["window_id"]]["draft_sha256"], "native_pointer": native_ptr,
                                       "extraction_status": self.windows[rec["window_id"]]["status"], "source_verified": False}}
                metadata = {"designation": model["raw"].get("designation") if model else None,
                            "model_raw": model["raw"] if model else None, "group_title": group["raw"].get("title") if group else None}
                if table in ("characteristics", "group_characteristics"):
                    metadata.update({k: raw[k] for k in ("name", "unit", "condition", "scope", "scope_evidence", "header_path", "value_state", "origin", "row_evidence", "evidence") if k in raw})
                    yield _atom(base, "model_characteristic" if table == "characteristics" else "group_characteristic", rec["id"], pointer(line - 1, "raw"), raw, raw.get("raw_value", _MISSING), **metadata)
                else:
                    yield _atom(base, {"products": "model", "product_groups": "group", "uncertainties": "uncertainty"}[table], rec["id"], pointer(line - 1, "raw"), raw, raw, **metadata)
        for index, obs in enumerate(self.coverage["window_observations"]):
            source = self.sources[obs["source_id"]]
            yield _atom({"side": "oleg", "catalog": SOURCE_CATALOGS[source["sha256"]], "source_sha256": source["sha256"],
                         "physical_pages": _evidence_pages(obs["raw"]), "owner_ids": {"window_id": obs["window_id"]},
                         "provenance": {"file": "coverage.json", "file_sha256": self.documents["coverage.json"].sha256}},
                        "window_observation", obs["window_id"], pointer("window_observations", index, "raw"), obs["raw"], obs["raw"])

    def inventory(self) -> dict[str, Any]:
        manifest = self.documents["manifest.json"].raw
        counts = {name: len(records) for name, records in self.tables.items()}
        if counts != manifest["record_counts"]:
            raise FormatError("Manifest record counts differ")
        for document in self.documents.values():
            restore_raw(document)
        checked = 0
        for wid, window in self.windows.items():
            restored = self.restore_window_bytes(wid)
            if sha256(restored).hexdigest() != window["draft_sha256"]:
                raise FormatError(f"Byte restoration differs: {wid}")
            expected = {name: len(self._by_window[name, wid]) for name in TABLES if name != "uncertainties"}
            if expected != window["counts"]:
                raise FormatError(f"Window counts differ: {wid}")
            checked += 1
        value_types = Counter(rec["raw_value_type"] for name in ("characteristics", "group_characteristics") for rec in self.tables[name])
        if dict(value_types) != manifest["raw_value_types"]:
            raise FormatError("Manifest raw value types differ")
        for sid, source in self.sources.items():
            computed = {name: sum(r["source_id"] == sid for r in records) for name, records in self.tables.items()}
            computed["windows"] = sum(w["source_id"] == sid for w in self.windows.values())
            computed["reused_windows"] = sum(w["source_id"] == sid and w.get("reused") is True for w in self.windows.values())
            for key, declared in source.get("counts", {}).items():
                if key not in computed or type(declared) is not int or computed[key] != declared:
                    raise FormatError(f"Source declared count differs: {sid}/{key}")
        totals = {"accepted_windows": len(self.windows),
                  "reused_windows": sum(w.get("reused") is True for w in self.windows.values()),
                  "covered_physical_pages": len(self.coverage["pages"]), "sources": len(self.sources),
                  "total_characteristics": counts["characteristics"] + counts["group_characteristics"]}
        for key, actual in totals.items():
            for container in (manifest, self.coverage):
                if key in container and (type(container[key]) is not int or container[key] != actual):
                    raise FormatError(f"Declared total differs: {key}")
        designations = Counter((rec["source_id"], json.dumps(rec["raw"].get("designation"), ensure_ascii=False)) for rec in self.tables["products"])
        return {"manifest": self.manifest_verification, "foreign_keys": "passed", "record_counts": counts,
                "sources": {sid: {"catalog": SOURCE_CATALOGS[s["sha256"]], "sha256": s["sha256"], "page_count": s["page_count"]} for sid, s in self.sources.items()},
                "physical_pages": len(self.coverage["pages"]), "windows": len(self.windows),
                "native_roundtrip_windows_checked": checked, "native_roundtrip": "exact_types_values_order_presence_and_bytes",
                "raw_documents_roundtrip_checked": len(self.documents),
                "raw_value_types": dict(value_types), "duplicate_designation_keys": sum(n > 1 for n in designations.values()),
                "observations_on_duplicate_designation_keys": sum(n for n in designations.values() if n > 1),
                "characteristic_origins": dict(Counter(r["raw"].get("origin", "<missing>") for name in ("characteristics", "group_characteristics") for r in self.tables[name])),
                "header_path_types": dict(Counter(json_type(r["raw"].get("header_path", _MISSING)) for name in ("characteristics", "group_characteristics") for r in self.tables[name])),
                "product_record_kinds": dict(Counter(r["raw"].get("record_kind", "<missing>") for r in self.tables["products"])),
                "limitations": ["Observations are not unique SKUs; overlapping windows are retained.", "Group characteristics are not inherited by models.", "native_accepted is not source verification.", "Draft layouts/raw byte streams are required to restore split-member placement and exact formatting."]}


class OurSnapshot:
    def __init__(self, document: RawDocument, manifest_verification: dict[str, Any]):
        self.document = document
        self.raw = document.raw
        self.manifest_verification = manifest_verification
        self.sources = {cat["source"]["sha256"]: {"catalog": cat["id"], **cat["source"]} for cat in self.raw["catalogs"]}
        if len(self.sources) != len(self.raw["catalogs"]):
            raise FormatError("Duplicate snapshot source SHA")
        for sha, source in self.sources.items():
            if SOURCE_CATALOGS.get(sha) != source["catalog"]:
                raise FormatError("Snapshot source SHA/catalog mismatch")

    def iter_atoms(self) -> Iterator[dict[str, Any]]:
        for ci, catalog in enumerate(self.raw["catalogs"]):
            source = catalog["source"]
            for pi, page in enumerate(catalog["pages"]):
                if "source_sha256" in page and page["source_sha256"] != source["sha256"]:
                    raise FormatError(f"Page/catalog source SHA mismatch: {catalog['id']}/{page['pdf_page']}")
                content = page.get("content")
                if content is None:
                    continue
                prefix = ("catalogs", ci, "pages", pi, "content")
                base = {"side": "ours", "catalog": catalog["id"], "source_sha256": source["sha256"], "physical_pages": [page["pdf_page"]],
                        "owner_ids": {"catalog": catalog["id"], "pdf_page": page["pdf_page"]},
                        "provenance": {"file": self.document.path, "file_sha256": self.document.sha256,
                                       "page_pointer": pointer("catalogs", ci, "pages", pi), "status": page.get("status"),
                                       "candidate_sha256": page.get("candidate_sha256"), "producer": page.get("candidate_producer"),
                                       "source_checked_by": page.get("source_checked_by"), "source_verified": "per_page_status_only"}}
                rid = f"{catalog['id']}:{page['pdf_page']}"
                for key in ("title", "printed_page", "page_context"):
                    if key in content:
                        yield _atom(base, key, rid, pointer(*prefix, key), content[key], content[key])
                for ti, table in enumerate(content.get("tables", [])):
                    table_meta = {"table_index": ti, "table_title": table.get("title"), "table_id": table.get("id"), "table_pointer": pointer(*prefix, "tables", ti)}
                    for col_index, column in enumerate(table["columns"]):
                        yield _atom(base, "table_column", rid, pointer(*prefix, "tables", ti, "columns", col_index), column, column, **table_meta, column_index=col_index)
                    col_by_id = {col["id"]: (i, col) for i, col in enumerate(table["columns"])}
                    if len(col_by_id) != len(table["columns"]):
                        raise FormatError(f"Duplicate column IDs at {rid}/{ti}")
                    for ri, row in enumerate(table["rows"]):
                        for cell_index, cell in enumerate(row["cells"]):
                            if cell["column_id"] not in col_by_id:
                                raise FormatError(f"Unknown column at {rid}/{ti}/{ri}/{cell_index}")
                            coli, column = col_by_id[cell["column_id"]]
                            yield _atom(base, "table_cell", rid, pointer(*prefix, "tables", ti, "rows", ri, "cells", cell_index), cell, cell.get("value", _MISSING),
                                        **table_meta, row_index=ri, cell_index=cell_index, column_index=coli, column=column,
                                        name=column.get("label"), unit=column.get("unit"), qualifier=column.get("qualifier"), group_title=column.get("group"),
                                        value_state=cell.get("state"), row_pointer=pointer(*prefix, "tables", ti, "rows", ri),
                                        row_values=[c.get("value", _MISSING) if "value" in c else {"presence": False} for c in row["cells"]],
                                        column_labels=[c.get("label") for c in table["columns"]])
                for index, figure in enumerate(content.get("figures", [])):
                    for field in ("title", "description"):
                        if field in figure:
                            yield _atom(base, f"figure_{field}", rid, pointer(*prefix, "figures", index, field), figure[field], figure[field], figure_index=index, figure_raw=figure)
                    for li, label in enumerate(figure.get("labels", [])):
                        yield _atom(base, "figure_label", rid, pointer(*prefix, "figures", index, "labels", li), label, label, figure_index=index, figure_raw=figure)
                for key in ("text_blocks", "source_notes", "uncertainties"):
                    for index, value in enumerate(content.get(key, [])):
                        val = value.get("text", _MISSING) if isinstance(value, dict) else value
                        yield _atom(base, {"text_blocks": "text", "source_notes": "source_note", "uncertainties": "uncertainty"}[key], rid, pointer(*prefix, key, index), value, val)

    def inventory(self) -> dict[str, Any]:
        restore_raw(self.document)
        kinds: Counter[str] = Counter()
        for atom in self.iter_atoms():
            kinds[atom["kind"]] += 1
        pages = sum(len(c["pages"]) for c in self.raw["catalogs"])
        if pages != self.raw["page_count"]:
            raise FormatError("Snapshot declared page count differs")
        for cat in self.raw["catalogs"]:
            if [p["pdf_page"] for p in cat["pages"]] != list(range(1, cat["source"]["page_count"] + 1)):
                raise FormatError(f"Snapshot physical page inventory differs: {cat['id']}")
        page_statuses = Counter(p.get("status", "<missing>") for c in self.raw["catalogs"] for p in c["pages"])
        classifications = Counter((p.get("content") or {}).get("page_context", {}).get("kind", "<missing>") if isinstance((p.get("content") or {}).get("page_context"), dict) else "<missing>" for c in self.raw["catalogs"] for p in c["pages"])
        return {"manifest": self.manifest_verification, "pages": pages, "sources": self.sources, "atom_counts": dict(kinds),
                "page_statuses": dict(page_statuses), "page_context_kinds": dict(classifications),
                "json_roundtrip": "exact_types_values_order_presence_and_bytes", "raw_json_sha256": self.document.sha256,
                "limitations": ["Page tables are not assumed to be product offers; context/figures remain separate.", "Figure labels/descriptions remain literal; no inferred dimensional ownership or numeric casting.", "Status/producer provenance is retained, never promoted to source verification by this adapter."]}


def load_oleg_export(path: str | Path, *, verify_manifest: bool = True) -> OlegExport:
    return OlegExport(path, verify_manifest=verify_manifest)


def load_our_snapshot(path: str | Path, *, verify_manifest: bool = True) -> OurSnapshot:
    path = Path(path)
    if path.suffix.lower() != ".zip":
        return OurSnapshot(read_document(path), {"passed": None, "reason": "Standalone JSON has no supplied payload manifest"})
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise FormatError("Duplicate ZIP members")
        manifest = parse_json(archive.read("manifest.json"))
        if verify_manifest:
            if set(names) != set(manifest["files"]) | {"manifest.json"}:
                raise FormatError("ZIP payload/manifest inventory differs")
            for name, expected in manifest["files"].items():
                data = archive.read(name)  # also checks CRC; one member at a time
                if len(data) != expected["bytes"] or sha256(data).hexdigest() != expected["sha256"]:
                    raise FormatError(f"ZIP payload hash/size mismatch: {name}")
        name = "all-catalogues-980-pages.json"
        data = archive.read(name)
        document = RawDocument(f"{path}!/{name}", data, parse_json(data))
    return OurSnapshot(document, {"passed": True if verify_manifest else None, "files": len(manifest["files"]),
                                  "zip_sha256": _hash_file(path), "manifest": manifest})


def inventory_inputs(oleg_path: str | Path, our_path: str | Path) -> dict[str, Any]:
    oleg = load_oleg_export(oleg_path)
    first = oleg.inventory()
    # Keep the two measured jobs sequential and avoid retaining both decoded sets.
    del oleg
    ours = load_our_snapshot(our_path)
    second = ours.inventory()
    return {"schema_version": "lossless-format-inventory/1", "oleg": first, "ours": second,
            "final_format_selected": False, "semantic_equivalence_claimed": False}
