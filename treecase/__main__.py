"""Offline CLI for source capture, reports, replay audit and review packets."""

import argparse
import json
import sys
from pathlib import Path

from . import review_packet, store
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
    packet = sub.add_parser("review-packet")
    packet.add_argument("--db", required=True)
    packet.add_argument("--permit", required=True)
    packet.add_argument("--constraints", required=True)
    packet.add_argument("--attestations", required=True)
    packet.add_argument("--route", choices=list(review_packet.ROUTES), default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            value = run(args.db, args.force)
        elif args.command == "report":
            value = snapshot(args.db)
        elif args.command == "audit":
            value = audit(args.db, FIXTURES)
        elif args.command == "review-packet":
            with store.session(args.db) as db:
                rows = store.event_rows(db)
            snap = review_packet.internal_snapshot(rows, args.permit)
            constraints = json.loads(Path(args.constraints).read_text(encoding="utf-8"))
            attestations = json.loads(Path(args.attestations).read_text(encoding="utf-8"))
            value = review_packet.issue_packet(snap, constraints, attestations, route=args.route)
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
