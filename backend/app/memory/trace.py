"""Retrieval trace: proof of which memory produced an answer.

Two guarantees:
  1. Every answer stores the ids it used, the ids it considered and rejected,
     the per-stage pipeline counts, and the similarity/score behind each.
  2. The validator drops any memory id that was not in the context block.
     A model cannot cite a memory it was never shown.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AnswerTrace, Memory, MemoryEvent, MemorySource
from .retrieval import RetrievalResult


def _f(x) -> float:
    """Last line of defence: no numpy scalar reaches a JSON response."""
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return 0.0


def validate_used_ids(claimed: List[int], result: RetrievalResult) -> List[int]:
    """Reject anything the answerer cited that wasn't in the context block."""
    allowed = {h.memory.id for h in result.hits}
    return [i for i in claimed if i in allowed]


def build_trace(
    db: Session,
    user_id: int,
    result: RetrievalResult,
    used_ids: List[int],
    reason: str,
) -> Dict:
    used_set = set(used_ids)
    used_detail = []
    for hit in result.hits:
        if hit.memory.id not in used_set:
            continue
        m = hit.memory
        source = db.scalar(
            select(MemorySource)
            .where(MemorySource.memory_id == m.id)
            .order_by(MemorySource.id)
        )
        supersedes = db.get(Memory, m.supersedes_id) if m.supersedes_id else None
        used_detail.append({
            "id": m.id,
            "label": f"mem_{m.id:03d}",
            "key": m.key,
            "value": m.value,
            "status": m.status,
            "status_reason": m.status_reason,
            "memory_type": m.memory_type,
            "confidence": _f(m.confidence),
            "importance": _f(m.importance),
            "evidence_count": m.evidence_count,
            "evidence_type": m.evidence_type,
            "valid_from": m.valid_from.isoformat() if m.valid_from else None,
            "valid_until": m.valid_until.isoformat() if m.valid_until else None,
            "similarity": _f(hit.similarity),
            "memory_score": _f(hit.score),
            "rank": _f(hit.rank),
            "slot_matched": hit.slot_matched,
            "source": {
                "message_id": source.message_id if source else None,
                "excerpt": source.excerpt if source else None,
                "relation": source.relation if source else None,
            },
            "supersedes": ({
                "id": supersedes.id,
                "label": f"mem_{supersedes.id:03d}",
                "value": supersedes.value,
                "status": supersedes.status,
            } if supersedes else None),
        })

    considered = [{
        "id": h.memory.id,
        "label": f"mem_{h.memory.id:03d}",
        "key": h.memory.key,
        "value": h.memory.value,
        "status": h.memory.status,
        "similarity": _f(h.similarity),
        "rank": _f(h.rank),
        "excluded_because": _why_excluded(h.memory, result.time_scope),
    } for h in result.hits if h.memory.id not in used_set]

    return {
        "time_scope": result.time_scope,
        "pipeline": result.pipeline,
        "used": used_detail,
        "considered_not_used": considered,
        "reason": reason,
    }


def _why_excluded(m: Memory, scope: str) -> str:
    if m.status == "SUPERSEDED":
        return "superseded by a newer value"
    if m.status == "ENDED":
        return "no longer in effect"
    if m.status == "DISPUTED":
        return "unconfirmed"
    if m.status == "ARCHIVED":
        return "decayed out of active memory"
    return "lower relevance than the selected memory"


def store_trace(
    db: Session,
    user_id: int,
    assistant_message_id: int,
    result: RetrievalResult,
    used_ids: List[int],
    reason: str,
) -> None:
    db.add(AnswerTrace(
        user_id=user_id,
        assistant_message_id=assistant_message_id,
        time_scope=result.time_scope,
        used_memory_ids=list(used_ids),
        candidate_ids=[h.memory.id for h in result.hits],
        scores={f"mem_{h.memory.id:03d}": {"similarity": _f(h.similarity),
                                           "score": _f(h.score),
                                           "rank": _f(h.rank)}
                for h in result.hits},
        pipeline=result.pipeline,
        reason=reason,
    ))


def memory_detail(db: Session, user_id: int, memory_id: int) -> Optional[Dict]:
    m = db.get(Memory, memory_id)
    if m is None or m.user_id != user_id:
        return None  # 404, not 403 -- never confirm another user's ids exist

    sources = db.scalars(
        select(MemorySource).where(MemorySource.memory_id == m.id)
        .order_by(MemorySource.id)
    ).all()
    events = db.scalars(
        select(MemoryEvent).where(MemoryEvent.memory_id == m.id)
        .order_by(MemoryEvent.id)
    ).all()
    chain = db.scalars(
        select(Memory).where(Memory.slot_id == m.slot_id)
        .order_by(Memory.valid_from)
    ).all()

    return {
        "id": m.id,
        "label": f"mem_{m.id:03d}",
        "key": m.key,
        "value": m.value,
        "memory_type": m.memory_type,
        "status": m.status,
        "status_reason": m.status_reason,
        "assertion": m.assertion,
        "confidence": _f(m.confidence),
        "importance": _f(m.importance),
        "evidence_count": m.evidence_count,
        "evidence_type": m.evidence_type,
        "valid_from": m.valid_from.isoformat() if m.valid_from else None,
        "valid_until": m.valid_until.isoformat() if m.valid_until else None,
        "recorded_at": m.recorded_at.isoformat() if m.recorded_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "access_count": m.access_count,
        "supersedes_id": m.supersedes_id,
        "superseded_by_id": m.superseded_by_id,
        "sources": [{"message_id": s.message_id, "relation": s.relation,
                     "excerpt": s.excerpt} for s in sources],
        "events": [{"event": e.event, "from_status": e.from_status,
                    "to_status": e.to_status, "reason_code": e.reason_code,
                    "at": e.created_at.isoformat() if e.created_at else None}
                   for e in events],
        "slot_history": [{"id": c.id, "label": f"mem_{c.id:03d}",
                          "value": c.value, "status": c.status,
                          "valid_from": c.valid_from.isoformat() if c.valid_from else None,
                          "valid_until": c.valid_until.isoformat() if c.valid_until else None}
                         for c in chain if c.status != "RETRACTED"],
    }


def build_graph(db: Session, user_id: int) -> Dict:
    """The knowledge graph, derived from columns that already exist.

    No graph database. Nodes are memories; edges come from supersedes_id,
    shared slot_id, shared source_message_id and dispute_group_id.
    """
    rows = db.scalars(
        select(Memory).where(Memory.user_id == user_id)
        .order_by(Memory.id)
    ).all()

    nodes = [{
        "id": m.id,
        "label": f"mem_{m.id:03d}",
        "key": m.key,
        "value": m.value,
        "status": m.status,
        "memory_type": m.memory_type,
        "confidence": _f(m.confidence),
        "valid_from": m.valid_from.isoformat() if m.valid_from else None,
        "valid_until": m.valid_until.isoformat() if m.valid_until else None,
    } for m in rows if m.status != "RETRACTED"]

    ids = {n["id"] for n in nodes}
    edges = []
    by_slot: Dict[int, List[Memory]] = {}
    by_message: Dict[int, List[Memory]] = {}
    by_dispute: Dict[int, List[Memory]] = {}

    for m in rows:
        if m.status == "RETRACTED":
            continue
        by_slot.setdefault(m.slot_id, []).append(m)
        if m.source_message_id:
            by_message.setdefault(m.source_message_id, []).append(m)
        if m.dispute_group_id:
            by_dispute.setdefault(m.dispute_group_id, []).append(m)
        if m.supersedes_id and m.supersedes_id in ids:
            edges.append({"source": m.supersedes_id, "target": m.id,
                          "type": "SUPERSEDES"})

    for slot_id, members in by_slot.items():
        for a, b in zip(members, members[1:]):
            if not any(e["type"] == "SUPERSEDES" and
                       {e["source"], e["target"]} == {a.id, b.id} for e in edges):
                edges.append({"source": a.id, "target": b.id, "type": "SAME_SLOT"})

    for _, members in by_message.items():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                edges.append({"source": a.id, "target": b.id, "type": "SAME_SOURCE"})

    for _, members in by_dispute.items():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                edges.append({"source": a.id, "target": b.id, "type": "DISPUTES"})

    return {"nodes": nodes, "edges": edges}
