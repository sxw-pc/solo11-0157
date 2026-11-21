"""Issue a field-coverage data delivery decision for the current transect."""

def setup(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS field_delivery(
            case_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            evidence_id TEXT NOT NULL
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
