"""Memory extraction and query understanding.

The analyzer's ONLY job is to label a sentence with categories:
    key, value, memory_type, assertion.
It never assigns a status, never decides a contradiction, never writes.
Those decisions belong to resolver.py, which is pure code.

Two interchangeable backends behind one interface:

  "rules" (DEFAULT, no API key)
      Marker phrases + an entity registry. Fully deterministic, instant,
      and offline. Because the engine downstream is identical either way,
      the whole system can be demonstrated with the LLM switched off --
      which is the cleanest possible answer to "isn't this just prompting?".

  "llm"
      Same output schema, produced by a model. Generalises past the
      registry. Enable with ANALYZER=llm once a key is available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .normalize import display_value, normalize_value
from .resolver import Candidate

WILDCARD_KEY = "*"

# ============================================================
# Entity registry — what the rule analyzer knows about
# ============================================================
# This is the one piece an LLM backend replaces. Everything downstream
# (slots, resolver, lifecycle, retrieval, trace) is domain-agnostic.

ENTITIES = {
    # value -> (slot key, memory type, cardinality)
    "unity": ("game.engine", "PROJECT", "SINGLE"),
    "godot": ("game.engine", "PROJECT", "SINGLE"),
    "unreal": ("game.engine", "PROJECT", "SINGLE"),
    "gamemaker": ("game.engine", "PROJECT", "SINGLE"),
    "python": ("main_language", "FACT", "SINGLE"),
    "java": ("main_language", "FACT", "SINGLE"),
    "rust": ("main_language", "FACT", "SINGLE"),
    "c++": ("main_language", "FACT", "SINGLE"),
    "c#": ("main_language", "FACT", "SINGLE"),
    "go": ("main_language", "FACT", "SINGLE"),
    "javascript": ("main_language", "FACT", "SINGLE"),
    "typescript": ("main_language", "FACT", "SINGLE"),
    "kotlin": ("main_language", "FACT", "SINGLE"),
    "ruby": ("main_language", "FACT", "SINGLE"),
    "react": ("web.framework", "PROJECT", "SINGLE"),
    "next.js": ("web.framework", "PROJECT", "SINGLE"),
    "vue": ("web.framework", "PROJECT", "SINGLE"),
    "svelte": ("web.framework", "PROJECT", "SINGLE"),
    "django": ("web.framework", "PROJECT", "SINGLE"),
    "fastapi": ("web.framework", "PROJECT", "SINGLE"),
    "postgresql": ("database", "PROJECT", "SINGLE"),
    "mongodb": ("database", "PROJECT", "SINGLE"),
    "mysql": ("database", "PROJECT", "SINGLE"),
    "sqlite": ("database", "PROJECT", "SINGLE"),
    "valorant": ("favorite_game", "PREFERENCE", "SINGLE"),
    "minecraft": ("favorite_game", "PREFERENCE", "SINGLE"),
}

# Subject phrase -> slot key. Lets "my favorite food is biryani" work
# without the value being a known entity.
SUBJECTS = {
    "engine": "game.engine",
    "game engine": "game.engine",
    "language": "main_language",
    "main language": "main_language",
    "primary language": "main_language",
    "programming language": "main_language",
    "favorite language": "favorite_language",
    "favourite language": "favorite_language",
    "favorite food": "favorite_food",
    "favourite food": "favorite_food",
    "favorite game": "favorite_game",
    "favourite game": "favorite_game",
    "favorite color": "favorite_color",
    "favourite colour": "favorite_color",
    "framework": "web.framework",
    "database": "database",
    "city": "city",
    "job": "job",
    "role": "job",
    "name": "name",
}

SUBJECT_TYPES = {
    "favorite_food": "PREFERENCE",
    "favorite_game": "PREFERENCE",
    "favorite_color": "PREFERENCE",
    "favorite_language": "PREFERENCE",
    "main_language": "FACT",
    "city": "FACT",
    "job": "FACT",
    "name": "FACT",
    "game.engine": "PROJECT",
    "web.framework": "PROJECT",
    "database": "PROJECT",
}

THING_TO_KEY = {
    "game": "game.engine",
    "app": "web.framework",
    "website": "web.framework",
    "site": "web.framework",
    "backend": "web.framework",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# ============================================================
# Marker phrases -> assertion type
# ============================================================

MARKERS = [
    ("NON_LITERAL", [r"\bjust kidding\b", r"\bjk\b", r"\bkidding\b", r"🙄",
                     r"\bmy friend (?:said|uses)\b", r"\bsomeone said\b"]),
    ("RETRACT",     [r"\bforget (?:what i said|about|that)\b",
                     r"\bignore what i said\b", r"\bdelete that\b",
                     r"\bscratch that\b", r"\bnever mind what i said\b"]),
    ("CORRECTION",  [r"\bi was wrong\b", r"\bi misspoke\b",
                     r"\bthat'?s (?:not right|wrong|incorrect)\b",
                     r"\bcorrection\b", r"\bi meant\b",
                     r"\bno wait\b", r"\bactually\b"]),
    ("NEGATION",    [r"\bno longer\b", r"\bdon'?t use .* anymore\b",
                     r"\bnot using .* anymore\b", r"\bstopped using\b",
                     r"\bstopped playing\b", r"\bquit using\b"]),
    ("PAST",        [r"\bused to\b", r"\bback then\b",
                     r"\bi was using\b", r"\bpreviously i\b"]),
    ("HYPOTHETICAL",[r"\bmight\b", r"\bmaybe\b", r"\bthinking about\b",
                     r"\bconsidering\b", r"\bsomeday\b", r"\bperhaps\b",
                     r"\bi may \b", r"\bplanning to try\b"]),
    ("CHANGE",      [r"\bswitch(?:ed|ing)?\b", r"\bmoved to\b",
                     r"\bmigrat(?:ed|ing)\b", r"\bchanged to\b",
                     r"\bwent back to\b", r"\bnow (?:using|on)\b",
                     r"\bstarted using\b"]),
]

QUESTION_STARTS = (
    "what", "which", "who", "where", "when", "how", "do you", "did i",
    "am i", "was i", "tell me", "remind me",
)

META_PATTERNS = [
    r"what do you know about me", r"what do you remember",
    r"everything you know", r"what have you stored", r"my memories",
]

WHY_PATTERNS = [
    r"why did you say", r"where did you get", r"how do you know",
    r"what makes you (?:say|think)",
]


# ============================================================
# Output types
# ============================================================

@dataclass
class QueryIntent:
    needs_memory: bool = False
    time_scope: str = "CURRENT"          # CURRENT | AT | PREVIOUS | TIMELINE
    at_time: Optional[datetime] = None
    key_hints: List[str] = field(default_factory=list)
    is_meta: bool = False
    is_why: bool = False
    raw: str = ""


@dataclass
class Analysis:
    candidates: List[Candidate] = field(default_factory=list)
    query: QueryIntent = field(default_factory=QueryIntent)
    backend: str = "rules"


# ============================================================
# Helpers
# ============================================================

def _detect_assertion(text: str) -> Optional[str]:
    low = text.lower()
    for assertion, patterns in MARKERS:
        for pat in patterns:
            if re.search(pat, low):
                return assertion
    return None


def _find_entity(text: str) -> Optional[str]:
    """Longest known entity mentioned in the text, normalised."""
    found = _find_entity_span(text)
    return found[0] if found else None


def _find_entity_span(text: str):
    """Return (normalised_name, surface_form_as_written) or None.

    Keeping the surface form means the memory stores "Unity" the way the user
    typed it, not the lowercase registry key.
    """
    hits = []
    for name in ENTITIES:
        pat = r"(?<![\w])" + re.escape(name) + r"(?![\w])"
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            hits.append((name, m.group(0)))
    if not hits:
        return None
    return max(hits, key=lambda h: len(h[0]))


def _find_subject(text: str) -> Optional[str]:
    low = text.lower()
    hits = [(phrase, key) for phrase, key in SUBJECTS.items()
            if re.search(r"(?<![\w])" + re.escape(phrase) + r"(?![\w])", low)]
    if not hits:
        return None
    return max(hits, key=lambda h: len(h[0]))[1]


def _key_for(value_norm: str, subject_key: Optional[str]) -> Optional[tuple]:
    """Return (key, memory_type, cardinality) or None if unstorable."""
    if subject_key:
        mtype = SUBJECT_TYPES.get(subject_key, "FACT")
        return subject_key, mtype, "SINGLE"
    if value_norm in ENTITIES:
        return ENTITIES[value_norm]
    return None


def _parse_at_time(text: str, now: datetime) -> Optional[datetime]:
    low = text.lower()
    for name, num in MONTHS.items():
        if re.search(r"(?<![\w])" + name + r"(?![\w])", low):
            year = now.year if num <= now.month else now.year - 1
            ym = re.search(name + r"\s+(\d{4})", low)
            if ym:
                year = int(ym.group(1))
            return datetime(year, num, 15, tzinfo=timezone.utc)
    return None


# ============================================================
# Extraction
# ============================================================

VALUE_PATTERNS = [
    # "I switched my game to Godot" / "I switched from Unity to Godot"
    (r"\bswitch(?:ed|ing)?(?:\s+my\s+(?P<subj>[\w\s]{2,25}?))?\s+"
     r"(?:from\s+(?P<old>[\w\+\#\.]+)\s+)?to\s+(?P<val>[\w\+\#\.\s]{2,30}?)"
     r"(?:\s*[\.,!\?]|$)", "CHANGE"),
    # "I moved to Godot" / "migrated to Godot" / "went back to Unity"
    (r"\b(?:moved|migrated|changed|went back)\s+to\s+"
     r"(?P<val>[\w\+\#\.\s]{2,30}?)(?:\s*[\.,!\?]|$)", "CHANGE"),
    # "My main language is Python"
    (r"\bmy\s+(?P<subj>[\w\s]{2,25}?)\s+(?:is|are)\s+"
     r"(?P<val>[\w\+\#\.\s]{2,30}?)(?:\s*[\.,!\?]|$)", "STATEMENT"),
    # "I'm building a game in Unity"
    (r"\b(?:building|making|writing|developing)\s+(?:a|an|my)?\s*"
     r"(?P<thing>\w+)?\s*(?:in|with|using|on)\s+"
     r"(?P<val>[\w\+\#\.\s]{2,30}?)(?:\s*[\.,!\?]|$)", "STATEMENT"),
    # "I use Godot" / "I'm using Godot" / "I'm learning Java"
    (r"\bi(?:'m|\s+am)?\s*(?:now\s+)?(?:use|using|learning|on)\s+"
     r"(?P<val>[\w\+\#\.\s]{2,30}?)(?:\s*[\.,!\?]|$)", "STATEMENT"),
    # "I used to use Unity"
    (r"\bused to\s+(?:use|play|work with|be on)\s+"
     r"(?P<val>[\w\+\#\.\s]{2,30}?)(?:\s*[\.,!\?]|$)", "PAST"),
    # "I don't use Unity anymore"
    (r"\b(?:don'?t|do not|no longer|stopped)\s+(?:use|using|play|playing)\s+"
     r"(?P<val>[\w\+\#\.\s]{2,30}?)(?:\s+anymore)?(?:\s*[\.,!\?]|$)", "NEGATION"),
    # "Forget what I said about Python"
    (r"\bforget\s+(?:what i said\s+)?(?:about\s+)?"
     r"(?P<val>[\w\+\#\.\s]{2,30}?)(?:\s*[\.,!\?]|$)", "RETRACT"),
    # "I like peanuts" / "I love biryani" / "I really enjoy jazz" /
    # "I don't like cilantro" / "I dislike/hate mornings"
    (r"\bi\s+(?:really\s+|absolutely\s+|kind of\s+|sort of\s+)?"
     r"(?P<verb>don'?t like|do not like|dislike|hate|like|love|enjoy)\s+"
     r"(?P<val>[\w\+\#\.\s]{2,30}?)(?:\s*[\.,!\?]|$)", "STATEMENT"),
]

# Verbs above that mean the value is UNWANTED, not wanted.
NEGATIVE_LIKE_VERBS = {"dislike", "hate", "don't like", "dont like", "do not like"}

STOP_VALUES = {
    "it", "that", "this", "them", "him", "her", "me", "you", "there",
    "anything", "everything", "something", "nothing", "a", "an", "the",
}


def _extract_candidates(text: str, now: datetime) -> List[Candidate]:
    marker = _detect_assertion(text)
    if marker == "NON_LITERAL":
        return []

    out: List[Candidate] = []
    seen: set = set()

    for pattern, default_assertion in VALUE_PATTERNS:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            raw_val = (m.groupdict().get("val") or "").strip()
            if not raw_val:
                continue
            value_norm = normalize_value(raw_val)
            if not value_norm or value_norm in STOP_VALUES:
                continue

            subj_raw = (m.groupdict().get("subj") or "").strip()
            thing = (m.groupdict().get("thing") or "").strip().lower()
            verb_raw = (m.groupdict().get("verb") or "").strip().lower()
            subject_key = None
            if subj_raw:
                subject_key = SUBJECTS.get(subj_raw.lower())
            if subject_key is None and thing:
                subject_key = THING_TO_KEY.get(thing)
            if subject_key is None:
                subject_key = _find_subject(text)

            assertion_now = marker or default_assertion
            resolved = _key_for(value_norm, subject_key)
            if resolved is None:
                if verb_raw:
                    # "I like X" with no more specific attribute in play --
                    # a general taste, kept in its own MULTI slot so
                    # unrelated likes (peanuts, jazz, Godot) never collide.
                    key, mtype, card = "likes", "PREFERENCE", "MULTI"
                elif assertion_now in ("RETRACT", "NEGATION"):
                    # "Forget about biryani" names a value, not an attribute.
                    # WILDCARD_KEY tells the lifecycle to find whichever slot
                    # currently holds that value.
                    key, mtype, card = WILDCARD_KEY, "FACT", "SINGLE"
                else:
                    continue
            else:
                key, mtype, card = resolved

            # Marker phrases outrank the pattern's own default.
            assertion = marker or default_assertion
            if marker in (None, "CHANGE") and default_assertion in (
                "PAST", "NEGATION", "RETRACT"
            ):
                assertion = default_assertion

            dedupe = (key, value_norm)
            if dedupe in seen:
                continue
            seen.add(dedupe)

            polarity = -1 if verb_raw in NEGATIVE_LIKE_VERBS else 1

            out.append(Candidate(
                key=key,
                value=display_value(raw_val),
                value_norm=value_norm,
                memory_type=mtype,
                cardinality=card,
                assertion=assertion,
                polarity=polarity,
                valid_from=now,
                target_value_norm=value_norm if assertion in ("RETRACT", "NEGATION") else None,
                raw_text=text,
            ))

            # "switched from Unity to Godot" also records where it came from
            old = (m.groupdict().get("old") or "").strip()
            if old:
                old_norm = normalize_value(old)
                if old_norm and (old_norm, key) not in seen:
                    seen.add((key, old_norm))

    # Fallback: a known entity with no explicit frame is only IMPLIED.
    if not out:
        found = _find_entity_span(text)
        if found:
            entity, surface = found
            key, mtype, card = ENTITIES[entity]
            out.append(Candidate(
                key=key,
                value=display_value(surface),
                value_norm=entity,
                memory_type=mtype,
                cardinality=card,
                assertion=marker or "IMPLIED",
                valid_from=now,
                raw_text=text,
            ))

    return out


def _analyze_query(text: str, now: datetime) -> QueryIntent:
    low = text.lower().strip()
    is_question = low.endswith("?") or low.startswith(QUESTION_STARTS)
    intent = QueryIntent(raw=text)

    if any(re.search(p, low) for p in WHY_PATTERNS):
        intent.needs_memory = True
        intent.is_why = True
        return intent

    if any(re.search(p, low) for p in META_PATTERNS):
        intent.needs_memory = True
        intent.is_meta = True
        return intent

    if not is_question:
        return intent

    intent.needs_memory = True

    at = _parse_at_time(text, now)
    if at is not None:
        intent.time_scope = "AT"
        intent.at_time = at
    elif re.search(r"\b(before|previously|prior|used to|earlier)\b", low):
        intent.time_scope = "PREVIOUS"
    elif re.search(r"\b(timeline|history|changed over|all the|every)\b", low):
        intent.time_scope = "TIMELINE"

    subject = _find_subject(text)
    if subject:
        intent.key_hints.append(subject)
    entity = _find_entity(text)
    if entity and ENTITIES[entity][0] not in intent.key_hints:
        intent.key_hints.append(ENTITIES[entity][0])

    return intent


# ============================================================
# Public interface
# ============================================================

def analyze(text: str, now: datetime, backend: str = "rules") -> Analysis:
    if backend == "llm":
        from .analyzer_llm import analyze_with_llm  # optional, needs a key

        try:
            return analyze_with_llm(text, now)
        except Exception:
            pass  # fall through to rules; a demo must never hard-fail here

    query = _analyze_query(text, now)
    candidates = [] if query.needs_memory else _extract_candidates(text, now)
    return Analysis(candidates=candidates, query=query, backend=backend)
