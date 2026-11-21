"""Field-work scope, temporal legality and independent release review."""

import math

from .tree_policy import inspection_score, instant


def apply_work(event, trees, permits, works):
    item = event["work"]
    work_id, permit_id = item["work_id"], item["permit_id"]
    reasons = []
    permit = permits.get(permit_id)
    tree = trees.get(str(item["tree_no"]))
    when = item["performed_at"]
    if work_id in works:
        reasons.append("DUPLICATE_WORK")
    if not permit or permit["state"] != "approved":
        reasons.append("NO_ACTIVE_PERMIT")
    else:
        terms = permit["terms"]
        if permit["tree_no"] != str(item["tree_no"]) or any(
            item.get(k) != terms.get(k) for k in ("block_id", "grid_code", "tag_id")
        ):
            reasons.append("WORK_TREE_IDENTITY_MISMATCH")
        if not (terms["valid_from"] <= when <= terms["valid_to"]):
            reasons.append("WORK_OUTSIDE_PERMIT_WINDOW")
        if instant(when) < instant(terms["approved_at"]):
            reasons.append("WORK_BEFORE_APPROVAL")
        if tree is not None and int(terms["risk_revision"]) != tree["revision"]:
            reasons.append("PERMIT_RISK_REVISION_STALE_AT_WORK")
        if permit["revoked_at"] and when >= permit["revoked_at"]:
            reasons.append("WORK_AFTER_REVOCATION")
        cuts = item.get("cuts", [])
        if not cuts and terms["requested_action"] == "prune":
            reasons.append("NO_CUT_RECEIPT")
        count = 0
        for cut in cuts:
            n, diameter = cut.get("count"), cut.get("diameter_cm")
            if not isinstance(n, int) or n <= 0 or not isinstance(diameter, (int, float)) or not math.isfinite(diameter) or diameter <= 0:
                raise ValueError("cut count and diameter must be positive finite numbers")
            count += n
            if diameter > float(terms["max_cut_diameter_cm"]):
                reasons.append("CUT_DIAMETER_OVER_SCOPE")
        if count > int(terms["max_cut_count"]):
            reasons.append("CUT_COUNT_OVER_SCOPE")
    if tree is None:
        reasons.append("UNKNOWN_TREE")
    elif tree["risk"] in ("high", "urgent") and not (tree["seal_from"] <= when <= tree["seal_to"]):
        reasons.append("SEAL_NOT_ACTIVE_AT_WORK")
    review = item.get("reinspection")
    if not review:
        reasons.append("REINSPECTION_MISSING")
    else:
        if not review.get("stable"):
            reasons.append("REINSPECTION_UNSTABLE")
        if review.get("witness_id") == item.get("operator_id") or review.get("witness_org") == item.get("contractor_id"):
            reasons.append("REINSPECTION_NOT_INDEPENDENT")
        if instant(review["witnessed_at"]) < instant(when):
            reasons.append("REINSPECTION_BEFORE_WORK")
    counter = item.get("counter_evidence")
    counter_risk = None
    counter_items = []
    if counter:
        counter_risk, counter_reasons, counter_items = inspection_score(counter)
        if counter.get("inspector_id") == item.get("operator_id") or counter.get("inspector_org") == item.get("contractor_id"):
            reasons.append("COUNTER_EVIDENCE_NOT_INDEPENDENT")
        if instant(counter["observed_at"]) < instant(when):
            reasons.append("COUNTER_EVIDENCE_BEFORE_WORK")
        if counter_reasons:
            reasons.append("COUNTER_EVIDENCE_UNVERIFIED")
        if counter_risk in ("high", "urgent"):
            reasons.append("COUNTER_EVIDENCE_RISK_REMAINS")
    state = "held" if reasons else "accepted"
    works[work_id] = {"work_id": work_id, "permit_id": permit_id, "state": state,
                      "reasons": sorted(set(reasons)), "receipt": item,
                      "source_event_id": event["event_id"]}
    if state == "accepted" and tree and tree["risk"] in ("high", "urgent"):
        tree["released_at"] = review["witnessed_at"]
        tree["release_work_id"] = work_id
        if counter_risk == "low":
            prior_risk = tree["risk"]
            prior_basis = tree["basis"]
            tree["risk"] = "low"
            tree["revision"] += 1
            tree["basis"] = {"observed_at": counter["observed_at"],
                             "evidence_ids": [e["evidence_id"] for e in counter_items],
                             "counter_event": event["event_id"], "prior_risk": prior_risk,
                             "prior_basis": prior_basis,
                             "inspection_reasons": []}
    return state, sorted(set(reasons)), {"tree_risk": tree["risk"] if tree else None,
                                          "counter_risk": counter_risk,
                                          "seal_released": bool(tree and tree["release_work_id"] == work_id)}
