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


def test_b1_nested_directory_pytest_invocation_loads_root_conftest_and_isolates() -> None:
    """B1 regression: running pytest from a nested skill directory (`plugins/*/skills/*/scripts`)
    anchors rootdir at the repository root via `pytest.ini` and loads the root `conftest.py`
    autouse isolation fixture."""
    nested_dir = (
        conftest.REPO_ROOT
        / "plugins"
        / "shared"
        / "skills"
        / "orchestration-setup"
        / "scripts"
    )
    assert nested_dir.is_dir()
    assert (conftest.REPO_ROOT / "pytest.ini").is_file()

    # Pass a scrubbed environment where HOME points to REAL_HOME so only the root
    # conftest.py autouse fixture can redirect HOME and AI_ORCHESTRATION_CONFIG to tmp_path.
    env = os.environ.copy()
    env["HOME"] = str(conftest.REAL_HOME)
    env.pop("AI_ORCHESTRATION_CONFIG", None)
    env.pop("AI_ORCH_CONFIG_DIR", None)

    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-k",
            "test_autouse_fixture_isolates_env_vars_and_home",
            str(conftest.REPO_ROOT / "scripts" / "test_test_isolation.py"),
        ],
        cwd=str(nested_dir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"Nested pytest failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert f"rootdir: {conftest.REPO_ROOT}" in res.stdout
    assert "configfile: pytest.ini" in res.stdout
    assert "1 passed" in res.stdout


def test_b2_works_guard_tracks_only_orchestration_configs_and_excludes_only_repo_under_test(
    tmp_path: pathlib.Path,
) -> None:
    """B2 regression: `_snapshot_works_orchestration_configs` guards only the 5 orchestration
    config targets under `~/works` (`.ai-orchestration.local.toml`, `orchestration.toml`,
    `tasks/orchestration.toml`, `.ai-orchestration.toml`, `.ai-orchestration/`), ignores
    arbitrary non-config files in sibling projects, and `_resolve_excluded_repo_and_worktrees`
    excludes only the repository under test and its worktrees (never the parent workspace)."""
    excluded = conftest._resolve_excluded_repo_and_worktrees(conftest.REPO_ROOT)
    assert str(conftest.REPO_ROOT) in excluded
    # Parent workspace (e.g. ~/works/ai-coding-tools) must NEVER be in excluded
    parent_workspace = conftest.REAL_WORKS_DIR / "ai-coding-tools"
    assert str(parent_workspace.resolve()) not in excluded
    # Sibling repositories under ~/works/ai-coding-tools must NOT be excluded
    sibling_repo = parent_workspace / "ai-swissknife"
    assert not conftest._is_path_excluded(str(sibling_repo.resolve()), excluded)

    # Verify selective file guarding on a synthetic ~/works tree
    fake_works = tmp_path / "works"
    parent_ws = fake_works / "ai-coding-tools"
    repo_under_test = parent_ws / "ai-orchestration"
    repo_wt = parent_ws / ".worktrees" / "ai-orchestration" / "wt-1"
    sibling_proj = parent_ws / "sibling-project"
    other_proj = fake_works / "other-project"

    for d in (repo_under_test, repo_wt, sibling_proj, other_proj):
        (d / "tasks").mkdir(parents=True, exist_ok=True)
        (d / ".ai-orchestration").mkdir(parents=True, exist_ok=True)

    # Guarded files in sibling_proj and other_proj
    g_local = sibling_proj / ".ai-orchestration.local.toml"
    g_orch = sibling_proj / "orchestration.toml"
    g_tasks = sibling_proj / "tasks" / "orchestration.toml"
    g_dot = other_proj / ".ai-orchestration.toml"
    g_dir_file = other_proj / ".ai-orchestration" / "state.json"
    for gf in (g_local, g_orch, g_tasks, g_dot, g_dir_file):
        gf.write_text("guarded = true\n", encoding="utf-8")

    # Guarded-named files inside repo_under_test and its worktree (must be excluded)
    ex_orch = repo_under_test / "orchestration.toml"
    ex_wt_orch = repo_wt / ".ai-orchestration.local.toml"
    ex_orch.write_text("in_repo = true\n", encoding="utf-8")
    ex_wt_orch.write_text("in_wt = true\n", encoding="utf-8")

    # Non-guarded ordinary project files in sibling_proj and other_proj (must NOT be tracked)
    ordinary_src = sibling_proj / "main.py"
    ordinary_task = sibling_proj / "tasks" / "00-INDEX.md"
    ordinary_src.write_text("print('hi')\n", encoding="utf-8")
    ordinary_task.write_text("# Index\n", encoding="utf-8")

    fake_excluded = {
        str(repo_under_test.resolve()),
        str((parent_ws / ".worktrees" / "ai-orchestration").resolve()),
        str(repo_wt.resolve()),
    }
    snap = conftest._snapshot_works_orchestration_configs(
        fake_works, excluded_prefixes=fake_excluded
    )

    # All 5 guarded targets in sibling_proj / other_proj are tracked
    for gf in (g_local, g_orch, g_tasks, g_dot, g_dir_file, other_proj / ".ai-orchestration"):
        assert str(gf.resolve()) in snap, f"Expected guarded path {gf} in snapshot"

    # Repo under test and its worktree are excluded
    assert str(ex_orch.resolve()) not in snap
    assert str(ex_wt_orch.resolve()) not in snap
    assert str((repo_under_test / ".ai-orchestration").resolve()) not in snap

    # Ordinary files in sibling projects are ignored (no false failures from concurrent work)
    assert str(ordinary_src.resolve()) not in snap
    assert str(ordinary_task.resolve()) not in snap


def test_b3_reproduce_project_p_registration_and_fixture_creation_contained_under_isolated_home(
    tmp_path: pathlib.Path,
) -> None:
    """B3 regression: reproduces the exact project `p` write (`create_updated_project_fixture(tmp_path / 'p')`
    and `plan_workspace_register(tmp_path / 'p', title='p')` -> `apply_workspace_register`) that previously
    leaked `~/.config/ai-orchestration/projects/p/orchestration.toml` with `title = "p"`, and proves it stays
    strictly contained inside the per-test isolated `HOME` (`tmp_path / '_isolated_home'`)."""
    scripts_dir = conftest.REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import orchestration_registry as reg
    import test_orchestration_env as toe

    proj_p = tmp_path / "p"
    proj_p.mkdir(parents=True, exist_ok=True)

    # 1. Calling plan_workspace_register + apply_workspace_register WITHOUT explicit config_dir
    plan = reg.plan_workspace_register(proj_p, title="p")
    target_cfg = pathlib.Path(plan["workspace"]["config_path"]).resolve()
    isolated_home = (tmp_path / "_isolated_home").resolve()
    assert str(target_cfg).startswith(str(isolated_home) + os.sep)
    assert str(conftest.REAL_CONFIG_DIR) not in str(target_cfg)

    reg.apply_workspace_register(plan, expect_hash=plan["plan_hash"])
    assert target_cfg.is_file()
    content = target_cfg.read_text(encoding="utf-8")
    assert 'title = "p"' in content

    # 2. Calling create_updated_project_fixture(tmp_path / "p2") WITHOUT explicit home or global_config
    proj_p2 = tmp_path / "p2"
    toe.create_updated_project_fixture(proj_p2)
    isolated_projects_dir = isolated_home / ".config" / "ai-orchestration" / "projects"
    created_p2_configs = list(isolated_projects_dir.glob("p2*/orchestration.toml"))
    assert len(created_p2_configs) == 1
    assert 'name = "p2"' in created_p2_configs[0].read_text(encoding="utf-8")
    assert str(conftest.REAL_CONFIG_DIR) not in str(created_p2_configs[0].resolve())


def test_19_18_session_guard_ignores_live_broker_runtime_state_and_guards_configs_and_project_dirs(
    tmp_path: pathlib.Path,
) -> None:
    """Task 19.18 (3): `_snapshot_host_dir` ignores live broker runtime state (`*.sqlite`,
    `*-wal`, `*-shm`, `*.lock`, `broker/` sockets/pids, `broker.json`) while covering
    configuration files (`*.toml`, `*.json` configs) and new project directories."""
    cfg_root = tmp_path / "ai-orchestration"
    broker_dir = cfg_root / "broker"
    projects_dir = cfg_root / "projects" / "existing_proj"
    broker_dir.mkdir(parents=True)
    projects_dir.mkdir(parents=True)

    # Guarded config files
    global_toml = cfg_root / "orchestration.toml"
    proj_toml = projects_dir / "orchestration.toml"
    hub_reg_json = broker_dir / "hub_registry.json"
    global_toml.write_text("schema_version = 1\n", encoding="utf-8")
    proj_toml.write_text('[project]\nname = "existing_proj"\n', encoding="utf-8")
    hub_reg_json.write_text('{"projects": []}\n', encoding="utf-8")

    # Initial runtime state files
    (broker_dir / "registry.sqlite").write_bytes(b"sqlite-v1")
    (broker_dir / "registry.sqlite-wal").write_bytes(b"wal-v1")
    (broker_dir / "registry.sqlite-shm").write_bytes(b"shm-v1")
    (broker_dir / "registry.lock").write_text("", encoding="utf-8")
    (cfg_root / "broker.lock").write_text("", encoding="utf-8")
    (cfg_root / "broker.json").write_text('{"pid": 1234}\n', encoding="utf-8")

    before = conftest._snapshot_host_dir(cfg_root)

    # Simulate live Mac broker mutating SQLite WAL/SHM, locks, pids, sockets during test run
    (broker_dir / "registry.sqlite").write_bytes(b"sqlite-v2-modified")
    (broker_dir / "registry.sqlite-wal").write_bytes(b"wal-v2-modified-longer")
    (broker_dir / "registry.sqlite-shm").unlink()
    (broker_dir / "broker.pid").write_text("9999\n", encoding="utf-8")
    (broker_dir / "broker.sock").write_text("", encoding="utf-8")
    (cfg_root / "env.lock").write_text("", encoding="utf-8")
    (cfg_root / "broker.json").write_text('{"pid": 9999}\n', encoding="utf-8")

    after_runtime_only = conftest._snapshot_host_dir(cfg_root)
    assert after_runtime_only == before, "Live broker runtime state changes must not trigger session guard"

    # Now mutate a config file and create a new project directory -> must be detected
    hub_reg_json.write_text('{"projects": ["mutated"]}\n', encoding="utf-8")
    new_proj_dir = cfg_root / "projects" / "leaked_proj"
    new_proj_dir.mkdir(parents=True)

    after_config_leak = conftest._snapshot_host_dir(cfg_root)
    assert str(new_proj_dir.resolve()) not in before
    assert str(new_proj_dir.resolve()) in after_config_leak
    assert after_config_leak[str(hub_reg_json.resolve())] != before[str(hub_reg_json.resolve())]

