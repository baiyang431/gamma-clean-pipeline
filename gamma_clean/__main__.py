"""Run with python -m gamma_clean."""

import argparse
import sys

from . import __version__
from .core import CErr, xct


def cli(argv=None):
    prs = argparse.ArgumentParser(
        description="Clean a CSV using explicit JSON rules."
    )
    prs.add_argument("--version", action="version", version=__version__)
    prs.add_argument("--input", required=True, help="Input CSV path")
    prs.add_argument("--schema", required=True, help="UTF-8 JSON schema path")
    prs.add_argument(
        "--output-dir", required=True,
        help="New output directory (must not exist)",
    )
    prs.add_argument(
        "--encoding", default="utf-8-sig",
        help="Input encoding; default: utf-8-sig",
    )
    prs.add_argument(
        "--strict", action="store_true",
        help="Fail if any invalid or duplicate rows exist",
    )
    args = prs.parse_args(argv)
    try:
        rpt = xct(
            args.input, args.schema, args.output_dir, args.encoding, args.strict
        )
    except CErr as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return err.rc
    except OSError as err:
        print(f"ERROR: File operation failed: {err}", file=sys.stderr)
        return 3
    print(
        f"OK: input={rpt['input_rows']} output={rpt['output_rows']} "
        f"invalid={rpt['invalid_rows']} duplicates={rpt['duplicate_rows']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(cli())
