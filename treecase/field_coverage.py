"""Adjudicate the minimum signable coverage of synthetic integer-grid transects.

A transect contract is recorded in local segment coordinates. A clamp change
opens a new *round*: every segment of one round shares one translation, one
direction and one clamp scale. Only independent originals can lock a round's
translation to the absolute plot grid.

Two kinds of field evidence may certify coverage:

* two independent control points observed while the original clamp is still
  mounted, which map the whole track onto the absolute grid and certify a
  positioning review;
* a three-part closure control receipt (start anchor, shared endpoint
  relation, actual closure) for one undisturbed measuring chain. Closure may
  leave the absolute position ambiguous as long as every possible placement
  stays inside the contracted range and reaches the required coverage.

The signable quantity is the minimum true union over every equally credible
interpretation that satisfies all common evidence. Cells from different
interpretations are never stitched together, and a per-cell intersection is
never sold as a guaranteed total.
"""

import itertools
import json

RELATIONS = ("disjoint", "adjacent")


def _is_int(value):
    return type(value) is int


def _validate_span(span, label):
    if not isinstance(span, list) or len(span) != 2 or not all(_is_int(v) for v in span):
        raise ValueError(f"{label} must be a half-open integer span [lo, hi)")
    lo, hi = span
    if lo >= hi:
        raise ValueError(f"{label} must be a non-empty half-open span")
    return lo, hi


def _merge(cells):
    """Merge a sorted iterable of grid cells into half-open spans."""
    spans = []
    for cell in cells:
        if spans and cell == spans[-1][1]:
            spans[-1][1] = cell + 1
        else:
            spans.append([cell, cell + 1])
    return spans


def _placement(local, translation, direction):
    lo, hi = local
    length = hi - lo
    if direction == 1:
        start = translation + lo
    else:
        start = translation - hi
    return start, start + length


def _structure(evidence):
    if evidence.get("shape") != "field_contract":
        raise ValueError("field_contract evidence required")
    if not _is_int(evidence.get("minimum")) or evidence["minimum"] <= 0:
        raise ValueError("positive integer minimum required")
    range_lo, range_hi = _validate_span(evidence["contract_range"], "contract_range")

    rounds = {}
    for round_ in evidence.get("rounds", []):
        rid = round_.get("id")
        if not rid or rid in rounds:
            raise ValueError("round ids must be unique non-empty strings")
        direction = round_.get("direction", 1)
        scale = round_.get("scale", 1)
        if direction not in (-1, 1) or not _is_int(scale) or scale <= 0:
            raise ValueError(f"round {rid}: direction must be +/-1 and scale a positive integer")
        if not isinstance(round_.get("clamp_intact"), bool):
            raise ValueError(f"round {rid}: clamp_intact must be a boolean")
        rounds[rid] = {"id": rid, "direction": direction, "scale": scale,
                       "clamp_intact": round_["clamp_intact"]}

    segments = {}
    originals = {}
    for segment in evidence.get("segments", []):
        sid = segment.get("id")
        if not sid or sid in segments:
            raise ValueError("segment ids must be unique non-empty strings")
        rid = segment.get("round_id")
        if rid not in rounds:
            raise ValueError(f"segment {sid} references unknown round {rid}")
        local = _validate_span(segment["local"], f"segment {sid}.local")
        original_id = segment.get("original_id")
        if not isinstance(original_id, str) or not original_id:
            raise ValueError(f"segment {sid}: original_id is required")
        translations = segment.get("candidate_translations")
        if not isinstance(translations, list) or not translations or any(
                not _is_int(t) for t in translations) or len(set(translations)) != len(translations):
            raise ValueError(f"segment {sid}: candidate_translations must be distinct integers")
        scale = rounds[rid]["scale"]
        if any(t % scale != 0 for t in translations):
            raise ValueError(f"segment {sid}: translations must match the clamp scale {scale}")
        segments[sid] = {"id": sid, "round_id": rid, "local": local,
                         "original_id": original_id,
                         "candidates": tuple(sorted(translations))}
        originals.setdefault(original_id, []).append(sid)

    if not segments:
        raise ValueError("at least one segment is required")

    controls = {}
    for point in evidence.get("control_points", []):
        rid = point.get("round_id")
        if rid not in rounds:
            raise ValueError(f"control point {point.get('id')} references unknown round {rid}")
        if not _is_int(point.get("locked_translation")):
            raise ValueError(f"control point {point.get('id')}: locked_translation integer required")
        witness = point.get("witness_id")
        if not isinstance(witness, str) or not witness:
            raise ValueError(f"control point {point.get('id')}: independent witness_id required")
        if any(p["id"] == point.get("id") for p in controls.get(rid, [])):
            raise ValueError(f"round {rid}: duplicated control point id {point.get('id')}")
        controls.setdefault(rid, []).append(point)

    closures = []
    for receipt in evidence.get("closures", []):
        cid = receipt.get("id")
        if not cid or any(c["id"] == cid for c in closures):
            raise ValueError("closure ids must be unique non-empty strings")
        named = receipt.get("segments")
        if not isinstance(named, list) or len(named) < 2 or any(s not in segments for s in named):
            raise ValueError(f"closure {cid}: segments must name at least two known segments")
        if receipt.get("start_segment") not in named:
            raise ValueError(f"closure {cid}: start_segment must be one of its segments")
        relation = receipt.get("endpoint_relation")
        if relation not in RELATIONS:
            raise ValueError(f"closure {cid}: endpoint_relation must be one of {RELATIONS}")
        if not isinstance(receipt.get("actual_closure"), bool):
            raise ValueError(f"closure {cid}: actual_closure must be a boolean")
        closures.append({"id": cid, "segments": list(named),
                         "start_segment": receipt["start_segment"], "relation": relation,
                         "actual_closure": receipt["actual_closure"]})

    return range_lo, range_hi, rounds, segments, originals, controls, closures


def _duplicate_conflict(segments, originals):
    """Same physical original recorded twice with incompatible records."""
    for original_id, sids in originals.items():
        if len(sids) < 2:
            continue
        signatures = {(segments[s]["round_id"], tuple(segments[s]["local"]),
                       segments[s]["candidates"]) for s in sids}
        if len(signatures) > 1:
            return original_id
    return None


def evaluate(evidence):
    """Return the coverage commitment that the recorded originals support."""
    range_lo, range_hi, rounds, segments, originals, controls, closures = _structure(evidence)
    minimum = evidence["minimum"]
    basis_originals = sorted(originals)
    base = {
        "minimum": minimum,
        "contract_range": [range_lo, range_hi],
        "basis_originals": basis_originals,
        "interpretations": [],
    }

    conflicted = _duplicate_conflict(segments, originals)
    if conflicted is not None:
        return base | {
            "status": "withheld", "reason": "duplicate_conflict",
            "coverage_floor": 0, "coverage_max": 0, "certain_spans": [],
            "position_certified": False, "position_review_available": False,
            "interpretation_count": 0,
            "notes": [f"original {conflicted} arrived with incompatible records; originals held for verification"],
        }

    # One domain per round: the translations every segment of the round can
    # share, intersected with a control-point lock when the clamp survives.
    domains = {rid: None for rid in rounds}
    notes = []
    for segment in segments.values():
        rid = segment["round_id"]
        allowed = set(segment["candidates"])
        domains[rid] = allowed if domains[rid] is None else domains[rid] & allowed
    for rid, points in controls.items():
        locked = {p["locked_translation"] for p in points}
        if not rounds[rid]["clamp_intact"]:
            notes.append(f"round {rid}: clamp dismantled, current control points cannot back-project the track")
            continue
        witnesses = {p["witness_id"] for p in points}
        if len(witnesses) < 2:
            notes.append(f"round {rid}: two independent control points are required to lock translation")
            continue
        if len(locked) != 1:
            return base | {
                "status": "withheld", "reason": "contradictory_evidence",
                "coverage_floor": 0, "coverage_max": 0, "certain_spans": [],
                "position_certified": False, "position_review_available": False,
                "interpretation_count": 0,
                "notes": [f"round {rid}: independent control points disagree on translation; originals held for verification"],
            }
        domains[rid] = (domains[rid] or set()) & locked

    domains = {rid: tuple(sorted(domain or ())) for rid, domain in domains.items()}
    active_rounds = sorted({s["round_id"] for s in segments.values()})
    # A round supports a positioning review when the surviving original clamp
    # carries two independent control points, or when the original itself
    # permits only one legal translation (an anchored starting segment).
    review_rounds = []
    for rid in active_rounds:
        locked_by_controls = (rounds[rid]["clamp_intact"]
                              and len({p["witness_id"] for p in controls.get(rid, ())}) >= 2)
        if locked_by_controls or len(domains[rid]) == 1:
            review_rounds.append(rid)
    position_review_available = len(review_rounds) == len(active_rounds)

    if any(not domains[rid] for rid in active_rounds):
        return base | {
            "status": "withheld", "reason": "infeasible",
            "coverage_floor": 0, "coverage_max": 0, "certain_spans": [],
            "position_certified": False,
            "position_review_available": position_review_available,
            "interpretation_count": 0,
            "notes": notes + ["segments of one round share no legal translation"],
        }

    # Distinct originals only: re-submissions of the same physical segment are
    # counted once and can never double the covered total.
    witness_segments = []
    seen_originals = set()
    for sid in sorted(segments):
        segment = segments[sid]
        if segment["original_id"] in seen_originals:
            continue
        seen_originals.add(segment["original_id"])
        witness_segments.append(segment)

    interpretations = []
    round_choices = [domains[rid] for rid in active_rounds]
    for values in itertools.product(*round_choices):
        translations = dict(zip(active_rounds, values))
        placed = {}
        in_range = True
        for segment in witness_segments:
            rid = segment["round_id"]
            start, end = _placement(segment["local"], translations[rid], rounds[rid]["direction"])
            if start < range_lo or end > range_hi:
                in_range = False
                break
            placed[segment["id"]] = (start, end)
        if not in_range:
            continue

        satisfied = True
        for receipt in closures:
            if not receipt["actual_closure"]:
                continue
            chain = [placed[sid] for sid in receipt["segments"] if sid in placed]
            for (prev_start, prev_end), (next_start, next_end) in zip(chain, chain[1:]):
                if receipt["relation"] == "disjoint":
                    if not (prev_end <= next_start or next_end <= prev_start):
                        satisfied = False
                        break
                else:  # adjacent: a genuine shared endpoint on the same line
                    if prev_end != next_start:
                        satisfied = False
                        break
            if not satisfied:
                break
        if not satisfied:
            continue

        union_cells = sorted({cell for start, end in placed.values() for cell in range(start, end)})
        interpretations.append({
            "translations": translations,
            "union_spans": _merge(union_cells),
            "union_size": len(union_cells),
            "union_cells": union_cells,
        })

    if not interpretations:
        return base | {
            "status": "withheld", "reason": "infeasible",
            "coverage_floor": 0, "coverage_max": 0, "certain_spans": [],
            "position_certified": False,
            "position_review_available": position_review_available,
            "interpretation_count": 0,
            "notes": notes + ["no interpretation satisfies the closure control receipts inside the range"],
        }

    floor = min(item["union_size"] for item in interpretations)
    ceiling = max(item["union_size"] for item in interpretations)
    certain = set(interpretations[0]["union_cells"])
    for item in interpretations[1:]:
        certain &= set(item["union_cells"])
    unique_union = all(item["union_spans"] == interpretations[0]["union_spans"]
                       for item in interpretations[1:])
    position_certified = position_review_available and unique_union
    if floor >= minimum:
        status, reason = "ready", "coverage_floor_met"
    elif len(interpretations) > 1 and not position_review_available:
        status, reason = "withheld", "pending_verification"
    else:
        status, reason = "withheld", "below_minimum"
    if not position_review_available and all(
            rounds[rid]["clamp_intact"] for rid in active_rounds) and not controls:
        notes.append("no independent control points or closure receipts bind the local segments")

    return {
        "status": status,
        "reason": reason,
        "minimum": minimum,
        "contract_range": [range_lo, range_hi],
        "coverage_floor": floor,
        "coverage_max": ceiling,
        "certain_spans": _merge(sorted(certain)),
        "position_certified": position_certified,
        "position_review_available": position_review_available,
        "interpretation_count": len(interpretations),
        "interpretations": [{
            "translations": item["translations"],
            "union_spans": item["union_spans"],
            "union_size": item["union_size"],
        } for item in interpretations],
        "basis_originals": basis_originals,
        "notes": notes,
    }


def setup(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS field_coverage(
            case_id TEXT PRIMARY KEY,
            evidence_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            coverage_floor INTEGER NOT NULL,
            minimum INTEGER NOT NULL,
            certain_spans_json TEXT NOT NULL,
            position_certified INTEGER NOT NULL,
            position_review_available INTEGER NOT NULL,
            interpretation_count INTEGER NOT NULL,
            basis_json TEXT NOT NULL,
            result_json TEXT NOT NULL
        )"""
    )


def save(db, case_id, evidence_id, result):
    """Persist an adjudication and return the stored projection row."""
    setup(db)
    row = (case_id, evidence_id, result["status"], result["reason"],
           int(result["coverage_floor"]), int(result["minimum"]),
           json.dumps(result["certain_spans"], sort_keys=True),
           int(result["position_certified"]), int(result["position_review_available"]),
           int(result["interpretation_count"]),
           json.dumps(result["basis_originals"], sort_keys=True),
           json.dumps(result, sort_keys=True, separators=(",", ":")))
    db.execute(
        """INSERT INTO field_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(case_id) DO UPDATE SET
             evidence_id=excluded.evidence_id, status=excluded.status, reason=excluded.reason,
             coverage_floor=excluded.coverage_floor, minimum=excluded.minimum,
             certain_spans_json=excluded.certain_spans_json,
             position_certified=excluded.position_certified,
             position_review_available=excluded.position_review_available,
             interpretation_count=excluded.interpretation_count,
             basis_json=excluded.basis_json, result_json=excluded.result_json""",
        row,
    )
    return row
