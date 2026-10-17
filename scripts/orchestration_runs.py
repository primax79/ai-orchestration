#!/usr/bin/env python3
"""orchestration_runs.py — Core runs engine for ai-orchestration.

Implements:
  - Spec §1 (emergent T### tasks only)
  - Spec §3 (launch request fields, resolution chain, modes, prompts, R4 allowed modes)
  - Spec §4 (run options, preview, list, show)
  - Spec §5.1 (registry layout, run.json schema, monotonic records, secret redaction)
  - Spec §5.2 (concurrency locking, active run guards)
  - Amendments R1 (binding plan_hash), R4 (allowed modes per state), R8 (task_bundle_sha256),
    R10 (platform check), R13 (secrets redaction)
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import uuid

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

# ---------------------------------------------------------------------------
# Path resolution to companion modules
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS_ENGINE_DIR = (
    REPO_ROOT
    / "plugins"
    / "architect-side"
    / "skills"
    / "task-pipeline"
    / "scripts"
)
ORCH_CONFIG_DIR = (
    REPO_ROOT
    / "plugins"
    / "shared"
    / "skills"
    / "orchestration-setup"
    / "scripts"
)

if str(TASKS_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(TASKS_ENGINE_DIR))
if str(ORCH_CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_CONFIG_DIR))

try:
    from tasks_engine import (
        discover_emergent_tasks,
        task_bundle_sha256,
        normalize_state,
        transition_task,
    )
except ImportError:
    discover_emergent_tasks = None  # type: ignore
    task_bundle_sha256 = None  # type: ignore
    normalize_state = None  # type: ignore
    transition_task = None  # type: ignore

try:
    from orchestration_config import (
        resolve_config,
        find_project_config_path,
        default_global_config_path,
        load_toml_file,
    )
except ImportError:
    resolve_config = None  # type: ignore
    find_project_config_path = None  # type: ignore
    default_global_config_path = None  # type: ignore
    load_toml_file = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_RUN_ID_RE = re.compile(
    r"^[0-9]{8}-[0-9]{6}-T[0-9]{3}-(kilo|claude|codex)-[0-9a-f]{4}$"
)

VALID_MODES = {"orchestrate", "execute", "verify"}
VALID_TOOLS = {"kilo", "claude", "codex"}

ACTIVE_STATES = {"starting", "running"}
TERMINAL_STATES = {"succeeded", "failed", "cancelled", "lost"}

SECRET_FLAG_RE = re.compile(
    r"^(?:--|-)[a-zA-Z0-9_-]*(?:token|key|secret|password)[a-zA-Z0-9_-]*$",
    re.IGNORECASE,
)
SECRET_ENV_REF_RE = re.compile(r"^\{env:[A-Za-z0-9_]+\}$")

# R4 — Actions per state table
# Task state -> allowed modes (empty list means no run modes allowed)
ALLOWED_MODES_PER_STATE: dict[str, list[str]] = {
    "open": ["execute", "orchestrate"],
    "bounced": ["execute", "orchestrate"],
    "in progress": ["orchestrate"],  # execute only allowed as continuation of existing run
    "delivered": ["verify", "orchestrate"],
    "waiting": ["orchestrate"],
    "blocked": ["orchestrate"],
    "verified": [],
    "done": [],
    "done with a caveat": [],
    "dropped": [],
}

DEFAULT_MODE_PER_STATE: dict[str, str | None] = {
    "open": "execute",
    "bounced": "execute",
    "in progress": "orchestrate",
    "delivered": "verify",
    "waiting": "orchestrate",
    "blocked": "orchestrate",
    "verified": None,
    "done": None,
    "done with a caveat": None,
    "dropped": None,
}

DEFAULT_LOG_CHUNK_SIZE = int(os.environ.get("AI_ORCH_LOG_CHUNK_SIZE", 10 * 1024 * 1024))


# ---------------------------------------------------------------------------
# Process Identity and Group Kill Helpers (R2, R9, R13)
# ---------------------------------------------------------------------------

def get_process_start_time(pid: int) -> str | None:
    """Retrieve process start time via `ps -o lstart= -p <pid>` in ISO format."""
    if pid <= 0:
        return None
    try:
        res = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return None
        out = (res.stdout or "").strip()
        if not out:
            return None
        parts = out.split()
        if len(parts) >= 5:
            cleaned = " ".join(parts[:5])
            try:
                dt = datetime.datetime.strptime(cleaned, "%a %b %d %H:%M:%S %Y")
                return dt.isoformat()
            except ValueError:
                pass
        return out
    except Exception:
        return None


def is_process_alive(pid: int, expected_start_time: str | None = None) -> bool:
    """Check if process is alive and optionally verify start time (PID reuse check)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if expected_start_time is not None:
        cur_start = get_process_start_time(pid)
        return cur_start is not None and cur_start == expected_start_time
    return True


def kill_process_group(
    pgid: int,
    leader_pid: int | None = None,
    expected_leader_start_time: str | None = None,
    timeout: float = 10.0,
) -> bool:
    """Send SIGTERM to process group after verifying leader start time, then SIGKILL if needed."""
    if pgid <= 0:
        return False

    if leader_pid is not None and expected_leader_start_time is not None:
        cur_start = get_process_start_time(leader_pid)
        if cur_start is None or cur_start != expected_leader_start_time:
            # PID reused or leader died with wrong start time: do NOT kill!
            return False

    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        return True  # already dead

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except OSError:
            return True
        time.sleep(0.1)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass
    return True


def expand_secret_env_vars(argv: list[str]) -> list[str]:
    """Expand {env:VAR_NAME} placeholders from os.environ at spawn time (R13)."""
    expanded: list[str] = []
    for arg in argv:
        new_arg = re.sub(
            r"\{env:([A-Za-z0-9_]+)\}",
            lambda m: os.environ.get(m.group(1), ""),
            arg,
        )
        expanded.append(new_arg)
    return expanded


def check_claude_allowed_tools(headless_cfg: dict[str, Any], mode: str) -> tuple[bool, str | None]:
    """R11 — Claude requires configured allowed_tools for the mode."""
    at = headless_cfg.get("allowed_tools")
    if isinstance(at, dict):
        at = at.get(mode)
    if not at or not isinstance(at, list) or len(at) == 0:
        return False, f"Claude requires 'allowed_tools' to be configured under [tools.claude.headless] for mode '{mode}' (no default permission policy)"
    return True, None


def read_log_chunks(
    run_dir: pathlib.Path,
    since_offset: int = 0,
) -> tuple[int, int, bytes]:
    """Read bytes from events chunk files starting at since_offset.
    
    Returns (first_available_offset, next_offset, data_bytes).
    """
    manifest_path = run_dir / "chunks.json"
    manifest: list[dict[str, Any]] = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = []

    chunk_files = sorted(run_dir.glob("events.*.jsonl"))
    if not chunk_files:
        legacy = run_dir / "events.jsonl"
        if legacy.is_file():
            chunk_files = [legacy]

    if not chunk_files:
        return 0, 0, b""

    chunk_map: list[dict[str, Any]] = []
    if manifest:
        man_by_fn = {m["file"]: m for m in manifest if isinstance(m, dict) and "file" in m}
        for f in chunk_files:
            if f.name in man_by_fn:
                m = man_by_fn[f.name]
                chunk_map.append({
                    "file": f,
                    "start_offset": m.get("start_offset", 0),
                    "size": f.stat().st_size,
                })
            else:
                prev_end = chunk_map[-1]["start_offset"] + chunk_map[-1]["size"] if chunk_map else 0
                chunk_map.append({
                    "file": f,
                    "start_offset": prev_end,
                    "size": f.stat().st_size,
                })
    else:
        cur_off = 0
        for f in chunk_files:
            sz = f.stat().st_size
            chunk_map.append({
                "file": f,
                "start_offset": cur_off,
                "size": sz,
            })
            cur_off += sz

    first_available_offset = chunk_map[0]["start_offset"]
    last_chunk = chunk_map[-1]
    next_offset = last_chunk["start_offset"] + last_chunk["size"]

    target_start = max(since_offset, first_available_offset)
    if target_start >= next_offset:
        return first_available_offset, next_offset, b""

    out_bytes = bytearray()
    for entry in chunk_map:
        c_start = entry["start_offset"]
        c_size = entry["size"]
        c_end = c_start + c_size
        if target_start < c_end:
            skip = max(0, target_start - c_start)
            try:
                with open(entry["file"], "rb") as f:
                    if skip > 0:
                        f.seek(skip)
                    out_bytes.extend(f.read())
            except OSError:
                pass

    return first_available_offset, next_offset, bytes(out_bytes)


def parse_log_events(data_bytes: bytes) -> list[dict[str, Any]]:
    """Parse JSON lines from stdout events into structured summary events."""
    events: list[dict[str, Any]] = []
    text = data_bytes.decode("utf-8", errors="replace")
    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        try:
            obj = json.loads(trimmed)
            if isinstance(obj, dict):
                evt: dict[str, Any] = {"raw": obj}
                content = None
                if "content" in obj:
                    content = obj["content"]
                elif "text" in obj:
                    content = obj["text"]
                elif "delta" in obj and isinstance(obj["delta"], dict) and "text" in obj["delta"]:
                    content = obj["delta"]["text"]

                if content is not None:
                    evt["text"] = str(content)

                if "tool" in obj or "tool_use" in obj or obj.get("type") in ("tool_use", "tool_call"):
                    evt["tool_call"] = obj.get("tool") or obj.get("tool_use") or obj.get("name") or obj

                if "error" in obj or obj.get("type") == "error":
                    evt["error"] = obj.get("error") or obj.get("message") or obj

                evt["type"] = obj.get("type") or obj.get("role") or "event"
                events.append(evt)
                continue
        except json.JSONDecodeError:
            pass
        events.append({"type": "text", "text": trimmed})
    return events


# ---------------------------------------------------------------------------
# Pure Guards
# ---------------------------------------------------------------------------

def check_platform(plat: str = sys.platform, fcntl_mod: Any = fcntl) -> str | None:
    """R10 — macOS and Linux only. Windows or absence of fcntl refused."""
    if plat.startswith("win") or fcntl_mod is None:
        return "unsupported-platform"
    return None


def check_task_id(task_id: str) -> tuple[bool, str | None]:
    """Spec §1 — Emergent tasks (T###) only. Refuse NN.T or invalid formats."""
    if not isinstance(task_id, str) or not task_id.strip():
        return False, "Task ID cannot be empty"
    t_clean = task_id.strip()
    if re.match(r"^T\d{3,}$", t_clean):
        return True, None
    if re.match(r"^(?:NN|\d+)\.(?:T|\d+)", t_clean, re.IGNORECASE) or t_clean.upper() == "NN.T":
        return False, "Initiative tasks (NN.T) are not supported in v1; emergent tasks (T###) only"
    return False, f"Invalid task ID '{task_id}'; emergent tasks (T###) only"


def get_allowed_modes_for_state(state: str, has_existing_run: bool = False, is_continue: bool = False) -> list[str]:
    """Return list of allowed modes for a given task state per R4."""
    canon = normalize_state(state) if normalize_state else state.lower()
    base = list(ALLOWED_MODES_PER_STATE.get(canon, []))
    if canon == "in progress" and (has_existing_run or is_continue):
        if "execute" not in base:
            base.insert(0, "execute")
    return base


def get_default_mode_for_state(state: str, has_existing_run: bool = False, is_continue: bool = False) -> str | None:
    """Return default mode for a task state per R4."""
    canon = normalize_state(state) if normalize_state else state.lower()
    if canon in ("open", "bounced"):
        return "execute"
    if canon == "delivered":
        return "verify"
    if canon in ("waiting", "blocked"):
        return "orchestrate"
    if canon == "in progress":
        return "execute" if is_continue else "orchestrate"
    return None


def check_task_state_and_mode(
    state: str,
    mode: str,
    has_existing_run: bool = False,
    is_continue: bool = False,
) -> tuple[bool, str | None]:
    """Guard: Verify task state allows the requested mode (R4)."""
    canon = normalize_state(state) if normalize_state else state.lower()
    if canon not in ALLOWED_MODES_PER_STATE:
        return False, f"Unknown task state '{state}'"

    allowed = get_allowed_modes_for_state(canon, has_existing_run=has_existing_run, is_continue=is_continue)
    if not allowed:
        return False, f"No run modes allowed for task in state '{state}'"

    if mode not in allowed:
        if canon == "in progress" and mode == "execute":
            return False, "execute mode for task in state 'in progress' is only allowed as a continuation of an existing run"
        return False, f"mode '{mode}' is not allowed for task in state '{state}' (allowed: {', '.join(allowed)})"

    return True, None


def check_tool_availability(
    tool_id: str,
    tool_cfg: dict[str, Any],
    which_fn: Any = shutil.which,
    version_fn: Any = None,
) -> tuple[bool, str | None, str | None]:
    """Guard: Tool must be enabled in config AND installed with working CLI version."""
    if not isinstance(tool_cfg, dict):
        return False, None, f"Tool '{tool_id}' not found in configuration"

    if not tool_cfg.get("enabled", True):
        return False, None, f"Tool '{tool_id}' is disabled in configuration"

    cli_cmd = tool_cfg.get("cli_command", tool_id)
    cli_path = which_fn(cli_cmd)
    if not cli_path:
        return False, None, f"CLI executable '{cli_cmd}' not found in PATH"

    version_str: str | None = None
    if version_fn is not None:
        try:
            version_str = version_fn(cli_path)
            if not version_str:
                return False, None, f"Could not determine version for CLI '{cli_cmd}'"
        except Exception as e:
            return False, None, f"Version check failed for '{cli_cmd}': {e}"
    else:
        try:
            res = subprocess.run(
                [cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            out = (res.stdout or res.stderr or "").strip()
            if res.returncode == 0 and out:
                version_str = out.splitlines()[0].strip()
            else:
                return False, None, f"CLI '{cli_cmd} --version' returned exit code {res.returncode}"
        except subprocess.TimeoutExpired:
            return False, None, f"Version check timed out (5s) for '{cli_cmd}'"
        except Exception as e:
            return False, None, f"Failed to execute '{cli_cmd} --version': {e}"

    return True, version_str, None


def check_same_task_active(
    task_id: str,
    active_runs: list[dict[str, Any]],
    force: bool = False,
) -> tuple[bool, str | None]:
    """Guard: At most one active run per task (--force bypasses ONLY this guard)."""
    if force:
        return True, None
    for run in active_runs:
        if run.get("task_id") == task_id and run.get("status") in ACTIVE_STATES:
            return False, f"Task '{task_id}' already has an active run: {run.get('run_id')}"
    return True, None


def check_same_cwd_active(
    cwd: str,
    isolation: str,
    active_runs: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    """Guard: At most one active run per cwd with isolation: none (never bypassable)."""
    if isolation != "none":
        return True, None

    try:
        target_path = pathlib.Path(cwd).resolve()
    except Exception:
        target_path = pathlib.Path(cwd)

    for run in active_runs:
        if run.get("isolation") == "none" and run.get("status") in ACTIVE_STATES:
            r_cwd = run.get("cwd")
            if not r_cwd:
                continue
            try:
                r_path = pathlib.Path(r_cwd).resolve()
                if r_path == target_path:
                    return False, f"Working directory '{cwd}' already has an active run with isolation 'none': {run.get('run_id')}"
            except Exception:
                if str(r_cwd) == str(cwd):
                    return False, f"Working directory '{cwd}' already has an active run with isolation 'none': {run.get('run_id')}"
    return True, None


def check_independence_guard(
    mode: str,
    tool: str,
    task_executor: str | None,
    target_run_tool: str | None = None,
    allow_same_tool: bool = False,
) -> tuple[bool, str | None]:
    """Guard: In verify mode, tool cannot equal task's executor or target_run tool (R5, §5.6)."""
    if mode != "verify":
        return True, None
    if allow_same_tool:
        return True, None

    if task_executor and task_executor != "-" and tool.lower() == task_executor.lower():
        return (
            False,
            f"Tool '{tool}' matches task executor '{task_executor}'; verify requires an independent tool "
            "(or pass --allow-same-tool for independent-session)",
        )

    if target_run_tool and target_run_tool != "-" and tool.lower() == target_run_tool.lower():
        return (
            False,
            f"Tool '{tool}' matches target_run tool '{target_run_tool}'; verify requires an independent tool "
            "(or pass --allow-same-tool for independent-session)",
        )

    return True, None


# ---------------------------------------------------------------------------
# Path & Git Helpers
# ---------------------------------------------------------------------------

def get_git_toplevel(path: pathlib.Path) -> pathlib.Path | None:
    """Find git toplevel for a given directory path."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return pathlib.Path(res.stdout.strip()).resolve()
    except Exception:
        pass

    cur = path.resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    return None


def get_git_main_repo(workspace: pathlib.Path) -> pathlib.Path | None:
    """If workspace is in a worktree, return the main repository root."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            common_dir = pathlib.Path(res.stdout.strip())
            if not common_dir.is_absolute():
                common_dir = (workspace / common_dir).resolve()
            if common_dir.name == ".git":
                return common_dir.parent
            return common_dir
    except Exception:
        pass
    return get_git_toplevel(workspace)


def get_repo_head(repo_root: pathlib.Path) -> str:
    """Get HEAD commit hash of repository."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def check_repo_clean(repo_root: pathlib.Path) -> tuple[bool, list[str]]:
    """Check if repository is clean, ignoring .ai-orchestration/."""
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return True, []
        lines = []
        for line in res.stdout.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            # status line format: XY path
            file_part = line[3:].strip()
            if file_part.startswith(".ai-orchestration"):
                continue
            lines.append(line_str)
        return len(lines) == 0, lines
    except Exception:
        return True, []


def resolve_target_repo(
    workspace: pathlib.Path,
    paths_header: str | None,
) -> tuple[pathlib.Path | None, list[pathlib.Path], str | None]:
    """Resolve target repo from task's paths header (Spec §5.4).

    Each path is resolved through its nearest existing ancestor to a git toplevel.
    All paths must resolve to exactly one repo; otherwise refused.
    """
    if not paths_header or paths_header.strip() in ("", "-"):
        repo = get_git_toplevel(workspace) or workspace
        return repo, [repo], None

    main_repo = get_git_main_repo(workspace)
    raw_paths = [p.strip() for p in paths_header.split(",") if p.strip() and p.strip() != "-"]
    if not raw_paths:
        repo = get_git_toplevel(workspace) or workspace
        return repo, [repo], None

    found_repos: list[pathlib.Path] = []
    for item in raw_paths:
        candidate = (workspace / item).resolve()
        if not candidate.exists() and main_repo:
            cand_main = (main_repo / item).resolve()
            if cand_main.exists() or cand_main.parent.exists():
                candidate = cand_main

        # Nearest existing ancestor
        anc = candidate
        while not anc.exists() and anc != anc.parent:
            anc = anc.parent

        repo = get_git_toplevel(anc) or anc
        if repo not in found_repos:
            found_repos.append(repo)

    if len(found_repos) > 1:
        repos_str = ", ".join(f"'{str(r)}'" for r in sorted(found_repos))
        return None, found_repos, f"Paths resolve to multiple git repositories: [{repos_str}]"
    if len(found_repos) == 1:
        return found_repos[0], found_repos, None
    default_r = get_git_toplevel(workspace) or workspace
    return default_r, [default_r], None


def ensure_git_exclude(repo_root: pathlib.Path) -> tuple[bool, str | None]:
    """Ensure .ai-orchestration/ is added to .git/info/exclude and ignored (Spec §5.1).

    NOTE: Must only be called on stateful operations (like start), never on preview or options.
    """
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            exclude_path = pathlib.Path(res.stdout.strip())
            if not exclude_path.is_absolute():
                exclude_path = (repo_root / exclude_path).resolve()
        else:
            exclude_path = repo_root / ".git" / "info" / "exclude"
    except Exception:
        exclude_path = repo_root / ".git" / "info" / "exclude"

    exclude_path.parent.mkdir(parents=True, exist_ok=True)
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

    # Verify git check-ignore
    try:
        check = subprocess.run(
            ["git", "check-ignore", "-q", ".ai-orchestration/"],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
        if check.returncode != 0:
            check2 = subprocess.run(
                ["git", "check-ignore", "-q", ".ai-orchestration"],
                cwd=str(repo_root),
                capture_output=True,
                check=False,
            )
            if check2.returncode != 0:
                return False, "Path '.ai-orchestration/' is still not ignored by git check-ignore"
    except Exception as e:
        return False, f"git check-ignore execution failed: {e}"

    return True, None


# ---------------------------------------------------------------------------
# Tool, Profile, Model Resolution
# ---------------------------------------------------------------------------

def resolve_tool(
    mode: str,
    requested_tool: str | None,
    task: dict[str, Any],
    merged_cfg: dict[str, Any],
    project_cfg: dict[str, Any] | None,
    global_cfg: dict[str, Any] | None,
    allow_same_tool: bool = False,
    target_run_tool: str | None = None,
) -> tuple[str | None, str | None]:
    """Tool resolution chain (Spec §3, R5).

    Chain:
      1. Explicit choice (--tool)
      2. Task executor header (when it names a valid tool id, for execute)
      3. Project routing (default_orchestrator / default_executor)
      4. Global routing (default_orchestrator / default_executor)
      For verify: honours cross_agent_order honoring independence guard.

    Returns (resolved_tool_id, chosen_cross_order_entry).
    """
    tools = merged_cfg.get("tools", {})

    if requested_tool:
        return requested_tool, None

    if mode == "verify":
        ver_cfg = merged_cfg.get("verification", {})
        cross_order = ver_cfg.get("cross_agent_order", [])
        task_executor = task.get("executor")

        # Try to find first entry that passes independence guard
        for entry in cross_order:
            if ":" not in entry:
                continue
            cand_tool, _ = entry.split(":", 1)
            indep_ok, _ = check_independence_guard(
                mode="verify",
                tool=cand_tool,
                task_executor=task_executor,
                target_run_tool=target_run_tool,
                allow_same_tool=allow_same_tool,
            )
            if indep_ok:
                t_cfg = tools.get(cand_tool, {})
                if t_cfg.get("enabled", True):
                    return cand_tool, entry

        # If allow_same_tool, fall back to first enabled entry
        if allow_same_tool:
            for entry in cross_order:
                if ":" in entry:
                    cand_tool, _ = entry.split(":", 1)
                    if tools.get(cand_tool, {}).get("enabled", True):
                        return cand_tool, entry

        return None, None

    if mode == "execute":
        # Layer 2: Task executor header
        task_exec = task.get("executor")
        if task_exec and task_exec != "-" and task_exec in tools:
            return task_exec, None

        # Layer 3: Project routing
        if project_cfg:
            p_exec = project_cfg.get("routing", {}).get("default_executor")
            if p_exec and p_exec in tools:
                return p_exec, None

        # Layer 4: Global routing
        if global_cfg:
            g_exec = global_cfg.get("routing", {}).get("default_executor")
            if g_exec and g_exec in tools:
                return g_exec, None

        merged_exec = merged_cfg.get("routing", {}).get("default_executor")
        if merged_exec and merged_exec in tools:
            return merged_exec, None

        return "kilo" if "kilo" in tools else None

    if mode == "orchestrate":
        # Layer 3: Project routing
        if project_cfg:
            p_orch = project_cfg.get("routing", {}).get("default_orchestrator")
            if p_orch and p_orch in tools:
                return p_orch, None

        # Layer 4: Global routing
        if global_cfg:
            g_orch = global_cfg.get("routing", {}).get("default_orchestrator")
            if g_orch and g_orch in tools:
                return g_orch, None

        merged_orch = merged_cfg.get("routing", {}).get("default_orchestrator")
        if merged_orch and merged_orch in tools:
            return merged_orch, None

        return "kilo" if "kilo" in tools else None

    return None, None


def resolve_profile(
    mode: str,
    requested_profile: str | None,
    task: dict[str, Any],
    merged_cfg: dict[str, Any],
    project_cfg: dict[str, Any] | None,
    global_cfg: dict[str, Any] | None,
    chosen_cross_order_entry: str | None = None,
) -> str:
    """Resolve profile per mode and task (Spec §3)."""
    if requested_profile:
        return requested_profile

    if mode == "orchestrate":
        return "orchestration"

    if mode == "verify":
        if chosen_cross_order_entry and ":" in chosen_cross_order_entry:
            return chosen_cross_order_entry.split(":", 1)[1]
        return "deep-reasoning"

    if mode == "execute":
        task_prof = task.get("profile")
        if task_prof and task_prof != "-":
            return task_prof

        if project_cfg:
            p_prof = project_cfg.get("routing", {}).get("default_profile")
            if p_prof:
                return p_prof

        if global_cfg:
            g_prof = global_cfg.get("routing", {}).get("default_profile")
            if g_prof:
                return g_prof

        return merged_cfg.get("routing", {}).get("default_profile", "bulk-execution")

    return "bulk-execution"


def resolve_model_and_variants(
    tool: str,
    profile: str,
    requested_model: str | None,
    requested_variant: str | None,
    requested_effort: str | None,
    merged_cfg: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Resolve model, variant, and effort from tool profile and overrides."""
    tcfg = merged_cfg.get("tools", {}).get(tool, {})
    pentry = tcfg.get("profiles", {}).get(profile, {})

    model = requested_model or pentry.get("model")
    variant = requested_variant or pentry.get("variant")
    effort = requested_effort or pentry.get("effort")

    # If explicit variant was supplied, clear effort unless effort was also explicitly given
    if requested_variant and not requested_effort:
        effort = None
    elif requested_effort and not requested_variant:
        variant = None

    return model, variant, effort


# ---------------------------------------------------------------------------
# Adapter Argv & Secret Redaction (R13)
# ---------------------------------------------------------------------------

def redact_argv(argv: list[str]) -> list[str]:
    """Redact literal secrets in flags matching token|key|secret|password.

    Preserves {env:NAME} references unredacted per R13.
    """
    redacted: list[str] = []
    skip_next = False

    for i, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue

        if "=" in arg:
            flag, val = arg.split("=", 1)
            if SECRET_FLAG_RE.match(flag):
                if SECRET_ENV_REF_RE.match(val):
                    redacted.append(f"{flag}={val}")
                else:
                    redacted.append(f"{flag}=[REDACTED]")
            else:
                redacted.append(arg)
        elif SECRET_FLAG_RE.match(arg):
            redacted.append(arg)
            if i + 1 < len(argv):
                next_val = argv[i + 1]
                if SECRET_ENV_REF_RE.match(next_val):
                    redacted.append(next_val)
                else:
                    redacted.append("[REDACTED]")
                skip_next = True
        else:
            redacted.append(arg)

    return redacted


def validate_headless_argv_secrets(argv: list[str]) -> list[str]:
    """Validate that headless argv overrides do not contain literal secrets (R13)."""
    errors: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if "=" in arg:
            flag, val = arg.split("=", 1)
            if SECRET_FLAG_RE.match(flag):
                if not SECRET_ENV_REF_RE.match(val):
                    errors.append(
                        f"Flag '{flag}' contains literal secret {val!r}; "
                        "headless argv overrides must use '{env:NAME}' references"
                    )
        elif SECRET_FLAG_RE.match(arg):
            if i + 1 < len(argv):
                next_val = argv[i + 1]
                if not SECRET_ENV_REF_RE.match(next_val):
                    errors.append(
                        f"Flag '{arg}' contains literal secret {next_val!r}; "
                        "headless argv overrides must use '{env:NAME}' references"
                    )
                i += 1
        i += 1
    return errors


def build_adapter_argv(
    tool: str,
    tool_cfg: dict[str, Any],
    mode: str,
    cwd: str,
    model: str,
    variant: str | None = None,
    effort: str | None = None,
    session_id: str | None = None,
    prompt_file: str | None = None,
) -> list[str]:
    """Build the adapter argv list for a given tool (Spec §5.7)."""
    headless = tool_cfg.get("headless", {})
    if not isinstance(headless, dict):
        headless = {}

    permission_mode = headless.get("permission_mode") or "acceptEdits"
    sandbox = headless.get("sandbox") or "workspace-write"
    session_id_val = session_id or "{session_id}"
    prompt_file_val = prompt_file or "{prompt_file}"

    # If headless has an explicit argv override
    if "argv" in headless and isinstance(headless["argv"], list):
        template = headless["argv"]
        replacements = {
            "cwd": cwd,
            "model": model,
            "variant": variant or "",
            "effort": effort or "",
            "session_id": session_id_val,
            "permission_mode": permission_mode,
            "sandbox": sandbox,
            "prompt_file": prompt_file_val,
        }
        res: list[str] = []
        for arg in template:
            formatted = arg
            for ph, val in replacements.items():
                formatted = formatted.replace(f"{{{ph}}}", val)
            res.append(formatted)
        return res

    # Built-in adapter defaults per tool
    if tool == "kilo":
        argv = [
            "kilo",
            "run",
            "--format",
            "json",
            "--dir",
            cwd,
            "-m",
            model,
        ]
        if variant:
            argv.extend(["--variant", variant])
        argv.extend(["-f", prompt_file_val, "Follow the attached task prompt."])
        return argv

    if tool == "claude":
        argv = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--session-id",
            session_id_val,
            "--model",
            model,
        ]
        if effort:
            argv.extend(["--effort", effort])
        argv.extend([
            "--permission-mode",
            permission_mode,
            "--permission-prompts",
            "none",
        ])
        allowed_tools = headless.get("allowed_tools")
        if allowed_tools and isinstance(allowed_tools, list):
            argv.extend(["--allowedTools", ",".join(allowed_tools)])
        return argv

    if tool == "codex":
        argv = [
            "codex",
            "exec",
            "--json",
            "-C",
            cwd,
            "-m",
            model,
            "-s",
            sandbox,
        ]
        if effort:
            argv.extend(["-c", f"model_reasoning_effort={effort}"])
        argv.append("-")
        return argv

    # Generic fallback
    return [tool, "--dir", cwd, "-m", model]


# ---------------------------------------------------------------------------
# Prompt Builders (Spec §3)
# ---------------------------------------------------------------------------

def load_task_files_content(task: dict[str, Any]) -> str:
    """Read task file content (or all markdown files for a folder task)."""
    is_folder = bool(task.get("is_folder", False))
    task_root_str = task.get("task_root") or task.get("file_path", "")
    task_root = pathlib.Path(task_root_str)

    if not is_folder:
        file_path = pathlib.Path(task.get("file_path", task_root))
        if file_path.is_file():
            return file_path.read_text(encoding="utf-8")
        return ""

    parts: list[str] = []
    folder = task_root if task_root.is_dir() else task_root.parent
    if folder.is_dir():
        for fname in ("README.md", "CONTEXT.md", "PROGRESS.md"):
            p = folder / fname
            if p.is_file():
                parts.append(f"### {fname}\n\n{p.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def build_prompt(
    mode: str,
    task: dict[str, Any],
    target_commit: str | None = None,
    instructions: str | None = None,
) -> str:
    """Deterministic prompt builder per mode (Spec §3)."""
    task_id = task.get("id", "UNKNOWN")
    task_title = task.get("title", "")
    task_content = load_task_files_content(task)

    blocks: list[str] = [
        f"# Task: {task_id} — {task_title}",
        "",
        "## Task Specification",
        "",
        task_content.strip(),
        "",
    ]

    if mode == "orchestrate":
        blocks.extend([
            "## Orchestrator Guidelines",
            "",
            "- You are acting as Architect and Orchestrator for this task in the workspace root.",
            "- Follow the workspace `AGENTS.md` orchestration rules strictly: keep the main session free, do not implement multi-file code directly, and delegate implementation to worktrees or subagents.",
            "- Never mark or transition the task to `verified` on your own work. Task verification must be performed independently (e.g., cross-agent verification or operator approval).",
            "- If blocked by a design ambiguity or missing decision, file a blocking question using the ```ai-orch-question fenced block format.",
            "",
        ])
    elif mode == "execute":
        blocks.extend([
            "## Executor Contract",
            "",
            "- Zero interactivity: You are running headlessly in an isolated background run. Do not ask questions or offer choices. Make the most reasonable technical decision based on the instructions.",
            "- Scope discipline: Implement exactly what the task specification requires. Do not add unrequested features, abstractions, or refactors.",
            "- Commit on the run branch: Create a single atomic git commit scoped strictly to the files changed for this task on the run branch.",
            "- Conclude your final message with a `## Final Report` matching exactly this structure:",
            "  ```markdown",
            "  ## Final Report",
            "  - **Outcome**: `success` | `partial` | `failed`",
            "  - **Files changed**:",
            "    - `path/to/file` — summary of changes",
            "  - **Verification**:",
            "    - Command: `<runnable command>`",
            "    - Output: `<actual output and exit code>`",
            "  - **Issues**:",
            "    - `None` (or description of blockers/deviations)",
            "  ```",
            "- If you encounter a blocking decision or critical ambiguity, file a blocking question using the ```ai-orch-question fenced block format instead of guessing.",
            "",
        ])
    elif mode == "verify":
        commit_str = target_commit or "HEAD"
        blocks.extend([
            "## Verification Guidelines",
            "",
            "- You are acting as an independent verifier in a detached throwaway worktree.",
            f"- Artifact commit being verified: `{commit_str}`.",
            "- Run the verification checks described in the task's `## Verification` section.",
            "- Do not modify code on the branch. This is an evaluation run.",
            "- Conclude your final message with the mandatory verdict block:",
            "  ```ai-orch-verdict",
            '  {"verdict": "verified" | "bounced", "findings": [{"id": "B1", "severity": "blocker|major|minor", "text": "..."}], "checks": [{"step": "...", "result": "pass|fail", "evidence": "..."}]}',
            "  ```",
            "",
        ])

    if instructions and instructions.strip():
        blocks.extend([
            "## Additional Instructions",
            "",
            instructions.strip(),
            "",
        ])

    return "\n".join(blocks).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Plan Hash (R1)
# ---------------------------------------------------------------------------

def compute_plan_hash(
    canonical_request: dict[str, Any],
    task_bundle_hash: str,
    effective_argv_redacted: list[str],
    prompt: str,
    repo_head: str,
    effective_config: dict[str, Any],
) -> str:
    """Compute binding plan_hash (R1).

    Hash over: canonical request, task bundle hash, effective adapter argv (redacted),
    prompt hash, target repo HEAD, and effective config hash.
    """
    req_str = json.dumps(canonical_request, sort_keys=True, separators=(",", ":"))
    argv_str = json.dumps(effective_argv_redacted, separators=(",", ":"))
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    cfg_str = json.dumps(effective_config, sort_keys=True, separators=(",", ":"))
    cfg_hash = hashlib.sha256(cfg_str.encode("utf-8")).hexdigest()

    hasher = hashlib.sha256()
    hasher.update(req_str.encode("utf-8") + b"\n")
    hasher.update(task_bundle_hash.encode("utf-8") + b"\n")
    hasher.update(argv_str.encode("utf-8") + b"\n")
    hasher.update(prompt_hash.encode("utf-8") + b"\n")
    hasher.update(repo_head.encode("utf-8") + b"\n")
    hasher.update(cfg_hash.encode("utf-8") + b"\n")

    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Registry & Concurrency Locking (Spec §5.1, §5.2)
# ---------------------------------------------------------------------------

_RUN_LOCK_COUNTS: dict[str, int] = {}
_RUN_LOCK_FDS: dict[str, int] = {}


@contextlib.contextmanager
def run_lock(workspace: pathlib.Path):
    """Exclusive fcntl.flock on <workspace>/.ai-orchestration/runs/.lock (re-entrant within process)."""
    global _RUN_LOCK_COUNTS, _RUN_LOCK_FDS
    runs_dir = workspace / ".ai-orchestration" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(runs_dir, 0o700)
    except OSError:
        pass

    lock_file = runs_dir / ".lock"
    lock_key = str(lock_file.resolve())

    count = _RUN_LOCK_COUNTS.get(lock_key, 0)
    if count > 0:
        _RUN_LOCK_COUNTS[lock_key] = count + 1
        try:
            yield
        finally:
            _RUN_LOCK_COUNTS[lock_key] -= 1
            if _RUN_LOCK_COUNTS[lock_key] == 0:
                _RUN_LOCK_COUNTS.pop(lock_key, None)
        return

    fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        _RUN_LOCK_COUNTS[lock_key] = 1
        _RUN_LOCK_FDS[lock_key] = fd
        yield
    finally:
        _RUN_LOCK_COUNTS.pop(lock_key, None)
        _RUN_LOCK_FDS.pop(lock_key, None)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def generate_run_id(task_id: str, tool: str) -> str:
    """Generate run_id: <YYYYMMDD-HHMMSS>-<task>-<tool>-<4 hex>."""
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    rand_hex = os.urandom(2).hex()
    clean_task = task_id.strip()
    return f"{now_str}-{clean_task}-{tool.lower()}-{rand_hex}"


def validate_run_id(run_id: str) -> bool:
    """Strict run_id validation regex (Spec §5.1). Rejects traversal."""
    if not isinstance(run_id, str):
        return False
    return bool(VALID_RUN_ID_RE.match(run_id))


def reconcile(record: dict[str, Any], workspace: pathlib.Path | None = None) -> dict[str, Any]:
    """Reconciliation hook called on read (Spec §5.3, R2)."""
    status = record.get("status")
    if status not in ACTIVE_STATES:
        return record

    ws = workspace or (pathlib.Path(record["workspace"]) if record.get("workspace") else None)
    sup = record.get("supervisor", {})
    sup_pid = sup.get("pid")
    sup_start = sup.get("start_time")

    is_lost = False

    if sup_pid is None:
        started_at = record.get("started_at")
        if started_at:
            try:
                started_str = started_at.replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(started_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                now = datetime.datetime.now(datetime.timezone.utc)
                if (now - dt).total_seconds() > 60:
                    is_lost = True
            except Exception:
                pass
    else:
        cur_sup_start = get_process_start_time(sup_pid)
        if cur_sup_start is None or cur_sup_start != sup_start:
            is_lost = True

    if is_lost:
        record["status"] = "lost"
        record["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        agent = record.get("agent", {})
        agent_pid = agent.get("pid")
        agent_pgid = agent.get("pgid")
        agent_start = agent.get("start_time")
        if agent_pid and agent_pgid and agent_start:
            kill_process_group(
                pgid=agent_pgid,
                leader_pid=agent_pid,
                expected_leader_start_time=agent_start,
                timeout=0.2,
            )

        if ws:
            try:
                save_run_record(ws, record)
            except Exception:
                pass

    return record


def create_run_record(
    run_id: str,
    task_id: str,
    mode: str,
    tool: str,
    profile: str,
    model: str,
    variant: str | None,
    effort: str | None,
    requested_by: str,
    workspace: str,
    cwd: str,
    isolation: str,
    task_bundle_sha256: str,
    argv_display: list[str],
    plan_hash: str,
    worktree_path: str | None = None,
    branch: str | None = None,
    base_commit: str | None = None,
    target_run: str | None = None,
    target_commit: str | None = None,
    continued_from: str | None = None,
) -> dict[str, Any]:
    """Initialize a run.json record structure (Spec §5.1, R2, R3, R8)."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "run_id": run_id,
        "task_id": task_id,
        "mode": mode,
        "tool": tool,
        "profile": profile,
        "model": model,
        "variant": variant,
        "effort": effort,
        "requested_by": requested_by,
        "workspace": workspace,
        "cwd": cwd,
        "isolation": isolation,
        "worktree_path": worktree_path,
        "branch": branch,
        "base_commit": base_commit,
        "final_commit": None,
        "target_run": target_run,
        "target_commit": target_commit,
        "task_bundle_sha256": task_bundle_sha256,
        "plan_hash": plan_hash,
        "supervisor": {"pid": None, "start_time": None},
        "agent": {"pid": None, "pgid": None, "start_time": None},
        "argv_display": argv_display,
        "status": "starting",
        "exit_code": None,
        "started_at": now_iso,
        "ended_at": None,
        "session_id": None,
        "continued_from": continued_from,
        "final_report": None,
        "verdict": None,
        "questions": [],
        "task_transition_error": None,
    }


def save_run_record(workspace: pathlib.Path, record: dict[str, Any]) -> None:
    """Atomic monotonic write of run.json under run_lock (Spec §5.1, §5.2)."""
    run_id = record.get("run_id")
    if not run_id or not validate_run_id(run_id):
        raise ValueError(f"Invalid run_id '{run_id}'")

    with run_lock(workspace):
        run_dir = workspace / ".ai-orchestration" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass

        run_file = run_dir / "run.json"
        if run_file.is_file():
            try:
                existing = json.loads(run_file.read_text(encoding="utf-8"))
                ex_st = existing.get("status")
                new_st = record.get("status")
                if ex_st in TERMINAL_STATES and new_st not in TERMINAL_STATES:
                    raise ValueError(
                        f"Monotonic guard: cannot overwrite terminal status '{ex_st}' with '{new_st}'"
                    )
                if ex_st in ("cancelled", "lost") and new_st in ("succeeded", "failed"):
                    record["status"] = ex_st
            except (json.JSONDecodeError, OSError):
                pass

        fd, tmp_path = tempfile.mkstemp(
            dir=str(run_dir),
            prefix="run.json.tmp.",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, run_file)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def load_run_record(workspace: pathlib.Path, run_id: str) -> dict[str, Any] | None:
    """Load and reconcile a run record by run_id."""
    if not validate_run_id(run_id):
        return None
    run_file = workspace / ".ai-orchestration" / "runs" / run_id / "run.json"
    if not run_file.is_file():
        return None
    try:
        data = json.loads(run_file.read_text(encoding="utf-8"))
        return reconcile(data, workspace)
    except Exception:
        return None


def list_run_records(
    workspace: pathlib.Path,
    task_id: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """List run records, newest first, after reconciliation (Spec §4)."""
    runs_dir = workspace / ".ai-orchestration" / "runs"
    if not runs_dir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for entry in runs_dir.iterdir():
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        if not validate_run_id(entry.name):
            continue
        run_file = entry / "run.json"
        if not run_file.is_file():
            continue
        try:
            data = json.loads(run_file.read_text(encoding="utf-8"))
            record = reconcile(data, workspace)
        except Exception:
            continue

        if task_id and record.get("task_id") != task_id:
            continue
        if active_only and record.get("status") not in ACTIVE_STATES:
            continue
        results.append(record)

    results.sort(key=lambda r: r.get("run_id", ""), reverse=True)
    return results


# ---------------------------------------------------------------------------
# CLI Commands: options, preview, list, show
# ---------------------------------------------------------------------------

def print_error(json_mode: bool, reason: str, error: str) -> None:
    if json_mode:
        print(json.dumps({"ok": False, "reason": reason, "error": error}, indent=2))
    else:
        print(f"[FAIL] {reason}: {error}", file=sys.stderr)


def cmd_options(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        print_error(args.json, plat_err, "Runs engine is supported on macOS and Linux only (fcntl required)")
        return 1

    task_id = args.task
    valid_task, task_err = check_task_id(task_id)
    if not valid_task:
        reason = "initiative-tasks-not-supported" if "Initiative" in (task_err or "") else "invalid-task-id"
        print_error(args.json, reason, task_err or "Invalid task ID")
        return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    tasks_dir = ws / "tasks"
    if not tasks_dir.is_dir():
        print_error(args.json, "tasks-dir-not-found", f"Tasks directory not found at {tasks_dir}")
        return 1

    if discover_emergent_tasks is None:
        print_error(args.json, "engine-missing", "tasks_engine module could not be imported")
        return 1

    all_tasks = discover_emergent_tasks(tasks_dir)
    task = next((t for t in all_tasks if t["id"] == task_id), None)
    if not task:
        print_error(args.json, "task-not-found", f"Task '{task_id}' not found in tasks directory")
        return 1

    canonical_state = task.get("canonical_state", "open")
    allowed_modes = get_allowed_modes_for_state(canonical_state)
    default_mode = get_default_mode_for_state(canonical_state)

    gpath = getattr(args, "global_config", None)
    merged_cfg, _ = resolve_config(gpath, ws)
    project_cfg_path = find_project_config_path(ws, gpath)
    project_cfg = load_toml_file(project_cfg_path) if project_cfg_path.exists() else None
    global_cfg = load_toml_file(gpath or default_global_config_path())

    tools_cfg = merged_cfg.get("tools", {})
    tools_status: dict[str, Any] = {}
    models_per_profile: dict[str, Any] = {}

    for tname, tcfg in tools_cfg.items():
        if not isinstance(tcfg, dict):
            continue
        cli_cmd = tcfg.get("cli_command", tname)
        cli_p = shutil.which(cli_cmd)
        avail, ver_str, err_str = check_tool_availability(tname, tcfg)
        tools_status[tname] = {
            "enabled": bool(tcfg.get("enabled", True)),
            "installed": cli_p is not None,
            "available": avail,
            "cli_command": cli_cmd,
            "path": cli_p,
            "version": ver_str,
            "reason": err_str,
        }

        prof_map: dict[str, Any] = {}
        for prof_name, pentry in tcfg.get("profiles", {}).items():
            if isinstance(pentry, dict):
                prof_map[prof_name] = {
                    "model": pentry.get("model"),
                    "variant": pentry.get("variant"),
                    "effort": pentry.get("effort"),
                }
        models_per_profile[tname] = prof_map

    all_runs = list_run_records(ws, task_id=task_id)
    usable_verify_targets = [
        {
            "run_id": r["run_id"],
            "ended_at": r.get("ended_at"),
            "final_commit": r.get("final_commit"),
            "tool": r.get("tool"),
        }
        for r in all_runs
        if r.get("mode") == "execute" and r.get("status") == "succeeded"
    ]
    latest_verify_target = usable_verify_targets[0]["run_id"] if usable_verify_targets else "none"

    resolved_defaults: dict[str, Any] = {}
    for m in ("execute", "orchestrate", "verify"):
        res_tool, _ = resolve_tool(
            mode=m,
            requested_tool=None,
            task=task,
            merged_cfg=merged_cfg,
            project_cfg=project_cfg,
            global_cfg=global_cfg,
            allow_same_tool=False,
            target_run_tool=(usable_verify_targets[0]["tool"] if usable_verify_targets else None) if m == "verify" else None,
        )
        res_prof = resolve_profile(
            mode=m,
            requested_profile=None,
            task=task,
            merged_cfg=merged_cfg,
            project_cfg=project_cfg,
            global_cfg=global_cfg,
        )
        t_for_mod = res_tool or "kilo"
        res_model, res_variant, res_effort = resolve_model_and_variants(
            tool=t_for_mod,
            profile=res_prof,
            requested_model=None,
            requested_variant=None,
            requested_effort=None,
            merged_cfg=merged_cfg,
        )
        entry_def: dict[str, Any] = {
            "mode": m,
            "tool": res_tool,
            "profile": res_prof,
            "model": res_model,
            "variant": res_variant,
            "effort": res_effort,
        }
        if m == "execute":
            entry_def["isolation"] = "worktree"
        elif m == "orchestrate":
            entry_def["isolation"] = "none"
        elif m == "verify":
            entry_def["isolation"] = "worktree"
            entry_def["target_run"] = latest_verify_target
        resolved_defaults[m] = entry_def

    payload = {
        "ok": True,
        "task": {
            "id": task["id"],
            "title": task.get("title", ""),
            "state": canonical_state,
            "executor": task.get("executor") or "-",
            "profile": task.get("profile"),
            "bundle_sha256": task.get("bundle_sha256"),
        },
        "allowed_modes": allowed_modes,
        "default_mode": default_mode,
        "tools": tools_status,
        "models_per_profile": models_per_profile,
        "resolved_defaults": resolved_defaults,
        "usable_verify_targets": usable_verify_targets,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Task ID      : {task['id']} ({canonical_state})")
        print(f"Allowed modes: {', '.join(allowed_modes) if allowed_modes else 'none'}")
        print(f"Default mode : {default_mode}")
        print("\nTools:")
        for tn, ts in tools_status.items():
            st = "available" if ts["available"] else f"unavailable ({ts['reason']})"
            print(f"  {tn:<10} -> {st} (v={ts['version'] or '-'})")
    return 0


def validate_run_request(
    args: argparse.Namespace,
) -> tuple[bool, tuple[str, str] | None, dict[str, Any] | None]:
    """Validate launch request fields and return computed plan parameters."""
    plat_err = check_platform()
    if plat_err:
        return False, (plat_err, "Runs engine is supported on macOS and Linux only (fcntl required)"), None

    task_id = args.task
    valid_task, task_err = check_task_id(task_id)
    if not valid_task:
        reason = "initiative-tasks-not-supported" if "Initiative" in (task_err or "") else "invalid-task-id"
        return False, (reason, task_err or "Invalid task ID"), None

    ws = pathlib.Path(args.workspace or ".").resolve()
    tasks_dir = ws / "tasks"
    if not tasks_dir.is_dir():
        return False, ("tasks-dir-not-found", f"Tasks directory not found at {tasks_dir}"), None

    if discover_emergent_tasks is None:
        return False, ("engine-missing", "tasks_engine module could not be imported"), None

    all_tasks = discover_emergent_tasks(tasks_dir)
    task = next((t for t in all_tasks if t["id"] == task_id), None)
    if not task:
        return False, ("task-not-found", f"Task '{task_id}' not found in tasks directory"), None

    canonical_state = task.get("canonical_state", "open")
    mode = args.mode or get_default_mode_for_state(canonical_state)
    if not mode:
        return False, ("no-modes-allowed", f"No run modes allowed for task in state '{canonical_state}'"), None

    all_runs = list_run_records(ws, task_id=task_id)
    has_existing_run = any(r.get("task_id") == task_id for r in all_runs)
    mode_valid, mode_err = check_task_state_and_mode(
        canonical_state, mode, has_existing_run=has_existing_run
    )
    if not mode_valid:
        return False, ("invalid-mode-for-state", mode_err or "Invalid mode for task state"), None

    gpath = getattr(args, "global_config", None)
    merged_cfg, _ = resolve_config(gpath, ws)
    project_cfg_path = find_project_config_path(ws, gpath)
    project_cfg = load_toml_file(project_cfg_path) if project_cfg_path.exists() else None
    global_cfg = load_toml_file(gpath or default_global_config_path())

    target_repo, _, repo_err = resolve_target_repo(ws, task.get("paths"))
    if repo_err:
        return False, ("multi-repo-paths", repo_err), None
    if not target_repo:
        target_repo = ws

    target_run_id: str | None = None
    target_run_tool: str | None = None
    target_commit: str | None = None

    if mode == "verify":
        target_run_id = args.target_run
        if not target_run_id:
            succeeded_runs = [
                r for r in all_runs if r.get("mode") == "execute" and r.get("status") == "succeeded"
            ]
            if succeeded_runs:
                target_run_id = succeeded_runs[0]["run_id"]
                target_run_tool = succeeded_runs[0].get("tool")
                target_commit = succeeded_runs[0].get("final_commit")
            else:
                target_run_id = "none"
        elif target_run_id != "none":
            matched_run = next((r for r in all_runs if r.get("run_id") == target_run_id), None)
            if not matched_run:
                return False, ("target-run-not-found", f"Target run '{target_run_id}' not found"), None
            if matched_run.get("status") != "succeeded":
                return (
                    False,
                    (
                        "target-run-not-succeeded",
                        f"Target run '{target_run_id}' status is '{matched_run.get('status')}', must be 'succeeded'",
                    ),
                    None,
                )
            target_run_tool = matched_run.get("tool")
            target_commit = matched_run.get("final_commit")

        if target_run_id == "none" or not target_commit:
            target_commit = get_repo_head(target_repo)

    tool, chosen_entry = resolve_tool(
        mode=mode,
        requested_tool=args.tool,
        task=task,
        merged_cfg=merged_cfg,
        project_cfg=project_cfg,
        global_cfg=global_cfg,
        allow_same_tool=args.allow_same_tool,
        target_run_tool=target_run_tool,
    )
    if not tool:
        return False, ("tool-resolution-failed", "Could not resolve a suitable tool for this request"), None

    indep_valid, indep_err = check_independence_guard(
        mode=mode,
        tool=tool,
        task_executor=task.get("executor"),
        target_run_tool=target_run_tool,
        allow_same_tool=args.allow_same_tool,
    )
    if not indep_valid:
        return False, ("independence-violation", indep_err or "Independence guard violation"), None

    tool_cfg = merged_cfg.get("tools", {}).get(tool, {})
    avail, _, avail_err = check_tool_availability(tool, tool_cfg)
    if not avail:
        reason = "tool-disabled" if "disabled" in (avail_err or "") else "tool-not-installed"
        return False, (reason, avail_err or f"Tool '{tool}' is not available"), None

    profile = resolve_profile(
        mode=mode,
        requested_profile=args.profile,
        task=task,
        merged_cfg=merged_cfg,
        project_cfg=project_cfg,
        global_cfg=global_cfg,
        chosen_cross_order_entry=chosen_entry,
    )

    model, variant, effort = resolve_model_and_variants(
        tool=tool,
        profile=profile,
        requested_model=args.model,
        requested_variant=args.variant,
        requested_effort=args.effort,
        merged_cfg=merged_cfg,
    )
    if not model:
        return False, ("model-not-configured", f"No model configured for tool '{tool}' profile '{profile}'"), None

    isolation = args.isolation or ("worktree" if mode == "execute" else "none")

    planned_branch: str | None = None
    planned_worktree: str | None = None
    if mode == "execute":
        if isolation == "worktree":
            planned_branch = f"run/{task_id}"
            planned_worktree = str(target_repo.parent / ".worktrees" / target_repo.name / f"run-{task_id}")
            cwd = planned_worktree
        else:
            cwd = str(target_repo)
    elif mode == "verify":
        planned_branch = None
        planned_worktree = str(target_repo.parent / ".worktrees" / target_repo.name / f"verify-{task_id}")
        cwd = planned_worktree
    else:  # orchestrate
        cwd = str(ws)

    active_runs = [r for r in all_runs if r.get("status") in ACTIVE_STATES]
    task_act_valid, task_act_err = check_same_task_active(task_id, active_runs, force=args.force)
    if not task_act_valid:
        return False, ("same-task-active", task_act_err or "Task already has an active run"), None

    cwd_act_valid, cwd_act_err = check_same_cwd_active(cwd, isolation, active_runs)
    if not cwd_act_valid:
        return (
            False,
            ("same-cwd-active", cwd_act_err or "Working directory already has an active run with isolation 'none'"),
            None,
        )

    warnings: list[str] = []
    if mode == "verify" and args.allow_same_tool:
        if (task.get("executor") and tool.lower() == task.get("executor", "").lower()) or (
            target_run_tool and tool.lower() == target_run_tool.lower()
        ):
            warnings.append("Verification downgraded to independent-session: verifier tool matches executor tool.")

    if mode == "execute" and isolation == "worktree":
        is_clean, dirty_files = check_repo_clean(target_repo)
        if not is_clean:
            warnings.append(
                f"Target repository has uncommitted changes that will not be present in the worktree ({len(dirty_files)} dirty files)."
            )

    headless_cfg = tool_cfg.get("headless", {}) if isinstance(tool_cfg.get("headless"), dict) else {}
    if tool == "claude":
        pm = headless_cfg.get("permission_mode")
        if pm in ("bypassPermissions", "--dangerously-skip-permissions"):
            warnings.append(f"Tool 'claude' has elevated permission mode '{pm}'.")
        ok_at, _ = check_claude_allowed_tools(headless_cfg, mode)
        if not ok_at:
            warnings.append(
                f"Claude has no configured 'allowed_tools' for mode '{mode}' under [tools.claude.headless]; launch will be refused until configured."
            )
    elif tool == "codex":
        sb = headless_cfg.get("sandbox")
        if sb in ("danger-full-access", "read-write-full"):
            warnings.append(f"Tool 'codex' has elevated sandbox mode '{sb}'.")

    prompt = build_prompt(mode, task, target_commit=target_commit, instructions=args.instructions)
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    raw_argv = build_adapter_argv(
        tool=tool,
        tool_cfg=tool_cfg,
        mode=mode,
        cwd=cwd,
        model=model,
        variant=variant,
        effort=effort,
        session_id="{session_id}",
        prompt_file="{prompt_file}",
    )
    argv_display = redact_argv(raw_argv)

    canonical_request: dict[str, Any] = {
        "allow_same_tool": bool(args.allow_same_tool),
        "effort": effort,
        "instructions": args.instructions or "",
        "isolation": isolation,
        "mode": mode,
        "model": model,
        "profile": profile,
        "target_run": target_run_id or "none",
        "task": task_id,
        "tool": tool,
        "variant": variant,
    }

    bundle_hash = task.get("bundle_sha256") or (task_bundle_sha256(task) if task_bundle_sha256 else "")
    repo_head = get_repo_head(target_repo)
    plan_hash = compute_plan_hash(
        canonical_request=canonical_request,
        task_bundle_hash=bundle_hash,
        effective_argv_redacted=argv_display,
        prompt=prompt,
        repo_head=repo_head,
        effective_config=merged_cfg,
    )

    data = {
        "task_id": task_id,
        "task": task,
        "canonical_state": canonical_state,
        "mode": mode,
        "ws": ws,
        "merged_cfg": merged_cfg,
        "project_cfg": project_cfg,
        "global_cfg": global_cfg,
        "target_repo": target_repo,
        "target_run_id": target_run_id,
        "target_run_tool": target_run_tool,
        "target_commit": target_commit,
        "tool": tool,
        "tool_cfg": tool_cfg,
        "profile": profile,
        "model": model,
        "variant": variant,
        "effort": effort,
        "isolation": isolation,
        "cwd": cwd,
        "planned_branch": planned_branch,
        "planned_worktree": planned_worktree,
        "prompt": prompt,
        "prompt_sha256": prompt_sha256,
        "raw_argv": raw_argv,
        "argv_display": argv_display,
        "canonical_request": canonical_request,
        "bundle_hash": bundle_hash,
        "repo_head": repo_head,
        "plan_hash": plan_hash,
        "warnings": warnings,
    }
    return True, None, data


def cmd_preview(args: argparse.Namespace) -> int:
    ok, err_info, data = validate_run_request(args)
    if not ok:
        reason, err_msg = err_info  # type: ignore
        print_error(args.json, reason, err_msg)
        return 1

    payload = {
        "ok": True,
        "prompt": data["prompt"],  # type: ignore
        "prompt_sha256": data["prompt_sha256"],  # type: ignore
        "argv_display": data["argv_display"],  # type: ignore
        "cwd": data["cwd"],  # type: ignore
        "planned_worktree": data["planned_worktree"],  # type: ignore
        "planned_branch": data["planned_branch"],  # type: ignore
        "warnings": data["warnings"],  # type: ignore
        "plan_hash": data["plan_hash"],  # type: ignore
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Mode            : {data['mode']}")  # type: ignore
        print(f"Tool / Profile  : {data['tool']} / {data['profile']}")  # type: ignore
        print(f"Model           : {data['model']}")  # type: ignore
        print(f"Working Dir     : {data['cwd']}")  # type: ignore
        print(f"Planned Branch  : {data['planned_branch'] or 'none'}")  # type: ignore
        print(f"Planned Worktree: {data['planned_worktree'] or 'none'}")  # type: ignore
        print(f"Plan Hash       : {data['plan_hash']}")  # type: ignore
        if data["warnings"]:  # type: ignore
            print("\nWarnings:")
            for w in data["warnings"]:  # type: ignore
                print(f"  [WARN] {w}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        print_error(args.json, plat_err, "Runs engine is supported on macOS and Linux only (fcntl required)")
        return 1

    req_by = getattr(args, "requested_by", "cli") or "cli"
    if req_by in ("ui", "vscode") and not getattr(args, "expect_plan_hash", None):
        print_error(
            args.json,
            "missing-plan-hash",
            "--expect-plan-hash is required when requested by ui or vscode (R1)",
        )
        return 1

    ok, err_info, data = validate_run_request(args)
    if not ok:
        reason, err_msg = err_info  # type: ignore
        print_error(args.json, reason, err_msg)
        return 1

    # Worktree isolation check (07.3 scope: execute with worktree not implemented yet)
    if data["mode"] == "execute" and data["isolation"] != "none":  # type: ignore
        print_error(
            args.json,
            "not-implemented-yet",
            "Worktree isolation is not implemented yet in 07.3; specify --isolation none",
        )
        return 1

    # Claude allowed_tools check (R11)
    if data["tool"] == "claude":  # type: ignore
        tool_cfg = data["merged_cfg"].get("tools", {}).get("claude", {})  # type: ignore
        headless_cfg = tool_cfg.get("headless", {}) if isinstance(tool_cfg.get("headless"), dict) else {}
        ok_at, at_err = check_claude_allowed_tools(headless_cfg, data["mode"])  # type: ignore
        if not ok_at:
            print_error(args.json, "missing-allowed-tools", at_err or "Missing allowed_tools for Claude")
            return 1

    expect_hash = getattr(args, "expect_plan_hash", None)
    if expect_hash:
        if expect_hash.strip().lower() != data["plan_hash"].lower():  # type: ignore
            print_error(
                args.json,
                "plan-hash-mismatch",
                f"Plan hash mismatch: expected {expect_hash}, computed {data['plan_hash']}",  # type: ignore
            )
            return 1

    ws = data["ws"]  # type: ignore
    task_id = data["task_id"]  # type: ignore

    with run_lock(ws):
        all_runs = list_run_records(ws, task_id=task_id)
        active_runs = [r for r in all_runs if r.get("status") in ACTIVE_STATES]

        task_act_ok, task_act_err = check_same_task_active(task_id, active_runs, force=args.force)
        if not task_act_ok:
            print_error(args.json, "same-task-active", task_act_err or "Task already has an active run")
            return 1

        cwd_act_ok, cwd_act_err = check_same_cwd_active(data["cwd"], data["isolation"], active_runs)  # type: ignore
        if not cwd_act_ok:
            print_error(
                args.json,
                "same-cwd-active",
                cwd_act_err or "Working directory already has an active run with isolation 'none'",
            )
            return 1

        ex_ok, ex_err = ensure_git_exclude(data["target_repo"])  # type: ignore
        if not ex_ok:
            print_error(args.json, "git-exclude-failed", ex_err or "Could not ensure .ai-orchestration/ is ignored")
            return 1

        run_id = generate_run_id(task_id, data["tool"])  # type: ignore
        run_dir = ws / ".ai-orchestration" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass

        prompt_path = run_dir / "prompt.md"
        prompt_path.write_text(data["prompt"], encoding="utf-8")  # type: ignore
        try:
            os.chmod(prompt_path, 0o600)
        except OSError:
            pass

        session_id = str(uuid.uuid4()) if data["tool"] == "claude" else None  # type: ignore

        record = create_run_record(
            run_id=run_id,
            task_id=task_id,
            mode=data["mode"],  # type: ignore
            tool=data["tool"],  # type: ignore
            profile=data["profile"],  # type: ignore
            model=data["model"],  # type: ignore
            variant=data["variant"],  # type: ignore
            effort=data["effort"],  # type: ignore
            requested_by=req_by,
            workspace=str(ws),
            cwd=data["cwd"],  # type: ignore
            isolation=data["isolation"],  # type: ignore
            task_bundle_sha256=data["bundle_hash"],  # type: ignore
            argv_display=data["argv_display"],  # type: ignore
            plan_hash=data["plan_hash"],  # type: ignore
            worktree_path=data["planned_worktree"],  # type: ignore
            branch=data["planned_branch"],  # type: ignore
            target_run=data["target_run_id"],  # type: ignore
            target_commit=data["target_commit"],  # type: ignore
        )
        if session_id:
            record["session_id"] = session_id

        save_run_record(ws, record)

        sup_cmd = [
            sys.executable,
            str(pathlib.Path(__file__).resolve()),
            "_supervise",
            str(run_dir),
        ]
        gpath = getattr(args, "global_config", None)
        if gpath:
            sup_cmd.extend(["--global-config", str(gpath)])

        subprocess.Popen(
            sup_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    if args.json:
        print(json.dumps({"ok": True, "run_id": run_id, "status": "starting", "plan_hash": data["plan_hash"]}, indent=2))  # type: ignore
    else:
        print(f"Run {run_id} started (status: starting).")
    return 0


def cmd_supervise(args: argparse.Namespace) -> int:
    run_dir = pathlib.Path(args.run_dir).resolve()
    run_file = run_dir / "run.json"
    if not run_file.is_file():
        return 1
    try:
        record = json.loads(run_file.read_text(encoding="utf-8"))
    except Exception:
        return 1

    workspace = pathlib.Path(record["workspace"])

    # 1. Record supervisor identity FIRST (Instruction 2)
    my_pid = os.getpid()
    my_start_time = get_process_start_time(my_pid)
    record["supervisor"] = {"pid": my_pid, "start_time": my_start_time}
    save_run_record(workspace, record)

    # 2. Prepare adapter argv
    gpath = getattr(args, "global_config", None)
    merged_cfg, _ = resolve_config(gpath, workspace)
    tool_cfg = merged_cfg.get("tools", {}).get(record["tool"], {})
    headless_cfg = tool_cfg.get("headless", {}) if isinstance(tool_cfg.get("headless"), dict) else {}

    session_id = record.get("session_id")
    if not session_id and record["tool"] == "claude":
        session_id = str(uuid.uuid4())
        record["session_id"] = session_id

    prompt_path = run_dir / "prompt.md"
    raw_argv = build_adapter_argv(
        tool=record["tool"],
        tool_cfg=tool_cfg,
        mode=record["mode"],
        cwd=record["cwd"],
        model=record["model"],
        variant=record.get("variant"),
        effort=record.get("effort"),
        session_id=session_id or "{session_id}",
        prompt_file=str(prompt_path),
    )

    prompt_via = headless_cfg.get("prompt_via")
    if not prompt_via:
        if record["tool"] == "kilo" or ("{prompt_file}" in headless_cfg.get("argv", [])):
            prompt_via = "file"
        else:
            prompt_via = "stdin"

    expanded_argv = expand_secret_env_vars(raw_argv)
    prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""

    cwd_path = pathlib.Path(record["cwd"])
    cwd_path.mkdir(parents=True, exist_ok=True)

    # 3. Spawn agent process in new process group (Instruction 2)
    try:
        proc = subprocess.Popen(
            expanded_argv,
            stdin=subprocess.PIPE if prompt_via == "stdin" else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd_path),
            start_new_session=True,
        )
    except Exception as e:
        record["status"] = "failed"
        record["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record["exit_code"] = 1
        with open(run_dir / "stderr.log", "a", encoding="utf-8") as f:
            f.write(f"Failed to spawn agent: {e}\n")
        save_run_record(workspace, record)
        return 1

    # 4. Record agent identity and set status to running (Instruction 2)
    agent_pid = proc.pid
    try:
        agent_pgid = os.getpgid(proc.pid)
    except OSError:
        agent_pgid = proc.pid
    agent_start_time = get_process_start_time(agent_pid)
    record["agent"] = {"pid": agent_pid, "pgid": agent_pgid, "start_time": agent_start_time}
    record["status"] = "running"
    save_run_record(workspace, record)

    # 5. Write prompt to stdin if prompt_via == "stdin"
    if prompt_via == "stdin" and proc.stdin:
        try:
            proc.stdin.write(prompt_text.encode("utf-8"))
            proc.stdin.flush()
            proc.stdin.close()
        except Exception:
            pass

    # 6. Execute mode: transition task to "in progress" (Instruction 2)
    if record.get("mode") == "execute":
        try:
            tasks_dir = workspace / "tasks"
            if tasks_dir.is_dir() and discover_emergent_tasks and transition_task:
                all_tasks = discover_emergent_tasks(tasks_dir)
                t = next((x for x in all_tasks if x["id"] == record["task_id"]), None)
                if t and t.get("canonical_state") in ("open", "bounced"):
                    ok, trans_res = transition_task(
                        tasks_dir=tasks_dir,
                        task_id=record["task_id"],
                        new_state="in progress",
                        actor=record.get("tool"),
                    )
                    if not ok:
                        record["task_transition_error"] = trans_res.get("error") or str(trans_res)
                        save_run_record(workspace, record)
        except Exception as e:
            record["task_transition_error"] = str(e)
            save_run_record(workspace, record)

    # 7. Stream stdout and stderr
    stderr_log = run_dir / "stderr.log"

    def stream_stderr():
        try:
            with open(stderr_log, "ab", buffering=0) as f:
                try:
                    os.chmod(stderr_log, 0o600)
                except OSError:
                    pass
                while True:
                    chunk = proc.stderr.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        except Exception:
            pass

    t_err = threading.Thread(target=stream_stderr, daemon=True)
    t_err.start()

    max_chunk_size = DEFAULT_LOG_CHUNK_SIZE
    chunk_manifest_path = run_dir / "chunks.json"
    manifest: list[dict[str, Any]] = []

    def stream_stdout():
        chunk_idx = 0
        current_offset = 0
        chunk_start_offset = 0
        cur_fn = f"events.{chunk_idx:03d}.jsonl"
        cur_path = run_dir / cur_fn
        cur_file = open(cur_path, "ab", buffering=0)
        try:
            os.chmod(cur_path, 0o600)
        except OSError:
            pass
        chunk_written = 0

        def rotate():
            nonlocal chunk_idx, current_offset, chunk_start_offset, cur_fn, cur_path, cur_file, chunk_written
            cur_file.close()
            manifest.append({
                "chunk": chunk_idx,
                "file": cur_fn,
                "start_offset": chunk_start_offset,
                "end_offset": current_offset,
            })
            chunk_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            chunk_idx += 1
            chunk_start_offset = current_offset
            chunk_written = 0
            cur_fn = f"events.{chunk_idx:03d}.jsonl"
            cur_path = run_dir / cur_fn
            cur_file = open(cur_path, "ab", buffering=0)
            try:
                os.chmod(cur_path, 0o600)
            except OSError:
                pass

        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break

                if chunk_written > 0 and (chunk_written + len(line) > max_chunk_size):
                    rotate()

                cur_file.write(line)
                chunk_written += len(line)
                current_offset += len(line)

            cur_file.close()
            manifest.append({
                "chunk": chunk_idx,
                "file": cur_fn,
                "start_offset": chunk_start_offset,
                "end_offset": current_offset,
            })
            chunk_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            if cur_file:
                cur_file.close()

    t_out = threading.Thread(target=stream_stdout, daemon=True)
    t_out.start()

    # Wait for process exit
    exit_code = proc.wait()
    t_out.join(timeout=5.0)
    t_err.join(timeout=5.0)

    # 8. Completion handling
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cur_record = load_run_record(workspace, record["run_id"])
    if cur_record and cur_record.get("status") in TERMINAL_STATES:
        final_status = cur_record["status"]
    else:
        final_status = "succeeded" if exit_code == 0 else "failed"

    record["status"] = final_status
    record["exit_code"] = exit_code
    record["ended_at"] = now_iso

    save_run_record(workspace, record)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        print_error(args.json, plat_err, "Runs engine is supported on macOS and Linux only (fcntl required)")
        return 1

    run_id = args.run_id
    if not validate_run_id(run_id):
        print_error(args.json, "invalid-run-id", f"Invalid run_id format '{run_id}'")
        return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    run_dir = ws / ".ai-orchestration" / "runs" / run_id
    if not run_dir.is_dir():
        print_error(args.json, "not-found", f"Run '{run_id}' not found")
        return 1

    since_offset = getattr(args, "since_offset", 0) or 0
    first_avail, next_offset, data_bytes = read_log_chunks(run_dir, since_offset=since_offset)

    tail_n = getattr(args, "tail", None)

    if getattr(args, "raw", False):
        raw_text = data_bytes.decode("utf-8", errors="replace")
        raw_lines = raw_text.splitlines()
        if tail_n is not None and tail_n > 0:
            raw_lines = raw_lines[-tail_n:]
        final_raw = "\n".join(raw_lines)
        if args.json:
            print(json.dumps({
                "ok": True,
                "run_id": run_id,
                "first_available_offset": first_avail,
                "next_offset": next_offset,
                "raw": final_raw,
            }, indent=2))
        else:
            if final_raw:
                print(final_raw)
        return 0

    events = parse_log_events(data_bytes)
    if tail_n is not None and tail_n > 0:
        events = events[-tail_n:]

    if args.json:
        print(json.dumps({
            "ok": True,
            "run_id": run_id,
            "first_available_offset": first_avail,
            "next_offset": next_offset,
            "events": events,
        }, indent=2))
    else:
        for evt in events:
            if "text" in evt:
                print(evt["text"])
            elif "tool_call" in evt:
                print(f"[TOOL] {evt['tool_call']}")
            elif "error" in evt:
                print(f"[ERROR] {evt['error']}")
            else:
                print(json.dumps(evt.get("raw", evt)))
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        print_error(args.json, plat_err, "Runs engine is supported on macOS and Linux only (fcntl required)")
        return 1

    run_id = args.run_id
    if not validate_run_id(run_id):
        print_error(args.json, "invalid-run-id", f"Invalid run_id format '{run_id}'")
        return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    with run_lock(ws):
        run_file = ws / ".ai-orchestration" / "runs" / run_id / "run.json"
        if not run_file.is_file():
            print_error(args.json, "not-found", f"Run '{run_id}' not found")
            return 1

        try:
            record = json.loads(run_file.read_text(encoding="utf-8"))
        except Exception as e:
            print_error(args.json, "record-corrupt", f"Failed to load run record: {e}")
            return 1

        status = record.get("status")
        if status in TERMINAL_STATES:
            if status == "cancelled":
                if args.json:
                    print(json.dumps({"ok": True, "run_id": run_id, "status": "cancelled", "message": "Run is already cancelled"}, indent=2))
                else:
                    print(f"Run {run_id} is already cancelled.")
                return 0
            else:
                print_error(args.json, "run-terminal", f"Cannot cancel run in terminal state '{status}'")
                return 1

        record["status"] = "cancelled"
        record["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_run_record(ws, record)

    # Outside the flock, kill process group
    agent = record.get("agent", {})
    agent_pid = agent.get("pid")
    agent_pgid = agent.get("pgid")
    agent_start = agent.get("start_time")
    if agent_pid and agent_pgid and agent_start:
        kill_process_group(
            pgid=agent_pgid,
            leader_pid=agent_pid,
            expected_leader_start_time=agent_start,
            timeout=10.0,
        )

    # Also signal supervisor if running
    sup = record.get("supervisor", {})
    sup_pid = sup.get("pid")
    sup_start = sup.get("start_time")
    if sup_pid and sup_start and is_process_alive(sup_pid, sup_start):
        try:
            os.kill(sup_pid, signal.SIGTERM)
        except OSError:
            pass

    if args.json:
        print(json.dumps({"ok": True, "run_id": run_id, "status": "cancelled"}, indent=2))
    else:
        print(f"Run {run_id} cancelled.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        print_error(args.json, plat_err, "Runs engine is supported on macOS and Linux only (fcntl required)")
        return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    runs = list_run_records(ws, task_id=args.task, active_only=args.active)

    if args.json:
        print(json.dumps({"ok": True, "runs": runs}, indent=2))
    else:
        if not runs:
            print("No agent runs found.")
        else:
            print(f"{'RUN ID':<36} {'TASK':<6} {'MODE':<11} {'TOOL':<7} {'STATUS':<10} {'STARTED AT'}")
            print("-" * 90)
            for r in runs:
                print(
                    f"{r['run_id']:<36} {r.get('task_id','-'):<6} {r.get('mode','-'):<11} "
                    f"{r.get('tool','-'):<7} {r.get('status','-'):<10} {r.get('started_at','-')[:19]}"
                )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    plat_err = check_platform()
    if plat_err:
        print_error(args.json, plat_err, "Runs engine is supported on macOS and Linux only (fcntl required)")
        return 1

    run_id = args.run_id
    if not validate_run_id(run_id):
        print_error(args.json, "invalid-run-id", f"Invalid run_id format '{run_id}'")
        return 1

    ws = pathlib.Path(args.workspace or ".").resolve()
    record = load_run_record(ws, run_id)
    if not record:
        print_error(args.json, "not-found", f"Run '{run_id}' not found")
        return 1

    if args.json:
        print(json.dumps({"ok": True, "run": record}, indent=2))
    else:
        print(f"Run ID     : {record['run_id']}")
        print(f"Task       : {record.get('task_id')}")
        print(f"Mode       : {record.get('mode')}")
        print(f"Tool       : {record.get('tool')}")
        print(f"Status     : {record.get('status')}")
        print(f"Started At : {record.get('started_at')}")
        print(f"Ended At   : {record.get('ended_at') or '-'}")
        print(f"Plan Hash  : {record.get('plan_hash') or '-'}")
    return 0


# ---------------------------------------------------------------------------
# Argument Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--global-config", type=pathlib.Path, default=None, help="Override path to global orchestration.toml")
    ap.add_argument("--json", action="store_true", help="Output structured JSON on stdout")

    sub = ap.add_subparsers(dest="cmd", required=True)

    # options
    p_opt = sub.add_parser("options", help="Show tools availability and resolved defaults for a task")
    p_opt.add_argument("--task", required=True, help="Task ID (e.g. T007)")
    p_opt.add_argument("--workspace", default=None, help="Project workspace root")
    p_opt.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_opt.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_opt.set_defaults(func=cmd_options)

    # preview
    p_prev = sub.add_parser("preview", help="Validate launch request and return binding preview")
    p_prev.add_argument("--task", required=True, help="Task ID (e.g. T007)")
    p_prev.add_argument("--mode", choices=("orchestrate", "execute", "verify"), default=None)
    p_prev.add_argument("--tool", default=None, help="Target tool (kilo, claude, codex)")
    p_prev.add_argument("--profile", default=None, help="Role profile")
    p_prev.add_argument("--model", default=None, help="Model identifier")
    p_prev.add_argument("--variant", default=None, help="Reasoning variant")
    p_prev.add_argument("--effort", default=None, help="Reasoning effort")
    p_prev.add_argument("--isolation", choices=("worktree", "none"), default=None)
    p_prev.add_argument("--target-run", default=None, help="Target execute run ID for verify mode (or 'none')")
    p_prev.add_argument("--instructions", default=None, help="Additional prompt instructions")
    p_prev.add_argument("--allow-same-tool", action="store_true", help="Allow same tool for verify (downgrades to independent-session)")
    p_prev.add_argument("--allow-dirty-base", action="store_true", help="Proceed from dirty HEAD with warning")
    p_prev.add_argument("--force", action="store_true", help="Bypass same-task active run guard")
    p_prev.add_argument("--workspace", default=None, help="Project workspace root")
    p_prev.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_prev.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_prev.set_defaults(func=cmd_preview)

    # start
    p_start = sub.add_parser("start", help="Start agent run with supervisor")
    p_start.add_argument("--task", required=True, help="Task ID (e.g. T007)")
    p_start.add_argument("--mode", choices=("orchestrate", "execute", "verify"), default=None)
    p_start.add_argument("--tool", default=None, help="Target tool (kilo, claude, codex)")
    p_start.add_argument("--profile", default=None, help="Role profile")
    p_start.add_argument("--model", default=None, help="Model identifier")
    p_start.add_argument("--variant", default=None, help="Reasoning variant")
    p_start.add_argument("--effort", default=None, help="Reasoning effort")
    p_start.add_argument("--isolation", choices=("worktree", "none"), default=None)
    p_start.add_argument("--target-run", default=None, help="Target execute run ID for verify mode (or 'none')")
    p_start.add_argument("--instructions", default=None, help="Additional prompt instructions")
    p_start.add_argument("--allow-same-tool", action="store_true", help="Allow same tool for verify (downgrades to independent-session)")
    p_start.add_argument("--allow-dirty-base", action="store_true", help="Proceed from dirty HEAD with warning")
    p_start.add_argument("--force", action="store_true", help="Bypass same-task active run guard")
    p_start.add_argument("--expect-plan-hash", default=None, help="Required for ui/vscode, optional for cli")
    p_start.add_argument("--requested-by", choices=("ui", "vscode", "cli"), default="cli", help="Caller origin")
    p_start.add_argument("--workspace", default=None, help="Project workspace root")
    p_start.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_start.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_start.set_defaults(func=cmd_start)

    # logs
    p_logs = sub.add_parser("logs", help="Display run logs with logical offsets across chunks")
    p_logs.add_argument("run_id", help="Run ID")
    p_logs.add_argument("--tail", type=int, default=None, help="Show last N lines/events")
    p_logs.add_argument("--since-offset", type=int, default=0, help="Logical byte offset to start reading from")
    p_logs.add_argument("--raw", action="store_true", help="Output raw stream instead of parsed summary")
    p_logs.add_argument("--workspace", default=None, help="Project workspace root")
    p_logs.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_logs.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_logs.set_defaults(func=cmd_logs)

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel active run by terminating process group")
    p_cancel.add_argument("run_id", help="Run ID")
    p_cancel.add_argument("--workspace", default=None, help="Project workspace root")
    p_cancel.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_cancel.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_cancel.set_defaults(func=cmd_cancel)

    # _supervise (internal)
    p_sup = sub.add_parser("_supervise", help="Internal runner supervisor")
    p_sup.add_argument("run_dir", help="Path to run directory")
    p_sup.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_sup.set_defaults(func=cmd_supervise)

    # list
    p_list = sub.add_parser("list", help="List agent runs after reconciliation")
    p_list.add_argument("--task", default=None, help="Filter by task ID")
    p_list.add_argument("--active", action="store_true", help="Filter by active runs only")
    p_list.add_argument("--workspace", default=None, help="Project workspace root")
    p_list.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_list.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = sub.add_parser("show", help="Display run record after reconciliation")
    p_show.add_argument("run_id", help="Run ID (e.g. 20261017-123456-T007-kilo-a1b2)")
    p_show.add_argument("--workspace", default=None, help="Project workspace root")
    p_show.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_show.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_show.set_defaults(func=cmd_show)

    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
