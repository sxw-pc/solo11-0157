"""Readable current state and the decisions that led there."""

import json

from . import store


def snapshot(db_path):
    with store.session(db_path) as db:
        events = [{"event_id": r["event_id"], "kind": r["kind"],
                   "recorded_at": r["recorded_at"], "raw_sha256": r["raw_sha256"],
                   "artifact_hashes": json.loads(r["artifacts_json"])}
                  for r in store.event_rows(db)]
        decisions = [{"event_id": r["event_id"], "kind": r["kind"],
                      "object_id": r["object_id"], "outcome": r["outcome"],
                      "reasons": json.loads(r["reasons_json"]),
                      "rule_version": r["rule_version"],
                      "details": json.loads(r["details_json"])}
                     for r in db.execute("SELECT * FROM decisions ORDER BY event_id")]
        trees = {r["tree_no"]: {"risk": r["risk"], "revision": r["revision"],
                                 "archive_revision": r["archive_revision"],
                                 "seal_revision": r["seal_revision"],
                                 "seal_from": r["seal_from"], "seal_to": r["seal_to"],
                                 "seal_radius_m": r["seal_radius_m"],
                                 "released_at": r["released_at"],
                                 "release_work_id": r["release_work_id"],
                                 "identity": json.loads(r["identity_json"]),
                                 "basis": json.loads(r["basis_json"])}
                 for r in db.execute("SELECT * FROM tree_projection")}
        permits = {r["permit_id"]: {"tree_no": r["tree_no"], "state": r["state"],
                                     "reasons": json.loads(r["reasons_json"]),
                                     "terms": json.loads(r["terms_json"]),
                                     "revoked_at": r["revoked_at"]}
                   for r in db.execute("SELECT * FROM permit_projection")}
        works = {r["work_id"]: {"permit_id": r["permit_id"], "state": r["state"],
                                "reasons": json.loads(r["reasons_json"]),
                                "source_event_id": r["source_event_id"],
                                "receipt": json.loads(r["receipt_json"])}
                 for r in db.execute("SELECT * FROM work_projection")}
    return {"events": events, "decisions": decisions, "trees": trees,
            "permits": permits, "works": works}
