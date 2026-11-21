"""Offline CLI for source capture, reports and replay audit."""

import argparse
import json
import sys

from .demo import FIXTURES, run
from .engine import audit, import_file
from .report import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(prog="treecase")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("tree-import", "permit-import", "work-import", "permit-revoke"):
        entry = sub.add_parser(name)
        entry.add_argument("--db", required=True)
        entry.add_argument("--file", required=True)
    for name in ("report", "audit"):
        entry = sub.add_parser(name)
        entry.add_argument("--db", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--db", required=True)
    demo.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            value = run(args.db, args.force)
        elif args.command == "report":
            value = snapshot(args.db)
        elif args.command == "audit":
            value = audit(args.db, FIXTURES)
        else:
            kind = {"tree-import": "tree", "permit-import": "permit",
                    "work-import": "work", "permit-revoke": "revocation"}[args.command]
            value = import_file(args.db, args.file, kind)
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
