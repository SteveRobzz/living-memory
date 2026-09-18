# Living Memory

**RAG retrieves information. Living Memory decides what is still true.**

A temporal memory engine for AI assistants. Every fact carries a status, a
validity interval, the evidence behind it and a logged reason for every change
— and no answer can cite a memory it was not shown.

Built for Epochesque (HackClub VITC), Track 3.

---

## Folder structure

Create this exactly:

```
living-memory/
├── docker-compose.yml
├── README.md
├── backend/
│   ├── schema.sql
│   ├── requirements.txt
│   ├── .env.example          → copy to .env
│   ├── pytest.ini
│   ├── seed_demo.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── clock.py
│   │   ├── db.py
│   │   ├── auth.py
│   │   ├── models.py
│   │   ├── embeddings.py
│   │   ├── main.py
│   │   └── memory/
│   │       ├── __init__.py
│   │       ├── resolver.py       ← the core: decides what is true
│   │       ├── normalize.py
│   │       ├── slots.py
│   │       ├── analyzer.py       ← rule-based, no API key
│   │       ├── analyzer_llm.py   ← optional LLM backend
│   │       ├── lifecycle.py
│   │       ├── retrieval.py
│   │       ├── context.py
│   │       └── trace.py
│   └── tests/
│       ├── __init__.py
│       ├── test_resolver.py      27 tests, no DB needed
│       └── test_e2e.py           23 tests, needs the DB
└── frontend/
    ├── package.json
    ├── next.config.mjs
    ├── postcss.config.mjs
    ├── tailwind.config.ts
    ├── tsconfig.json
    ├── .env.local.example    → copy to .env.local
    ├── lib/api.ts
    ├── app/
    │   ├── layout.tsx
    │   ├── globals.css
    │   └── page.tsx
    └── components/
        ├── StatusChip.tsx
        ├── MemoryPanel.tsx
        ├── TraceView.tsx
        ├── Timeline.tsx
        ├── GraphView.tsx
        └── MemoryDrawer.tsx
```

`app/__init__.py`, `app/memory/__init__.py` and `tests/__init__.py` are empty
files — create them or the imports fail.

---

## Setup

```bash
# 1. database
docker compose up -d
docker compose exec -T db psql -U lm -d livingmemory < backend/schema.sql

# 2. backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest -q                          # expect: 50 passed
uvicorn app.main:app --reload --port 8000

# 3. frontend (new terminal)
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                        # http://localhost:3000
```

Postgres runs on **5433** so it won't clash with a local install.

---

## No API key required

`ANALYZER=rules` is the default. Extraction runs on marker phrases and an
entity registry — no model, no network, no key. Everything downstream
(resolver, lifecycle, retrieval, trace) never touched an LLM in the first
place.

If a key turns up later, set `ANALYZER=llm` and one of `ANTHROPIC_API_KEY` /
`GROQ_API_KEY`. Same output schema, same engine. Groq and Google AI Studio
both issue free keys with no card.

This is also the best answer to *"isn't this just prompting?"* — you can run
the whole demo with the model switched off.

---

## Demo script (~4 min)

| Step | Do | Judges see |
|---|---|---|
| 1 | Pick **Maya**. Click **Jan 2026**. Say: `I'm building a game in Unity.` | `mem_001 created · ACTIVE`. Demo-clock banner is visible. |
| 2 | `My favorite food is biryani.` | Second memory, different slot. |
| 3 | **Kill uvicorn. Restart it. Click "new session".** Ask `What engine am I using?` | Unity, with a trace. **Persistence.** |
| 4 | Click **Mar 2026**. `I switched my game to Godot.` | Two chips: Unity → `superseded`, Godot → `created`. |
| 5 | `What engine am I currently using?` → **Why did I say this?** | mem ACTIVE, source excerpt, `replaced mem_001 (Unity)`, pipeline counts. |
| 6 | `What engine was I using before?` | Unity, from the supersession chain. |
| 7 | `What engine was I using in February?` | Unity — point-in-time query. |
| 8 | `Spent all day in Unity again.` | Both go **DISPUTED**. No active value. It asks which is current. |
| 9 | `I'm using Godot.` | Dispute resolved. Godot ACTIVE, Unity SUPERSEDED. |
| 10 | Open **Timeline** tab | Unity bar Jan–Mar, Godot bar Mar–now. |
| 11 | Switch to **Dev**. `What engine am I using?` | "I don't have anything stored." **Isolation.** |
| 12 | Switch back to Maya | Still Godot. |

Backup: `python seed_demo.py` rebuilds this state in ten seconds. Record a
screen capture tonight in case the venue network misbehaves.

**Step 8 is the one to linger on.** Most memory systems accept the newest
statement. This one refuses to guess.

---

## Judge Q&A

**"Isn't this just RAG?"**
RAG has no notion of validity. Tell it Python on Monday and Java on Tuesday
and both sit in the vector store with equal weight — Python may even rank
higher for being mentioned more. Here Python is marked SUPERSEDED by the
resolver and filtered out in code before anything composes an answer.

**"Couldn't you just put this in the prompt?"**
Prompts don't persist across sessions, don't survive the context window,
have no mechanism for deciding which of two conflicting facts wins, and leave
no audit trail. Kill the server mid-demo and this still knows.

**"Isn't this just a knowledge graph?"**
A knowledge graph stores relationships. It has no validity intervals, no
status transitions, no contradiction resolution. The graph in the Observatory
is a *view* over `supersedes_id`, `slot_id` and `dispute_group_id` — it's
rendered from the engine, it isn't the engine.

**"How do you know which memory is currently true?"**
`schema.sql`:
```sql
CREATE UNIQUE INDEX one_active_per_single_slot
  ON memories (slot_id) WHERE status = 'ACTIVE' AND cardinality = 'SINGLE';
```
Two current values are impossible at the database level. Status is set by
`resolver.py`, which imports nothing from the database, the network or any
model.

**"What happens when the user contradicts themselves?"**
Explicit change → old value SUPERSEDED, history kept. Explicit correction →
old value RETRACTED, because it was never true, and the new value inherits
its start date. Ambiguous → both DISPUTED and the assistant asks.

**"Can you prove which memory generated the answer?"**
Every answer stores used ids, considered-and-rejected ids with the reason
each was excluded, per-stage pipeline counts, and similarity/score per
candidate. The validator drops any id that wasn't in the context block.

---

## The five states

| State | Meaning | In "now" answers | In history |
|---|---|---|---|
| ACTIVE | currently true | yes | yes |
| SUPERSEDED | was true, replaced | no | yes |
| ENDED | was true, stopped, nothing replaced it | no | yes |
| DISPUTED | conflicting values, unresolved | no — it asks instead | yes |
| RETRACTED | **never true** (corrected or forgotten) | no | **no** |
| ARCHIVED | believed but decayed out of retrieval | on direct match | yes |

The SUPERSEDED / RETRACTED split is the distinction most systems collapse.
"I switched from Unity to Godot" belongs in history. "I was wrong, it was
never Unity" does not.

## Confidence

```
effective_confidence = base(assertion) + 0.05 × min(evidence_count − 1, 4)
```
CORRECTION 0.95 · CHANGE 0.90 · STATEMENT 0.85 · IMPLIED 0.60 · HYPOTHETICAL 0.40.
A new value may only displace an active one at ≥ 0.80. Below that it disputes.
Stated three times, a plain statement reaches 0.95. That's the whole model.

## Not built, on purpose

Neo4j, Redis, Celery, microservices, websockets, memory summarisation, ANN
index tuning, OAuth. None are needed at this scale and each is a thing that
can break at 9:55am.
