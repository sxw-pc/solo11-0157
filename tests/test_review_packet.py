"""External-review packets: route legality, witness anonymity and recomputation."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from treecase import engine, store
from treecase.review_packet import (adjudication_ref, internal_snapshot, issue_packet,
                                    verify_packet, witness_domains)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "treecase" / "fixtures"
CONSTRAINTS = json.loads((ROOT / "fixtures" / "review_packet_constraints.json").read_text(encoding="utf-8"))
ATTESTATIONS = json.loads((ROOT / "fixtures" / "review_packet_attestations.json").read_text(encoding="utf-8"))


class Case:
    def __init__(self, tmp_path):
        self.db = tmp_path / "case.db"

    def import_source(self, category, name):
        return engine.import_file(self.db, FIXTURES / category / name)

    def rows(self):
        with store.session(self.db) as session:
            return store.event_rows(session)

    def snapshot(self, permit_id="PER-101-NORMAL"):
        return internal_snapshot(self.rows(), permit_id)


def normal_case(tmp_path):
    case = Case(tmp_path)
    case.import_source("tree", "t101_initial.json")
    case.import_source("permit", "t101_prune_normal.json")
    return case


def option_constraints(doc, route):
    for option in doc["new_alias_options"]:
        if option["id"] == route:
            return option.get("constraints", [])
    raise AssertionError(f"missing option {route}")


def write_permit_603(tmp_path):
    doc = json.loads((FIXTURES / "permit" / "t101_prune_normal.json").read_text(encoding="utf-8"))
    doc["event_id"] = "permit-t603-normal"
    doc["recorded_at"] = "2026-03-03T10:00:00+08:00"
    doc["permit"].update({"permit_id": "PER-603-NORMAL", "tree_no": "603", "block_id": "BLK-13",
                          "grid_code": "G13-04", "tag_id": "TAG-8603", "risk_revision": 1})
    folder = tmp_path / "permit"
    folder.mkdir()
    assets = tmp_path / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "permit_signature.txt").write_bytes((FIXTURES / "assets" / "permit_signature.txt").read_bytes())
    path = folder / "t603_permit.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def cli(*args):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-m", "treecase", *map(str, args)],
                          cwd=ROOT, env=env, text=True, capture_output=True)


def test_snapshot_binds_adjudication_to_risk_revision(tmp_path):
    case = normal_case(tmp_path)
    snap = case.snapshot()
    assert snap["adjudication"] == {"state": "approved", "reasons": []}
    assert snap["tree"]["risk"] == "high" and snap["tree"]["revision"] == 1
    assert adjudication_ref(snap) == "PER-101-NORMAL#rev1"
    assert snap["decision_event_id"] == "permit-t101-normal"
    assert [e["captured_by"] for e in snap["inspection"]["evidence"]] == ["PATROL-A", "PATROL-B"]
    case.import_source("tree", "t101_late_urgent.json")
    revised = case.snapshot()
    assert revised["adjudication"]["state"] == "denied"
    assert "STALE_RISK_REVISION" in revised["adjudication"]["reasons"]
    assert revised["tree"]["revision"] == 2
    assert adjudication_ref(revised) == "PER-101-NORMAL#rev2"
    assert revised["snapshot_digest"] != snap["snapshot_digest"]


def test_expanded_route_refused_when_combined_packets_pin_witness(tmp_path):
    case = normal_case(tmp_path)
    result = issue_packet(case.snapshot(), CONSTRAINTS, ATTESTATIONS, route="expanded")
    assert not result["issued"] and result["manual_review"]
    decision = result["route_decisions"]["expanded"]
    assert not decision["issuable"]
    assert decision["reasons"] == ["WITNESS_UNIQUELY_IDENTIFIABLE:lean"]
    assert decision["witness_possibilities"]["lean"] == 1
    people = CONSTRAINTS["people"]
    old_only = witness_domains(people, CONSTRAINTS["old_public_constraints"])
    assert old_only["possibilities"]["lean"] == ["A", "B"]
    new_only = witness_domains(people, option_constraints(CONSTRAINTS, "expanded"))
    assert new_only["possibilities"]["lean"] == ["B", "C"]
    combined = witness_domains(people, CONSTRAINTS["old_public_constraints"] + option_constraints(CONSTRAINTS, "expanded"))
    assert combined["possibilities"]["lean"] == ["B"]


def test_relationship_only_packet_recomputes_approval(tmp_path):
    case = normal_case(tmp_path)
    result = issue_packet(case.snapshot(), CONSTRAINTS, ATTESTATIONS)
    assert result["issued"] and result["route"] == "relationship-only"
    packet = result["packet"]
    assert packet["target"]["adjudication_ref"] == "PER-101-NORMAL#rev1"
    assert packet["target"]["decision_event_id"] == "permit-t101-normal"
    assert packet["access"] == {"originals_inspectable": False, "per_item_lookup": False,
                                "attachment_projection": False, "closed_review": True}
    blob = json.dumps(packet)
    assert "PATROL" not in blob and "attachment_sha256" not in blob and "alias" not in blob
    assert packet["distinctness"]["basis"] == "relation-credential"
    assert packet["relation_credential"]["credential_id"] == "REL-101-REV1"
    assert packet["privacy"]["witness_possibilities"]["lean"] == 2
    check = verify_packet(packet)
    assert check["valid"], check["problems"]
    assert check["recomputed_risk"] == "high"
    assert check["recomputed_outcome"] == "approved" and check["recomputed_reasons"] == []
    assert check["freshness_ok"] and check["seal_window_ok"] and check["distinctness_ok"]


def test_old_packet_still_verifies_after_risk_revision(tmp_path):
    case = normal_case(tmp_path)
    first = issue_packet(case.snapshot(), CONSTRAINTS, ATTESTATIONS)
    assert first["issued"] and first["packet"]["target"]["risk_revision"] == 1
    case.import_source("tree", "t101_late_urgent.json")
    revised = case.snapshot()
    assert revised["adjudication"]["state"] == "denied"
    second = issue_packet(revised, CONSTRAINTS, ATTESTATIONS)
    assert second["issued"] and second["packet"]["target"]["risk_revision"] == 2
    check_second = verify_packet(second["packet"])
    assert check_second["valid"], check_second["problems"]
    assert check_second["recomputed_outcome"] == "denied"
    assert "STALE_RISK_REVISION" in check_second["recomputed_reasons"]
    assert not check_second["seal_window_ok"]
    check_first = verify_packet(first["packet"])
    assert check_first["valid"] and check_first["recomputed_outcome"] == "approved"
    assert first["packet"]["target"]["snapshot_digest"] != second["packet"]["target"]["snapshot_digest"]


def test_same_collector_cannot_be_packaged_as_distinct(tmp_path):
    case = Case(tmp_path)
    case.import_source("tree", "t603_single_source.json")
    engine.import_file(case.db, write_permit_603(tmp_path))
    snap = case.snapshot("PER-603-NORMAL")
    assert snap["adjudication"]["state"] == "denied"
    assert "UNVERIFIED_TREE_RISK" in snap["adjudication"]["reasons"]
    constraints = {"people": ["A", "B", "C"], "old_public_constraints": [],
                   "new_alias_options": [{"id": "expanded", "proves_distinct": ["lean", "hollow"]},
                                         {"id": "relationship-only", "proves_distinct": ["lean", "hollow"]}]}
    refused = issue_packet(snap, constraints, {"credentials": []})
    assert not refused["issued"] and refused["manual_review"]
    assert "DISTINCTNESS_NOT_IN_ORIGINALS" in refused["route_decisions"]["expanded"]["reasons"]
    assert "DISTINCTNESS_NOT_IN_ORIGINALS" in refused["route_decisions"]["relationship-only"]["reasons"]
    fake = {"credentials": [{"credential_id": "REL-603-FAKE",
                             "adjudication_ref": "PER-603-NORMAL#rev1",
                             "attestor_id": "ATTESTOR-Q",
                             "evidence_ids": ["EV-T603-L1", "EV-T603-H1"],
                             "distinct": True,
                             "grade_inputs": {"lean_angle_deg": 19.0, "hollow_ratio": 0.5},
                             "effective_delta_seconds": 300}]}
    still_refused = issue_packet(snap, constraints, fake, route="relationship-only")
    assert not still_refused["issued"]
    reasons = still_refused["route_decisions"]["relationship-only"]["reasons"]
    assert any("CONTRADICTS_ORIGINALS" in reason for reason in reasons)
    honest_constraints = {"people": ["A", "B", "C"], "old_public_constraints": [],
                          "new_alias_options": [{"id": "expanded"}]}
    honest = issue_packet(snap, honest_constraints, {"credentials": []}, route="expanded")
    assert honest["issued"]
    packet = honest["packet"]
    aliases = {item["kind"]: item["alias"] for item in packet["inspection"]["evidence"]}
    assert aliases["lean"] == aliases["hollow"]
    assert packet["distinctness"]["pairs"] == []
    check = verify_packet(packet)
    assert check["valid"], check["problems"]
    assert check["recomputed_risk"] == "unverified"
    assert check["recomputed_risk_reasons"] == ["INSUFFICIENT_INDEPENDENT_EVIDENCE"]
    assert check["recomputed_outcome"] == "denied"
    assert "UNVERIFIED_TREE_RISK" in check["recomputed_reasons"]


def test_credential_must_match_revision_and_keep_attestor_independent(tmp_path):
    case = normal_case(tmp_path)
    snap = case.snapshot()
    wrong_revision = {"credentials": [dict(ATTESTATIONS["credentials"][1])]}
    result = issue_packet(snap, CONSTRAINTS, wrong_revision, route="relationship-only")
    assert not result["issued"]
    reason = result["route_decisions"]["relationship-only"]["reasons"][0]
    assert reason.startswith("RELATION_CREDENTIAL_INVALID") and "ADJUDICATION_REF_MISMATCH" in reason
    insider = dict(ATTESTATIONS["credentials"][0])
    insider["credential_id"] = "REL-101-INSIDER"
    insider["attestor_id"] = "PATROL-A"
    result = issue_packet(snap, CONSTRAINTS, {"credentials": [insider]}, route="relationship-only")
    assert not result["issued"]
    assert "ATTESTOR_NOT_INDEPENDENT" in result["route_decisions"]["relationship-only"]["reasons"][0]
    result = issue_packet(snap, CONSTRAINTS, {"credentials": []}, route="relationship-only")
    assert result["route_decisions"]["relationship-only"]["reasons"] == ["RELATION_CREDENTIAL_MISSING"]


def test_packet_times_are_relative_offsets_from_one_origin(tmp_path):
    case = normal_case(tmp_path)
    packet = issue_packet(case.snapshot(), CONSTRAINTS, ATTESTATIONS)["packet"]
    blob = json.dumps(packet)
    assert "2026-03-01T09" not in blob and "2026-03-02T10" not in blob
    assert packet["time_unit"] == "seconds"
    observed = packet["inspection"]["observed_offset"]
    for item in packet["inspection"]["evidence"]:
        assert abs(observed - item["capture_offset"]) <= 7 * 24 * 3600
    seal = packet["adjudication"]["seal"]
    assert seal["from_offset"] <= packet["permit"]["approved_offset"] <= seal["to_offset"]
    assert seal["radius_m"] == 12


def test_tampered_packet_fails_verification(tmp_path):
    case = normal_case(tmp_path)
    packet = issue_packet(case.snapshot(), CONSTRAINTS, ATTESTATIONS)["packet"]
    tampered = copy.deepcopy(packet)
    tampered["adjudication"]["permit_outcome"] = "denied"
    check = verify_packet(tampered)
    assert not check["valid"]
    assert "PACKET_ID_MISMATCH" in check["problems"]
    assert "PERMIT_OUTCOME_MISMATCH" in check["problems"]


def test_cli_review_packet_entrypoint(tmp_path):
    db = tmp_path / "case.db"
    good = cli("tree-import", "--db", db, "--file", FIXTURES / "tree" / "t101_initial.json")
    assert good.returncode == 0, good.stderr
    good = cli("permit-import", "--db", db, "--file", FIXTURES / "permit" / "t101_prune_normal.json")
    assert good.returncode == 0, good.stderr
    out = cli("review-packet", "--db", db, "--permit", "PER-101-NORMAL",
              "--constraints", ROOT / "fixtures" / "review_packet_constraints.json",
              "--attestations", ROOT / "fixtures" / "review_packet_attestations.json")
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert payload["issued"] and payload["route"] == "relationship-only"
    assert payload["packet"]["target"]["adjudication_ref"] == "PER-101-NORMAL#rev1"
    refused = cli("review-packet", "--db", db, "--permit", "PER-101-NORMAL",
                  "--constraints", ROOT / "fixtures" / "review_packet_constraints.json",
                  "--attestations", ROOT / "fixtures" / "review_packet_attestations.json",
                  "--route", "expanded")
    assert refused.returncode == 0, refused.stderr
    payload = json.loads(refused.stdout)
    assert not payload["issued"] and payload["manual_review"]
    assert any(r.startswith("WITNESS_UNIQUELY_IDENTIFIABLE")
               for r in payload["route_decisions"]["expanded"]["reasons"])
