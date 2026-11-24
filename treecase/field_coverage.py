"""Synthetic transect coverage adjudication under mounting-round uncertainty.

A field contract records local half-open integer intervals per physical
segment, the mounting rounds they belong to, the legal plot range and the
original field evidence.  A round shares one translation, direction and
fixture scale; only independent original records can pin it.  Every
feasible interpretation must explain all common evidence and stay inside
the plot range.

Two independent sign-off paths are modelled:

* two independent control points on an observation still in its original
  mounting lock the round translation onto the absolute grid, certifying
  positions and whether a positioning re-survey can be provided;
* three closed-control receipts (origin, shared endpoint relation and
  actual closure) kept for an un-broken measurement chain can certify a
  coverage total while the absolute position stays ambiguous between
  legal regions.  Closure only constrains the rounds its chain contains.

The signable coverage lower bound is the smallest true union over every
equally credible interpretation.  A cell is reported as a certain
position only when every interpretation covers it.  Cells from different
interpretations are never stitched into a larger union, and the per-cell
intersection is never mistaken for the guaranteed total.
"""

from itertools import product

SCHEMA = "treecase.field_contract.v1"

# Adjudication reason codes.
PENDING_VERIFICATION = "PENDING_VERIFICATION"
COVERAGE_NOT_ASSURED = "COVERAGE_NOT_ASSURED"
CANNOT_REACH_MINIMUM = "CANNOT_REACH_MINIMUM"
NO_SHARED_ROUND_TRANSLATION = "NO_SHARED_ROUND_TRANSLATION"
NO_FEASIBLE_INTERPRETATION = "NO_FEASIBLE_INTERPRETATION"
CONTROL_POINT_CONFLICT = "CONTROL_POINT_CONFLICT"
MOUNTING_DISMANTLED = "MOUNTING_DISMANTLED_CONTROL_UNUSABLE"
CLOSURE_CHAIN_BROKEN = "CLOSURE_CHAIN_BROKEN"
CLOSURE_OUTSIDE_CHAIN = "CLOSURE_RELATION_OUTSIDE_CHAIN"
SOURCE_CONFLICT = "SOURCE_CONFLICT"
CONTRACT_TERMS_CONFLICT = "CONTRACT_TERMS_CONFLICT"
ROUND_RECORD_CONFLICT = "ROUND_RECORD_CONFLICT"

RELATIONS = ("disjoint", "abut")
CLOSURE_RECEIPTS = ("origin", "endpoint_relation", "closure")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _is_int_span(value):
    return (isinstance(value, list) and len(value) == 2
            and type(value[0]) is int and type(value[1]) is int and value[0] < value[1])


def _is_string_list(value):
    return isinstance(value, list) and len(value) >= 1 and all(isinstance(v, str) and v for v in value)


def _evidence_sources(item):
    if "source_ids" in item:
        return tuple(item["source_ids"])
    return (item["source_id"],)


def validate_contract(contract):
    """Reject structurally malformed contracts; semantic gaps become reasons."""
    _require(isinstance(contract, dict), "contract object required")
    _require(isinstance(contract.get("id"), str) and contract["id"], "contract id required")
    _require(isinstance(contract.get("case_id"), str) and contract["case_id"], "case_id required")
    _require(_is_int_span(contract.get("plot_range")), "valid plot_range required")
    minimum = contract.get("minimum")
    _require(type(minimum) is int and minimum >= 0, "valid minimum required")

    rounds = contract.get("rounds")
    _require(isinstance(rounds, list) and rounds, "rounds required")
    round_ids = set()
    for round_ in rounds:
        rid = round_.get("id")
        _require(isinstance(rid, str) and rid and rid not in round_ids, "unique round id required")
        round_ids.add(rid)
        _require(round_.get("direction") == "forward", "only forward synthetic direction supported")
        _require(round_.get("scale") == 1, "only unit fixture scale supported")
        _require(isinstance(round_.get("mounting_intact"), bool), "mounting_intact flag required")

    segments = contract.get("segments")
    _require(isinstance(segments, list) and segments, "segments required")
    segment_ids = set()
    for segment in segments:
        sid = segment.get("id")
        _require(isinstance(sid, str) and sid and sid not in segment_ids, "unique segment id required")
        segment_ids.add(sid)
        _require(isinstance(segment.get("source_id"), str) and segment["source_id"],
                 "segment source_id required")
        _require(segment.get("round") in round_ids, "segment round must reference a contract round")
        _require(_is_int_span(segment.get("local")), "valid local span required")
        translations = segment.get("translations")
        _require(isinstance(translations, list) and translations, "translations required")
        _require(all(type(t) is int for t in translations), "integer translations required")
        _require(len(set(translations)) == len(translations), "duplicate translations not allowed")

    evidence = contract.get("evidence", [])
    _require(isinstance(evidence, list), "evidence list required")
    for item in evidence:
        kind = item.get("kind")
        if kind == "length_witness":
            _require(item.get("segment") in segment_ids, "length witness segment required")
            _require(isinstance(item.get("source_id"), str) and item["source_id"],
                     "evidence source_id required")
        elif kind == "control_points":
            _require(item.get("round") in round_ids, "control point round required")
            _require(type(item.get("translation")) is int, "control point translation required")
            points = item.get("points")
            _require(isinstance(points, list) and len(points) == 2, "two control points required")
            witnesses = set()
            for point in points:
                _require(isinstance(point.get("point_id"), str) and point["point_id"],
                         "point_id required")
                witness = point.get("witness_id")
                _require(isinstance(witness, str) and witness, "witness_id required")
                _require(witness not in witnesses, "independent control point witnesses required")
                witnesses.add(witness)
            _require(isinstance(item.get("reinspection_available"), bool),
                     "reinspection_available flag required")
            _require(_is_string_list(item.get("source_ids")), "control point source_ids required")
        elif kind == "closure":
            _require(isinstance(item.get("chain_rounds"), list) and item["chain_rounds"],
                     "closure chain required")
            _require(all(rid in round_ids for rid in item["chain_rounds"]),
                     "closure chain round required")
            receipts = item.get("receipts")
            _require(isinstance(receipts, dict), "closure receipts required")
            _require(all(isinstance(receipts.get(key), str) and receipts[key]
                         for key in CLOSURE_RECEIPTS),
                     "origin, endpoint relation and closure receipts required")
            relations = item.get("relations")
            _require(isinstance(relations, list) and relations, "closure relations required")
            for relation in relations:
                _require(relation.get("a") in segment_ids and relation.get("b") in segment_ids,
                         "closure relation segments required")
                _require(relation.get("relation") in RELATIONS, "supported relation required")
            _require(isinstance(item.get("chain_unbroken"), bool), "chain_unbroken flag required")
            _require(_is_string_list(item.get("source_ids")), "closure source_ids required")
        else:
            raise ValueError(f"unsupported evidence kind: {kind!r}")
    return True


def merge_contracts(contracts):
    """Merge submissions for one case without double counting physical segments.

    Segments are identified by their original-record source_id.  Identical
    repeats collapse to one physical segment; contradictory repeats are
    retained as conflicts so the originals stay available for verification.
    """
    contracts = tuple(contracts)
    _require(len(contracts) >= 1, "at least one contract required")
    for contract in contracts:
        validate_contract(contract)
    base = contracts[0]
    merged = {
        "schema": SCHEMA,
        "id": "+".join(contract["id"] for contract in contracts),
        "case_id": base["case_id"],
        "plot_range": list(base["plot_range"]),
        "minimum": base["minimum"],
        "rounds": [],
        "segments": [],
        "evidence": [],
        "submission_ids": [contract["id"] for contract in contracts],
        "conflicts": [],
    }
    rounds = {}
    for contract in contracts:
        if contract["case_id"] != base["case_id"]:
            raise ValueError("contracts must share one case_id")
        if contract["plot_range"] != base["plot_range"] or contract["minimum"] != base["minimum"]:
            merged["conflicts"].append(
                {"kind": CONTRACT_TERMS_CONFLICT, "submission_id": contract["id"]})
        for round_ in contract["rounds"]:
            signature = (round_["direction"], round_["scale"], round_["mounting_intact"])
            previous = rounds.get(round_["id"])
            if previous is None:
                rounds[round_["id"]] = (signature, contract["id"])
                merged["rounds"].append(dict(round_))
            elif previous[0] != signature:
                merged["conflicts"].append({
                    "kind": ROUND_RECORD_CONFLICT, "round": round_["id"],
                    "submission_ids": [previous[1], contract["id"]]})

    # source_id -> merged segment record; submission local ids are remapped so
    # evidence references still resolve after cross-submission id collisions.
    stored_by_source = {}
    used_segment_ids = set()
    segment_id_map = {}
    for contract in contracts:
        for segment in contract["segments"]:
            key = segment["source_id"]
            signature = (segment["round"], tuple(segment["local"]),
                         tuple(sorted(segment["translations"])))
            stored = stored_by_source.get(key)
            if stored is None:
                record = dict(segment, submission_id=contract["id"])
                # Segment ids are local to each submission: disambiguate
                # collisions so the merged case still passes structural checks.
                if segment["id"] in used_segment_ids:
                    record["id"] = f"{contract['id']}:{segment['id']}"
                used_segment_ids.add(record["id"])
                merged["segments"].append(record)
                stored_by_source[key] = (signature, contract["id"], record)
            elif stored[0] != signature:
                merged["conflicts"].append({
                    "kind": SOURCE_CONFLICT, "source_id": key,
                    "submission_ids": [stored[1], contract["id"]]})
            # An identical repeat is the same physical segment: point its evidence
            # references at the single stored segment rather than double counting.
            segment_id_map[(contract["id"], segment["id"])] = stored_by_source[key][2]["id"]

    evidence_keys = set()
    for contract in contracts:
        def remap(segment_id):
            return segment_id_map[(contract["id"], segment_id)]

        for item in contract["evidence"]:
            copied = dict(item)
            if "segment" in copied:
                copied["segment"] = remap(copied["segment"])
            if "relations" in copied:
                copied["relations"] = [
                    dict(relation, a=remap(relation["a"]), b=remap(relation["b"]))
                    for relation in item["relations"]]
            key = (item["kind"],) + tuple(sorted(_evidence_sources(item)))
            if key in evidence_keys:
                continue
            evidence_keys.add(key)
            merged["evidence"].append(copied)
    return merged


def _placed_span(segment, translation):
    return [segment["local"][0] + translation, segment["local"][1] + translation]


def _relation_holds(relation, placements):
    a = placements[relation["a"]]
    b = placements[relation["b"]]
    cells_a = set(range(a[0], a[1]))
    cells_b = set(range(b[0], b[1]))
    if relation["relation"] == "disjoint":
        return cells_a.isdisjoint(cells_b)
    # "abut": a true shared endpoint on the same line with no interior overlap.
    return cells_a.isdisjoint(cells_b) and (a[1] == b[0] or b[1] == a[0])


def adjudicate(contract):
    """Return the signable coverage decision for a validated (or merged) contract."""
    validate_contract(contract)
    plot_lo, plot_hi = contract["plot_range"]
    rounds = {round_["id"]: round_ for round_ in contract["rounds"]}
    segments = contract["segments"]
    segment_by_id = {segment["id"]: segment for segment in segments}
    reasons = []

    # Per-round candidate translations: intersection of per-segment originals,
    # restricted to placements fully inside the legal plot range.
    candidates = {}
    for round_id in sorted(rounds):
        cand = None
        for segment in segments:
            if segment["round"] != round_id:
                continue
            valid = set()
            for translation in segment["translations"]:
                span = _placed_span(segment, translation)
                if span[0] >= plot_lo and span[1] <= plot_hi:
                    valid.add(translation)
            cand = valid if cand is None else cand & valid
        candidates[round_id] = set() if cand is None else cand

    # Evidence path A: two independent control points lock one round, but only
    # while the observation remains in its original mounting.
    control_rounds = set()
    reinspection_available = True
    for item in contract["evidence"]:
        if item["kind"] != "control_points":
            continue
        round_id = item["round"]
        if not rounds[round_id]["mounting_intact"]:
            reasons.append(f"{MOUNTING_DISMANTLED}:{round_id}")
            continue
        control_rounds.add(round_id)
        reinspection_available = reinspection_available and item["reinspection_available"]
        if item["translation"] not in candidates[round_id]:
            reasons.append(f"{CONTROL_POINT_CONFLICT}:{round_id}")
            candidates[round_id] = set()
        else:
            candidates[round_id] = {item["translation"]}

    # Evidence path B: closed-control receipts on an un-broken chain.  Relations
    # only apply to rounds the chain actually contains.
    relations = []
    closure_present = False
    for item in contract["evidence"]:
        if item["kind"] != "closure":
            continue
        if not item["chain_unbroken"]:
            reasons.append(CLOSURE_CHAIN_BROKEN)
            continue
        chain = set(item["chain_rounds"])
        applicable = []
        for relation in item["relations"]:
            if (segment_by_id[relation["a"]]["round"] not in chain
                    or segment_by_id[relation["b"]]["round"] not in chain):
                reasons.append(f"{CLOSURE_OUTSIDE_CHAIN}:{relation['a']},{relation['b']}")
            else:
                applicable.append(relation)
        if applicable:
            closure_present = True
            relations.extend(applicable)

    # Every surviving interpretation explains ALL evidence and stays in range.
    interpretations = []
    if all(candidates.values()):
        round_ids = sorted(rounds)
        for combo in product(*(sorted(candidates[rid]) for rid in round_ids)):
            translations = dict(zip(round_ids, combo))
            placements = {
                segment["id"]: _placed_span(segment, translations[segment["round"]])
                for segment in segments
            }
            if any(not _relation_holds(relation, placements) for relation in relations):
                continue
            union = sorted({tick for span in placements.values() for tick in range(span[0], span[1])})
            interpretations.append({
                "round_translations": translations,
                "placements": placements,
                "union": union,
                "coverage": len(union),
            })
    if not interpretations:
        reasons.append(NO_SHARED_ROUND_TRANSLATION if not all(candidates.values())
                       else NO_FEASIBLE_INTERPRETATION)

    if interpretations:
        unions = [set(item["union"]) for item in interpretations]
        guaranteed_coverage = min(len(union) for union in unions)
        certain_cells = sorted(set.intersection(*unions))
        possible_cells = sorted(set.union(*unions))
        certified_positions = []
        for segment in segments:
            spans = {tuple(item["placements"][segment["id"]]) for item in interpretations}
            if len(spans) == 1:
                certified_positions.append({
                    "segment_id": segment["id"],
                    "source_id": segment["source_id"],
                    "absolute": list(next(iter(spans))),
                })
    else:
        guaranteed_coverage = 0
        certain_cells = []
        possible_cells = []
        certified_positions = []

    conflicts = contract.get("conflicts", [])
    if conflicts:
        status = "pending"
        reasons.insert(0, SOURCE_CONFLICT)
    elif not interpretations:
        status = "withheld"
    elif guaranteed_coverage >= contract["minimum"]:
        status = "ready"
    elif any(item["coverage"] >= contract["minimum"] for item in interpretations):
        # Some credible interpretation reaches the minimum: more originals may
        # still resolve the ambiguity, so the case is held for verification.
        status = "pending"
        reasons.append(COVERAGE_NOT_ASSURED)
        reasons.append(PENDING_VERIFICATION)
    else:
        status = "withheld"
        reasons.append(CANNOT_REACH_MINIMUM)

    if control_rounds:
        certificate = "control_points"
        certain_segment_ids = {position["segment_id"] for position in certified_positions}
        position_certified = (reinspection_available
                              and all(segment["id"] in certain_segment_ids for segment in segments))
    elif closure_present:
        certificate = "closure"
        position_certified = False
    else:
        certificate = None
        position_certified = False

    evidence_ids = sorted({
        source for item in contract["evidence"] for source in _evidence_sources(item)
    })
    return {
        "case_id": contract["case_id"],
        "contract_ids": list(contract.get("submission_ids", [contract["id"]])),
        "status": status,
        "required_minimum": contract["minimum"],
        "plot_range": list(contract["plot_range"]),
        "guaranteed_coverage": guaranteed_coverage,
        "certain_cells": certain_cells,
        "possible_cells": possible_cells,
        "certificate": certificate,
        "position_certified": position_certified,
        "reinspection_available": bool(control_rounds) and reinspection_available,
        "certified_positions": certified_positions,
        "interpretations": interpretations,
        "reasons": reasons,
        "conflicts": conflicts,
        "evidence_ids": evidence_ids,
        "segment_source_ids": {segment["id"]: segment["source_id"] for segment in segments},
    }
