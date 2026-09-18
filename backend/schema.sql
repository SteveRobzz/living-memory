-- ============================================================
-- LIVING MEMORY — schema
-- Source of truth for what is currently true, what used to be
-- true, what supports it, and what contradicts it.
-- Apply with:
--   docker compose exec -T db psql -U lm -d livingmemory < backend/schema.sql
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------- identity ----------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id           SERIAL PRIMARY KEY,
    handle       TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    color        TEXT NOT NULL DEFAULT '#3b82f6',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS conversations_user ON conversations (user_id, created_at DESC);

-- Raw log. Messages are evidence, NOT memory.
CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()   -- demo clock aware
);

CREATE INDEX IF NOT EXISTS messages_conv ON messages (conversation_id, id);

-- ---------- slots -------------------------------------------
-- A slot is one attribute of one user ("game.engine").
-- Per-user registry => key vocabularies never leak between users.

CREATE TABLE IF NOT EXISTS memory_slots (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key           TEXT NOT NULL,
    memory_type   TEXT NOT NULL,
    cardinality   TEXT NOT NULL DEFAULT 'SINGLE' CHECK (cardinality IN ('SINGLE','MULTI')),
    description   TEXT,
    key_embedding vector(384),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, key)
);

-- ---------- memories ----------------------------------------
-- APPEND ONLY. Every version of a fact is its own row.
-- Nothing is deleted on supersession; only status + links change.

CREATE TABLE IF NOT EXISTS memories (
    id                BIGSERIAL PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slot_id           INTEGER NOT NULL REFERENCES memory_slots(id) ON DELETE CASCADE,

    key               TEXT NOT NULL,
    value             TEXT NOT NULL,
    value_norm        TEXT NOT NULL,
    polarity          SMALLINT NOT NULL DEFAULT 1 CHECK (polarity IN (1,-1)),

    memory_type       TEXT NOT NULL,
    cardinality       TEXT NOT NULL DEFAULT 'SINGLE' CHECK (cardinality IN ('SINGLE','MULTI')),

    status            TEXT NOT NULL DEFAULT 'ACTIVE'
                      CHECK (status IN ('ACTIVE','SUPERSEDED','ENDED','RETRACTED','DISPUTED','ARCHIVED')),
    status_reason     TEXT,

    assertion         TEXT NOT NULL,
    confidence        REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    importance        REAL NOT NULL CHECK (importance >= 0 AND importance <= 1),

    -- deterministic evidence model
    evidence_count    INTEGER NOT NULL DEFAULT 1,
    evidence_type     TEXT NOT NULL DEFAULT 'STATED'
                      CHECK (evidence_type IN ('STATED','REPEATED','IMPLIED','INFERRED')),

    -- VALID time: when this was true in the user's life
    valid_from        TIMESTAMPTZ NOT NULL,
    valid_until       TIMESTAMPTZ,
    -- RECORDED time: when the system learned it
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ,                 -- TEMPORARY_CONTEXT only

    last_confirmed_at TIMESTAMPTZ,
    last_accessed_at  TIMESTAMPTZ,
    access_count      INTEGER NOT NULL DEFAULT 0,

    -- relationships (this is the knowledge graph; no Neo4j needed)
    supersedes_id     BIGINT REFERENCES memories(id) ON DELETE SET NULL,
    superseded_by_id  BIGINT REFERENCES memories(id) ON DELETE SET NULL,
    dispute_group_id  BIGINT,

    source_message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
    embedding         vector(384)
);

-- THE GUARANTEE: at most one ACTIVE value per single-cardinality slot.
-- This is what makes "which memory is currently true" a database fact.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_single_slot
    ON memories (slot_id)
    WHERE status = 'ACTIVE' AND cardinality = 'SINGLE';

CREATE UNIQUE INDEX IF NOT EXISTS one_active_value_per_multi_slot
    ON memories (slot_id, value_norm)
    WHERE status = 'ACTIVE' AND cardinality = 'MULTI';

CREATE INDEX IF NOT EXISTS memories_user_status ON memories (user_id, status);
CREATE INDEX IF NOT EXISTS memories_slot_valid  ON memories (slot_id, valid_from);
CREATE INDEX IF NOT EXISTS memories_dispute     ON memories (dispute_group_id)
    WHERE dispute_group_id IS NOT NULL;

-- ---------- provenance --------------------------------------
-- One memory can be supported by many messages (repetition
-- reinforces a single row instead of creating duplicates).

CREATE TABLE IF NOT EXISTS memory_sources (
    id         BIGSERIAL PRIMARY KEY,
    memory_id  BIGINT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    relation   TEXT NOT NULL CHECK (relation IN ('CREATED','REINFORCED','CORRECTED','ENDED','DISPUTED')),
    excerpt    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (memory_id, message_id, relation)
);

CREATE INDEX IF NOT EXISTS memory_sources_mem ON memory_sources (memory_id);

-- ---------- audit trail -------------------------------------
-- Every state transition, with the reason and the message that caused it.

CREATE TABLE IF NOT EXISTS memory_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_id   BIGINT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    event       TEXT NOT NULL CHECK (event IN (
                    'CREATED','REINFORCED','SUPERSEDED','ENDED','RETRACTED',
                    'DISPUTED','DISPUTE_RESOLVED','ARCHIVED','RESTORED','ACCESSED')),
    from_status TEXT,
    to_status   TEXT,
    reason_code TEXT NOT NULL,
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    message_id  BIGINT REFERENCES messages(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memory_events_mem  ON memory_events (memory_id, created_at);
CREATE INDEX IF NOT EXISTS memory_events_user ON memory_events (user_id, created_at DESC);

-- ---------- retrieval trace ---------------------------------

CREATE TABLE IF NOT EXISTS answer_traces (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assistant_message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    time_scope           TEXT NOT NULL,
    used_memory_ids      BIGINT[] NOT NULL DEFAULT '{}',
    candidate_ids        BIGINT[] NOT NULL DEFAULT '{}',
    scores               JSONB NOT NULL DEFAULT '{}'::jsonb,
    pipeline             JSONB NOT NULL DEFAULT '{}'::jsonb,  -- counts at each filter stage
    reason               TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS answer_traces_msg ON answer_traces (assistant_message_id);

-- ---------- demo users --------------------------------------

INSERT INTO users (handle, display_name, color) VALUES
    ('maya', 'Maya',  '#3b82f6'),
    ('dev',  'Dev',   '#f97316')
ON CONFLICT (handle) DO NOTHING;
