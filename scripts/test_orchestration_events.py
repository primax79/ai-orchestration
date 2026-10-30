"""test_orchestration_events.py — Comprehensive tests for append-only event store and outbox engine.

Verifies:
  - Spec §0c E1, E13, Spec §1
  - Concurrent emitters (threads and processes) produce gap-free unique seqs
  - Chunk rotation and chunk manifest
  - Reader across chunks, --since boundaries, and type filter
  - Truncated last line tolerated by reader and recovered by reconciliation
  - Counter-ahead and counter-behind reconciliation
  - Atomic manifest (no partial file visible to concurrent readers)
  - events tail --follow polling
  - CLI commands: ai-orch events emit, tail, stats, reconcile
  - Outbox prepare/commit/rollback and reconciliation
"""
from __future__ import annotations

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
    tail_events,
    reconcile,
    get_stats,
    prune_events,
    event_lock,
    outbox_prepare,
    outbox_commit,
    outbox_rollback,
    outbox_transaction,
    reconcile_outbox,
    load_manifest,
    ensure_git_exclude,
    open_event_store,
    EventStore,
)

BIN_AI_ORCH = REPO_ROOT / "bin" / "ai-orch"


@pytest.fixture
def ws(tmp_path: pathlib.Path) -> pathlib.Path:
    workspace = tmp_path / "test_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


# ---------------------------------------------------------------------------
# 1. Basic Single Event & Schema Tests (Spec §1)
# ---------------------------------------------------------------------------

def test_emit_single_event(ws: pathlib.Path):
    payload = {"state": "in progress", "actor": "alice"}
    ev = emit(
        ws,
        "task.transitioned",
        payload,
        source="tasks_engine",
        correlation_id="corr-123",
        subject="T001",
        origin_session="sess-abc",
    )

    # Required spec fields
    assert ev["seq"] == 1
    assert isinstance(ev["id"], str) and len(ev["id"]) > 10
    assert ev["ts"].endswith("Z")
    assert ev["type"] == "task.transitioned"
    assert ev["source"] == "tasks_engine"
    assert ev["payload"] == payload
    assert ev["data"] == payload  # Spec §1 alias
    assert ev["subject"] == "T001"
    assert ev["origin_session"] == "sess-abc"
    assert ev["actor"] == "tasks_engine"
    assert ev["correlation_id"] == "corr-123"
    assert ev["schema_version"] == 1

    # Check counter file
    counter_path = ws / ".ai-orchestration" / "events" / "counter"
    assert counter_path.is_file()
    assert counter_path.read_text(encoding="utf-8").strip() == "1"

    # Check manifest file
    manifest_path = ws / ".ai-orchestration" / "events" / "chunks.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest) == 1
    chunk0 = manifest[0]
    assert chunk0["chunk"] == 0
    assert chunk0["file"] == "events.000.jsonl"
    assert chunk0["first_seq"] == 1
    assert chunk0["last_seq"] == 1
    assert chunk0["event_count"] == 1
    assert chunk0["size"] > 0


# ---------------------------------------------------------------------------
# 2. Concurrent Emitters (Threads and Processes)
# ---------------------------------------------------------------------------

def test_concurrent_emitters_threads(ws: pathlib.Path):
    thread_count = 8
    events_per_thread = 25
    total_events = thread_count * events_per_thread

    def worker(worker_id: int):
        for i in range(events_per_thread):
            emit(
                ws,
                "thread.event",
                {"worker": worker_id, "iteration": i},
                source=f"thread-{worker_id}",
            )

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    events = read_events(ws)
    assert len(events) == total_events

    seqs = [e["seq"] for e in events]
    # Gap-free, unique sequence numbers
    assert seqs == list(range(1, total_events + 1))


def _process_worker(ws_str: str, worker_id: int, count: int):
    for i in range(count):
        emit(
            pathlib.Path(ws_str),
            "proc.event",
            {"worker": worker_id, "i": i},
            source=f"proc-{worker_id}",
        )


def test_concurrent_emitters_processes(ws: pathlib.Path):
    proc_count = 4
    events_per_proc = 25
    total_events = proc_count * events_per_proc

    ctx = multiprocessing.get_context("spawn")
    processes = []
    for p in range(proc_count):
        proc = ctx.Process(target=_process_worker, args=(str(ws), p, events_per_proc))
        proc.start()
        processes.append(proc)

    for proc in processes:
        proc.join()
        assert proc.exitcode == 0

    events = read_events(ws)
    assert len(events) == total_events

    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, total_events + 1))


# ---------------------------------------------------------------------------
# 3. Chunk Rotation and Manifest
# ---------------------------------------------------------------------------

def test_chunk_rotation_and_manifest(ws: pathlib.Path):
    # Small chunk size to force rotation every ~2 events
    chunk_limit = 400
    for i in range(15):
        emit(
            ws,
            "test.rotate",
            {"i": i, "padding": "x" * 120},
            source="rotator",
            max_chunk_size=chunk_limit,
        )

    manifest = load_manifest(ws / ".ai-orchestration" / "events")
    assert len(manifest) >= 4

    # Verify manifest invariants
    for idx, chunk_info in enumerate(manifest):
        assert chunk_info["chunk"] == idx
        assert chunk_info["file"] == f"events.{idx:03d}.jsonl"
        assert chunk_info["first_seq"] <= chunk_info["last_seq"]
        assert chunk_info["event_count"] > 0
        assert chunk_info["size"] > 0
        assert chunk_info["end_offset"] == chunk_info["start_offset"] + chunk_info["size"]

        if idx > 0:
            prev = manifest[idx - 1]
            assert chunk_info["start_offset"] == prev["end_offset"]
            assert chunk_info["first_seq"] == prev["last_seq"] + 1

    # Verify all events are present in order
    all_events = read_events(ws)
    assert len(all_events) == 15
    assert [e["seq"] for e in all_events] == list(range(1, 16))


# ---------------------------------------------------------------------------
# 4. Reader Across Chunks and --since Boundaries
# ---------------------------------------------------------------------------

def test_reader_across_chunks_and_since_boundaries(ws: pathlib.Path):
    for i in range(20):
        emit(
            ws,
            "test.reader",
            {"index": i},
            source="test",
            max_chunk_size=300,  # Forces multiple chunks
        )

    # 1. Read all
    all_evs = read_events(ws)
    assert len(all_evs) == 20

    # 2. --since is an exclusive cursor: events after SEQ (0 = from the start)
    since0 = read_events(ws, since=0)
    assert len(since0) == 20
    assert since0[0]["seq"] == 1
    since1 = read_events(ws, since=1)
    assert len(since1) == 19
    assert since1[0]["seq"] == 2

    # 3. --since middle
    since8 = read_events(ws, since=8)
    assert len(since8) == 12
    assert since8[0]["seq"] == 9
    assert since8[-1]["seq"] == 20

    # 4. --since last
    since19 = read_events(ws, since=19)
    assert len(since19) == 1
    assert since19[0]["seq"] == 20
    assert read_events(ws, since=20) == []

    # 5. --since beyond last
    since25 = read_events(ws, since=25)
    assert len(since25) == 0

    # 6. --limit with --since
    since5_lim3 = read_events(ws, since=5, limit=3)
    assert len(since5_lim3) == 3
    assert [e["seq"] for e in since5_lim3] == [6, 7, 8]

    # 7. --limit without --since (tail behavior: last N)
    last5 = read_events(ws, limit=5)
    assert len(last5) == 5
    assert [e["seq"] for e in last5] == [16, 17, 18, 19, 20]


def test_reader_type_filter(ws: pathlib.Path):
    emit(ws, "task.transitioned", {"to": "in progress"}, source="test")
    emit(ws, "run.started", {"run_id": "R1"}, source="test")
    emit(ws, "task.transitioned", {"to": "delivered"}, source="test")
    emit(ws, "question.asked", {"q": "Q1"}, source="test")
    emit(ws, "run.finished", {"run_id": "R1"}, source="test")

    # Filter task.transitioned
    tasks = read_events(ws, types=["task.transitioned"])
    assert len(tasks) == 2
    assert all(e["type"] == "task.transitioned" for e in tasks)

    # Filter multiple types
    runs = read_events(ws, types=["run.started", "run.finished"])
    assert len(runs) == 2
    assert {e["type"] for e in runs} == {"run.started", "run.finished"}

    # Filter question
    qs = read_events(ws, types=["question.asked"])
    assert len(qs) == 1
    assert qs[0]["payload"]["q"] == "Q1"


# ---------------------------------------------------------------------------
# 5. Truncated Final Line Tolerated (Spec §0c E13)
# ---------------------------------------------------------------------------

def test_truncated_last_line_tolerated(ws: pathlib.Path):
    for i in range(4):
        emit(ws, "test.valid", {"i": i}, source="test")

    events_dir = ws / ".ai-orchestration" / "events"
    last_chunk = sorted(events_dir.glob("events.*.jsonl"))[-1]

    # Corrupt final line by appending truncated partial JSON with no newline
    with open(last_chunk, "ab") as f:
        f.write(b'{"seq":5,"type":"task.trans')
        f.flush()

    # Reader must tolerate truncated final line
    events = read_events(ws, tolerance=True)
    assert len(events) == 4
    assert [e["seq"] for e in events] == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# 6. Reconciliation: Counter-Ahead, Counter-Behind, and Truncation Recovery
# ---------------------------------------------------------------------------

def test_counter_ahead_reconciliation(ws: pathlib.Path):
    for i in range(5):
        emit(ws, "test.rec", {"i": i}, source="test")

    events_dir = ws / ".ai-orchestration" / "events"
    counter_path = events_dir / "counter"

    # Simulate crash after counter incremented but before chunk write
    counter_path.write_text("10\n", encoding="utf-8")

    rec_res = reconcile(ws)
    assert rec_res["ok"] is True
    assert rec_res["counter_before"] == 10
    assert rec_res["counter_after"] == 5
    assert rec_res["last_seq"] == 5

    assert counter_path.read_text(encoding="utf-8").strip() == "5"

    # Next emit gets seq 6 (gap-free!)
    next_ev = emit(ws, "test.rec", {"i": 6}, source="test")
    assert next_ev["seq"] == 6


def test_counter_behind_reconciliation(ws: pathlib.Path):
    for i in range(5):
        emit(ws, "test.rec", {"i": i}, source="test")

    events_dir = ws / ".ai-orchestration" / "events"
    counter_path = events_dir / "counter"

    # Simulate counter lag
    counter_path.write_text("2\n", encoding="utf-8")

    rec_res = reconcile(ws)
    assert rec_res["ok"] is True
    assert rec_res["counter_before"] == 2
    assert rec_res["counter_after"] == 5
    assert rec_res["last_seq"] == 5

    assert counter_path.read_text(encoding="utf-8").strip() == "5"

    # Next emit gets seq 6 (no duplicate!)
    next_ev = emit(ws, "test.rec", {"i": 6}, source="test")
    assert next_ev["seq"] == 6


def test_truncated_last_line_reconciliation(ws: pathlib.Path):
    for i in range(4):
        emit(ws, "test.rec", {"i": i}, source="test")

    events_dir = ws / ".ai-orchestration" / "events"
    last_chunk = sorted(events_dir.glob("events.*.jsonl"))[-1]

    # Append broken line
    with open(last_chunk, "ab") as f:
        f.write(b'{"seq":5,"type":"task.incomplete_data_here\n')
        f.flush()

    # Counter set to 5
    (events_dir / "counter").write_text("5\n", encoding="utf-8")

    rec_res = reconcile(ws)
    assert rec_res["ok"] is True
    assert len(rec_res["truncated_lines"]) == 1
    assert rec_res["last_seq"] == 4
    assert rec_res["counter_after"] == 4

    # Subsequent emit writes seq 5 cleanly
    ev5 = emit(ws, "test.clean", {"i": 5}, source="test")
    assert ev5["seq"] == 5

    all_evs = read_events(ws)
    assert len(all_evs) == 5
    assert [e["seq"] for e in all_evs] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# 7. Atomic Manifest (No Partial File Visible)
# ---------------------------------------------------------------------------

def test_atomic_manifest_no_partial_file(ws: pathlib.Path):
    stop_event = threading.Event()
    read_errors: list[str] = []

    def reader_loop():
        events_dir = ws / ".ai-orchestration" / "events"
        while not stop_event.is_set():
            manifest_file = events_dir / "chunks.json"
            if manifest_file.is_file():
                try:
                    txt = manifest_file.read_text(encoding="utf-8")
                    if txt:
                        json.loads(txt)
                except Exception as e:
                    read_errors.append(f"Failed to read/parse manifest: {e}")
            time.sleep(0.001)

    t = threading.Thread(target=reader_loop)
    t.start()

    # Rapidly emit events with small chunks to trigger repeated manifest overwrites
    for i in range(50):
        emit(ws, "test.atomic", {"i": i}, source="writer", max_chunk_size=300)

    stop_event.set()
    t.join()

    assert not read_errors, f"Encountered partial or corrupt manifest reads: {read_errors}"


# ---------------------------------------------------------------------------
# 8. Follow Mode (events tail -f)
# ---------------------------------------------------------------------------

def test_events_tail_follow(ws: pathlib.Path):
    # Emit initial event
    emit(ws, "test.follow", {"msg": "init"}, source="test")

    collected: list[dict[str, Any]] = []
    stop_event = threading.Event()

    def follow_worker():
        for ev in tail_events(ws, follow=True, poll_interval=0.05, stop_event=stop_event):
            collected.append(ev)

    t = threading.Thread(target=follow_worker)
    t.start()

    # Wait for follow worker to consume initial event
    time.sleep(0.15)
    emit(ws, "test.follow", {"msg": "second"}, source="test")
    time.sleep(0.15)
    emit(ws, "test.follow", {"msg": "third"}, source="test")
    time.sleep(0.2)

    stop_event.set()
    t.join(timeout=2.0)

    assert len(collected) == 3
    assert [e["payload"]["msg"] for e in collected] == ["init", "second", "third"]


# ---------------------------------------------------------------------------
# 9. CLI Tests via bin/ai-orch
# ---------------------------------------------------------------------------

def test_cli_emit_and_tail(ws: pathlib.Path):
    # emit via CLI
    cmd_emit = [
        str(BIN_AI_ORCH),
        "events",
        "emit",
        "task.transitioned",
        "--payload",
        json.dumps({"task_id": "T001", "to": "in progress"}),
        "--source",
        "cli_test",
        "--subject",
        "T001",
        "--workspace",
        str(ws),
        "--json",
    ]
    res_emit = subprocess.run(cmd_emit, capture_output=True, text=True, check=True)
    out_emit = json.loads(res_emit.stdout)
    assert out_emit["ok"] is True
    assert out_emit["event"]["seq"] == 1
    assert out_emit["event"]["type"] == "task.transitioned"

    # tail via CLI
    cmd_tail = [
        str(BIN_AI_ORCH),
        "events",
        "tail",
        "--since",
        "0",
        "--workspace",
        str(ws),
        "--json",
    ]
    res_tail = subprocess.run(cmd_tail, capture_output=True, text=True, check=True)
    out_tail = json.loads(res_tail.stdout)
    assert out_tail["ok"] is True
    assert len(out_tail["events"]) == 1
    assert out_tail["events"][0]["seq"] == 1

    # stats via CLI
    cmd_stats = [
        str(BIN_AI_ORCH),
        "events",
        "stats",
        "--workspace",
        str(ws),
        "--json",
    ]
    res_stats = subprocess.run(cmd_stats, capture_output=True, text=True, check=True)
    out_stats = json.loads(res_stats.stdout)
    assert out_stats["ok"] is True
    assert out_stats["total_events"] == 1
    assert out_stats["counter"] == 1

    # reconcile via CLI
    cmd_rec = [
        str(BIN_AI_ORCH),
        "events",
        "reconcile",
        "--workspace",
        str(ws),
        "--json",
    ]
    res_rec = subprocess.run(cmd_rec, capture_output=True, text=True, check=True)
    out_rec = json.loads(res_rec.stdout)
    assert out_rec["ok"] is True


# ---------------------------------------------------------------------------
# 10. Outbox API and Recovery Tests (Spec §0c E1)
# ---------------------------------------------------------------------------

def test_outbox_prepare_commit(ws: pathlib.Path):
    mutation_id = "mut-001"
    outbox_prepare(
        ws,
        mutation_id,
        [{"path": "tasks/T001.md", "action": "modify"}],
        "task.transitioned",
        {"task_id": "T001", "to": "in progress"},
        source="outbox_test",
        subject="T001",
    )

    outbox_file = ws / ".ai-orchestration" / "events" / "outbox" / f"{mutation_id}.json"
    assert outbox_file.is_file()
    rec = json.loads(outbox_file.read_text(encoding="utf-8"))
    assert rec["status"] == "prepared"

    # Readers see 0 events before commit
    assert len(read_events(ws)) == 0

    # Commit outbox record
    ev = outbox_commit(ws, mutation_id)
    assert ev["seq"] == 1
    assert ev["type"] == "task.transitioned"

    # Now readers see the committed event
    events = read_events(ws)
    assert len(events) == 1
    assert events[0]["seq"] == 1


def test_outbox_rollback(ws: pathlib.Path):
    target_file = ws / "test.txt"
    target_file.write_text("original content", encoding="utf-8")

    mutation_id = "mut-002"
    outbox_prepare(
        ws,
        mutation_id,
        [{"path": "test.txt", "action": "modify"}],
        "file.modified",
        {"file": "test.txt"},
        source="test",
        pre_images={"test.txt": "original content"},
    )

    # Mutate file
    target_file.write_text("corrupted content", encoding="utf-8")

    # Roll back
    outbox_rollback(ws, mutation_id)

    # Content restored
    assert target_file.read_text(encoding="utf-8") == "original content"

    # No events committed
    assert len(read_events(ws)) == 0


def test_outbox_transaction_success(ws: pathlib.Path):
    target = ws / "state.json"
    target.write_text(json.dumps({"state": "initial"}), encoding="utf-8")

    with outbox_transaction(
        ws,
        "mut-tx-1",
        [{"path": "state.json"}],
        "state.changed",
        {"state": "updated"},
        source="tx_test",
        pre_images={"state.json": json.dumps({"state": "initial"})},
    ):
        target.write_text(json.dumps({"state": "updated"}), encoding="utf-8")

    # Event committed
    events = read_events(ws)
    assert len(events) == 1
    assert events[0]["type"] == "state.changed"
    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "updated"}


def test_outbox_transaction_exception_rolls_back(ws: pathlib.Path):
    target = ws / "state.json"
    target.write_text("original", encoding="utf-8")

    with pytest.raises(RuntimeError):
        with outbox_transaction(
            ws,
            "mut-tx-fail",
            [{"path": "state.json"}],
            "state.failed",
            {},
            source="tx_test",
            pre_images={"state.json": "original"},
        ):
            target.write_text("bad data", encoding="utf-8")
            raise RuntimeError("failure during mutation")

    # Rolled back
    assert target.read_text(encoding="utf-8") == "original"
    assert len(read_events(ws)) == 0


def test_reconcile_outbox_startup(ws: pathlib.Path):
    target = ws / "applied.txt"
    target.write_text("done", encoding="utf-8")

    outbox_prepare(
        ws,
        "mut-startup",
        [{"path": "applied.txt", "expected_content": "done"}],
        "task.applied",
        {"status": "done"},
        source="reconcile_test",
    )

    reconciled = reconcile_outbox(ws)
    assert len(reconciled) == 1
    assert reconciled[0]["action"] == "committed"

    events = read_events(ws)
    assert len(events) == 1
    assert events[0]["type"] == "task.applied"


# ---------------------------------------------------------------------------
# 11. Git Exclude & Retention
# ---------------------------------------------------------------------------

def test_git_exclude(ws: pathlib.Path):
    git_dir = ws / ".git" / "info"
    git_dir.mkdir(parents=True, exist_ok=True)
    exclude_file = git_dir / "exclude"

    ensure_git_exclude(ws)
    assert exclude_file.is_file()
    assert ".ai-orchestration/" in exclude_file.read_text(encoding="utf-8")


def test_prune_events(ws: pathlib.Path):
    # Emit events across multiple chunks
    for i in range(12):
        emit(ws, "test.prune", {"i": i}, source="test", max_chunk_size=300)

    manifest_before = load_manifest(ws / ".ai-orchestration" / "events")
    assert len(manifest_before) >= 3

    # Retain only last 2 chunks
    res_prune = prune_events(ws, keep_chunks=2)
    assert res_prune["ok"] is True
    assert res_prune["deleted_chunks"] >= 1

    manifest_after = load_manifest(ws / ".ai-orchestration" / "events")
    assert len(manifest_after) == 2
    assert manifest_after[0]["first_seq"] > 1


# ---------------------------------------------------------------------------
# 12. Additional Reconciliation & EventStore Tests
# ---------------------------------------------------------------------------

def test_truncated_last_line_without_newline(ws: pathlib.Path):
    for i in range(3):
        emit(ws, "test.valid", {"i": i}, source="test")

    events_dir = ws / ".ai-orchestration" / "events"
    last_chunk = sorted(events_dir.glob("events.*.jsonl"))[-1]

    # Append broken bytes with NO newline at all
    with open(last_chunk, "ab") as f:
        f.write(b'{"seq":4,"type":"task.incomplete_bytes_without_newline')
        f.flush()

    (events_dir / "counter").write_text("4\n", encoding="utf-8")

    rec = reconcile(ws)
    assert rec["ok"] is True
    assert len(rec["truncated_lines"]) == 1
    assert rec["last_seq"] == 3
    assert rec["counter_after"] == 3

    # Next emit gets seq 4 cleanly
    ev4 = emit(ws, "test.clean", {"i": 4}, source="test")
    assert ev4["seq"] == 4
    events = read_events(ws)
    assert len(events) == 4
    assert [e["seq"] for e in events] == [1, 2, 3, 4]


def test_open_event_store_and_class_api(ws: pathlib.Path):
    store = open_event_store(ws)
    assert isinstance(store, EventStore)
    assert store.reconcile_report is not None

    ev = store.emit("test.store", {"hello": "world"}, subject="SUB1")
    assert ev["seq"] == 1
    assert ev["source"] == "core"  # default source
    assert ev["subject"] == "SUB1"

    read_evs = store.read()
    assert len(read_evs) == 1
    assert read_evs[0]["seq"] == 1

    stats = store.stats()
    assert stats["total_events"] == 1
    assert stats["counter"] == 1


def test_emit_default_source(ws: pathlib.Path):
    ev = emit(ws, "test.default", {"data": 123})
    assert ev["source"] == "core"
    assert ev["actor"] == "core"
    assert ev["seq"] == 1


def test_cli_tail_jsonl(ws: pathlib.Path):
    emit(ws, "test.jsonl1", {"a": 1})
    emit(ws, "test.jsonl2", {"b": 2})

    cmd_tail = [
        str(BIN_AI_ORCH),
        "events",
        "tail",
        "--workspace",
        str(ws),
        "--jsonl",
    ]
    res = subprocess.run(cmd_tail, capture_output=True, text=True, check=True)
    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1["seq"] == 1
    assert e2["seq"] == 2


# ---------------------------------------------------------------------------
# Session Field & Filter Tests (Task 12.13)
# ---------------------------------------------------------------------------

def test_emit_session_field_and_fallback(ws: pathlib.Path):
    # 1. Explicit session parameter
    ev1 = emit(ws, "run.started", {"status": "starting"}, session="sess-agent-1", subject="R1")
    assert ev1["session"] == "sess-agent-1"
    assert ev1["origin_session"] == "sess-agent-1"

    # 2. Distinct session and origin_session
    ev2 = emit(
        ws,
        "run.started",
        {"status": "starting"},
        session="sess-agent-2",
        origin_session="sess-orch-main",
        subject="R2",
    )
    assert ev2["session"] == "sess-agent-2"
    assert ev2["origin_session"] == "sess-orch-main"

    # 3. Session extracted from payload
    ev3 = emit(ws, "run.started", {"session_id": "sess-from-payload"}, subject="R3")
    assert ev3["session"] == "sess-from-payload"
    assert ev3["origin_session"] == "sess-from-payload"


def test_tail_session_filter_api_and_cli(ws: pathlib.Path):
    emit(ws, "task.transitioned", {"step": 1}, session="sess-alpha")
    emit(ws, "run.started", {"step": 2}, session="sess-beta")
    emit(ws, "run.finished", {"step": 3}, session="sess-alpha")
    emit(ws, "config.changed", {"step": 4})  # No session

    # API read_events filtering
    alpha_events = read_events(ws, session="sess-alpha")
    assert len(alpha_events) == 2
    assert [e["seq"] for e in alpha_events] == [1, 3]

    beta_events = read_events(ws, session="sess-beta")
    assert len(beta_events) == 1
    assert beta_events[0]["seq"] == 2

    # CLI tail filtering
    cmd = [
        str(BIN_AI_ORCH),
        "events",
        "tail",
        "--workspace",
        str(ws),
        "--session",
        "sess-alpha",
        "--json",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out = json.loads(res.stdout)
    assert out["ok"] is True
    assert out["count"] == 2
    assert [e["seq"] for e in out["events"]] == [1, 3]


def test_tail_session_filter_follow_mode(ws: pathlib.Path):
    stop_event = threading.Event()
    collected: list[dict[str, Any]] = []

    def collector():
        for ev in tail_events(ws, session="sess-target", follow=True, poll_interval=0.05, stop_event=stop_event):
            collected.append(ev)

    t = threading.Thread(target=collector, daemon=True)
    t.start()

    time.sleep(0.1)
    emit(ws, "test.ignore", {"data": 1}, session="sess-other")
    emit(ws, "test.match1", {"data": 2}, session="sess-target")
    emit(ws, "test.ignore2", {"data": 3})
    emit(ws, "test.match2", {"data": 4}, origin_session="sess-target")

    deadline = time.time() + 3.0
    while len(collected) < 2 and time.time() < deadline:
        time.sleep(0.05)

    stop_event.set()
    t.join(timeout=2.0)

    assert len(collected) == 2
    assert [e["type"] for e in collected] == ["test.match1", "test.match2"]


def test_19_4_events_include_host_id(ws: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Task 19.4: emitted events and outbox commits record canonical host id."""
    cfg_file = tmp_path / "orchestration.toml"
    cfg_file.write_text('[host]\nid = "alf_ubuntu"\n', encoding="utf-8")
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(cfg_file))

    ev1 = emit(ws, "task.created", {"task_id": "T001"})
    assert ev1["host"] == "alf_ubuntu"

    ev2 = emit(ws, "run.started", {"run_id": "r1"}, host="mac")
    assert ev2["host"] == "mac"

    with outbox_transaction(
        ws,
        "mut-host-1",
        [],
        "task.transitioned",
        {"task_id": "T001"},
        source="tasks_engine",
    ):
        pass

    events = read_events(ws)
    assert [e["host"] for e in events] == ["alf_ubuntu", "mac", "alf_ubuntu"]



