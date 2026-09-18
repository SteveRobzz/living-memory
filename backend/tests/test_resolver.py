"""
Resolver tests — no database, no LLM, no API key required.

If these pass, the memory engine is correct. Everything else is plumbing.
Run:  pytest tests/test_resolver.py -v
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.memory.resolver import (
    Candidate,
    ExistingMemory,
    effective_confidence,
    resolve,
)

JAN = datetime(2026, 1, 5, tzinfo=timezone.utc)
FEB = datetime(2026, 2, 10, tzinfo=timezone.utc)
MAR = datetime(2026, 3, 2, tzinfo=timezone.utc)
MAY = datetime(2026, 5, 9, tzinfo=timezone.utc)


def cand(value, assertion="STATEMENT", key="game.engine", **kw):
    return Candidate(
        key=key,
        value=value,
        value_norm=value.strip().lower(),
        memory_type=kw.pop("memory_type", "PROJECT"),
        cardinality=kw.pop("cardinality", "SINGLE"),
        assertion=assertion,
        **kw,
    )


def mem(id, value, status="ACTIVE", valid_from=JAN, **kw):
    return ExistingMemory(
        id=id,
        value=value,
        value_norm=value.strip().lower(),
        status=status,
        confidence=kw.pop("confidence", 0.85),
        valid_from=valid_from,
        **kw,
    )


def creates(res):
    return [o for o in res.ops if o.kind == "CREATE"]


def status_ops(res):
    return [o for o in res.ops if o.kind == "SET_STATUS"]


# ---------- confidence model ---------------------------------

def test_confidence_single_statement():
    assert effective_confidence("STATEMENT", 1) == 0.85


def test_confidence_rises_with_evidence():
    assert effective_confidence("STATEMENT", 3) == 0.95


def test_confidence_saturates():
    assert effective_confidence("STATEMENT", 50) == 0.99


def test_implied_never_reaches_overwrite_threshold():
    assert effective_confidence("IMPLIED", 1) < 0.80


# ---------- rule 1: non-literal ------------------------------

def test_rule1_joke_is_not_stored():
    res = resolve(cand("COBOL", "NON_LITERAL"), [mem(1, "Godot")], MAR)
    assert res.ops == []
    assert res.reason_code == "IGNORED_NON_LITERAL"


# ---------- rule 2: hypothetical -----------------------------

def test_rule2_hypothetical_does_not_touch_active():
    res = resolve(cand("Unreal", "HYPOTHETICAL"), [mem(1, "Godot")], MAR)
    assert status_ops(res) == []
    op = creates(res)[0]
    assert op.slot_key_override == "game.engine.considering"
    assert op.memory_type_override == "GOAL"


# ---------- rule 3: retract ----------------------------------

def test_rule3_retract_hides_from_history():
    res = resolve(cand("Godot", "RETRACT", target_value_norm="godot"),
                  [mem(1, "Godot")], MAR)
    assert status_ops(res)[0].to_status == "RETRACTED"
    assert creates(res) == []


def test_rule3_retract_with_no_match_is_noop():
    res = resolve(cand("Unity", "RETRACT", target_value_norm="unity"),
                  [mem(1, "Godot")], MAR)
    assert res.ops == []


# ---------- rule 4: negation ---------------------------------

def test_rule4_negation_ends_value():
    res = resolve(cand("Unity", "NEGATION"), [mem(1, "Unity")], MAR)
    op = status_ops(res)[0]
    assert op.to_status == "ENDED"
    assert op.set_valid_until == MAR
    assert creates(res) == []


# ---------- rule 5: past tense -------------------------------

def test_rule5_past_backfills_history_without_disturbing_present():
    res = resolve(cand("Unity", "PAST"), [mem(1, "Godot", valid_from=MAR)], MAY)
    assert status_ops(res) == []
    op = creates(res)[0]
    assert op.status == "SUPERSEDED"
    assert op.valid_until == MAR


def test_rule5b_past_tense_about_current_value_ends_it():
    res = resolve(cand("Godot", "PAST"), [mem(1, "Godot")], MAY)
    assert status_ops(res)[0].to_status == "ENDED"


# ---------- rule 6: empty slot -------------------------------

def test_rule6_first_memory_is_active():
    res = resolve(cand("Unity"), [], JAN)
    op = creates(res)[0]
    assert op.status == "ACTIVE"
    assert op.valid_from == JAN
    assert res.reason_code == "CREATED"


# ---------- rule 7: reinforcement ----------------------------

def test_rule7_repeat_reinforces_instead_of_duplicating():
    res = resolve(cand("Godot"), [mem(1, "Godot", evidence_count=1)], MAR)
    assert creates(res) == []
    op = res.ops[0]
    assert op.kind == "REINFORCE"
    assert op.confidence == 0.90


# ---------- rule 8: correction -------------------------------

def test_rule8_correction_retracts_old_value():
    res = resolve(cand("Godot", "CORRECTION"), [mem(1, "Unity", valid_from=JAN)], MAR)
    assert status_ops(res)[0].to_status == "RETRACTED"


def test_rule8_correction_inherits_valid_from():
    """The old value was never true, so the new one owns its whole interval."""
    res = resolve(cand("Godot", "CORRECTION"), [mem(1, "Unity", valid_from=JAN)], MAR)
    assert creates(res)[0].valid_from == JAN


# ---------- rule 9: confident change -------------------------

def test_rule9_change_supersedes():
    res = resolve(cand("Godot", "CHANGE"), [mem(1, "Unity", valid_from=JAN)], MAR)
    old = status_ops(res)[0]
    assert old.to_status == "SUPERSEDED"
    assert old.set_valid_until == MAR
    assert creates(res)[0].status == "ACTIVE"


def test_rule9_supersede_links_both_ways():
    res = resolve(cand("Godot", "CHANGE"), [mem(1, "Unity")], MAR)
    assert status_ops(res)[0].set_superseded_by == "NEW"
    assert creates(res)[0].supersedes_id == 1


def test_rule9_old_memory_is_never_deleted():
    res = resolve(cand("Godot", "CHANGE"), [mem(1, "Unity")], MAR)
    assert all(o.kind != "DELETE" for o in res.ops)
    assert status_ops(res)[0].to_status == "SUPERSEDED"


# ---------- rule 10: dispute ---------------------------------

def test_rule10_low_confidence_creates_dispute():
    res = resolve(cand("Unity", "IMPLIED"), [mem(1, "Godot")], MAR)
    assert res.disputed is True
    assert status_ops(res)[0].to_status == "DISPUTED"
    assert creates(res)[0].status == "DISPUTED"


def test_rule10_dispute_asks_the_user():
    res = resolve(cand("Unity", "IMPLIED"), [mem(1, "Godot")], MAR)
    assert res.clarify is not None
    assert "Godot" in res.clarify and "Unity" in res.clarify


def test_rule10_no_active_value_while_disputed():
    """The slot deliberately has no current value until the user clarifies."""
    res = resolve(cand("Unity", "IMPLIED"), [mem(1, "Godot")], MAR)
    assert not any(o.status == "ACTIVE" for o in creates(res))


# ---------- rules 11/12: multi-value slots -------------------

def test_rule11_multi_values_coexist():
    res = resolve(cand("jazz", key="music.likes", cardinality="MULTI",
                       memory_type="PREFERENCE"),
                  [mem(1, "rock")], MAR)
    assert status_ops(res) == []
    assert creates(res)[0].status == "ACTIVE"


def test_rule12_polarity_flip_supersedes():
    res = resolve(cand("rock", key="music.likes", cardinality="MULTI",
                       memory_type="PREFERENCE", polarity=-1),
                  [mem(1, "rock", polarity=1)], MAR)
    assert status_ops(res)[0].to_status == "SUPERSEDED"


# ---------- rule 13: dispute resolution ----------------------

def test_rule13_dispute_resolved_by_clarification():
    live = [mem(1, "Godot", status="DISPUTED"), mem(2, "Unity", status="DISPUTED")]
    res = resolve(cand("Godot", "STATEMENT"), live, MAR)
    by_id = {o.memory_id: o for o in status_ops(res)}
    assert by_id[1].to_status == "ACTIVE"
    assert by_id[2].to_status == "SUPERSEDED"
    assert creates(res) == []


def test_rule13_third_value_resolves_dispute():
    live = [mem(1, "Godot", status="DISPUTED"), mem(2, "Unity", status="DISPUTED")]
    res = resolve(cand("Unreal", "CHANGE"), live, MAR)
    assert all(o.to_status == "SUPERSEDED" for o in status_ops(res))
    assert creates(res)[0].status == "ACTIVE"


# ---------- isolation of adjacent slots ----------------------

def test_different_slots_do_not_collide():
    """favorite language and work language are separate attributes."""
    res = resolve(cand("Java", "CHANGE", key="work.language",
                       memory_type="FACT"), [], MAR)
    assert res.reason_code == "CREATED"


# ---------- the demo path ------------------------------------

def test_demo_unity_to_godot():
    """The exact sequence judges will watch."""
    # January: first mention
    r1 = resolve(cand("Unity"), [], JAN)
    assert creates(r1)[0].status == "ACTIVE"

    unity = mem(12, "Unity", valid_from=JAN)

    # March: explicit switch
    r2 = resolve(cand("Godot", "CHANGE"), [unity], MAR)
    assert status_ops(r2)[0].memory_id == 12
    assert status_ops(r2)[0].to_status == "SUPERSEDED"
    assert status_ops(r2)[0].set_valid_until == MAR
    assert creates(r2)[0].supersedes_id == 12

    godot = mem(17, "Godot", valid_from=MAR)

    # A hedged remark must NOT silently flip the engine back
    r3 = resolve(cand("Unity", "IMPLIED"), [godot], MAY)
    assert r3.disputed is True

    # The user clarifies
    live = [mem(17, "Godot", status="DISPUTED", valid_from=MAR),
            mem(18, "Unity", status="DISPUTED", valid_from=MAY)]
    r4 = resolve(cand("Godot", "STATEMENT"), live, MAY)
    by_id = {o.memory_id: o for o in status_ops(r4)}
    assert by_id[17].to_status == "ACTIVE"
    assert by_id[18].to_status == "SUPERSEDED"


# ---------- regression: numpy scalars must never reach JSON ----

def test_numpy_values_are_json_serializable():
    """pgvector returns numpy arrays when numpy is installed, and numpy
    scalars are not JSON serializable. Every number that can reach an API
    response must be a plain Python float."""
    import json

    np = pytest.importorskip("numpy")
    from app.embeddings import as_floats, cosine
    from app.memory.trace import _f

    a = np.array([0.1] * 384, dtype="float32")
    b = np.array([0.25] * 384, dtype="float32")

    sim = cosine(a, b)
    assert type(sim) is float
    json.dumps({"similarity": sim})

    assert all(type(x) is float for x in as_floats(a))
    assert type(_f(np.float32(0.5))) is float
    json.dumps({"x": _f(np.float32(0.5))})
