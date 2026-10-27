#!/usr/bin/env python3
"""orchestration_sessions.py — Session registry, identifiers and cursors for ai-orchestration.

Implements:
  - Spec §0 (headless orchestrator, role vs session, succession, self-registration)
  - Spec §0b (orchestrator role holder, routing integration)
  - Spec §0c E2 (cursor belongs to the role; batches and succession)
  - Spec §0c E10 (four distinct ids: role_id, generation, registry_session_id, provider_session_id)
  - Spec §2 (session registry layout, register/heartbeat/deregister, list/show, cursors, subscriptions, staleness)
  - CLI: `ai-orch sessions register|heartbeat|list|show|cursor|deregister` (with `session`, `ack`, `end` aliases)
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import logging
import os
import pathlib
import sys
import threading
import time
from typing import Any, Callable
import uuid

logger = logging.getLogger("orchestration_sessions")

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

# Add parent directory to path to import companion modules
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from orchestration_events import (
    check_platform,
    emit,
    ensure_git_exclude,
    read_events,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DEFAULT_STALE_TIMEOUT_SEC = float(os.environ.get("AI_ORCH_SESSION_STALE_TIMEOUT", 300.0))

# Thread-safety & in-process re-entrancy tracking for session lock
_SESSION_LOCK_COUNTS: dict[str, int] = {}
_SESSION_LOCK_FDS: dict[str, int] = {}
_SESSION_THREAD_LOCKS: dict[str, threading.RLock] = {}
_SESSION_GLOBAL_LOCK = threading.Lock()


def _get_thread_lock(lock_key: str) -> threading.RLock:
    with _SESSION_GLOBAL_LOCK:
        if lock_key not in _SESSION_THREAD_LOCKS:
            _SESSION_THREAD_LOCKS[lock_key] = threading.RLock()
        return _SESSION_THREAD_LOCKS[lock_key]


# ---------------------------------------------------------------------------
# Locking & Atomic I/O
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def session_lock(workspace: pathlib.Path | str):
    """Exclusive fcntl.flock on <workspace>/.ai-orchestration/sessions/.lock.

    Serialized across processes via fcntl.flock; re-entrant across nested calls
    and serialized across threads in the same process via threading.RLock.
    Acquired before event_lock when emitting session events.
    """
    plat_err = check_platform()
    if plat_err:
        raise RuntimeError("Sessions engine is supported on macOS and Linux only (fcntl required)")

    ws = pathlib.Path(workspace).resolve()
    sessions_dir = ws / ".ai-orchestration" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(sessions_dir, 0o700)
    except OSError:
        pass

    lock_file = sessions_dir / ".lock"
    lock_key = str(lock_file.resolve())
    thread_lock = _get_thread_lock(lock_key)

    with thread_lock:
        count = _SESSION_LOCK_COUNTS.get(lock_key, 0)
        if count > 0:
            _SESSION_LOCK_COUNTS[lock_key] = count + 1
            try:
                yield
            finally:
                _SESSION_LOCK_COUNTS[lock_key] -= 1
                if _SESSION_LOCK_COUNTS[lock_key] == 0:
                    _SESSION_LOCK_COUNTS.pop(lock_key, None)
            return

        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            _SESSION_LOCK_COUNTS[lock_key] = 1
            _SESSION_LOCK_FDS[lock_key] = fd
            yield
        finally:
            _SESSION_LOCK_COUNTS.pop(lock_key, None)
            _SESSION_LOCK_FDS.pop(lock_key, None)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)


def _write_json_atomic(path: pathlib.Path, data: dict[str, Any]) -> None:
    """Write JSON data to path atomically using tempfile + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".tmp.{path.name}.{os.getpid()}.{uuid.uuid4().hex}"
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _read_json_safe(path: pathlib.Path) -> dict[str, Any]:
    """Read and parse JSON file, raising FileNotFoundError if absent."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Staleness & Status Calculation
# ---------------------------------------------------------------------------

def compute_session_status(
    session_data: dict[str, Any],
    stale_timeout_sec: float = DEFAULT_STALE_TIMEOUT_SEC,
    now: datetime.datetime | None = None,
) -> str:
    """Calculate the session status (active, stale, retired, deregistered)."""
    current_status = session_data.get("status", "active")
    if current_status in ("retired", "deregistered"):
        return current_status
    if session_data.get("retired"):
        return "retired"

    last_seen_str = session_data.get("last_seen")
    if not last_seen_str:
        return "stale"

    try:
        clean_ts = last_seen_str.replace("Z", "+00:00")
        last_seen_dt = datetime.datetime.fromisoformat(clean_ts)
        if last_seen_dt.tzinfo is None:
            last_seen_dt = last_seen_dt.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return "stale"

    current_now = now or datetime.datetime.now(datetime.timezone.utc)
    elapsed = (current_now - last_seen_dt).total_seconds()
    if elapsed > stale_timeout_sec:
        return "stale"
    return "active"


# ---------------------------------------------------------------------------
# Subscription Matching (§2)
# ---------------------------------------------------------------------------

def matches_subscription(event: dict[str, Any], subscriptions: list[str]) -> bool:
    """Check if an event matches any subscription pattern.

    Supported patterns:
      - "*" matches all events
      - "question.*" matches any event type starting with "question."
      - "task.transitioned" exact event type match
      - "subject:T013" matches event subject
    """
    if not subscriptions:
        return False

    ev_type = event.get("type", "")
    ev_subject = event.get("subject", "")

    for sub in subscriptions:
        if sub == "*":
            return True
        if sub.endswith(".*"):
            prefix = sub[:-2]
            if ev_type.startswith(prefix + "."):
                return True
        elif sub == ev_type:
            return True
        elif sub.startswith("subject:"):
            target_subject = sub[len("subject:"):]
            if target_subject == "*" or target_subject == ev_subject:
                return True
    return False


# ---------------------------------------------------------------------------
# Core Registry Functions
# ---------------------------------------------------------------------------

def find_session_by_provider_id(
    workspace: pathlib.Path | str,
    provider_session_id: str,
    tool: str | None = None,
    stale_timeout_sec: float = DEFAULT_STALE_TIMEOUT_SEC,
) -> dict[str, Any] | None:
    """Find an existing registered session by provider_session_id."""
    if not provider_session_id:
        return None
    sessions = list_sessions(workspace, tool=tool, stale_timeout_sec=stale_timeout_sec)
    # Prefer non-deregistered/non-retired sessions first
    for s in sessions:
        if s.get("provider_session_id") == provider_session_id and s.get("status") not in ("retired", "deregistered"):
            return s
    for s in sessions:
        if s.get("provider_session_id") == provider_session_id:
            return s
    return None


def register_session(
    workspace: pathlib.Path | str,
    tool: str = "claude",
    kind: str = "headless",
    role: str | None = None,
    provider_session_id: str | None = None,
    resume_id: str | None = None,
    session_id: str | None = None,
    cwd: str | None = None,
    subscriptions: list[str] | None = None,
    cursor: int | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register a new orchestration session under session_lock.

    If role == "orchestrator", updates orchestrator.json and manages role succession
    (retiring previous generation, bumping generation N -> N+1, preserving cursor per E2,
    and emitting orchestrator.rotated event).
    Emits session.registered event.
    """
    ws = pathlib.Path(workspace).resolve()
    ensure_git_exclude(ws)

    prov_sess_id = provider_session_id or resume_id
    now_iso = _now_iso()

    with session_lock(ws):
        sessions_dir = ws / ".ai-orchestration" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        existing_sess: dict[str, Any] | None = None
        if session_id:
            reg_session_id = session_id
            cand_path = sessions_dir / f"{reg_session_id}.json"
            if cand_path.is_file():
                try:
                    existing_sess = _read_json_safe(cand_path)
                except Exception:
                    existing_sess = None
        elif prov_sess_id:
            found = find_session_by_provider_id(ws, prov_sess_id, tool=tool)
            if found:
                existing_sess = found
                reg_session_id = str(found["session_id"])
            else:
                reg_session_id = str(uuid.uuid4())
        else:
            reg_session_id = str(uuid.uuid4())

        if existing_sess and not prov_sess_id:
            prov_sess_id = existing_sess.get("provider_session_id")

        final_generation: int | None = None
        base_cursor = int(existing_sess.get("cursor", 0)) if existing_sess else 0
        final_cursor: int = cursor if cursor is not None else base_cursor

        # Handle role tracking and succession
        if role == "orchestrator":
            orch_file = ws / ".ai-orchestration" / "orchestrator.json"
            if orch_file.is_file():
                try:
                    orch_doc = _read_json_safe(orch_file)
                except Exception:
                    orch_doc = {}
                cur_info = orch_doc.get("current", {})
                old_sess_id = cur_info.get("session_id")
                old_tool = cur_info.get("tool", "unknown")
                old_gen = orch_doc.get("generation", 1)
                role_cursor = orch_doc.get("cursor", 0)

                if old_sess_id and old_sess_id != reg_session_id:
                    # Role succession to generation N+1
                    new_gen = old_gen + 1
                    # Retire old session
                    old_sess_file = sessions_dir / f"{old_sess_id}.json"
                    if old_sess_file.is_file():
                        try:
                            old_data = _read_json_safe(old_sess_file)
                            old_data["status"] = "retired"
                            old_data["retired"] = {
                                "at": now_iso,
                                "reason": reason or "succession",
                            }
                            _write_json_atomic(old_sess_file, old_data)
                        except Exception as e:
                            logger.warning(f"Could not retire old session {old_sess_id}: {e}")

                    inherited_cursor = max(role_cursor, final_cursor)
                    orch_doc["generation"] = new_gen
                    orch_doc["cursor"] = inherited_cursor
                    orch_doc["current"] = {
                        "role_id": "orchestrator",
                        "generation": new_gen,
                        "registry_session_id": reg_session_id,
                        "session_id": reg_session_id,
                        "provider_session_id": prov_sess_id,
                        "tool": tool,
                        "kind": kind,
                        "started": now_iso,
                        "turns": 0,
                        "last_usage": None,
                        "status": "active",
                    }
                    _write_json_atomic(orch_file, orch_doc)

                    # Emit orchestrator.rotated (Spec §0 line 33)
                    emit(
                        ws,
                        "orchestrator.rotated",
                        payload={
                            "role": "orchestrator",
                            "generation": new_gen,
                            "session_id": reg_session_id,
                            "previous_session_id": old_sess_id,
                            "previous_tool": old_tool,
                            "tool": tool,
                            "reason": reason or "succession",
                            "cursor": inherited_cursor,
                        },
                        subject="orchestrator",
                        origin_session=reg_session_id,
                        actor=tool,
                    )
                    final_generation = new_gen
                    final_cursor = inherited_cursor
                else:
                    # Same session or re-registering
                    final_generation = old_gen
                    final_cursor = max(role_cursor, final_cursor)
                    orch_doc["generation"] = final_generation
                    orch_doc["cursor"] = final_cursor
                    orch_doc["current"] = {
                        "role_id": "orchestrator",
                        "generation": final_generation,
                        "registry_session_id": reg_session_id,
                        "session_id": reg_session_id,
                        "provider_session_id": prov_sess_id,
                        "tool": tool,
                        "kind": kind,
                        "started": now_iso,
                        "turns": cur_info.get("turns", 0),
                        "last_usage": cur_info.get("last_usage"),
                        "status": "active",
                    }
                    _write_json_atomic(orch_file, orch_doc)
            else:
                # First orchestrator registration
                final_generation = 1
                orch_doc = {
                    "role_id": "orchestrator",
                    "generation": final_generation,
                    "cursor": final_cursor,
                    "current": {
                        "role_id": "orchestrator",
                        "generation": final_generation,
                        "registry_session_id": reg_session_id,
                        "session_id": reg_session_id,
                        "provider_session_id": prov_sess_id,
                        "tool": tool,
                        "kind": kind,
                        "started": now_iso,
                        "turns": 0,
                        "last_usage": None,
                        "status": "active",
                    },
                }
                _write_json_atomic(orch_file, orch_doc)

        elif role is not None:
            # Generic role support
            roles_dir = ws / ".ai-orchestration" / "roles"
            roles_dir.mkdir(parents=True, exist_ok=True)
            role_file = roles_dir / f"{role}.json"
            if role_file.is_file():
                try:
                    rdoc = _read_json_safe(role_file)
                except Exception:
                    rdoc = {}
                old_sess_id = rdoc.get("current", {}).get("session_id")
                old_gen = rdoc.get("generation", 1)
                rc = rdoc.get("cursor", 0)
                if old_sess_id and old_sess_id != reg_session_id:
                    new_gen = old_gen + 1
                    inherited_cursor = max(rc, final_cursor)
                    rdoc["generation"] = new_gen
                    rdoc["cursor"] = inherited_cursor
                    rdoc["current"] = {
                        "role_id": role,
                        "generation": new_gen,
                        "session_id": reg_session_id,
                        "registry_session_id": reg_session_id,
                        "provider_session_id": prov_sess_id,
                        "tool": tool,
                        "started": now_iso,
                        "status": "active",
                    }
                    _write_json_atomic(role_file, rdoc)
                    final_generation = new_gen
                    final_cursor = inherited_cursor
                    emit(
                        ws,
                        "role.changed",
                        payload={
                            "role": role,
                            "generation": new_gen,
                            "session_id": reg_session_id,
                            "previous_session_id": old_sess_id,
                            "tool": tool,
                            "reason": reason or "succession",
                            "cursor": inherited_cursor,
                        },
                        subject=role,
                        origin_session=reg_session_id,
                        actor=tool,
                    )
                else:
                    final_generation = old_gen
                    final_cursor = max(rc, final_cursor)
            else:
                final_generation = 1
                rdoc = {
                    "role_id": role,
                    "generation": final_generation,
                    "cursor": final_cursor,
                    "current": {
                        "role_id": role,
                        "generation": final_generation,
                        "session_id": reg_session_id,
                        "registry_session_id": reg_session_id,
                        "provider_session_id": prov_sess_id,
                        "tool": tool,
                        "started": now_iso,
                        "status": "active",
                    },
                }
                _write_json_atomic(role_file, rdoc)

        # Build session record
        resume_block: dict[str, Any] | None = None
        if kind == "headless" or prov_sess_id:
            resume_block = {
                "provider_session_id": prov_sess_id,
                "session_id": prov_sess_id,
                "cwd": cwd or str(ws),
            }

        created_at = (existing_sess.get("created_at") if existing_sess else None) or now_iso
        if subscriptions:
            eff_subs = list(subscriptions)
        elif existing_sess:
            eff_subs = list(existing_sess.get("subscriptions") or [])
        else:
            eff_subs = []
        eff_meta: dict[str, Any] = dict(existing_sess.get("metadata") or {}) if existing_sess else {}
        if metadata:
            eff_meta.update(metadata)

        session_record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "session_id": reg_session_id,
            "registry_session_id": reg_session_id,
            "role": role,
            "role_id": role,
            "generation": final_generation,
            "tool": tool,
            "kind": kind,
            "provider_session_id": prov_sess_id,
            "resume": resume_block,
            "created_at": created_at,
            "last_seen": now_iso,
            "cursor": final_cursor,
            "subscriptions": eff_subs,
            "status": "active",
            "retired": None,
            "metadata": eff_meta,
        }

        sess_path = sessions_dir / f"{reg_session_id}.json"
        _write_json_atomic(sess_path, session_record)

        # Emit session.registered event
        emit(
            ws,
            "session.registered",
            payload=session_record,
            subject=reg_session_id,
            origin_session=reg_session_id,
            actor=tool,
        )

        return session_record


def heartbeat_session(
    workspace: pathlib.Path | str,
    session_id: str,
) -> dict[str, Any]:
    """Touch a session's last_seen timestamp under session_lock.

    If session was stale, restores status to active.
    """
    ws = pathlib.Path(workspace).resolve()
    with session_lock(ws):
        sess_path = ws / ".ai-orchestration" / "sessions" / f"{session_id}.json"
        if not sess_path.is_file():
            raise FileNotFoundError(f"Session not found: {session_id}")

        sess_data = _read_json_safe(sess_path)
        now_iso = _now_iso()
        sess_data["last_seen"] = now_iso

        if sess_data.get("status") == "stale":
            sess_data["status"] = "active"

        _write_json_atomic(sess_path, sess_data)
        return sess_data


def deregister_session(
    workspace: pathlib.Path | str,
    session_id: str,
    reason: str = "normal_exit",
) -> dict[str, Any]:
    """Deregister / end a session under session_lock.

    Marks session as deregistered with retired metadata.
    Updates role file if the session is currently holding a role.
    Emits session.deregistered event.
    """
    ws = pathlib.Path(workspace).resolve()
    now_iso = _now_iso()

    with session_lock(ws):
        sess_path = ws / ".ai-orchestration" / "sessions" / f"{session_id}.json"
        if not sess_path.is_file():
            raise FileNotFoundError(f"Session not found: {session_id}")

        sess_data = _read_json_safe(sess_path)
        sess_data["status"] = "deregistered"
        sess_data["retired"] = {
            "at": now_iso,
            "reason": reason,
        }
        _write_json_atomic(sess_path, sess_data)

        # If holding orchestrator role, update orchestrator.json
        if sess_data.get("role") == "orchestrator":
            orch_file = ws / ".ai-orchestration" / "orchestrator.json"
            if orch_file.is_file():
                try:
                    orch_doc = _read_json_safe(orch_file)
                    if orch_doc.get("current", {}).get("session_id") == session_id:
                        orch_doc["current"]["status"] = "deregistered"
                        _write_json_atomic(orch_file, orch_doc)
                except Exception:
                    pass

        # Emit session.deregistered event
        emit(
            ws,
            "session.deregistered",
            payload={
                "session_id": session_id,
                "role": sess_data.get("role"),
                "tool": sess_data.get("tool"),
                "reason": reason,
                "cursor": sess_data.get("cursor", 0),
            },
            subject=session_id,
            origin_session=session_id,
            actor=sess_data.get("tool") or "core",
        )

        return sess_data


def get_cursor(
    workspace: pathlib.Path | str,
    session_id: str | None = None,
    role: str | None = None,
) -> int:
    """Get current cursor for a session or role."""
    ws = pathlib.Path(workspace).resolve()
    with session_lock(ws):
        if role:
            if role == "orchestrator":
                orch_file = ws / ".ai-orchestration" / "orchestrator.json"
                if orch_file.is_file():
                    orch_doc = _read_json_safe(orch_file)
                    return int(orch_doc.get("cursor", 0))
                return 0
            roles_file = ws / ".ai-orchestration" / "roles" / f"{role}.json"
            if roles_file.is_file():
                rdoc = _read_json_safe(roles_file)
                return int(rdoc.get("cursor", 0))
            return 0

        if session_id:
            sess_path = ws / ".ai-orchestration" / "sessions" / f"{session_id}.json"
            if not sess_path.is_file():
                raise FileNotFoundError(f"Session not found: {session_id}")
            sdata = _read_json_safe(sess_path)
            return int(sdata.get("cursor", 0))

        raise ValueError("Either session_id or role must be provided")


def advance_cursor(
    workspace: pathlib.Path | str,
    seq: int,
    session_id: str | None = None,
    role: str | None = None,
) -> int:
    """Advance cursor monotonically under session_lock.

    Raises ValueError if seq < current_cursor.
    Updates role cursor in orchestrator.json if session holds orchestrator role
    or if role == 'orchestrator' per E2.
    """
    ws = pathlib.Path(workspace).resolve()
    with session_lock(ws):
        if not session_id and not role:
            raise ValueError("Either session_id or role must be provided")

        if role:
            if role == "orchestrator":
                orch_file = ws / ".ai-orchestration" / "orchestrator.json"
                if not orch_file.is_file():
                    raise FileNotFoundError("Orchestrator role file not found")
                orch_doc = _read_json_safe(orch_file)
                cur_cursor = int(orch_doc.get("cursor", 0))
                if seq < cur_cursor:
                    raise ValueError(
                        f"Cursor can only advance monotonically: attempted {seq} < current {cur_cursor}"
                    )
                orch_doc["cursor"] = seq
                _write_json_atomic(orch_file, orch_doc)

                cur_sess_id = orch_doc.get("current", {}).get("session_id")
                if cur_sess_id:
                    sess_path = ws / ".ai-orchestration" / "sessions" / f"{cur_sess_id}.json"
                    if sess_path.is_file():
                        try:
                            sdata = _read_json_safe(sess_path)
                            if seq > int(sdata.get("cursor", 0)):
                                sdata["cursor"] = seq
                                _write_json_atomic(sess_path, sdata)
                        except Exception:
                            pass
                return seq
            else:
                roles_file = ws / ".ai-orchestration" / "roles" / f"{role}.json"
                if not roles_file.is_file():
                    raise FileNotFoundError(f"Role file not found: {role}")
                rdoc = _read_json_safe(roles_file)
                cur_cursor = int(rdoc.get("cursor", 0))
                if seq < cur_cursor:
                    raise ValueError(
                        f"Cursor can only advance monotonically: attempted {seq} < current {cur_cursor}"
                    )
                rdoc["cursor"] = seq
                _write_json_atomic(roles_file, rdoc)
                return seq

        if session_id:
            sess_path = ws / ".ai-orchestration" / "sessions" / f"{session_id}.json"
            if not sess_path.is_file():
                raise FileNotFoundError(f"Session not found: {session_id}")
            sdata = _read_json_safe(sess_path)
            cur_cursor = int(sdata.get("cursor", 0))
            if seq < cur_cursor:
                raise ValueError(
                    f"Cursor can only advance monotonically: attempted {seq} < current {cur_cursor}"
                )
            sdata["cursor"] = seq
            _write_json_atomic(sess_path, sdata)

            # If holding orchestrator role, sync role cursor
            if sdata.get("role") == "orchestrator":
                orch_file = ws / ".ai-orchestration" / "orchestrator.json"
                if orch_file.is_file():
                    try:
                        orch_doc = _read_json_safe(orch_file)
                        if orch_doc.get("current", {}).get("session_id") == session_id:
                            if seq > int(orch_doc.get("cursor", 0)):
                                orch_doc["cursor"] = seq
                                _write_json_atomic(orch_file, orch_doc)
                    except Exception:
                        pass
            return seq

        raise ValueError("Invalid target")


def get_session(
    workspace: pathlib.Path | str,
    session_id: str,
    stale_timeout_sec: float = DEFAULT_STALE_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Retrieve one session by id, with dynamic staleness computed."""
    ws = pathlib.Path(workspace).resolve()
    sess_path = ws / ".ai-orchestration" / "sessions" / f"{session_id}.json"
    if not sess_path.is_file():
        raise FileNotFoundError(f"Session not found: {session_id}")

    data = _read_json_safe(sess_path)
    data["status"] = compute_session_status(data, stale_timeout_sec=stale_timeout_sec)
    return data


def list_sessions(
    workspace: pathlib.Path | str,
    role: str | None = None,
    status: str | None = None,
    tool: str | None = None,
    stale_timeout_sec: float = DEFAULT_STALE_TIMEOUT_SEC,
) -> list[dict[str, Any]]:
    """List sessions matching optional filters (role, status, tool)."""
    ws = pathlib.Path(workspace).resolve()
    sessions_dir = ws / ".ai-orchestration" / "sessions"
    if not sessions_dir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for entry in sessions_dir.iterdir():
        if not entry.name.endswith(".json") or entry.name.startswith("."):
            continue
        try:
            data = _read_json_safe(entry)
            data["status"] = compute_session_status(data, stale_timeout_sec=stale_timeout_sec)
        except Exception:
            continue

        if role is not None and data.get("role") != role:
            continue
        if tool is not None and data.get("tool") != tool:
            continue
        if status is not None and status != "all":
            if data.get("status") != status:
                continue

        results.append(data)

    results.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return results


def get_role_holder(
    workspace: pathlib.Path | str,
    role: str = "orchestrator",
    stale_timeout_sec: float = DEFAULT_STALE_TIMEOUT_SEC,
) -> dict[str, Any] | None:
    """Look up the current holder of a role (Spec §0, §0b, E10)."""
    ws = pathlib.Path(workspace).resolve()
    if role == "orchestrator":
        orch_file = ws / ".ai-orchestration" / "orchestrator.json"
        if orch_file.is_file():
            try:
                orch_doc = _read_json_safe(orch_file)
                cur = orch_doc.get("current", {})
                sess_id = cur.get("session_id")
                session_obj: dict[str, Any] | None = None
                if sess_id:
                    try:
                        session_obj = get_session(ws, sess_id, stale_timeout_sec=stale_timeout_sec)
                    except FileNotFoundError:
                        session_obj = None

                return {
                    "role": "orchestrator",
                    "role_id": "orchestrator",
                    "generation": orch_doc.get("generation", 1),
                    "cursor": orch_doc.get("cursor", 0),
                    "session_id": sess_id,
                    "registry_session_id": sess_id,
                    "provider_session_id": cur.get("provider_session_id"),
                    "tool": cur.get("tool"),
                    "status": session_obj.get("status") if session_obj else cur.get("status", "unknown"),
                    "current": cur,
                    "session": session_obj,
                }
            except Exception as e:
                logger.warning(f"Failed to read orchestrator.json: {e}")

    # Fallback: scan sessions directory for active holder of role
    candidates = list_sessions(ws, role=role, status="active", stale_timeout_sec=stale_timeout_sec)
    if candidates:
        active_sess = candidates[0]
        return {
            "role": role,
            "role_id": role,
            "generation": active_sess.get("generation", 1),
            "cursor": active_sess.get("cursor", 0),
            "session_id": active_sess.get("session_id"),
            "registry_session_id": active_sess.get("session_id"),
            "provider_session_id": active_sess.get("provider_session_id"),
            "tool": active_sess.get("tool"),
            "status": active_sess.get("status"),
            "session": active_sess,
        }

    return None


def get_pending_work(
    workspace: pathlib.Path | str,
    session_id: str,
    stale_timeout_sec: float = DEFAULT_STALE_TIMEOUT_SEC,
) -> list[dict[str, Any]]:
    """Get pending events for a session per Spec §2:

    Events after its cursor that match its subscriptions,
    or whose subject/origin_session has origin-session = this session.
    """
    ws = pathlib.Path(workspace).resolve()
    sess = get_session(ws, session_id, stale_timeout_sec=stale_timeout_sec)
    cursor = int(sess.get("cursor", 0))
    subscriptions = sess.get("subscriptions", [])

    events = read_events(ws, since=cursor)
    pending: list[dict[str, Any]] = []

    for ev in events:
        ev_seq = int(ev.get("seq", 0))
        if ev_seq <= cursor:
            continue
        is_origin = (
            ev.get("origin_session") == session_id
            or ev.get("session") == session_id
            or ev.get("subject") == session_id
        )
        if is_origin or matches_subscription(ev, subscriptions):
            pending.append(ev)

    return pending


# ---------------------------------------------------------------------------
# CLI Parser & Entrypoint
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-orch sessions",
        description="Session registry, identifiers, role holders and cursors for ai-orchestration.",
    )
    parser.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    sub = parser.add_subparsers(dest="subcommand", required=True)

    # register
    reg = sub.add_parser("register", help="Register a new orchestration session")
    reg.add_argument("--tool", "-t", default="claude", help="Tool: claude, kilo, codex, human (default: claude)")
    reg.add_argument("--kind", "-k", default="headless", choices=["headless", "interactive"], help="Session kind")
    reg.add_argument("--role", "-r", default=None, help="Role name, e.g. orchestrator")
    reg.add_argument("--resume-id", help="Underlying provider session ID for resumption")
    reg.add_argument("--provider-session-id", help="Alias for --resume-id")
    reg.add_argument("--session-id", "--id", help="Pre-assigned session ID")
    reg.add_argument("--cwd", help="Working directory for headless resumption")
    reg.add_argument("--subscribe", "--subscriptions", nargs="*", default=[], help="Event subscription patterns")
    reg.add_argument("--cursor", type=int, default=None, help="Initial cursor sequence number")
    reg.add_argument("--reason", help="Reason for registration or succession")
    reg.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    reg.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # heartbeat
    hb = sub.add_parser("heartbeat", help="Send a heartbeat for an active session")
    hb.add_argument("session_id", nargs="?", default=None, help="Session ID")
    hb.add_argument("--session", "--id", dest="session_opt", help="Session ID option")
    hb.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    hb.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # list
    ls = sub.add_parser("list", help="List registered sessions")
    ls.add_argument("--role", "-r", help="Filter by role")
    ls.add_argument("--status", choices=["active", "stale", "retired", "deregistered", "all"], help="Filter by status")
    ls.add_argument("--tool", "-t", help="Filter by tool")
    ls.add_argument("--stale-timeout", type=float, default=DEFAULT_STALE_TIMEOUT_SEC, help="Staleness threshold in seconds")
    ls.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    ls.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # show
    sh = sub.add_parser("show", help="Show details of a session or role holder")
    sh.add_argument("session_id", nargs="?", default=None, help="Session ID")
    sh.add_argument("--session", "--id", dest="session_opt", help="Session ID option")
    sh.add_argument("--role", "-r", help="Show role holder, e.g. orchestrator")
    sh.add_argument("--stale-timeout", type=float, default=DEFAULT_STALE_TIMEOUT_SEC, help="Staleness threshold in seconds")
    sh.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    sh.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # cursor / ack
    cur = sub.add_parser("cursor", help="Get or advance session or role cursor")
    cur.add_argument("session_id", nargs="?", default=None, help="Session ID")
    cur.add_argument("--session", "--id", dest="session_opt", help="Session ID option")
    cur.add_argument("--role", "-r", help="Role name, e.g. orchestrator")
    cur.add_argument("--seq", type=int, default=None, help="Sequence number to advance cursor to")
    cur.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    cur.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    ack = sub.add_parser("ack", help="Alias for cursor --seq")
    ack.add_argument("session_id", nargs="?", default=None, help="Session ID")
    ack.add_argument("--session", "--id", dest="session_opt", help="Session ID option")
    ack.add_argument("--role", "-r", help="Role name, e.g. orchestrator")
    ack.add_argument("--seq", type=int, required=True, help="Sequence number to advance cursor to")
    ack.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    ack.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # deregister / end
    dreg = sub.add_parser("deregister", help="Deregister and end a session")
    dreg.add_argument("session_id", nargs="?", default=None, help="Session ID")
    dreg.add_argument("--session", "--id", dest="session_opt", help="Session ID option")
    dreg.add_argument("--reason", default="normal_exit", help="Reason for ending session")
    dreg.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    dreg.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    end = sub.add_parser("end", help="Alias for deregister")
    end.add_argument("session_id", nargs="?", default=None, help="Session ID")
    end.add_argument("--session", "--id", dest="session_opt", help="Session ID option")
    end.add_argument("--reason", default="normal_exit", help="Reason for ending session")
    end.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    end.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # role lookup
    rl = sub.add_parser("role", help="Look up role holder details")
    rl.add_argument("role_name", nargs="?", default="orchestrator", help="Role name (default: orchestrator)")
    rl.add_argument("--stale-timeout", type=float, default=DEFAULT_STALE_TIMEOUT_SEC, help="Staleness threshold in seconds")
    rl.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    rl.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    ws_arg = getattr(args, "workspace", None) or os.getcwd()
    workspace = pathlib.Path(ws_arg).resolve()
    is_json = bool(getattr(args, "json", False))

    try:
        if args.subcommand == "register":
            sess = register_session(
                workspace,
                tool=args.tool,
                kind=args.kind,
                role=args.role,
                provider_session_id=args.provider_session_id or args.resume_id,
                session_id=args.session_id,
                cwd=args.cwd,
                subscriptions=args.subscribe,
                cursor=args.cursor,
                reason=args.reason,
            )
            if is_json:
                print(json.dumps(sess, indent=2))
            else:
                role_str = f" [role: {sess['role']}]" if sess.get("role") else ""
                print(f"Registered session {sess['session_id']}{role_str} ({sess['tool']}, {sess['kind']})")
            return 0

        elif args.subcommand == "heartbeat":
            sid = args.session_id or args.session_opt
            if not sid:
                print("Error: session_id is required", file=sys.stderr)
                return 2
            sess = heartbeat_session(workspace, sid)
            if is_json:
                print(json.dumps(sess, indent=2))
            else:
                print(f"Heartbeat updated for session {sid} (last_seen: {sess['last_seen']})")
            return 0

        elif args.subcommand == "list":
            sessions = list_sessions(
                workspace,
                role=args.role,
                status=args.status,
                tool=args.tool,
                stale_timeout_sec=args.stale_timeout,
            )
            if is_json:
                print(json.dumps(sessions, indent=2))
            else:
                if not sessions:
                    print("No sessions found.")
                else:
                    for s in sessions:
                        role_str = f" role={s['role']}" if s.get("role") else ""
                        gen_str = f" gen={s['generation']}" if s.get("generation") else ""
                        print(
                            f"  {s['session_id'][:12]}  tool={s['tool']:<8}  status={s['status']:<12}{role_str}{gen_str}  last_seen={s['last_seen']}"
                        )
            return 0

        elif args.subcommand == "show":
            sid = args.session_id or args.session_opt
            if args.role and not sid:
                holder = get_role_holder(workspace, role=args.role, stale_timeout_sec=args.stale_timeout)
                if not holder:
                    if is_json:
                        print(json.dumps({"error": f"No holder for role: {args.role}"}, indent=2))
                    else:
                        print(f"No active holder for role {args.role}")
                    return 1
                if is_json:
                    print(json.dumps(holder, indent=2))
                else:
                    print(f"Role: {holder['role']} (generation {holder['generation']}, cursor {holder['cursor']})")
                    print(f"Holder session: {holder['session_id']} (tool: {holder['tool']}, status: {holder['status']})")
                return 0

            if not sid:
                print("Error: session_id or --role is required", file=sys.stderr)
                return 2

            sess = get_session(workspace, sid, stale_timeout_sec=args.stale_timeout)
            if is_json:
                print(json.dumps(sess, indent=2))
            else:
                print(f"Session: {sess['session_id']}")
                print(f"  Tool: {sess['tool']} ({sess['kind']})")
                if sess.get("role"):
                    print(f"  Role: {sess['role']} (generation: {sess.get('generation')})")
                print(f"  Status: {sess['status']}")
                print(f"  Cursor: {sess.get('cursor', 0)}")
                print(f"  Last seen: {sess.get('last_seen')}")
                if sess.get("subscriptions"):
                    print(f"  Subscriptions: {', '.join(sess['subscriptions'])}")
            return 0

        elif args.subcommand in ("cursor", "ack"):
            sid = args.session_id or args.session_opt
            role = args.role
            seq = args.seq

            if seq is not None:
                new_cursor = advance_cursor(workspace, seq=seq, session_id=sid, role=role)
                if is_json:
                    print(json.dumps({"cursor": new_cursor, "target": sid or role}, indent=2))
                else:
                    target_name = f"role {role}" if role else f"session {sid}"
                    print(f"Advanced cursor for {target_name} to {new_cursor}")
                return 0
            else:
                cur_val = get_cursor(workspace, session_id=sid, role=role)
                if is_json:
                    print(json.dumps({"cursor": cur_val, "target": sid or role}, indent=2))
                else:
                    target_name = f"role {role}" if role else f"session {sid}"
                    print(f"Current cursor for {target_name}: {cur_val}")
                return 0

        elif args.subcommand in ("deregister", "end"):
            sid = args.session_id or args.session_opt
            if not sid:
                print("Error: session_id is required", file=sys.stderr)
                return 2
            sess = deregister_session(workspace, sid, reason=args.reason)
            if is_json:
                print(json.dumps(sess, indent=2))
            else:
                print(f"Deregistered session {sid} (reason: {args.reason})")
            return 0

        elif args.subcommand == "role":
            role_name = args.role_name or "orchestrator"
            holder = get_role_holder(workspace, role=role_name, stale_timeout_sec=args.stale_timeout)
            if not holder:
                if is_json:
                    print(json.dumps({"error": f"No holder for role: {role_name}"}, indent=2))
                else:
                    print(f"No holder found for role: {role_name}")
                return 1
            if is_json:
                print(json.dumps(holder, indent=2))
            else:
                print(f"Role: {holder['role']} (generation: {holder['generation']}, cursor: {holder['cursor']})")
                print(f"Current session: {holder['session_id']} (tool: {holder['tool']}, status: {holder['status']})")
            return 0

        else:
            parser.print_help()
            return 2

    except Exception as exc:
        if is_json:
            print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
