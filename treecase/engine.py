"""Deterministic cross-subsystem replay from captured source events."""

import hashlib
import json
import sqlite3

from . import evidence, permit_policy, store, tree_policy, work_policy


def replay(rows):
    trees, permits, works, decisions = {}, {}, {}, []
    for row in sorted(rows, key=lambda item: (item["recorded_at"], item["event_id"])):
        if not evidence.verify_event(row):
            raise evidence.SourceError(f"source digest or payload mismatch: {row['event_id']}")
        event = json.loads(row["payload_json"])
        kind = row["kind"]
        if kind == "tree":
            outcome, reasons, details = tree_policy.apply_tree(event, trees)
            object_id = str(event["tree"]["tree_no"])
        elif kind == "permit":
            outcome, reasons, details = permit_policy.apply_permit(event, trees, permits)
            object_id = event["permit"]["permit_id"]
        elif kind == "work":
            outcome, reasons, details = work_policy.apply_work(event, trees, permits, works)
            object_id = event["work"]["work_id"]
        elif kind == "revocation":
            outcome, reasons, details = permit_policy.apply_revocation(event, trees, permits, works)
            object_id = event["revocation"]["permit_id"]
        else:
            raise evidence.SourceError(f"unsupported event kind: {kind}")
        decisions.append({"event_id": row["event_id"], "kind": kind,
                          "object_id": object_id, "outcome": outcome,
                          "reasons": reasons, "details": details})
    return {"trees": trees, "permits": permits, "works": works, "decisions": decisions}


def import_file(db_path, file_path, expected_kind=None):
    kind, payload, raw, artifacts = evidence.read_source(file_path)
    if expected_kind is not None and expected_kind != kind:
        raise evidence.SourceError(f"expected {expected_kind} source, got {kind}")
    raw_hash = hashlib.sha256(raw).hexdigest()
    with store.session(db_path) as db:
        old = db.execute("SELECT raw_sha256 FROM events WHERE event_id=?", (payload["event_id"],)).fetchone()
        if old:
            if old[0] != raw_hash:
                raise evidence.SourceError("event ID reused with different bytes")
            decision = db.execute("SELECT outcome,reasons_json FROM decisions WHERE event_id=?", (payload["event_id"],)).fetchone()
            return {"event_id": payload["event_id"], "kind": kind, "duplicate": True,
                    "outcome": decision[0], "reasons": json.loads(decision[1])}
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)", (
            payload["event_id"], kind, payload["recorded_at"], raw_hash, raw,
            json.dumps(payload, sort_keys=True), json.dumps(artifacts, sort_keys=True)))
        result = replay(store.event_rows(db))
        store.replace_projections(db, result)
        decision = next(d for d in result["decisions"] if d["event_id"] == payload["event_id"])
        return {"event_id": payload["event_id"], "kind": kind, "duplicate": False,
                "outcome": decision["outcome"], "reasons": decision["reasons"],
                "details": decision["details"]}


def audit(db_path, fixture_root=None):
    with store.session(db_path) as db:
        rows = store.event_rows(db)
        result = replay(rows)
        reference = sqlite3.connect(":memory:")
        reference.row_factory = sqlite3.Row
        projection_mismatches = []
        try:
            reference.executescript(store.DDL)
            for row in rows:
                reference.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)", (
                    row["event_id"], row["kind"], row["recorded_at"],
                    row["raw_sha256"], row["raw_bytes"], row["payload_json"], row["artifacts_json"]))
            store.replace_projections(reference, result)
            for table in ("decisions", "tree_projection", "permit_projection", "work_projection",
                          "tree_archives", "inspections", "evidence_items", "seal_orders", "reinspections"):
                actual = {r[0]: tuple(r) for r in db.execute(f"SELECT * FROM {table}")}
                expected = {r[0]: tuple(r) for r in reference.execute(f"SELECT * FROM {table}")}
                for key in sorted(actual.keys() | expected.keys()):
                    if actual.get(key) != expected.get(key):
                        projection_mismatches.append(f"{table}:{key}")
        finally:
            reference.close()
        mismatches = [item.split(":", 1)[1] for item in projection_mismatches
                      if item.startswith("decisions:")]
        artifacts_ok = None if fixture_root is None else all(
            evidence.verify_artifacts(row, fixture_root) for row in rows)
        return {"event_count": len(rows), "decision_count": len(result["decisions"]),
                "projection_matches_replay": not projection_mismatches,
                "mismatched_event_ids": mismatches, "source_integrity": True,
                "projection_mismatches": projection_mismatches,
                "artifact_integrity": artifacts_ok,
                "trees": len(result["trees"]), "permits": len(result["permits"]),
                "works": len(result["works"])}
