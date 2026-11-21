"""Raw-source capture, referenced artifact hashing and replay integrity."""

import hashlib
import json
from pathlib import Path


class SourceError(ValueError):
    pass


KIND_BY_SCHEMA = {
    "treecase.tree.v1": "tree",
    "treecase.permit.v1": "permit",
    "treecase.work.v1": "work",
    "treecase.permit_revocation.v1": "revocation",
}


def _paths(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("file", "signature_file", "notice_file") and value:
                yield value
            else:
                yield from _paths(value)
    elif isinstance(node, list):
        for value in node:
            yield from _paths(value)


def read_source(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    try:
        doc = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema") not in KIND_BY_SCHEMA:
        raise SourceError("unsupported event schema")
    if not doc.get("event_id") or not doc.get("recorded_at"):
        raise SourceError("event_id and recorded_at are required")
    kind = KIND_BY_SCHEMA[doc["schema"]]
    if not isinstance(doc.get(kind), dict) and kind != "revocation":
        raise SourceError(f"missing {kind} object")
    if kind == "revocation" and not isinstance(doc.get("revocation"), dict):
        raise SourceError("missing revocation object")
    artifacts = {}
    for relative in sorted(set(_paths(doc))):
        target = (path.parent / relative).resolve()
        if not target.is_relative_to(path.parent.parent):
            raise SourceError(f"artifact outside fixture tree: {relative}")
        if not target.is_file():
            raise SourceError(f"missing artifact: {relative}")
        artifacts[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    return kind, doc, raw, artifacts


def verify_event(row):
    if hashlib.sha256(row["raw_bytes"]).hexdigest() != row["raw_sha256"]:
        return False
    try:
        return json.loads(row["raw_bytes"]) == json.loads(row["payload_json"])
    except (UnicodeError, json.JSONDecodeError):
        return False


def verify_artifacts(row, fixture_root):
    """Check currently available fixture files against captured source hashes."""
    doc = json.loads(row["payload_json"])
    root = Path(fixture_root)
    category = row["kind"] if row["kind"] != "revocation" else "permit"
    base = root / category
    hashes = json.loads(row["artifacts_json"])
    for relative in _paths(doc):
        target = (base / relative).resolve()
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != hashes.get(relative):
            return False
    return True
