"""SQLAlchemy 2.0 models. Mirrors schema.sql exactly.

schema.sql is authoritative (it holds the partial unique indexes that
guarantee one ACTIVE value per slot). These classes are the read/write API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY, BigInteger, Boolean, DateTime, ForeignKey, Integer,
    JSON, Float, SmallInteger, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    color: Mapped[str] = mapped_column(String, default="#3b82f6")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemorySlot(Base):
    __tablename__ = "memory_slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String)
    memory_type: Mapped[str] = mapped_column(String)
    cardinality: Mapped[str] = mapped_column(String, default="SINGLE")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_embedding = mapped_column(Vector(384), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slot_id: Mapped[int] = mapped_column(ForeignKey("memory_slots.id", ondelete="CASCADE"))

    key: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(Text)
    value_norm: Mapped[str] = mapped_column(Text)
    polarity: Mapped[int] = mapped_column(SmallInteger, default=1)

    memory_type: Mapped[str] = mapped_column(String)
    cardinality: Mapped[str] = mapped_column(String, default="SINGLE")

    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    status_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    assertion: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    importance: Mapped[float] = mapped_column(Float)

    evidence_count: Mapped[int] = mapped_column(Integer, default=1)
    evidence_type: Mapped[str] = mapped_column(String, default="STATED")

    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    supersedes_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("memories.id"), nullable=True)
    superseded_by_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("memories.id"), nullable=True)
    dispute_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    source_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("messages.id"), nullable=True)
    embedding = mapped_column(Vector(384), nullable=True)


class MemorySource(Base):
    __tablename__ = "memory_sources"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"))
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    relation: Mapped[str] = mapped_column(String)
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryEvent(Base):
    __tablename__ = "memory_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    memory_id: Mapped[int] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String)
    from_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reason_code: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("messages.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnswerTrace(Base):
    __tablename__ = "answer_traces"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    assistant_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    time_scope: Mapped[str] = mapped_column(String)
    used_memory_ids: Mapped[list] = mapped_column(ARRAY(BigInteger), default=list)
    candidate_ids: Mapped[list] = mapped_column(ARRAY(BigInteger), default=list)
    scores: Mapped[dict] = mapped_column(JSONB, default=dict)
    pipeline: Mapped[dict] = mapped_column(JSONB, default=dict)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
