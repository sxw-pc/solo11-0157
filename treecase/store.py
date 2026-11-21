"""Immutable event journal and disposable projections."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, recorded_at TEXT NOT NULL,
  raw_sha256 TEXT NOT NULL, raw_bytes BLOB NOT NULL,
  payload_json TEXT NOT NULL, artifacts_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tree_archives (
  archive_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
  tree_no TEXT NOT NULL, revision INTEGER NOT NULL, accepted INTEGER NOT NULL,
  identity_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inspections (
  inspection_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
  tree_no TEXT NOT NULL, observed_at TEXT NOT NULL, risk TEXT NOT NULL,
  reasons_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_items (
  evidence_id TEXT PRIMARY KEY, inspection_id TEXT NOT NULL REFERENCES inspections(inspection_id),
  kind TEXT NOT NULL, captured_by TEXT NOT NULL, captured_at TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  event_id TEXT PRIMARY KEY REFERENCES events(event_id), kind TEXT NOT NULL,
  object_id TEXT NOT NULL, outcome TEXT NOT NULL, reasons_json TEXT NOT NULL,
  details_json TEXT NOT NULL, rule_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tree_projection (
  tree_no TEXT PRIMARY KEY, identity_json TEXT NOT NULL, risk TEXT NOT NULL,
  revision INTEGER NOT NULL, archive_revision INTEGER NOT NULL, seal_revision INTEGER NOT NULL,
  seal_from TEXT, seal_to TEXT, seal_radius_m INTEGER NOT NULL,
  released_at TEXT, release_work_id TEXT, basis_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permit_projection (
  permit_id TEXT PRIMARY KEY, tree_no TEXT NOT NULL, state TEXT NOT NULL,
  reasons_json TEXT NOT NULL, terms_json TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS seal_orders (
  tree_no TEXT PRIMARY KEY REFERENCES tree_projection(tree_no), risk_revision INTEGER NOT NULL,
  radius_m INTEGER NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT NOT NULL,
  released_at TEXT, release_work_id TEXT
);
CREATE TABLE IF NOT EXISTS work_projection (
  work_id TEXT PRIMARY KEY, permit_id TEXT NOT NULL, state TEXT NOT NULL,
  reasons_json TEXT NOT NULL, receipt_json TEXT NOT NULL, source_event_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reinspections (
  reinspection_id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES work_projection(work_id),
  witness_id TEXT NOT NULL, witnessed_at TEXT NOT NULL, stable INTEGER NOT NULL,
  independent INTEGER NOT NULL, artifact_sha256 TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'immutable source event'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'immutable source event'); END;
"""


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(DDL)
    return db


@contextmanager
def session(path):
    db = connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def event_rows(db):
    return [dict(row) for row in db.execute(
        "SELECT * FROM events ORDER BY recorded_at, event_id")]


def replace_projections(db, result):
    for table in ("evidence_items", "inspections", "tree_archives", "reinspections",
                  "seal_orders", "decisions", "tree_projection", "permit_projection", "work_projection"):
        db.execute(f"DELETE FROM {table}")
    for decision in result["decisions"]:
        db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?)", (
            decision["event_id"], decision["kind"], decision["object_id"],
            decision["outcome"], json.dumps(decision["reasons"]),
            json.dumps(decision["details"], sort_keys=True), "treecase-rules-1.0"))
    for tree in result["trees"].values():
        db.execute("INSERT INTO tree_projection VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            tree["tree_no"], json.dumps(tree["identity"], sort_keys=True),
            tree["risk"], tree["revision"], tree["archive_revision"],
            tree["seal_revision"], tree["seal_from"],
            tree["seal_to"], tree["seal_radius_m"], tree["released_at"],
            tree["release_work_id"], json.dumps(tree["basis"], sort_keys=True)))
        if tree["seal_from"]:
            db.execute("INSERT INTO seal_orders VALUES (?,?,?,?,?,?,?)", (
                tree["tree_no"], tree["seal_revision"], tree["seal_radius_m"],
                tree["seal_from"], tree["seal_to"], tree["released_at"], tree["release_work_id"]))
    for permit in result["permits"].values():
        db.execute("INSERT INTO permit_projection VALUES (?,?,?,?,?,?)", (
            permit["permit_id"], permit["tree_no"], permit["state"],
            json.dumps(permit["reasons"]), json.dumps(permit["terms"], sort_keys=True),
            permit["revoked_at"]))
    for work in result["works"].values():
        db.execute("INSERT INTO work_projection VALUES (?,?,?,?,?,?)", (
            work["work_id"], work["permit_id"], work["state"],
            json.dumps(work["reasons"]), json.dumps(work["receipt"], sort_keys=True),
            work["source_event_id"]))
    _materialize_source_entities(db, result)


def _materialize_source_entities(db, result):
    decisions = {d["event_id"]: d for d in result["decisions"]}
    for row in event_rows(db):
        payload = json.loads(row["payload_json"])
        artifacts = json.loads(row["artifacts_json"])
        if row["kind"] == "tree":
            tree = payload["tree"]
            db.execute("INSERT INTO tree_archives VALUES (?,?,?,?,?,?)", (
                tree["archive_id"], row["event_id"], str(tree["tree_no"]),
                int(tree["archive_version"]),
                int(decisions[row["event_id"]]["outcome"] not in ("identity_conflict", "archive_conflict")),
                json.dumps(tree, sort_keys=True)))
            for inspection in payload.get("inspections", []):
                _inspection(db, inspection, row["event_id"], str(tree["tree_no"]), artifacts)
        elif row["kind"] == "work":
            work = payload["work"]
            counter = work.get("counter_evidence")
            if counter:
                _inspection(db, counter, row["event_id"], str(work["tree_no"]), artifacts)
            review = work.get("reinspection")
            if review:
                independent = (review["witness_id"] != work.get("operator_id") and
                               review["witness_org"] != work.get("contractor_id"))
                db.execute("INSERT INTO reinspections VALUES (?,?,?,?,?,?,?)", (
                    review["reinspection_id"], work["work_id"], review["witness_id"],
                    review["witnessed_at"], int(review["stable"]), int(independent),
                    artifacts.get(review["file"], "")))


def _inspection(db, inspection, event_id, tree_no, artifacts):
    from .tree_policy import inspection_score
    risk, reasons, _ = inspection_score(inspection)
    db.execute("INSERT INTO inspections VALUES (?,?,?,?,?,?)", (
        inspection["inspection_id"], event_id, tree_no, inspection["observed_at"],
        risk, json.dumps(reasons)))
    for item in inspection.get("evidence", []):
        db.execute("INSERT INTO evidence_items VALUES (?,?,?,?,?,?)", (
            item["evidence_id"], inspection["inspection_id"], item["kind"],
            item["captured_by"], item["capture_at"], artifacts.get(item["file"], "")))
