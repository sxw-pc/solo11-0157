"""Offline external-review evidence packets bound to one adjudication snapshot.

An external reviewer may recompute whether a pruning permit rested on two
independent inspectors, but may never learn the inspector roster.  This
module builds an anonymized packet from an internal snapshot obtained by
replaying the original source events through :mod:`treecase.engine`, and
decides which of the two contractual delivery routes may legally be used:

* ``expanded`` -- dual-witness codenames plus approved attachment
  projections for supervisors who keep per-item inspection rights.
* ``relationship-only`` -- a relation credential issued by an independent
  attestor under the same adjudication reference vouches for the
  distinctness of the two verified originals, the actual grade inputs and
  the recomputable effective time delta; the reviewer recomputes the
  permit but holds no per-item inspection rights afterwards.

Packets already handed over stay in the reviewer's hands, so the anonymity
analysis always unions the constraints of previously delivered public
material with whatever a new packet would reveal.  A route is refused and
left for manual review whenever the combined view would pin any restricted
witness to a single name, when distinctness is not grounded in the
verified originals, or when no credible relation credential exists.  A
column cannot be quietly dropped from an already delivered packet: the old
constraints are always part of the analysis.  Timestamps are emitted as
second offsets from one legal time origin so freshness and seal-window
checks remain recomputable without exposing absolute dates.
"""

import hashlib
import json
from datetime import timedelta
from itertools import product

from . import engine, permit_policy
from .tree_policy import inspection_score, instant


class PacketError(ValueError):
    """Raised when a review packet cannot be built from the ledger."""


ROUTES = ("expanded", "relationship-only")
GRADE_FIELDS = ("lean_angle_deg", "hollow_ratio")
RETENTION_SCOPE = "controlled-dossier"
AUDIENCE = "external-review"


def adjudication_ref(snapshot):
    """Reference binding a packet or credential to one adjudicated version."""
    return f"{snapshot['permit_id']}#rev{snapshot['tree']['revision']}"


def _offset(origin, value):
    return int((instant(value) - origin).total_seconds())


def _iso(origin, offset):
    return (origin + timedelta(seconds=offset)).isoformat()


def _grounding_inspection(rows, tree):
    observed = tree["basis"].get("observed_at")
    if not observed:
        return None, {}
    for row in rows:
        payload = json.loads(row["payload_json"])
        artifacts = json.loads(row["artifacts_json"])
        if row["kind"] == "tree" and str(payload["tree"]["tree_no"]) == tree["tree_no"]:
            for inspection in payload.get("inspections", []):
                if inspection.get("observed_at") == observed:
                    return inspection, artifacts
        elif row["kind"] == "work":
            work = payload.get("work", {})
            counter = work.get("counter_evidence")
            if counter and str(work.get("tree_no")) == tree["tree_no"] and counter.get("observed_at") == observed:
                return counter, artifacts
    return None, {}


def internal_snapshot(rows, permit_id):
    """Replay originals and capture the adjudication of ``permit_id`` as examined now.

    The same application is re-tried against the current tree file, so a
    later risk revision shows up exactly the way the baseline rules report
    it (for example ``STALE_RISK_REVISION``).
    """
    result = engine.replay(rows)
    permit = result["permits"].get(permit_id)
    if permit is None:
        raise PacketError(f"unknown permit: {permit_id}")
    tree = result["trees"].get(permit["tree_no"])
    if tree is None:
        raise PacketError(f"permit {permit_id} references unknown tree {permit['tree_no']}")
    state, reasons, _ = permit_policy.apply_permit({"permit": permit["terms"]}, {tree["tree_no"]: tree}, {})
    inspection, artifacts = _grounding_inspection(rows, tree)
    if inspection is None:
        raise PacketError(f"no grounding inspection for tree {tree['tree_no']} revision {tree['revision']}")
    decision = next((d for d in result["decisions"] if d["kind"] == "permit" and d["object_id"] == permit_id), None)
    evidence_items = []
    for item in inspection.get("evidence", []):
        entry = {"evidence_id": item["evidence_id"], "kind": item["kind"],
                 "capture_at": item["capture_at"], "captured_by": item["captured_by"],
                 "artifact_sha256": artifacts.get(item.get("file"), "")}
        for field in GRADE_FIELDS:
            if field in item:
                entry[field] = item[field]
        evidence_items.append(entry)
    snapshot = {
        "permit_id": permit_id,
        "decision_event_id": decision["event_id"] if decision else None,
        "adjudication": {"state": state, "reasons": list(reasons)},
        "tree": {key: tree[key] for key in ("tree_no", "identity", "risk", "revision",
                                            "archive_revision", "seal_from", "seal_to", "seal_radius_m")},
        "risk_reasons": list(tree["basis"].get("inspection_reasons", [])),
        "usable_evidence_ids": list(tree["basis"].get("evidence_ids", [])),
        "inspection": {"inspection_id": inspection.get("inspection_id"),
                       "observed_at": inspection["observed_at"],
                       "self_reported": bool(inspection.get("self_reported")),
                       "evidence": evidence_items},
        "permit_terms": dict(permit["terms"]),
    }
    snapshot["snapshot_digest"] = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()
    return snapshot


def witness_domains(people, constraints, distinct_pairs=(), equal_pairs=()):
    """Enumerate global identity explanations consistent with every constraint.

    An explanation assigns one person to each witness role and must satisfy
    all packets at once: a person cannot be A for one table and B for
    another.  ``distinct_pairs`` are publicly known inequalities (proven
    independent collectors), ``equal_pairs`` publicly visible equalities
    (one uploader behind one shared codename).
    """
    pairs = [tuple(pair) for pair in distinct_pairs] + [tuple(pair) for pair in equal_pairs]
    roles = sorted({c["witness"] for c in constraints} | {w for pair in pairs for w in pair})
    domains = {role: set(people) for role in roles}
    for constraint in constraints:
        domains[constraint["witness"]] &= set(constraint["possible_people"])
    explanations = []
    for combo in product(*(sorted(domains[role]) for role in roles)):
        mapping = dict(zip(roles, combo))
        if any(mapping[a] == mapping[b] for a, b in distinct_pairs):
            continue
        if any(mapping[a] != mapping[b] for a, b in equal_pairs):
            continue
        explanations.append(mapping)
    possibilities = {role: sorted({m[role] for m in explanations}) for role in roles}
    return {"roles": roles, "explanations": explanations, "possibilities": possibilities}


def _usable_items(snapshot):
    usable = set(snapshot["usable_evidence_ids"])
    return sorted((e for e in snapshot["inspection"]["evidence"] if e["evidence_id"] in usable),
                  key=lambda e: e["evidence_id"])


def _equal_pairs(usable):
    by_collector = {}
    for item in usable:
        by_collector.setdefault(item["captured_by"], set()).add(item["kind"])
    pairs = []
    for kinds in by_collector.values():
        ordered = sorted(kinds)
        pairs.extend((a, b) for i, a in enumerate(ordered) for b in ordered[i + 1:])
    return pairs


def _grade_inputs(usable):
    inputs = {}
    for item in usable:
        for field in GRADE_FIELDS:
            if field in item:
                value = float(item[field])
                inputs[field] = max(inputs.get(field, value), value)
    return inputs


def _capture_delta(usable):
    if len(usable) != 2:
        return None
    first, second = (instant(item["capture_at"]) for item in usable)
    return int(abs(first - second).total_seconds())


def _credential_problems(credential, snapshot, usable):
    problems = []
    if credential.get("adjudication_ref") != adjudication_ref(snapshot):
        problems.append("ADJUDICATION_REF_MISMATCH")
    if set(credential.get("evidence_ids") or []) != {item["evidence_id"] for item in usable}:
        problems.append("EVIDENCE_SET_MISMATCH")
    collectors = {item["captured_by"] for item in usable}
    attestor = credential.get("attestor_id")
    if not attestor or attestor in collectors:
        problems.append("ATTESTOR_NOT_INDEPENDENT")
    if credential.get("distinct") is not True:
        problems.append("DISTINCTNESS_NOT_ATTESTED")
    if len(collectors) < 2:
        problems.append("CONTRADICTS_ORIGINALS")
    claimed = {k: float(v) for k, v in (credential.get("grade_inputs") or {}).items()}
    if claimed != _grade_inputs(usable):
        problems.append("GRADE_INPUT_MISMATCH")
    if credential.get("effective_delta_seconds") != _capture_delta(usable):
        problems.append("TIME_DELTA_MISMATCH")
    return problems


def _select_credential(credentials, snapshot, usable):
    if not credentials:
        return None, "RELATION_CREDENTIAL_MISSING"
    best = None
    for credential in credentials:
        problems = _credential_problems(credential, snapshot, usable)
        if not problems:
            return credential, None
        if best is None or len(problems) < len(best):
            best = problems
    return None, "RELATION_CREDENTIAL_INVALID:" + "+".join(best)


def evaluate_routes(snapshot, constraints_doc, credentials):
    """Decide which delivery route may legally be issued for this snapshot."""
    people = constraints_doc["people"]
    old_constraints = list(constraints_doc.get("old_public_constraints", []))
    options = {option["id"]: option for option in constraints_doc.get("new_alias_options", [])}
    usable = _usable_items(snapshot)
    ground_distinct = len({item["captured_by"] for item in usable}) >= 2
    equal_pairs = _equal_pairs(usable)
    decisions = {}
    for route in ROUTES:
        option = options.get(route)
        if option is None:
            decisions[route] = {"issuable": False, "reasons": ["ROUTE_NOT_OFFERED"],
                                "analysis": None, "credential": None, "claimed_pairs": []}
            continue
        reasons = []
        claimed = option.get("proves_distinct") or []
        claimed_pairs = [tuple(claimed)] if claimed else []
        credential = None
        if claimed_pairs and not ground_distinct:
            reasons.append("DISTINCTNESS_NOT_IN_ORIGINALS")
        if route == "expanded":
            if any(not item["artifact_sha256"] for item in usable):
                reasons.append("ATTACHMENT_PROJECTION_MISSING")
            # Aliases are public in this route, so the reviewer sees the
            # ground truth: distinct uploaders show as distinct codenames,
            # one uploader shows as one shared codename.
            distinct_public = ground_distinct
            public_equal = [] if ground_distinct else equal_pairs
        else:
            credential, problem = _select_credential(credentials, snapshot, usable)
            if credential is None:
                reasons.append(problem)
            distinct_public = credential is not None and ground_distinct
            public_equal = []
        combined = old_constraints + list(option.get("constraints", []))
        analysis = witness_domains(
            people, combined,
            distinct_pairs=claimed_pairs if distinct_public else [],
            equal_pairs=public_equal)
        if not analysis["explanations"]:
            reasons.append("CONSTRAINTS_INCONSISTENT")
        else:
            for role, possible in analysis["possibilities"].items():
                if len(possible) < 2:
                    reasons.append(f"WITNESS_UNIQUELY_IDENTIFIABLE:{role}")
        decisions[route] = {"issuable": not reasons, "reasons": reasons,
                            "analysis": analysis, "credential": credential,
                            "claimed_pairs": claimed_pairs}
    return decisions


def _public_decisions(decisions):
    summary = {}
    for route, decision in decisions.items():
        entry = {"issuable": decision["issuable"], "reasons": list(decision["reasons"])}
        analysis = decision.get("analysis")
        if analysis:
            entry["explanations"] = len(analysis["explanations"])
            entry["witness_possibilities"] = {role: len(possible)
                                              for role, possible in analysis["possibilities"].items()}
        summary[route] = entry
    return summary


def issue_packet(snapshot, constraints_doc, attestations_doc=None, route=None):
    """Issue a packet for the snapshot, or explain why it stays manual.

    Without an explicit ``route`` the expanded packet is preferred whenever
    it is legal; the narrower relationship-only packet is the fallback.
    """
    credentials = list((attestations_doc or {}).get("credentials", []))
    decisions = evaluate_routes(snapshot, constraints_doc, credentials)
    if route is not None and route not in ROUTES:
        raise PacketError(f"unknown route: {route}")
    candidates = [route] if route else list(ROUTES)
    chosen = next((candidate for candidate in candidates if decisions[candidate]["issuable"]), None)
    summary = _public_decisions(decisions)
    target = {"permit_id": snapshot["permit_id"], "risk_revision": snapshot["tree"]["revision"],
              "adjudication_ref": adjudication_ref(snapshot)}
    if chosen is None:
        return {"issued": False, "manual_review": True, "target": target, "route_decisions": summary}
    packet = _build_packet(snapshot, decisions[chosen], chosen)
    return {"issued": True, "route": chosen, "packet": packet, "route_decisions": summary}


def _access_block(route):
    if route == "expanded":
        return {"originals_inspectable": True, "per_item_lookup": True,
                "attachment_projection": True, "retention_scope": RETENTION_SCOPE}
    return {"originals_inspectable": False, "per_item_lookup": False,
            "attachment_projection": False, "closed_review": True}


def _distinctness_basis(route, decision):
    if not decision["claimed_pairs"]:
        return None
    return "issuer-verified-dual-originals" if route == "expanded" else "relation-credential"


def _build_packet(snapshot, decision, route):
    origin = instant(snapshot["inspection"]["observed_at"]).replace(hour=0, minute=0, second=0, microsecond=0)
    usable = _usable_items(snapshot)
    aliases = {collector: f"WITNESS-{index + 1}"
               for index, collector in enumerate(sorted({item["captured_by"] for item in usable}))}
    evidence = []
    for item in usable:
        entry = {"kind": item["kind"], "capture_offset": _offset(origin, item["capture_at"])}
        for field in GRADE_FIELDS:
            if field in item:
                entry[field] = item[field]
        if route == "expanded":
            entry["alias"] = aliases[item["captured_by"]]
            entry["attachment_sha256"] = item["artifact_sha256"]
            entry["retention_scope"] = RETENTION_SCOPE
        evidence.append(entry)
    terms = snapshot["permit_terms"]
    tree = snapshot["tree"]
    analysis = decision["analysis"]
    packet = {
        "packet_type": "treecase.review_packet.v1",
        "route": route,
        "audience": AUDIENCE,
        "target": {"permit_id": snapshot["permit_id"],
                   "decision_event_id": snapshot["decision_event_id"],
                   "risk_revision": tree["revision"],
                   "adjudication_ref": adjudication_ref(snapshot),
                   "snapshot_digest": snapshot["snapshot_digest"]},
        "time_origin": origin.isoformat(),
        "time_unit": "seconds",
        "tree": {"identity": tree["identity"], "archive_revision": tree["archive_revision"],
                 "risk_revision": tree["revision"]},
        "inspection": {"observed_offset": _offset(origin, snapshot["inspection"]["observed_at"]),
                       "self_reported": snapshot["inspection"]["self_reported"],
                       "evidence": evidence},
        "adjudication": {"risk": tree["risk"], "risk_reasons": list(snapshot["risk_reasons"]),
                         "seal": {"from_offset": _offset(origin, tree["seal_from"]) if tree["seal_from"] else None,
                                  "to_offset": _offset(origin, tree["seal_to"]) if tree["seal_to"] else None,
                                  "radius_m": tree["seal_radius_m"]},
                         "permit_outcome": snapshot["adjudication"]["state"],
                         "permit_reasons": list(snapshot["adjudication"]["reasons"])},
        "permit": {"permit_id": terms["permit_id"], "tree_no": str(terms["tree_no"]),
                   "block_id": terms["block_id"], "grid_code": terms["grid_code"], "tag_id": terms["tag_id"],
                   "requested_action": terms["requested_action"],
                   "max_cut_diameter_cm": terms["max_cut_diameter_cm"],
                   "max_cut_count": terms["max_cut_count"],
                   "valid_from_offset": _offset(origin, terms["valid_from"]),
                   "valid_to_offset": _offset(origin, terms["valid_to"]),
                   "applied_offset": _offset(origin, terms["applied_at"]),
                   "approved_offset": _offset(origin, terms["approved_at"]),
                   "risk_revision": terms["risk_revision"],
                   "protected_authorization": terms.get("protected_authorization"),
                   "signer_id": terms.get("signer_id"),
                   "signature_present": bool(terms.get("signature_file"))},
        "distinctness": {"pairs": [list(pair) for pair in decision["claimed_pairs"]],
                         "basis": _distinctness_basis(route, decision)},
        "access": _access_block(route),
        "privacy": {"explanations": len(analysis["explanations"]),
                    "witness_possibilities": {role: len(possible)
                                              for role, possible in analysis["possibilities"].items()}},
    }
    if route == "relationship-only":
        credential = decision["credential"]
        packet["relation_credential"] = {
            "credential_id": credential["credential_id"],
            "adjudication_ref": credential["adjudication_ref"],
            "attestor_id": credential["attestor_id"],
            "distinct": True,
            "grade_inputs": {k: float(v) for k, v in credential["grade_inputs"].items()},
            "effective_delta_seconds": credential["effective_delta_seconds"]}
        packet["distinctness"]["credential_id"] = credential["credential_id"]
    packet["packet_id"] = "RP-" + hashlib.sha256(
        json.dumps(packet, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return packet


def _credential_block_problems(packet, credential):
    if not credential:
        return ["RELATION_CREDENTIAL_MISSING"]
    problems = []
    if credential.get("adjudication_ref") != packet["target"]["adjudication_ref"]:
        problems.append("ADJUDICATION_REF_MISMATCH")
    if credential.get("distinct") is not True:
        problems.append("DISTINCTNESS_NOT_ATTESTED")
    if not credential.get("attestor_id"):
        problems.append("ATTESTOR_MISSING")
    inputs = {}
    for item in packet["inspection"]["evidence"]:
        for field in GRADE_FIELDS:
            if field in item:
                value = float(item[field])
                inputs[field] = max(inputs.get(field, value), value)
    claimed = {k: float(v) for k, v in (credential.get("grade_inputs") or {}).items()}
    if claimed != inputs:
        problems.append("GRADE_INPUT_MISMATCH")
    items = packet["inspection"]["evidence"]
    if len(items) == 2:
        delta = abs(items[0]["capture_offset"] - items[1]["capture_offset"])
        if credential.get("effective_delta_seconds") != delta:
            problems.append("TIME_DELTA_MISMATCH")
    return problems


def _verify_distinctness(packet, route, credential):
    pairs = packet["distinctness"].get("pairs") or []
    if not pairs:
        return True, []
    if route == "expanded":
        aliases = {item["kind"]: item.get("alias") for item in packet["inspection"]["evidence"]}
        if all(aliases.get(a) and aliases.get(b) and aliases[a] != aliases[b] for a, b in pairs):
            return True, []
        return False, ["DISTINCTNESS_UNPROVEN"]
    problems = _credential_block_problems(packet, credential)
    return (not problems), problems


def verify_packet(packet):
    """Recompute the adjudication from packet fields alone.

    The reviewer reruns the same tree-grade and permit rules on shifted
    timestamps, checks freshness and the seal window, and confirms the
    distinctness claim matches what the packet actually proves.
    """
    problems = []
    body = {key: value for key, value in packet.items() if key != "packet_id"}
    expected_id = "RP-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    if packet.get("packet_id") != expected_id:
        problems.append("PACKET_ID_MISMATCH")
    origin = instant(packet["time_origin"])
    route = packet["route"]
    target = packet["target"]
    if target.get("adjudication_ref") != f"{target['permit_id']}#rev{target['risk_revision']}":
        problems.append("ADJUDICATION_REF_MISMATCH")
    credential = packet.get("relation_credential")
    evidence = []
    for index, item in enumerate(packet["inspection"]["evidence"]):
        rebuilt = {"kind": item["kind"], "capture_at": _iso(origin, item["capture_offset"]),
                   "evidence_id": f"packet-item-{index + 1}"}
        for field in GRADE_FIELDS:
            if field in item:
                rebuilt[field] = item[field]
        if route == "expanded":
            rebuilt["captured_by"] = item.get("alias", "UNALIASSED-COLLECTOR")
        elif credential:
            rebuilt["captured_by"] = f"{credential['credential_id']}#{index + 1}"
        else:
            rebuilt["captured_by"] = "UNATTESTED-COLLECTOR"
        evidence.append(rebuilt)
    inspection = {"observed_at": _iso(origin, packet["inspection"]["observed_offset"]),
                  "self_reported": packet["inspection"]["self_reported"], "evidence": evidence}
    risk, risk_reasons, _ = inspection_score(inspection)
    adjudication = packet["adjudication"]
    if risk != adjudication["risk"]:
        problems.append("RISK_MISMATCH")
    if sorted(risk_reasons) != sorted(adjudication["risk_reasons"]):
        problems.append("RISK_REASON_MISMATCH")
    seal = adjudication["seal"]
    tree = {"identity": packet["tree"]["identity"], "risk": risk,
            "revision": packet["tree"]["risk_revision"],
            "seal_from": _iso(origin, seal["from_offset"]) if seal["from_offset"] is not None else None,
            "seal_to": _iso(origin, seal["to_offset"]) if seal["to_offset"] is not None else None}
    permit = packet["permit"]
    terms = {"permit_id": permit["permit_id"], "tree_no": permit["tree_no"],
             "block_id": permit["block_id"], "grid_code": permit["grid_code"], "tag_id": permit["tag_id"],
             "requested_action": permit["requested_action"],
             "max_cut_diameter_cm": permit["max_cut_diameter_cm"], "max_cut_count": permit["max_cut_count"],
             "valid_from": _iso(origin, permit["valid_from_offset"]),
             "valid_to": _iso(origin, permit["valid_to_offset"]),
             "applied_at": _iso(origin, permit["applied_offset"]),
             "approved_at": _iso(origin, permit["approved_offset"]),
             "risk_revision": permit["risk_revision"],
             "protected_authorization": permit["protected_authorization"],
             "signer_id": permit["signer_id"],
             "signature_file": "attested" if permit["signature_present"] else None}
    outcome, reasons, _ = permit_policy.apply_permit({"permit": terms}, {terms["tree_no"]: tree}, {})
    if outcome != adjudication["permit_outcome"]:
        problems.append("PERMIT_OUTCOME_MISMATCH")
    if sorted(reasons) != sorted(adjudication["permit_reasons"]):
        problems.append("PERMIT_REASON_MISMATCH")
    freshness_ok = "STALE_EVIDENCE" not in risk_reasons
    seal_window_ok = True
    if risk in ("high", "urgent"):
        seal_window_ok = bool(tree["seal_from"] <= terms["approved_at"] <= tree["seal_to"])
    distinctness_ok, distinctness_problems = _verify_distinctness(packet, route, credential)
    problems.extend(distinctness_problems)
    if route == "relationship-only":
        for item in packet["inspection"]["evidence"]:
            if "alias" in item or "attachment_sha256" in item:
                problems.append("ACCESS_BOUNDARY_VIOLATION")
    return {"valid": not problems, "problems": problems,
            "recomputed_risk": risk, "recomputed_risk_reasons": sorted(risk_reasons),
            "recomputed_outcome": outcome, "recomputed_reasons": sorted(reasons),
            "freshness_ok": freshness_ok, "seal_window_ok": seal_window_ok,
            "distinctness_ok": distinctness_ok}
