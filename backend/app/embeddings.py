"""Embeddings for semantic retrieval.

Two interchangeable backends, both 384-dimensional so the schema never changes:

  "hash"       - deterministic lexical hashing. No download, no network, no
                 model, runs in microseconds. Captures word overlap, which is
                 what the demo's retrieval actually leans on. DEFAULT, because
                 a hackathon demo must never depend on a model download
                 finishing over venue wifi.

  "fastembed"  - BAAI/bge-small-en-v1.5 via ONNX on CPU. True semantic
                 similarity ("what am I coding with" ~ "main_language").
                 Downloads ~90MB once. Set EMBEDDING_BACKEND=fastembed and
                 warm it before demoing.

Retrieval never depends on embeddings alone: slot-key matching runs in
parallel and is pinned ahead of vector hits. Embeddings widen recall; they
do not decide truth.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import List, Optional

from .config import get_settings

DIM = 384
_TOKEN = re.compile(r"[a-z0-9\+\#\.]+")

_model = None


def _tokens(text: str) -> List[str]:
    return _TOKEN.findall(text.lower())


def _hash_embed(text: str) -> List[float]:
    """Deterministic bag-of-words hashing into a unit vector.

    Each token (plus its bigrams) is hashed to a dimension and accumulated,
    then L2-normalised. Two strings sharing words land close together.
    """
    vec = [0.0] * DIM
    toks = _tokens(text)
    if not toks:
        return vec
    grams = list(toks) + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    for gram in grams:
        digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        # rarer (longer) grams weigh slightly more
        vec[idx] += sign * (1.0 + 0.3 * ("_" in gram))
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _load_fastembed():
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # imported lazily on purpose

        _model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _model


def embed(text: str) -> List[float]:
    backend = get_settings().embedding_backend
    if backend == "fastembed":
        try:
            model = _load_fastembed()
            return [float(x) for x in next(iter(model.embed([text])))]
        except Exception:
            # Never let an embedding failure take down a write or a demo.
            return _hash_embed(text)
    return _hash_embed(text)


def as_floats(vec) -> Optional[List[float]]:
    """Normalise a stored embedding (list or numpy array) to Python floats."""
    if vec is None:
        return None
    return [float(x) for x in vec]


def embed_memory(key: str, value: str) -> List[float]:
    """Embed a memory as an attribute/value pair, not a bare value."""
    readable = key.replace(".", " ").replace("_", " ")
    return embed(f"{readable}: {value}")


def cosine(a, b) -> float:
    """Cosine similarity, always as a plain Python float.

    pgvector hands embeddings back as numpy arrays when numpy is installed,
    and numpy scalars are not JSON serializable. Every value that can reach
    an API response is coerced here, at the source.
    """
    if a is None or b is None:
        return 0.0
    a = [float(x) for x in a]
    b = [float(x) for x in b]
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(dot / (na * nb))
