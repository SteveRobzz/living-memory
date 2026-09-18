"""Context construction and answer composition.

The context block is the ONLY thing an answer may draw on. It carries every
memory's id, status and validity interval, so nothing about truth is left to
the model's judgement.

Two answerer backends, same interface:

  "rules" (DEFAULT, no API key)
      Composes the answer from the resolved context with templates. Slightly
      stiff prose, perfectly correct attribution, zero hallucination risk,
      and it proves the memory engine stands on its own.

  "llm"
      Passes the same block to a model with instructions to use only what is
      listed. The validator then rejects any memory id the model cites that
      was not in the block.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from typing import List, Optional, Tuple

from .retrieval import Hit, RetrievalResult

STATUS_NOTE = {
    "ACTIVE": "current",
    "SUPERSEDED": "replaced",
    "ENDED": "stopped",
    "DISPUTED": "unconfirmed",
    "ARCHIVED": "inactive",
}


def _fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "now"


def build_context(result: RetrievalResult) -> str:
    """The labelled block. This is what a judge should be shown on screen."""
    if not result.hits:
        return "(no stored memory matched this question)"
    lines = []
    for hit in result.hits:
        m = hit.memory
        line = (f"[mem_{m.id:03d}] {m.status:<10} {m.key} = {m.value}  "
                f"valid {_fmt(m.valid_from)} -> {_fmt(m.valid_until)}")
        if m.supersedes_id:
            line += f"  (supersedes mem_{m.supersedes_id:03d})"
        if m.superseded_by_id:
            line += f"  (superseded by mem_{m.superseded_by_id:03d})"
        lines.append(line)
    return "\n".join(lines)


def _human_key(key: str) -> str:
    return key.replace("game.engine", "game engine") \
              .replace("web.framework", "web framework") \
              .replace("main_language", "main language") \
              .replace("_", " ").replace(".", " ")


def compose_answer(
    result: RetrievalResult,
    query_text: str,
    clarify: Optional[str],
    changes_summary: Optional[str],
    now: datetime,
) -> Tuple[str, List[int], str]:
    """Return (answer, used_memory_ids, reason)."""

    # An open dispute outranks everything: say so, don't guess.
    if clarify:
        return clarify, [], "Conflicting values; asked the user to confirm."

    if result.disputed:
        m = result.disputed
        vals = " or ".join(f"\u201c{x.value}\u201d" for x in m)
        return (
            f"I'm not certain right now — you've mentioned {vals} for "
            f"{_human_key(m[0].key)} and I haven't been able to confirm which "
            f"is current. Which one is it?",
            [x.id for x in m],
            "Slot is in DISPUTED state.",
        )

    if not result.hits:
        # A plain statement ("My favorite game is Valorant.") isn't a
        # question, so there's nothing to retrieve -- the acknowledgement
        # IS the whole answer. Only say "I don't know" when the user
        # actually asked something and nothing matched.
        if changes_summary:
            return changes_summary, [], "Memory written; no question was asked."
        base = "I don't have anything stored about that yet."
        return base, [], "No matching memory."

    scope = result.time_scope
    active = [h for h in result.hits if h.memory.status == "ACTIVE"]
    history = [h for h in result.hits
               if h.memory.status in ("SUPERSEDED", "ENDED")]

    if scope == "TIMELINE":
        ordered = sorted(result.hits, key=lambda h: h.memory.valid_from)
        parts = [f"{h.memory.value} ({_fmt(h.memory.valid_from)} to "
                 f"{_fmt(h.memory.valid_until)})" for h in ordered]
        answer = (f"Here's how your {_human_key(ordered[0].memory.key)} has "
                  f"changed: " + " \u2192 ".join(parts) + ".")
        return answer, [h.memory.id for h in ordered], "Full slot timeline."

    if scope == "PREVIOUS":
        prior = sorted(history, key=lambda h: h.memory.valid_from, reverse=True)
        if prior:
            m = prior[0].memory
            answer = (f"Before that you were using {m.value}, from "
                      f"{_fmt(m.valid_from)} until {_fmt(m.valid_until)}.")
            return answer, [m.id], "Walked the supersession chain backwards."
        return ("I don't have an earlier value stored for that.", [],
                "No superseded memory in this slot.")

    if scope == "AT":
        if result.hits:
            m = result.hits[0].memory
            answer = (f"At that point you were using {m.value}.")
            return answer, [m.id], "Point-in-time query over valid_from/valid_until."
        return ("I don't have anything covering that date.", [],
                "No memory valid at that time.")

    # CURRENT (and meta)
    if active:
        grouped: "OrderedDict[str, list]" = OrderedDict()
        for h in active:
            grouped.setdefault(h.memory.key, []).append(h.memory)

        multi_valued = len(grouped) > 1 or any(len(v) > 1 for v in grouped.values())
        if multi_valued:
            parts = []
            for key, mems in grouped.items():
                if key == "likes":
                    liked = [m.value for m in mems if m.polarity == 1]
                    disliked = [m.value for m in mems if m.polarity != 1]
                    if liked:
                        parts.append(f"you like {', '.join(liked)}")
                    if disliked:
                        parts.append(f"you don't like {', '.join(disliked)}")
                else:
                    vals = ", ".join(m.value for m in mems)
                    parts.append(f"{_human_key(key)}: {vals}")
            answer = "Here's what I currently have — " + "; ".join(parts) + "."
            return answer, [m.id for mems in grouped.values() for m in mems], "All active memories."

        m = active[0].memory
        if m.key == "likes":
            liking_verb = "like" if m.polarity == 1 else "don't like"
            answer = f"You {liking_verb} {m.value}."
        elif m.key.startswith("favorite"):
            answer = f"Your {_human_key(m.key)} is {m.value}."
        elif m.memory_type == "PREFERENCE":
            answer = f"Your {_human_key(m.key)} is {m.value}."
        else:
            answer = f"You're currently using {m.value}."
        used = [m.id]
        prior = [h for h in history if h.memory.superseded_by_id == m.id]
        if prior:
            p = prior[0].memory
            answer += f" You switched from {p.value} on {_fmt(m.valid_from)}."
            used.append(p.id)
        if changes_summary:
            answer = f"{changes_summary} {answer}"
        return answer, used, "Active value for the matching slot."

    if history:
        m = history[0].memory
        return (f"You're not using anything for that at the moment — you "
                f"stopped with {m.value} on {_fmt(m.valid_until)}.",
                [m.id], "Slot has no active value.")

    return ("I don't have a current value stored for that.", [],
            "No active memory.")


def acknowledge(changes) -> Optional[str]:
    """Short confirmation shown when a message wrote memory but asked nothing.

    Grouped by the RESULTING status rather than the event name, so this
    covers an explicit change, a correction, and a dispute being resolved
    with the same logic -- all three end with one value ACTIVE and one or
    more others no longer current.
    """
    if not changes:
        return None

    active = [c for c in changes if c.status == "ACTIVE"]
    history = [c for c in changes if c.status in ("SUPERSEDED", "ENDED")]
    retracted = [c for c in changes if c.status == "RETRACTED"]
    disputed = [c for c in changes if c.status == "DISPUTED"]
    reinforced = [c for c in changes if c.event == "REINFORCED"]

    # A dispute was just raised, nothing resolved yet -- `clarify` already
    # carries the question the user needs to answer; say nothing here.
    if disputed and not active:
        return None

    if active and history:
        winner, loser = active[0], history[0]
        # Same value, opposite polarity -- a preference reversed, not a
        # value that changed. "Updated -- likes is peanuts, peanuts kept
        # as history" would be nonsense; say what actually happened.
        if winner.value.strip().lower() == loser.value.strip().lower():
            if winner.key == "likes":
                verb = "like" if winner.polarity == 1 else "don't like"
                return f"Noted — you {verb} {winner.value} now."
            return f"Updated — {_human_key(winner.key)} reversed for {winner.value}."
        verb = "Confirmed" if winner.reason_code == "DISPUTE_RESOLVED" else "Updated"
        return (f"{verb} — {_human_key(winner.key)} is {winner.value}. "
                f"{loser.value} is kept as history.")

    if active and retracted:
        winner = active[0]
        return (f"Corrected — {_human_key(winner.key)} is {winner.value}. "
                f"{retracted[0].value} was never accurate, so it's been removed.")

    if retracted:
        return f"Removed — I've dropped {retracted[0].value} from memory."

    if history and not active:
        return f"Noted — you've stopped with {history[0].value}."

    if active:
        c = active[0]
        if c.key == "likes":
            verb = "like" if c.polarity == 1 else "don't like"
            return f"Got it — you {verb} {c.value}."
        return f"Got it — {_human_key(c.key)}: {c.value}."
    if reinforced:
        return f"Noted again — {_human_key(reinforced[0].key)} is still {reinforced[0].value}."
    return None
