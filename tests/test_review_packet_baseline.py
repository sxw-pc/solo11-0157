import json
from pathlib import Path

from treecase.permit_policy import apply_permit
from treecase.tree_policy import apply_tree

FIXTURES = Path(__file__).resolve().parents[1] / "treecase" / "fixtures"


def load(category, name):
    return json.loads((FIXTURES / category / name).read_text(encoding="utf-8"))


def test_inspection_revision_changes_normal_pruning_authorization():
    trees = {}
    initial = load("tree", "t101_initial.json")
    permit = load("permit", "t101_prune_normal.json")
    assert apply_tree(initial, trees)[0] == "high"
    assert apply_permit(permit, trees, {})[0] == "approved"
    assert apply_tree(load("tree", "t101_late_urgent.json"), trees)[0] == "urgent"
    state, reasons, _ = apply_permit(permit, trees, {})
    assert state == "denied"
    assert "STALE_RISK_REVISION" in reasons
