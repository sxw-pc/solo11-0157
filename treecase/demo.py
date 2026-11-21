"""Runs every bundled independent scenario against one offline ledger."""

from pathlib import Path

from .engine import audit, import_file
from .report import snapshot


FIXTURES = Path(__file__).parent / "fixtures"


def run(db_path, force=False):
    db_path = Path(db_path)
    if db_path.exists() and force:
        db_path.unlink()
    if db_path.exists():
        raise FileExistsError(f"demo database exists: {db_path}; use --force")
    imported = []
    for category in ("tree", "permit", "work"):
        for path in sorted((FIXTURES / category).glob("*.json")):
            imported.append(import_file(db_path, path))
    state = snapshot(db_path)
    result = audit(db_path, FIXTURES)
    result.update({"status": "demo_complete", "outcomes": {
        name: sum(1 for decision in state["decisions"] if decision["outcome"] == name)
        for name in sorted({decision["outcome"] for decision in state["decisions"]})},
        "imported": len(imported)})
    return result
