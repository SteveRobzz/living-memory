"""Slot resolution: proposed key -> the user's existing slot, or a new one.

A slot is one attribute of one user ("game.engine"). Two memories can only
contradict each other if they land in the same slot, so this is the step that
decides what counts as a contradiction at all.

Resolution order (first match wins):
  1. exact key match within this user's slots
  2. static alias table
  3. key-embedding cosine similarity >= SAME_SLOT_THRESHOLD
  4. otherwise: create a new slot
"""
from __future__ import annotations
import re
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MemorySlot
from ..embeddings import embed, cosine

SAME_SLOT_THRESHOLD = 0.88

KEY_ALIASES = {
    "primary_language": "main_language",
    "programming_language": "main_language",
    "coding_language": "main_language",
    "current_language": "main_language",
    "language": "main_language",
    "engine": "game.engine",
    "game_engine": "game.engine",
    "favourite_food": "favorite_food",
    "favourite_language": "favorite_language",
    "favourite_game": "favorite_game",
    "framework": "web.framework",
}

_FILLER = re.compile(r"^(my_|the_|current_|currently_)")


def normalize_key(key: str) -> str:
    k = key.strip().lower().replace(" ", "_").replace("-", "_")
    k = re.sub(r"[^\w\.]", "", k)
    k = _FILLER.sub("", k)
    return KEY_ALIASES.get(k, k)


def get_or_create_slot(
    db: Session,
    user_id: int,
    key: str,
    memory_type: str,
    cardinality: str = "SINGLE",
) -> MemorySlot:
    key = normalize_key(key)

    slot = db.scalar(
        select(MemorySlot).where(
            MemorySlot.user_id == user_id, MemorySlot.key == key
        )
    )
    if slot is not None:
        return slot

    # Embedding fallback: catch paraphrased keys of the same attribute.
    key_vec = embed(key.replace(".", " ").replace("_", " "))
    existing: Iterable[MemorySlot] = db.scalars(
        select(MemorySlot).where(
            MemorySlot.user_id == user_id,
            MemorySlot.memory_type == memory_type,
        )
    ).all()
    best: Optional[MemorySlot] = None
    best_sim = 0.0
    for cand in existing:
        if cand.key_embedding is None:
            continue
        sim = cosine(key_vec, list(cand.key_embedding))
        if sim > best_sim:
            best, best_sim = cand, sim
    if best is not None and best_sim >= SAME_SLOT_THRESHOLD:
        return best

    slot = MemorySlot(
        user_id=user_id,
        key=key,
        memory_type=memory_type,
        cardinality=cardinality,
        key_embedding=key_vec,
    )
    db.add(slot)
    db.flush()
    return slot
