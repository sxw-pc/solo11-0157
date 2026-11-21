"""Regenerate the synthetic, offline-only JSON fixtures used by treecase."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "treecase" / "fixtures"
ASSETS = [
    "lean_101_a.txt", "hollow_101_b.txt", "lean_101_urgent_c.txt", "hollow_101_urgent_d.txt",
    "counter_lean_101_e.txt", "counter_hollow_101_f.txt", "lean_201_a.txt", "hollow_201_b.txt",
    "lean_202_a.txt", "hollow_202_b.txt", "lean_301_a.txt", "hollow_301_b.txt", "lean_401_a.txt",
    "hollow_401_b.txt", "lean_501_a.txt", "hollow_501_b.txt", "lean_601_a.txt", "hollow_601_b.txt",
    "lean_602_expired.txt", "hollow_602_b.txt", "lean_603_single.txt", "hollow_603_single.txt",
    "lean_701_a.txt", "hollow_701_b.txt", "permit_signature.txt", "reinspection_101.txt",
    "reinspection_301.txt", "reinspection_501.txt", "reinspection_701.txt", "revocation_notice_t701.txt",
]


def ev(eid, kind, at, by, file, value):
    key = "lean_angle_deg" if kind == "lean" else "hollow_ratio"
    return {"evidence_id": eid, "kind": kind, "capture_at": at, "captured_by": by, "file": file, key: value}


def insp(iid, obs, inspector, org, evidence):
    return {"inspection_id": iid, "inspector_id": inspector, "inspector_org": org,
            "observed_at": obs, "self_reported": False, "evidence": evidence}


def asset(name):
    return "../assets/" + name


def tree(event, recorded, reference, archive, version, no, block, grid, tag, species, protected, inspections):
    return {
        "schema": "treecase.tree.v1", "event_id": event, "recorded_at": recorded,
        "source": {"kind": "patrol_inspection", "reference": reference},
        "tree": {"archive_id": archive, "archive_version": version, "tree_no": no, "block_id": block,
                 "grid_code": grid, "tag_id": tag, "species": species, "protected_level": protected,
                 "planted_year": 1998},
        "inspections": inspections,
    }


def pair(prefix, lean_file, hollow_file, angle, hollow):
    return [
        ev(prefix + "-L", "lean", "2026-03-01T08:55:00+08:00", "PATROL-A", asset(lean_file), angle),
        ev(prefix + "-H", "hollow", "2026-03-01T09:05:00+08:00", "PATROL-B", asset(hollow_file), hollow),
    ]


TREES = {
    "t101_initial.json": tree("tree-t101-initial", "2026-03-01T10:00:00+08:00", "PATROL-2026-0301-101", "ARC-101-01", 1,
        "101", "BLK-07", "G07-14", "TAG-7781", "Styphnolobium japonicum", "ordinary",
        [insp("INS-T101-01", "2026-03-01T09:10:00+08:00", "PATROL-A", "City Forestry Patrol", [
            ev("EV-T101-L1", "lean", "2026-03-01T09:05:00+08:00", "PATROL-A", asset("lean_101_a.txt"), 12.0),
            ev("EV-T101-H1", "hollow", "2026-03-01T09:12:00+08:00", "PATROL-B", asset("hollow_101_b.txt"), 0.22)])]),
    "t101_late_urgent.json": tree("tree-t101-late-urgent", "2026-03-04T09:00:00+08:00", "PATROL-2026-0304-101", "ARC-101-02", 2,
        "101", "BLK-07", "G07-14", "TAG-7781", "Styphnolobium japonicum", "ordinary",
        [insp("INS-T101-02", "2026-03-04T08:00:00+08:00", "PATROL-C", "City Forestry Patrol", [
            ev("EV-T101-L2", "lean", "2026-03-04T07:50:00+08:00", "PATROL-C", asset("lean_101_urgent_c.txt"), 22.0),
            ev("EV-T101-H2", "hollow", "2026-03-04T08:05:00+08:00", "PATROL-D", asset("hollow_101_urgent_d.txt"), 0.48)])]),
    "t201_protected.json": tree("tree-t201-initial", "2026-03-01T10:00:00+08:00", "PATROL-2026-0301-201", "ARC-201-01", 1,
        "201", "BLK-08", "G08-03", "TAG-8120", "Ginkgo biloba", "protected",
        [insp("INS-T201-01", "2026-03-01T09:00:00+08:00", "PATROL-A", "City Forestry Patrol", pair("EV-T201", "lean_201_a.txt", "hollow_201_b.txt", 9.0, 0.25))]),
    "t202_seal_window.json": tree("tree-t202-initial", "2026-03-01T11:00:00+08:00", "PATROL-2026-0301-202", "ARC-202-01", 1,
        "202", "BLK-08", "G08-04", "TAG-8121", "Cinnamomum camphora", "ordinary",
        [insp("INS-T202-01", "2026-03-01T10:00:00+08:00", "PATROL-A", "City Forestry Patrol", pair("EV-T202", "lean_202_a.txt", "hollow_202_b.txt", 11.0, 0.21))]),
    "t301_permit_window.json": tree("tree-t301-initial", "2026-03-01T12:00:00+08:00", "PATROL-2026-0301-301", "ARC-301-01", 1,
        "301", "BLK-10", "G10-02", "TAG-8301", "Fraxinus chinensis", "ordinary",
        [insp("INS-T301-01", "2026-03-01T11:00:00+08:00", "PATROL-A", "City Forestry Patrol", pair("EV-T301", "lean_301_a.txt", "hollow_301_b.txt", 10.0, 0.20))]),
    "t401_permit_conflict.json": tree("tree-t401-initial", "2026-03-01T09:30:00+08:00", "PATROL-2026-0301-401", "ARC-401-01", 1,
        "401", "BLK-11", "G11-05", "TAG-8401", "Acer truncatum", "ordinary",
        [insp("INS-T401-01", "2026-03-01T09:00:00+08:00", "PATROL-A", "City Forestry Patrol", pair("EV-T401", "lean_401_a.txt", "hollow_401_b.txt", 14.0, 0.30))]),
    "t501_work_scope.json": tree("tree-t501-initial", "2026-03-01T10:30:00+08:00", "PATROL-2026-0301-501", "ARC-501-01", 1,
        "501", "BLK-12", "G12-02", "TAG-8501", "Sophora japonica", "ordinary",
        [insp("INS-T501-01", "2026-03-01T10:00:00+08:00", "PATROL-A", "City Forestry Patrol", pair("EV-T501", "lean_501_a.txt", "hollow_501_b.txt", 12.0, 0.20))]),
    "t601_identity_base.json": tree("tree-t601-base", "2026-03-01T10:00:00+08:00", "PATROL-2026-0301-601", "ARC-601-01", 1,
        "601", "BLK-61", "G61-01", "TAG-6001", "Platanus orientalis", "ordinary",
        [insp("INS-T601-01", "2026-03-01T09:30:00+08:00", "PATROL-A", "City Forestry Patrol", pair("EV-T601", "lean_601_a.txt", "hollow_601_b.txt", 9.0, 0.22))]),
    "t601_identity_conflict.json": tree("tree-t601-conflict", "2026-03-02T10:00:00+08:00", "PATROL-2026-0302-601X", "ARC-601-02", 2,
        "601", "BLK-62", "G62-99", "TAG-6002", "Platanus orientalis", "ordinary", []),
    "t602_expired_photo.json": tree("tree-t602-expired-photo", "2026-03-02T10:00:00+08:00", "PATROL-2026-0302-602", "ARC-602-01", 1,
        "602", "BLK-13", "G13-03", "TAG-8602", "Ulmus pumila", "ordinary",
        [insp("INS-T602-01", "2026-03-01T09:10:00+08:00", "PATROL-A", "City Forestry Patrol", [
            ev("EV-T602-L1", "lean", "2026-02-01T09:00:00+08:00", "PATROL-A", asset("lean_602_expired.txt"), 27.0),
            ev("EV-T602-H1", "hollow", "2026-03-01T09:12:00+08:00", "PATROL-B", asset("hollow_602_b.txt"), 0.10)])]),
    "t603_single_source.json": tree("tree-t603-single-source", "2026-03-02T10:00:00+08:00", "PATROL-2026-0302-603", "ARC-603-01", 1,
        "603", "BLK-13", "G13-04", "TAG-8603", "Salix matsudana", "ordinary",
        [insp("INS-T603-01", "2026-03-01T09:00:00+08:00", "PATROL-X", "City Forestry Patrol", [
            ev("EV-T603-L1", "lean", "2026-03-01T09:00:00+08:00", "PATROL-X", asset("lean_603_single.txt"), 19.0),
            ev("EV-T603-H1", "hollow", "2026-03-01T09:05:00+08:00", "PATROL-X", asset("hollow_603_single.txt"), 0.50)])]),
    "t701_revocation.json": tree("tree-t701-initial", "2026-03-01T10:00:00+08:00", "PATROL-2026-0301-701", "ARC-701-01", 1,
        "701", "BLK-14", "G14-02", "TAG-8701", "Celtis sinensis", "ordinary",
        [insp("INS-T701-01", "2026-03-01T09:00:00+08:00", "PATROL-A", "City Forestry Patrol", pair("EV-T701", "lean_701_a.txt", "hollow_701_b.txt", 13.0, 0.24))]),
}


def permit(event, recorded, reference, pid, tree_id, action, maxd, maxc, vf, vt, applied, approved, revision):
    return {
        "schema": "treecase.permit.v1", "event_id": event, "recorded_at": recorded,
        "source": {"kind": "permit_application", "reference": reference},
        "permit": {"permit_id": pid, "tree_no": tree_id[0], "block_id": tree_id[1], "grid_code": tree_id[2],
                   "tag_id": tree_id[3], "requested_action": action, "max_cut_diameter_cm": maxd,
                   "max_cut_count": maxc, "valid_from": vf, "valid_to": vt, "applied_at": applied,
                   "approved_at": approved, "signer_id": "OFFICER-3", "signature_file": asset("permit_signature.txt"),
                   "protected_authorization": None, "risk_revision": revision},
    }


T101 = ("101", "BLK-07", "G07-14", "TAG-7781")
T201 = ("201", "BLK-08", "G08-03", "TAG-8120")
T202 = ("202", "BLK-08", "G08-04", "TAG-8121")
T301 = ("301", "BLK-10", "G10-02", "TAG-8301")
T401 = ("401", "BLK-11", "G11-05", "TAG-8401")
T501 = ("501", "BLK-12", "G12-02", "TAG-8501")
T701 = ("701", "BLK-14", "G14-02", "TAG-8701")
PERMITS = {
    "t101_prune_normal.json": permit("permit-t101-normal", "2026-03-02T10:00:00+08:00", "PERMIT-2026-0302-101N", "PER-101-NORMAL", T101, "prune", 8.0, 2, "2026-03-03T00:00:00+08:00", "2026-03-10T23:59:00+08:00", "2026-03-02T09:00:00+08:00", "2026-03-02T10:00:00+08:00", 1),
    "t101_emergency.json": permit("permit-t101-emergency", "2026-03-04T10:30:00+08:00", "PERMIT-2026-0304-101E", "PER-101-EMERGENCY", T101, "prune", 10.0, 2, "2026-03-04T12:00:00+08:00", "2026-03-05T18:00:00+08:00", "2026-03-04T10:10:00+08:00", "2026-03-04T10:30:00+08:00", 2),
    "t201_protected_prune.json": permit("permit-t201-prune", "2026-03-02T10:00:00+08:00", "PERMIT-2026-0302-201P", "PER-201-PRUNE", T201, "prune", 6.0, 2, "2026-03-02T12:00:00+08:00", "2026-03-03T18:00:00+08:00", "2026-03-02T09:30:00+08:00", "2026-03-02T10:00:00+08:00", 1),
    "t201_protected_remove_denied.json": permit("permit-t201-remove-denied", "2026-03-04T10:00:00+08:00", "PERMIT-2026-0304-201R", "PER-201-REMOVE", T201, "remove", 20.0, 1, "2026-03-04T12:00:00+08:00", "2026-03-05T18:00:00+08:00", "2026-03-04T09:40:00+08:00", "2026-03-04T10:00:00+08:00", 1),
    "t202_expired_seal_denied.json": permit("permit-t202-expired-seal", "2026-03-10T10:00:00+08:00", "PERMIT-2026-0310-202", "PER-202-EXPIRED", T202, "prune", 5.0, 1, "2026-03-10T12:00:00+08:00", "2026-03-12T18:00:00+08:00", "2026-03-10T09:30:00+08:00", "2026-03-10T10:00:00+08:00", 1),
    "t301_short_window.json": permit("permit-t301-short", "2026-03-02T10:00:00+08:00", "PERMIT-2026-0302-301", "PER-301-SHORT", T301, "prune", 5.0, 1, "2026-03-02T12:00:00+08:00", "2026-03-03T18:00:00+08:00", "2026-03-02T09:30:00+08:00", "2026-03-02T10:00:00+08:00", 1),
    "t401_conflict_a.json": permit("permit-t401-a", "2026-03-02T09:00:00+08:00", "PERMIT-2026-0302-401A", "PER-401-A", T401, "prune", 7.0, 2, "2026-03-02T12:00:00+08:00", "2026-03-10T18:00:00+08:00", "2026-03-02T08:30:00+08:00", "2026-03-02T09:00:00+08:00", 1),
    "t401_conflict_b.json": permit("permit-t401-b", "2026-03-03T09:00:00+08:00", "PERMIT-2026-0303-401B", "PER-401-B", T401, "support", 5.0, 1, "2026-03-03T12:00:00+08:00", "2026-03-09T18:00:00+08:00", "2026-03-03T08:30:00+08:00", "2026-03-03T09:00:00+08:00", 1),
    "t501_scope.json": permit("permit-t501-scope", "2026-03-02T10:00:00+08:00", "PERMIT-2026-0302-501", "PER-501-SCOPE", T501, "prune", 5.0, 1, "2026-03-02T12:00:00+08:00", "2026-03-10T18:00:00+08:00", "2026-03-02T09:30:00+08:00", "2026-03-02T10:00:00+08:00", 1),
    "t701_revocable.json": permit("permit-t701-revocable", "2026-03-02T10:00:00+08:00", "PERMIT-2026-0302-701", "PER-701-REVOKE", T701, "prune", 6.0, 2, "2026-03-02T12:00:00+08:00", "2026-03-10T18:00:00+08:00", "2026-03-02T09:30:00+08:00", "2026-03-02T10:00:00+08:00", 1),
}


def reinsp(iid, at, witness, org, file):
    return {"reinspection_id": iid, "witness_id": witness, "witness_org": org,
            "witnessed_at": at, "stable": True, "file": asset(file)}


def work(event, recorded, reference, wid, pid, tree_id, performed, cuts, contractor, operator, inspection=None, counter=None):
    return {
        "schema": "treecase.work.v1", "event_id": event, "recorded_at": recorded,
        "source": {"kind": "field_work_receipt", "reference": reference},
        "work": {"work_id": wid, "permit_id": pid, "tree_no": tree_id[0], "block_id": tree_id[1],
                 "grid_code": tree_id[2], "tag_id": tree_id[3], "contractor_id": contractor,
                 "operator_id": operator, "performed_at": performed, "cuts": cuts,
                 "reinspection": inspection, "counter_evidence": counter},
    }


COUNTER101 = {
    "inspection_id": "INS-W101-COUNTER", "observer_id": "EVAL-9", "observer_org": "Independent Tree Audit Office",
    "inspector_id": "EVAL-9", "inspector_org": "Independent Tree Audit Office",
    "observed_at": "2026-03-05T09:40:00+08:00", "self_reported": False,
    "evidence": [
        ev("EV-W101-CL", "lean", "2026-03-05T09:35:00+08:00", "EVAL-9", asset("counter_lean_101_e.txt"), 6.0),
        ev("EV-W101-CH", "hollow", "2026-03-05T09:42:00+08:00", "EVAL-10", asset("counter_hollow_101_f.txt"), 0.05),
    ],
}
WORKS = {
    "t101_complete.json": work("work-t101-complete", "2026-03-05T11:00:00+08:00", "WORK-2026-0305-101", "W-101", "PER-101-EMERGENCY", T101,
        "2026-03-05T09:00:00+08:00", [{"diameter_cm": 6.0, "count": 1, "part": "lower limb"}], "GREEN-OPS", "OP-9",
        reinsp("R-101", "2026-03-05T10:00:00+08:00", "AUD-22", "Independent Tree Audit Office", "reinspection_101.txt"), COUNTER101),
    "t301_outside_window.json": work("work-t301-outside", "2026-03-04T11:00:00+08:00", "WORK-2026-0304-301", "W-301", "PER-301-SHORT", T301,
        "2026-03-04T09:00:00+08:00", [{"diameter_cm": 2.0, "count": 1, "part": "lower limb"}], "GREEN-OPS", "OP-12",
        reinsp("R-301", "2026-03-04T10:00:00+08:00", "AUD-33", "Independent Tree Audit Office", "reinspection_301.txt")),
    "t501_overcut.json": work("work-t501-overcut", "2026-03-04T11:00:00+08:00", "WORK-2026-0304-501", "W-501-OVERCUT", "PER-501-SCOPE", T501,
        "2026-03-04T09:00:00+08:00", [{"diameter_cm": 6.0, "count": 1, "part": "main scaffold"}], "GREEN-OPS", "OP-14",
        reinsp("R-501", "2026-03-04T10:00:00+08:00", "AUD-44", "Independent Tree Audit Office", "reinspection_501.txt")),
    "t501_no_reinspection.json": work("work-t501-noinspection", "2026-03-05T11:00:00+08:00", "WORK-2026-0305-501", "W-501-NOINSP", "PER-501-SCOPE", T501,
        "2026-03-05T09:00:00+08:00", [{"diameter_cm": 4.0, "count": 1, "part": "lower limb"}], "GREEN-OPS", "OP-14"),
    "t701_prior_accepted.json": work("work-t701-prior", "2026-03-03T11:00:00+08:00", "WORK-2026-0303-701", "W-701-PRIOR", "PER-701-REVOKE", T701,
        "2026-03-03T09:00:00+08:00", [{"diameter_cm": 3.0, "count": 1, "part": "lower limb"}], "GREEN-OPS", "OP-21",
        reinsp("R-701", "2026-03-03T10:00:00+08:00", "AUD-77", "Independent Tree Audit Office", "reinspection_701.txt")),
    "t701_future_blocked.json": work("work-t701-future", "2026-03-08T10:00:00+08:00", "WORK-2026-0308-701", "W-701-FUTURE", "PER-701-REVOKE", T701,
        "2026-03-08T09:00:00+08:00", [{"diameter_cm": 2.0, "count": 1, "part": "lower limb"}], "GREEN-OPS", "OP-21"),
}


def dump(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    for folder in ("assets", "tree", "permit", "work"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        (ROOT / "assets" / name).write_text(f"offline synthetic evidence artifact: {name}\n", encoding="utf-8")
    for name, payload in TREES.items():
        dump(ROOT / "tree" / name, payload)
    for name, payload in PERMITS.items():
        dump(ROOT / "permit" / name, payload)
    for name, payload in WORKS.items():
        dump(ROOT / "work" / name, payload)
    revocation = {
        "schema": "treecase.permit_revocation.v1", "event_id": "revoke-t701-notice",
        "recorded_at": "2026-03-06T12:00:00+08:00",
        "source": {"kind": "revocation_notice", "reference": "REVOKE-2026-0306-701"},
        "revocation": {"permit_id": "PER-701-REVOKE", "revoked_at": "2026-03-06T11:00:00+08:00",
                       "reason": "签章机构撤回许可，既有作业责任待复核", "authority": "Municipal Risk Office",
                       "notice_file": asset("revocation_notice_t701.txt")},
    }
    dump(ROOT / "permit" / "t701_revocation.json", revocation)


if __name__ == "__main__":
    main()
