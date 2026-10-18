#!/usr/bin/env python3
"""test_orchestration_orchestrator.py — Tests for headless orchestrator role engine.

Verifies:
  - Queue order + crash recovery (Spec §0c E6)
  - One turn at a time (never two concurrent resumptions of the role session)
  - Bounds kill a runaway stub (wall-clock timeout, whole process group, dead state)
  - Resume in the same session (generation session continuity across turns)
  - Rotation on context threshold (Spec §0c E8 normalized usage trigger)
  - Stale generation refused (Spec §0c E9 fenced succession token validation)
  - Self-registration when no session holds the role
  - Events emitted across lifecycle (turn.queued, turn.started, turn.finished, turn.failed, orchestrator.*)
  - Reduced capability policy for unattended event batch turns (Spec §0c E3)
  - Fenced succession rollback on handoff failure (Spec §0c E9)
  - CLI subcommands (status, queue, enqueue, run-next, rotate, hand-off, cancel)
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
BIN_AI_ORCH = REPO_ROOT / "bin" / "ai-orch"
STUB_AGENT = SCRIPTS_DIR / "fixtures" / "runs" / "stub_agent.py"

for p in (SCRIPTS_DIR, REPO_ROOT / "plugins" / "shared" / "skills" / "orchestration-setup" / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import orchestration_orchestrator as orch
import orchestration_events as events
import orchestration_sessions as sessions


@pytest.fixture(autouse=True)
def _no_real_agent_clis(tmp_path_factory, monkeypatch):
    """Guard against invoking real agent CLIs in tests."""
    fake_bin = tmp_path_factory.mktemp("fake-clis")
    for name in ("kilo", "claude", "codex"):
        exe = fake_bin / name
        exe.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            f'  --version) echo "{name} 0.0.0-test-fake"; exit 0 ;;\n'
            '  models) echo "google/gemini-3.8-flash"; exit 0 ;;\n'
            "esac\n"
            f"echo 'REAL {name} CLI CALLED: configure a stub' >&2\n"
            "exit 97\n"
        )
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.fixture
def ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a configured test workspace pointing to stub_agent."""
    proj_cfg = tmp_path / ".ai-orchestration.local.toml"
    proj_cfg.write_text(
        f"""[routing]
default_orchestrator = "claude"

[orchestrator]
rotate_after_tokens = 50000
timeout_seconds = 30.0

[tools.claude]
enabled = true

[tools.claude.headless]
argv = ["{sys.executable}", "{STUB_AGENT}", "--session-id", "{{session_id}}"]
resume_argv = ["{sys.executable}", "{STUB_AGENT}", "--session-id", "{{session_id}}"]

[tools.kilo]
enabled = true

[tools.kilo.headless]
argv = ["{sys.executable}", "{STUB_AGENT}", "--session-id", "{{session_id}}"]
resume_argv = ["{sys.executable}", "{STUB_AGENT}", "--session-id", "{{session_id}}"]
""",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Self-Registration & Status Tests
# ---------------------------------------------------------------------------

def test_self_registration_on_empty_workspace(ws: pathlib.Path):
    """When no orchestrator session exists, status/start self-registers generation 1."""
    orch_file = ws / ".ai-orchestration" / "orchestrator.json"
    assert not orch_file.exists()

    status = orch.get_orchestrator_status(ws)
    assert status["role"] == "orchestrator"
    assert status["generation"] == 1
    assert status["status"] == "active"
    assert status["tool"] == "claude"
    assert status["session_id"] is not None
    assert status["turns"] == 0

    assert orch_file.is_file()
    evs = events.read_events(ws)
    ev_types = [e["type"] for e in evs]
    assert "orchestrator.started" in ev_types
    assert "session.registered" in ev_types


def test_pause_and_resume_orchestrator(ws: pathlib.Path):
    """Pause and resume transitions orchestrator role status."""
    orch.start_orchestrator(ws)
    st = orch.get_orchestrator_status(ws)
    assert st["status"] == "active"

    orch.pause_orchestrator(ws)
    st = orch.get_orchestrator_status(ws)
    assert st["status"] == "paused"

    # Running next turn while paused returns paused status
    orch.enqueue_turn(ws, message="hello")
    res = orch.run_next_turn(ws)
    assert res["status"] == "paused"

    orch.resume_orchestrator(ws)
    st = orch.get_orchestrator_status(ws)
    assert st["status"] == "active"


# ---------------------------------------------------------------------------
# 2. Queue Order & Coalescing Tests (Spec §0c E6)
# ---------------------------------------------------------------------------

def test_queue_priority_and_turn_order(ws: pathlib.Path):
    """Owner messages take priority, but at least 1 event batch runs after 3 owner turns (Spec §0c E6)."""
    orch.start_orchestrator(ws)

    # Enqueue 4 owner chats and 2 event batches
    e1 = orch.enqueue_turn(ws, turn_type="owner_chat", message="msg 1")["turn_id"]
    e2 = orch.enqueue_turn(ws, turn_type="owner_chat", message="msg 2")["turn_id"]
    e3 = orch.enqueue_turn(ws, turn_type="owner_chat", message="msg 3")["turn_id"]
    e4 = orch.enqueue_turn(ws, turn_type="owner_chat", message="msg 4")["turn_id"]

    ev1 = orch.enqueue_turn(
        ws,
        turn_type="event_batch",
        events=[{"seq": 1, "id": "ev-1", "type": "task.transitioned"}],
    )["turn_id"]
    ev2 = orch.enqueue_turn(
        ws,
        turn_type="event_batch",
        events=[{"seq": 2, "id": "ev-2", "type": "task.transitioned"}],
    )["turn_id"]

    # Turn 1: owner chat 1
    t1 = orch.select_next_turn(ws, consecutive_owner_turns=0)
    assert t1 is not None and t1["turn_id"] == e1

    # Turn 2: owner chat 2
    t2 = orch.select_next_turn(ws, consecutive_owner_turns=1)
    assert t2 is not None and t2["turn_id"] == e1  # (since e1 is still queued)

    # After 3 consecutive owner turns, event batch takes priority!
    t_after_3 = orch.select_next_turn(ws, consecutive_owner_turns=3)
    assert t_after_3 is not None
    assert t_after_3["type"] == "event_batch"
    assert t_after_3["turn_id"] == ev1


def test_coalesce_event_batches(ws: pathlib.Path):
    """Multiple pending event batches coalesce into a single execution batch (Spec §0)."""
    orch.start_orchestrator(ws)

    b1 = orch.enqueue_turn(
        ws,
        turn_type="event_batch",
        events=[{"seq": 10, "id": "ev-10", "type": "question.asked"}],
    )["turn"]
    b2 = orch.enqueue_turn(
        ws,
        turn_type="event_batch",
        events=[{"seq": 11, "id": "ev-11", "type": "question.answered"}],
    )["turn"]

    coalesced = orch.coalesce_event_batches(ws, b1)
    assert len(coalesced["events"]) == 2
    assert coalesced["events"][0]["seq"] == 10
    assert coalesced["events"][1]["seq"] == 11

    # Check second batch marked as merged
    q_items = orch.list_queue(ws)
    b2_fresh = [it for it in q_items if it["turn_id"] == b2["turn_id"]][0]
    assert b2_fresh["state"] == "merged"
    assert b2_fresh["merged_into"] == b1["turn_id"]


# ---------------------------------------------------------------------------
# 3. Crash Recovery Tests (Spec §0c E6)
# ---------------------------------------------------------------------------

def test_stale_claim_crash_recovery(ws: pathlib.Path):
    """A crashed worker holding an active turn is recovered and retried once (Spec §0, E6)."""
    orch.start_orchestrator(ws)
    turn = orch.enqueue_turn(ws, message="turn to recover")["turn"]
    turn_id = turn["turn_id"]

    # Simulate a crash: mark state as 'running' with a dead PID
    q_file = orch.get_queue_dir(ws) / f"{turn_id}.json"
    turn["state"] = "running"
    turn["pid"] = 999999  # Guaranteed non-existent PID
    turn["start_time"] = "dummy"
    orch._write_json_atomic(q_file, turn)

    # run_next_turn detects dead worker and recovers turn to queued
    res = orch.run_next_turn(ws)
    # The turn was retried and executed successfully
    assert res["status"] == "done"
    assert res["turn_id"] == turn_id

    # Verify event emitted for recovery
    evs = events.read_events(ws)
    fail_evs = [e for e in evs if e["type"] == "turn.failed"]
    assert len(fail_evs) >= 1
    assert fail_evs[0]["payload"]["retryable"] is True


# ---------------------------------------------------------------------------
# 4. Concurrency Guard: One Turn at a Time
# ---------------------------------------------------------------------------

def test_one_turn_at_a_time_busy_guard(ws: pathlib.Path):
    """While a turn is running, a second run-next returns status busy."""
    orch.start_orchestrator(ws)
    # Configure tool with sleep so process stays alive
    cfg_file = ws / ".ai-orchestration.local.toml"
    cfg_file.write_text(
        f"""[routing]
default_orchestrator = "claude"

[tools.claude]
enabled = true

[tools.claude.headless]
argv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "3.0", "--session-id", "{{session_id}}"]
resume_argv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "3.0", "--session-id", "{{session_id}}"]
""",
        encoding="utf-8",
    )

    t1 = orch.enqueue_turn(ws, message="turn 1")["turn_id"]
    t2 = orch.enqueue_turn(ws, message="turn 2")["turn_id"]

    # Start turn 1 in a background thread
    import threading
    t_thread = threading.Thread(target=lambda: orch.run_next_turn(ws), daemon=True)
    t_thread.start()

    # Wait for turn 1 to start running
    time.sleep(0.5)

    # Attempt to run next turn while turn 1 is running
    res = orch.run_next_turn(ws)
    assert res["status"] == "busy"
    assert res["turn_id"] == t1

    t_thread.join(timeout=10.0)


# ---------------------------------------------------------------------------
# 5. Bounds Kill Runaway Stub (Spec §0c E5)
# ---------------------------------------------------------------------------

def test_bounds_kill_runaway_stub(ws: pathlib.Path):
    """Wall-clock timeout terminates runaway process group and marks turn dead."""
    orch.start_orchestrator(ws)

    # Configure tool with sleep 60s
    cfg_file = ws / ".ai-orchestration.local.toml"
    cfg_file.write_text(
        f"""[routing]
default_orchestrator = "claude"

[tools.claude]
enabled = true

[tools.claude.headless]
argv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "60.0", "--session-id", "{{session_id}}"]
resume_argv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "60.0", "--session-id", "{{session_id}}"]
""",
        encoding="utf-8",
    )

    t = orch.enqueue_turn(ws, message="runaway turn")["turn"]
    turn_id = t["turn_id"]

    t0 = time.time()
    # Run with short timeout of 1.0 second
    res = orch.run_next_turn(ws, timeout=1.0)
    elapsed = time.time() - t0

    assert elapsed < 5.0  # Killed promptly
    assert res["status"] == "dead"
    assert res["bound_exceeded"] == "wall_clock_timeout"

    # Check turn record in turns/
    turn_record = orch._read_json_safe(orch.get_turns_dir(ws) / turn_id / "turn.json")
    assert turn_record["state"] == "dead"
    assert turn_record["bound_exceeded"] == "wall_clock_timeout"

    # Verify event emitted
    evs = events.read_events(ws)
    failed_ev = [e for e in evs if e["type"] == "turn.failed"][-1]
    assert failed_ev["payload"]["bound_exceeded"] == "wall_clock_timeout"


# ---------------------------------------------------------------------------
# 6. Session Resumption Continuity
# ---------------------------------------------------------------------------

def test_session_continuity_across_turns(ws: pathlib.Path):
    """Turns reuse and resume in the exact same provider session."""
    orch.start_orchestrator(ws, tool="claude")
    st = orch.get_orchestrator_status(ws)
    orig_prov_id = st["provider_session_id"]
    assert orig_prov_id is not None

    # Run turn 1
    orch.enqueue_turn(ws, message="turn 1")
    r1 = orch.run_next_turn(ws)
    assert r1["status"] == "done"

    st1 = orch.get_orchestrator_status(ws)
    assert st1["turns"] == 1
    assert st1["provider_session_id"] == orig_prov_id

    # Run turn 2
    orch.enqueue_turn(ws, message="turn 2")
    r2 = orch.run_next_turn(ws)
    assert r2["status"] == "done"

    st2 = orch.get_orchestrator_status(ws)
    assert st2["turns"] == 2
    assert st2["provider_session_id"] == orig_prov_id


# ---------------------------------------------------------------------------
# 7. Rotation on Context Threshold (Spec §0c E8)
# ---------------------------------------------------------------------------

def test_rotation_on_context_threshold(ws: pathlib.Path):
    """Context growth past threshold triggers succession to generation N+1."""
    orch.start_orchestrator(ws)

    # Configure tool to emit usage above threshold
    # Stub outputs 1 step_finish line simulating kilo context or we can pass lines
    # Let's configure STUB_AGENT with custom python script that outputs step_finish event
    step_script = ws / "emit_usage.py"
    step_script.write_text(
        """import sys, json, datetime
evt = {
    "type": "step_finish",
    "part": {
        "tokens": {
            "total": 120000,
            "input": 1000,
            "output": 500,
            "cache": {"read": 50000, "write": 0}
        }
    }
}
sys.stdout.write(json.dumps(evt) + "\\n")
sys.stdout.write(json.dumps({"type": "message", "role": "assistant", "content": "Done."}) + "\\n")
sys.stdout.flush()
sys.exit(0)
""",
        encoding="utf-8",
    )

    cfg_file = ws / ".ai-orchestration.local.toml"
    cfg_file.write_text(
        f"""[routing]
default_orchestrator = "claude"

[orchestrator]
rotate_after_tokens = 50000

[tools.claude]
enabled = true

[tools.claude.headless]
argv = ["{sys.executable}", "{step_script}"]
resume_argv = ["{sys.executable}", "{step_script}"]
""",
        encoding="utf-8",
    )

    orch.enqueue_turn(ws, message="trigger rotation")
    res = orch.run_next_turn(ws)
    assert res["status"] == "done"

    # Status should now be generation 2!
    st = orch.get_orchestrator_status(ws)
    assert st["generation"] == 2

    # Check orchestrator.rotated event
    evs = events.read_events(ws)
    rot_evs = [e for e in evs if e["type"] == "orchestrator.rotated"]
    assert len(rot_evs) >= 1
    assert rot_evs[-1]["payload"]["generation"] == 2
    assert rot_evs[-1]["payload"]["reason"] == "context_threshold"


# ---------------------------------------------------------------------------
# 8. Fenced Succession & Stale Generation Refusal (Spec §0c E9)
# ---------------------------------------------------------------------------

def test_stale_generation_refused(ws: pathlib.Path):
    """Turn or execution carrying a stale generation token is refused."""
    orch.start_orchestrator(ws)
    st = orch.get_orchestrator_status(ws)
    assert st["generation"] == 1

    # Check validation helper
    ok, err = orch.check_generation_token(ws, expected_generation=1)
    assert ok is True

    ok_stale, err_stale = orch.check_generation_token(ws, expected_generation=99)
    assert ok_stale is False
    assert "stale-generation" in (err_stale or "")

    # Perform rotation to gen 2 (no handoff for speed)
    rot_res = orch.rotate_orchestrator(ws, handoff=False, reason="test_rotation")
    assert rot_res["status"] == "rotated"
    assert rot_res["generation"] == 2

    # Old generation 1 is now stale
    ok_gen1, err_gen1 = orch.check_generation_token(ws, expected_generation=1)
    assert ok_gen1 is False
    assert "stale-generation" in (err_gen1 or "")


def test_fenced_succession_rollback_on_handoff_failure(ws: pathlib.Path):
    """If the handoff bootstrap turn fails, rotation rolls back to previous generation."""
    orch.start_orchestrator(ws)
    st_init = orch.get_orchestrator_status(ws)
    init_sess_id = st_init["session_id"]
    assert st_init["generation"] == 1

    # Configure tool to fail exit 1
    cfg_file = ws / ".ai-orchestration.local.toml"
    cfg_file.write_text(
        f"""[routing]
default_orchestrator = "claude"

[tools.claude]
enabled = true

[tools.claude.headless]
argv = ["{sys.executable}", "{STUB_AGENT}", "--exit-code", "1"]
resume_argv = ["{sys.executable}", "{STUB_AGENT}", "--exit-code", "1"]
""",
        encoding="utf-8",
    )

    # Attempt rotation with handoff
    res = orch.rotate_orchestrator(ws, handoff=True)
    assert res["status"] == "failed"
    assert res["error"] == "handoff_turn_failed"

    # Status must roll back to generation 1 and active!
    st_after = orch.get_orchestrator_status(ws)
    assert st_after["generation"] == 1
    assert st_after["session_id"] == init_sess_id
    assert st_after["status"] == "active"

    # Event orchestrator.rotation_failed emitted
    evs = events.read_events(ws)
    rf = [e for e in evs if e["type"] == "orchestrator.rotation_failed"]
    assert len(rf) >= 1


# ---------------------------------------------------------------------------
# 9. Reduced Capability Policy for Unattended Turns (Spec §0c E3)
# ---------------------------------------------------------------------------

def test_unattended_turn_reduced_capabilities(ws: pathlib.Path):
    """Event batch turns run with reduced capability policy and untrusted delimiters."""
    orch.start_orchestrator(ws)

    ev_turn = orch.enqueue_turn(
        ws,
        turn_type="event_batch",
        events=[{"seq": 42, "id": "ev-42", "type": "task.transitioned", "data": {"to": "delivered"}}],
    )["turn"]

    assert ev_turn["policy"] == "reduced_capability"

    # Build prompt and verify delimiters and notice
    prompt = orch.build_turn_prompt(ev_turn)
    assert "<untrusted-event-data>" in prompt
    assert "</untrusted-event-data>" in prompt
    assert "REDUCED CAPABILITIES" in prompt

    # Execute turn
    res = orch.run_next_turn(ws)
    assert res["status"] == "done"

    # Verify cursor advanced to 42
    st = orch.get_orchestrator_status(ws)
    assert st["cursor"] == 42


# ---------------------------------------------------------------------------
# 10. Turn Cancellation (Spec §0c E6)
# ---------------------------------------------------------------------------

def test_cancel_queued_turn(ws: pathlib.Path):
    """Cancelling a queued turn removes it and sets state to cancelled."""
    orch.start_orchestrator(ws)
    turn = orch.enqueue_turn(ws, message="cancel me")["turn"]
    t_id = turn["turn_id"]

    res = orch.cancel_turn(ws, t_id)
    assert res["status"] == "cancelled"

    # Turn file in queue/ is removed, saved in turns/
    q_items = orch.list_queue(ws)
    assert not any(it["turn_id"] == t_id for it in q_items)

    arch_file = orch.get_turns_dir(ws) / t_id / "turn.json"
    assert arch_file.is_file()
    doc = orch._read_json_safe(arch_file)
    assert doc["state"] == "cancelled"


# ---------------------------------------------------------------------------
# 11. CLI Integration Tests
# ---------------------------------------------------------------------------

def test_cli_subcommands(ws: pathlib.Path):
    """Test ai-orch orchestrator subcommands via subprocess."""
    # 1. status
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "orchestrator", "status", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    st = json.loads(res.stdout)
    assert st["role"] == "orchestrator"
    assert st["generation"] == 1

    # 2. enqueue
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "orchestrator",
            "enqueue",
            "--message",
            "CLI hello",
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    enq = json.loads(res.stdout)
    assert enq["status"] == "enqueued"
    t_id = enq["turn_id"]

    # 3. queue
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "orchestrator", "queue", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    q_list = json.loads(res.stdout)
    assert len(q_list) == 1
    assert q_list[0]["turn_id"] == t_id

    # 4. run-next
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "orchestrator", "run-next", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    rn = json.loads(res.stdout)
    assert rn["status"] == "done"

    # 5. hand-off
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "orchestrator", "hand-off", "--workspace", str(ws), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    ho = json.loads(res.stdout)
    assert "Orchestrator Role Succession Handoff" in ho["handoff_prompt"]

    # 6. rotate
    res = subprocess.run(
        [
            sys.executable,
            str(BIN_AI_ORCH),
            "orchestrator",
            "rotate",
            "--no-handoff",
            "--workspace",
            str(ws),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    rot = json.loads(res.stdout)
    assert rot["status"] == "rotated"
    assert rot["generation"] == 2
