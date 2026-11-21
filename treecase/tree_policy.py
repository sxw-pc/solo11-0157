"""Identity, inspection credibility, risk revision and seal policy."""

from datetime import datetime, timedelta


def instant(value):
    return datetime.fromisoformat(value)


IDENTITY_FIELDS = ("tree_no", "block_id", "grid_code", "tag_id", "species", "protected_level")


def inspection_score(inspection):
    reasons = []
    observed = instant(inspection["observed_at"])
    if inspection.get("self_reported"):
        reasons.append("SELF_REPORT")
    usable = []
    for item in inspection.get("evidence", []):
        age = abs(observed - instant(item["capture_at"]))
        if age > timedelta(days=7):
            reasons.append("STALE_EVIDENCE")
            continue
        usable.append(item)
    kinds = {item["kind"] for item in usable}
    witnesses = {item["captured_by"] for item in usable}
    if not {"lean", "hollow"}.issubset(kinds) or len(witnesses) < 2:
        reasons.append("INSUFFICIENT_INDEPENDENT_EVIDENCE")
    if reasons:
        return "unverified", sorted(set(reasons)), usable
    lean = max(float(e.get("lean_angle_deg", 0)) for e in usable if e["kind"] == "lean")
    hollow = max(float(e.get("hollow_ratio", 0)) for e in usable if e["kind"] == "hollow")
    if lean >= 20 or hollow >= 0.4:
        return "urgent", [], usable
    if lean >= 10 or hollow >= 0.2:
        return "high", [], usable
    return "low", [], usable


def apply_tree(event, trees):
    item = event["tree"]
    tree_no = str(item["tree_no"])
    prior = trees.get(tree_no)
    identity = {key: item[key] for key in IDENTITY_FIELDS}
    if prior and prior["identity"] != identity:
        return "identity_conflict", ["TREE_IDENTITY_CONFLICT"], {"previous": prior["identity"]}
    revision = int(item["archive_version"])
    if prior and revision <= prior["archive_revision"]:
        return "archive_conflict", ["ARCHIVE_VERSION_NOT_NEWER"], {"current_revision": prior["archive_revision"]}
    assessments = []
    for inspection in event.get("inspections", []):
        risk, reasons, usable = inspection_score(inspection)
        assessments.append((instant(inspection["observed_at"]), risk, reasons, inspection, usable))
    if assessments:
        _, risk, reasons, chosen, usable = max(assessments, key=lambda part: part[0])
        observed_at = chosen["observed_at"]
    else:
        risk, reasons, usable, observed_at = "unverified", ["NO_INSPECTION"], [], None
    if prior and prior["basis"].get("observed_at") and observed_at:
        if instant(prior["basis"]["observed_at"]) > instant(observed_at):
            risk, reasons, observed_at = prior["risk"], ["OLDER_INSPECTION_RETAINED"], prior["basis"]["observed_at"]
    seal_from = observed_at if risk in ("high", "urgent") else None
    seal_to = (instant(observed_at) + timedelta(days=2 if risk == "urgent" else 7)).isoformat() if seal_from else None
    risk_revision = max(revision, prior["revision"] + 1) if prior else revision
    trees[tree_no] = {
        "tree_no": tree_no, "identity": identity, "risk": risk,
        "revision": risk_revision, "archive_revision": revision,
        "seal_revision": risk_revision,
        "seal_from": seal_from, "seal_to": seal_to,
        "seal_radius_m": 30 if risk == "urgent" else (12 if risk == "high" else 0),
        "released_at": None, "release_work_id": None,
        "basis": {"observed_at": observed_at, "evidence_ids": [e["evidence_id"] for e in usable],
                  "inspection_reasons": reasons},
    }
    return risk, reasons, {"revision": risk_revision, "archive_revision": revision,
                           "seal_to": seal_to,
                           "seal_radius_m": trees[tree_no]["seal_radius_m"],
                           "evidence_ids": trees[tree_no]["basis"]["evidence_ids"]}
