"""Capture synthetic traverse spans on nominal integer coordinates."""

import argparse
import json
from pathlib import Path

from . import field_delivery, store


def capture(db, evidence):
    spans = evidence["spans"]
    if not spans or any(type(lo) is not int or type(hi) is not int or lo >= hi for lo, hi in spans):
        raise ValueError("valid half-open integer spans required")
    covered = {tick for lo, hi in spans for tick in range(lo, hi)}
    limit = evidence["minimum"]
    outcome = "complete" if len(covered) >= limit else "short"
    db.execute(
        """CREATE TABLE IF NOT EXISTS field_track(
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, raw TEXT NOT NULL,
            outcome TEXT NOT NULL
        )"""
    )
    raw = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    existing = db.execute("SELECT raw FROM field_track WHERE id=?", (evidence["id"],)).fetchone()
    if existing:
        if existing[0] != raw:
            raise ValueError("track id conflict")
        return {"outcome": outcome, "delivery": "already_recorded"}
    db.execute("INSERT INTO field_track VALUES (?,?,?,?)", (evidence["id"], evidence["case_id"], raw, outcome))
    state = field_delivery.reconsider(db, evidence["case_id"], outcome, evidence["id"])
    return {"outcome": outcome, "delivery": state}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    evidence = json.loads(Path(args.input).read_text(encoding="utf-8"))
    with store.session(args.db) as db:
        print(json.dumps(capture(db, evidence), ensure_ascii=False))


if __name__ == "__main__":
    main()
