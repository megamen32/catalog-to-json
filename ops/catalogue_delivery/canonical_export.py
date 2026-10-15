"""Lossless, streaming Excel and clean ZIP export of canonical-catalogue/1.

This exporter selects no facts and makes no catalogue corrections. The input JSON
is the sole data source. See ``WORKBOOK_ENCODING`` for the public readback format.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from ijson.backends import python as streaming_json
from ijson.common import ObjectBuilder
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet._writer import ALL_TEMP_FILES, WorksheetWriter


SCHEMA = "canonical-catalogue/1"
FIELDS = (
    "id", "catalog", "page", "kind", "model", "parameter", "part",
    "condition", "value", "unit", "state", "source_fact_ids", "producer_ref",
)
RAW_FIELDS = ("id", "catalog", "page", "kind")
JSON_FIELDS = tuple(field for field in FIELDS if field not in RAW_FIELDS)
HEADERS = (*FIELDS, "value_display")
DATA_SHEETS = ("Характеристики", "Чертежи", "Описание")
LONG_MARKER = "[Полное значение: Длинные значения]"
CELL_UNITS = 30_000
TEXT_ALIGNMENT = Alignment(vertical="top", wrap_text=True)
HEADER_FONT = Font(bold=True)
WORKBOOK_ENCODING = {
    "schema": "canonical-workbook/1",
    "data_sheets": list(DATA_SHEETS),
    "headers": list(HEADERS),
    "raw_fields": list(RAW_FIELDS),
    "json_fields": list(JSON_FIELDS),
    "display_only_fields": ["value_display"],
    "unresolved_sheet": {"name": "Неоднозначные", "headers": ["index", "value"]},
    "envelope_sheet": {"name": "Метаданные", "headers": ["key", "value"]},
    "continuation_sheet": {
        "name": "Длинные значения",
        "headers": ["sheet", "row", "record_id", "field", "chunk_index", "chunk_count", "chunk"],
        "marker": LONG_MARKER,
        "row_numbering": "Excel 1-based including header",
        "chunk_numbering": "0-based",
        "maximum_utf16_units": CELL_UNITS,
    },
}


def dumps(value):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if any(not _xml_character(char) for char in text):
        return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return text


def _xml_character(char):
    code = ord(char)
    return code in (9, 10, 13) or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _units(value):
    return len(value.encode("utf-16-le")) // 2


def _chunks(value):
    """Split without cutting a Unicode character or exceeding Excel's limit."""
    chunk, size = [], 0
    for char in value:
        width = 2 if ord(char) > 0xFFFF else 1
        if size + width > CELL_UNITS:
            yield "".join(chunk)
            chunk, size = [], 0
        chunk.append(char)
        size += width
    if chunk:
        yield "".join(chunk)


def _envelope(path):
    """Read every top-level field except records without materializing records."""
    builder = ObjectBuilder()
    found_records = False
    with Path(path).open("rb") as stream:
        for prefix, event, value in streaming_json.parse(stream, use_float=True):
            if prefix == "records" and not found_records:
                if event != "start_array":
                    raise ValueError("Canonical records must be an array")
                found_records = True
            if prefix == "records" or prefix.startswith("records."):
                continue
            if prefix == "" and event == "map_key" and value == "records":
                continue
            builder.event(event, value)
    if not found_records or not isinstance(builder.value, dict) or builder.value.get("schema") != SCHEMA:
        raise ValueError(f"Expected {SCHEMA} JSON object")
    return builder.value


def sheet_for(kind):
    if kind in {"model_parameter", "group_parameter", "model_designation"}:
        return DATA_SHEETS[0]
    return DATA_SHEETS[1] if kind == "figure" else DATA_SHEETS[2]


def _text_cell(sheet, value):
    # Never let openpyxl turn a source string starting '=' into a formula.
    cell = WriteOnlyCell(sheet, value=value)
    if isinstance(value, str):
        cell.data_type = "s"
        cell.alignment = TEXT_ALIGNMENT
    return cell


def export(canonical_json_path, output_dir):
    """Create exact input JSON, lossless workbook, manifest, README and clean ZIP.

    Returns absolute paths. Existing deliverables are never overwritten. Source
    records are streamed; the workbook uses openpyxl write-only sheets.
    """
    source = Path(canonical_json_path).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = {name: output / name for name in (
        "catalogue.json", "catalogue.xlsx", "README.txt", "manifest.json", "catalogues-unified.zip",
    )}
    for path in paths.values():
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing deliverable: {path}")
    shutil.copyfile(source, paths["catalogue.json"])
    envelope = _envelope(paths["catalogue.json"])
    unresolved = envelope.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("Canonical unresolved must be a list")
    producers = envelope.get("producers")
    if not isinstance(producers, dict):
        raise ValueError("Canonical producers must be an object")
    book = Workbook(write_only=True)
    sheets = {}
    row_numbers = {}
    for name, headers in [
        *((name, HEADERS) for name in DATA_SHEETS),
        ("Неоднозначные", ("index", "value")),
        ("Метаданные", ("key", "value")),
        ("Длинные значения", tuple(WORKBOOK_ENCODING["continuation_sheet"]["headers"])),
    ]:
        sheet = book.create_sheet(name)
        sheet.freeze_panes = "A2"
        if name in DATA_SHEETS:
            sheet.column_dimensions["A"].width = 24
            for column in ("E", "F", "G", "H", "I", "N"):
                sheet.column_dimensions[column].width = 36
        # openpyxl defaults worksheet scratch files to system /tmp. Keep all
        # transient catalogue data inside this project output directory instead.
        scratch = tempfile.NamedTemporaryFile(prefix=".xlsx-", suffix=".xml", dir=output, delete=False)
        scratch.close()
        ALL_TEMP_FILES.append(scratch.name)
        sheet._writer = WorksheetWriter(sheet, out=scratch.name)
        sheet._writer.write_top()
        cells = [_text_cell(sheet, header) for header in headers]
        for cell in cells:
            cell.font = HEADER_FONT
        sheet.append(cells)
        sheets[name], row_numbers[name] = sheet, 1
    continuation_count = 0

    def append(name, record_id, values):
        nonlocal continuation_count
        row_numbers[name] += 1
        if row_numbers[name] > 1_048_576:
            raise ValueError(f"Excel row limit exceeded: {name}")
        cells = []
        for field, value in values:
            if isinstance(value, str) and _units(value) > CELL_UNITS:
                parts = list(_chunks(value))
                for index, part in enumerate(parts):
                    continuation_count += 1
                    if continuation_count >= 1_048_576:
                        raise ValueError("Excel continuation row limit exceeded")
                    long_sheet = sheets["Длинные значения"]
                    long_sheet.append([_text_cell(long_sheet, item) for item in (
                        name, row_numbers[name], record_id, field, index, len(parts), part,
                    )])
                value = LONG_MARKER
            cells.append(_text_cell(sheets[name], value))
        sheets[name].append(cells)

    ids, counts, kinds = set(), Counter(), Counter()
    with paths["catalogue.json"].open("rb") as stream:
        for record in streaming_json.items(stream, "records.item", use_float=True):
            if not isinstance(record, dict) or set(record) != set(FIELDS):
                raise ValueError("Record fields must exactly match the canonical record contract")
            for field in ("id", "catalog", "kind"):
                if not isinstance(record[field], str) or not record[field]:
                    raise ValueError(f"{field} must be a nonempty string")
            if type(record["page"]) is not int or record["page"] < 1:
                raise ValueError("page must be a positive integer")
            if record["id"] in ids:
                raise ValueError(f"Duplicate canonical id: {record['id']}")
            ids.add(record["id"])
            if record["producer_ref"] not in producers:
                raise ValueError(f"Unknown producer_ref: {record['producer_ref']}")
            if not isinstance(record["source_fact_ids"], list) or not record["source_fact_ids"]:
                raise ValueError("Every record must reference original source_fact_ids")
            values = [(field, record[field] if field in RAW_FIELDS else dumps(record[field]))
                      for field in FIELDS]
            display = record["value"] if isinstance(record["value"], str) else dumps(record["value"])
            # The exact typed value above is authoritative. Do not duplicate large
            # source text into a second set of continuation rows.
            if any(not _xml_character(char) for char in display) or _units(display) > CELL_UNITS:
                display = "Полное значение — в колонке value"
            values.append(("value_display", display))
            append(sheet_for(record["kind"]), record["id"], values)
            counts[record["catalog"]] += 1
            kinds[record["kind"]] += 1
    for index, item in enumerate(unresolved):
        append("Неоднозначные", f"unresolved:{index}", (("index", index), ("value", dumps(item))))
    for key, value in envelope.items():
        if key != "unresolved":
            append("Метаданные", key, (("key", key), ("value", dumps(value))))
    book.save(paths["catalogue.xlsx"])
    review_scope = envelope.get("metadata", {}).get("review_scope", "не указан")
    readme = (
        "Сведённые каталоги Никиты и Олега\n\n"
        "Сведённые каталоги Форэнерго.\n"
        "catalogue.xlsx — просмотр и фильтрация; начинайте с листа «Характеристики».\n"
        "catalogue.json — те же данные для программной обработки.\n"
        "Чертежи и описание сохранены на отдельных листах Excel.\n"
        "В обоих файлах сохранены источник, физическая страница и фактический производитель.\n"
        "История решений и отклонённые альтернативы в этот архив не входят.\n\n"
        "Перепроверялось сведение двух сохранённых оцифровок. Новая независимая\n"
        "проверка всех исходных страниц PDF не выполнялась. Неизвестные и\n"
        "противоречивые значения помечены явно и не равны нулю.\n\n"
        f"Записей: {len(ids)}. Фактов в сохранённом исходном списке неоднозначностей: {len(unresolved)}.\n"
        "Они сохранены отдельно и не объявлены проверенными характеристиками.\n"
        "Неизвестные значения и ограничения интерпретации отдельных записей дополнительно\n"
        "отмечены их полями state и metadata; этот список не является оценкой точности.\n"
        f"Объём проверки: {dumps(review_scope)}\n\n"
        "Excel: nullable/составные поля записаны как JSON, чтобы различать null, пустую\n"
        "строку, прочерк, ноль и тип значения. value_display — только удобное отображение.\n"
        "Слишком длинные значения сохранены полностью на листе «Длинные значения»;\n"
        "сборка по sheet,row,field и chunk_index. Точная схема записана в manifest.json.\n"
        "Формулы из исходного текста не исполняются.\n"
    )
    paths["README.txt"].write_text(readme, encoding="utf-8")
    manifest = {
        "schema": "canonical-delivery/1", "canonical_schema": SCHEMA,
        "record_count": len(ids), "unresolved_count": len(unresolved),
        "records_by_catalog": dict(sorted(counts.items())),
        "records_by_kind": dict(sorted(kinds.items())),
        "continuation_chunks": continuation_count,
        "workbook_encoding": WORKBOOK_ENCODING,
        "files": {name: {"sha256": sha256(paths[name]), "bytes": paths[name].stat().st_size}
                  for name in ("catalogue.json", "catalogue.xlsx", "README.txt")},
    }
    paths["manifest.json"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(paths["catalogues-unified.zip"], "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as archive:
        for name in ("catalogue.json", "catalogue.xlsx", "README.txt", "manifest.json"):
            archive.write(paths[name], arcname=name)
    return {**{name: str(path) for name, path in paths.items()}, "manifest": manifest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = export(args.input, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "manifest"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
