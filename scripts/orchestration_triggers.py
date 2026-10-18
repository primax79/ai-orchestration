#!/usr/bin/env python3
"""orchestration_triggers.py — Trigger engine, event matching, batching and reduced-capability policy.

Implements:
  - Spec §5 (trigger rules, configuration in orchestration.toml, matching, actions, safety)
  - Spec §0c E2 (deliveries as immutable batches, role cursor, at-least-once delivery, idempotency)
  - Spec §0c E3 (reduced-capability policy for unattended trigger turns: safe read-mostly,
                 proposing actions with hashes instead of direct execution for agent launches/mutations)
  - Spec §0c E7 (trigger state per (rule, event): pending, fired, skipped, retry, dead;
                 deterministic firing IDs; watermark advances only when rules reach terminal states;
                 singleton daemon with lock/lease; persisted token buckets for rate limiting)
  - Commands: `ai-orch triggers run-once`, `ai-orch triggers daemon`, `ai-orch triggers list`,
              `ai-orch triggers status`, `ai-orch triggers history`
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fnmatch
import hashlib
import json
import logging
import os
import pathlib
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterator
import uuid

try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None  # type: ignore

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
from orchestration_sessions import (
    advance_cursor,
    get_cursor,
    get_role_holder,
    session_lock,
)
from orchestration_orchestrator import (
    advance_trigger_scan_cursor,
    enqueue_turn,
    get_delivery_cursor,
    get_trigger_scan_cursor,
)

logger = logging.getLogger("orchestration_triggers")

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_MAX_PER_HOUR = 6
DEFAULT_BATCH_SIZE = 100
MAX_LOOP_DEPTH = 3

TERMINAL_STATES = {"fired", "skipped", "dead"}
NON_TERMINAL_STATES = {"pending", "retry"}
ALLOWED_ACTIONS = {"notify", "resume-origin", "start-run", "command", "enqueue-turn"}
NOTE_ID_RE = re.compile(r"^N\d{3,}$")

# Thread-safety & in-process re-entrancy tracking for trigger lock
_TRIGGER_LOCK_COUNTS: dict[str, int] = {}
_TRIGGER_LOCK_FDS: dict[str, int] = {}
_TRIGGER_THREAD_LOCKS: dict[str, threading.RLock] = {}
_TRIGGER_GLOBAL_LOCK = threading.Lock()

# Thread-safety for daemon lock
_DAEMON_LOCK_COUNTS: dict[str, int] = {}
_DAEMON_LOCK_FDS: dict[str, int] = {}
_DAEMON_THREAD_LOCKS: dict[str, threading.RLock] = {}


def _get_thread_lock(lock_dict: dict[str, threading.RLock], lock_key: str) -> threading.RLock:
    with _TRIGGER_GLOBAL_LOCK:
        if lock_key not in lock_dict:
            lock_dict[lock_key] = threading.RLock()
        return lock_dict[lock_key]


# ---------------------------------------------------------------------------
# Locking & Atomic Helpers
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def trigger_lock(workspace: pathlib.Path | str):
    """Exclusive fcntl.flock on <workspace>/.ai-orchestration/triggers/.lock."""
    plat_err = check_platform()
    if plat_err:
        raise RuntimeError("Triggers engine is supported on macOS and Linux only (fcntl required)")

    ws = pathlib.Path(workspace).resolve()
    trig_dir = ws / ".ai-orchestration" / "triggers"
    trig_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(trig_dir, 0o700)
    except OSError:
        pass

    lock_file = trig_dir / ".lock"
    lock_key = str(lock_file.resolve())
    thread_lock = _get_thread_lock(_TRIGGER_THREAD_LOCKS, lock_key)

    with thread_lock:
        count = _TRIGGER_LOCK_COUNTS.get(lock_key, 0)
        if count > 0:
            _TRIGGER_LOCK_COUNTS[lock_key] = count + 1
            try:
                yield
            finally:
                _TRIGGER_LOCK_COUNTS[lock_key] -= 1
                if _TRIGGER_LOCK_COUNTS[lock_key] == 0:
                    _TRIGGER_LOCK_COUNTS.pop(lock_key, None)
            return

        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            _TRIGGER_LOCK_COUNTS[lock_key] = 1
            _TRIGGER_LOCK_FDS[lock_key] = fd
            yield
        finally:
            _TRIGGER_LOCK_COUNTS.pop(lock_key, None)
            _TRIGGER_LOCK_FDS.pop(lock_key, None)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)


@contextlib.contextmanager
def daemon_lock(workspace: pathlib.Path | str, non_blocking: bool = False):
    """Exclusive fcntl.flock on <workspace>/.ai-orchestration/triggers/.daemon.lock."""
    plat_err = check_platform()
    if plat_err:
        raise RuntimeError("Triggers engine is supported on macOS and Linux only (fcntl required)")

    ws = pathlib.Path(workspace).resolve()
    trig_dir = ws / ".ai-orchestration" / "triggers"
    trig_dir.mkdir(parents=True, exist_ok=True)

    lock_file = trig_dir / ".daemon.lock"
    lock_key = str(lock_file.resolve())
    thread_lock = _get_thread_lock(_DAEMON_THREAD_LOCKS, lock_key)

    with thread_lock:
        count = _DAEMON_LOCK_COUNTS.get(lock_key, 0)
        if count > 0:
            if non_blocking:
                raise BlockingIOError("Daemon lock is already held in this process")
            _DAEMON_LOCK_COUNTS[lock_key] = count + 1
            try:
                yield
            finally:
                _DAEMON_LOCK_COUNTS[lock_key] -= 1
                if _DAEMON_LOCK_COUNTS[lock_key] == 0:
                    _DAEMON_LOCK_COUNTS.pop(lock_key, None)
            return

        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if non_blocking else 0)
                fcntl.flock(fd, flags)
            _DAEMON_LOCK_COUNTS[lock_key] = 1
            _DAEMON_LOCK_FDS[lock_key] = fd
            yield
        finally:
            _DAEMON_LOCK_COUNTS.pop(lock_key, None)
            _DAEMON_LOCK_FDS.pop(lock_key, None)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)


def _write_json_atomic(path: pathlib.Path, data: Any) -> None:
    """Write JSON data to path atomically using tempfile + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".tmp.{path.name}.{os.getpid()}.{uuid.uuid4().hex}"
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _read_json_safe(path: pathlib.Path) -> Any:
    """Read and parse JSON file, raising FileNotFoundError if absent."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Configuration Loading & Validation (Spec §5)
# ---------------------------------------------------------------------------

def validate_trigger_rule(rule: dict[str, Any]) -> list[str]:
    """Validate a single trigger rule. Returns a list of validation error strings."""
    errors: list[str] = []

    name = rule.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        errors.append("Trigger rule missing required non-empty string 'name'")
    elif not name.replace("-", "").replace("_", "").isalnum():
        errors.append(f"Trigger rule name '{name}' must contain only alphanumeric characters, dashes, or underscores")

    on_event = rule.get("on")
    if not on_event or not isinstance(on_event, str) or not on_event.strip():
        errors.append(f"Trigger rule '{name or 'unnamed'}' missing required non-empty string 'on'")

    action = rule.get("action")
    if not action or action not in ALLOWED_ACTIONS:
        errors.append(
            f"Trigger rule '{name or 'unnamed'}' has invalid action '{action}'. "
            f"Allowed actions: {sorted(ALLOWED_ACTIONS)}"
        )

    if action == "command":
        cmd = rule.get("command")
        if not cmd:
            errors.append(f"Trigger rule '{name}' with action 'command' must specify 'command'")
        elif isinstance(cmd, list):
            if not cmd or not all(isinstance(x, str) for x in cmd):
                errors.append(f"Trigger rule '{name}' 'command' list must contain strings")
            elif cmd[0] not in ("ai-orch", "./bin/ai-orch", "bin/ai-orch") and not cmd[0].endswith("/ai-orch"):
                # Safety check: arbitrary shell is out of scope (Spec §5, §7)
                errors.append(f"Trigger rule '{name}' command must invoke 'ai-orch' subcommand (arbitrary shell disallowed)")
        elif isinstance(cmd, str):
            cmd_parts = cmd.strip().split()
            if not cmd_parts or (cmd_parts[0] not in ("ai-orch", "./bin/ai-orch", "bin/ai-orch") and not cmd_parts[0].endswith("/ai-orch")):
                errors.append(f"Trigger rule '{name}' command must invoke 'ai-orch' subcommand (arbitrary shell disallowed)")
        else:
            errors.append(f"Trigger rule '{name}' 'command' must be a list of strings or string")

    elif action == "start-run":
        run_block = rule.get("run")
        if not run_block or not isinstance(run_block, dict):
            errors.append(f"Trigger rule '{name}' with action 'start-run' must specify 'run' table")

    when = rule.get("when")
    if when is not None and not isinstance(when, dict):
        errors.append(f"Trigger rule '{name}' 'when' must be a key-value mapping")

    max_ph = rule.get("max_per_hour")
    if max_ph is not None and (not isinstance(max_ph, int) or max_ph <= 0):
        errors.append(f"Trigger rule '{name}' 'max_per_hour' must be a positive integer")

    return errors


def normalize_trigger_rule(raw_rule: dict[str, Any]) -> dict[str, Any]:
    """Normalize rule attributes, applying spec defaults."""
    action = raw_rule.get("action", "")
    # Spec §5 Safety: "every rule that launches an agent defaults to enabled = false"
    default_enabled = False if action == "start-run" else True

    rule = dict(raw_rule)
    rule["enabled"] = bool(raw_rule.get("enabled", default_enabled))
    rule["max_per_hour"] = int(raw_rule.get("max_per_hour", DEFAULT_MAX_PER_HOUR))
    if "when" in rule and isinstance(rule["when"], dict):
        rule["when"] = dict(rule["when"])
    else:
        rule["when"] = {}

    return rule


def find_config_files(workspace: pathlib.Path | str) -> list[pathlib.Path]:
    """Find candidate orchestration.toml files in order of precedence."""
    ws = pathlib.Path(workspace).resolve()
    candidates: list[pathlib.Path] = []

    # 1. Local unversioned project config inside repo
    local_dot = ws / ".ai-orchestration.local.toml"
    if local_dot.is_file():
        candidates.append(local_dot)

    # 2. Project config directly in repo root (if present)
    repo_cfg = ws / "orchestration.toml"
    if repo_cfg.is_file() and repo_cfg not in candidates:
        candidates.append(repo_cfg)

    # 3. Project config in ~/.config/ai-orchestration/projects/<name>/orchestration.toml
    proj_dir = pathlib.Path.home() / ".config" / "ai-orchestration" / "projects" / ws.name / "orchestration.toml"
    if proj_dir.is_file() and proj_dir not in candidates:
        candidates.append(proj_dir)

    # 4. Global config in ~/.config/ai-orchestration/orchestration.toml (or env var)
    env_gpath = os.environ.get("AI_ORCHESTRATION_CONFIG")
    if env_gpath:
        gpath = pathlib.Path(env_gpath).expanduser().resolve()
    else:
        gpath = pathlib.Path.home() / ".config" / "ai-orchestration" / "orchestration.toml"
    if gpath.is_file() and gpath not in candidates:
        candidates.append(gpath)

    return candidates


def load_triggers_config(
    workspace: pathlib.Path | str,
    config_path: pathlib.Path | str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Load and validate trigger configuration.

    Returns:
      (meta, normalized_rules, validation_errors)
      where meta contains 'kill_switch_enabled', 'config_paths', etc.
    """
    ws = pathlib.Path(workspace).resolve()
    if tomllib is None:
        raise RuntimeError("Python 3.11+ (stdlib tomllib) is required to parse trigger configuration")

    cfg_paths = [pathlib.Path(config_path).resolve()] if config_path else find_config_files(ws)

    kill_switch_enabled = True
    raw_rules: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    validation_errors: list[str] = []

    for cp in cfg_paths:
        if not cp.is_file():
            continue
        try:
            data = tomllib.loads(cp.read_text(encoding="utf-8"))
        except Exception as e:
            validation_errors.append(f"Failed to parse TOML from {cp}: {e}")
            continue

        # Check global kill switch: [triggers] enabled = false (or triggers_enabled = false)
        trig_section = data.get("triggers")
        if isinstance(trig_section, dict):
            if "enabled" in trig_section:
                val = trig_section["enabled"]
                if isinstance(val, bool):
                    kill_switch_enabled = kill_switch_enabled and val
            # Might have rules nested under [triggers.rules] or rules = [...]
            rules_nested = trig_section.get("rules")
            if isinstance(rules_nested, list):
                for r in rules_nested:
                    if isinstance(r, dict):
                        raw_rules.append(r)
        elif isinstance(trig_section, list):
            # [[triggers]] array of tables
            for r in trig_section:
                if isinstance(r, dict):
                    raw_rules.append(r)

        # Also support [[trigger]]
        single_trig = data.get("trigger")
        if isinstance(single_trig, list):
            for r in single_trig:
                if isinstance(r, dict):
                    raw_rules.append(r)

        if "triggers_enabled" in data and isinstance(data["triggers_enabled"], bool):
            kill_switch_enabled = kill_switch_enabled and data["triggers_enabled"]

    # Validate rules
    normalized_rules: list[dict[str, Any]] = []
    for r in raw_rules:
        errs = validate_trigger_rule(r)
        if errs:
            validation_errors.extend(errs)
            continue

        name = r["name"]
        if name in seen_names:
            validation_errors.append(f"Duplicate trigger rule name: '{name}'")
            continue
        seen_names.add(name)

        normalized_rules.append(normalize_trigger_rule(r))

    meta = {
        "kill_switch_enabled": kill_switch_enabled,
        "config_paths": [str(p) for p in cfg_paths if p.is_file()],
        "rule_count": len(normalized_rules),
    }

    return meta, normalized_rules, validation_errors


# ---------------------------------------------------------------------------
# Matching & Filters (Spec §5)
# ---------------------------------------------------------------------------

def _extract_field(event: dict[str, Any], field: str) -> Any:
    """Extract a field value from event payload/data or top-level event."""
    data = event.get("data")
    if isinstance(data, dict) and field in data:
        return data[field]

    payload = event.get("payload")
    if isinstance(payload, dict) and field in payload:
        return payload[field]

    if field in event:
        return event[field]

    return None


def matches_event_type(pattern: str, event_type: str) -> bool:
    """Match event type string against pattern (supporting exact match or wildcards like * or task.*).

    The wildcard '*' matches all domain events, excluding internal 'trigger.*' events
    to prevent cascade loops unless explicitly requested.
    """
    if pattern == event_type:
        return True
    if pattern == "*":
        return not event_type.startswith("trigger.")
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return event_type.startswith(prefix + ".")
    return fnmatch.fnmatch(event_type, pattern)


def matches_filter(when_filter: dict[str, Any], event: dict[str, Any]) -> bool:
    """Check if all key-value matchers in when_filter match the event."""
    if not when_filter:
        return True

    for key, expected in when_filter.items():
        actual = _extract_field(event, key)

        if expected == "*":
            # Wildcard: field must be present and not None / empty / "-"
            if actual is None or actual == "" or actual == "-":
                return False
        elif isinstance(expected, str) and ("*" in expected or "?" in expected):
            if actual is None or not fnmatch.fnmatch(str(actual), expected):
                return False
        else:
            if actual != expected and str(actual) != str(expected):
                return False

    return True


def check_loop_guard(rule_name: str, event: dict[str, Any]) -> bool:
    """Check loop guard per Spec §5.

    "an event caused by a trigger-launched run carries cause, and a rule never
    fires on its own descendants beyond depth 3"
    Returns True if allowed to fire, False if recursion limit exceeded.
    """
    cause = _extract_field(event, "cause")
    if not cause:
        return True

    # Cause can be a dict: {"trigger": "rule_name", "depth": int}
    # or list of ancestor trigger names / firing IDs
    if isinstance(cause, dict):
        ancestor = cause.get("trigger") or cause.get("rule")
        depth = cause.get("depth", 1)
        if ancestor == rule_name and depth >= MAX_LOOP_DEPTH:
            logger.warning("Loop guard: skipping rule '%s' due to cause depth %d", rule_name, depth)
            return False
    elif isinstance(cause, list):
        occurrences = sum(1 for c in cause if (isinstance(c, str) and rule_name in c) or (isinstance(c, dict) and c.get("rule") == rule_name))
        if occurrences >= MAX_LOOP_DEPTH:
            logger.warning("Loop guard: skipping rule '%s' due to %d cause occurrences", rule_name, occurrences)
            return False
    elif isinstance(cause, str):
        if cause == rule_name or cause.startswith(f"{rule_name}:"):
            # Check for stacked causes e.g. rule:rule:rule
            depth = cause.split(":").count(rule_name)
            if depth >= MAX_LOOP_DEPTH:
                logger.warning("Loop guard: skipping rule '%s' due to string cause depth %d", rule_name, depth)
                return False

    return True


def matches_trigger(rule: dict[str, Any], event: dict[str, Any]) -> bool:
    """Evaluate whether an event matches a trigger rule (event type, when filter, loop guard)."""
    if not rule.get("enabled", True):
        return False

    ev_type = event.get("type", "")
    if not matches_event_type(rule.get("on", ""), ev_type):
        return False

    if not matches_filter(rule.get("when", {}), event):
        return False

    if not check_loop_guard(rule["name"], event):
        return False

    return True


# ---------------------------------------------------------------------------
# Rate Limiting (Token Buckets per E7)
# ---------------------------------------------------------------------------

def _load_rate_limits(workspace: pathlib.Path) -> dict[str, Any]:
    path = workspace / ".ai-orchestration" / "triggers" / "rate_limits.json"
    if not path.is_file():
        return {}
    try:
        return _read_json_safe(path)
    except Exception:
        return {}


def _save_rate_limits(workspace: pathlib.Path, limits: dict[str, Any]) -> None:
    path = workspace / ".ai-orchestration" / "triggers" / "rate_limits.json"
    _write_json_atomic(path, limits)


def check_and_consume_rate_limit(
    workspace: pathlib.Path,
    rule: dict[str, Any],
    now_ts: float | None = None,
) -> tuple[bool, str | None]:
    """Check and consume one token from persisted token buckets (E7).

    Returns (allowed, not_before_iso).
    Must be called under trigger_lock.
    """
    now = now_ts or time.time()
    rule_name = rule["name"]
    max_per_hour = rule.get("max_per_hour", DEFAULT_MAX_PER_HOUR)
    refill_rate_per_sec = max_per_hour / 3600.0

    limits = _load_rate_limits(workspace)
    bucket = limits.get(rule_name, {})

    tokens = float(bucket.get("tokens", max_per_hour))
    last_update = float(bucket.get("last_update", now))

    # Refill tokens based on elapsed time
    elapsed = max(0.0, now - last_update)
    tokens = min(float(max_per_hour), tokens + (elapsed * refill_rate_per_sec))

    if tokens >= 1.0:
        tokens -= 1.0
        limits[rule_name] = {
            "tokens": tokens,
            "last_update": now,
        }
        _save_rate_limits(workspace, limits)
        return True, None
    else:
        # Calculate when next token will be available
        needed = 1.0 - tokens
        wait_sec = needed / refill_rate_per_sec
        not_before = datetime.datetime.fromtimestamp(now + wait_sec, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        return False, not_before


# ---------------------------------------------------------------------------
# Deterministic Firing ID & State per (Rule, Event) - E7
# ---------------------------------------------------------------------------

def make_firing_id(rule_name: str, event_seq: int, event_id: str) -> str:
    """Generate a deterministic firing ID for a (rule, event) pair."""
    short_hash = hashlib.sha256(f"{rule_name}:{event_id}".encode("utf-8")).hexdigest()[:8]
    return f"trig-{rule_name}-{event_seq}-{short_hash}"


def get_firing_record(workspace: pathlib.Path, firing_id: str) -> dict[str, Any] | None:
    """Retrieve firing record for a given firing_id, or None if not found."""
    firings_dir = workspace / ".ai-orchestration" / "triggers" / "firings"
    path = firings_dir / f"{firing_id}.json"
    if not path.is_file():
        return None
    try:
        return _read_json_safe(path)
    except Exception:
        return None


def save_firing_record(workspace: pathlib.Path, record: dict[str, Any]) -> None:
    """Persist firing record atomically."""
    firings_dir = workspace / ".ai-orchestration" / "triggers" / "firings"
    firings_dir.mkdir(parents=True, exist_ok=True)
    path = firings_dir / f"{record['firing_id']}.json"
    _write_json_atomic(path, record)


# ---------------------------------------------------------------------------
# Batching & Cursor per E2
# ---------------------------------------------------------------------------

def _load_batch(workspace: pathlib.Path, batch_id: str) -> dict[str, Any] | None:
    batch_file = workspace / ".ai-orchestration" / "triggers" / "batches" / f"{batch_id}.json"
    if not batch_file.is_file():
        return None
    try:
        return _read_json_safe(batch_file)
    except Exception:
        return None


def _save_batch(workspace: pathlib.Path, batch_data: dict[str, Any]) -> None:
    batch_dir = workspace / ".ai-orchestration" / "triggers" / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    batch_file = batch_dir / f"{batch_data['batch_id']}.json"
    _write_json_atomic(batch_file, batch_data)


def find_active_batch(workspace: pathlib.Path, role: str = "orchestrator") -> dict[str, Any] | None:
    """Find any outstanding unacknowledged batch (state in 'pending', 'running')."""
    batch_dir = workspace / ".ai-orchestration" / "triggers" / "batches"
    if not batch_dir.is_dir():
        return None

    for p in sorted(batch_dir.glob("*.json")):
        if p.name.startswith("."):
            continue
        try:
            bdata = _read_json_safe(p)
            if bdata.get("role") == role and bdata.get("state") in ("pending", "running"):
                return bdata
        except Exception:
            continue
    return None


def create_batch(
    workspace: pathlib.Path,
    events: list[dict[str, Any]],
    role: str = "orchestrator",
) -> dict[str, Any]:
    """Create an immutable delivery batch record per E2."""
    if not events:
        raise ValueError("Cannot create an empty batch")

    first_seq = events[0]["seq"]
    last_seq = events[-1]["seq"]
    batch_id = f"batch-{role}-{first_seq}-{last_seq}-{uuid.uuid4().hex[:8]}"

    batch_data = {
        "batch_id": batch_id,
        "role": role,
        "start_seq": first_seq,
        "end_seq": last_seq,
        "event_ids": [ev["id"] for ev in events],
        "event_seqs": [ev["seq"] for ev in events],
        "state": "pending",
        "created_at": _now_iso(),
        "acknowledged_at": None,
        "retries": 0,
    }
    _save_batch(workspace, batch_data)
    return batch_data


# ---------------------------------------------------------------------------
# Reduced-Capability Policy (E3) & Action Execution
# ---------------------------------------------------------------------------

def execute_action(
    workspace: pathlib.Path,
    rule: dict[str, Any],
    event: dict[str, Any],
    firing_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a trigger action conforming to E3 reduced-capability policy.

    Safe read actions and notify are executed directly.
    Unsafe mutating actions and agent launches (start-run) are proposed as
    'proposed_action' records with a cryptographic hash for UI confirmation.
    """
    action = rule["action"]
    rule_name = rule["name"]

    if dry_run:
        return {
            "status": "dry_run",
            "action": action,
            "rule": rule_name,
            "event_seq": event.get("seq"),
            "event_id": event.get("id"),
        }

    # 1. Action: notify
    if action == "notify":
        notif_id = str(uuid.uuid4())
        notif_dir = workspace / ".ai-orchestration" / "notifications"
        notif_dir.mkdir(parents=True, exist_ok=True)

        notif_payload = {
            "id": notif_id,
            "rule": rule_name,
            "event_seq": event.get("seq"),
            "event_type": event.get("type"),
            "subject": event.get("subject"),
            "data": event.get("data") or event.get("payload"),
            "created_at": _now_iso(),
            "read": False,
        }
        notif_path = notif_dir / f"{notif_id}.json"
        _write_json_atomic(notif_path, notif_payload)

        return {
            "status": "notified",
            "notification_id": notif_id,
        }

    # 2. Action: resume-origin
    elif action == "resume-origin":
        # Spec §0 / §5: "origin-session on questions, runs and notes is orchestrator (the role)...
        # resume-origin therefore means 'enqueue a turn for the orchestrator', or 'continue the run' when origin is a run."
        origin_run = _extract_field(event, "origin_run")
        origin_session = event.get("origin_session") or _extract_field(event, "origin_session") or "orchestrator"

        if origin_run and origin_run != "-":
            # Resuming a run: under E3, proposals requiring execution are recorded
            action_id = str(uuid.uuid4())
            hash_input = f"resume-run:{origin_run}:{event['id']}"
            action_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            prop_dir = workspace / ".ai-orchestration" / "proposed_actions"
            prop_dir.mkdir(parents=True, exist_ok=True)
            prop_data = {
                "action_id": action_id,
                "action_hash": action_hash,
                "type": "resume-run",
                "origin_run": origin_run,
                "rule": rule_name,
                "subject": event.get("subject"),
                "trigger_event": event["id"],
                "trigger_seq": event["seq"],
                "trigger_subject": event.get("subject"),
                "created_at": _now_iso(),
                "status": "pending_confirmation",
            }
            _write_json_atomic(prop_dir / f"{action_id}.json", prop_data)

            return {
                "status": "proposed",
                "type": "resume-run",
                "action_id": action_id,
                "action_hash": action_hash,
                "origin_run": origin_run,
            }
        else:
            # Enqueue a turn for the orchestrator role (Spec §0)
            return _enqueue_orchestrator_turn(workspace, rule_name, event)

    # 3. Action: enqueue-turn
    elif action == "enqueue-turn":
        return _enqueue_orchestrator_turn(workspace, rule_name, event)

    # 4. Action: start-run
    elif action == "start-run":
        # Under E3: "anything that would launch an agent must go through the reduced-capability policy of E3
        # and be recorded, not executed directly if the spec says turns are 12.5's job"
        run_params = rule.get("run", {})
        action_id = str(uuid.uuid4())
        serialized_params = json.dumps(run_params, sort_keys=True)
        action_hash = hashlib.sha256(serialized_params.encode("utf-8")).hexdigest()

        prop_dir = workspace / ".ai-orchestration" / "proposed_actions"
        prop_dir.mkdir(parents=True, exist_ok=True)

        task_id = run_params.get("task") or event.get("subject") or (event.get("data") or {}).get("task")
        proposed_plan_hash = None
        if task_id:
            try:
                own_bin = pathlib.Path(__file__).resolve().parent.parent / "bin" / "ai-orch"
                target_flag = "--note" if NOTE_ID_RE.match(str(task_id)) else "--task"
                p_cmd = [
                    sys.executable,
                    str(own_bin),
                    "run",
                    "preview",
                    target_flag,
                    str(task_id),
                    "--workspace",
                    str(workspace),
                    "--json",
                ]
                if run_params.get("mode"):
                    p_cmd.extend(["--mode", str(run_params["mode"])])
                tool = run_params.get("tool")
                if tool and tool != "cross_agent_order":
                    p_cmd.extend(["--tool", str(tool)])
                for opt in ("profile", "model", "variant", "effort", "isolation", "target_run", "instructions"):
                    if run_params.get(opt):
                        p_cmd.extend([f"--{opt.replace('_', '-')}", str(run_params[opt])])
                for flag in ("allow_same_tool", "allow_dirty_base", "force", "keep_worktree"):
                    if run_params.get(flag):
                        p_cmd.append(f"--{flag.replace('_', '-')}")

                res = subprocess.run(p_cmd, cwd=str(workspace), capture_output=True, text=True, check=False)
                if res.returncode == 0:
                    p_data = json.loads(res.stdout)
                    proposed_plan_hash = p_data.get("plan_hash")
            except Exception:
                pass

        prop_data = {
            "action_id": action_id,
            "action_hash": action_hash,
            "type": "start-run",
            "rule": rule_name,
            "subject": event.get("subject"),
            "trigger_event": event["id"],
            "trigger_seq": event["seq"],
            "trigger_subject": event.get("subject"),
            "run_params": run_params,
            "created_at": _now_iso(),
            "status": "pending_confirmation",
            "policy": "reduced_capability",
        }
        if proposed_plan_hash:
            prop_data["plan_hash"] = proposed_plan_hash

        _write_json_atomic(prop_dir / f"{action_id}.json", prop_data)

        return {
            "status": "proposed",
            "type": "start-run",
            "action_id": action_id,
            "action_hash": action_hash,
            "run_params": run_params,
        }

    # 5. Action: command
    elif action == "command":
        cmd_raw = rule.get("command", [])
        cmd_list = cmd_raw if isinstance(cmd_raw, list) else cmd_raw.strip().split()

        # Check E3 policy on command:
        # Read-mostly policy: file read, ai-orch read commands, questions ask, notify
        subcmd = cmd_list[1] if len(cmd_list) > 1 else ""
        subsub = cmd_list[2] if len(cmd_list) > 2 else ""

        # Only `ai-orch` itself may run unattended: the sub-command checks below are
        # meaningless for any other program (e.g. ["rm", "events", "x"]).
        is_ai_orch = bool(cmd_list) and os.path.basename(str(cmd_list[0])) == "ai-orch"
        is_safe_command = is_ai_orch and (
            subcmd in ("events", "sessions", "session", "describe")
            or (subcmd == "tasks" and subsub in ("list", "validate", "graph", "labels"))
            or (subcmd == "inbox" and subsub in ("list", "show"))
            or (subcmd == "questions" and subsub in ("list", "show", "ask"))
            or (subcmd == "config" and subsub == "show")
        )

        if is_safe_command:
            try:
                # Run this repo's ai-orch with the current interpreter, not whatever
                # `ai-orch` the rule names or PATH resolves.
                own_bin = pathlib.Path(__file__).resolve().parent.parent / "bin" / "ai-orch"
                res = subprocess.run(
                    [sys.executable, str(own_bin), *[str(a) for a in cmd_list[1:]]],
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return {
                    "status": "executed",
                    "command": cmd_list,
                    "exit_code": res.returncode,
                    "stdout": res.stdout[:500],
                    "stderr": res.stderr[:500],
                }
            except Exception as e:
                return {
                    "status": "failed",
                    "command": cmd_list,
                    "error": str(e),
                }
        else:
            # Mutating command not allowed unattended under E3: propose it
            action_id = str(uuid.uuid4())
            action_hash = hashlib.sha256(" ".join(cmd_list).encode("utf-8")).hexdigest()

            prop_dir = workspace / ".ai-orchestration" / "proposed_actions"
            prop_dir.mkdir(parents=True, exist_ok=True)
            prop_data = {
                "action_id": action_id,
                "action_hash": action_hash,
                "type": "command",
                "command": cmd_list,
                "rule": rule_name,
                "subject": event.get("subject"),
                "trigger_event": event["id"],
                "trigger_seq": event["seq"],
                "trigger_subject": event.get("subject"),
                "created_at": _now_iso(),
                "status": "pending_confirmation",
                "reason": "mutating_command_requires_confirmation_under_e3",
            }
            _write_json_atomic(prop_dir / f"{action_id}.json", prop_data)

            return {
                "status": "proposed",
                "type": "command",
                "action_id": action_id,
                "action_hash": action_hash,
                "command": cmd_list,
            }

    return {"status": "unsupported_action", "action": action}


def _enqueue_orchestrator_turn(
    workspace: pathlib.Path | str,
    rule_name: str,
    event: dict[str, Any],
) -> dict[str, Any]:
    """Enqueue a turn request via canonical enqueue_turn under orchestrator lock (Spec §0, E6, T026)."""
    res = enqueue_turn(
        workspace,
        turn_type="event_batch",
        events=[event],
        trigger_rule=rule_name,
    )
    return {
        "status": "enqueued_turn",
        "turn_seq": res["turn_seq"],
        "turn_id": res["turn_id"],
        "turn": res.get("turn"),
    }


# ---------------------------------------------------------------------------
# Proposed Actions Management (Spec §0c E3, T024)
# ---------------------------------------------------------------------------

def list_proposals(
    workspace: pathlib.Path | str,
    status: str = "all",
) -> dict[str, Any]:
    """List proposed actions in <workspace>/.ai-orchestration/proposed_actions/ (Spec §0c E3, T024).

    Filter by status: pending (matches pending and pending_confirmation), confirmed, rejected, or all.
    """
    ws = pathlib.Path(workspace).resolve()
    prop_dir = ws / ".ai-orchestration" / "proposed_actions"
    if not prop_dir.is_dir():
        return {
            "ok": True,
            "count": 0,
            "proposals": [],
            "proposed_actions": [],
        }

    records: list[dict[str, Any]] = []
    norm_status = (status or "all").lower().strip()
    if norm_status == "pending_confirmation":
        norm_status = "pending"

    for p in sorted(prop_dir.glob("*.json")):
        if p.name.startswith("."):
            continue
        try:
            rec = _read_json_safe(p)
            rec_status = rec.get("status", "")
            if norm_status == "all":
                records.append(rec)
            elif norm_status == "pending" and rec_status in ("pending", "pending_confirmation"):
                records.append(rec)
            elif norm_status == rec_status:
                records.append(rec)
        except Exception:
            continue

    records.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return {
        "ok": True,
        "count": len(records),
        "proposals": records,
        "proposed_actions": records,
    }


def confirm_action(
    workspace: pathlib.Path | str,
    action_id: str,
    expect_hash: str,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Confirm and execute a proposed action under the trigger lock (Spec §0c E3, T024).

    Refuses unless the proposal is pending and expect_hash matches proposal action_hash.
    Executes through the same paths an owner action would use:
      - start-run: runs preview to compute current plan_hash, validates it against any proposed
                   plan_hash or parameters, then runs start with --expect-plan-hash and --requested-by.
      - command: runs with repo's ai-orch only if argv[0] is ai-orch, otherwise refuses.
      - resume-run: resumes run with ai-orch run start --continue <origin_run>.
    Records outcome (status: confirmed, result, run_id) atomically and emits trigger.action_confirmed.
    """
    ws = pathlib.Path(workspace).resolve()
    ensure_git_exclude(ws)

    clean_id = action_id[:-5] if action_id.endswith(".json") else action_id
    prop_path = ws / ".ai-orchestration" / "proposed_actions" / f"{clean_id}.json"

    with trigger_lock(ws):
        if not prop_path.is_file():
            return {
                "ok": False,
                "error": "proposal_not_found",
                "action_id": clean_id,
                "message": f"Proposed action '{clean_id}' not found at {prop_path}",
            }

        try:
            proposal = _read_json_safe(prop_path)
        except Exception as e:
            return {
                "ok": False,
                "error": "proposal_read_error",
                "action_id": clean_id,
                "message": f"Failed reading proposed action '{clean_id}': {e}",
            }

        current_status = proposal.get("status", "")
        if current_status not in ("pending", "pending_confirmation"):
            return {
                "ok": False,
                "error": "not_pending",
                "action_id": clean_id,
                "status": current_status,
                "message": f"Proposed action '{clean_id}' is not pending (current status: {current_status})",
            }

        actual_hash = (proposal.get("action_hash") or "").strip().lower()
        if expect_hash.strip().lower() != actual_hash:
            return {
                "ok": False,
                "error": "hash_mismatch",
                "action_id": clean_id,
                "expected": expect_hash,
                "actual": proposal.get("action_hash"),
                "message": f"Action hash mismatch for '{clean_id}': expected '{expect_hash}', got '{proposal.get('action_hash')}'",
            }

        act_type = proposal.get("type")
        own_bin = pathlib.Path(__file__).resolve().parent.parent / "bin" / "ai-orch"

        # Path 1: start-run
        if act_type == "start-run":
            run_params = proposal.get("run_params", {})
            task_id = (
                run_params.get("task")
                or proposal.get("subject")
                or proposal.get("trigger_subject")
                or proposal.get("task_id")
            )
            if not task_id and proposal.get("trigger_seq"):
                try:
                    evs = read_events(ws, since=proposal["trigger_seq"] - 1, limit=5)
                    for ev in evs:
                        if ev.get("seq") == proposal["trigger_seq"] or ev.get("id") == proposal.get("trigger_event"):
                            task_id = ev.get("subject") or (ev.get("data") or {}).get("task")
                            break
                except Exception:
                    pass

            if not task_id:
                return {
                    "ok": False,
                    "error": "missing_target_task",
                    "action_id": clean_id,
                    "message": f"Cannot determine target task for proposed start-run action '{clean_id}'",
                }

            target_flag = "--note" if NOTE_ID_RE.match(str(task_id)) else "--task"
            if run_params.get("batch"):
                target_flag = "--batch"
                task_id = run_params["batch"]
            elif run_params.get("note"):
                target_flag = "--note"
                task_id = run_params["note"]

            # Step 1a: run preview
            preview_cmd = [
                sys.executable,
                str(own_bin),
                "run",
                "preview",
                target_flag,
                str(task_id),
                "--workspace",
                str(ws),
                "--json",
            ]
            if run_params.get("mode"):
                preview_cmd.extend(["--mode", str(run_params["mode"])])
            tool = run_params.get("tool")
            if tool and tool != "cross_agent_order":
                preview_cmd.extend(["--tool", str(tool)])
            for opt in ("profile", "model", "variant", "effort", "isolation", "target_run", "instructions"):
                if run_params.get(opt):
                    preview_cmd.extend([f"--{opt.replace('_', '-')}", str(run_params[opt])])
            for flag in ("allow_same_tool", "allow_dirty_base", "force", "keep_worktree"):
                if run_params.get(flag):
                    preview_cmd.append(f"--{flag.replace('_', '-')}")

            preview_proc = subprocess.run(preview_cmd, cwd=str(ws), capture_output=True, text=True, check=False)
            try:
                preview_data = json.loads(preview_proc.stdout)
            except Exception:
                preview_data = {"error": preview_proc.stderr or preview_proc.stdout}

            if preview_proc.returncode != 0:
                err_detail = preview_data.get("message") or preview_data.get("error") or preview_proc.stderr or "preview failed"
                return {
                    "ok": False,
                    "error": "preview_failed",
                    "action_id": clean_id,
                    "details": preview_data,
                    "message": f"Run preview failed: {err_detail}",
                }

            current_plan_hash = preview_data.get("plan_hash")
            if not current_plan_hash:
                return {
                    "ok": False,
                    "error": "preview_missing_plan_hash",
                    "action_id": clean_id,
                    "details": preview_data,
                    "message": "Run preview did not return a plan_hash",
                }

            # Step 1b: check if preview hash differs from what was proposed in a way that matters
            proposed_plan_hash = proposal.get("plan_hash") or run_params.get("plan_hash") or run_params.get("expect_plan_hash")
            if proposed_plan_hash and proposed_plan_hash.lower() != current_plan_hash.lower():
                return {
                    "ok": False,
                    "error": "plan_hash_mismatch",
                    "action_id": clean_id,
                    "message": (
                        f"Preview plan hash '{current_plan_hash}' differs from proposed plan hash '{proposed_plan_hash}' "
                        "(task or repository state changed since proposal was generated)"
                    ),
                    "proposed_plan_hash": proposed_plan_hash,
                    "current_plan_hash": current_plan_hash,
                }

            for check_field in ("mode", "tool", "profile", "model"):
                if run_params.get(check_field) and run_params[check_field] != "cross_agent_order":
                    if preview_data.get(check_field) and preview_data[check_field] != run_params[check_field]:
                        return {
                            "ok": False,
                            "error": f"{check_field}_mismatch",
                            "action_id": clean_id,
                            "message": f"Preview {check_field} '{preview_data[check_field]}' differs from proposed {check_field} '{run_params[check_field]}'",
                        }

            # Step 1c: run start
            start_cmd = [
                sys.executable,
                str(own_bin),
                "run",
                "start",
                target_flag,
                str(task_id),
                "--workspace",
                str(ws),
                "--expect-plan-hash",
                current_plan_hash,
                "--json",
            ]
            if run_params.get("mode"):
                start_cmd.extend(["--mode", str(run_params["mode"])])
            if tool and tool != "cross_agent_order":
                start_cmd.extend(["--tool", str(tool)])
            for opt in ("profile", "model", "variant", "effort", "isolation", "target_run", "instructions"):
                if run_params.get(opt):
                    start_cmd.extend([f"--{opt.replace('_', '-')}", str(run_params[opt])])
            for flag in ("allow_same_tool", "allow_dirty_base", "force", "keep_worktree"):
                if run_params.get(flag):
                    start_cmd.append(f"--{flag.replace('_', '-')}")

            req_by = "cli"
            if actor in ("ui", "vscode"):
                req_by = actor
            start_cmd.extend(["--requested-by", req_by])

            start_proc = subprocess.run(start_cmd, cwd=str(ws), capture_output=True, text=True, check=False)
            try:
                start_data = json.loads(start_proc.stdout)
            except Exception:
                start_data = {"error": start_proc.stderr or start_proc.stdout}

            if start_proc.returncode != 0:
                err_detail = start_data.get("message") or start_data.get("error") or start_proc.stderr or "run start failed"
                return {
                    "ok": False,
                    "error": "start_failed",
                    "action_id": clean_id,
                    "details": start_data,
                    "message": f"Run start failed: {err_detail}",
                }

            run_id = start_data.get("run_id")
            proposal["status"] = "confirmed"
            proposal["confirmed_at"] = _now_iso()
            if actor:
                proposal["confirmed_by"] = actor
            proposal["result"] = start_data
            if run_id:
                proposal["run_id"] = run_id
            _write_json_atomic(prop_path, proposal)

            try:
                emit(
                    ws,
                    "trigger.action_confirmed",
                    payload={
                        "action_id": clean_id,
                        "action_hash": proposal.get("action_hash"),
                        "type": "start-run",
                        "rule": proposal.get("rule"),
                        "run_id": run_id,
                        "result": start_data,
                        "actor": actor,
                    },
                    subject=clean_id,
                    origin_session=proposal.get("rule"),
                    actor=actor or "owner",
                )
            except Exception as e:
                logger.warning("Could not emit trigger.action_confirmed: %s", e)

            return {
                "ok": True,
                "action_id": clean_id,
                "status": "confirmed",
                "run_id": run_id,
                "result": start_data,
            }

        # Path 2: command
        elif act_type == "command":
            cmd_raw = proposal.get("command", [])
            cmd_list = cmd_raw if isinstance(cmd_raw, list) else cmd_raw.strip().split()

            is_ai_orch = bool(cmd_list) and os.path.basename(str(cmd_list[0])) == "ai-orch"
            if not is_ai_orch:
                return {
                    "ok": False,
                    "error": "disallowed_command",
                    "action_id": clean_id,
                    "message": f"Command '{cmd_list[0] if cmd_list else ''}' is disallowed. Only ai-orch commands may be confirmed and executed.",
                }

            res = subprocess.run(
                [sys.executable, str(own_bin), *[str(a) for a in cmd_list[1:]]],
                cwd=str(ws),
                capture_output=True,
                text=True,
                check=False,
            )
            cmd_result = {
                "command": cmd_list,
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
            proposal["status"] = "confirmed"
            proposal["confirmed_at"] = _now_iso()
            if actor:
                proposal["confirmed_by"] = actor
            proposal["result"] = cmd_result
            _write_json_atomic(prop_path, proposal)

            try:
                emit(
                    ws,
                    "trigger.action_confirmed",
                    payload={
                        "action_id": clean_id,
                        "action_hash": proposal.get("action_hash"),
                        "type": "command",
                        "rule": proposal.get("rule"),
                        "result": cmd_result,
                        "actor": actor,
                    },
                    subject=clean_id,
                    origin_session=proposal.get("rule"),
                    actor=actor or "owner",
                )
            except Exception as e:
                logger.warning("Could not emit trigger.action_confirmed: %s", e)

            return {
                "ok": res.returncode == 0,
                "action_id": clean_id,
                "status": "confirmed",
                "result": cmd_result,
            }

        # Path 3: resume-run
        elif act_type == "resume-run":
            origin_run = proposal.get("origin_run")
            if not origin_run:
                return {
                    "ok": False,
                    "error": "missing_origin_run",
                    "action_id": clean_id,
                    "message": "Proposal missing origin_run",
                }

            start_cmd = [
                sys.executable,
                str(own_bin),
                "run",
                "start",
                "--continue",
                origin_run,
                "--workspace",
                str(ws),
                "--json",
            ]
            req_by = "cli"
            if actor in ("ui", "vscode"):
                req_by = actor
            start_cmd.extend(["--requested-by", req_by])

            start_proc = subprocess.run(start_cmd, cwd=str(ws), capture_output=True, text=True, check=False)
            try:
                start_data = json.loads(start_proc.stdout)
            except Exception:
                start_data = {"error": start_proc.stderr or start_proc.stdout}

            if start_proc.returncode != 0:
                err_detail = start_data.get("message") or start_data.get("error") or start_proc.stderr or "run start failed"
                return {
                    "ok": False,
                    "error": "start_failed",
                    "action_id": clean_id,
                    "details": start_data,
                    "message": f"Run start --continue failed: {err_detail}",
                }

            run_id = start_data.get("run_id")
            proposal["status"] = "confirmed"
            proposal["confirmed_at"] = _now_iso()
            if actor:
                proposal["confirmed_by"] = actor
            proposal["result"] = start_data
            if run_id:
                proposal["run_id"] = run_id
            _write_json_atomic(prop_path, proposal)

            try:
                emit(
                    ws,
                    "trigger.action_confirmed",
                    payload={
                        "action_id": clean_id,
                        "action_hash": proposal.get("action_hash"),
                        "type": "resume-run",
                        "rule": proposal.get("rule"),
                        "run_id": run_id,
                        "result": start_data,
                        "actor": actor,
                    },
                    subject=clean_id,
                    origin_session=proposal.get("rule"),
                    actor=actor or "owner",
                )
            except Exception as e:
                logger.warning("Could not emit trigger.action_confirmed: %s", e)

            return {
                "ok": True,
                "action_id": clean_id,
                "status": "confirmed",
                "run_id": run_id,
                "result": start_data,
            }

        else:
            return {
                "ok": False,
                "error": "unsupported_action_type",
                "action_id": clean_id,
                "type": act_type,
                "message": f"Unsupported proposed action type '{act_type}'",
            }


def reject_action(
    workspace: pathlib.Path | str,
    action_id: str,
    reason: str,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Reject a proposed action with a reason under the trigger lock (Spec §0c E3, T024).

    Refuses unless the proposal is pending.
    Records rejected status and reason atomically, and emits trigger.action_rejected.
    """
    ws = pathlib.Path(workspace).resolve()
    ensure_git_exclude(ws)

    clean_id = action_id[:-5] if action_id.endswith(".json") else action_id
    prop_path = ws / ".ai-orchestration" / "proposed_actions" / f"{clean_id}.json"

    if not reason or not reason.strip():
        return {
            "ok": False,
            "error": "missing_reason",
            "action_id": clean_id,
            "message": "A non-empty reason is required to reject a proposed action",
        }

    with trigger_lock(ws):
        if not prop_path.is_file():
            return {
                "ok": False,
                "error": "proposal_not_found",
                "action_id": clean_id,
                "message": f"Proposed action '{clean_id}' not found at {prop_path}",
            }

        try:
            proposal = _read_json_safe(prop_path)
        except Exception as e:
            return {
                "ok": False,
                "error": "proposal_read_error",
                "action_id": clean_id,
                "message": f"Failed reading proposed action '{clean_id}': {e}",
            }

        current_status = proposal.get("status", "")
        if current_status not in ("pending", "pending_confirmation"):
            return {
                "ok": False,
                "error": "not_pending",
                "action_id": clean_id,
                "status": current_status,
                "message": f"Proposed action '{clean_id}' is not pending (current status: {current_status})",
            }

        clean_reason = reason.strip()
        proposal["status"] = "rejected"
        proposal["rejected_at"] = _now_iso()
        proposal["rejected_reason"] = clean_reason
        if actor:
            proposal["rejected_by"] = actor
        _write_json_atomic(prop_path, proposal)

        try:
            emit(
                ws,
                "trigger.action_rejected",
                payload={
                    "action_id": clean_id,
                    "action_hash": proposal.get("action_hash"),
                    "type": proposal.get("type"),
                    "rule": proposal.get("rule"),
                    "reason": clean_reason,
                    "actor": actor,
                },
                subject=clean_id,
                origin_session=proposal.get("rule"),
                actor=actor or "owner",
            )
        except Exception as e:
            logger.warning("Could not emit trigger.action_rejected: %s", e)

        return {
            "ok": True,
            "action_id": clean_id,
            "status": "rejected",
            "reason": clean_reason,
        }


# ---------------------------------------------------------------------------
# Core Trigger Engine Workflow (run_once)
# ---------------------------------------------------------------------------

def run_once(
    workspace: pathlib.Path | str,
    *,
    config_path: pathlib.Path | str | None = None,
    role: str = "orchestrator",
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute one scan pass over events since cursor.

    Steps:
      1. Load and validate configuration. If kill switch is off, return early.
      2. Under trigger_lock:
         a. Recover any active unacknowledged batch (E2), or read new events since role cursor.
         b. Evaluate matching rules against events.
         c. Check rate limits and execute actions with E3 reduced-capability policy.
         d. Record deterministic firing states (E7).
         e. Advance scan watermark and acknowledge batch only when applicable rules reach terminal states.
         f. Advance role cursor atomically and emit trigger.fired events.
    """
    ws = pathlib.Path(workspace).resolve()
    ensure_git_exclude(ws)

    # Step 1: Load and validate config
    meta, rules, validation_errors = load_triggers_config(ws, config_path=config_path)
    if validation_errors:
        return {
            "ok": False,
            "error": "config_validation_failed",
            "validation_errors": validation_errors,
        }

    if not meta.get("kill_switch_enabled", True):
        logger.info("Trigger engine kill switch is active ([triggers] enabled = false); skipping.")
        return {
            "ok": True,
            "status": "disabled_by_kill_switch",
            "events_processed": 0,
            "firings": [],
        }

    if not rules:
        return {
            "ok": True,
            "status": "no_rules_configured",
            "events_processed": 0,
            "firings": [],
        }

    # Step 2: Process batch under trigger_lock
    if dry_run:
        return _process_dry_run(ws, rules, role=role, batch_size=batch_size)

    with trigger_lock(ws):
        # Check for outstanding batch
        active_batch = find_active_batch(ws, role=role)

        if active_batch:
            # Resume processing outstanding batch
            event_seqs = active_batch.get("event_seqs", [])
            if event_seqs:
                # Read specific events for this batch
                min_seq = min(event_seqs)
                events = read_events(ws, since=min_seq - 1)
                events = [e for e in events if e.get("seq") in event_seqs]
            else:
                events = []
            batch_data = active_batch
            batch_data["retries"] = batch_data.get("retries", 0) + 1
            batch_data["state"] = "running"
            _save_batch(ws, batch_data)
        else:
            # Query trigger_scan cursor
            cursor = get_trigger_scan_cursor(ws, role=role)
            new_events = read_events(ws, since=cursor, limit=batch_size)
            if not new_events:
                return {
                    "ok": True,
                    "status": "up_to_date",
                    "cursor": cursor,
                    "trigger_scan_cursor": cursor,
                    "delivery_cursor": get_delivery_cursor(ws, role=role),
                    "events_processed": 0,
                    "firings": [],
                }

            # Create immutable batch per E2
            batch_data = create_batch(ws, new_events, role=role)
            batch_data["state"] = "running"
            _save_batch(ws, batch_data)
            events = new_events

        # Process events in the batch sequentially
        firings_summary: list[dict[str, Any]] = []
        highest_settled_seq = get_trigger_scan_cursor(ws, role=role)
        all_settled = True

        for ev in events:
            ev_seq = ev["seq"]
            ev_id = ev["id"]
            ev_settled = True

            matched_rules = [r for r in rules if matches_trigger(r, ev)]

            for rule in matched_rules:
                rule_name = rule["name"]
                firing_id = make_firing_id(rule_name, ev_seq, ev_id)

                # Check if firing record already exists (idempotency per E2/E7)
                existing = get_firing_record(ws, firing_id)
                if existing:
                    state = existing.get("state")
                    if state in TERMINAL_STATES:
                        firings_summary.append({
                            "firing_id": firing_id,
                            "rule": rule_name,
                            "event_seq": ev_seq,
                            "state": state,
                            "replayed": True,
                        })
                        continue

                # Check rate limit (E7)
                allowed, not_before = check_and_consume_rate_limit(ws, rule)
                if not allowed:
                    rec = {
                        "firing_id": firing_id,
                        "rule_name": rule_name,
                        "event_seq": ev_seq,
                        "event_id": ev_id,
                        "event_type": ev.get("type"),
                        "state": "retry",
                        "not_before": not_before,
                        "created_at": existing.get("created_at") if existing else _now_iso(),
                        "updated_at": _now_iso(),
                        "retries": (existing.get("retries", 0) + 1) if existing else 0,
                    }
                    save_firing_record(ws, rec)
                    ev_settled = False
                    firings_summary.append({
                        "firing_id": firing_id,
                        "rule": rule_name,
                        "event_seq": ev_seq,
                        "state": "retry",
                        "not_before": not_before,
                    })
                    continue

                # Execute action conforming to E3
                try:
                    result = execute_action(ws, rule, ev, firing_id, dry_run=False)
                    state = "fired"
                    err_msg = None
                except Exception as e:
                    logger.exception("Failed executing action for rule '%s' on event %d: %s", rule_name, ev_seq, e)
                    result = {"status": "error", "error": str(e)}
                    state = "retry"
                    err_msg = str(e)
                    ev_settled = False

                rec = {
                    "firing_id": firing_id,
                    "rule_name": rule_name,
                    "event_seq": ev_seq,
                    "event_id": ev_id,
                    "event_type": ev.get("type"),
                    "action": rule["action"],
                    "state": state,
                    "result": result,
                    "error": err_msg,
                    "created_at": existing.get("created_at") if existing else _now_iso(),
                    "updated_at": _now_iso(),
                    "retries": (existing.get("retries", 0) + 1) if existing else 0,
                }
                save_firing_record(ws, rec)

                # Emit trigger.fired event (Spec §5 line 206)
                try:
                    emit(
                        ws,
                        "trigger.fired",
                        payload={
                            "rule": rule_name,
                            "firing_id": firing_id,
                            "event_seq": ev_seq,
                            "event_id": ev_id,
                            "event_type": ev.get("type"),
                            "action": rule["action"],
                            "state": state,
                            "result": result,
                        },
                        subject=rule_name,
                        origin_session=role,
                        actor="trigger_engine",
                    )
                except Exception as emit_err:
                    logger.warning("Could not emit trigger.fired: %s", emit_err)

                firings_summary.append({
                    "firing_id": firing_id,
                    "rule": rule_name,
                    "event_seq": ev_seq,
                    "state": state,
                    "result": result,
                })

            if ev_settled and all_settled:
                highest_settled_seq = max(highest_settled_seq, ev_seq)
            else:
                all_settled = False

        # E7 scan watermark rule: advance trigger_scan cursor only when applicable rules reach terminal state (Spec §0c E2, E7, T026)
        if all_settled and events:
            # Whole batch settled: mark acknowledged
            batch_data["state"] = "acknowledged"
            batch_data["acknowledged_at"] = _now_iso()
            _save_batch(ws, batch_data)

            # Advance trigger_scan cursor (delivery cursor advances only after turn completion)
            last_seq = events[-1]["seq"]
            new_cursor = advance_trigger_scan_cursor(ws, seq=last_seq, role=role)
        elif highest_settled_seq > get_trigger_scan_cursor(ws, role=role):
            new_cursor = advance_trigger_scan_cursor(ws, seq=highest_settled_seq, role=role)
        else:
            new_cursor = get_trigger_scan_cursor(ws, role=role)

        # Store triggers cursor metadata
        _save_trigger_cursor(ws, role, new_cursor)

        return {
            "ok": True,
            "status": "acknowledged" if all_settled else "partial_settled",
            "batch_id": batch_data["batch_id"],
            "cursor": new_cursor,
            "trigger_scan_cursor": new_cursor,
            "delivery_cursor": get_delivery_cursor(ws, role=role),
            "events_processed": len(events),
            "firings": firings_summary,
        }


def _save_trigger_cursor(workspace: pathlib.Path | str, role: str, cursor: int) -> None:
    ws = pathlib.Path(workspace).resolve()
    cur_path = ws / ".ai-orchestration" / "triggers" / "cursor.json"
    cur_path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cur_path.is_file():
        try:
            data = _read_json_safe(cur_path)
        except Exception:
            data = {}
    rdata = data.get(role, {})
    deliv = rdata.get("delivery_cursor", get_delivery_cursor(ws, role=role))
    data[role] = {
        "cursor": cursor,
        "trigger_scan_cursor": cursor,
        "delivery_cursor": deliv,
        "updated_at": _now_iso(),
    }
    _write_json_atomic(cur_path, data)


def _process_dry_run(
    workspace: pathlib.Path,
    rules: list[dict[str, Any]],
    role: str = "orchestrator",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Execute dry-run scan without writing anything to disk."""
    cursor = get_trigger_scan_cursor(workspace, role=role)
    new_events = read_events(workspace, since=cursor, limit=batch_size)

    firings: list[dict[str, Any]] = []
    for ev in new_events:
        for rule in rules:
            if matches_trigger(rule, ev):
                firing_id = make_firing_id(rule["name"], ev["seq"], ev["id"])
                res = execute_action(workspace, rule, ev, firing_id, dry_run=True)
                firings.append({
                    "firing_id": firing_id,
                    "rule": rule["name"],
                    "event_seq": ev["seq"],
                    "action": rule["action"],
                    "plan": res,
                })

    return {
        "ok": True,
        "dry_run": True,
        "cursor": cursor,
        "trigger_scan_cursor": cursor,
        "delivery_cursor": get_delivery_cursor(workspace, role=role),
        "events_count": len(new_events),
        "firings": firings,
    }


# ---------------------------------------------------------------------------
# Daemon Mode (Spec §5, E7)
# ---------------------------------------------------------------------------

class TriggerDaemon:
    """Singleton trigger daemon with lease and graceful shutdown."""

    def __init__(
        self,
        workspace: pathlib.Path | str,
        *,
        config_path: pathlib.Path | str | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        role: str = "orchestrator",
    ) -> None:
        self.workspace = pathlib.Path(workspace).resolve()
        self.config_path = config_path
        self.poll_interval = poll_interval
        self.role = role
        self.stop_event = threading.Event()
        self.is_running = False

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> int:
        plat_err = check_platform()
        if plat_err:
            print(f"Error: {plat_err} (Triggers engine requires macOS or Linux)", file=sys.stderr)
            return 1

        try:
            with daemon_lock(self.workspace, non_blocking=True):
                self._update_lease(status="running")
                self.is_running = True
                logger.info("Trigger daemon started for workspace: %s", self.workspace)

                try:
                    while not self.stop_event.is_set():
                        try:
                            run_once(
                                self.workspace,
                                config_path=self.config_path,
                                role=self.role,
                                dry_run=False,
                            )
                        except Exception as e:
                            logger.exception("Error in daemon loop turn: %s", e)

                        self._update_lease(status="running")

                        # Responsive wait
                        deadline = time.time() + self.poll_interval
                        while time.time() < deadline:
                            if self.stop_event.is_set():
                                break
                            time.sleep(0.05)
                finally:
                    self.is_running = False
                    self._update_lease(status="stopped")
                    logger.info("Trigger daemon stopped gracefully")
                return 0

        except BlockingIOError:
            print("Error: Another trigger daemon is already running for this workspace", file=sys.stderr)
            return 1

    def _update_lease(self, status: str) -> None:
        lease_path = self.workspace / ".ai-orchestration" / "triggers" / "daemon.json"
        lease = {
            "pid": os.getpid(),
            "status": status,
            "role": self.role,
            "poll_interval": self.poll_interval,
            "heartbeat_at": _now_iso(),
        }
        _write_json_atomic(lease_path, lease)


# ---------------------------------------------------------------------------
# CLI Command Handlers & Parser
# ---------------------------------------------------------------------------

def cmd_run_once(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    res = run_once(
        ws,
        config_path=getattr(args, "config", None),
        role=getattr(args, "role", "orchestrator"),
        batch_size=getattr(args, "batch_size", DEFAULT_BATCH_SIZE),
        dry_run=bool(getattr(args, "dry_run", False)),
    )

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if not res.get("ok"):
            print(f"Error: {res.get('error')}", file=sys.stderr)
            if res.get("validation_errors"):
                for err in res["validation_errors"]:
                    print(f"  - {err}", file=sys.stderr)
            return 1

        status = res.get("status")
        if status == "disabled_by_kill_switch":
            print("Triggers are disabled globally by kill switch ([triggers] enabled = false).")
        elif status == "no_rules_configured":
            print("No trigger rules configured.")
        elif status == "up_to_date":
            print(f"No new events. Cursor is at {res.get('cursor')}.")
        elif res.get("dry_run"):
            print(f"Dry-run evaluated {res.get('events_count', 0)} events; {len(res.get('firings', []))} firings planned.")
            for f in res.get("firings", []):
                print(f"  - Rule '{f['rule']}' on event {f['event_seq']}: action '{f['action']}'")
        else:
            print(f"Processed {res.get('events_processed', 0)} events (batch: {res.get('batch_id')}, cursor: {res.get('cursor')}).")
            for f in res.get("firings", []):
                replayed_str = " (replayed)" if f.get("replayed") else ""
                print(f"  - [{f['state'].upper()}{replayed_str}] Rule '{f['rule']}' (event seq: {f['event_seq']})")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    daemon = TriggerDaemon(
        ws,
        config_path=getattr(args, "config", None),
        poll_interval=getattr(args, "poll_interval", DEFAULT_POLL_INTERVAL),
        role=getattr(args, "role", "orchestrator"),
    )

    # Attach signal handlers for graceful stop
    def handle_signal(sig, frame):
        daemon.stop()

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except (ValueError, AttributeError):
        pass

    return daemon.run()


def cmd_list(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    meta, rules, errors = load_triggers_config(ws, config_path=getattr(args, "config", None))

    if args.json:
        print(json.dumps({
            "ok": not bool(errors),
            "meta": meta,
            "rules": rules,
            "errors": errors,
        }, indent=2))
        return 0 if not errors else 1

    if errors:
        print("Validation errors in trigger configuration:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    ks_status = "ENABLED" if meta.get("kill_switch_enabled") else "DISABLED (kill switch)"
    print(f"Triggers Engine: {ks_status} (Configured rules: {len(rules)})\n")
    if not rules:
        print("No rules defined in configuration.")
        return 0

    for r in rules:
        en_str = "enabled" if r.get("enabled") else "disabled"
        when_str = f" when={json.dumps(r.get('when'))}" if r.get("when") else ""
        print(f"  - {r['name']:<24} on={r['on']:<20} action={r['action']:<14} ({en_str}){when_str}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    meta, rules, errors = load_triggers_config(ws)
    role = getattr(args, "role", "orchestrator")
    scan_cursor = get_trigger_scan_cursor(ws, role=role)
    deliv_cursor = get_delivery_cursor(ws, role=role)

    # Check daemon state
    lease_path = ws / ".ai-orchestration" / "triggers" / "daemon.json"
    daemon_info = None
    if lease_path.is_file():
        try:
            daemon_info = _read_json_safe(lease_path)
        except Exception:
            pass

    # Count firings
    firings_dir = ws / ".ai-orchestration" / "triggers" / "firings"
    firings_count = len(list(firings_dir.glob("*.json"))) if firings_dir.is_dir() else 0

    status_data = {
        "ok": True,
        "kill_switch_enabled": meta.get("kill_switch_enabled", True),
        "rule_count": len(rules),
        "role": role,
        "cursor": scan_cursor,
        "trigger_scan_cursor": scan_cursor,
        "delivery_cursor": deliv_cursor,
        "total_firings": firings_count,
        "daemon": daemon_info,
        "config_paths": meta.get("config_paths", []),
    }

    if args.json:
        print(json.dumps(status_data, indent=2))
    else:
        print(f"Triggers Engine Status:")
        print(f"  Kill switch: {'Active (Triggers Enabled)' if status_data['kill_switch_enabled'] else 'Triggering Disabled'}")
        print(f"  Configured rules: {status_data['rule_count']}")
        print(f"  Role '{role}' cursor: {scan_cursor}")
        print(f"  Role '{role}' delivery cursor: {deliv_cursor}")
        print(f"  Total recorded firings: {firings_count}")
        if daemon_info:
            print(f"  Daemon: {daemon_info.get('status')} (PID: {daemon_info.get('pid')}, heartbeat: {daemon_info.get('heartbeat_at')})")
        else:
            print("  Daemon: not running")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    firings_dir = ws / ".ai-orchestration" / "triggers" / "firings"
    if not firings_dir.is_dir():
        if args.json:
            print(json.dumps({"ok": True, "firings": []}, indent=2))
        else:
            print("No firings recorded yet.")
        return 0

    records: list[dict[str, Any]] = []
    target_rule = getattr(args, "rule", None)

    for p in sorted(firings_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        if p.name.startswith("."):
            continue
        try:
            rec = _read_json_safe(p)
            if target_rule and rec.get("rule_name") != target_rule:
                continue
            records.append(rec)
        except Exception:
            continue

    limit = getattr(args, "limit", 20)
    if limit and limit > 0:
        records = records[:limit]

    if args.json:
        print(json.dumps({"ok": True, "count": len(records), "firings": records}, indent=2))
    else:
        if not records:
            print("No matching firings found.")
        else:
            for r in records:
                print(
                    f"  [{r.get('state', '?').upper()}] {r.get('rule_name')} (event: {r.get('event_seq')}) "
                    f"at {r.get('updated_at')}: {json.dumps(r.get('result', {}))[:80]}"
                )
    return 0


def cmd_proposals(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    status = getattr(args, "status", "all") or "all"
    res = list_proposals(ws, status=status)
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    if not res.get("ok"):
        print(f"Error: {res.get('error')}", file=sys.stderr)
        return 1

    props = res.get("proposals", [])
    if not props:
        print(f"No proposed actions found (status: {status}).")
        return 0

    print(f"Proposed Actions ({len(props)}, status: {status}):\n")
    for p in props:
        act_id = p.get("action_id", "?")
        st = p.get("status", "?")
        ptype = p.get("type", "?")
        rule = p.get("rule", "?")
        h = (p.get("action_hash") or "")[:12]
        created = p.get("created_at", "")
        print(f"  [{st.upper()}] {act_id} (type: {ptype}, rule: {rule}, hash: {h}..., created: {created})")
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    res = confirm_action(
        ws,
        args.action_id,
        args.expect_hash,
        actor=getattr(args, "actor", None),
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    if not res.get("ok"):
        print(f"Error: {res.get('message') or res.get('error')}", file=sys.stderr)
        return 1

    run_id_str = f" (run_id: {res['run_id']})" if res.get("run_id") else ""
    print(f"Action '{args.action_id}' confirmed and executed{run_id_str}.")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    res = reject_action(
        ws,
        args.action_id,
        args.reason,
        actor=getattr(args, "actor", None),
    )
    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    if not res.get("ok"):
        print(f"Error: {res.get('message') or res.get('error')}", file=sys.stderr)
        return 1

    print(f"Action '{args.action_id}' rejected (reason: {args.reason}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestration_triggers.py",
        description="Trigger engine, event matching, batching and reduced-capability policy for ai-orchestration.",
    )
    parser.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    sub = parser.add_subparsers(dest="subcommand", required=True)

    # run-once
    p_run = sub.add_parser("run-once", help="Process new events since role cursor in one pass")
    p_run.add_argument("--config", "-c", help="Path to orchestration.toml configuration file")
    p_run.add_argument("--role", "-r", default="orchestrator", help="Role name (default: orchestrator)")
    p_run.add_argument("--batch-size", "-b", type=int, default=DEFAULT_BATCH_SIZE, help="Maximum events per batch")
    p_run.add_argument("--dry-run", action="store_true", help="Evaluate without executing actions or advancing cursor")
    p_run.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    p_run.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_run.set_defaults(func=cmd_run_once)

    # daemon
    p_daemon = sub.add_parser("daemon", help="Run background daemon polling for new events")
    p_daemon.add_argument("--config", "-c", help="Path to orchestration.toml configuration file")
    p_daemon.add_argument("--role", "-r", default="orchestrator", help="Role name (default: orchestrator)")
    p_daemon.add_argument("--poll-interval", "-i", type=float, default=DEFAULT_POLL_INTERVAL, help="Poll interval in seconds")
    p_daemon.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    p_daemon.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_daemon.set_defaults(func=cmd_daemon)

    # list
    p_list = sub.add_parser("list", help="List configured trigger rules and kill switch status")
    p_list.add_argument("--config", "-c", help="Path to orchestration.toml configuration file")
    p_list.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    p_list.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_list.set_defaults(func=cmd_list)

    # status
    p_status = sub.add_parser("status", help="Show trigger engine status and daemon health")
    p_status.add_argument("--role", "-r", default="orchestrator", help="Role name (default: orchestrator)")
    p_status.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    p_status.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_status.set_defaults(func=cmd_status)

    # history
    p_hist = sub.add_parser("history", help="Show history of trigger firings")
    p_hist.add_argument("--rule", help="Filter by rule name")
    p_hist.add_argument("--limit", "-n", type=int, default=20, help="Maximum entries to display")
    p_hist.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    p_hist.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_hist.set_defaults(func=cmd_history)

    # proposals
    p_props = sub.add_parser("proposals", help="List proposed trigger actions")
    p_props.add_argument("--status", choices=["pending", "confirmed", "rejected", "all", "pending_confirmation"], default="all", help="Filter by status (default: all)")
    p_props.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    p_props.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_props.set_defaults(func=cmd_proposals)

    # confirm
    p_conf = sub.add_parser("confirm", help="Confirm and execute a proposed trigger action")
    p_conf.add_argument("action_id", help="Proposed action ID to confirm")
    p_conf.add_argument("--expect-hash", "--expect-action-hash", dest="expect_hash", required=True, help="Expected action hash for concurrency safety")
    p_conf.add_argument("--actor", default=None, help="Actor confirming the action (e.g. owner, ui)")
    p_conf.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    p_conf.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_conf.set_defaults(func=cmd_confirm)

    # reject
    p_rej = sub.add_parser("reject", help="Reject a proposed trigger action with a reason")
    p_rej.add_argument("action_id", help="Proposed action ID to reject")
    p_rej.add_argument("--reason", required=True, help="Reason for rejecting the action")
    p_rej.add_argument("--actor", default=None, help="Actor rejecting the action (e.g. owner, ui)")
    p_rej.add_argument("--workspace", "-w", default=None, help="Path to workspace root")
    p_rej.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_rej.set_defaults(func=cmd_reject)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
