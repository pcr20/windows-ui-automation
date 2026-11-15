"""Element selectors. Pure Python so it can be tested off Windows.

Syntax: semicolon-separated terms, all of which must match.

    path=0.3.1              exact position in the tree dump (fast, but brittle)
    type=Button             control type (case-insensitive)
    name=Archive e-mail     exact name (case-insensitive)
    name~=archive           name contains
    aid=btnOK               AutomationId (exact)
    class=WindowsForms10... class name contains
    has=Invoke              element supports this pattern
    nth=1                   pick the nth match (0-based, default 0)
"""
from __future__ import annotations

KEYS = {"path", "type", "name", "name~", "aid", "class", "has", "nth"}


def parse(text: str) -> dict:
    sel: dict = {}
    for term in filter(None, (t.strip() for t in text.split(";"))):
        if "=" not in term:
            raise ValueError(f"bad selector term {term!r} (expected key=value)")
        key, value = term.split("=", 1)
        key = key.strip().lower()
        if key not in KEYS:
            raise ValueError(f"unknown selector key {key!r}; use one of {sorted(KEYS)}")
        sel[key] = int(value) if key == "nth" else value.strip()
    if not sel:
        raise ValueError("empty selector")
    return sel


def matches(node: dict, sel: dict) -> bool:
    """node: dict with path, type, name, aid, class, patterns."""
    name = (node.get("name") or "").lower()
    checks = {
        "path": lambda v: node.get("path") == v,
        "type": lambda v: (node.get("type") or "").lower() == v.lower(),
        "name": lambda v: name == v.lower(),
        "name~": lambda v: v.lower() in name,
        "aid": lambda v: (node.get("aid") or "") == v,
        "class": lambda v: v.lower() in (node.get("class") or "").lower(),
        "has": lambda v: v.lower() in [p.lower() for p in node.get("patterns", [])],
    }
    return all(checks[k](v) for k, v in sel.items() if k != "nth")


def pick(nodes: list[dict], sel: dict) -> dict:
    hits = [n for n in nodes if matches(n, sel)]
    nth = sel.get("nth", 0)
    if nth >= len(hits):
        raise LookupError(f"selector matched {len(hits)} element(s); nth={nth} not available")
    return hits[nth]
