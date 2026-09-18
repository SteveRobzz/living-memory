"""End-to-end tests against a real Postgres + pgvector database.

These exercise the whole path: message -> analyzer -> resolver -> lifecycle
-> retrieval -> answer -> trace. No LLM and no API key involved.

Requires the database from docker-compose to be up and schema.sql applied:
    docker compose up -d
    docker compose exec -T db psql -U lm -d livingmemory < backend/schema.sql
    pytest tests/test_e2e.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.main import app

JAN = "2026-01-05T09:00:00+00:00"
FEB = "2026-02-10T09:00:00+00:00"
MAR = "2026-03-02T09:00:00+00:00"
MAY = "2026-05-09T09:00:00+00:00"


@pytest.fixture()
def client():
    c = TestClient(app)
    c.post("/demo/reset")
    yield c
    c.post("/demo/clock", json={"as_of": None})


def login(client, handle):
    r = client.post("/auth/demo-login", json={"handle": handle})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def new_conv(client, headers, title=None):
    return client.post("/conversations", json={"title": title},
                       headers=headers).json()["id"]


def say(client, headers, conv, text):
    r = client.post(f"/conversations/{conv}/messages",
                    json={"content": text}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def set_clock(client, iso):
    client.post("/demo/clock", json={"as_of": iso})


def memories(client, headers, status=None):
    url = "/memories" + (f"?status={status}" if status else "")
    return client.get(url, headers=headers).json()


def active_value(client, headers, key):
    for m in memories(client, headers, "ACTIVE"):
        if m["key"] == key:
            return m["value"]
    return None


# ============================================================

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_1_basic_persistence(client):
    """Memory survives a new session. The engine's state is in the DB."""
    h = login(client, "maya")
    c1 = new_conv(client, h)
    say(client, h, c1, "My main language is Python.")

    # brand new conversation, as if the app was closed and reopened
    c2 = new_conv(client, h)
    out = say(client, h, c2, "What is my main language?")
    assert "Python" in out["assistant_message"]["content"]
    assert out["trace"]["used"], "answer must cite a memory"


def test_2_contradiction_supersedes_and_keeps_history(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "I'm building a game in Unity.")
    set_clock(client, MAR)
    out = say(client, h, c, "I switched my game to Godot.")

    events = {ch["event"] for ch in out["memory_changes"]}
    assert "SUPERSEDED" in events and "CREATED" in events

    assert active_value(client, h, "game.engine") == "Godot"
    superseded = [m for m in memories(client, h, "SUPERSEDED")
                  if m["value"] == "Unity"]
    assert superseded, "Unity must remain as history, not be deleted"
    assert superseded[0]["superseded_by_id"] is not None


def test_3_current_question_answers_godot_with_trace(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "I'm building a game in Unity.")
    set_clock(client, MAR)
    say(client, h, c, "I switched my game to Godot.")

    out = say(client, h, c, "What engine am I currently using?")
    assert "Godot" in out["assistant_message"]["content"]
    used = out["trace"]["used"]
    assert len(used) >= 1
    assert used[0]["status"] == "ACTIVE"
    assert used[0]["value"] == "Godot"
    assert used[0]["supersedes"]["value"] == "Unity"
    assert used[0]["source"]["excerpt"]


def test_4_previous_question_walks_the_chain(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "I'm building a game in Unity.")
    set_clock(client, MAR)
    say(client, h, c, "I switched my game to Godot.")

    out = say(client, h, c, "What engine was I using before?")
    assert "Unity" in out["assistant_message"]["content"]


def test_5_historical_point_in_time(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "I'm building a game in Unity.")
    set_clock(client, MAR)
    say(client, h, c, "I switched my game to Godot.")
    set_clock(client, MAY)

    out = say(client, h, c, "What engine was I using in February?")
    assert "Unity" in out["assistant_message"]["content"]


def test_6_multiple_changes_timeline(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "My main language is Python.")
    set_clock(client, FEB)
    say(client, h, c, "I switched to Java.")
    set_clock(client, MAR)
    say(client, h, c, "I switched to Rust.")

    assert active_value(client, h, "main_language") == "Rust"
    timeline = client.get("/memories/timeline", headers=h).json()
    slot = next(t for t in timeline if t["key"] == "main_language")
    values = [e["value"] for e in slot["entries"]]
    assert values == ["Python", "Java", "Rust"]


def test_7_hypothetical_does_not_overwrite(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, MAR)
    say(client, h, c, "I'm building a game in Godot.")
    say(client, h, c, "I might try Unreal someday.")

    assert active_value(client, h, "game.engine") == "Godot"


def test_8_implied_conflict_becomes_disputed(client):
    """Ambiguous conflict must NOT silently accept the newest statement."""
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, MAR)
    say(client, h, c, "I'm building a game in Godot.")
    out = say(client, h, c, "Spent all day in Unity again.")

    statuses = {ch["status"] for ch in out["memory_changes"]}
    assert "DISPUTED" in statuses
    assert active_value(client, h, "game.engine") is None
    assert "?" in out["assistant_message"]["content"]


def test_9_dispute_resolved_by_clarification(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, MAR)
    say(client, h, c, "I'm building a game in Godot.")
    say(client, h, c, "Spent all day in Unity again.")
    say(client, h, c, "I'm using Godot.")

    assert active_value(client, h, "game.engine") == "Godot"
    supers = [m["value"] for m in memories(client, h, "SUPERSEDED")]
    assert "Unity" in supers


def test_10_explicit_correction_retracts(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "My main language is Go.")
    set_clock(client, MAR)
    say(client, h, c, "Actually I was wrong, my main language is Rust.")

    assert active_value(client, h, "main_language") == "Rust"
    retracted = [m["value"] for m in memories(client, h, "RETRACTED")]
    assert "Go" in retracted
    timeline = client.get("/memories/timeline", headers=h).json()
    slot = next(t for t in timeline if t["key"] == "main_language")
    assert "Go" not in [e["value"] for e in slot["entries"]], \
        "a retracted value was never true, so it has no history"


def test_11_forget_removes_from_answers(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    say(client, h, c, "My favorite food is biryani.")
    say(client, h, c, "Forget what I said about biryani.")

    out = say(client, h, c, "What is my favorite food?")
    assert "biryani" not in out["assistant_message"]["content"].lower()


def test_12_repetition_reinforces_instead_of_duplicating(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    say(client, h, c, "My main language is Python.")
    say(client, h, c, "My main language is Python.")
    say(client, h, c, "My main language is Python.")

    rows = [m for m in memories(client, h, "ACTIVE") if m["key"] == "main_language"]
    assert len(rows) == 1
    assert rows[0]["evidence_count"] == 3
    assert rows[0]["confidence"] > 0.85


def test_13_chitchat_is_not_stored(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    say(client, h, c, "I'm hungry.")
    say(client, h, c, "That's cool, thanks.")
    assert memories(client, h) == []


def test_14_multi_user_isolation(client):
    a = login(client, "maya")
    b = login(client, "dev")
    ca, cb = new_conv(client, a), new_conv(client, b)

    say(client, a, ca, "My favorite game is Valorant.")
    say(client, b, cb, "My favorite game is Minecraft.")

    out_a = say(client, a, ca, "What is my favorite game?")
    out_b = say(client, b, cb, "What is my favorite game?")
    assert "Valorant" in out_a["assistant_message"]["content"]
    assert "Minecraft" in out_b["assistant_message"]["content"]
    assert "Minecraft" not in out_a["assistant_message"]["content"]


def test_15_cross_user_read_is_404_not_403(client):
    a = login(client, "maya")
    b = login(client, "dev")
    ca = new_conv(client, a)
    say(client, a, ca, "My favorite game is Valorant.")
    mem_id = memories(client, a)[0]["id"]

    r = client.get(f"/memories/{mem_id}", headers=b)
    assert r.status_code == 404, "must not confirm another user's ids exist"


def test_16_unrelated_question_returns_nothing(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    say(client, h, c, "My favorite food is biryani.")
    out = say(client, h, c, "What is my main language?")
    assert "biryani" not in out["assistant_message"]["content"].lower()


def test_17_trace_only_cites_retrieved_memories(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, MAR)
    say(client, h, c, "I'm building a game in Godot.")
    out = say(client, h, c, "What engine am I using?")

    candidate_ids = {m["id"] for m in out["trace"]["used"]} | \
                    {m["id"] for m in out["trace"]["considered_not_used"]}
    for used in out["trace"]["used"]:
        assert used["id"] in candidate_ids


def test_18_stored_trace_is_retrievable(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    say(client, h, c, "My main language is Python.")
    out = say(client, h, c, "What is my main language?")
    msg_id = out["assistant_message"]["id"]

    r = client.get(f"/messages/{msg_id}/trace", headers=h)
    assert r.status_code == 200
    assert r.json()["used_memory_ids"]


def test_19_graph_has_supersedes_edge(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "I'm building a game in Unity.")
    set_clock(client, MAR)
    say(client, h, c, "I switched my game to Godot.")

    g = client.get("/memories/graph", headers=h).json()
    assert len(g["nodes"]) == 2
    assert any(e["type"] == "SUPERSEDES" for e in g["edges"])


def test_20_negation_ends_without_replacement(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "I'm building a game in Unity.")
    set_clock(client, MAR)
    say(client, h, c, "I don't use Unity anymore.")

    assert active_value(client, h, "game.engine") is None
    ended = [m["value"] for m in memories(client, h, "ENDED")]
    assert "Unity" in ended


def test_21_events_are_logged_with_reasons(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "I'm building a game in Unity.")
    set_clock(client, MAR)
    say(client, h, c, "I switched my game to Godot.")

    events = client.get("/events", headers=h).json()
    codes = {e["reason_code"] for e in events}
    assert "SUPERSEDED_BY_CHANGE" in codes


def test_22_meta_question_lists_active_only(client):
    h = login(client, "maya")
    c = new_conv(client, h)
    set_clock(client, JAN)
    say(client, h, c, "I'm building a game in Unity.")
    set_clock(client, MAR)
    say(client, h, c, "I switched my game to Godot.")

    out = say(client, h, c, "What do you know about me?")
    content = out["assistant_message"]["content"]
    assert "Godot" in content and "Unity" not in content
