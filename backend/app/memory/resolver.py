"""
LIVING MEMORY — deterministic conflict resolver.

This module decides what is currently true.

It is a PURE function of (candidate, live memories in the slot, now).
No database. No network. No LLM. No global clock.

That matters for two reasons:
  1. It is exhaustively unit-testable without an API key or a server.
  2. It is the answer to "how do you know which memory is currently true?"
     The LLM only labels the *assertion type* of a sentence. Every status
     transition below is decided here, in code you can read.

The caller (memory/lifecycle.py) executes the returned operations inside a
single transaction and writes memory_events rows for each one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

# ============================================================
# Vocabulary
# ============================================================

ASSERTIONS = (
    "STATEMENT",     # "My main language is Python."
    "CHANGE",        # "I switched to Java."
    "CORRECTION",    # "I was wrong, it's Rust."
    "IMPLIED",       # "Debugging my Godot scene again."
    "PAST",          # "I used to use Unity."
    "NEGATION",      # "I don't use Unity anymore."
    "RETRACT",       # "Forget what I said about Python."
    "HYPOTHETICAL",  # "I might learn Rust someday."
    "NON_LITERAL",   # jokes, sarcasm, quoting someone else
)

STATUSES = ("ACTIVE", "SUPERSEDED", "ENDED", "RETRACTED", "DISPUTED", "ARCHIVED")

# The LLM (or the rule analyzer) picks a CATEGORY.
# Code assigns the NUMBER. Model-generated confidence scores are not stable
# enough to be allowed to overwrite a user's facts.
BASE_CONFIDENCE = {
    "CORRECTION": 0.95,
    "RETRACT": 0.95,
    "CHANGE": 0.90,
    "STATEMENT": 0.85,
    "PAST": 0.85,
    "NEGATION": 0.85,
    "IMPLIED": 0.60,
    "HYPOTHETICAL": 0.40,
    "NON_LITERAL": 0.0,
}

DEFAULT_IMPORTANCE = {
    "FACT": 0.8,
    "PROJECT": 0.8,
    "DECISION": 0.7,
    "RELATIONSHIP": 0.7,
    "PREFERENCE": 0.6,
    "GOAL": 0.6,
    "TEMPORARY_CONTEXT": 0.3,
}

# A new value may only displace an ACTIVE one at or above this confidence.
# Below it, we do NOT guess — we raise a dispute.
OVERWRITE_THRESHOLD = 0.80

EVIDENCE_BONUS = 0.05      # per extra supporting message
EVIDENCE_BONUS_CAP = 4     # saturates after 5 total mentions
CONFIDENCE_CEILING = 0.99


def effective_confidence(assertion: str, evidence_count: int = 1) -> float:
    """Deterministic, one-line, explainable-on-a-slide confidence.

    Stated once      -> 0.85
    Stated 3 times   -> 0.95
    Merely implied   -> 0.60  (never enough to overwrite)
    """
    base = BASE_CONFIDENCE.get(assertion, 0.5)
    bonus = EVIDENCE_BONUS * min(max(evidence_count - 1, 0), EVIDENCE_BONUS_CAP)
    return round(min(CONFIDENCE_CEILING, base + bonus), 4)


def default_importance(memory_type: str) -> float:
    return DEFAULT_IMPORTANCE.get(memory_type, 0.5)


# ============================================================
# Inputs
# ============================================================

@dataclass
class Candidate:
    """One extractable fact from one user message."""
    key: str
    value: str
    value_norm: str
    memory_type: str = "FACT"
    cardinality: str = "SINGLE"
    assertion: str = "STATEMENT"
    polarity: int = 1
    valid_from: Optional[datetime] = None
    # For RETRACT / NEGATION: which existing value is being targeted.
    # None means "whatever is live in this slot".
    target_value_norm: Optional[str] = None
    ttl_hours: Optional[int] = None
    raw_text: str = ""


@dataclass
class ExistingMemory:
    """A row already in this slot. Only live rows need to be passed in."""
    id: int
    value: str
    value_norm: str
    status: str
    confidence: float
    valid_from: datetime
    evidence_count: int = 1
    polarity: int = 1
    dispute_group_id: Optional[int] = None


# ============================================================
# Outputs
# ============================================================

@dataclass
class Op:
    """One instruction for the lifecycle executor."""
    kind: str                      # CREATE | SET_STATUS | REINFORCE
    reason_code: str

    # --- CREATE ---
    value: Optional[str] = None
    value_norm: Optional[str] = None
    status: Optional[str] = None
    assertion: Optional[str] = None
    confidence: Optional[float] = None
    importance: Optional[float] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    supersedes_id: Optional[int] = None
    polarity: int = 1
    expires_at: Optional[datetime] = None
    # Route this memory to a different slot than the candidate's key
    # (used to keep hypotheticals out of fact slots).
    slot_key_override: Optional[str] = None
    memory_type_override: Optional[str] = None

    # --- SET_STATUS / REINFORCE ---
    memory_id: Optional[int] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    set_valid_until: Optional[datetime] = None
    # "NEW" = link to the row created by this same resolution. The executor
    # patches the FK after INSERT, inside the same transaction.
    set_superseded_by: Optional[str] = None
    join_dispute_group: bool = False
    event: Optional[str] = None


@dataclass
class Resolution:
    ops: List[Op] = field(default_factory=list)
    reason_code: str = "NOOP"
    clarify: Optional[str] = None     # question the assistant should ask
    disputed: bool = False
    notes: str = ""


# ============================================================
# The decision table
# ============================================================

def resolve(
    candidate: Candidate,
    existing: List[ExistingMemory],
    now: datetime,
) -> Resolution:
    """Map (new fact, current slot state) -> state transitions.

    `existing` should contain the slot's ACTIVE and DISPUTED rows.
    Rules are evaluated in order; the first match wins.
    """
    c = candidate
    valid_from = c.valid_from or now
    live = [m for m in existing if m.status in ("ACTIVE", "DISPUTED")]
    active = [m for m in live if m.status == "ACTIVE"]
    disputed = [m for m in live if m.status == "DISPUTED"]
    conf = effective_confidence(c.assertion)
    imp = default_importance(c.memory_type)

    def create(status="ACTIVE", **kw) -> Op:
        return Op(
            kind="CREATE",
            value=kw.pop("value", c.value),
            value_norm=kw.pop("value_norm", c.value_norm),
            status=status,
            assertion=c.assertion,
            confidence=kw.pop("confidence", conf),
            importance=imp,
            valid_from=kw.pop("valid_from", valid_from),
            polarity=c.polarity,
            **kw,
        )

    # --- Rule 1: non-literal. Jokes and quotes are not memory. -----------
    if c.assertion == "NON_LITERAL":
        return Resolution(reason_code="IGNORED_NON_LITERAL",
                          notes="Non-literal statement; nothing stored.")

    # --- Rule 13 (checked early): the user is settling an open dispute ---
    # A confident statement that matches one side of a dispute resolves it.
    if disputed and conf >= OVERWRITE_THRESHOLD and c.assertion in (
        "STATEMENT", "CHANGE", "CORRECTION"
    ):
        winner = next((m for m in disputed if m.value_norm == c.value_norm), None)
        ops: List[Op] = []
        if winner is not None:
            ops.append(Op(kind="SET_STATUS", memory_id=winner.id,
                          from_status="DISPUTED", to_status="ACTIVE",
                          event="DISPUTE_RESOLVED",
                          reason_code="DISPUTE_RESOLVED"))
            for loser in disputed:
                if loser.id == winner.id:
                    continue
                ops.append(Op(kind="SET_STATUS", memory_id=loser.id,
                              from_status="DISPUTED", to_status="SUPERSEDED",
                              set_valid_until=valid_from,
                              event="DISPUTE_RESOLVED",
                              reason_code="DISPUTE_RESOLVED"))
            return Resolution(ops=ops, reason_code="DISPUTE_RESOLVED",
                              notes=f"User confirmed '{winner.value}'.")
        # A third, different value while disputed: it wins, the rest supersede.
        for loser in disputed:
            ops.append(Op(kind="SET_STATUS", memory_id=loser.id,
                          from_status="DISPUTED", to_status="SUPERSEDED",
                          set_valid_until=valid_from,
                          set_superseded_by="NEW",
                          event="DISPUTE_RESOLVED",
                          reason_code="DISPUTE_RESOLVED"))
        ops.append(create(status="ACTIVE", reason_code="DISPUTE_RESOLVED",
                          supersedes_id=disputed[0].id))
        return Resolution(ops=ops, reason_code="DISPUTE_RESOLVED",
                          notes=f"New value '{c.value}' resolved the dispute.")

    # --- Rule 2: hypothetical. Never touches a fact slot. ----------------
    if c.assertion == "HYPOTHETICAL":
        return Resolution(
            ops=[create(status="ACTIVE",
                        reason_code="STORED_AS_GOAL",
                        slot_key_override=f"{c.key}.considering",
                        memory_type_override="GOAL")],
            reason_code="STORED_AS_GOAL",
            notes="Hypothetical stored as a GOAL; current value untouched.",
        )

    # --- Rule 3: explicit retraction. It was never true. -----------------
    if c.assertion == "RETRACT":
        targets = _targets(live, c.target_value_norm)
        if not targets:
            return Resolution(reason_code="RETRACT_NO_MATCH",
                              notes="Nothing matching to retract.")
        return Resolution(
            ops=[Op(kind="SET_STATUS", memory_id=m.id, from_status=m.status,
                    to_status="RETRACTED", event="RETRACTED",
                    reason_code="RETRACTED_BY_USER") for m in targets],
            reason_code="RETRACTED_BY_USER",
            notes="User asked to forget this; hidden from history.",
        )

    # --- Rule 4: negation. It was true, it stopped, nothing replaced it. -
    if c.assertion == "NEGATION":
        targets = _targets(live, c.target_value_norm or c.value_norm)
        if not targets:
            return Resolution(reason_code="NEGATION_NO_MATCH",
                              notes="Nothing matching to end.")
        return Resolution(
            ops=[Op(kind="SET_STATUS", memory_id=m.id, from_status=m.status,
                    to_status="ENDED", set_valid_until=valid_from,
                    event="ENDED", reason_code="ENDED_BY_USER")
                 for m in targets],
            reason_code="ENDED_BY_USER",
            notes="Value ended; slot now has no current value.",
        )

    # --- Rule 5: past tense. Backfill history, don't disturb the present -
    if c.assertion == "PAST":
        match = next((m for m in active if m.value_norm == c.value_norm), None)
        if match is not None:
            # "I used to use Unity" while Unity is still ACTIVE -> it ended.
            return Resolution(
                ops=[Op(kind="SET_STATUS", memory_id=match.id,
                        from_status="ACTIVE", to_status="ENDED",
                        set_valid_until=valid_from, event="ENDED",
                        reason_code="ENDED_BY_PAST_TENSE")],
                reason_code="ENDED_BY_PAST_TENSE",
            )
        until = min([m.valid_from for m in active], default=now)
        return Resolution(
            ops=[create(status="SUPERSEDED",
                        reason_code="HISTORY_BACKFILL",
                        valid_from=c.valid_from or until,
                        valid_until=until)],
            reason_code="HISTORY_BACKFILL",
            notes="Recorded as history; current value untouched.",
        )

    # --- Rule 6: empty slot ----------------------------------------------
    if not live:
        return Resolution(ops=[create(status="ACTIVE", reason_code="CREATED")],
                          reason_code="CREATED")

    # --- Rule 7: same value repeated -> reinforce, do not duplicate ------
    same = next((m for m in live
                 if m.value_norm == c.value_norm and m.polarity == c.polarity), None)
    if same is not None and same.status == "ACTIVE":
        new_count = same.evidence_count + 1
        return Resolution(
            ops=[Op(kind="REINFORCE", memory_id=same.id,
                    confidence=effective_confidence(c.assertion, new_count),
                    event="REINFORCED", reason_code="REINFORCED")],
            reason_code="REINFORCED",
            notes=f"Evidence count -> {new_count}.",
        )

    # --- MULTI-cardinality slots -----------------------------------------
    if c.cardinality == "MULTI":
        flipped = next((m for m in active
                        if m.value_norm == c.value_norm and m.polarity != c.polarity), None)
        if flipped is not None:
            # Rule 12: "I like X" -> "I don't like X"
            return Resolution(
                ops=[
                    Op(kind="SET_STATUS", memory_id=flipped.id,
                       from_status="ACTIVE", to_status="SUPERSEDED",
                       set_valid_until=valid_from, set_superseded_by="NEW",
                       event="SUPERSEDED", reason_code="SUPERSEDED_BY_POLARITY"),
                    create(status="ACTIVE", reason_code="SUPERSEDED_BY_POLARITY",
                           supersedes_id=flipped.id),
                ],
                reason_code="SUPERSEDED_BY_POLARITY",
            )
        # Rule 11: another value coexists
        return Resolution(ops=[create(status="ACTIVE", reason_code="CREATED")],
                          reason_code="CREATED",
                          notes="Multi-value slot; added alongside existing values.")

    # --- SINGLE slot, value differs --------------------------------------
    incumbent = active[0] if active else live[0]

    # Rule 8: correction. The old value was NEVER true.
    # The new value inherits the old one's start date, so historical
    # queries return the corrected value, not the mistake.
    if c.assertion == "CORRECTION":
        ops = [Op(kind="SET_STATUS", memory_id=m.id, from_status=m.status,
                  to_status="RETRACTED", event="RETRACTED",
                  reason_code="RETRACTED_BY_CORRECTION") for m in live]
        ops.append(create(status="ACTIVE",
                          reason_code="RETRACTED_BY_CORRECTION",
                          valid_from=incumbent.valid_from,
                          supersedes_id=incumbent.id))
        return Resolution(ops=ops, reason_code="RETRACTED_BY_CORRECTION",
                          notes="Previous value was never true; removed from history.")

    # Rule 9: confident change. Old value becomes history.
    if conf >= OVERWRITE_THRESHOLD:
        return Resolution(
            ops=[
                Op(kind="SET_STATUS", memory_id=incumbent.id,
                   from_status=incumbent.status, to_status="SUPERSEDED",
                   set_valid_until=valid_from, set_superseded_by="NEW",
                   event="SUPERSEDED", reason_code="SUPERSEDED_BY_CHANGE"),
                create(status="ACTIVE", reason_code="SUPERSEDED_BY_CHANGE",
                       supersedes_id=incumbent.id),
            ],
            reason_code="SUPERSEDED_BY_CHANGE",
            notes=f"'{incumbent.value}' -> '{c.value}'. History preserved.",
        )

    # Rule 10: not confident enough. Represent uncertainty instead of guessing.
    # Both rows go DISPUTED, so the slot has NO active value until the user
    # clarifies. This is the opposite of "newest statement wins".
    ops = [Op(kind="SET_STATUS", memory_id=incumbent.id,
              from_status=incumbent.status, to_status="DISPUTED",
              join_dispute_group=True, event="DISPUTED",
              reason_code="CONFLICT_DISPUTED")]
    ops.append(create(status="DISPUTED", reason_code="CONFLICT_DISPUTED",
                      join_dispute_group=True))
    return Resolution(
        ops=ops,
        reason_code="CONFLICT_DISPUTED",
        disputed=True,
        clarify=(f"You've mentioned both \u201c{incumbent.value}\u201d and "
                 f"\u201c{c.value}\u201d for {c.key}. Which one is current?"),
        notes="Conflict below confidence threshold; no value assumed.",
    )


def _targets(live: List[ExistingMemory], value_norm: Optional[str]) -> List[ExistingMemory]:
    if value_norm is None:
        return list(live)
    return [m for m in live if m.value_norm == value_norm]
