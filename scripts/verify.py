"""Exercise the documented CLI and optionally save real verification evidence."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    runs = []
    with tempfile.TemporaryDirectory(prefix="gamma-verify-") as directory:
        base = Path(directory)

        def invoke(label, source, output, extra=(), expected_exit=0):
            args = ["-m", "gamma_clean", "--input", str(source), "--schema", "examples/schema.json",
                    "--output-dir", str(output), *extra]
            result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True,
                                    text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
            require(result.returncode == expected_exit,
                    f"{label}: expected exit {expected_exit}, got {result.returncode}: {result.stderr}")
            runs.append({"case": label, "exit_code": result.returncode,
                         "stdout": result.stdout.strip(), "stderr": result.stderr.strip()})

        source = ROOT / "examples" / "dirty.csv"
        original_hash = digest(source)
        invoke("sample", source, base / "one")
        invoke("repeat", source, base / "two")
        sample = base / "one"
        require((sample / "clean.csv").read_bytes() == (ROOT / "examples/expected/clean.csv").read_bytes(),
                "Sample clean output differs from independent expected fixture")
        hashes = {}
        for name in ("clean.csv", "rejected.jsonl", "report.json"):
            hashes[name] = digest(sample / name)
            require(hashes[name] == digest(base / "two" / name), f"Repeat mismatch: {name}")
        invoke("idempotent", sample / "clean.csv", base / "idempotent")
        require((sample / "clean.csv").read_bytes() == (base / "idempotent/clean.csv").read_bytes(),
                "Clean CSV is not idempotent")
        gbk = base / "gb18030.csv"
        gbk.write_bytes(source.read_text(encoding="utf-8").encode("gb18030"))
        invoke("explicit_gb18030", gbk, base / "gb", ["--encoding", "gb18030"])
        require((base / "gb/clean.csv").read_bytes() == (sample / "clean.csv").read_bytes(),
                "GB18030 output mismatch")
        invoke("strict_rejection", source, base / "strict", ["--strict"], 1)
        require(not (base / "strict").exists(), "Strict failure published outputs")
        malformed = base / "malformed.csv"
        malformed.write_bytes(b"wrong,header\n")
        invoke("bad_header", malformed, base / "bad", expected_exit=2)
        require(not (base / "bad").exists(), "Bad input published outputs")
        require(digest(source) == original_hash, "Source data was modified")
        report = json.loads((sample / "report.json").read_bytes())
        return {
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                            "os": platform.system(), "os_release": platform.release(),
                            "machine": platform.machine(), "runtime_dependencies": []},
            "checks": {"expected_clean_match": True, "repeat_all_artifacts_equal": True,
                       "clean_csv_idempotent": True, "gb18030_output_equal": True,
                       "failure_outputs_absent": True, "source_unchanged": True},
            "artifact_sha256": hashes, "sample_report": report, "cli_runs": runs,
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
