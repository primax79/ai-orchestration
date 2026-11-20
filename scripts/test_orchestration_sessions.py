"""test_orchestration_sessions.py — Comprehensive tests for session registry, identifiers and cursors.

Verifies:
  - Spec §0, §0b, §0c E2, E10, Spec §2
  - Registration, defaults, pre-assigned IDs, custom subscriptions, kind and tool
  - Orchestrator role registration, succession to generation N+1, role cursor inheritance (E2)
  - List and show with dynamic staleness (timeout)
  - Heartbeat resets staleness back to active
  - Deregister / end with retired reason
  - Monotonic cursor advance and backwards movement refusal
  - Subscriptions matching and get_pending_work
  - Concurrent heartbeats from multiple multiprocessing processes
  - Atomic writes and session lock thread/process safety
  - Event emission on register, deregister, and orchestrator rotation
  - CLI commands via bin/ai-orch sessions and session alias
"""
from __future__ import annotations

import datetime
import json
import multiprocessing
import os
import pathlib
import subprocess
import sys
import threading
import time
from typing import Any
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from orchestration_events import (
    emit,
    read_events,
)
from orchestration_sessions import (
    session_lock,
    register_session,
    heartbeat_session,
    deregister_session,
    advance_cursor,
    get_cursor,
    get_session,
    list_sessions,
    get_role_holder,
    get_pending_work,
    compute_session_status,
    matches_subscription,
    DEFAULT_STALE_TIMEOUT_SEC,
)

BIN_AI_ORCH = REPO_ROOT / "bin" / "ai-orch"


@pytest.fixture
def ws(tmp_path: pathlib.Path) -> pathlib.Path:
    workspace = tmp_path / "test_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


# ---------------------------------------------------------------------------
# Registration Tests
# ---------------------------------------------------------------------------

def test_register_session_defaults(ws: pathlib.Path):
    """Test default registration creates session file and returns valid metadata."""
    sess = register_session(ws, tool="claude", kind="headless")
    sid = sess["session_id"]
    assert sid
    assert sess["registry_session_id"] == sid
    assert sess["tool"] == "claude"
    assert sess["kind"] == "headless"
    assert sess["status"] == "active"
    assert sess["cursor"] == 0
    assert sess["subscriptions"] == []
    assert sess["created_at"]
    assert sess["last_seen"] == sess["created_at"]

    sess_file = ws / ".ai-orchestration" / "sessions" / f"{sid}.json"
    assert sess_file.is_file()
    data = json.loads(sess_file.read_text(encoding="utf-8"))
    assert data["session_id"] == sid
    assert data["tool"] == "claude"


def test_register_session_custom_fields(ws: pathlib.Path):
    """Test registration with pre-assigned session ID, resume info, and subscriptions."""
    custom_id = "custom-sess-uuid-1234"
    prov_id = "thread_abc123"
    subs = ["question.*", "task.transitioned", "subject:T001"]

    sess = register_session(
        ws,
        tool="codex",
        kind="headless",
        session_id=custom_id,
        resume_id=prov_id,
        subscriptions=subs,
        cursor=5,
    )
    assert sess["session_id"] == custom_id
    assert sess["provider_session_id"] == prov_id
    assert sess["resume"]["provider_session_id"] == prov_id
    assert sess["resume"]["cwd"] == str(ws)
    assert sess["cursor"] == 5
    assert sess["subscriptions"] == subs

    # Verify event was emitted
    events = read_events(ws)
    assert len(events) == 1
    assert events[0]["type"] == "session.registered"
    assert events[0]["subject"] == custom_id
    assert events[0]["origin_session"] == custom_id


# ---------------------------------------------------------------------------
# Orchestrator Role & Succession Tests (Spec §0, E2, E10)
# ---------------------------------------------------------------------------

def test_orchestrator_role_and_succession(ws: pathlib.Path):
    """Test orchestrator role creation, generation 1, cursor advance, and generation 2 succession."""
    # 1. Register first orchestrator generation
    sess1 = register_session(
        ws,
        tool="claude",
        role="orchestrator",
        cursor=10,
    )
    sid1 = sess1["session_id"]
    assert sess1["role"] == "orchestrator"
    assert sess1["generation"] == 1
    assert sess1["cursor"] == 10

    orch_file = ws / ".ai-orchestration" / "orchestrator.json"
    assert orch_file.is_file()
    orch_data = json.loads(orch_file.read_text(encoding="utf-8"))
    assert orch_data["role_id"] == "orchestrator"
    assert orch_data["generation"] == 1
    assert orch_data["cursor"] == 10
    assert orch_data["current"]["session_id"] == sid1
    assert orch_data["current"]["status"] == "active"

    # Advance cursor on session 1
    advance_cursor(ws, seq=42, session_id=sid1)
    orch_data = json.loads(orch_file.read_text(encoding="utf-8"))
    assert orch_data["cursor"] == 42

    # Verify role holder lookup
    holder = get_role_holder(ws, "orchestrator")
    assert holder is not None
    assert holder["generation"] == 1
    assert holder["session_id"] == sid1
    assert holder["cursor"] == 42
    assert holder["status"] == "active"

    # 2. Succession: register generation 2 with a new tool session
    sess2 = register_session(
        ws,
        tool="kilo",
        role="orchestrator",
        reason="context_exhausted",
    )
    sid2 = sess2["session_id"]
    assert sid2 != sid1
    assert sess2["generation"] == 2
    # Per E2: new generation inherits the role's cursor!
    assert sess2["cursor"] == 42

    # Check session 1 was retired
    s1_data = get_session(ws, sid1)
    assert s1_data["status"] == "retired"
    assert s1_data["retired"]["reason"] == "context_exhausted"
    assert s1_data["retired"]["at"]

    # Check orchestrator.json points to generation 2
    orch_data2 = json.loads(orch_file.read_text(encoding="utf-8"))
    assert orch_data2["generation"] == 2
    assert orch_data2["cursor"] == 42
    assert orch_data2["current"]["session_id"] == sid2
    assert orch_data2["current"]["tool"] == "kilo"

    # Verify role holder lookup now returns generation 2
    holder2 = get_role_holder(ws, "orchestrator")
    assert holder2 is not None
    assert holder2["generation"] == 2
    assert holder2["session_id"] == sid2
    assert holder2["tool"] == "kilo"

    # Verify events emitted: session.registered (sess1), orchestrator.rotated, session.registered (sess2)
    evs = read_events(ws)
    types = [e["type"] for e in evs]
    assert "orchestrator.rotated" in types
    rot_ev = [e for e in evs if e["type"] == "orchestrator.rotated"][0]
    assert rot_ev["payload"]["generation"] == 2
    assert rot_ev["payload"]["previous_session_id"] == sid1
    assert rot_ev["payload"]["session_id"] == sid2
    assert rot_ev["payload"]["reason"] == "context_exhausted"


# ---------------------------------------------------------------------------
# List and Show Tests
# ---------------------------------------------------------------------------

def test_list_and_filter_sessions(ws: pathlib.Path):
    """Test listing sessions and filtering by role, tool, and status."""
    s1 = register_session(ws, tool="claude", role="orchestrator")
    s2 = register_session(ws, tool="kilo", kind="interactive")
    s3 = register_session(ws, tool="codex", kind="headless")

    all_sess = list_sessions(ws)
    assert len(all_sess) == 3

    claude_sess = list_sessions(ws, tool="claude")
    assert len(claude_sess) == 1
    assert claude_sess[0]["session_id"] == s1["session_id"]

    kilo_sess = list_sessions(ws, tool="kilo")
    assert len(kilo_sess) == 1
    assert kilo_sess[0]["session_id"] == s2["session_id"]

    orch_sess = list_sessions(ws, role="orchestrator")
    assert len(orch_sess) == 1
    assert orch_sess[0]["session_id"] == s1["session_id"]

    deregister_session(ws, s3["session_id"])
    active_sess = list_sessions(ws, status="active")
    assert len(active_sess) == 2
    dreg_sess = list_sessions(ws, status="deregistered")
    assert len(dreg_sess) == 1
    assert dreg_sess[0]["session_id"] == s3["session_id"]


def test_show_session(ws: pathlib.Path):
    """Test retrieving session details and error on missing session."""
    s = register_session(ws, tool="human", kind="interactive")
    sid = s["session_id"]

    fetched = get_session(ws, sid)
    assert fetched["session_id"] == sid
    assert fetched["tool"] == "human"

    with pytest.raises(FileNotFoundError):
        get_session(ws, "non-existent-session-id")


# ---------------------------------------------------------------------------
# Heartbeat & Staleness Tests
# ---------------------------------------------------------------------------

def test_heartbeat_and_staleness(ws: pathlib.Path):
    """Test staleness detection and heartbeat revival."""
    sess = register_session(ws, tool="claude")
    sid = sess["session_id"]

    # Initially active
    s_active = get_session(ws, sid, stale_timeout_sec=5.0)
    assert s_active["status"] == "active"

    # Simulate past timestamp > timeout
    old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=20)).isoformat()
    sess_file = ws / ".ai-orchestration" / "sessions" / f"{sid}.json"
    data = json.loads(sess_file.read_text(encoding="utf-8"))
    data["last_seen"] = old_time
    sess_file.write_text(json.dumps(data), encoding="utf-8")

    # Should now be reported as stale
    s_stale = get_session(ws, sid, stale_timeout_sec=10.0)
    assert s_stale["status"] == "stale"

    # List sessions filter by status=stale
    stale_list = list_sessions(ws, status="stale", stale_timeout_sec=10.0)
    assert len(stale_list) == 1
    assert stale_list[0]["session_id"] == sid

    # Heartbeat updates last_seen and restores status
    hb = heartbeat_session(ws, sid)
    assert hb["status"] == "active"
    s_restored = get_session(ws, sid, stale_timeout_sec=10.0)
    assert s_restored["status"] == "active"


# ---------------------------------------------------------------------------
# Monotonic Cursor Tests
# ---------------------------------------------------------------------------

def test_monotonic_cursor_advance(ws: pathlib.Path):
    """Test cursor advances monotonically and rejects backwards movement."""
    s = register_session(ws, tool="claude", cursor=5)
    sid = s["session_id"]

    assert get_cursor(ws, session_id=sid) == 5

    # Advance to 10
    c1 = advance_cursor(ws, seq=10, session_id=sid)
    assert c1 == 10
    assert get_cursor(ws, session_id=sid) == 10

    # Advance to 20
    c2 = advance_cursor(ws, seq=20, session_id=sid)
    assert c2 == 20
    assert get_cursor(ws, session_id=sid) == 20

    # Same cursor is allowed
    c_same = advance_cursor(ws, seq=20, session_id=sid)
    assert c_same == 20

    # Moving backwards must raise ValueError
    with pytest.raises(ValueError, match="Cursor can only advance monotonically"):
        advance_cursor(ws, seq=15, session_id=sid)

    # Remains 20
    assert get_cursor(ws, session_id=sid) == 20


def test_cursor_per_role_e2(ws: pathlib.Path):
    """Test cursor advance on a role advances orchestrator.json and current session."""
    s = register_session(ws, tool="claude", role="orchestrator", cursor=0)
    sid = s["session_id"]

    # Advance via role parameter
    adv = advance_cursor(ws, seq=55, role="orchestrator")
    assert adv == 55

    # Both role and session cursor are updated
    assert get_cursor(ws, role="orchestrator") == 55
    assert get_cursor(ws, session_id=sid) == 55

    # Regressing role cursor is refused
    with pytest.raises(ValueError, match="Cursor can only advance monotonically"):
        advance_cursor(ws, seq=40, role="orchestrator")


# ---------------------------------------------------------------------------
# Subscriptions and Pending Work Tests (§2)
# ---------------------------------------------------------------------------

def test_subscriptions_matching():
    """Test subscription pattern matcher."""
    assert matches_subscription({"type": "question.asked"}, ["*"])
    assert matches_subscription({"type": "question.asked"}, ["question.*"])
    assert matches_subscription({"type": "question.answered"}, ["question.*"])
    assert not matches_subscription({"type": "task.transitioned"}, ["question.*"])
    assert matches_subscription({"type": "task.transitioned"}, ["task.transitioned"])
    assert matches_subscription({"type": "any", "subject": "T012"}, ["subject:T012"])
    assert not matches_subscription({"type": "any", "subject": "T013"}, ["subject:T012"])


def test_pending_work_filtering(ws: pathlib.Path):
    """Test get_pending_work returns events matching subscriptions or origin_session."""
    sess = register_session(
        ws,
        tool="claude",
        subscriptions=["question.*"],
        cursor=0,
    )
    sid = sess["session_id"]

    # Emit events
    emit(ws, "task.transitioned", {"task": "T001"}, subject="T001")
    emit(ws, "question.asked", {"question": "Q001"}, subject="Q001")
    emit(ws, "run.finished", {"run": "R001"}, subject="R001", origin_session=sid)

    pending = get_pending_work(ws, sid)
    # Events matching:
    # 1. question.asked (matched subscription question.*)
    # 2. run.finished (matched origin_session == sid)
    # Note: session.registered was seq 1, cursor was 0 so it also had origin_session=sid
    pending_types = [p["type"] for p in pending]
    assert "question.asked" in pending_types
    assert "run.finished" in pending_types
    assert "task.transitioned" not in pending_types

    # Advance cursor past the events
    latest_seq = max(int(p["seq"]) for p in pending)
    advance_cursor(ws, seq=latest_seq, session_id=sid)

    # Now pending should be empty
    pending_after = get_pending_work(ws, sid)
    assert len(pending_after) == 0


# ---------------------------------------------------------------------------
# Deregister Tests
# ---------------------------------------------------------------------------

def test_deregister_session(ws: pathlib.Path):
    """Test session deregistration updates status, records retired metadata, and emits event."""
    sess = register_session(ws, tool="kilo", role="orchestrator")
    sid = sess["session_id"]

    dreg = deregister_session(ws, sid, reason="shutdown")
    assert dreg["status"] == "deregistered"
    assert dreg["retired"]["reason"] == "shutdown"
    assert dreg["retired"]["at"]

    # Check orchestrator.json status
    orch_holder = get_role_holder(ws, "orchestrator")
    assert orch_holder is not None
    assert orch_holder["status"] == "deregistered"

    # Verify event emitted
    evs = read_events(ws)
    dreg_evs = [e for e in evs if e["type"] == "session.deregistered"]
    assert len(dreg_evs) == 1
    assert dreg_evs[0]["subject"] == sid
    assert dreg_evs[0]["payload"]["reason"] == "shutdown"


# ---------------------------------------------------------------------------
# Concurrency Tests (Processes & Heartbeats)
# ---------------------------------------------------------------------------

def _heartbeat_worker(ws_str: str, sid: str, count: int, success_counter: multiprocessing.Value):
    ws_path = pathlib.Path(ws_str)
    for _ in range(count):
        try:
            heartbeat_session(ws_path, sid)
            time.sleep(0.005)
        except Exception:
            return
    with success_counter.get_lock():
        success_counter.value += 1


def test_concurrent_heartbeats_multiprocess(ws: pathlib.Path):
    """Test concurrent heartbeats from multiple operating system processes."""
    sess = register_session(ws, tool="claude")
    sid = sess["session_id"]

    num_processes = 6
    heartbeats_per_process = 15
    counter = multiprocessing.Value("i", 0)

    processes = [
        multiprocessing.Process(
            target=_heartbeat_worker,
            args=(str(ws), sid, heartbeats_per_process, counter),
        )
        for _ in range(num_processes)
    ]

    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=15.0)

    assert counter.value == num_processes

    # Session file must be completely valid JSON and active
    final_data = get_session(ws, sid)
    assert final_data["status"] == "active"
    assert final_data["last_seen"]


# ---------------------------------------------------------------------------
# CLI Tests via bin/ai-orch
# ---------------------------------------------------------------------------

def test_cli_sessions_lifecycle(ws: pathlib.Path):
    """Test CLI commands: register, heartbeat, list, show, cursor, deregister."""
    # Register
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "sessions",
            "register",
            "--tool",
            "codex",
            "--kind",
            "headless",
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    reg_data = json.loads(res.stdout)
    sid = reg_data["session_id"]
    assert sid
    assert reg_data["tool"] == "codex"

    # Heartbeat
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "sessions",
            "heartbeat",
            sid,
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    hb_data = json.loads(res.stdout)
    assert hb_data["session_id"] == sid

    # List
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "sessions",
            "list",
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    list_data = json.loads(res.stdout)
    assert any(s["session_id"] == sid for s in list_data)

    # Show
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "sessions",
            "show",
            sid,
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    show_data = json.loads(res.stdout)
    assert show_data["session_id"] == sid
    assert show_data["status"] == "active"

    # Cursor advance
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "sessions",
            "cursor",
            sid,
            "--seq",
            "77",
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    cur_data = json.loads(res.stdout)
    assert cur_data["cursor"] == 77

    # Cursor read
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "sessions",
            "cursor",
            sid,
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    cur_data2 = json.loads(res.stdout)
    assert cur_data2["cursor"] == 77

    # Deregister via alias "end"
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "session",
            "end",
            sid,
            "--reason",
            "task_complete",
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    dreg_data = json.loads(res.stdout)
    assert dreg_data["status"] == "deregistered"
    assert dreg_data["retired"]["reason"] == "task_complete"


def test_19_4_session_records_include_host_and_backward_compat(
    ws: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Task 19.4: session records and role files include host; legacy sessions without host remain valid."""
    cfg_file = tmp_path / "orchestration.toml"
    cfg_file.write_text('[host]\nid = "alf_ubuntu"\n', encoding="utf-8")
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(cfg_file))

    s1 = register_session(ws, tool="claude", role="orchestrator")
    assert s1["host"] == "alf_ubuntu"
    holder = get_role_holder(ws, role="orchestrator")
    assert holder is not None
    assert holder["host"] == "alf_ubuntu"
    assert holder["current"]["host"] == "alf_ubuntu"

    s2 = register_session(ws, tool="kilo", host="mac")
    assert s2["host"] == "mac"
    assert [s["session_id"] for s in list_sessions(ws, host="mac")] == [s2["session_id"]]

    # Legacy session file without 'host' remains valid
    legacy_path = ws / ".ai-orchestration" / "sessions" / "legacy-sess.json"
    legacy_data = dict(s2)
    legacy_data["session_id"] = "legacy-sess"
    legacy_data.pop("host", None)
    legacy_path.write_text(json.dumps(legacy_data), encoding="utf-8")
    loaded_legacy = get_session(ws, "legacy-sess")
    assert loaded_legacy["session_id"] == "legacy-sess"
    assert "legacy-sess" in [s["session_id"] for s in list_sessions(ws)]

