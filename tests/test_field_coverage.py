"""Synthetic transect coverage contracts: minimum coverage and sign-off paths."""

import json
import subprocess
import sys
from pathlib import Path

from treecase import field_coverage, field_track, store

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "field_coverage.json"


def contracts():
    return {item["id"]: item for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["contracts"]}


def decide(contract_id):
    return field_coverage.adjudicate(field_coverage.merge_contracts([contracts()[contract_id]]))


def test_field_x_a_length_witness_only_is_pending_with_full_ambiguity():
    decision = decide("FIELD-X-A")
    assert decision["status"] == "pending"
    assert decision["certificate"] is None
    assert decision["position_certified"] is False
    assert len(decision["interpretations"]) == 3
    assert decision["guaranteed_coverage"] == 2
    assert decision["certain_cells"] == [0, 1]
    assert decision["possible_cells"] == [0, 1, 2, 3, 4, 5]
    assert any(item["coverage"] >= 4 for item in decision["interpretations"])
    assert field_coverage.PENDING_VERIFICATION in decision["reasons"]
    assert field_coverage.COVERAGE_NOT_ASSURED in decision["reasons"]
    # The two extreme interpretations are full overlap and complete disjointness.
    coverages = sorted(item["coverage"] for item in decision["interpretations"])
    assert coverages == [2, 4, 4]


def test_field_x_a_does_not_allow_stitching_or_cell_intersection_total():
    decision = decide("FIELD-X-A")
    # Per-cell intersection is the certain position, not the guaranteed total.
    assert len(decision["certain_cells"]) == 2
    assert decision["guaranteed_coverage"] == 2
    # The possible cells span six units, but no interpretation covers them all.
    assert len(decision["possible_cells"]) == 6
    assert max(item["coverage"] for item in decision["interpretations"]) == 4
    # Cells from different interpretations must never be stitched into a wider claim.
    stitched = set()
    for item in decision["interpretations"]:
        stitched |= set(item["union"])
    assert len(stitched) == 6
    assert decision["guaranteed_coverage"] != len(stitched)


def test_field_x_b_two_control_points_lock_translation_and_sign_position():
    decision = decide("FIELD-X-B")
    assert decision["status"] == "ready"
    assert decision["certificate"] == "control_points"
    assert decision["position_certified"] is True
    assert decision["reinspection_available"] is True
    assert decision["guaranteed_coverage"] == 4
    assert decision["certain_cells"] == [0, 1, 2, 3]
    assert len(decision["interpretations"]) == 1
    assert decision["interpretations"][0]["round_translations"] == {"R1": 0, "R2": 2}
    assert {tuple(p["absolute"]) for p in decision["certified_positions"]} == {
        (0, 2), (2, 4)}
    assert decision["evidence_ids"] == ["CP-X-2A", "CP-X-2B", "LW-X-S1", "LW-X-S2"]


def test_field_x_c_closure_certifies_total_without_second_segment_position():
    decision = decide("FIELD-X-C")
    assert decision["status"] == "ready"
    assert decision["certificate"] == "closure"
    assert decision["position_certified"] is False
    assert decision["reinspection_available"] is False
    # The dismantled mounting makes the current control points unusable.
    assert any(reason.startswith(field_coverage.MOUNTING_DISMANTLED) for reason in decision["reasons"])
    # Closure leaves translations 2 or 4; every interpretation still covers 4.
    assert len(decision["interpretations"]) == 2
    assert all(item["coverage"] == 4 for item in decision["interpretations"])
    assert decision["guaranteed_coverage"] == 4
    assert decision["certain_cells"] == [0, 1]
    assert decision["possible_cells"] == [0, 1, 2, 3, 4, 5]
    # Only the fixed first segment has a verifiable absolute position.
    assert decision["certified_positions"] == [
        {"segment_id": "S1", "source_id": "SRC-X-SEG-1", "absolute": [0, 2]}]
    translations = sorted(item["round_translations"]["R2"] for item in decision["interpretations"])
    assert translations == [2, 4]


def test_field_x_d_three_segments_without_shared_round_translation_withholds():
    decision = decide("FIELD-X-D")
    assert decision["status"] == "withheld"
    assert decision["interpretations"] == []
    assert decision["guaranteed_coverage"] == 0
    assert decision["certain_cells"] == []
    assert field_coverage.NO_SHARED_ROUND_TRANSLATION in decision["reasons"]


def test_field_x_e_second_independent_input_of_same_segment_does_not_double_count():
    docs = contracts()
    merged = field_coverage.merge_contracts([docs["FIELD-X-E-1"], docs["FIELD-X-E-2"]])
    assert len(merged["segments"]) == 1
    assert merged["evidence"] and len(merged["evidence"]) == 1
    decision = field_coverage.adjudicate(merged)
    assert decision["status"] == "ready"
    assert decision["guaranteed_coverage"] == 2
    assert decision["certain_cells"] == [2, 3]
    # The physical segment is counted once even with two submissions.
    assert decision["interpretations"][0]["coverage"] == 2
    assert decision["contract_ids"] == ["FIELD-X-E-1", "FIELD-X-E-2"]


def test_field_x_f_contradictory_same_source_records_are_held_pending():
    docs = contracts()
    merged = field_coverage.merge_contracts([docs["FIELD-X-F-1"], docs["FIELD-X-F-2"]])
    assert len(merged["segments"]) == 1
    assert any(conflict["kind"] == field_coverage.SOURCE_CONFLICT for conflict in merged["conflicts"])
    decision = field_coverage.adjudicate(merged)
    assert decision["status"] == "pending"
    assert field_coverage.SOURCE_CONFLICT in decision["reasons"]
    # Both originals stay on file for verification.
    assert decision["contract_ids"] == ["FIELD-X-F-1", "FIELD-X-F-2"]


def test_field_x_g_dismantled_mounting_control_does_not_lock_translation():
    decision = decide("FIELD-X-G")
    assert any(reason.startswith(field_coverage.MOUNTING_DISMANTLED) for reason in decision["reasons"])
    assert decision["certificate"] is None
    assert decision["position_certified"] is False
    # Without closure the dismantled mounting leaves the full translation ambiguity:
    # guaranteed 2 only, so the total cannot yet be signed even though some
    # interpretations would cover 4.
    assert decision["status"] == "pending"
    assert decision["guaranteed_coverage"] == 2
    assert decision["certain_cells"] == [0, 1]
    assert len(decision["interpretations"]) == 3


def test_out_of_range_translations_are_excluded_from_interpretations():
    contract = {
        "schema": field_coverage.SCHEMA,
        "id": "RANGE-1", "case_id": "CASE-RANGE", "plot_range": [0, 4], "minimum": 2,
        "rounds": [{"id": "R1", "direction": "forward", "scale": 1, "mounting_intact": True}],
        "segments": [{"id": "S1", "source_id": "SRC-R1", "round": "R1",
                      "local": [0, 2], "translations": [0, 3]}],
        "evidence": [{"kind": "length_witness", "segment": "S1", "source_id": "LW-R1"}],
    }
    decision = field_coverage.adjudicate(field_coverage.merge_contracts([contract]))
    # Translation 3 would place the segment at [3,5), outside the plot.
    assert decision["interpretations"][0]["placements"] == {"S1": [0, 2]}
    assert decision["guaranteed_coverage"] == 2


def test_closure_cannot_borrow_evidence_for_rounds_outside_its_chain():
    contract = {
        "schema": field_coverage.SCHEMA,
        "id": "CHAIN-1", "case_id": "CASE-CHAIN", "plot_range": [0, 8], "minimum": 2,
        "rounds": [
            {"id": "R1", "direction": "forward", "scale": 1, "mounting_intact": True},
            {"id": "R2", "direction": "forward", "scale": 1, "mounting_intact": False},
        ],
        "segments": [
            {"id": "S1", "source_id": "SRC-C1", "round": "R1", "local": [0, 2], "translations": [0]},
            {"id": "S2", "source_id": "SRC-C2", "round": "R2", "local": [0, 2], "translations": [0, 2]},
        ],
        "evidence": [
            {"kind": "closure", "chain_rounds": ["R1"],
             "receipts": {"origin": "RC-O", "endpoint_relation": "RC-E", "closure": "RC-C"},
             "relations": [{"a": "S1", "b": "S2", "relation": "disjoint"}],
             "chain_unbroken": True, "source_ids": ["RC-O", "RC-E", "RC-C"]},
        ],
    }
    decision = field_coverage.adjudicate(field_coverage.merge_contracts([contract]))
    assert any(field_coverage.CLOSURE_OUTSIDE_CHAIN in reason for reason in decision["reasons"])
    # The relation is not enforceable, so both translations remain open.
    assert len(decision["interpretations"]) == 2
    assert decision["guaranteed_coverage"] == 2


def test_broken_closure_chain_cannot_certify_the_total():
    contract = {
        "schema": field_coverage.SCHEMA,
        "id": "CHAIN-2", "case_id": "CASE-CHAIN-BROKEN", "plot_range": [0, 6], "minimum": 4,
        "rounds": [
            {"id": "R1", "direction": "forward", "scale": 1, "mounting_intact": True},
            {"id": "R2", "direction": "forward", "scale": 1, "mounting_intact": False},
        ],
        "segments": [
            {"id": "S1", "source_id": "SRC-B1", "round": "R1", "local": [0, 2], "translations": [0]},
            {"id": "S2", "source_id": "SRC-B2", "round": "R2", "local": [0, 2], "translations": [0, 2, 4]},
        ],
        "evidence": [
            {"kind": "closure", "chain_rounds": ["R1", "R2"],
             "receipts": {"origin": "RC-B-O", "endpoint_relation": "RC-B-E", "closure": "RC-B-C"},
             "relations": [{"a": "S1", "b": "S2", "relation": "disjoint"}],
             "chain_unbroken": False, "source_ids": ["RC-B-O", "RC-B-E", "RC-B-C"]},
        ],
    }
    decision = field_coverage.adjudicate(field_coverage.merge_contracts([contract]))
    assert field_coverage.CLOSURE_CHAIN_BROKEN in decision["reasons"]
    assert decision["certificate"] is None
    assert decision["status"] == "pending"


def test_merge_remaps_local_segment_id_collisions_between_submissions():
    base = contracts()["FIELD-X-E-1"]
    other = json.loads(json.dumps(base))
    other["id"] = "FIELD-X-E-3"
    other["segments"][0]["source_id"] = "SRC-X-E-DIFFERENT"
    other["segments"][0]["translations"] = [0, 2]
    merged = field_coverage.merge_contracts([base, other])
    segment_ids = {segment["id"] for segment in merged["segments"]}
    assert len(segment_ids) == 2
    # Length-witness references still resolve after the remap.
    witness_segments = {item["segment"] for item in merged["evidence"]
                        if item["kind"] == "length_witness"}
    assert witness_segments <= segment_ids
    field_coverage.validate_contract(merged)
    decision = field_coverage.adjudicate(merged)
    # Both segments are always in range, but the second may overlap the fixed one.
    assert decision["status"] == "ready"
    assert decision["guaranteed_coverage"] == 2
    assert decision["certain_cells"] == [2, 3]


def test_contract_capture_persists_and_recomputes_from_originals(tmp_path):
    docs = contracts()
    with store.session(tmp_path / "field.sqlite") as db:
        summary, decision = field_track.capture_contract(db, docs["FIELD-X-B"])
        assert summary["delivery"] == "ready"
        assert summary["guaranteed_coverage"] == 4
        assert summary["persistence"] == "recorded"
        # Replay from the stored originals yields the same decision.
        rows = db.execute("SELECT raw FROM field_coverage_contract WHERE id='FIELD-X-B'").fetchall()
        reloaded = json.loads(rows[0][0])
        replayed = field_coverage.adjudicate(field_coverage.merge_contracts([reloaded]))
        assert replayed["guaranteed_coverage"] == decision["guaranteed_coverage"]
        assert replayed["certain_cells"] == decision["certain_cells"]
        row = db.execute(
            "SELECT status,guaranteed_coverage,certificate,evidence_ids_json "
            "FROM field_coverage_delivery WHERE case_id='CASE-X-B'").fetchone()
        assert row[0] == "ready"
        assert row[1] == 4
        assert row[2] == "control_points"
        assert set(json.loads(row[3])) == {"CP-X-2A", "CP-X-2B", "LW-X-S1", "LW-X-S2"}


def test_contract_capture_is_idempotent_and_conflicting_bytes_fail(tmp_path):
    docs = contracts()
    with store.session(tmp_path / "field.sqlite") as db:
        first, _ = field_track.capture_contract(db, docs["FIELD-X-A"])
        assert first["persistence"] == "recorded"
        second, _ = field_track.capture_contract(db, docs["FIELD-X-A"])
        assert second["persistence"] == "already_recorded"
        altered = json.loads(json.dumps(docs["FIELD-X-A"]))
        altered["minimum"] = 5
        try:
            field_track.capture_contract(db, altered)
        except ValueError:
            pass
        else:
            raise AssertionError("conflicting contract bytes must be rejected")
        rows = db.execute("SELECT COUNT(*) FROM field_coverage_contract").fetchone()
        assert rows[0] == 1


def test_two_submissions_merge_inside_capture_without_double_counting(tmp_path):
    docs = contracts()
    with store.session(tmp_path / "field.sqlite") as db:
        first, _ = field_track.capture_contract(db, docs["FIELD-X-E-1"])
        second, decision = field_track.capture_contract(db, docs["FIELD-X-E-2"])
    assert first["delivery"] == "ready"
    assert second["delivery"] == "ready"
    assert decision["guaranteed_coverage"] == 2
    assert len(decision["segment_source_ids"]) == 1
    assert decision["contract_ids"] == ["FIELD-X-E-1", "FIELD-X-E-2"]


def test_baseline_capture_still_drives_legacy_delivery(tmp_path):
    with store.session(tmp_path / "field.sqlite") as db:
        complete = {
            "id": "FIELD-1", "case_id": "DEMO-PLOT", "minimum": 4,
            "spans": [[0, 2], [2, 4]],
        }
        short = {
            "id": "FIELD-2", "case_id": "DEMO-PLOT", "minimum": 4,
            "spans": [[0, 2], [1, 3]],
        }
        assert field_track.capture(db, complete) == {"outcome": "complete", "delivery": "ready"}
        assert field_track.capture(db, short) == {"outcome": "short", "delivery": "withheld"}
        row = db.execute(
            "SELECT status,evidence_id FROM field_delivery WHERE case_id='DEMO-PLOT'").fetchone()
        assert tuple(row) == ("withheld", "FIELD-2")


def test_malformed_contract_raises_value_error():
    bad = {
        "schema": field_coverage.SCHEMA,
        "id": "BAD-1", "case_id": "CASE-BAD", "plot_range": [0, 4], "minimum": 2,
        "rounds": [{"id": "R1", "direction": "forward", "scale": 1, "mounting_intact": True}],
        "segments": [{"id": "S1", "source_id": "SRC-BAD", "round": "R1",
                      "local": [0, 2], "translations": [0]}],
        "evidence": [{"kind": "control_points", "round": "R1", "translation": 0,
                      "points": [{"point_id": "P1", "witness_id": "W1"},
                                 {"point_id": "P2", "witness_id": "W1"}],
                      "reinspection_available": True, "source_ids": ["P1", "P2"]}],
    }
    try:
        field_coverage.validate_contract(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("control points need two independent witnesses")


def test_module_entry_point_remains_importable_and_cli_runs(tmp_path):
    output = subprocess.run(
        [sys.executable, "-B", "-m", "treecase.field_track", "--help"],
        cwd=ROOT, text=True, capture_output=True, check=True)
    assert "--input" in output.stdout
    input_path = tmp_path / "contract.json"
    input_path.write_text(json.dumps(contracts()["FIELD-X-B"]), encoding="utf-8")
    db_path = tmp_path / "cli.sqlite"
    output = subprocess.run(
        [sys.executable, "-B", "-m", "treecase.field_track",
         "--db", str(db_path), "--input", str(input_path)],
        cwd=ROOT, text=True, capture_output=True, check=True)
    result = json.loads(output.stdout)
    assert result["delivery"] == "ready"
    assert result["guaranteed_coverage"] == 4
    assert result["position_certified"] is True


def test_cli_accepts_the_fixture_container_and_keeps_cases_distinct(tmp_path):
    db_path = tmp_path / "container.sqlite"
    output = subprocess.run(
        [sys.executable, "-B", "-m", "treecase.field_track",
         "--db", str(db_path), "--input", str(FIXTURE)],
        cwd=ROOT, text=True, capture_output=True, check=True)
    results = {item["case_id"]: item for item in json.loads(output.stdout)}
    assert results["CASE-X-A"]["delivery"] == "pending"
    assert results["CASE-X-B"]["delivery"] == "ready"
    assert results["CASE-X-C"]["delivery"] == "ready"
    assert results["CASE-X-D"]["delivery"] == "withheld"
    # The two independent E submissions never double count the physical segment.
    assert results["CASE-X-E"]["guaranteed_coverage"] == 2
    assert results["CASE-X-F"]["delivery"] == "pending"
    with store.session(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM field_coverage_contract").fetchone()[0] == 9
        assert db.execute(
            "SELECT COUNT(*) FROM field_coverage_delivery").fetchone()[0] == 7
