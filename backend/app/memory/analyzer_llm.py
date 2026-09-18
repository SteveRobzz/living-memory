"""Optional LLM analyzer.

Same output type as the rule analyzer. Only the classification step changes;
resolver, lifecycle, retrieval and trace are untouched, which is the point.

Enable with ANALYZER=llm plus one key. Works with Anthropic, Groq or Google
(Groq and Google both issue free keys with no card, if you need one fast).

The model is asked ONLY for categories. It is never asked for a status,
never told what the current value is, and never allowed to decide a conflict.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List

import httpx

from ..config import get_settings
from .analyzer import Analysis, QueryIntent, _analyze_query
from .normalize import display_value, normalize_value
from .resolver import Candidate

SYSTEM = """You label a single user message for a memory system.
Return ONLY JSON, no prose and no markdown fences.

{"candidates":[{"key":"snake_case.attribute","value":"the value",
  "memory_type":"FACT|PREFERENCE|GOAL|PROJECT|DECISION|RELATIONSHIP|TEMPORARY_CONTEXT",
  "assertion":"STATEMENT|CHANGE|CORRECTION|IMPLIED|PAST|NEGATION|RETRACT|HYPOTHETICAL|NON_LITERAL",
  "cardinality":"SINGLE|MULTI"}]}

Rules:
- Only lasting information. "I'm hungry" yields no candidates.
- Reuse an existing key when the message is about that same attribute.
- Never invent a status, confidence or decision about which value is correct.
- One attribute per candidate. "favorite language" and "work language" differ.
"""


def _post_anthropic(key: str, prompt: str) -> str:
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={"model": "claude-haiku-4-5-20251001", "max_tokens": 700,
              "temperature": 0, "system": SYSTEM,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=20,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _post_groq(key: str, prompt: str) -> str:
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "llama-3.3-70b-versatile", "temperature": 0,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": prompt}]},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def analyze_with_llm(text: str, now: datetime, existing_keys: List[str] | None = None) -> Analysis:
    s = get_settings()
    prompt = (f"Today is {now.date().isoformat()}.\n"
              f"Existing keys for this user: {existing_keys or []}\n"
              f"Message: {text}")

    if s.anthropic_api_key:
        raw = _post_anthropic(s.anthropic_api_key, prompt)
    elif s.groq_api_key:
        raw = _post_groq(s.groq_api_key, prompt)
    else:
        raise RuntimeError("ANALYZER=llm but no API key configured")

    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    data = json.loads(raw)

    query: QueryIntent = _analyze_query(text, now)
    candidates: List[Candidate] = []
    if not query.needs_memory:
        for c in data.get("candidates", []):
            value = str(c.get("value", "")).strip()
            if not value:
                continue
            candidates.append(Candidate(
                key=str(c.get("key", "")).strip() or "fact",
                value=display_value(value),
                value_norm=normalize_value(value),
                memory_type=c.get("memory_type", "FACT"),
                cardinality=c.get("cardinality", "SINGLE"),
                assertion=c.get("assertion", "STATEMENT"),
                valid_from=now,
                raw_text=text,
            ))
    return Analysis(candidates=candidates, query=query, backend="llm")
