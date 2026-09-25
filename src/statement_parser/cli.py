"""statement-parser CLI: one summary line per document; JSON on request.
Nothing is written to disk unless --json-dir is given."""

import argparse
import sys
from pathlib import Path

from . import parse_statements


def _summary(doc):
    check = doc.check_balance()
    balance = {True: "balance OK", False: "BALANCE MISMATCH", None: "no balances"}[check]
    period = f"{doc.period_start or '?'}..{doc.period_end or '?'}"
    return (
        f"{Path(doc.source_file).name}: {doc.doc_type} | {doc.account_label or ''} "
        f"{doc.account_ref or ''} | {period} | {len(doc.movements)} movement(s), "
        f"{len(doc.positions)} position(s) | {balance}"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(prog="statement-parser", description=__doc__)
    ap.add_argument("paths", nargs="+", help="statement files or directories")
    ap.add_argument("--json", action="store_true", help="print documents as JSON to stdout")
    ap.add_argument("--json-dir", type=Path, help="write one <file>.json per document here")
    ap.add_argument("--lenient", action="store_true", help="don't fail on a balance mismatch")
    args = ap.parse_args(argv)

    documents, errors = parse_statements(args.paths, strict=not args.lenient)
    for doc in documents:
        if args.json:
            print(doc.to_json())
        else:
            print(_summary(doc))
            for warning in doc.warnings:
                print(f"  warning: {warning}")
        if args.json_dir:
            args.json_dir.mkdir(parents=True, exist_ok=True)
            (args.json_dir / f"{Path(doc.source_file).name}.json").write_text(doc.to_json(), encoding="utf-8")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
