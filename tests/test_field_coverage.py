"""Minimum-coverage commitments under clamp-change uncertainty (FIELD-X)."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from treecase import field_coverage, field_delivery, field_track, store

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "field_coverage_field_x.json"


def passes():
    return {item["id"]: item for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["passes"]}


def contract(**overrides):
    evidence = {
        "id": "T", "case_id": "C", "shape": "field_contract",
        "contract_range": [0, 6], "minimum": 4,
        "rounds": [
            {"id": "R0", "clamp_intact": True, "direction": 1, "scale": 2},
            {"id": "R1", "clamp_intact": True, "direction": 1, "scale": 2},
        ],
        "segments": [
            {"id": "S1", "round_id": "R0", "local": [0, 2],
             "candidate_translations": [0], "original_id": "O1"},
            {"id": "S2", "round_id": "R1", "local": [0, 2],
             "candidate_translations": [0, 2, 4], "original_id": "O2"},
        ],
        "control_points": [], "closures": [],
    }
    evidence.update(overrides)
    return evidence


@pytest.fixture()
def db(tmp_path):
    with store.session(tmp_path / "field.sqlite") as connection:
        yield connection


# --- the five FIELD-X evidence situations -----------------------------------

def test_length_only_witness_is_pending_without_stitching_uncertainty(db):
    result = field_track.capture(db, copy.deepcopy(passes()["FIELD-X-LEN"]))
    # Overlap and disjointness are both still credible: nothing total can be
    # signed until independent control evidence arrives.
    assert result["delivery"] == "withheld"
    assert result["reason"] == "pending_verification"
    assert result["coverage_floor"] == 2
    assert result["certain_spans"] == [[0, 2]]
    assert result["position_certified"] is False
    assert result["position_review_available"] is False
    assert result["interpretation_count"] == 3
    # The three interpretations are full unions, never a patchwork of cells.
    detail = json.loads(db.execute(
        "SELECT result_json FROM field_coverage WHERE case_id='FIELD-X-LEN'").fetchone()[0])
    assert [item["union_size"] for item in detail["interpretations"]] == [2, 4, 4]
    assert tuple(db.execute(
        "SELECT status FROM field_delivery WHERE case_id='FIELD-X-LEN'").fetchone()) == ("withheld",)


def test_two_control_points_lock_translation_and_certify_position(db):
    result = field_track.capture(db, copy.deepcopy(passes()["FIELD-X-CTL"]))
    assert result["delivery"] == "ready"
    assert result["reason"] == "coverage_floor_met"
    assert result["coverage_floor"] == 4
    assert result["certain_spans"] == [[0, 4]]
    assert result["position_certified"] is True
    assert result["position_review_available"] is True
    assert result["interpretation_count"] == 1
    detail = json.loads(db.execute(
        "SELECT result_json FROM field_coverage WHERE case_id='FIELD-X-CTL'").fetchone()[0])
    assert detail["interpretations"][0]["translations"] == {"R0": 0, "R1": 2}


def test_closure_receipt_signs_total_but_not_the_second_position(db):
    result = field_track.capture(db, copy.deepcopy(passes()["FIELD-X-CLS"]))
    assert result["delivery"] == "ready"
    assert result["coverage_floor"] == 4
    # Only the anchor is necessary; S2 may sit at [2,4) or [4,6).
    assert result["certain_spans"] == [[0, 2]]
    assert result["position_certified"] is False
    assert result["position_review_available"] is False
    detail = json.loads(db.execute(
        "SELECT result_json FROM field_coverage WHERE case_id='FIELD-X-CLS'").fetchone()[0])
    assert sorted(item["translations"]["R1"] for item in detail["interpretations"]) == [2, 4]
    assert all(item["union_size"] == 4 for item in detail["interpretations"])
    assert detail["basis_originals"] == ["ORIG-X-1", "ORIG-X-2"]


def test_segments_satisfying_their_own_constraints_but_sharing_no_round_translation(db):
    result = field_track.capture(db, copy.deepcopy(passes()["FIELD-X-INF"]))
    assert result["delivery"] == "withheld"
    assert result["reason"] == "infeasible"
    assert result["coverage_floor"] == 0
    assert result["interpretation_count"] == 0
    assert result["position_certified"] is False


def test_second_independent_input_pointing_at_the_same_field_segment_is_not_doubled(db):
    result = field_track.capture(db, copy.deepcopy(passes()["FIELD-X-DUP"]))
    assert result["delivery"] == "ready"
    assert result["coverage_floor"] == 4
    detail = json.loads(db.execute(
        "SELECT result_json FROM field_coverage WHERE case_id='FIELD-X-DUP'").fetchone()[0])
    # The duplicated original appears once in the audit basis and once in each
    # union; counting both records would have produced a floor of 6.
    assert detail["basis_originals"] == ["ORIG-X-1", "ORIG-X-2"]
    assert max(item["union_size"] for item in detail["interpretations"]) == 4


def test_contradicting_records_of_one_original_are_held_for_verification(db):
    result = field_track.capture(db, copy.deepcopy(passes()["FIELD-X-DUPCON"]))
    assert result["delivery"] == "withheld"
    assert result["reason"] == "duplicate_conflict"
    assert result["coverage_floor"] == 0
    # The conflicting originals remain on record for review.
    raw = db.execute("SELECT raw FROM field_track WHERE id='FIELD-X-DUPCON'").fetchone()[0]
    assert json.loads(raw)["id"] == "FIELD-X-DUPCON"


# --- adjudicating rules beyond the fixture ---------------------------------

def test_interpretations_are_full_unions_never_cross_interpretation_patches():
    result = field_coverage.evaluate(contract())
    spans = {tuple(tuple(span) for span in item["union_spans"])
             for item in result["interpretations"]}
    # No mixed placement such as [0,4) stitched from the t=2 and t=4 worlds.
    assert spans == {((0, 2),), ((0, 2), (2, 4)), ((0, 2), (4, 6))}
    # The guaranteed total is a minimum over whole interpretations (2), not the
    # per-cell intersection sold as a quantity (which would also be 2 cells but
    # could never imply coverage of S2 anywhere).
    assert result["coverage_floor"] == 2
    assert result["certain_spans"] == [[0, 2]]
    assert result["status"] == "withheld"


def test_per_cell_intersection_is_not_sold_when_totals_differ():
    # S1 at [0,2); S2 length 3 can overlap S1 by two cells, so the floor
    # drops to 3 while every interpretation still contains the anchor cells.
    evidence = contract()
    evidence["segments"][1]["local"] = [0, 3]
    evidence["segments"][1]["candidate_translations"] = [0, 2]
    result = field_coverage.evaluate(evidence)
    sizes = sorted(item["union_size"] for item in result["interpretations"])
    assert sizes == [3, 5]
    assert result["coverage_floor"] == 3
    assert result["certain_spans"] == [[0, 2]]


def test_control_point_lock_is_ignored_after_clamp_dismantle():
    evidence = contract()
    evidence["rounds"][1]["clamp_intact"] = False
    evidence["control_points"] = [
        {"id": "CP-A", "round_id": "R1", "witness_id": "A", "locked_translation": 2},
        {"id": "CP-B", "round_id": "R1", "witness_id": "B", "locked_translation": 2},
    ]
    result = field_coverage.evaluate(evidence)
    assert result["position_review_available"] is False
    assert result["interpretation_count"] == 3
    assert any("clamp dismantled" in note for note in result["notes"])


def test_contradictory_control_points_withhold_and_keep_originals(db):
    evidence = contract()
    evidence["id"] = "CONFLICT-CTL"
    evidence["case_id"] = "CONFLICT-CTL"
    evidence["control_points"] = [
        {"id": "CP-A", "round_id": "R1", "witness_id": "A", "locked_translation": 2},
        {"id": "CP-B", "round_id": "R1", "witness_id": "B", "locked_translation": 4},
    ]
    result = field_track.capture(db, evidence)
    assert result["delivery"] == "withheld"
    assert result["reason"] == "contradictory_evidence"
    assert db.execute("SELECT 1 FROM field_track WHERE id='CONFLICT-CTL'").fetchone() is not None


def test_adjacent_closure_requires_a_real_shared_endpoint():
    evidence = contract()
    evidence["closures"] = [{
        "id": "CLS", "start_segment": "S1", "segments": ["S1", "S2"],
        "endpoint_relation": "adjacent", "actual_closure": True,
    }]
    result = field_coverage.evaluate(evidence)
    # Only translation 2 makes S2 start exactly where S1 ends.
    assert result["interpretation_count"] == 1
    assert result["interpretations"][0]["translations"]["R1"] == 2
    assert result["coverage_floor"] == 4


def test_unclosed_receipt_does_not_bind():
    evidence = contract()
    evidence["closures"] = [{
        "id": "CLS", "start_segment": "S1", "segments": ["S1", "S2"],
        "endpoint_relation": "disjoint", "actual_closure": False,
    }]
    result = field_coverage.evaluate(evidence)
    assert result["interpretation_count"] == 3


def test_closure_only_constrains_rounds_that_actually_contain_its_segments():
    # An anchor locked at [0,2) cannot rescue an out-of-range S2: the receipt
    # constrains the R1 placement directly rather than lending R0's origin.
    evidence = contract()
    evidence["contract_range"] = [0, 4]
    evidence["closures"] = [{
        "id": "CLS", "start_segment": "S1", "segments": ["S1", "S2"],
        "endpoint_relation": "disjoint", "actual_closure": True,
    }]
    result = field_coverage.evaluate(evidence)
    assert sorted(item["translations"]["R1"] for item in result["interpretations"]) == [2]
    assert result["coverage_floor"] == 4


def test_reversed_direction_round_places_local_intervals_backwards():
    evidence = contract()
    evidence["contract_range"] = [0, 8]
    evidence["rounds"][1]["direction"] = -1
    evidence["segments"][1]["candidate_translations"] = [4, 6]
    result = field_coverage.evaluate(evidence)
    placed = {item["translations"]["R1"]: item["union_spans"]
              for item in result["interpretations"]}
    assert placed[4] == [[0, 4]]  # local [0,2) ending at the anchor, touching S1
    assert placed[6] == [[0, 2], [4, 6]]


def test_out_of_range_placements_are_dropped_before_the_floor_is_signed():
    evidence = contract()
    evidence["contract_range"] = [0, 4]
    result = field_coverage.evaluate(evidence)
    assert sorted(item["translations"]["R1"] for item in result["interpretations"]) == [0, 2]


def test_reconsider_accepts_the_coverage_result_directly(db):
    result = field_coverage.evaluate(contract())
    state = field_delivery.reconsider(db, "C", "short", "T", result)
    assert state == "withheld"
    assert tuple(db.execute(
        "SELECT status,evidence_id FROM field_delivery WHERE case_id='C'").fetchone()) == (
        "withheld", "T")


def test_identical_recapture_is_idempotent_but_changed_bytes_conflict(db):
    evidence = copy.deepcopy(passes()["FIELD-X-CTL"])
    first = field_track.capture(db, evidence)
    again = field_track.capture(db, copy.deepcopy(evidence))
    assert first["delivery"] == "ready"
    assert again["delivery"] == "already_recorded"
    altered = copy.deepcopy(evidence)
    altered["minimum"] = 6
    with pytest.raises(ValueError, match="track id conflict"):
        field_track.capture(db, altered)


def test_auditor_can_recompute_from_the_stored_original(db):
    evidence = copy.deepcopy(passes()["FIELD-X-CLS"])
    field_track.capture(db, evidence)
    raw = db.execute("SELECT raw FROM field_track WHERE id='FIELD-X-CLS'").fetchone()[0]
    recomputed = field_coverage.evaluate(json.loads(raw))
    stored = json.loads(db.execute(
        "SELECT result_json FROM field_coverage WHERE case_id='FIELD-X-CLS'").fetchone()[0])
    assert recomputed["coverage_floor"] == stored["coverage_floor"]
    assert recomputed["interpretations"] == stored["interpretations"]
    assert recomputed["basis_originals"] == ["ORIG-X-1", "ORIG-X-2"]


def test_module_cli_entry_runs(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(passes()["FIELD-X-CTL"]), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "treecase.field_track",
         "--db", str(tmp_path / "cli.sqlite"), "--input", str(source)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["coverage_floor"] == 4
    assert payload["delivery"] == "ready"


def test_malformed_contract_is_rejected():
    with pytest.raises(ValueError):
        field_coverage.evaluate(contract(segments=[]))
    with pytest.raises(ValueError):
        bad = contract()
        bad["rounds"][0]["scale"] = 3
        field_coverage.evaluate(bad)
    with pytest.raises(ValueError):
        bad = contract()
        bad["segments"][1]["candidate_translations"] = [1]  # off the scale-2 grid
        field_coverage.evaluate(bad)
    with pytest.raises(ValueError):
        bad = contract()
        bad["control_points"] = [
            {"id": "CP-A", "round_id": "R1", "witness_id": "A", "locked_translation": 2}]
        bad["closures"] = [{"id": "CLS", "start_segment": "S1", "segments": ["S1", "MISSING"],
                            "endpoint_relation": "disjoint", "actual_closure": True}]
        field_coverage.evaluate(bad)
