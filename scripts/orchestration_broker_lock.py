#!/usr/bin/env python3
"""orchestration_broker_lock.py — Singleton broker lock and status helpers.

Provides on-disk singleton locking for the orchestration broker via `broker.lock`
and status discovery via `broker.json` and non-blocking flock probe.

Stdlib-only, cross-framework, POSIX flock based.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import threading
from typing import Any

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

_ACTIVE_HANDLES_LOCK = threading.Lock()
_ACTIVE_LOCK_PATHS: set[str] = set()


def get_global_config_dir(env_var: str = "AI_ORCHESTRATION_CONFIG") -> pathlib.Path:
    """Resolve global config directory.

    Precedence:
      1. `$AI_ORCHESTRATION_CONFIG` (if set; if points to a file ending in .toml, uses parent dir)
      2. `~/.config/ai-orchestration`
    """
    env_val = os.environ.get(env_var)
    if env_val:
        p = pathlib.Path(env_val).expanduser().resolve()
        if p.is_file() or p.suffix == ".toml" or p.name.endswith(".toml"):
            return p.parent
        return p
    return pathlib.Path.home() / ".config" / "ai-orchestration"


class BrokerLockHandle:
    """Handle holding an acquired exclusive lock on broker.lock."""

    def __init__(self, fd: int, lock_path: pathlib.Path):
        self.fd = fd
        self.lock_path = lock_path.resolve()
        self._released = False
        with _ACTIVE_HANDLES_LOCK:
            _ACTIVE_LOCK_PATHS.add(str(self.lock_path))

    @classmethod
    def is_held_locally(cls, lock_path: pathlib.Path) -> bool:
        with _ACTIVE_HANDLES_LOCK:
            return str(lock_path.resolve()) in _ACTIVE_LOCK_PATHS

    def release(self) -> None:
        if not self._released:
            self._released = True
            with _ACTIVE_HANDLES_LOCK:
                _ACTIVE_LOCK_PATHS.discard(str(self.lock_path))
            try:
                if fcntl is not None:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass

    def close(self) -> None:
        self.release()

    def __enter__(self) -> BrokerLockHandle:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


def acquire_broker_lock(
    config_dir: pathlib.Path | str | None = None,
) -> BrokerLockHandle | None:
    """Attempt non-blocking exclusive acquisition of `broker.lock`.

    Returns a `BrokerLockHandle` if acquired, or `None` if the lock is held
    by another process or cannot be acquired.
    """
    if fcntl is None:
        return None

    cdir = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    lock_file = cdir / "broker.lock"

    try:
        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        try:
            os.close(fd)
        except OSError:
            pass
        return None

    return BrokerLockHandle(fd, lock_file)


def is_pid_alive(pid: int | None) -> bool:
    """Check if process with given PID is alive without sending a signal."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False


class BrokerStatus(dict):
    """Dictionary representing broker status with attribute access."""

    @property
    def held(self) -> bool:
        return bool(self.get("held", False))

    @property
    def pid(self) -> int | None:
        v = self.get("pid")
        return int(v) if v is not None else None

    @property
    def pid_alive(self) -> bool:
        return bool(self.get("pid_alive", False))

    @property
    def live_pid(self) -> int | None:
        return self.pid if self.pid_alive else None

    @property
    def port(self) -> int | None:
        v = self.get("port")
        return int(v) if v is not None else None

    @property
    def started_at(self) -> str | None:
        v = self.get("started_at")
        return str(v) if v is not None else None

    @property
    def token_file(self) -> str | None:
        v = self.get("token_file")
        return str(v) if v is not None else None


def broker_status(
    config_dir: pathlib.Path | str | None = None,
) -> BrokerStatus:
    """Inspect broker status from `broker.json` and a non-blocking lock probe.

    Never makes HTTP calls. Returns a BrokerStatus dict:
      {"held": bool, "pid": int|None, "port": int|None, "started_at": str|None}
    """
    cdir = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    lock_file = cdir / "broker.lock"
    json_file = cdir / "broker.json"

    held = False
    if BrokerLockHandle.is_held_locally(lock_file):
        held = True
    elif lock_file.exists() and fcntl is not None:
        try:
            fd = os.open(str(lock_file), os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Acquired successfully -> NOT held by anyone else
                fcntl.flock(fd, fcntl.LOCK_UN)
                held = False
            except (BlockingIOError, OSError):
                held = True
            finally:
                os.close(fd)
        except OSError:
            # File might have been removed or permission denied
            held = False

    pid: int | None = None
    port: int | None = None
    started_at: str | None = None
    token_file: str | None = None

    manifest_exists = json_file.is_file()
    if manifest_exists:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw_pid = data.get("pid")
                raw_port = data.get("port")
                pid = int(raw_pid) if raw_pid is not None else None
                port = int(raw_port) if raw_port is not None else None
                started_at = str(data.get("started_at")) if data.get("started_at") else None
                token_file = str(data.get("token_file")) if data.get("token_file") else None
        except Exception:
            pass

    pid_alive = is_pid_alive(pid)

    if manifest_exists and pid is not None and not pid_alive:
        held = False

    return BrokerStatus({
        "held": held,
        "pid": pid,
        "pid_alive": pid_alive,
        "port": port,
        "started_at": started_at,
        "token_file": token_file,
    })


def write_broker_manifest(
    config_dir: pathlib.Path | str | None = None,
    pid: int | None = None,
    port: int | None = None,
    started_at: str | None = None,
    token_file: str | None = None,
) -> pathlib.Path:
    """Write broker.json readiness record atomically."""
    cdir = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    json_file = cdir / "broker.json"
    tmp_file = cdir / f"broker.json.tmp.{os.getpid()}"

    data: dict[str, Any] = {
        "pid": pid if pid is not None else os.getpid(),
        "port": port,
        "started_at": started_at,
    }
    if token_file is not None:
        data["token_file"] = str(token_file)
    tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(str(tmp_file), str(json_file))
    return json_file


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subcommand", nargs="?", default="status", choices=["status"], help="Subcommand (default: status)")
    ap.add_argument("--config-dir", default=None, help="Explicit config directory")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    st = broker_status(args.config_dir)
    if args.json:
        print(json.dumps(dict(st), indent=2))
    else:
        held_str = "held" if st.held else "not held"
        pid_str = f"pid={st.pid}" if st.pid else "no pid"
        port_str = f"port={st.port}" if st.port else "no port"
        print(f"Broker lock: {held_str} ({pid_str}, {port_str})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
