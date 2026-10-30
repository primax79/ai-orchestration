#!/usr/bin/env python3
"""orchestration_invoke.py — Shared supervised-invocation primitive for ai-orchestration.

Implements Spec §0c E4:
  - Extracted shared invocation primitive (adapters, process groups, logging, timeout, cancel)
  - Used by run supervisors and orchestrator turns
  - Process group management with process tree descendant kill from T022
  - Chunked stdout capture with manifest and unbuffered stderr capture
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
import datetime
import json
import logging
import os
import pathlib
import signal
import subprocess
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("orchestration_invoke")

DEFAULT_LOG_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB chunks (Spec §5.1, R9)
_USE_PROCFS = True


# ---------------------------------------------------------------------------
# Process Inspection & Lifecycle Helpers (T022)
# ---------------------------------------------------------------------------

def get_process_start_time(pid: int) -> str | None:
    """Get the process start time (ps -o lstart= -p <pid>) to detect PID reuse."""
    try:
        res = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def _is_pid_zombie(pid: int) -> bool:
    """Return True if pid has already terminated (zombie 'Z' or dead 'X'), or no longer exists."""
    if _USE_PROCFS:
        stat_path = pathlib.Path(f"/proc/{pid}/stat")
        if stat_path.exists():
            try:
                data = stat_path.read_text(encoding="utf-8", errors="replace")
                idx = data.rfind(")")
                if idx != -1:
                    state = data[idx + 1 :].strip()[:1]
                    return state in ("Z", "X", "x")
            except FileNotFoundError:
                return True
            except OSError:
                pass

    try:
        res = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return True
        stat_str = res.stdout.strip()
        if not stat_str or stat_str[0] in ("Z", "X", "x"):
            return True
    except Exception:
        pass
    return False


def _is_process_group_alive(pgid: int) -> bool:
    """Return True if at least one non-zombie process exists in process group pgid."""
    if pgid <= 0:
        return False
    try:
        os.killpg(pgid, 0)
    except PermissionError:
        pass
    except OSError:
        return False

    for ps_cmd in (
        ["ps", "-A", "-o", "pid=", "-o", "pgid=", "-o", "stat="],
        ["ps", "-ax", "-o", "pid=", "-o", "pgid=", "-o", "stat="],
    ):
        try:
            res = subprocess.run(ps_cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                parsed_any = False
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        try:
                            p_pgid = int(parts[1])
                            p_stat = parts[2]
                            parsed_any = True
                            if p_pgid == pgid and not p_stat.startswith(("Z", "X", "x")):
                                return True
                        except ValueError:
                            continue
                if parsed_any:
                    return False
        except Exception:
            pass
    return True


def is_process_alive(pid: int, expected_start_time: str | None = None) -> bool:
    """Check if a process is alive, guarding against zombies and PID reuse if expected_start_time is given."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if _is_pid_zombie(pid):
        return False
    if expected_start_time is not None:
        cur_start = get_process_start_time(pid)
        return cur_start is not None and cur_start == expected_start_time
    return True


def get_process_descendants(root_pid: int) -> list[int]:
    """Find all descendant process IDs of root_pid by recursively walking the process tree."""
    if root_pid <= 0:
        return []

    # First attempt: ps with separate -o flags (portable across Linux procps and macOS BSD ps)
    for ps_cmd in (
        ["ps", "-A", "-o", "pid=", "-o", "ppid="],
        ["ps", "-ax", "-o", "pid=", "-o", "ppid="],
        ["ps", "-o", "pid=", "-o", "ppid="],
    ):
        try:
            res = subprocess.run(ps_cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                parent_to_children: dict[int, list[int]] = collections.defaultdict(list)
                parsed_any = False
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            pid, ppid = int(parts[0]), int(parts[1])
                            parent_to_children[ppid].append(pid)
                            parsed_any = True
                        except ValueError:
                            continue
                if not parsed_any:
                    continue
                descendants: list[int] = []
                queue = collections.deque(parent_to_children.get(root_pid, []))
                visited = {root_pid}
                while queue:
                    curr = queue.popleft()
                    if curr in visited:
                        continue
                    visited.add(curr)
                    descendants.append(curr)
                    queue.extend(parent_to_children.get(curr, []))
                return descendants
        except Exception:
            pass

    # Fallback: pgrep -P recursively
    try:
        descendants = []
        queue = collections.deque([root_pid])
        visited = {root_pid}
        while queue:
            curr = queue.popleft()
            res = subprocess.run(["pgrep", "-P", str(curr)], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line:
                        try:
                            child_pid = int(line)
                            if child_pid not in visited:
                                visited.add(child_pid)
                                descendants.append(child_pid)
                                queue.append(child_pid)
                        except ValueError:
                            continue
        return descendants
    except Exception:
        return []


def kill_process_group(
    pgid: int,
    leader_pid: int | None = None,
    expected_leader_start_time: str | None = None,
    timeout: float = 10.0,
    reap_fn: Callable[[], Any] | None = None,
) -> bool:
    """Send SIGTERM to process group and agent descendants, then SIGKILL if needed."""
    if pgid <= 0:
        return False

    if leader_pid is not None and expected_leader_start_time is not None:
        cur_start = get_process_start_time(leader_pid)
        if cur_start is None or cur_start != expected_leader_start_time:
            # PID reused or leader died with wrong start time: do NOT kill!
            return False

    # Collect descendants of leader BEFORE sending signals
    descendants: list[int] = []
    if leader_pid is not None:
        descendants = get_process_descendants(leader_pid)

    # 1. Send SIGTERM to descendants
    for dpid in descendants:
        try:
            os.kill(dpid, signal.SIGTERM)
        except OSError:
            pass

    # 2. Send SIGTERM to process group
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if reap_fn is not None:
            try:
                reap_fn()
            except Exception:
                pass

        group_alive = _is_process_group_alive(pgid)
        desc_alive = any(is_process_alive(dpid) for dpid in descendants)

        if not group_alive and not desc_alive:
            return True
        time.sleep(0.05)

    # Refresh descendants in case any were spawned before leader died
    all_descendants = set(descendants)
    if leader_pid is not None:
        all_descendants.update(get_process_descendants(leader_pid))

    # SIGKILL descendants
    for dpid in all_descendants:
        try:
            os.kill(dpid, signal.SIGKILL)
        except OSError:
            pass

    # SIGKILL process group
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass

    time.sleep(0.1)
    if reap_fn is not None:
        try:
            reap_fn()
        except Exception:
            pass

    group_alive = _is_process_group_alive(pgid)
    desc_alive = any(is_process_alive(dpid) for dpid in all_descendants)

    return not group_alive and not desc_alive


# ---------------------------------------------------------------------------
# Supervised Invocation Primitive (Spec §0c E4, E5)
# ---------------------------------------------------------------------------

@dataclass
class InvocationResult:
    """Outcome of a supervised process invocation."""
    exit_code: int
    timed_out: bool = False
    cancelled: bool = False
    pid: int | None = None
    pgid: int | None = None
    start_time: str | None = None
    ended_at: str | None = None
    duration_seconds: float = 0.0
    error: str | None = None


class SupervisedInvocation:
    """Manages execution of a child process in an isolated process group.

    Handles:
      - Process group isolation (start_new_session=True)
      - Stdin prompt injection
      - Output streaming to rotating log chunks (stdout) and log file (stderr)
      - Wall-clock timeout with whole process group termination
      - Graceful cancel via SIGTERM/SIGKILL process tree kill
    """

    def __init__(
        self,
        argv: list[str],
        cwd: pathlib.Path | str,
        *,
        prompt_text: str | None = None,
        prompt_via: str = "stdin",
        log_dir: pathlib.Path | str | None = None,
        stderr_path: pathlib.Path | str | None = None,
        max_chunk_size: int = DEFAULT_LOG_CHUNK_SIZE,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.argv = argv
        self.cwd = pathlib.Path(cwd).resolve()
        self.prompt_text = prompt_text
        self.prompt_via = prompt_via
        self.log_dir = pathlib.Path(log_dir).resolve() if log_dir else None
        self.stderr_path = pathlib.Path(stderr_path).resolve() if stderr_path else (self.log_dir / "stderr.log" if self.log_dir else None)
        self.max_chunk_size = max_chunk_size
        self.timeout = timeout
        self.env = env

        self.proc: subprocess.Popen[bytes] | None = None
        self.pid: int | None = None
        self.pgid: int | None = None
        self.start_time: str | None = None
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.cancelled = False
        self.timed_out = False

        self._t_out: threading.Thread | None = None
        self._t_err: threading.Thread | None = None
        self._start_monotonic: float = 0.0

    def start(self, on_started: Callable[[SupervisedInvocation], None] | None = None) -> SupervisedInvocation:
        """Spawn the process in a new process group and start I/O capture."""
        if not self.cwd.is_dir():
            raise FileNotFoundError(f"Working directory '{self.cwd}' does not exist")

        stdin_mode = subprocess.PIPE if (self.prompt_via == "stdin" and self.prompt_text is not None) else subprocess.DEVNULL

        self.proc = subprocess.Popen(
            self.argv,
            stdin=stdin_mode,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.cwd),
            start_new_session=True,
            env=self.env,
        )

        self._start_monotonic = time.time()
        self.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.pid = self.proc.pid
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except OSError:
            self.pgid = self.proc.pid
        self.start_time = get_process_start_time(self.pid)

        # Write prompt to stdin if requested
        if self.prompt_via == "stdin" and self.prompt_text is not None and self.proc.stdin:
            try:
                self.proc.stdin.write(self.prompt_text.encode("utf-8"))
                self.proc.stdin.flush()
                self.proc.stdin.close()
            except Exception:
                pass

        # Start stderr capture thread
        if self.stderr_path and self.proc.stderr:
            stderr_path = self.stderr_path
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            proc_stderr = self.proc.stderr

            def stream_stderr():
                try:
                    with open(stderr_path, "ab", buffering=0) as f:
                        try:
                            os.chmod(stderr_path, 0o600)
                        except OSError:
                            pass
                        while True:
                            chunk = proc_stderr.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                except Exception:
                    pass

            self._t_err = threading.Thread(target=stream_stderr, daemon=True)
            self._t_err.start()

        # Start stdout capture thread with chunking
        if self.log_dir and self.proc.stdout:
            log_dir = self.log_dir
            log_dir.mkdir(parents=True, exist_ok=True)
            max_size = self.max_chunk_size
            proc_stdout = self.proc.stdout

            def stream_stdout():
                chunk_idx = 0
                current_offset = 0
                chunk_start_offset = 0
                cur_fn = f"events.{chunk_idx:03d}.jsonl"
                cur_path = log_dir / cur_fn
                chunk_manifest_path = log_dir / "chunks.json"
                manifest: list[dict[str, Any]] = []

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
                    cur_path = log_dir / cur_fn
                    cur_file = open(cur_path, "ab", buffering=0)
                    try:
                        os.chmod(cur_path, 0o600)
                    except OSError:
                        pass

                try:
                    while True:
                        line = proc_stdout.readline()
                        if not line:
                            break

                        if chunk_written > 0 and (chunk_written + len(line) > max_size):
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

            self._t_out = threading.Thread(target=stream_stdout, daemon=True)
            self._t_out.start()

        if on_started is not None:
            on_started(self)

        return self

    def cancel(self, timeout: float = 10.0) -> bool:
        """Cancel the invocation by terminating its process group and descendants."""
        self.cancelled = True
        ok = False
        if self.pgid and self.pid and self.start_time:
            ok = kill_process_group(
                pgid=self.pgid,
                leader_pid=self.pid,
                expected_leader_start_time=self.start_time,
                timeout=timeout,
                reap_fn=self.proc.poll if self.proc is not None else None,
            )
        elif self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=timeout)
                ok = True
            except Exception:
                try:
                    self.proc.kill()
                    ok = True
                except Exception:
                    ok = False
        else:
            ok = True

        if self.proc:
            try:
                self.proc.wait(timeout=0.5)
            except Exception:
                pass
        return ok

    def wait(self, timeout: float | None = None) -> InvocationResult:
        """Wait for the process to terminate, with optional wall-clock timeout."""
        if self.proc is None:
            raise RuntimeError("Process was not started")

        effective_timeout = timeout if timeout is not None else self.timeout

        if effective_timeout is not None and effective_timeout > 0:
            deadline = time.time() + effective_timeout
            while time.time() < deadline:
                ret = self.proc.poll()
                if ret is not None:
                    break
                time.sleep(0.05)
            else:
                if self.proc.poll() is None:
                    self.timed_out = True
                    self.cancel(timeout=5.0)

        exit_code = self.proc.wait()

        if self._t_out is not None:
            self._t_out.join(timeout=5.0)
        if self._t_err is not None:
            self._t_err.join(timeout=5.0)

        duration = time.time() - self._start_monotonic
        self.ended_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return InvocationResult(
            exit_code=exit_code,
            timed_out=self.timed_out,
            cancelled=self.cancelled,
            pid=self.pid,
            pgid=self.pgid,
            start_time=self.start_time,
            ended_at=self.ended_at,
            duration_seconds=duration,
        )


def invoke_supervised(
    argv: list[str],
    cwd: pathlib.Path | str,
    *,
    prompt_text: str | None = None,
    prompt_via: str = "stdin",
    log_dir: pathlib.Path | str | None = None,
    stderr_path: pathlib.Path | str | None = None,
    max_chunk_size: int = DEFAULT_LOG_CHUNK_SIZE,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    on_started: Callable[[SupervisedInvocation], None] | None = None,
) -> InvocationResult:
    """Convenience helper to spawn and supervise a process until completion."""
    inv = SupervisedInvocation(
        argv=argv,
        cwd=cwd,
        prompt_text=prompt_text,
        prompt_via=prompt_via,
        log_dir=log_dir,
        stderr_path=stderr_path,
        max_chunk_size=max_chunk_size,
        timeout=timeout,
        env=env,
    )
    inv.start(on_started=on_started)
    return inv.wait()
