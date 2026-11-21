"""Permit authorization, seal fit, temporal windows and revocation."""

from .tree_policy import instant


def _same_identity(record, tree):
    return all(record.get(key) == tree["identity"].get(key) for key in ("tree_no", "block_id", "grid_code", "tag_id"))


def apply_permit(event, trees, permits):
    item = event["permit"]
    permit_id, tree_no = item["permit_id"], str(item["tree_no"])
    reasons = []
    tree = trees.get(tree_no)
    if permit_id in permits:
        reasons.append("DUPLICATE_PERMIT")
    if tree is None:
        reasons.append("UNKNOWN_TREE")
    else:
        if not _same_identity(item, tree):
            reasons.append("PERMIT_TREE_IDENTITY_MISMATCH")
        if int(item["risk_revision"]) != tree["revision"]:
            reasons.append("STALE_RISK_REVISION")
        if tree["risk"] == "unverified":
            reasons.append("UNVERIFIED_TREE_RISK")
        if tree["risk"] in ("high", "urgent") and not (tree["seal_from"] <= item["approved_at"] <= tree["seal_to"]):
            reasons.append("SEAL_NOT_ACTIVE_AT_APPROVAL")
        if tree["identity"]["protected_level"] != "ordinary" and item["requested_action"] in ("remove", "prune"):
            if not item.get("protected_authorization"):
                reasons.append("PROTECTED_AUTHORIZATION_MISSING")
    if not (instant(item["applied_at"]) <= instant(item["approved_at"]) <= instant(item["valid_to"])):
        reasons.append("INVALID_APPROVAL_TIME")
    if not instant(item["valid_from"]) < instant(item["valid_to"]):
        reasons.append("INVALID_PERMIT_WINDOW")
    if not item.get("signer_id") or not item.get("signature_file"):
        reasons.append("UNSIGNED_PERMIT")
    for other in permits.values():
        terms = other["terms"]
        if other["tree_no"] == tree_no and other["state"] == "approved" and (
            item["valid_from"] <= terms["valid_to"] and terms["valid_from"] <= item["valid_to"]
        ) and item["requested_action"] != terms["requested_action"]:
            reasons.append("CONFLICTING_PARALLEL_PERMIT")
    state = "denied" if reasons else "approved"
    permits[permit_id] = {"permit_id": permit_id, "tree_no": tree_no, "state": state,
                          "reasons": sorted(set(reasons)), "terms": item, "revoked_at": None}
    return state, sorted(set(reasons)), {"risk_revision": tree["revision"] if tree else None}


def apply_revocation(event, trees, permits, works):
    notice = event["revocation"]
    permit = permits.get(notice["permit_id"])
    if not permit:
        return "unmatched", ["UNKNOWN_PERMIT"], {}
    if permit["revoked_at"]:
        return "duplicate", ["ALREADY_REVOKED"], {}
    permit["revoked_at"] = notice["revoked_at"]
    permit["state"] = "revoked"
    permit["reasons"].append("AUTHORITY_REVOKED")
    disputed = []
    for work in works.values():
        if work["permit_id"] == notice["permit_id"] and work["state"] == "accepted":
            work["state"] = "disputed"
            work["reasons"].append("PERMIT_REVOKED_AFTER_WORK")
            disputed.append(work["work_id"])
            tree = trees.get(str(work["receipt"]["tree_no"]))
            if tree and tree["release_work_id"] == work["work_id"]:
                tree["released_at"] = None
                tree["release_work_id"] = None
                if tree["basis"].get("counter_event") == work["source_event_id"]:
                    tree["risk"] = tree["basis"]["prior_risk"]
                    tree["basis"] = tree["basis"]["prior_basis"]
                    tree["revision"] += 1
    return "revoked", [], {"disputed_work_ids": disputed}
