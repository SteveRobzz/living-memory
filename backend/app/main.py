"""Living Memory — FastAPI application.

All routes in one module. At this size, splitting into a routers/ package
would cost clarity and buy nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import clock
from .auth import current_user, issue_token
from .config import get_settings
from .db import get_db
from .models import (
    AnswerTrace, Conversation, Memory, MemoryEvent, MemorySlot,
    MemorySource, Message, User,
)
from .memory.analyzer import analyze
from .memory.context import acknowledge, build_context, compose_answer
from .memory.lifecycle import apply_analysis, sweep_expired
from .memory.retrieval import mark_accessed, retrieve
from .memory.trace import (
    build_graph, build_trace, memory_detail, store_trace, validate_used_ids,
)

settings = get_settings()
app = FastAPI(title="Living Memory", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Schemas
# ============================================================

class LoginIn(BaseModel):
    handle: str


class ConversationIn(BaseModel):
    title: Optional[str] = None


class MessageIn(BaseModel):
    content: str


class ClockIn(BaseModel):
    as_of: Optional[str] = None


# ============================================================
# Auth
# ============================================================

@app.get("/health")
def health():
    return {"ok": True, "now": clock.now().isoformat(),
            "simulated": clock.is_simulated(),
            "analyzer": settings.analyzer,
            "llm_enabled": settings.llm_enabled}


@app.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.id)).all()
    return [{"id": u.id, "handle": u.handle, "display_name": u.display_name,
             "color": u.color} for u in users]


@app.post("/auth/demo-login")
def demo_login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.handle == body.handle))
    if user is None:
        user = User(handle=body.handle, display_name=body.handle.title(),
                    color="#8b5cf6")
        db.add(user)
        db.commit()
    return {"token": issue_token(user.id),
            "user": {"id": user.id, "handle": user.handle,
                     "display_name": user.display_name, "color": user.color}}


# ============================================================
# Conversations
# ============================================================

@app.get("/conversations")
def list_conversations(user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Conversation).where(Conversation.user_id == user.id)
        .order_by(Conversation.id.desc())
    ).all()
    return [{"id": c.id, "title": c.title or f"Session {c.id}",
             "created_at": c.created_at.isoformat()} for c in rows]


@app.post("/conversations")
def create_conversation(body: ConversationIn,
                        user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    conv = Conversation(user_id=user.id, title=body.title, created_at=clock.now())
    db.add(conv)
    db.commit()
    return {"id": conv.id, "title": conv.title or f"Session {conv.id}"}


@app.get("/conversations/{conv_id}/messages")
def get_messages(conv_id: int, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Not found")
    rows = db.scalars(
        select(Message).where(Message.conversation_id == conv_id)
        .order_by(Message.id)
    ).all()
    return [{"id": m.id, "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat()} for m in rows]


# ============================================================
# The main loop
# ============================================================

@app.post("/conversations/{conv_id}/messages")
def post_message(conv_id: int, body: MessageIn,
                 user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Not found")

    now = clock.now()
    expired = sweep_expired(db, user.id, now)

    user_msg = Message(conversation_id=conv_id, user_id=user.id, role="user",
                       content=body.content, created_at=now)
    db.add(user_msg)
    db.flush()

    # 1. classify (never decides truth)
    analysis = analyze(body.content, now, backend=settings.analyzer)

    # 2. WRITE PATH — deterministic resolution, then persist
    write = apply_analysis(db, user.id, analysis, user_msg.id, now)
    changes = list(expired) + list(write.changes)

    # 3. READ PATH
    if analysis.query.needs_memory:
        result = retrieve(db, user.id, body.content, analysis.query, now)
    else:
        from .memory.retrieval import RetrievalResult
        result = RetrievalResult(hits=[], pipeline={"candidates": 0},
                                 time_scope="CURRENT")

    context_block = build_context(result)
    answer, claimed_ids, reason = compose_answer(
        result, body.content, write.clarify, acknowledge(write.changes), now
    )

    # 4. validate attribution
    used_ids = validate_used_ids(claimed_ids, result)
    used_memories = [h.memory for h in result.hits if h.memory.id in set(used_ids)]
    mark_accessed(db, used_memories, now)

    assistant_msg = Message(conversation_id=conv_id, user_id=user.id,
                            role="assistant", content=answer, created_at=now)
    db.add(assistant_msg)
    db.flush()

    trace = build_trace(db, user.id, result, used_ids, reason)
    trace["context_block"] = context_block
    store_trace(db, user.id, assistant_msg.id, result, used_ids, reason)
    db.commit()

    return {
        "assistant_message": {"id": assistant_msg.id, "role": "assistant",
                              "content": answer,
                              "created_at": assistant_msg.created_at.isoformat()},
        "user_message": {"id": user_msg.id, "content": body.content},
        "trace": trace,
        "memory_changes": [c.as_dict() for c in changes],
        "analyzer": analysis.backend,
        "now": now.isoformat(),
    }


# ============================================================
# Memory views (the Observatory's data)
# ============================================================

@app.get("/memories")
def list_memories(status: Optional[str] = None,
                  memory_type: Optional[str] = None,
                  user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    q = select(Memory).where(Memory.user_id == user.id)
    if status:
        q = q.where(Memory.status.in_(status.split(",")))
    if memory_type:
        q = q.where(Memory.memory_type == memory_type)
    rows = db.scalars(q.order_by(Memory.id.desc())).all()
    return [{
        "id": m.id, "label": f"mem_{m.id:03d}", "key": m.key, "value": m.value,
        "memory_type": m.memory_type, "status": m.status,
        "status_reason": m.status_reason,
        "confidence": round(float(m.confidence), 3),
        "importance": round(float(m.importance), 3),
        "evidence_count": m.evidence_count, "evidence_type": m.evidence_type,
        "valid_from": m.valid_from.isoformat() if m.valid_from else None,
        "valid_until": m.valid_until.isoformat() if m.valid_until else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "supersedes_id": m.supersedes_id, "superseded_by_id": m.superseded_by_id,
        "access_count": m.access_count,
    } for m in rows]


@app.get("/memories/graph")
def memories_graph(user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    return build_graph(db, user.id)


@app.get("/memories/timeline")
def memories_timeline(user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """One row per slot, each with its full ordered history."""
    slots = db.scalars(
        select(MemorySlot).where(MemorySlot.user_id == user.id)
        .order_by(MemorySlot.key)
    ).all()
    out = []
    for slot in slots:
        rows = db.scalars(
            select(Memory).where(Memory.slot_id == slot.id,
                                 Memory.status != "RETRACTED")
            .order_by(Memory.valid_from)
        ).all()
        if not rows:
            continue
        out.append({
            "slot_id": slot.id, "key": slot.key,
            "memory_type": slot.memory_type,
            "entries": [{
                "id": m.id, "label": f"mem_{m.id:03d}", "value": m.value,
                "status": m.status,
                "valid_from": m.valid_from.isoformat() if m.valid_from else None,
                "valid_until": m.valid_until.isoformat() if m.valid_until else None,
            } for m in rows],
        })
    return out


@app.get("/memories/{memory_id}")
def get_memory(memory_id: int, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    detail = memory_detail(db, user.id, memory_id)
    if detail is None:
        raise HTTPException(404, "Not found")
    return detail


@app.delete("/memories/{memory_id}")
def forget_memory(memory_id: int, hard: bool = False,
                  user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    m = db.get(Memory, memory_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "Not found")
    prev = m.status
    m.status = "RETRACTED"
    m.status_reason = "RETRACTED_BY_USER"
    m.updated_at = clock.now()
    if hard:
        m.value = "[deleted]"
        m.value_norm = "[deleted]"
        m.embedding = None
    db.add(MemoryEvent(user_id=user.id, memory_id=m.id, event="RETRACTED",
                       from_status=prev, to_status="RETRACTED",
                       reason_code="RETRACTED_BY_USER",
                       detail={"hard": hard}))
    db.commit()
    return {"id": m.id, "status": m.status, "hard": hard}


@app.get("/messages/{message_id}/trace")
def get_trace(message_id: int, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    row = db.scalar(
        select(AnswerTrace).where(
            AnswerTrace.assistant_message_id == message_id,
            AnswerTrace.user_id == user.id,
        )
    )
    if row is None:
        raise HTTPException(404, "Not found")
    return {
        "time_scope": row.time_scope,
        "used_memory_ids": row.used_memory_ids,
        "candidate_ids": row.candidate_ids,
        "scores": row.scores,
        "pipeline": row.pipeline,
        "reason": row.reason,
    }


@app.get("/events")
def list_events(limit: int = 50, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    rows = db.scalars(
        select(MemoryEvent).where(MemoryEvent.user_id == user.id)
        .order_by(MemoryEvent.id.desc()).limit(limit)
    ).all()
    return [{"id": e.id, "memory_id": e.memory_id, "event": e.event,
             "from_status": e.from_status, "to_status": e.to_status,
             "reason_code": e.reason_code, "detail": e.detail,
             "at": e.created_at.isoformat() if e.created_at else None}
            for e in rows]


# ============================================================
# Demo controls
# ============================================================

def _require_demo():
    if not settings.demo_mode:
        raise HTTPException(403, "Demo mode disabled")


@app.post("/demo/clock")
def set_clock(body: ClockIn):
    _require_demo()
    target = None
    if body.as_of:
        target = datetime.fromisoformat(body.as_of)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
    now = clock.set_simulated(target)
    return {"now": now.isoformat(), "simulated": clock.is_simulated()}


@app.post("/demo/reset")
def reset(db: Session = Depends(get_db)):
    _require_demo()
    for table in (AnswerTrace, MemoryEvent, MemorySource):
        db.execute(delete(table))
    db.execute(delete(Memory))
    db.execute(delete(MemorySlot))
    db.execute(delete(Message))
    db.execute(delete(Conversation))
    db.commit()
    clock.set_simulated(None)
    return {"ok": True}
