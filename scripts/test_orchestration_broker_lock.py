#!/usr/bin/env python3
"""test_orchestration_broker_lock.py — Tests for broker singleton locking and status."""
from __future__ import annotations

import json
import multiprocessing
import os
import pathlib
import sys
import time

import pytest

import orchestration_broker_lock as obl


def _holding_worker(cfg_dir: str, ready_evt: Any, stop_evt: Any) -> None:
    """Helper process that acquires the broker lock and holds it until stopped."""
    os.environ["AI_ORCHESTRATION_CONFIG"] = cfg_dir
    handle = obl.acquire_broker_lock(cfg_dir)
    assert handle is not None
    obl.write_broker_manifest(cfg_dir, pid=os.getpid(), port=8888, started_at="2026-10-18T12:00:00Z")
    ready_evt.set()
    stop_evt.wait(timeout=10)
    handle.release()


def test_get_global_config_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. No env var
    monkeypatch.delenv("AI_ORCHESTRATION_CONFIG", raising=False)
    default_dir = obl.get_global_config_dir()
    assert default_dir == pathlib.Path.home() / ".config" / "ai-orchestration"

    # 2. Env var pointing to directory
    custom_dir = tmp_path / "custom_config"
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(custom_dir))
    assert obl.get_global_config_dir() == custom_dir.resolve()

    # 3. Env var pointing to toml file
    toml_path = custom_dir / "orchestration.toml"
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(toml_path))
    assert obl.get_global_config_dir() == custom_dir.resolve()


def test_acquire_broker_lock_single_process(tmp_path: pathlib.Path) -> None:
    cfg = tmp_path / "broker_cfg"
    handle = obl.acquire_broker_lock(cfg)
    assert handle is not None

    # Status shows held
    st = obl.broker_status(cfg)
    assert st.held is True
    assert st["held"] is True

    # Release
    handle.release()
    st_after = obl.broker_status(cfg)
    assert st_after.held is False


def test_acquire_broker_lock_context_manager(tmp_path: pathlib.Path) -> None:
    cfg = tmp_path / "broker_cfg"
    with obl.acquire_broker_lock(cfg) as handle:
        assert handle is not None
        assert obl.broker_status(cfg).held is True

    assert obl.broker_status(cfg).held is False


def test_broker_status_with_helper_process(tmp_path: pathlib.Path) -> None:
    cfg = tmp_path / "broker_cfg"
    cfg.mkdir(parents=True, exist_ok=True)

    # Initial status: not held, no json
    st = obl.broker_status(cfg)
    assert st.held is False
    assert st.pid is None
    assert st.port is None
    assert st.started_at is None

    # Start helper process
    ready_evt = multiprocessing.Event()
    stop_evt = multiprocessing.Event()
    proc = multiprocessing.Process(
        target=_holding_worker,
        args=(str(cfg), ready_evt, stop_evt),
    )
    proc.start()

    try:
        assert ready_evt.wait(timeout=5)

        # Main process attempts acquisition: should fail
        attempt = obl.acquire_broker_lock(cfg)
        assert attempt is None

        # Inspect status
        st_held = obl.broker_status(cfg)
        assert st_held.held is True
        assert st_held.pid == proc.pid
        assert st_held.port == 8888
        assert st_held.started_at == "2026-10-18T12:00:00Z"
    finally:
        stop_evt.set()
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()

    # Once process ends, lock is released (even if broker.json remains)
    st_ended = obl.broker_status(cfg)
    assert st_ended.held is False
    assert st_ended.pid == proc.pid  # Json data preserved, but held is False
    assert st_ended.pid_alive is False
    assert st_ended.live_pid is None


def test_is_pid_alive() -> None:
    # 1. Current process is alive
    assert obl.is_pid_alive(os.getpid()) is True

    # 2. None, 0, or negative pid
    assert obl.is_pid_alive(None) is False
    assert obl.is_pid_alive(0) is False
    assert obl.is_pid_alive(-1) is False

    # 3. Dead process
    import subprocess
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = proc.pid
    proc.wait()
    assert obl.is_pid_alive(dead_pid) is False


def test_stale_manifest_with_inherited_lock_fd(tmp_path: pathlib.Path) -> None:
    """If broker.json has a dead pid, held MUST be False even if broker.lock is held."""
    cfg = tmp_path / "stale_cfg"
    cfg.mkdir(parents=True, exist_ok=True)

    # Acquire lock in current process (simulating an orphan child that inherited the lock fd)
    handle = obl.acquire_broker_lock(cfg)
    assert handle is not None

    # Spawn short-lived process to obtain a definitively dead PID
    import subprocess
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = proc.pid
    proc.wait()

    token_file = cfg / "ui-token"
    token_file.write_text("test-token-1234\n", encoding="utf-8")

    obl.write_broker_manifest(
        cfg,
        pid=dead_pid,
        port=7777,
        started_at="2026-10-18T10:00:00Z",
        token_file=str(token_file),
    )

    # Status check MUST report held=False because the broker pid in broker.json is dead
    st = obl.broker_status(cfg)
    assert st.held is False
    assert st.pid == dead_pid
    assert st.pid_alive is False
    assert st.live_pid is None
    assert st.port == 7777
    assert st.token_file == str(token_file)

    handle.release()
