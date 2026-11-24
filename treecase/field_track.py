"""Capture synthetic traverse spans and coverage contracts on nominal grids."""

import argparse
import json
from pathlib import Path

from . import field_coverage, field_delivery, store


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


def _record_contract(db, contract, raw):
    db.execute(
        """CREATE TABLE IF NOT EXISTS field_coverage_contract(
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, raw TEXT NOT NULL
        )"""
    )
    existing = db.execute(
        "SELECT raw FROM field_coverage_contract WHERE id=?", (contract["id"],)).fetchone()
    if existing:
        if existing[0] != raw:
            raise ValueError("contract id conflict")
        return "already_recorded"
    db.execute("INSERT INTO field_coverage_contract VALUES (?,?,?)",
               (contract["id"], contract["case_id"], raw))
    return "recorded"


def capture_contract(db, contract):
    """Adjudicate one coverage contract against the original records on file."""
    field_coverage.validate_contract(contract)
    raw = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    persistence = _record_contract(db, contract, raw)
    rows = db.execute(
        "SELECT raw FROM field_coverage_contract WHERE case_id=? ORDER BY id",
        (contract["case_id"],)).fetchall()
    submissions = [json.loads(row[0]) for row in rows]
    merged = field_coverage.merge_contracts(submissions)
    decision = field_coverage.adjudicate(merged)
    field_delivery.record_coverage(db, decision)
    summary = {
        "case_id": decision["case_id"],
        "delivery": decision["status"],
        "guaranteed_coverage": decision["guaranteed_coverage"],
        "certain_cells": decision["certain_cells"],
        "position_certified": decision["position_certified"],
        "certificate": decision["certificate"],
        "reasons": decision["reasons"],
        "persistence": persistence,
        "evidence_ids": decision["evidence_ids"],
    }
    return summary, decision


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    evidence = json.loads(Path(args.input).read_text(encoding="utf-8"))
    with store.session(args.db) as db:
        if evidence.get("schema") == field_coverage.SCHEMA:
            summary, _ = capture_contract(db, evidence)
            print(json.dumps(summary, ensure_ascii=False))
        elif isinstance(evidence.get("contracts"), list):
            results = [capture_contract(db, contract)[0]
                       for contract in evidence["contracts"]]
            print(json.dumps(results, ensure_ascii=False))
        else:
            print(json.dumps(capture(db, evidence), ensure_ascii=False))


if __name__ == "__main__":
    main()
