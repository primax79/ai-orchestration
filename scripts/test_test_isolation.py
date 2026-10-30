#!/usr/bin/env python3
"""test_test_isolation.py — Tests verifying test environment isolation and session guard (T089)."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

import conftest


def test_autouse_fixture_isolates_env_vars_and_home(tmp_path: pathlib.Path) -> None:
    """Every test has HOME, AI_ORCHESTRATION_CONFIG, AI_ORCH_CONFIG_DIR, XDG_CONFIG_HOME,
    and KILO_MCP_DATA_DIR isolated under tmp_path."""
    home_dir = (tmp_path / "_isolated_home").resolve()
    assert pathlib.Path(os.environ["HOME"]).resolve() == home_dir
    assert pathlib.Path.home().resolve() == home_dir

    cfg_dir = home_dir / ".config" / "ai-orchestration"
    assert pathlib.Path(os.environ["AI_ORCHESTRATION_CONFIG"]).resolve() == cfg_dir
    assert pathlib.Path(os.environ["AI_ORCH_CONFIG_DIR"]).resolve() == cfg_dir
    assert pathlib.Path(os.environ["XDG_CONFIG_HOME"]).resolve() == home_dir / ".config"

    kilo_mcp_dir = home_dir / ".local" / "share" / "kilo-mcp"
    assert pathlib.Path(os.environ["KILO_MCP_DATA_DIR"]).resolve() == kilo_mcp_dir

    global_toml = cfg_dir / "orchestration.toml"
    assert global_toml.is_file()
    assert "[routing]" in global_toml.read_text(encoding="utf-8")


def test_subprocesses_inherit_isolated_home(tmp_path: pathlib.Path) -> None:
    """Subprocesses spawned without overriding env inherit the isolated HOME."""
    home_dir = (tmp_path / "_isolated_home").resolve()
    cmd = [
        sys.executable,
        "-c",
        "import os, pathlib; print(pathlib.Path.home().resolve()); print(os.environ.get('AI_ORCHESTRATION_CONFIG'))",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out_lines = res.stdout.strip().splitlines()
    assert len(out_lines) == 2
    assert out_lines[0] == str(home_dir)
    assert out_lines[1] == str(home_dir / ".config" / "ai-orchestration")


def test_default_global_config_path_fallback_stays_under_tmp_home(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When explicit config env vars are deleted, default_global_config_path() still
    falls back to Path.home() which resolves under tmp_path, never touching host."""
    setup_scripts = conftest.REPO_ROOT / "plugins" / "shared" / "skills" / "orchestration-setup" / "scripts"
    if str(setup_scripts) not in sys.path:
        sys.path.insert(0, str(setup_scripts))
    import orchestration_config as oc

    home_dir = (tmp_path / "_isolated_home").resolve()

    # 1. With AI_ORCHESTRATION_CONFIG set
    p1 = oc.default_global_config_path().resolve()
    assert p1 == home_dir / ".config" / "ai-orchestration" / "orchestration.toml"

    # 2. When AI_ORCHESTRATION_CONFIG is removed, AI_ORCH_CONFIG_DIR is used
    monkeypatch.delenv("AI_ORCHESTRATION_CONFIG", raising=False)
    p2 = oc.default_global_config_path().resolve()
    assert p2 == home_dir / ".config" / "ai-orchestration" / "orchestration.toml"

    # 3. When both config env vars are removed, Path.home() is used
    monkeypatch.delenv("AI_ORCH_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AI_ORCH_HOME", raising=False)
    p3 = oc.default_global_config_path().resolve()
    assert p3 == home_dir / ".config" / "ai-orchestration" / "orchestration.toml"
    assert str(conftest.REAL_HOME) not in str(p3)


def test_session_guard_snapshot_detects_mutations(tmp_path: pathlib.Path) -> None:
    """_snapshot_host_dir accurately identifies file creation, modification, and deletion."""
    mock_host = tmp_path / "mock_host"
    mock_host.mkdir()
    f1 = mock_host / "file1.txt"
    f1.write_text("hello", encoding="utf-8")

    snap_before = conftest._snapshot_host_dir(mock_host)
    assert str(f1.resolve()) in snap_before

    # Creation
    f2 = mock_host / "file2.txt"
    f2.write_text("world", encoding="utf-8")

    # Modification
    f1.write_text("hello modified content", encoding="utf-8")

    snap_after = conftest._snapshot_host_dir(mock_host)
    assert str(f2.resolve()) not in snap_before
    assert str(f2.resolve()) in snap_after
    assert snap_after[str(f1.resolve())] != snap_before[str(f1.resolve())]
