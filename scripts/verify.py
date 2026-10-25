"""Exercise the documented CLI and optionally save real verification evidence."""

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def verify():
    runs = []
    with tempfile.TemporaryDirectory(prefix="gamma-verify-") as directory:
        base = Path(directory)

        def invoke(label, source, output, extra=(), expected_exit=0):
            args = [
                sys.executable, "-m", "gamma_clean",
                "--input", str(source),
                "--schema", "examples/schema.json",
                "--output-dir", str(output),
                *extra,
            ]
            result = subprocess.run(
                args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            if result.returncode != expected_exit:
                raise RuntimeError(
                    f"{label}: expected exit {expected_exit}, "
                    f"got {result.returncode}: {result.stderr}"
                )
            if expected_exit and output.exists():
                raise RuntimeError(f"{label}: failed command left an output directory")
            runs.append({
                "case": label,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })

        source = ROOT / "examples" / "dirty.csv"
        original = source.read_bytes()
        invoke("sample", source, base / "one")
        invoke("repeat", source, base / "two")
        sample = base / "one"
        expected = (ROOT / "examples/expected/clean.csv").read_bytes()
        if (sample / "clean.csv").read_bytes() != expected:
            raise RuntimeError("Sample output differs from expected CSV")
        for name in ("clean.csv", "rejected.jsonl", "report.json"):
            if (sample / name).read_bytes() != (base / "two" / name).read_bytes():
                raise RuntimeError(f"Repeat mismatch: {name}")
        encoded_source = base / "gb18030.csv"
        encoded_source.write_bytes(original.decode("utf-8").encode("gb18030"))
        invoke(
            "explicit_gb18030", encoded_source, base / "gb",
            ["--encoding", "gb18030"],
        )
        if (base / "gb/clean.csv").read_bytes() != expected:
            raise RuntimeError("GB18030 output differs from expected CSV")
        invoke("strict_rejection", source, base / "strict", ["--strict"], 1)
        malformed = base / "malformed.csv"
        malformed.write_bytes(b"wrong,header\n")
        invoke("bad_header", malformed, base / "bad", expected_exit=2)
        if source.read_bytes() != original:
            raise RuntimeError("Source data was modified")
        report = json.loads((sample / "report.json").read_bytes())
        return {
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "python": platform.python_version(),
                "os": f"{platform.system()} {platform.release()}",
                "runtime_dependencies": [],
            },
            "checks": {
                "expected_clean_match": True,
                "repeat_all_artifacts_equal": True,
                "gb18030_output_equal": True,
                "failure_outputs_absent": True,
                "source_unchanged": True,
            },
            "sample_report": report,
            "cli_runs": runs,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, help="Optional evidence JSON destination")
    args = parser.parse_args()
    evidence = verify()
    text = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(text, encoding="utf-8", newline="\n")
    print(text, end="")


if __name__ == "__main__":
    main()
