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
