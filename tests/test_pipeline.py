import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gamma_clean.core import CleanError, clean_data, load_schema, run


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.schema_raw = (EXAMPLES / "schema.json").read_bytes()
        self.schema = load_schema(self.schema_raw)

    def clean_rows(self, rows, schema=None):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerows(rows)
        return clean_data(stream.getvalue().encode("utf-8"), schema or self.schema)

    def small_schema(self, columns, **extra):
        schema = {"version": 1, "columns": columns, **extra}
        return load_schema(json.dumps(schema).encode())

    def cli(self, *extra, source=None, schema=None, output=None):
        return subprocess.run(
            [
                sys.executable, "-m", "gamma_clean",
                "--input", str(source or EXAMPLES / "dirty.csv"),
                "--schema", str(schema or EXAMPLES / "schema.json"),
                "--output-dir", str(output or self.base / "result"),
                *extra,
            ],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )

    def test_sample_matches_independent_expected_csv_and_rejection_reasons(self):
        clean, rejected, report = clean_data(
            (EXAMPLES / "dirty.csv").read_bytes(), self.schema
        )
        self.assertEqual(clean, (EXAMPLES / "expected" / "clean.csv").read_bytes())
        records = [json.loads(line) for line in rejected.decode().splitlines()]
        self.assertEqual(
            {record["record"]: record["reasons"] for record in records},
            {
                3: ["duplicate"],
                5: ["age:below_min"],
                6: ["amount:invalid_number"],
                7: ["joined:invalid_date"],
                8: ["status:not_in_choices"],
                9: ["name:missing_required"],
                11: ["age:above_max"],
            },
        )
        self.assertEqual(
            (
                report["input_rows"], report["output_rows"], report["invalid_rows"],
                report["duplicate_rows"], report["filled_cells_in_output"],
            ),
            (11, 4, 6, 1, 2),
        )

    def test_clean_output_is_idempotent(self):
        first, _, _ = clean_data((EXAMPLES / "dirty.csv").read_bytes(), self.schema)
        second, rejects, report = clean_data(first, self.schema)
        self.assertEqual(first, second)
        self.assertEqual(rejects, b"")
        self.assertEqual(report["filled_cells_in_output"], 0)

    def test_utf8_bom_is_supported(self):
        raw = (EXAMPLES / "dirty.csv").read_bytes()
        self.assertEqual(
            clean_data(b"\xef\xbb\xbf" + raw, self.schema)[0],
            clean_data(raw, self.schema)[0],
        )

    def test_explicit_gb18030_preserves_chinese(self):
        raw = (EXAMPLES / "dirty.csv").read_text(encoding="utf-8").encode("gb18030")
        self.assertEqual(
            clean_data(raw, self.schema, "gb18030")[0],
            (EXAMPLES / "expected" / "clean.csv").read_bytes(),
        )

    def test_wrong_or_unknown_encoding_fails_without_replacement(self):
        raw = (EXAMPLES / "dirty.csv").read_text(encoding="utf-8").encode("gb18030")
        for encoding in ("utf-8-sig", "does-not-exist"):
            with self.subTest(encoding=encoding), self.assertRaises(CleanError):
                clean_data(raw, self.schema, encoding)

    def test_empty_file_fails_and_header_only_succeeds(self):
        with self.assertRaises(CleanError):
            clean_data(b"", self.schema)
        header = b"id,name,age,city,amount,joined,status\n"
        clean, rejects, report = clean_data(header, self.schema)
        self.assertEqual(clean, header)
        self.assertEqual(rejects, b"")
        self.assertEqual(report["input_rows"], 0)

    def test_missing_extra_duplicate_headers_fail(self):
        for header in (
            "id", "id,name,age,city,amount,joined,status,extra",
            "id,name,age,city,amount,joined,id",
        ):
            with self.subTest(header=header), self.assertRaises(CleanError):
                clean_data((header + "\n").encode(), self.schema)
        schema = self.small_schema([{"name": "é", "type": "string"}])
        with self.assertRaises(CleanError):
            clean_data("e\u0301\nvalue\n".encode("utf-8"), schema)

    def test_header_order_is_reordered_to_schema(self):
        schema = self.small_schema([
            {"name": "id", "type": "string"}, {"name": "n", "type": "integer"},
        ])
        self.assertEqual(clean_data(b"n,id\n02,001\n", schema)[0], b"id,n\n001,2\n")

    def test_bad_quoting_wrong_width_and_blank_record_fail(self):
        schema = self.small_schema([{"name": "id", "type": "string"}])
        for raw in (b'id\n"unterminated\n', b"id\na,b\n", b"id\n\n"):
            with self.subTest(raw=raw), self.assertRaises(CleanError):
                clean_data(raw, schema)

    def test_quoted_commas_and_multiline_values_are_preserved(self):
        schema = self.small_schema([{"name": "text", "type": "string"}])
        clean, rejects, _ = self.clean_rows(
            [["text"], ["line 1, hello\nline 2"]], schema
        )
        self.assertEqual(
            list(csv.reader(io.StringIO(clean.decode(), newline="")))[1],
            ["line 1, hello\nline 2"],
        )
        self.assertEqual(rejects, b"")

    def test_missing_default_optional_and_required(self):
        schema = self.small_schema([
            {"name": "id", "type": "string"},
            {"name": "a", "type": "integer", "required": False},
            {"name": "b", "type": "string", "required": False, "default": "未知"},
        ])
        clean, rejected, report = self.clean_rows(
            [["id", "a", "b"], ["001", "NA", "NULL"], [" ", "", ""]], schema
        )
        self.assertIn("001,,未知\n", clean.decode())
        self.assertIn("id:missing_required", rejected.decode())
        self.assertEqual(report["filled_cells_in_output"], 1)

    def test_decimal_precision_zero_and_numeric_boundaries(self):
        schema = self.small_schema([
            {"name": "n", "type": "number", "min": 0, "max": 100},
        ])
        clean, rejected, report = self.clean_rows(
            [["n"], ["0.123456789012345678901234567890"], ["-0.000"], ["100.00"],
             ["100.01"], ["-0.01"], ["NaN"], ["Infinity"], ["1e2"]], schema,
        )
        self.assertEqual(clean.decode(), "n\n0.12345678901234567890123456789\n0\n100\n")
        self.assertEqual(report["invalid_rows"], 5)
        self.assertIn("above_max", rejected.decode())

    def test_integer_format_and_bounds(self):
        schema = self.small_schema([
            {"name": "n", "type": "integer", "min": 0, "max": 120},
        ])
        clean, _, report = self.clean_rows(
            [["n"], ["+000"], ["120"], ["121"], ["1.0"], ["١"]], schema
        )
        self.assertEqual(clean, b"n\n0\n120\n")
        self.assertEqual(report["invalid_rows"], 3)

    def test_leap_day_and_strict_iso_dates(self):
        schema = self.small_schema([{"name": "d", "type": "date"}])
        clean, _, report = self.clean_rows(
            [["d"], ["2024-02-29"], ["2023-02-29"],
             ["2024-2-29"], ["2024/02/29"]], schema,
        )
        self.assertEqual(clean, b"d\n2024-02-29\n")
        self.assertEqual(report["invalid_rows"], 3)

    def test_invalid_record_does_not_consume_duplicate_key(self):
        schema = self.small_schema(
            [{"name": "id", "type": "string"}, {"name": "n", "type": "integer"}],
            dedupe_key=["id"],
        )
        clean, rejected, report = self.clean_rows(
            [["id", "n"], ["x", "bad"], ["x", "001"], ["x", "2"]], schema
        )
        self.assertEqual(clean, b"id,n\nx,1\n")
        self.assertEqual((report["invalid_rows"], report["duplicate_rows"]), (1, 1))
        self.assertEqual(
            [json.loads(record)["record"] for record in rejected.splitlines()],
            [2, 4],
        )

    def test_default_deduplication_compares_canonical_entire_row(self):
        schema = self.small_schema([{"name": "n", "type": "integer"}])
        clean, _, report = clean_data(b"n\n001\n1\n2\n", schema)
        self.assertEqual(clean, b"n\n1\n2\n")
        self.assertEqual(report["duplicate_rows"], 1)

    def test_nfc_and_whitespace_are_applied_before_key_deduplication(self):
        schema = self.small_schema(
            [{"name": "id", "type": "string"}, {"name": "label", "type": "string"}],
            dedupe_key=["id"],
        )
        clean, rejected, report = self.clean_rows(
            [
                ["id", "label"], [" e\u0301 ", " first "],
                ["é", "second"], [" é ", "third"],
            ],
            schema,
        )
        self.assertEqual(clean.decode(), "id,label\né,first\n")
        self.assertEqual(report["duplicate_rows"], 2)
        records = [json.loads(line) for line in rejected.splitlines()]
        self.assertEqual(records[1]["values"], [" é ", "third"])
        self.assertEqual(records[0]["reasons"], ["duplicate"])

    def test_nfc_defaults_and_choices_match_cleaned_values(self):
        schema = self.small_schema(
            [
                {
                    "name": "city", "type": "string", "required": False,
                    "default": " cafe\u0301 ",
                },
                {"name": "status", "type": "string", "choices": [" e\u0301 "]},
            ],
            missing_tokens=["", " N/A "],
        )
        clean, rejected, report = self.clean_rows(
            [["city", "status"], ["N/A", "é"], ["cafe\u0301", " e\u0301 "]],
            schema,
        )
        self.assertEqual(clean.decode(), "city,status\ncafé,é\n")
        self.assertEqual(report["filled_cells_in_output"], 1)
        self.assertEqual(report["duplicate_rows"], 1)
        self.assertEqual(json.loads(rejected)["reasons"], ["duplicate"])

    def test_nul_input_is_rejected(self):
        with self.assertRaises(CleanError):
            clean_data(b"id\x00\n", self.schema)

    def test_schema_rejects_unknown_keys_and_invalid_rules(self):
        valid = {"version": 1, "columns": [{"name": "n", "type": "integer"}]}
        bad_schemas = [
            [], {}, {**valid, "version": True}, {**valid, "typo": 1},
            {**valid, "dedupe_key": ["absent"]}, {**valid, "dedupe_key": []},
            {**valid, "missing_tokens": ["NA"]},
        ]
        bad_rules = [
            {"name": "n", "type": "imaginary"},
            {"name": "n", "type": "integer", "min": True},
            {"name": "n", "type": "integer", "min": 5, "max": 1},
            {"name": "n", "type": "integer", "required": "yes"},
            {"name": "n", "type": "integer", "required": False, "default": "bad"},
            {"name": "n", "type": "string", "choices": ["a", 1]},
            {"name": " n", "type": "string"},
            {"name": "n", "type": "string", "typo": 1},
        ]
        bad_schemas += [{**valid, "columns": [rule]} for rule in bad_rules]
        bad_schemas += [{**valid, "columns": valid["columns"] * 2}]
        for schema in bad_schemas:
            with self.subTest(schema=schema), self.assertRaises(CleanError):
                load_schema(json.dumps(schema).encode())

    def test_nonfinite_bounds_and_malformed_json_fail(self):
        invalid = [b'{"version":NaN}', b'{broken', b"\xff"]
        for value in (float("nan"), float("inf"), float("-inf")):
            invalid.append(json.dumps({
                "version": 1,
                "columns": [{"name": "n", "type": "number", "min": value}],
            }).encode())
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(CleanError):
                load_schema(raw)

    def test_success_cli_publishes_expected_data_and_report(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.base / "result"
        self.assertEqual(
            {path.name for path in output.iterdir()},
            {"clean.csv", "rejected.jsonl", "report.json"},
        )
        report = json.loads((output / "report.json").read_bytes())
        self.assertEqual(
            report["input_rows"], report["output_rows"] + report["rejected_rows"]
        )
        self.assertEqual(
            (output / "clean.csv").read_bytes(),
            (EXAMPLES / "expected" / "clean.csv").read_bytes(),
        )
        records = (output / "rejected.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(records), report["rejected_rows"])

    def test_strict_mode_exit_one_publishes_nothing(self):
        result = self.cli("--strict")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Strict mode", result.stderr)
        self.assertFalse((self.base / "result").exists())

    def test_valid_input_passes_strict_mode(self):
        result = self.cli("--strict", source=EXAMPLES / "expected" / "clean.csv")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_schema_and_encoding_exit_two(self):
        bad = self.base / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        results = [self.cli(schema=bad), self.cli("--encoding", "absent")]
        for result in results:
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((self.base / "result").exists())

    def test_missing_input_exit_three(self):
        result = self.cli(source=self.base / "missing.csv")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertFalse((self.base / "result").exists())

    def test_existing_output_is_preserved(self):
        output = self.base / "result"
        output.mkdir()
        (output / "marker").write_bytes(b"keep me")
        result = self.cli()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(list(output.iterdir()), [output / "marker"])
        self.assertEqual((output / "marker").read_bytes(), b"keep me")

    def test_bad_input_does_not_publish_partial_artifacts(self):
        bad = self.base / "bad.csv"
        bad.write_bytes(b"wrong,header\n")
        result = self.cli(source=bad)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.base / "result").exists())
        self.assertFalse(list(self.base.glob(".gamma-clean-*")))

    def test_paths_with_spaces_work_and_inputs_are_unchanged(self):
        source = self.base / "source with spaces.csv"
        raw = (EXAMPLES / "dirty.csv").read_bytes()
        source.write_bytes(raw)
        result = self.cli(source=source, output=self.base / "result with spaces")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual((EXAMPLES / "schema.json").read_bytes(), self.schema_raw)

    def test_write_failure_removes_staging_and_leaves_no_result(self):
        original_write = Path.write_bytes

        def fail_on_report(path, data):
            if path.name == "report.json":
                raise OSError("simulated disk error")
            return original_write(path, data)

        with patch("gamma_clean.core.Path.write_bytes", new=fail_on_report):
            with self.assertRaises(OSError):
                run(
                    EXAMPLES / "dirty.csv", EXAMPLES / "schema.json",
                    self.base / "result",
                )
        self.assertFalse((self.base / "result").exists())
        self.assertFalse(list(self.base.glob(".gamma-clean-*")))

    def test_cli_argument_error_and_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "gamma_clean"], cwd=ROOT, capture_output=True
        )
        self.assertEqual(result.returncode, 2)
        result = subprocess.run(
            [sys.executable, "-m", "gamma_clean", "--version"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "1.0.0"))


if __name__ == "__main__":
    unittest.main()
