"""Issue a field-coverage data delivery decision for the current transect."""


def setup(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS field_delivery(
            case_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            evidence_id TEXT NOT NULL
        )"""
    )


def reconsider(db, case_id, outcome, evidence_id, result=None):
    """Reconsider delivery for ``case_id``.

    The three-argument path preserves the nominal-grid baseline: a complete
    transect is ready, a short one is withheld. When a field-contract
    adjudication ``result`` is supplied, its own commitment status decides,
    so a case can be ready on a signed coverage lower bound even though its
    exact position remains ambiguous, or stay withheld pending verification.
    """
    setup(db)
    if result is None:
        state = "ready" if outcome == "complete" else "withheld"
    else:
        state = result["status"]
    db.execute(
        """INSERT INTO field_delivery VALUES (?,?,?)
           ON CONFLICT(case_id) DO UPDATE SET status=excluded.status,
                evidence_id=excluded.evidence_id""",
        (case_id, state, evidence_id),
    )
    return state
