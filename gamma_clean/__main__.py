"""Run with python -m gamma_clean."""

import argparse
import sys

from . import __version__
from .core import CleanError, run


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Clean a CSV using explicit JSON rules."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--input", required=True, help="Input CSV path")
    parser.add_argument("--schema", required=True, help="UTF-8 JSON schema path")
    parser.add_argument(
        "--output-dir", required=True,
        help="New output directory (must not exist)",
    )
    parser.add_argument(
        "--encoding", default="utf-8-sig",
        help="Input encoding; default: utf-8-sig",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Fail if any invalid or duplicate rows exist",
    )
    args = parser.parse_args(argv)
    try:
        report = run(
            args.input, args.schema, args.output_dir, args.encoding, args.strict
        )
    except CleanError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"ERROR: File operation failed: {exc}", file=sys.stderr)
        return 3
    print(
        f"OK: input={report['input_rows']} output={report['output_rows']} "
        f"invalid={report['invalid_rows']} duplicates={report['duplicate_rows']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
