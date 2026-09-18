"""Lifecycle executor: turns resolver operations into database rows.

Everything for one message happens inside ONE transaction, with the slot row
locked. That, plus the partial unique index in schema.sql, is why two ACTIVE
values for the same attribute cannot exist even under concurrent writes.

Nothing is ever deleted. Supersession changes status and links only, so the
full history stays queryable:
    Unity (SUPERSEDED, valid Jan-Mar)  ->  Godot (ACTIVE, valid Mar-now)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from ..embeddings import embed_memory
from ..models import Memory, MemoryEvent, MemorySlot, MemorySource
from .analyzer import Analysis
from .normalize import normalize_value
from .resolver import Candidate, ExistingMemory, Op, Resolution, resolve
from .slots import get_or_create_slot

LIVE_STATUSES = ("ACTIVE", "DISPUTED")


@dataclass
class Change:
    """What the UI shows as a toast, and what the demo narrates."""
    memory_id: int
    key: str
    value: str
    status: str
    prev_status: Optional[str]
    reason_code: str
    event: str
    polarity: int = 1

    def as_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "key": self.key,
            "value": self.value,
            "status": self.status,
            "prev_status": self.prev_status,
            "reason_code": self.reason_code,
            "event": self.event,
        }


@dataclass
class WriteResult:
    changes: List[Change]
    clarify: Optional[str] = None
    disputed: bool = False
    notes: List[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


def _live_memories(db: Session, slot_id: int) -> List[Memory]:
    return list(db.scalars(
        select(Memory)
        .where(Memory.slot_id == slot_id, Memory.status.in_(LIVE_STATUSES))
        .order_by(Memory.valid_from)
    ).all())


def _to_existing(rows: List[Memory]) -> List[ExistingMemory]:
    return [
        ExistingMemory(
            id=r.id,
            value=r.value,
            value_norm=r.value_norm,
            status=r.status,
            confidence=r.confidence,
            valid_from=r.valid_from,
            evidence_count=r.evidence_count,
            polarity=r.polarity,
            dispute_group_id=r.dispute_group_id,
        )
        for r in rows
    ]


def _log(
    db: Session,
    user_id: int,
    memory_id: int,
    event: str,
    reason_code: str,
    from_status: Optional[str],
    to_status: Optional[str],
    message_id: Optional[int],
    detail: Optional[dict] = None,
) -> None:
    db.add(MemoryEvent(
        user_id=user_id,
        memory_id=memory_id,
        event=event,
        from_status=from_status,
        to_status=to_status,
        reason_code=reason_code,
        detail=detail or {},
        message_id=message_id,
    ))


def apply_candidate(
    db: Session,
    user_id: int,
    candidate: Candidate,
    message_id: Optional[int],
    now: datetime,
) -> WriteResult:
    """Resolve one candidate against its slot and persist the outcome."""
    if candidate.key == "*":
        # A retraction/negation that named a value but no attribute.
        # Find whichever slot currently holds that value for this user.
        owner = db.scalar(
            select(Memory).where(
                Memory.user_id == user_id,
                Memory.value_norm == candidate.value_norm,
                Memory.status.in_(LIVE_STATUSES),
            ).order_by(Memory.id.desc())
        )
        if owner is None:
            return WriteResult(changes=[])
        slot = db.get(MemorySlot, owner.slot_id)
    else:
        slot = get_or_create_slot(
            db, user_id, candidate.key, candidate.memory_type,
            candidate.cardinality,
        )

    # Serialise writes to this slot. The unique index is the final guard;
    # this lock keeps us from having to rely on it.
    db.execute(
        sql_text("SELECT id FROM memory_slots WHERE id = :sid FOR UPDATE"),
        {"sid": slot.id},
    )

    existing_rows = _live_memories(db, slot.id)
    by_id = {r.id: r for r in existing_rows}

    resolution: Resolution = resolve(candidate, _to_existing(existing_rows), now)
    changes: List[Change] = []
    created: Optional[Memory] = None
    dispute_group = next(
        (r.dispute_group_id for r in existing_rows if r.dispute_group_id), None
    )

    # --- status changes first, so the unique index is free when we insert ---
    pending_links: List[Op] = []
    for op in resolution.ops:
        if op.kind == "SET_STATUS":
            row = by_id.get(op.memory_id)
            if row is None:
                continue
            prev = row.status
            row.status = op.to_status
            row.status_reason = op.reason_code
            row.updated_at = now
            if op.set_valid_until is not None:
                row.valid_until = op.set_valid_until
            if op.to_status == "ACTIVE":
                row.valid_until = None
            if op.join_dispute_group:
                dispute_group = dispute_group or row.id
                row.dispute_group_id = dispute_group
            if op.to_status != "DISPUTED":
                row.dispute_group_id = None
            if op.set_superseded_by == "NEW":
                pending_links.append(op)
            _log(db, user_id, row.id, op.event or op.to_status, op.reason_code,
                 prev, op.to_status, message_id,
                 {"value": row.value, "key": row.key})
            if message_id is not None:
                relation = {
                    "SUPERSEDED": "CORRECTED", "RETRACTED": "CORRECTED",
                    "ENDED": "ENDED", "DISPUTED": "DISPUTED",
                }.get(op.to_status, "REINFORCED")
                db.add(MemorySource(memory_id=row.id, message_id=message_id,
                                    relation=relation,
                                    excerpt=candidate.raw_text[:280]))
            changes.append(Change(row.id, row.key, row.value, row.status, prev,
                                  op.reason_code, op.event or op.to_status,
                                  polarity=row.polarity))

        elif op.kind == "REINFORCE":
            row = by_id.get(op.memory_id)
            if row is None:
                continue
            row.evidence_count += 1
            row.confidence = op.confidence or row.confidence
            row.evidence_type = "REPEATED"
            row.last_confirmed_at = now
            row.updated_at = now
            _log(db, user_id, row.id, "REINFORCED", op.reason_code,
                 row.status, row.status, message_id,
                 {"evidence_count": row.evidence_count})
            if message_id is not None:
                db.add(MemorySource(memory_id=row.id, message_id=message_id,
                                    relation="REINFORCED",
                                    excerpt=candidate.raw_text[:280]))
            changes.append(Change(row.id, row.key, row.value, row.status,
                                  row.status, op.reason_code, "REINFORCED",
                                  polarity=row.polarity))

    db.flush()

    # --- then inserts ---
    for op in resolution.ops:
        if op.kind != "CREATE":
            continue
        target_slot = slot
        if op.slot_key_override:
            target_slot = get_or_create_slot(
                db, user_id, op.slot_key_override,
                op.memory_type_override or candidate.memory_type,
                candidate.cardinality,
            )
        expires = None
        if candidate.ttl_hours:
            expires = now + timedelta(hours=candidate.ttl_hours)

        row = Memory(
            user_id=user_id,
            slot_id=target_slot.id,
            key=target_slot.key,
            value=op.value,
            value_norm=op.value_norm or normalize_value(op.value or ""),
            polarity=op.polarity,
            memory_type=op.memory_type_override or candidate.memory_type,
            cardinality=target_slot.cardinality,
            status=op.status,
            status_reason=op.reason_code,
            assertion=op.assertion or candidate.assertion,
            confidence=op.confidence or 0.85,
            importance=op.importance or 0.5,
            evidence_count=1,
            evidence_type="IMPLIED" if candidate.assertion == "IMPLIED" else "STATED",
            valid_from=op.valid_from or now,
            valid_until=op.valid_until,
            recorded_at=now,
            updated_at=now,
            expires_at=expires,
            last_confirmed_at=now,
            supersedes_id=op.supersedes_id,
            source_message_id=message_id,
            embedding=embed_memory(target_slot.key, op.value or ""),
        )
        if op.join_dispute_group:
            row.dispute_group_id = dispute_group
        db.add(row)
        db.flush()
        created = row

        if op.join_dispute_group and dispute_group is None:
            dispute_group = row.id
            row.dispute_group_id = dispute_group

        _log(db, user_id, row.id, "DISPUTED" if row.status == "DISPUTED" else "CREATED",
             op.reason_code, None, row.status, message_id,
             {"value": row.value, "key": row.key})
        if message_id is not None:
            db.add(MemorySource(memory_id=row.id, message_id=message_id,
                                relation="CREATED",
                                excerpt=candidate.raw_text[:280]))
        changes.append(Change(row.id, row.key, row.value, row.status, None,
                              op.reason_code,
                              "DISPUTED" if row.status == "DISPUTED" else "CREATED",
                              polarity=row.polarity))

    # --- patch supersession links now that the new row has an id ---
    if created is not None:
        for op in pending_links:
            row = by_id.get(op.memory_id)
            if row is not None:
                row.superseded_by_id = created.id
        if dispute_group and created.status == "DISPUTED":
            created.dispute_group_id = dispute_group

    db.flush()
    return WriteResult(
        changes=changes,
        clarify=resolution.clarify,
        disputed=resolution.disputed,
        notes=[resolution.notes] if resolution.notes else [],
    )


def apply_analysis(
    db: Session,
    user_id: int,
    analysis: Analysis,
    message_id: Optional[int],
    now: datetime,
) -> WriteResult:
    """Apply every candidate from one message, in order.

    Order matters: "blue, no wait, green" creates blue and then retracts it.
    """
    all_changes: List[Change] = []
    clarify = None
    disputed = False
    notes: List[str] = []
    for candidate in analysis.candidates:
        result = apply_candidate(db, user_id, candidate, message_id, now)
        all_changes.extend(result.changes)
        clarify = clarify or result.clarify
        disputed = disputed or result.disputed
        notes.extend(result.notes)
    return WriteResult(all_changes, clarify, disputed, notes)


def sweep_expired(db: Session, user_id: int, now: datetime) -> List[Change]:
    """Lazy TTL sweep. Runs at the start of each request for this user.

    No background worker, no queue, no Redis -- the sweep is cheap and only
    ever touches one user's rows.
    """
    rows = db.scalars(
        select(Memory).where(
            Memory.user_id == user_id,
            Memory.status == "ACTIVE",
            Memory.expires_at.isnot(None),
            Memory.expires_at <= now,
        )
    ).all()
    changes = []
    for row in rows:
        prev = row.status
        row.status = "ENDED"
        row.status_reason = "ENDED_BY_TTL"
        row.valid_until = row.expires_at
        row.updated_at = now
        _log(db, user_id, row.id, "ENDED", "ENDED_BY_TTL", prev, "ENDED", None)
        changes.append(Change(row.id, row.key, row.value, "ENDED", prev,
                              "ENDED_BY_TTL", "ENDED"))
    if changes:
        db.flush()
    return changes
