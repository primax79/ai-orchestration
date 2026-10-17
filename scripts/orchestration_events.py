#!/usr/bin/env python3
"""orchestration_events.py — Append-only event store and outbox engine for ai-orchestration.

Implements:
  - Spec §0c E1 (outbox write API, exclusive event lock fcntl, crash recovery, counter reconciliation)
  - Spec §0c E13 (readers use core, chunk manifest watcher, truncated final line tolerance)
  - Spec §1 (events core: event schema, sequence numbers, immutable chunks, logical offsets, retention)
  - Commands: `ai-orch events tail`, `ai-orch events emit`, `ai-orch events stats`, `ai-orch events reconcile`
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import logging
import os
import pathlib
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterator
import uuid

logger = logging.getLogger("orchestration_events")

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DEFAULT_CHUNK_SIZE = int(os.environ.get("AI_ORCH_EVENTS_CHUNK_SIZE", 10 * 1024 * 1024))
DEFAULT_CHUNK_EVENTS = int(os.environ.get("AI_ORCH_EVENTS_CHUNK_COUNT", 100_000))

# Thread-safety & in-process re-entrancy tracking for event lock
_EVENT_LOCK_COUNTS: dict[str, int] = {}
_EVENT_LOCK_FDS: dict[str, int] = {}
_EVENT_THREAD_LOCKS: dict[str, threading.RLock] = {}
_GLOBAL_LOCK = threading.Lock()


def check_platform(plat: str = sys.platform, fcntl_mod: Any = fcntl) -> str | None:
    """macOS and Linux only. Windows or absence of fcntl refused."""
    if plat.startswith("win") or fcntl_mod is None:
        return "unsupported-platform"
    return None


def _get_thread_lock(lock_key: str) -> threading.RLock:
    with _GLOBAL_LOCK:
        if lock_key not in _EVENT_THREAD_LOCKS:
            _EVENT_THREAD_LOCKS[lock_key] = threading.RLock()
        return _EVENT_THREAD_LOCKS[lock_key]


# ---------------------------------------------------------------------------
# Locking & Git Exclude
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def event_lock(workspace: pathlib.Path | str):
    """Exclusive fcntl.flock on <workspace>/.ai-orchestration/events/.lock.

    Serialized across processes via fcntl.flock; re-entrant across nested calls
    and serialized across threads in the same process via threading.RLock.
    """
    plat_err = check_platform()
    if plat_err:
        raise RuntimeError("Events engine is supported on macOS and Linux only (fcntl required)")

    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(events_dir, 0o700)
    except OSError:
        pass

    lock_file = events_dir / ".lock"
    lock_key = str(lock_file.resolve())
    thread_lock = _get_thread_lock(lock_key)

    with thread_lock:
        count = _EVENT_LOCK_COUNTS.get(lock_key, 0)
        if count > 0:
            _EVENT_LOCK_COUNTS[lock_key] = count + 1
            try:
                yield
            finally:
                _EVENT_LOCK_COUNTS[lock_key] -= 1
                if _EVENT_LOCK_COUNTS[lock_key] == 0:
                    _EVENT_LOCK_COUNTS.pop(lock_key, None)
            return

        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            _EVENT_LOCK_COUNTS[lock_key] = 1
            _EVENT_LOCK_FDS[lock_key] = fd
            yield
        finally:
            _EVENT_LOCK_COUNTS.pop(lock_key, None)
            _EVENT_LOCK_FDS.pop(lock_key, None)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)


def ensure_git_exclude(repo_root: pathlib.Path | str) -> tuple[bool, str | None]:
    """Ensure .ai-orchestration/ is added to .git/info/exclude and ignored."""
    ws = pathlib.Path(repo_root).resolve()
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=str(ws),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            exclude_path = pathlib.Path(res.stdout.strip())
            if not exclude_path.is_absolute():
                exclude_path = (ws / exclude_path).resolve()
        else:
            exclude_path = ws / ".git" / "info" / "exclude"
    except Exception:
        exclude_path = ws / ".git" / "info" / "exclude"

    try:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    existing_text = ""
    if exclude_path.is_file():
        try:
            existing_text = exclude_path.read_text(encoding="utf-8")
        except Exception:
            pass

    if ".ai-orchestration" not in existing_text:
        try:
            with open(exclude_path, "a", encoding="utf-8") as f:
                if existing_text and not existing_text.endswith("\n"):
                    f.write("\n")
                f.write(".ai-orchestration/\n")
        except Exception as e:
            return False, f"Failed to update {exclude_path}: {e}"

    # Verify git check-ignore if in a git repo
    try:
        check = subprocess.run(
            ["git", "check-ignore", "-q", ".ai-orchestration/"],
            cwd=str(ws),
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode != 0:
            check2 = subprocess.run(
                ["git", "check-ignore", "-q", ".ai-orchestration"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                check=False,
            )
            if check2.returncode != 0:
                return False, "Path '.ai-orchestration/' is still not ignored by git check-ignore"
    except Exception:
        pass

    return True, None


# ---------------------------------------------------------------------------
# Atomic Manifest Operations
# ---------------------------------------------------------------------------

def _write_manifest_atomic(events_dir: pathlib.Path, manifest: list[dict[str, Any]]) -> None:
    """Update chunks.json manifest atomically using write-temp + rename with fsync."""
    manifest_path = events_dir / "chunks.json"
    tmp_path = events_dir / f"chunks.json.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    content = json.dumps(manifest, indent=2).encode("utf-8")
    with open(tmp_path, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, manifest_path)


def load_manifest(events_dir: pathlib.Path) -> list[dict[str, Any]]:
    """Load chunks.json manifest safely, returning [] if absent or malformed."""
    manifest_path = events_dir / "chunks.json"
    if not manifest_path.is_file():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Reconciliation (Counter vs Chunks, Truncated Lines, Outbox)
# ---------------------------------------------------------------------------

def reconcile_chunks(events_dir: pathlib.Path) -> dict[str, Any]:
    """Reconcile counter vs last seq in chunk files, recover truncated final lines,

    and rebuild chunks.json manifest. Must be called under event_lock.
    """
    events_dir.mkdir(parents=True, exist_ok=True)
    counter_path = events_dir / "counter"
    counter_before = 0
    if counter_path.is_file():
        try:
            txt = counter_path.read_text(encoding="utf-8").strip()
            counter_before = int(txt) if txt else 0
        except ValueError:
            counter_before = 0

    chunk_files = sorted(events_dir.glob("events.*.jsonl"))

    # Also handle single unchunked events.jsonl if present and no chunks exist
    legacy_file = events_dir / "events.jsonl"
    if not chunk_files and legacy_file.is_file():
        dest = events_dir / "events.000.jsonl"
        legacy_file.rename(dest)
        chunk_files = [dest]

    if not chunk_files:
        # No chunks exist
        counter_after = 0
        with open(counter_path, "w", encoding="utf-8") as f:
            f.write("0\n")
            f.flush()
            os.fsync(f.fileno())
        _write_manifest_atomic(events_dir, [])
        return {
            "ok": True,
            "reconciled": counter_before != 0,
            "counter_before": counter_before,
            "counter_after": counter_after,
            "last_seq": 0,
            "truncated_lines": [],
            "chunk_count": 0,
        }

    all_truncated: list[dict[str, Any]] = []
    new_manifest: list[dict[str, Any]] = []
    current_logical_offset = 0
    highest_valid_seq = 0

    for idx, cf in enumerate(chunk_files):
        try:
            raw_data = cf.read_bytes()
        except OSError:
            continue

        chunk_size = len(raw_data)
        lines_raw = raw_data.splitlines(keepends=True)
        valid_byte_len = 0
        chunk_events_count = 0
        chunk_first_seq: int | None = None
        chunk_last_seq: int | None = None
        chunk_has_truncation = False

        for line_bytes in lines_raw:
            stripped = line_bytes.strip()
            if not stripped:
                valid_byte_len += len(line_bytes)
                continue
            try:
                line_str = stripped.decode("utf-8")
                ev = json.loads(line_str)
                if isinstance(ev, dict) and "seq" in ev:
                    seq = int(ev["seq"])
                    if chunk_first_seq is None:
                        chunk_first_seq = seq
                    chunk_last_seq = seq
                    if seq > highest_valid_seq:
                        highest_valid_seq = seq
                    chunk_events_count += 1
                    valid_byte_len += len(line_bytes)
                else:
                    raise ValueError("JSON line missing 'seq' field")
            except Exception as e:
                # Corrupted / truncated line encountered
                chunk_has_truncation = True
                all_truncated.append({
                    "chunk": cf.name,
                    "offset": valid_byte_len,
                    "error": str(e),
                    "raw": stripped.decode("utf-8", errors="replace")[:100],
                })
                # Truncate at the end of the last valid line
                break

        if chunk_has_truncation and valid_byte_len < chunk_size:
            with open(cf, "rb+") as f:
                f.seek(valid_byte_len)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
            chunk_size = valid_byte_len

        start_offset = current_logical_offset
        end_offset = current_logical_offset + chunk_size
        current_logical_offset = end_offset

        new_manifest.append({
            "chunk": idx,
            "file": cf.name,
            "first_seq": chunk_first_seq if chunk_first_seq is not None else 0,
            "last_seq": chunk_last_seq if chunk_last_seq is not None else 0,
            "event_count": chunk_events_count,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "size": chunk_size,
        })

    # Reconcile counter: counter must match highest_valid_seq
    counter_after = highest_valid_seq
    with open(counter_path, "w", encoding="utf-8") as f:
        f.write(f"{counter_after}\n")
        f.flush()
        os.fsync(f.fileno())

    _write_manifest_atomic(events_dir, new_manifest)

    return {
        "ok": True,
        "reconciled": (counter_before != counter_after) or bool(all_truncated),
        "counter_before": counter_before,
        "counter_after": counter_after,
        "last_seq": highest_valid_seq,
        "truncated_lines": all_truncated,
        "chunk_count": len(new_manifest),
    }


def reconcile_outbox(workspace: pathlib.Path | str) -> list[dict[str, Any]]:
    """Reconcile pending outbox records (Spec §0c E1).

    If a prepared record has all intended changes applied, commits it;
    otherwise rolls back the mutation and restores pre-images.
    """
    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    outbox_dir = events_dir / "outbox"
    if not outbox_dir.is_dir():
        return []

    records_processed: list[dict[str, Any]] = []
    for p in sorted(outbox_dir.glob("*.json")):
        if p.name.startswith("."):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(rec, dict) or rec.get("status") != "prepared":
            continue

        mutation_id = rec.get("mutation_id", p.stem)
        intended = rec.get("intended_changes", [])

        # Check if all intended changes are applied
        all_applied = True
        for change in intended:
            rel_path = change.get("path")
            if not rel_path:
                continue
            target = ws / rel_path
            expected_content = change.get("expected_content")
            if expected_content is not None:
                if not target.is_file() or target.read_text(encoding="utf-8") != expected_content:
                    all_applied = False
                    break
            else:
                if not target.exists():
                    all_applied = False
                    break

        if all_applied and intended:
            # Commit the outbox record
            committed_event = outbox_commit(ws, mutation_id)
            records_processed.append({"mutation_id": mutation_id, "action": "committed", "event": committed_event})
        else:
            # Rollback and restore pre-images
            outbox_rollback(ws, mutation_id)
            records_processed.append({"mutation_id": mutation_id, "action": "rolled_back"})

    return records_processed


def reconcile(workspace: pathlib.Path | str) -> dict[str, Any]:
    """Complete reconciliation of the event store and outbox under exclusive lock."""
    ws = pathlib.Path(workspace).resolve()
    with event_lock(ws):
        chunk_res = reconcile_chunks(ws / ".ai-orchestration" / "events")
        outbox_res = reconcile_outbox(ws)
        chunk_res["outbox_reconciled"] = outbox_res
        return chunk_res


# ---------------------------------------------------------------------------
# Outbox Write API (Spec §0c E1, Spec §1)
# ---------------------------------------------------------------------------

def emit(
    workspace: pathlib.Path | str,
    type: str,
    payload: Any,
    *,
    source: str = "core",
    correlation_id: str | None = None,
    subject: str | None = None,
    origin_session: str | None = None,
    actor: str | None = None,
    event_id: str | None = None,
    max_chunk_size: int | None = None,
    max_chunk_events: int | None = None,
) -> dict[str, Any]:
    """Emit an event to the append-only event log under the exclusive event lock.

    Allocates a monotonically increasing sequence number from the counter file,
    appends the JSON line to the active chunk, fsyncs, rotates chunks by size/count,
    and updates the chunk manifest atomically (write-temp + rename).
    """
    plat_err = check_platform()
    if plat_err:
        raise RuntimeError("Events engine is supported on macOS and Linux only (fcntl required)")

    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    ensure_git_exclude(ws)

    chunk_size_limit = max_chunk_size or DEFAULT_CHUNK_SIZE
    chunk_events_limit = max_chunk_events or DEFAULT_CHUNK_EVENTS

    with event_lock(ws):
        counter_path = events_dir / "counter"
        if not counter_path.is_file():
            reconcile_chunks(events_dir)

        try:
            txt = counter_path.read_text(encoding="utf-8").strip()
            current_seq = int(txt) if txt else 0
        except ValueError:
            reconcile_chunks(events_dir)
            txt = counter_path.read_text(encoding="utf-8").strip()
            current_seq = int(txt) if txt else 0

        next_seq = current_seq + 1

        resolved_subject = subject
        if resolved_subject is None and isinstance(payload, dict):
            resolved_subject = payload.get("subject") or payload.get("task_id") or payload.get("question_id") or "-"
        if resolved_subject is None:
            resolved_subject = "-"

        resolved_origin = origin_session
        if resolved_origin is None and isinstance(payload, dict):
            resolved_origin = payload.get("origin_session")

        resolved_actor = actor or source

        event: dict[str, Any] = {
            "seq": next_seq,
            "id": event_id or str(uuid.uuid4()),
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "type": type,
            "source": source,
            "payload": payload,
            "data": payload,  # alias for Spec §1
            "subject": resolved_subject,  # Spec §1
            "origin_session": resolved_origin,  # Spec §1
            "actor": resolved_actor,  # Spec §1
            "correlation_id": correlation_id,
            "schema_version": SCHEMA_VERSION,
        }

        line_str = json.dumps(event, separators=(",", ":")) + "\n"
        line_bytes = line_str.encode("utf-8")

        manifest = load_manifest(events_dir)
        if not manifest:
            # Need to create first chunk
            chunk_idx = 0
            cur_fn = f"events.{chunk_idx:03d}.jsonl"
            chunk_path = events_dir / cur_fn
            start_offset = 0
            chunk_entry: dict[str, Any] | None = None
        else:
            last_entry = manifest[-1]
            chunk_idx = last_entry["chunk"]
            cur_fn = last_entry["file"]
            chunk_path = events_dir / cur_fn
            chunk_size = chunk_path.stat().st_size if chunk_path.exists() else 0
            chunk_count = last_entry.get("event_count", 0)

            # Rotation check
            if chunk_size > 0 and (
                (chunk_size + len(line_bytes) > chunk_size_limit)
                or (chunk_count >= chunk_events_limit)
            ):
                chunk_idx += 1
                cur_fn = f"events.{chunk_idx:03d}.jsonl"
                chunk_path = events_dir / cur_fn
                start_offset = last_entry["end_offset"]
                chunk_entry = None
            else:
                start_offset = last_entry["start_offset"]
                chunk_entry = last_entry

        # Append line with fsync
        with open(chunk_path, "ab") as f:
            f.write(line_bytes)
            f.flush()
            os.fsync(f.fileno())

        # Update counter with fsync
        with open(counter_path, "w", encoding="utf-8") as f:
            f.write(f"{next_seq}\n")
            f.flush()
            os.fsync(f.fileno())

        # Update manifest atomically
        if chunk_entry is None:
            manifest.append({
                "chunk": chunk_idx,
                "file": cur_fn,
                "first_seq": next_seq,
                "last_seq": next_seq,
                "event_count": 1,
                "start_offset": start_offset,
                "end_offset": start_offset + len(line_bytes),
                "size": len(line_bytes),
            })
        else:
            if chunk_entry.get("first_seq", 0) == 0:
                chunk_entry["first_seq"] = next_seq
            chunk_entry["last_seq"] = next_seq
            chunk_entry["event_count"] = chunk_entry.get("event_count", 0) + 1
            chunk_entry["size"] = chunk_entry.get("size", 0) + len(line_bytes)
            chunk_entry["end_offset"] = chunk_entry["start_offset"] + chunk_entry["size"]

        _write_manifest_atomic(events_dir, manifest)
        return event


# ---------------------------------------------------------------------------
# Outbox Helpers (Spec §0c E1)
# ---------------------------------------------------------------------------

def outbox_prepare(
    workspace: pathlib.Path | str,
    mutation_id: str,
    intended_changes: list[dict[str, Any]] | None,
    event_type: str,
    payload: Any,
    *,
    source: str,
    correlation_id: str | None = None,
    subject: str | None = None,
    origin_session: str | None = None,
    actor: str | None = None,
    pre_images: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write an outbox record in state 'prepared' before applying file mutations."""
    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    outbox_dir = events_dir / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    ensure_git_exclude(ws)

    record = {
        "mutation_id": mutation_id,
        "status": "prepared",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_type": event_type,
        "payload": payload,
        "source": source,
        "correlation_id": correlation_id,
        "subject": subject,
        "origin_session": origin_session,
        "actor": actor,
        "intended_changes": intended_changes or [],
        "pre_images": pre_images or {},
    }
    record_file = outbox_dir / f"{mutation_id}.json"
    tmp_file = outbox_dir / f"{mutation_id}.json.tmp.{os.getpid()}"
    tmp_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp_file, record_file)
    return record


def outbox_commit(
    workspace: pathlib.Path | str,
    mutation_id: str,
) -> dict[str, Any]:
    """Commit a prepared outbox record by emitting the event and updating record status."""
    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    outbox_dir = events_dir / "outbox"
    record_file = outbox_dir / f"{mutation_id}.json"
    if not record_file.is_file():
        raise FileNotFoundError(f"Outbox record for mutation_id {mutation_id!r} not found")

    record = json.loads(record_file.read_text(encoding="utf-8"))
    if record.get("status") == "committed":
        return record.get("event", {})

    with event_lock(ws):
        event = emit(
            ws,
            record["event_type"],
            record["payload"],
            source=record.get("source", "outbox"),
            correlation_id=record.get("correlation_id"),
            subject=record.get("subject"),
            origin_session=record.get("origin_session"),
            actor=record.get("actor"),
        )
        record["status"] = "committed"
        record["committed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        record["event"] = event
        tmp_file = outbox_dir / f"{mutation_id}.json.tmp.{os.getpid()}"
        tmp_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp_file, record_file)
        return event


def outbox_rollback(
    workspace: pathlib.Path | str,
    mutation_id: str,
) -> dict[str, Any]:
    """Roll back a prepared outbox record and restore pre-images."""
    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    outbox_dir = events_dir / "outbox"
    record_file = outbox_dir / f"{mutation_id}.json"
    if not record_file.is_file():
        raise FileNotFoundError(f"Outbox record for mutation_id {mutation_id!r} not found")

    record = json.loads(record_file.read_text(encoding="utf-8"))
    pre_images = record.get("pre_images", {})
    for rel_path, content in pre_images.items():
        target_path = ws / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            if target_path.exists():
                target_path.unlink()
        else:
            target_path.write_text(content, encoding="utf-8")

    record["status"] = "rolled_back"
    record["rolled_back_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    tmp_file = outbox_dir / f"{mutation_id}.json.tmp.{os.getpid()}"
    tmp_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp_file, record_file)
    return record


@contextlib.contextmanager
def outbox_transaction(
    workspace: pathlib.Path | str,
    mutation_id: str,
    intended_changes: list[dict[str, Any]] | None,
    event_type: str,
    payload: Any,
    *,
    source: str,
    correlation_id: str | None = None,
    subject: str | None = None,
    origin_session: str | None = None,
    actor: str | None = None,
    pre_images: dict[str, str] | None = None,
):
    """Context manager for an outbox transaction.

    Prepares the outbox record, executes the body, commits on success, and rolls back
    restoring pre-images on exception.
    """
    outbox_prepare(
        workspace,
        mutation_id,
        intended_changes,
        event_type,
        payload,
        source=source,
        correlation_id=correlation_id,
        subject=subject,
        origin_session=origin_session,
        actor=actor,
        pre_images=pre_images,
    )
    try:
        yield
    except Exception:
        outbox_rollback(workspace, mutation_id)
        raise
    else:
        outbox_commit(workspace, mutation_id)


# ---------------------------------------------------------------------------
# Reading & Tailing Events (Spec §0c E13, Spec §1)
# ---------------------------------------------------------------------------

def read_events(
    workspace: pathlib.Path | str,
    *,
    since: int | None = None,
    limit: int | None = None,
    types: list[str] | set[str] | None = None,
    session: str | None = None,
    tolerance: bool = True,
    on_truncated: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Read events from the append-only log through the chunk manifest.

    Tolerates truncated final lines if tolerance=True.
    """
    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    manifest = load_manifest(events_dir)

    # Fallback to discovering chunks if manifest is missing
    if not manifest:
        chunks = sorted(events_dir.glob("events.*.jsonl"))
        if not chunks and (events_dir / "events.jsonl").is_file():
            chunks = [events_dir / "events.jsonl"]
        manifest = [{"chunk": i, "file": c.name} for i, c in enumerate(chunks)]

    if not manifest:
        return []

    types_set = set(types) if types else None
    events: list[dict[str, Any]] = []

    for chunk_info in manifest:
        # Optimization: skip chunk if last_seq is known and < since
        if since is not None and "last_seq" in chunk_info and chunk_info["last_seq"] <= since:
            continue

        chunk_path = events_dir / chunk_info["file"]
        if not chunk_path.is_file():
            continue

        try:
            lines = chunk_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError as err:
                if tolerance:
                    # Tolerate and report corrupted / truncated line
                    logger.warning("Ignoring truncated event line in %s: %s (%s)", chunk_path.name, line[:100], err)
                    if on_truncated is not None:
                        on_truncated({"chunk": chunk_path.name, "line": line, "error": str(err)})
                    continue
                raise

            if not isinstance(ev, dict) or "seq" not in ev:
                continue

            seq = ev["seq"]
            if since is not None and seq <= since:
                continue
            if types_set and ev.get("type") not in types_set:
                continue
            if session and ev.get("origin_session") != session:
                continue

            events.append(ev)

    if limit is not None and limit > 0:
        if since is not None:
            # When --since is specified, return the first `limit` events from that sequence
            events = events[:limit]
        else:
            # When --since is not specified, return the last `limit` events (tail behavior)
            events = events[-limit:]

    return events


def tail_events(
    workspace: pathlib.Path | str,
    *,
    since: int | None = None,
    limit: int | None = None,
    types: list[str] | set[str] | None = None,
    session: str | None = None,
    follow: bool = False,
    poll_interval: float = 0.25,
    stop_event: threading.Event | None = None,
    on_truncated: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield events in order. If follow=True, poll chunks.json manifest for new events."""
    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    types_set = set(types) if types else None

    # Step 1: Yield existing matching events
    initial_events = read_events(
        ws,
        since=since,
        limit=limit,
        types=types_set,
        session=session,
        tolerance=True,
        on_truncated=on_truncated,
    )

    last_emitted_seq = 0
    for ev in initial_events:
        seq = ev.get("seq", 0)
        if seq > last_emitted_seq:
            last_emitted_seq = seq
        yield ev

    if last_emitted_seq == 0 and since is not None:
        last_emitted_seq = since

    if not follow:
        return

    # Step 2: Follow mode — poll manifest periodically
    while True:
        if stop_event is not None and stop_event.is_set():
            break

        time.sleep(poll_interval)
        manifest = load_manifest(events_dir)
        if not manifest:
            continue

        candidate_chunks = [
            c for c in manifest
            if c.get("last_seq", 0) > last_emitted_seq
        ]
        if not candidate_chunks:
            continue

        for chunk_info in candidate_chunks:
            chunk_path = events_dir / chunk_info["file"]
            if not chunk_path.is_file():
                continue
            try:
                lines = chunk_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue

                if not isinstance(ev, dict) or "seq" not in ev:
                    continue

                seq = ev["seq"]
                if seq <= last_emitted_seq:
                    continue
                if types_set and ev.get("type") not in types_set:
                    continue
                if session and ev.get("origin_session") != session:
                    continue

                last_emitted_seq = seq
                yield ev


# ---------------------------------------------------------------------------
# Statistics API
# ---------------------------------------------------------------------------

def get_stats(workspace: pathlib.Path | str) -> dict[str, Any]:
    """Return counts, sequence range, chunks and counter state."""
    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"
    counter_path = events_dir / "counter"

    counter = 0
    if counter_path.is_file():
        try:
            txt = counter_path.read_text(encoding="utf-8").strip()
            counter = int(txt) if txt else 0
        except ValueError:
            counter = 0

    manifest = load_manifest(events_dir)
    total_events = sum(c.get("event_count", 0) for c in manifest)
    first_seq = manifest[0].get("first_seq") if manifest else None
    last_seq = manifest[-1].get("last_seq") if manifest else None

    return {
        "ok": True,
        "total_events": total_events,
        "first_seq": first_seq,
        "last_seq": last_seq,
        "chunk_count": len(manifest),
        "chunks": manifest,
        "counter": counter,
    }


# ---------------------------------------------------------------------------
# Retention Helper (Spec §1, Spec 07 R9)
# ---------------------------------------------------------------------------

def prune_events(
    workspace: pathlib.Path | str,
    *,
    keep_chunks: int | None = None,
    keep_seq_above: int | None = None,
) -> dict[str, Any]:
    """Delete whole old chunks according to retention policy and update manifest atomically."""
    ws = pathlib.Path(workspace).resolve()
    events_dir = ws / ".ai-orchestration" / "events"

    with event_lock(ws):
        manifest = load_manifest(events_dir)
        if not manifest or len(manifest) <= 1:
            return {"ok": True, "deleted_chunks": 0, "first_available_seq": manifest[0]["first_seq"] if manifest else 0}

        retained: list[dict[str, Any]] = []
        deleted_count = 0

        for idx, entry in enumerate(manifest):
            # Never delete the active (last) chunk
            if idx == len(manifest) - 1:
                retained.append(entry)
                continue

            should_delete = False
            if keep_chunks is not None and len(manifest) - idx > keep_chunks:
                should_delete = True
            elif keep_seq_above is not None and entry.get("last_seq", 0) < keep_seq_above:
                should_delete = True

            if should_delete:
                chunk_file = events_dir / entry["file"]
                if chunk_file.is_file():
                    try:
                        chunk_file.unlink()
                    except OSError:
                        pass
                deleted_count += 1
            else:
                retained.append(entry)

        _write_manifest_atomic(events_dir, retained)
        first_seq = retained[0].get("first_seq") if retained else 0
        return {
            "ok": True,
            "deleted_chunks": deleted_count,
            "first_available_seq": first_seq,
            "chunk_count": len(retained),
        }


# ---------------------------------------------------------------------------
# High-Level EventStore & open_event_store (reconciliation on open)
# ---------------------------------------------------------------------------

class EventStore:
    """Convenience interface for event store operations against a workspace.

    Reconciles counter vs chunks and uncommitted outbox entries on open if requested.
    """

    def __init__(
        self,
        workspace: pathlib.Path | str,
        *,
        reconcile_on_open: bool = True,
    ) -> None:
        self.workspace = pathlib.Path(workspace).resolve()
        if reconcile_on_open:
            self.reconcile_report = reconcile(self.workspace)
        else:
            self.reconcile_report = None

    def emit(
        self,
        type: str,
        payload: Any,
        *,
        source: str = "core",
        correlation_id: str | None = None,
        subject: str | None = None,
        origin_session: str | None = None,
        actor: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return emit(
            self.workspace,
            type,
            payload,
            source=source,
            correlation_id=correlation_id,
            subject=subject,
            origin_session=origin_session,
            actor=actor,
            **kwargs,
        )

    def read(
        self,
        *,
        since: int | None = None,
        limit: int | None = None,
        types: list[str] | set[str] | None = None,
        session: str | None = None,
        tolerance: bool = True,
        on_truncated: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        return read_events(
            self.workspace,
            since=since,
            limit=limit,
            types=types,
            session=session,
            tolerance=tolerance,
            on_truncated=on_truncated,
        )

    def tail(
        self,
        *,
        since: int | None = None,
        limit: int | None = None,
        types: list[str] | set[str] | None = None,
        session: str | None = None,
        follow: bool = False,
        poll_interval: float = 0.25,
        stop_event: threading.Event | None = None,
        on_truncated: Callable[[dict[str, Any]], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        return tail_events(
            self.workspace,
            since=since,
            limit=limit,
            types=types,
            session=session,
            follow=follow,
            poll_interval=poll_interval,
            stop_event=stop_event,
            on_truncated=on_truncated,
        )

    def stats(self) -> dict[str, Any]:
        return get_stats(self.workspace)

    def reconcile(self) -> dict[str, Any]:
        report = reconcile(self.workspace)
        self.reconcile_report = report
        return report

    def prune(
        self,
        *,
        keep_chunks: int | None = None,
        keep_seq_above: int | None = None,
    ) -> dict[str, Any]:
        return prune_events(
            self.workspace,
            keep_chunks=keep_chunks,
            keep_seq_above=keep_seq_above,
        )


def open_event_store(
    workspace: pathlib.Path | str,
    *,
    reconcile_on_open: bool = True,
) -> EventStore:
    """Open an event store for the workspace, reconciling on open by default."""
    return EventStore(workspace, reconcile_on_open=reconcile_on_open)


# ---------------------------------------------------------------------------
# CLI Command Handlers
# ---------------------------------------------------------------------------

def format_event_text(ev: dict[str, Any]) -> str:
    """Format single event for human-readable CLI display."""
    seq = ev.get("seq", "?")
    ts = ev.get("ts", "")
    ev_type = ev.get("type", "")
    source = ev.get("source", "-")
    subject = ev.get("subject", "-")
    payload_str = json.dumps(ev.get("payload", {}))
    return f"[{seq}] {ts} {ev_type} (source={source}, subject={subject}): {payload_str}"


def cmd_emit(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        err = {"ok": False, "error": plat_err, "message": "Events engine is supported on macOS and Linux only"}
        print(json.dumps(err, indent=2) if args.json else f"Error: {err['message']}", file=sys.stderr)
        return 1

    payload: Any = {}
    if getattr(args, "payload_file", None):
        try:
            payload = json.loads(pathlib.Path(args.payload_file).read_text(encoding="utf-8"))
        except Exception as e:
            err = {"ok": False, "error": f"Failed to read payload file: {e}"}
            print(json.dumps(err, indent=2) if args.json else f"Error: {err['error']}", file=sys.stderr)
            return 1
    elif getattr(args, "payload", None):
        try:
            payload = json.loads(args.payload)
        except Exception as e:
            err = {"ok": False, "error": f"Failed to parse payload JSON: {e}"}
            print(json.dumps(err, indent=2) if args.json else f"Error: {err['error']}", file=sys.stderr)
            return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    try:
        ev = emit(
            ws,
            args.type,
            payload,
            source=args.source or "cli",
            correlation_id=args.correlation_id,
            subject=args.subject,
            origin_session=getattr(args, "origin_session", None),
            actor=getattr(args, "actor", None),
        )
    except Exception as e:
        err = {"ok": False, "error": str(e)}
        print(json.dumps(err, indent=2) if args.json else f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"ok": True, "event": ev}, indent=2))
    else:
        print(f"Emitted event seq={ev['seq']} type={ev['type']} id={ev['id']}")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        err = {"ok": False, "error": plat_err, "message": "Events engine is supported on macOS and Linux only"}
        print(json.dumps(err, indent=2) if args.json else f"Error: {err['message']}", file=sys.stderr)
        return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    types = None
    if getattr(args, "type", None):
        types = []
        for t in args.type:
            types.extend([x.strip() for x in t.split(",") if x.strip()])

    if args.follow:
        try:
            for ev in tail_events(
                ws,
                since=args.since,
                limit=args.limit,
                types=types,
                session=getattr(args, "session", None),
                follow=True,
                poll_interval=getattr(args, "poll_interval", 0.25),
            ):
                if args.json:
                    print(json.dumps(ev), flush=True)
                else:
                    print(format_event_text(ev), flush=True)
        except KeyboardInterrupt:
            return 0
        return 0

    events = read_events(
        ws,
        since=args.since,
        limit=args.limit,
        types=types,
        session=getattr(args, "session", None),
        tolerance=True,
    )

    if args.jsonl:
        for ev in events:
            print(json.dumps(ev))
    elif args.json:
        print(json.dumps({
            "ok": True,
            "events": events,
            "count": len(events),
            "first_seq": events[0]["seq"] if events else None,
            "last_seq": events[-1]["seq"] if events else None,
        }, indent=2))
    else:
        for ev in events:
            print(format_event_text(ev))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        err = {"ok": False, "error": plat_err, "message": "Events engine is supported on macOS and Linux only"}
        print(json.dumps(err, indent=2) if args.json else f"Error: {err['message']}", file=sys.stderr)
        return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    res = get_stats(ws)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Total events: {res['total_events']}")
        print(f"Sequence range: {res['first_seq']} .. {res['last_seq']}")
        print(f"Chunks: {res['chunk_count']}")
        print(f"Counter: {res['counter']}")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        err = {"ok": False, "error": plat_err, "message": "Events engine is supported on macOS and Linux only"}
        print(json.dumps(err, indent=2) if args.json else f"Error: {err['message']}", file=sys.stderr)
        return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    res = reconcile(ws)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Reconciled: {res['reconciled']}")
        print(f"Counter: {res['counter_before']} -> {res['counter_after']}")
        print(f"Last seq: {res['last_seq']}")
        if res.get("truncated_lines"):
            print(f"Truncated lines recovered: {len(res['truncated_lines'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestration_events.py",
        description="Event store and outbox engine for ai-orchestration.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # emit
    p_emit = sub.add_parser("emit", help="Emit an event to the log under exclusive lock")
    p_emit.add_argument("type", help="Event type (e.g. task.transitioned, run.started)")
    p_emit.add_argument("--payload", help="JSON payload string", default="{}")
    p_emit.add_argument("--payload-file", help="Path to JSON file with payload", default=None)
    p_emit.add_argument("--source", help="Event source (e.g. cli, tasks_engine)", default="cli")
    p_emit.add_argument("--correlation-id", help="Optional correlation ID", default=None)
    p_emit.add_argument("--subject", help="Optional subject identifier (e.g. task ID)", default=None)
    p_emit.add_argument("--actor", help="Optional actor identifier", default=None)
    p_emit.add_argument("--origin-session", help="Optional origin session ID", default=None)
    p_emit.add_argument("--workspace", help="Workspace root directory", default=".")
    p_emit.add_argument("--json", action="store_true", help="Output JSON envelope")
    p_emit.set_defaults(func=cmd_emit)

    # tail
    p_tail = sub.add_parser("tail", help="Tail the event log through the chunk manifest")
    p_tail.add_argument("--since", type=int, help="Cursor: return events with seq > SEQ (exclusive; 0 = from the start)", default=None)
    p_tail.add_argument("--limit", type=int, help="Maximum events to return", default=None)
    p_tail.add_argument("--type", action="append", help="Filter by event type (can be repeated or comma-separated)", default=None)
    p_tail.add_argument("--session", help="Filter by origin_session", default=None)
    p_tail.add_argument("-f", "--follow", action="store_true", help="Poll manifest for new events")
    p_tail.add_argument("--poll-interval", type=float, default=0.25, help="Follow polling interval in seconds")
    p_tail.add_argument("--workspace", help="Workspace root directory", default=".")
    p_tail.add_argument("--json", action="store_true", help="Output JSON envelope")
    p_tail.add_argument("--jsonl", action="store_true", help="Output line-delimited JSON")
    p_tail.set_defaults(func=cmd_tail)

    # stats
    p_stats = sub.add_parser("stats", help="Show event store statistics")
    p_stats.add_argument("--workspace", help="Workspace root directory", default=".")
    p_stats.add_argument("--json", action="store_true", help="Output JSON envelope")
    p_stats.set_defaults(func=cmd_stats)

    # reconcile
    p_rec = sub.add_parser("reconcile", help="Reconcile counter vs chunks and recover truncated lines")
    p_rec.add_argument("--workspace", help="Workspace root directory", default=".")
    p_rec.add_argument("--json", action="store_true", help="Output JSON envelope")
    p_rec.set_defaults(func=cmd_reconcile)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
