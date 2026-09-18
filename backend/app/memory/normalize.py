"""Value normalisation.

Keeps "C++", "cpp" and "C plus plus" from becoming three different memories.
Deterministic, table-driven, no model involved.
"""
from __future__ import annotations
import re

VALUE_ALIASES = {
    "cpp": "c++", "c plus plus": "c++", "cplusplus": "c++",
    "js": "javascript", "ts": "typescript",
    "py": "python", "python3": "python",
    "golang": "go",
    "nextjs": "next.js", "next js": "next.js",
    "nodejs": "node.js", "node js": "node.js",
    "postgres": "postgresql", "psql": "postgresql",
    "unreal engine": "unreal", "ue5": "unreal",
    "godot engine": "godot",
    "unity3d": "unity", "unity engine": "unity",
}

_PUNCT = re.compile(r"[^\w\s\+\#\.\-]")
_WS = re.compile(r"\s+")


def normalize_value(value: str) -> str:
    v = value.strip().lower()
    v = _PUNCT.sub("", v)
    v = _WS.sub(" ", v).strip()
    v = v.rstrip(".")
    return VALUE_ALIASES.get(v, v)


def display_value(value: str) -> str:
    """Tidy the user's own casing for display without inventing a new spelling."""
    return _WS.sub(" ", value.strip()).rstrip(".,!?")
