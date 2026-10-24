"""Validate rules, clean CSV records, and publish reproducible artifacts."""

import codecs
import csv
import hashlib
import io
import json
import re
import shutil
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
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CleanError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise CleanError(f"Non-finite JSON number: {value}")


def convert(value, rule):
    """Return a canonical string or raise ValueError with a stable reason."""
    kind = rule["type"]
    if kind == "integer":
        if not re.fullmatch(r"[+-]?[0-9]+", value):
            raise ValueError("invalid_integer")
        value = str(int(value))
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
        number = Decimal(value)
        if "min" in rule and number < Decimal(str(rule["min"])):
            raise ValueError("below_min")
        if "max" in rule and number > Decimal(str(rule["max"])):
            raise ValueError("above_max")
    if "choices" in rule and value not in rule["choices"]:
        raise ValueError("not_in_choices")
    return value


def load_schema(raw):
    try:
        schema = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object,
                            parse_constant=reject_constant)
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
    if (not isinstance(tokens, list) or not all(isinstance(t, str) for t in tokens)
            or "" not in tokens or any(normalize(t) != t for t in tokens)):
        raise CleanError("missing_tokens must contain empty string and normalized strings")
    names = []
    for rule in columns:
        if not isinstance(rule, dict) or set(rule) - {
            "name", "type", "required", "default", "min", "max", "choices"
        }:
            raise CleanError("Column rule contains unsupported keys")
        name = rule.get("name")
        if not isinstance(name, str) or not name or normalize(name) != name or name in names:
            raise CleanError("Column names must be nonempty, normalized, and unique")
        names.append(name)
        if rule.get("type") not in ("string", "integer", "number", "date"):
            raise CleanError(f"Unsupported type for {name}")
        if type(rule.setdefault("required", True)) is not bool:
            raise CleanError(f"required must be boolean: {name}")
        for bound in ("min", "max"):
            if bound in rule:
                value = rule[bound]
                if (rule["type"] not in ("integer", "number") or type(value) not in (int, float)
                        or not Decimal(str(value)).is_finite()):
                    raise CleanError(f"Invalid numeric bound: {name}.{bound}")
        if "min" in rule and "max" in rule and rule["min"] > rule["max"]:
            raise CleanError(f"min exceeds max: {name}")
        if "choices" in rule:
            choices = rule["choices"]
            if (rule["type"] != "string" or not isinstance(choices, list) or not choices
                    or not all(isinstance(c, str) and normalize(c) == c and c not in tokens
                               for c in choices) or len(set(choices)) != len(choices)):
                raise CleanError(f"choices must be unique nonmissing strings: {name}")
        if "default" in rule:
            value = rule["default"]
            if rule["required"] or not isinstance(value, str) or normalize(value) in tokens:
                raise CleanError(f"default needs an optional column and a nonmissing string: {name}")
            try:
                rule["default"] = convert(normalize(value), rule)
            except (ValueError, InvalidOperation) as exc:
                raise CleanError(f"Invalid default for {name}: {exc}") from exc
    keys = schema.setdefault("dedupe_key", names.copy())
    if (not isinstance(keys, list) or not keys
            or not all(isinstance(k, str) and k in names for k in keys)
            or len(set(keys)) != len(keys)):
        raise CleanError("dedupe_key must contain unique existing column names")
    return schema


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
    clean_rows, rejected, seen = [], [], set()
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
                raise CleanError(f"CSV record {record}: expected {len(header)} cells, got {len(row)}")
            cleaned, reasons, fills = [], [], 0
            for rule, index in zip(columns, indices):
                value = normalize(row[index])
                if value in schema["missing_tokens"]:
                    if "default" in rule:
                        value = rule["default"]
                        fills += 1
                    elif rule["required"]:
                        reasons.append(f"{rule['name']}:missing_required")
                    else:
                        value = ""
                    cleaned.append(value)
                    continue
                try:
                    cleaned.append(convert(value, rule))
                except (ValueError, InvalidOperation) as exc:
                    reason = str(exc) if str(exc) in {
                        "invalid_integer", "invalid_number", "invalid_date",
                        "below_min", "above_max", "not_in_choices"
                    } else "invalid_value"
                    reasons.append(f"{rule['name']}:{reason}")
                    cleaned.append(value)
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
        raise CleanError(f"Malformed CSV near physical line {reader.line_num}: {exc}") from exc
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(names)
    writer.writerows(clean_rows)
    clean = output.getvalue().encode("utf-8")
    rejects = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rejected).encode("utf-8")
    report = {
        "tool_version": __version__, "schema_version": schema["version"], "encoding": codec,
        "input_rows": input_count, "output_rows": len(clean_rows),
        "invalid_rows": invalid_count, "duplicate_rows": duplicate_count,
        "rejected_rows": len(rejected), "filled_cells_in_output": filled_count,
        "dedupe_key": schema["dedupe_key"], "dedupe_policy": "first_valid_record",
        "sha256": {"input": sha256(raw), "clean.csv": sha256(clean), "rejected.jsonl": sha256(rejects)},
    }
    return clean, rejects, report


def run(input_path, schema_path, output_dir, encoding="utf-8-sig", strict=False):
    """Publish a new result directory only after input and rules pass validation."""
    input_path, schema_path, output_dir = map(Path, (input_path, schema_path, output_dir))
    if output_dir.exists() or output_dir.is_symlink():
        raise CleanError(f"Output directory already exists: {output_dir}", 3)
    raw_schema = schema_path.read_bytes()
    schema = load_schema(raw_schema)
    clean, rejected, report = clean_data(input_path.read_bytes(), schema, encoding)
    if strict and report["rejected_rows"]:
        raise CleanError(f"Strict mode: {report['rejected_rows']} rejected records; no output published", 1)
    report["strict"] = strict
    report["sha256"]["schema"] = sha256(raw_schema)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".gamma-clean-", dir=output_dir.parent))
    try:
        (staging / "clean.csv").write_bytes(clean)
        (staging / "rejected.jsonl").write_bytes(rejected)
        (staging / "report.json").write_bytes(json_bytes(report))
        staging.rename(output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return report
