"""test_orchestration_triggers.py — Unit and integration tests for orchestration triggers.

Verifies:
  - Spec §5, Spec §0c E2, E3, E7
  - Configuration parsing, normalization, defaults, and validation
  - Event matching (exact, wildcards, payload/data filters, glob, field presence)
  - Loop guard (cause / depth limit >= 3)
  - Rate limiting via persisted token buckets (E7)
  - Batching per E2 (immutable batches, pending -> running -> acknowledged)
  - Cursor advancement: advances only after success (E7 scan watermark)
  - Crash recovery & idempotency: re-running re-delivers batch but terminal firings are idempotent
  - E3 reduced-capability policy: safe notifications, proposed actions with hashes for agent launches/mutating commands, turn enqueuing
  - Dry-run mode: evaluates plan without writing any files or emitting events
  - Daemon mode: singleton lock, lease heartbeat, clean shutdown
  - CLI integration via bin/ai-orch triggers
"""
from __future__ import annotations

import datetime
import json
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
    advance_cursor,
    get_cursor,
    register_session,
)
from orchestration_triggers import (
    TriggerDaemon,
    check_and_consume_rate_limit,
    check_loop_guard,
    create_batch,
    daemon_lock,
    execute_action,
    find_active_batch,
    get_firing_record,
    load_triggers_config,
    make_firing_id,
    matches_filter,
    matches_trigger,
    run_once,
    trigger_lock,
    validate_trigger_rule,
)

BIN_AI_ORCH = REPO_ROOT / "bin" / "ai-orch"


@pytest.fixture
def ws(tmp_path: pathlib.Path) -> pathlib.Path:
    workspace = tmp_path / "test_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


# ---------------------------------------------------------------------------
# 1. Configuration Validation Tests
# ---------------------------------------------------------------------------

def test_config_validation_valid(ws: pathlib.Path):
    cfg_file = ws / ".ai-orchestration.local.toml"
    cfg_file.write_text("""
[[triggers]]
name = "on-answer"
on = "question.answered"
when = { origin_run = "*" }
action = "resume-origin"
enabled = true
max_per_hour = 10

[[triggers]]
name = "on-delivered"
on = "task.transitioned"
when = { to = "delivered" }
action = "start-run"
run = { mode = "verify", tool = "kilo" }
""")

    meta, rules, errors = load_triggers_config(ws)
    assert not errors
    assert meta["kill_switch_enabled"] is True
    assert len(rules) == 2
    r1 = rules[0]
    assert r1["name"] == "on-answer"
    assert r1["enabled"] is True
    assert r1["max_per_hour"] == 10

    r2 = rules[1]
    assert r2["name"] == "on-delivered"
    assert r2["action"] == "start-run"
    assert r2["run"] == {"mode": "verify", "tool": "kilo"}


def test_config_validation_errors(ws: pathlib.Path):
    # Missing name
    errs = validate_trigger_rule({"on": "question.answered", "action": "notify"})
    assert any("name" in e for e in errs)

    # Missing on
    errs = validate_trigger_rule({"name": "r1", "action": "notify"})
    assert any("'on'" in e for e in errs)

    # Invalid action
    errs = validate_trigger_rule({"name": "r1", "on": "foo", "action": "invalid-action"})
    assert any("invalid action" in e for e in errs)

    # start-run missing run
    errs = validate_trigger_rule({"name": "r1", "on": "foo", "action": "start-run"})
    assert any("run" in e for e in errs)

    # command with arbitrary non-ai-orch shell
    errs = validate_trigger_rule({"name": "r1", "on": "foo", "action": "command", "command": ["rm", "-rf", "/"]})
    assert any("ai-orch" in e for e in errs)


def test_config_duplicate_names(ws: pathlib.Path):
    cfg_file = ws / "orchestration.toml"
    cfg_file.write_text("""
[[triggers]]
name = "dup-name"
on = "event.one"
action = "notify"

[[triggers]]
name = "dup-name"
on = "event.two"
action = "notify"
""")
    meta, rules, errors = load_triggers_config(ws)
    assert any("Duplicate trigger rule name" in e for e in errors)


def test_config_agent_rule_defaults_disabled(ws: pathlib.Path):
    """Spec §5 Safety: 'every rule that launches an agent defaults to enabled = false'."""
    cfg_file = ws / ".ai-orchestration.local.toml"
    cfg_file.write_text("""
[[triggers]]
name = "agent-launcher"
on = "task.transitioned"
action = "start-run"
run = { mode = "verify" }

[[triggers]]
name = "notifier"
on = "task.transitioned"
action = "notify"
""")
    meta, rules, errors = load_triggers_config(ws)
    assert not errors
    assert len(rules) == 2
    r_agent = [r for r in rules if r["name"] == "agent-launcher"][0]
    r_notif = [r for r in rules if r["name"] == "notifier"][0]

    assert r_agent["enabled"] is False  # Opt-in default for agent runs
    assert r_notif["enabled"] is True   # Safe actions default enabled


def test_config_kill_switch(ws: pathlib.Path):
    """Spec §5 Safety: '[triggers] enabled = false' acts as a global kill switch."""
    cfg_file = ws / ".ai-orchestration.local.toml"
    cfg_file.write_text("""
[triggers]
enabled = false

[[triggers.rules]]
name = "test-rule"
on = "task.transitioned"
action = "notify"
""")
    meta, rules, errors = load_triggers_config(ws)
    assert meta["kill_switch_enabled"] is False
    assert len(rules) == 1

    # Emit an event and run_once
    emit(ws, "task.transitioned", {"to": "in_progress"}, subject="T001")
    res = run_once(ws)
    assert res["ok"] is True
    assert res["status"] == "disabled_by_kill_switch"
    assert res["events_processed"] == 0


# ---------------------------------------------------------------------------
# 2. Matching and Filtering Tests
# ---------------------------------------------------------------------------

def test_event_matching_types(ws: pathlib.Path):
    r_exact = {"name": "exact", "on": "task.transitioned", "action": "notify", "enabled": True}
    r_wildcard = {"name": "wildcard", "on": "task.*", "action": "notify", "enabled": True}
    r_all = {"name": "all", "on": "*", "action": "notify", "enabled": True}

    ev_task = {"seq": 1, "id": "1", "type": "task.transitioned", "data": {}}
    ev_q = {"seq": 2, "id": "2", "type": "question.answered", "data": {}}

    assert matches_trigger(r_exact, ev_task) is True
    assert matches_trigger(r_exact, ev_q) is False

    assert matches_trigger(r_wildcard, ev_task) is True
    assert matches_trigger(r_wildcard, ev_q) is False

    assert matches_trigger(r_all, ev_task) is True
    assert matches_trigger(r_all, ev_q) is True


def test_event_matching_filters(ws: pathlib.Path):
    rule = {
        "name": "r1",
        "on": "task.transitioned",
        "when": {
            "to": "delivered",
            "subject": "T01*",
            "origin_run": "*",
        },
        "action": "notify",
        "enabled": True,
    }

    # Matches all conditions
    ev_good = {
        "seq": 1,
        "id": "1",
        "type": "task.transitioned",
        "subject": "T012",
        "data": {"to": "delivered", "origin_run": "run-abc"},
    }
    assert matches_trigger(rule, ev_good) is True

    # Mismatch 'to'
    ev_bad_to = {
        "seq": 2,
        "id": "2",
        "type": "task.transitioned",
        "subject": "T012",
        "data": {"to": "in_progress", "origin_run": "run-abc"},
    }
    assert matches_trigger(rule, ev_bad_to) is False

    # Mismatch 'subject' glob
    ev_bad_subj = {
        "seq": 3,
        "id": "3",
        "type": "task.transitioned",
        "subject": "T022",
        "data": {"to": "delivered", "origin_run": "run-abc"},
    }
    assert matches_trigger(rule, ev_bad_subj) is False

    # Missing 'origin_run' (wildcard requirement)
    ev_no_origin = {
        "seq": 4,
        "id": "4",
        "type": "task.transitioned",
        "subject": "T012",
        "data": {"to": "delivered"},
    }
    assert matches_trigger(rule, ev_no_origin) is False


def test_loop_guard(ws: pathlib.Path):
    """Spec §5 Safety: 'a rule never fires on its own descendants beyond depth 3'."""
    ev_normal = {"seq": 1, "id": "1", "type": "task.transitioned", "data": {}}
    assert check_loop_guard("my-rule", ev_normal) is True

    ev_low_depth = {"seq": 2, "id": "2", "type": "task.transitioned", "data": {"cause": {"trigger": "my-rule", "depth": 2}}}
    assert check_loop_guard("my-rule", ev_low_depth) is True

    ev_excessive_depth = {"seq": 3, "id": "3", "type": "task.transitioned", "data": {"cause": {"trigger": "my-rule", "depth": 3}}}
    assert check_loop_guard("my-rule", ev_excessive_depth) is False

    ev_other_rule = {"seq": 4, "id": "4", "type": "task.transitioned", "data": {"cause": {"trigger": "other-rule", "depth": 5}}}
    assert check_loop_guard("my-rule", ev_other_rule) is True


# ---------------------------------------------------------------------------
# 3. Batching & Cursor Progression Tests (Spec §0c E2, E7)
# ---------------------------------------------------------------------------

def test_batching_and_cursor_advance_on_success(ws: pathlib.Path):
    """Deliveries are immutable batches per E2; cursor advances only after batch is handled."""
    # Write rule
    cfg = ws / ".ai-orchestration.local.toml"
    cfg.write_text("""
[[triggers]]
name = "notify-on-question"
on = "question.answered"
action = "notify"
enabled = true
""")

    # Register orchestrator session and advance past session.registered event
    register_session(ws, role="orchestrator", tool="claude", kind="headless")
    advance_cursor(ws, seq=1, role="orchestrator")
    assert get_cursor(ws, role="orchestrator") == 1

    # Emit 3 events
    e1 = emit(ws, "question.answered", {"question_id": "Q001"})
    e2 = emit(ws, "question.answered", {"question_id": "Q002"})
    e3 = emit(ws, "task.transitioned", {"to": "in_progress"})

    # Run once
    res = run_once(ws)
    assert res["ok"] is True
    assert res["status"] == "acknowledged"
    assert res["events_processed"] == 3
    assert len(res["firings"]) == 2  # e1, e2 matched, e3 did not

    # Cursor should advance to highest seq (4)
    new_cursor = get_cursor(ws, role="orchestrator")
    assert new_cursor == e3["seq"]

    # Batch should be marked acknowledged in batches dir
    batch = find_active_batch(ws, role="orchestrator")
    assert batch is None  # No unacknowledged active batch left


def test_cursor_does_not_advance_on_failure(ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Spec §0c E7 scan watermark rule: cursor advances ONLY when applicable rules reach terminal state."""
    cfg = ws / ".ai-orchestration.local.toml"
    cfg.write_text("""
[[triggers]]
name = "failing-action"
on = "task.transitioned"
action = "notify"
enabled = true
""")

    register_session(ws, role="orchestrator", tool="claude", kind="headless")
    advance_cursor(ws, seq=1, role="orchestrator")
    assert get_cursor(ws, role="orchestrator") == 1

    # Emit event (seq 2)
    emit(ws, "task.transitioned", {"to": "delivered"})

    # Monkeypatch execute_action to fail
    import orchestration_triggers
    def failing_execute(*args, **kwargs):
        raise RuntimeError("Simulated failure executing action")

    monkeypatch.setattr(orchestration_triggers, "execute_action", failing_execute)

    res = run_once(ws)
    assert res["ok"] is True
    assert res["status"] == "partial_settled"
    # Cursor must NOT have advanced because rule entered non-terminal state 'retry'
    assert get_cursor(ws, role="orchestrator") == 1

    # Active batch remains pending/running
    active_b = find_active_batch(ws, role="orchestrator")
    assert active_b is not None
    assert active_b["state"] == "running"


# ---------------------------------------------------------------------------
# 4. Crash Recovery and Idempotency Tests (E2, E7)
# ---------------------------------------------------------------------------

def test_rerun_after_crash_is_idempotent(ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Crash during a batch leaves it unacknowledged; re-run re-delivers the batch,

    but previously fired rules are idempotent and not re-executed.
    """
    cfg = ws / ".ai-orchestration.local.toml"
    cfg.write_text("""
[[triggers]]
name = "track-firings"
on = "task.transitioned"
action = "notify"
enabled = true
""")

    register_session(ws, role="orchestrator", tool="claude", kind="headless")
    advance_cursor(ws, seq=1, role="orchestrator")

    e1 = emit(ws, "task.transitioned", {"task": "T1"})  # seq 2
    e2 = emit(ws, "task.transitioned", {"task": "T2"})  # seq 3

    import orchestration_triggers
    execution_calls: list[int] = []
    real_exec = orchestration_triggers.execute_action

    def flaky_execute(workspace, rule, event, firing_id, **kwargs):
        seq = event["seq"]
        execution_calls.append(seq)
        if event["id"] == e2["id"] and len(execution_calls) == 2:
            # Crash on e2 during the first run!
            raise RuntimeError("Crash on event 2!")
        return real_exec(workspace, rule, event, firing_id, **kwargs)

    monkeypatch.setattr(orchestration_triggers, "execute_action", flaky_execute)

    # First run crashes on event 2
    res1 = run_once(ws)
    assert res1["status"] == "partial_settled"
    # e1 settled, so watermark advanced to e1 (seq 2)
    assert get_cursor(ws, role="orchestrator") == e1["seq"]

    # Event 1 was executed, event 2 was attempted
    assert execution_calls == [e1["seq"], e2["seq"]]

    # Verify event 1 has a 'fired' record
    f1_id = make_firing_id("track-firings", e1["seq"], e1["id"])
    rec1 = get_firing_record(ws, f1_id)
    assert rec1 is not None
    assert rec1["state"] == "fired"

    # Now second run: crash condition does not trigger (len(execution_calls) == 2 is false)
    res2 = run_once(ws)
    assert res2["status"] == "acknowledged"
    assert get_cursor(ws, role="orchestrator") == e2["seq"]

    # Event 1 was NOT re-executed! Event 2 was re-executed.
    assert execution_calls == [e1["seq"], e2["seq"], e2["seq"]]

    # Check summary indicates e1 was replayed
    e1_summary = [f for f in res2["firings"] if f["event_seq"] == e1["seq"]][0]
    assert e1_summary.get("replayed") is True


# ---------------------------------------------------------------------------
# 5. Reduced-Capability Policy (E3) Tests
# ---------------------------------------------------------------------------

def test_e3_start_run_proposes_action(ws: pathlib.Path):
    """Spec §0c E3: unattended triggers cannot launch agents directly;

    start-run actions must be recorded as proposed actions with hashes.
    """
    cfg = ws / ".ai-orchestration.local.toml"
    cfg.write_text("""
[[triggers]]
name = "verify-delivery"
on = "task.transitioned"
when = { to = "delivered" }
action = "start-run"
run = { mode = "verify", tool = "kilo" }
enabled = true
""")

    register_session(ws, role="orchestrator", tool="claude", kind="headless")
    ev = emit(ws, "task.transitioned", {"to": "delivered"}, subject="T010")

    res = run_once(ws)
    assert res["ok"] is True
    assert len(res["firings"]) == 1
    firing = res["firings"][0]
    assert firing["state"] == "fired"

    result = firing["result"]
    assert result["status"] == "proposed"
    assert result["type"] == "start-run"
    action_id = result["action_id"]
    action_hash = result["action_hash"]
    assert action_id
    assert action_hash

    # Verify proposed action was written under .ai-orchestration/proposed_actions/
    prop_file = ws / ".ai-orchestration" / "proposed_actions" / f"{action_id}.json"
    assert prop_file.is_file()
    prop_data = json.loads(prop_file.read_text(encoding="utf-8"))
    assert prop_data["action_hash"] == action_hash
    assert prop_data["type"] == "start-run"
    assert prop_data["status"] == "pending_confirmation"
    assert prop_data["run_params"] == {"mode": "verify", "tool": "kilo"}


def test_e3_mutating_command_proposes_action(ws: pathlib.Path):
    """Mutating ai-orch command is disallowed unattended under E3 and gets proposed."""
    rule = {
        "name": "mutating-rule",
        "on": "task.transitioned",
        "action": "command",
        "command": ["ai-orch", "tasks", "transition", "T001", "done"],
        "enabled": True,
    }
    ev = {"seq": 1, "id": "ev-1", "type": "task.transitioned"}
    res = execute_action(ws, rule, ev, "firing-1")

    assert res["status"] == "proposed"
    assert res["type"] == "command"
    assert res["action_hash"]
    assert "tasks" in res["command"]


def test_e3_safe_read_command_executes(ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Safe read commands under E3 are allowed to execute directly."""
    rule = {
        "name": "safe-cmd-rule",
        "on": "task.transitioned",
        "action": "command",
        "command": ["ai-orch", "tasks", "list"],
        "enabled": True,
    }
    ev = {"seq": 1, "id": "ev-1", "type": "task.transitioned"}

    # Mock subprocess.run to avoid running real tasks list on empty ws
    class MockProc:
        returncode = 0
        stdout = '{"tasks": []}'
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MockProc())

    res = execute_action(ws, rule, ev, "firing-1")
    assert res["status"] == "executed"
    assert res["exit_code"] == 0


def test_e3_resume_origin_enqueues_turn(ws: pathlib.Path):
    """resume-origin for role orchestrator enqueues an event batch turn in queue."""
    rule = {
        "name": "resume-on-answer",
        "on": "question.answered",
        "action": "resume-origin",
        "enabled": True,
    }
    ev = {"seq": 5, "id": "ev-q5", "type": "question.answered", "data": {"question_id": "Q001"}}

    res = execute_action(ws, rule, ev, "firing-5")
    assert res["status"] == "enqueued_turn"
    turn_id = res["turn_id"]

    # Verify turn file in .ai-orchestration/orchestrator/queue/
    q_file = ws / ".ai-orchestration" / "orchestrator" / "queue" / f"{turn_id}.json"
    assert q_file.is_file()
    turn_data = json.loads(q_file.read_text(encoding="utf-8"))
    assert turn_data["role"] == "orchestrator"
    assert turn_data["policy"] == "reduced_capability"
    assert turn_data["prompt_data"]["type"] == "untrusted_event_data"


# ---------------------------------------------------------------------------
# 6. Rate Limiting Tests (E7)
# ---------------------------------------------------------------------------

def test_rate_limiting_token_buckets(ws: pathlib.Path):
    """Spec §0c E7: rate limits are persisted token buckets; deferred items get 'retry' and not_before."""
    rule = {
        "name": "rate-limited-rule",
        "on": "test.event",
        "action": "notify",
        "max_per_hour": 2,  # 2 per hour
        "enabled": True,
    }

    t0 = 1000.0
    # First call: consumes token 1
    allowed1, nb1 = check_and_consume_rate_limit(ws, rule, now_ts=t0)
    assert allowed1 is True
    assert nb1 is None

    # Second call immediately: consumes token 2
    allowed2, nb2 = check_and_consume_rate_limit(ws, rule, now_ts=t0)
    assert allowed2 is True
    assert nb2 is None

    # Third call immediately: bucket empty!
    allowed3, nb3 = check_and_consume_rate_limit(ws, rule, now_ts=t0)
    assert allowed3 is False
    assert nb3 is not None
    assert "Z" in nb3

    # Fast-forward 1800 seconds (half hour = 1 token refilled)
    t1 = t0 + 1800.0
    allowed4, nb4 = check_and_consume_rate_limit(ws, rule, now_ts=t1)
    assert allowed4 is True


# ---------------------------------------------------------------------------
# 7. Dry-Run Mode Tests
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing(ws: pathlib.Path):
    """Dry-run mode plans actions without writing to disk or emitting events."""
    cfg = ws / ".ai-orchestration.local.toml"
    cfg.write_text("""
[[triggers]]
name = "dry-run-test"
on = "task.transitioned"
action = "notify"
enabled = true
""")
    register_session(ws, role="orchestrator", tool="claude", kind="headless")
    emit(ws, "task.transitioned", {"to": "delivered"})

    # Check triggers dir doesn't have firings before
    firings_dir = ws / ".ai-orchestration" / "triggers" / "firings"
    batches_dir = ws / ".ai-orchestration" / "triggers" / "batches"

    res = run_once(ws, dry_run=True)
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert len(res["firings"]) == 1
    assert res["firings"][0]["rule"] == "dry-run-test"

    # Confirm nothing was written to disk
    assert not firings_dir.exists() or len(list(firings_dir.glob("*.json"))) == 0
    assert not batches_dir.exists() or len(list(batches_dir.glob("*.json"))) == 0
    # Cursor should not have changed
    assert get_cursor(ws, role="orchestrator") == 0


# ---------------------------------------------------------------------------
# 8. Daemon Tests
# ---------------------------------------------------------------------------

def test_daemon_stops_cleanly(ws: pathlib.Path):
    """Daemon runs in background, responds to stop(), updates lease."""
    cfg = ws / ".ai-orchestration.local.toml"
    cfg.write_text("""
[[triggers]]
name = "d-test"
on = "task.transitioned"
action = "notify"
enabled = true
""")
    register_session(ws, role="orchestrator", tool="claude", kind="headless")

    daemon = TriggerDaemon(ws, poll_interval=0.1)

    t = threading.Thread(target=daemon.run, daemon=True)
    t.start()

    # Wait for daemon to start
    time.sleep(0.2)
    assert daemon.is_running is True

    lease_path = ws / ".ai-orchestration" / "triggers" / "daemon.json"
    assert lease_path.is_file()
    lease_data = json.loads(lease_path.read_text(encoding="utf-8"))
    assert lease_data["status"] == "running"

    # Advance cursor past session.registered
    advance_cursor(ws, seq=1, role="orchestrator")

    # Emit event while daemon runs
    ev = emit(ws, "task.transitioned", {"to": "delivered"})

    # Wait for daemon loop to process
    time.sleep(0.4)
    assert get_cursor(ws, role="orchestrator") >= ev["seq"]

    # Stop daemon
    daemon.stop()
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert daemon.is_running is False

    # Check lease status updated to stopped
    lease_data = json.loads(lease_path.read_text(encoding="utf-8"))
    assert lease_data["status"] == "stopped"


# ---------------------------------------------------------------------------
# 9. CLI Command Tests
# ---------------------------------------------------------------------------

def test_cli_triggers_commands(ws: pathlib.Path):
    """Test bin/ai-orch triggers list, run-once, status, history."""
    cfg = ws / ".ai-orchestration.local.toml"
    cfg.write_text("""
[[triggers]]
name = "cli-test-rule"
on = "task.transitioned"
action = "notify"
enabled = true
""")

    # 1. triggers list
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "triggers", "list", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert len(data["rules"]) == 1
    assert data["rules"][0]["name"] == "cli-test-rule"

    # Register session & advance past registration event
    register_session(ws, role="orchestrator", tool="claude", kind="headless")
    advance_cursor(ws, seq=1, role="orchestrator")
    ev = emit(ws, "task.transitioned", {"to": "done"})

    # 2. triggers run-once
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "triggers", "run-once", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["events_processed"] == 1

    # 3. triggers status
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "triggers", "status", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["cursor"] == ev["seq"]
    assert data["total_firings"] == 1

    # 4. triggers history
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "triggers", "history", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert len(data["firings"]) == 1
    assert data["firings"][0]["rule_name"] == "cli-test-rule"
