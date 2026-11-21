"""End-to-end decisions backed by the bundled synthetic evidence files."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from treecase import engine, evidence, report, store
from treecase.demo import FIXTURES, run


ROOT = Path(__file__).resolve().parents[1]


class EvidenceDeskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "case.db"

    def source(self, category, name):
        return FIXTURES / category / name

    def import_source(self, category, name):
        return engine.import_file(self.db, self.source(category, name))

    def state(self):
        return report.snapshot(self.db)

    def setup_tree(self, name):
        return self.import_source("tree", name)

    def modified_source(self, category, name, change):
        original = self.source(category, name)
        doc = json.loads(original.read_text(encoding="utf-8"))
        change(doc)
        destination = Path(self.tmp.name) / category / name
        destination.parent.mkdir(exist_ok=True)
        for relative in evidence._paths(doc):
            original_asset = (original.parent / relative).resolve()
            copied_asset = (destination.parent / relative).resolve()
            copied_asset.parent.mkdir(exist_ok=True)
            shutil.copyfile(original_asset, copied_asset)
        destination.write_text(json.dumps(doc), encoding="utf-8")
        return destination

    def cli(self, *args):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, "-m", "treecase", *map(str, args)],
                              cwd=ROOT, env=env, text=True, capture_output=True)

    def test_import_is_current_repository_code(self):
        self.assertEqual(Path(engine.__file__).resolve().parents[1], ROOT)

    def test_demo_replays_all_sources_and_cross_subsystem_conclusions(self):
        result = run(self.db)
        self.assertEqual(result["event_count"], 29)
        self.assertTrue(result["projection_matches_replay"])
        self.assertTrue(result["artifact_integrity"])
        state = self.state()
        self.assertEqual(state["trees"]["101"]["risk"], "low")
        self.assertEqual(state["trees"]["101"]["basis"]["prior_risk"], "urgent")
        self.assertEqual(state["trees"]["101"]["revision"], 3)
        self.assertEqual(state["permits"]["PER-101-EMERGENCY"]["state"], "approved")
        self.assertEqual(state["works"]["W-101"]["state"], "accepted")
        self.assertEqual(state["permits"]["PER-701-REVOKE"]["state"], "revoked")
        self.assertEqual(state["works"]["W-701-PRIOR"]["state"], "disputed")

    def test_tree_identity_conflict_preserves_master(self):
        self.setup_tree("t601_identity_base.json")
        before = self.state()["trees"]["601"]
        result = self.setup_tree("t601_identity_conflict.json")
        self.assertEqual(result["outcome"], "identity_conflict")
        self.assertEqual(self.state()["trees"]["601"], before)

    def test_two_independent_fresh_evidence_sources_are_required(self):
        expired = self.setup_tree("t602_expired_photo.json")
        single = self.setup_tree("t603_single_source.json")
        self.assertIn("STALE_EVIDENCE", expired["reasons"])
        self.assertIn("INSUFFICIENT_INDEPENDENT_EVIDENCE", single["reasons"])
        self.assertEqual(self.state()["trees"]["602"]["risk"], "unverified")

    def test_later_inspection_changes_risk_revision_and_seal(self):
        self.setup_tree("t101_initial.json")
        old = self.state()["trees"]["101"]
        self.setup_tree("t101_late_urgent.json")
        new = self.state()["trees"]["101"]
        self.assertEqual((old["risk"], new["risk"]), ("high", "urgent"))
        self.assertEqual((old["revision"], new["revision"]), (1, 2))
        self.assertNotEqual(old["seal_to"], new["seal_to"])
        self.assertEqual((old["seal_radius_m"], new["seal_radius_m"]), (12, 30))

    def test_protected_tree_requires_special_authorization(self):
        self.setup_tree("t201_protected.json")
        result = self.import_source("permit", "t201_protected_remove_denied.json")
        self.assertEqual(result["outcome"], "denied")
        self.assertIn("PROTECTED_AUTHORIZATION_MISSING", result["reasons"])

    def test_special_authorization_changes_protected_tree_conclusion(self):
        self.setup_tree("t201_protected.json")
        def authorize(doc):
            doc["permit"]["protected_authorization"] = "SYNTHETIC-SPECIAL-APPROVAL-201"
        source = self.modified_source("permit", "t201_protected_prune.json", authorize)
        result = engine.import_file(self.db, source)
        self.assertEqual(result["outcome"], "approved")

    def test_expired_seal_blocks_new_permit(self):
        self.setup_tree("t202_seal_window.json")
        result = self.import_source("permit", "t202_expired_seal_denied.json")
        self.assertIn("SEAL_NOT_ACTIVE_AT_APPROVAL", result["reasons"])

    def test_permit_risk_revision_and_work_are_cross_bound(self):
        self.setup_tree("t101_initial.json")
        self.import_source("permit", "t101_prune_normal.json")
        self.setup_tree("t101_late_urgent.json")
        self.import_source("permit", "t101_emergency.json")
        receipt = self.import_source("work", "t101_complete.json")
        self.assertEqual(receipt["outcome"], "accepted")
        self.assertEqual(self.state()["permits"]["PER-101-NORMAL"]["terms"]["risk_revision"], 1)

    def test_work_cannot_use_valid_permit_after_seal_expires(self):
        self.setup_tree("t101_initial.json")
        self.setup_tree("t101_late_urgent.json")
        def extend_permit(doc):
            doc["permit"]["valid_to"] = "2026-03-15T18:00:00+08:00"
        permit = self.modified_source("permit", "t101_emergency.json", extend_permit)
        engine.import_file(self.db, permit)
        def delay_work(doc):
            doc["work"]["performed_at"] = "2026-03-08T09:00:00+08:00"
            doc["work"]["reinspection"]["witnessed_at"] = "2026-03-08T10:00:00+08:00"
        work = self.modified_source("work", "t101_complete.json", delay_work)
        result = engine.import_file(self.db, work)
        self.assertIn("SEAL_NOT_ACTIVE_AT_WORK", result["reasons"])
        self.assertNotIn("WORK_OUTSIDE_PERMIT_WINDOW", result["reasons"])

    def test_parallel_conflicting_permits_do_not_both_approve(self):
        self.setup_tree("t401_permit_conflict.json")
        first = self.import_source("permit", "t401_conflict_a.json")
        second = self.import_source("permit", "t401_conflict_b.json")
        self.assertEqual(first["outcome"], "approved")
        self.assertIn("CONFLICTING_PARALLEL_PERMIT", second["reasons"])

    def test_work_outside_validity_is_held(self):
        self.setup_tree("t301_permit_window.json")
        self.import_source("permit", "t301_short_window.json")
        result = self.import_source("work", "t301_outside_window.json")
        self.assertIn("WORK_OUTSIDE_PERMIT_WINDOW", result["reasons"])

    def test_cut_scope_and_missing_reinspection_are_independent(self):
        self.setup_tree("t501_work_scope.json")
        self.import_source("permit", "t501_scope.json")
        over = self.import_source("work", "t501_overcut.json")
        no_review = self.import_source("work", "t501_no_reinspection.json")
        self.assertIn("CUT_DIAMETER_OVER_SCOPE", over["reasons"])
        self.assertIn("REINSPECTION_MISSING", no_review["reasons"])

    def test_count_scope_is_distinct_from_diameter_scope(self):
        self.setup_tree("t501_work_scope.json")
        self.import_source("permit", "t501_scope.json")
        def extra_cut(doc):
            doc["work"]["cuts"][0]["diameter_cm"] = 4.0
            doc["work"]["cuts"][0]["count"] = 2
        source = self.modified_source("work", "t501_overcut.json", extra_cut)
        result = engine.import_file(self.db, source)
        self.assertIn("CUT_COUNT_OVER_SCOPE", result["reasons"])
        self.assertNotIn("CUT_DIAMETER_OVER_SCOPE", result["reasons"])

    def test_non_independent_reinspection_cannot_release_seal(self):
        self.setup_tree("t101_initial.json")
        self.setup_tree("t101_late_urgent.json")
        self.import_source("permit", "t101_emergency.json")
        def same_operator(doc):
            doc["work"]["reinspection"]["witness_id"] = doc["work"]["operator_id"]
        source = self.modified_source("work", "t101_complete.json", same_operator)
        result = engine.import_file(self.db, source)
        self.assertIn("REINSPECTION_NOT_INDEPENDENT", result["reasons"])
        self.assertIsNone(self.state()["trees"]["101"]["release_work_id"])

    def test_revocation_disputes_prior_work_and_blocks_future_work(self):
        self.setup_tree("t701_revocation.json")
        self.import_source("permit", "t701_revocable.json")
        self.import_source("work", "t701_prior_accepted.json")
        self.assertEqual(self.state()["works"]["W-701-PRIOR"]["state"], "accepted")
        self.assertEqual(self.state()["trees"]["701"]["release_work_id"], "W-701-PRIOR")
        self.import_source("permit", "t701_revocation.json")
        self.assertEqual(self.state()["works"]["W-701-PRIOR"]["state"], "disputed")
        self.assertIsNone(self.state()["trees"]["701"]["release_work_id"])
        blocked = self.import_source("work", "t701_future_blocked.json")
        self.assertIn("NO_ACTIVE_PERMIT", blocked["reasons"])

    def test_revocation_invalidates_counter_evidence_from_disputed_work(self):
        self.setup_tree("t101_initial.json")
        self.setup_tree("t101_late_urgent.json")
        self.import_source("permit", "t101_emergency.json")
        self.import_source("work", "t101_complete.json")
        self.assertEqual(self.state()["trees"]["101"]["risk"], "low")
        def revoke(doc):
            doc["event_id"] = "revoke-t101-test"
            doc["revocation"]["permit_id"] = "PER-101-EMERGENCY"
        source = self.modified_source("permit", "t701_revocation.json", revoke)
        engine.import_file(self.db, source)
        state = self.state()
        self.assertEqual(state["trees"]["101"]["risk"], "urgent")
        self.assertEqual(state["trees"]["101"]["revision"], 4)
        self.assertIsNone(state["trees"]["101"]["release_work_id"])
        self.assertEqual(state["works"]["W-101"]["state"], "disputed")

    def test_same_source_is_idempotent_and_conflict_is_error(self):
        path = self.source("tree", "t101_initial.json")
        self.import_source("tree", path.name)
        self.assertTrue(engine.import_file(self.db, path)["duplicate"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["source"]["reference"] = "different-source"
        altered = Path(self.tmp.name) / "altered.json"
        altered.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(evidence.SourceError):
            engine.import_file(self.db, altered)
        self.assertEqual(engine.audit(self.db)["event_count"], 1)

    def test_late_import_order_does_not_change_current_conclusion(self):
        first_db = self.db
        second_db = Path(self.tmp.name) / "second.db"
        initial = self.source("tree", "t101_initial.json")
        urgent = self.source("tree", "t101_late_urgent.json")
        engine.import_file(first_db, initial)
        engine.import_file(first_db, urgent)
        engine.import_file(second_db, urgent)
        engine.import_file(second_db, initial)
        self.assertEqual(report.snapshot(first_db)["trees"], report.snapshot(second_db)["trees"])
        self.assertTrue(engine.audit(second_db)["projection_matches_replay"])

    def test_invalid_cut_rolls_back_event_and_projection(self):
        self.setup_tree("t501_work_scope.json")
        self.import_source("permit", "t501_scope.json")
        path = self.source("work", "t501_overcut.json")
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["work"]["cuts"][0]["count"] = -2
        # Keep the fixture-relative evidence paths valid without modifying the repository.
        bad = Path(self.tmp.name) / "work" / "bad.json"
        bad.parent.mkdir()
        (Path(self.tmp.name) / "assets").mkdir()
        for artifact in ("reinspection_501.txt",):
            (Path(self.tmp.name) / "assets" / artifact).write_bytes((FIXTURES / "assets" / artifact).read_bytes())
        bad.write_text(json.dumps(doc), encoding="utf-8")
        before = self.state()
        with self.assertRaises(ValueError):
            engine.import_file(self.db, bad)
        self.assertEqual(self.state(), before)
        self.assertEqual(engine.audit(self.db)["event_count"], 2)

    def test_projection_tampering_is_detected_by_replay(self):
        self.setup_tree("t101_initial.json")
        with store.session(self.db) as db:
            db.execute("UPDATE tree_projection SET risk='low' WHERE tree_no='101'")
        check = engine.audit(self.db, FIXTURES)
        self.assertFalse(check["projection_matches_replay"])
        self.assertIn("tree_projection:101", check["projection_mismatches"])

    def test_inspections_evidence_seal_and_reinspection_have_queryable_records(self):
        self.setup_tree("t101_initial.json")
        self.setup_tree("t101_late_urgent.json")
        self.import_source("permit", "t101_emergency.json")
        self.import_source("work", "t101_complete.json")
        with store.session(self.db) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tree_archives").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inspections").fetchone()[0], 3)
            evidence_row = db.execute("SELECT artifact_sha256 FROM evidence_items WHERE evidence_id='EV-T101-L1'").fetchone()
            self.assertEqual(len(evidence_row[0]), 64)
            seal = db.execute("SELECT radius_m,release_work_id FROM seal_orders WHERE tree_no='101'").fetchone()
            self.assertEqual(tuple(seal), (30, "W-101"))
            witness = db.execute("SELECT stable,independent FROM reinspections WHERE work_id='W-101'").fetchone()
            self.assertEqual(tuple(witness), (1, 1))
        self.assertTrue(engine.audit(self.db)["projection_matches_replay"])

    def test_source_journal_cannot_be_updated(self):
        self.setup_tree("t101_initial.json")
        with self.assertRaises(Exception):
            with store.session(self.db) as db:
                db.execute("UPDATE events SET raw_sha256='fake'")

    def test_asset_hash_audit_detects_changed_source_file(self):
        source = self.modified_source("tree", "t101_initial.json", lambda doc: None)
        engine.import_file(self.db, source)
        self.assertTrue(engine.audit(self.db, Path(self.tmp.name))["artifact_integrity"])
        asset = Path(self.tmp.name) / "assets" / "lean_101_a.txt"
        asset.write_bytes(asset.read_bytes() + b"tampered")
        result = engine.audit(self.db, Path(self.tmp.name))
        self.assertFalse(result["artifact_integrity"])
        self.assertTrue(result["source_integrity"])

    def test_cli_normal_and_bad_fixture(self):
        good = self.cli("tree-import", "--db", self.db, "--file", self.source("tree", "t101_initial.json"))
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)["outcome"], "high")
        bad = self.cli("work-import", "--db", self.db, "--file", self.source("tree", "t101_initial.json"))
        self.assertEqual(bad.returncode, 2)
        self.assertIn("expected work", bad.stderr)
        check = self.cli("audit", "--db", self.db)
        self.assertEqual(json.loads(check.stdout)["event_count"], 1)

    def test_cli_business_denial_is_recorded_and_reported(self):
        for name in ("t601_identity_base.json", "t601_identity_conflict.json"):
            completed = self.cli("tree-import", "--db", self.db, "--file", self.source("tree", name))
            self.assertEqual(completed.returncode, 0, completed.stderr)
        state = json.loads(self.cli("report", "--db", self.db).stdout)
        decision = next(d for d in state["decisions"] if d["event_id"] == "tree-t601-conflict")
        self.assertEqual(decision["outcome"], "identity_conflict")
        self.assertEqual(state["trees"]["601"]["identity"]["tag_id"], "TAG-6001")


if __name__ == "__main__":
    unittest.main()
