"""Capture synthetic traverse spans on nominal integer coordinates.

Two evidence shapes share this capture entry point:

* the nominal-grid baseline (``spans``), whose cells are recorded directly;
* a field contract (``shape == "field_contract"``), whose local segments may
  have been shifted by a clamp change and whose signable coverage is the
  minimum true union over every interpretation the originals allow.
"""

import argparse
import json
from pathlib import Path

from . import field_coverage, field_delivery, store


def _nominal_outcome(evidence):
    spans = evidence["spans"]
    if not spans or any(type(lo) is not int or type(hi) is not int or lo >= hi for lo, hi in spans):
        raise ValueError("valid half-open integer spans required")
    covered = {tick for lo, hi in spans for tick in range(lo, hi)}
    return "complete" if len(covered) >= evidence["minimum"] else "short"


def capture(db, evidence):
    if evidence.get("shape") == "field_contract":
        return _capture_contract(db, evidence)

    outcome = _nominal_outcome(evidence)
    raw = _record(db, evidence, outcome)
    if raw is not None:
        return {"outcome": outcome, "delivery": "already_recorded"}
    state = field_delivery.reconsider(db, evidence["case_id"], outcome, evidence["id"])
    return {"outcome": outcome, "delivery": state}


def _capture_contract(db, evidence):
    result = field_coverage.evaluate(evidence)
    outcome = "complete" if result["status"] == "ready" else "short"
    raw = _record(db, evidence, outcome)
    if raw is not None:
        return {"outcome": outcome, "delivery": "already_recorded",
                "status": result["status"], "reason": result["reason"],
                "coverage_floor": result["coverage_floor"],
                "position_certified": result["position_certified"]}
    field_coverage.save(db, evidence["case_id"], evidence["id"], result)
    state = field_delivery.reconsider(db, evidence["case_id"], outcome, evidence["id"], result)
    return {"outcome": outcome, "delivery": state, "status": result["status"],
            "reason": result["reason"], "coverage_floor": result["coverage_floor"],
            "coverage_max": result["coverage_max"],
            "certain_spans": result["certain_spans"],
            "position_certified": result["position_certified"],
            "position_review_available": result["position_review_available"],
            "interpretation_count": result["interpretation_count"]}


def _record(db, evidence, outcome):
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
        return raw
    db.execute("INSERT INTO field_track VALUES (?,?,?,?)",
               (evidence["id"], evidence["case_id"], raw, outcome))
    return None


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
