"""Issue field-coverage data delivery decisions for the current transect."""

import json


def setup(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS field_delivery(
            case_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            evidence_id TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS field_coverage_delivery(
            case_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            guaranteed_coverage INTEGER NOT NULL,
            minimum INTEGER NOT NULL,
            certain_cells_json TEXT NOT NULL,
            position_certified INTEGER NOT NULL,
            certificate TEXT,
            reasons_json TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            contract_ids_json TEXT NOT NULL
        )"""
    )


def reconsider(db, case_id, outcome, evidence_id):
    setup(db)
    state = "ready" if outcome == "complete" else "withheld"
    db.execute(
        """INSERT INTO field_delivery VALUES (?,?,?)
           ON CONFLICT(case_id) DO UPDATE SET status=excluded.status,
                evidence_id=excluded.evidence_id""",
        (case_id, state, evidence_id),
    )
    return state


def record_coverage(db, decision):
    """Persist the synthetic coverage decision so reviewers can recompute it."""
    setup(db)
    db.execute(
        """INSERT INTO field_coverage_delivery VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(case_id) DO UPDATE SET
                status=excluded.status,
                guaranteed_coverage=excluded.guaranteed_coverage,
                minimum=excluded.minimum,
                certain_cells_json=excluded.certain_cells_json,
                position_certified=excluded.position_certified,
                certificate=excluded.certificate,
                reasons_json=excluded.reasons_json,
                evidence_ids_json=excluded.evidence_ids_json,
                contract_ids_json=excluded.contract_ids_json""",
        (
            decision["case_id"], decision["status"],
            decision["guaranteed_coverage"], decision["required_minimum"],
            json.dumps(decision["certain_cells"]),
            int(decision["position_certified"]), decision["certificate"],
            json.dumps(decision["reasons"]),
            json.dumps(decision["evidence_ids"]),
            json.dumps(decision["contract_ids"]),
        ),
    )
