import json
from pathlib import Path

from treecase import field_track, store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "field_track_baseline.json"


def test_corrected_overlap_withholds_same_field_delivery(tmp_path):
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["passes"]
    with store.session(tmp_path / "field.sqlite") as db:
        assert field_track.capture(db, cases[0]) == {"outcome": "complete", "delivery": "ready"}
        assert field_track.capture(db, cases[1]) == {"outcome": "short", "delivery": "withheld"}
        assert tuple(db.execute(
            "SELECT status,evidence_id FROM field_delivery WHERE case_id='DEMO-PLOT'"
        ).fetchone()) == ("withheld", "FIELD-2")
