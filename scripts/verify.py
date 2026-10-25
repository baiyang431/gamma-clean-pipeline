import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


RT = Path(__file__).resolve().parents[1]


def vfy():
    rns = []
    with tempfile.TemporaryDirectory(prefix="gamma-verify-") as td:
        wd = Path(td)

        def inv(lbl, src, dst, ext=(), erc=0):
            args = [
                sys.executable, "-m", "gamma_clean",
                "--input", str(src),
                "--schema", "examples/schema.json",
                "--output-dir", str(dst),
                *ext,
            ]
            res = subprocess.run(
                args, cwd=RT, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            if res.returncode != erc:
                raise RuntimeError(
                    f"{lbl}: expected exit {erc}, "
                    f"got {res.returncode}: {res.stderr}"
                )
            if erc and dst.exists():
                raise RuntimeError(f"{lbl}: failed command left an output directory")
            rns.append({
                "case": lbl,
                "exit_code": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
            })

        src = RT / "examples" / "dirty.csv"
        org = src.read_bytes()
        inv("sample", src, wd / "one")
        inv("repeat", src, wd / "two")
        smp = wd / "one"
        exp = (RT / "examples/expected/clean.csv").read_bytes()
        if (smp / "clean.csv").read_bytes() != exp:
            raise RuntimeError("Sample output differs from expected CSV")
        for nm in ("clean.csv", "rejected.jsonl", "report.json"):
            if (smp / nm).read_bytes() != (wd / "two" / nm).read_bytes():
                raise RuntimeError(f"Repeat mismatch: {nm}")
        gsrc = wd / "gb18030.csv"
        gsrc.write_bytes(org.decode("utf-8").encode("gb18030"))
        inv(
            "explicit_gb18030", gsrc, wd / "gb",
            ["--encoding", "gb18030"],
        )
        if (wd / "gb/clean.csv").read_bytes() != exp:
            raise RuntimeError("GB18030 output differs from expected CSV")
        inv("strict_rejection", src, wd / "strict", ["--strict"], 1)
        mf = wd / "malformed.csv"
        mf.write_bytes(b"wrong,header\n")
        inv("bad_header", mf, wd / "bad", erc=2)
        if src.read_bytes() != org:
            raise RuntimeError("Source data was modified")
        rpt = json.loads((smp / "report.json").read_bytes())
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
            "sample_report": rpt,
            "cli_runs": rns,
        }


def cli():
    prs = argparse.ArgumentParser(description="Run CLI checks for the sample data.")
    prs.add_argument("--save", type=Path, help="Optional evidence JSON destination")
    args = prs.parse_args()
    evd = vfy()
    txt = json.dumps(evd, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(txt, encoding="utf-8", newline="\n")
    print(txt, end="")


if __name__ == "__main__":
    cli()
