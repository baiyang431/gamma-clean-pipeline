"""Validate rules, clean CSV records, and publish reproducible artifacts."""

import codecs
import csv
import io
import json
import re
import tempfile
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import __version__


class CleanError(Exception):
    """An expected input, schema, or quality error."""

    def __init__(self, message, exit_code=2):
        super().__init__(message)
        self.exit_code = exit_code


def normalize(value):
    return unicodedata.normalize("NFC", value).strip()


def json_bytes(value):
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return (text + "\n").encode("utf-8")


def convert(value, rule):
    """Return a canonical string or raise ValueError with a stable reason."""
    kind = rule["type"]
    if kind == "integer":
        if not re.fullmatch(r"[+-]?[0-9]+", value):
            raise ValueError("invalid_integer")
        try:
            value = str(int(value))
        except ValueError:
            raise ValueError("invalid_integer") from None
        number = Decimal(value)
    elif kind == "number":
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value):
            raise ValueError("invalid_number")
        number = Decimal(value)
        value = format(number, "f")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        if number == 0:
            value = "0"
    elif kind == "date":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("invalid_date")
        try:
            value = date.fromisoformat(value).isoformat()
        except ValueError:
            raise ValueError("invalid_date") from None
    if kind in ("integer", "number"):
        if "min" in rule and number < Decimal(str(rule["min"])):
            raise ValueError("below_min")
        if "max" in rule and number > Decimal(str(rule["max"])):
            raise ValueError("above_max")
    if "choices" in rule and value not in rule["choices"]:
        raise ValueError("not_in_choices")
    return value


def load_schema(raw):
    try:
        schema = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise CleanError(f"Invalid schema JSON: {exc}") from exc
    allowed = {"version", "columns", "dedupe_key", "missing_tokens"}
    if not isinstance(schema, dict) or set(schema) - allowed:
        raise CleanError("Schema must be an object with only supported keys")
    if type(schema.get("version")) is not int or schema["version"] != 1:
        raise CleanError("Schema version must be integer 1")
    columns = schema.get("columns")
    if not isinstance(columns, list) or not columns:
        raise CleanError("Schema columns must be a nonempty list")
    tokens = schema.setdefault("missing_tokens", ["", "NA", "N/A", "NULL", "null"])
    if (
        not isinstance(tokens, list)
        or not all(isinstance(token, str) for token in tokens)
        or "" not in tokens
    ):
        raise CleanError("missing_tokens must be a string list containing empty string")
    tokens = [normalize(token) for token in tokens]
    schema["missing_tokens"] = tokens
    names = []
    for rule in columns:
        allowed = {"name", "type", "required", "default", "min", "max", "choices"}
        if not isinstance(rule, dict) or set(rule) - allowed:
            raise CleanError("Column rule contains unsupported keys")
        name = rule.get("name")
        if (
            not isinstance(name, str)
            or not name
            or name.strip() != name
            or name in names
        ):
            raise CleanError("Column names must be nonempty, trimmed, and unique")
        names.append(name)
        if rule.get("type") not in ("string", "integer", "number", "date"):
            raise CleanError(f"Unsupported type for {name}")
        if type(rule.setdefault("required", True)) is not bool:
            raise CleanError(f"required must be boolean: {name}")
        for bound in ("min", "max"):
            if bound in rule:
                value = rule[bound]
                if (
                    rule["type"] not in ("integer", "number")
                    or type(value) not in (int, float)
                    or not Decimal(str(value)).is_finite()
                ):
                    raise CleanError(f"Invalid numeric bound: {name}.{bound}")
        if "min" in rule and "max" in rule and rule["min"] > rule["max"]:
            raise CleanError(f"min exceeds max: {name}")
        if "choices" in rule:
            choices = rule["choices"]
            if (
                rule["type"] != "string"
                or not isinstance(choices, list)
                or not choices
                or not all(isinstance(choice, str) for choice in choices)
            ):
                raise CleanError(f"choices must be a nonempty string list: {name}")
            rule["choices"] = [normalize(choice) for choice in choices]
        if "default" in rule:
            value = rule["default"]
            if rule["required"] or not isinstance(value, str):
                raise CleanError(f"default needs an optional string value: {name}")
            value = normalize(value)
            if value in tokens:
                raise CleanError(f"default must not be a missing token: {name}")
            try:
                rule["default"] = convert(value, rule)
            except (ValueError, InvalidOperation) as exc:
                raise CleanError(f"Invalid default for {name}: {exc}") from exc
    keys = schema.setdefault("dedupe_key", names.copy())
    if (
        not isinstance(keys, list)
        or not keys
        or not all(isinstance(key, str) and key in names for key in keys)
        or len(set(keys)) != len(keys)
    ):
        raise CleanError("dedupe_key must contain unique existing column names")
    return schema


def clean_row(row, columns, indices, missing_tokens):
    """Clean one record and collect field errors without stopping the file."""
    cleaned = []
    reasons = []
    filled_count = 0
    for rule, index in zip(columns, indices):
        value = normalize(row[index])
        if value in missing_tokens:
            if "default" in rule:
                value = rule["default"]
                filled_count += 1
            elif rule["required"]:
                reasons.append(f"{rule['name']}:missing_required")
            else:
                value = ""
        else:
            try:
                value = convert(value, rule)
            except (ValueError, InvalidOperation) as exc:
                reasons.append(f"{rule['name']}:{exc}")
        cleaned.append(value)
    return cleaned, reasons, filled_count


def serialize_results(names, rows, rejected):
    """Encode clean CSV and rejected records without changing raw field values."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(names)
    writer.writerows(rows)
    clean = output.getvalue().encode("utf-8")
    rejects = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in rejected
    ).encode("utf-8")
    return clean, rejects


def clean_data(raw, schema, encoding="utf-8-sig"):
    try:
        codec = codecs.lookup(encoding).name
        text = raw.decode(encoding, errors="strict")
    except (LookupError, UnicodeError) as exc:
        raise CleanError(f"Cannot decode input with {encoding}: {exc}") from exc
    if "\x00" in text:
        raise CleanError("Input contains NUL characters; check encoding or file type")
    csv.field_size_limit(1_000_000)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    columns = schema["columns"]
    names = [rule["name"] for rule in columns]
    clean_rows = []
    rejected = []
    seen = set()
    invalid_count = duplicate_count = filled_count = input_count = 0
    try:
        header = next(reader, None)
        if header is None or len(header) != len(names) or set(header) != set(names):
            raise CleanError("CSV header must contain each schema column exactly once")
        indices = [header.index(name) for name in names]
        key_indices = [names.index(name) for name in schema["dedupe_key"]]
        for record, row in enumerate(reader, start=2):
            input_count += 1
            if len(row) != len(header):
                raise CleanError(
                    f"CSV record {record}: expected {len(header)} cells, got {len(row)}"
                )
            cleaned, reasons, fills = clean_row(
                row, columns, indices, schema["missing_tokens"]
            )
            if reasons:
                invalid_count += 1
            else:
                key = tuple(cleaned[i] for i in key_indices)
                if key in seen:
                    duplicate_count += 1
                    reasons = ["duplicate"]
                else:
                    seen.add(key)
                    clean_rows.append(cleaned)
                    filled_count += fills
            if reasons:
                rejected.append({"record": record, "values": row, "reasons": reasons})
    except csv.Error as exc:
        raise CleanError(
            f"Malformed CSV near physical line {reader.line_num}: {exc}"
        ) from exc
    clean, rejects = serialize_results(names, clean_rows, rejected)
    report = {
        "tool_version": __version__,
        "schema_version": schema["version"],
        "encoding": codec,
        "input_rows": input_count,
        "output_rows": len(clean_rows),
        "invalid_rows": invalid_count,
        "duplicate_rows": duplicate_count,
        "rejected_rows": len(rejected),
        "filled_cells_in_output": filled_count,
        "dedupe_key": schema["dedupe_key"],
        "dedupe_policy": "first_valid_record",
    }
    return clean, rejects, report


def run(input_path, schema_path, output_dir, encoding="utf-8-sig", strict=False):
    """Publish a new result directory only after input and rules pass validation."""
    input_path = Path(input_path)
    schema_path = Path(schema_path)
    output_dir = Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise CleanError(f"Output directory already exists: {output_dir}", 3)
    schema = load_schema(schema_path.read_bytes())
    clean, rejected, report = clean_data(input_path.read_bytes(), schema, encoding)
    if strict and report["rejected_rows"]:
        raise CleanError(
            f"Strict mode: {report['rejected_rows']} rejected records; "
            "no output published",
            1,
        )
    report["strict"] = strict
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    # Write all files before exposing the result directory.
    with tempfile.TemporaryDirectory(
        prefix=".gamma-clean-", dir=output_dir.parent
    ) as directory:
        staging = Path(directory)
        (staging / "clean.csv").write_bytes(clean)
        (staging / "rejected.jsonl").write_bytes(rejected)
        (staging / "report.json").write_bytes(json_bytes(report))
        staging.rename(output_dir)
    return report
