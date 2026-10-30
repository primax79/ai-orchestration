#!/usr/bin/env python3
"""test_orchestration_registry.py — Tests for workspace identity, explicit projects, nesting & registry."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import sys
import uuid
import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ORCH_CONFIG_DIR = (
    REPO_ROOT
    / "plugins"
    / "shared"
    / "skills"
    / "orchestration-setup"
    / "scripts"
)
if str(ORCH_CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_CONFIG_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import orchestration_registry as reg
import orchestration_config as oc

BIN_AI_ORCH = REPO_ROOT / "bin" / "ai-orch"


@pytest.fixture
def isolated_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Set up an isolated AI_ORCHESTRATION_CONFIG environment."""
    cfg_dir = tmp_path / "global_config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(cfg_dir))
    return cfg_dir


def test_workspace_register_plan_and_apply_hash_refusal(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    ws_dir = tmp_path / "my_workspace"
    ws_dir.mkdir()

    # 1. Preview plan
    plan = reg.plan_workspace_register(path=ws_dir, slug="test-ws", title="Test Workspace", config_dir=isolated_env)
    assert plan["action"] == "register"
    assert plan["workspace"]["slug"] == "test-ws"
    assert plan["workspace"]["title"] == "Test Workspace"
    assert plan["workspace"]["canonical_path"] == str(ws_dir.resolve())
    plan_hash = plan["plan_hash"]
    assert plan_hash is not None

    # Verify nothing written to DB or config yet
    db_path = reg.get_db_path(isolated_env)
    assert reg.list_workspaces(isolated_env) == []
    cfg_path = pathlib.Path(plan["workspace"]["config_path"])
    assert not cfg_path.exists()

    # 2. Refusal when expect_hash missing
    with pytest.raises(ValueError, match="--expect-hash is required"):
        reg.apply_workspace_register(plan, expect_hash=None, config_dir=isolated_env)

    # 3. Refusal when expect_hash mismatch
    with pytest.raises(ValueError, match="Hash mismatch"):
        reg.apply_workspace_register(plan, expect_hash="bad_hash_12345", config_dir=isolated_env)

    # 4. Successful apply with matching expect_hash
    res = reg.apply_workspace_register(plan, expect_hash=plan_hash, config_dir=isolated_env)
    assert res["ok"] is True
    assert res["applied"] is True
    assert res["plan_hash"] == plan_hash

    # Check config file was written
    assert cfg_path.exists()
    cfg = oc.load_toml_file(cfg_path)
    assert cfg["workspace"]["uuid"] == plan["workspace"]["uuid"]
    assert cfg["workspace"]["id"] == "test-ws"
    assert cfg["workspace"]["title"] == "Test Workspace"

    # Check SQLite DB
    workspaces = reg.list_workspaces(isolated_env)
    assert len(workspaces) == 1
    assert workspaces[0]["slug"] == "test-ws"
    assert workspaces[0]["stale"] is False

    # Check show_workspace
    shown = reg.show_workspace("test-ws", config_dir=isolated_env)
    assert shown["uuid"] == plan["workspace"]["uuid"]
    assert shown["stale"] is False


def test_workspace_move_detection(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    ws_dir1 = tmp_path / "workspace_loc1"
    ws_dir1.mkdir()

    plan1 = reg.plan_workspace_register(path=ws_dir1, slug="move-ws", config_dir=isolated_env)
    reg.apply_workspace_register(plan1, expect_hash=plan1["plan_hash"], config_dir=isolated_env)

    # Now simulate moving the directory or creating workspace 2 with same uuid in config
    ws_dir2 = tmp_path / "workspace_loc2"
    ws_dir2.mkdir()
    cfg_path2 = ws_dir2 / ".ai-orchestration.local.toml"
    cfg_path2.write_text(
        f'[workspace]\nuuid = "{plan1["workspace"]["uuid"]}"\nid = "move-ws"\n',
        encoding="utf-8",
    )

    # Preview registration at loc2
    plan2 = reg.plan_workspace_register(path=ws_dir2, slug="move-ws", config_dir=isolated_env)
    assert plan2["action"] == "move"
    assert plan2["moved_from"] == str(ws_dir1.resolve())
    assert f"moved from {ws_dir1.resolve()}" in plan2["message"]

    # Apply move
    res2 = reg.apply_workspace_register(plan2, expect_hash=plan2["plan_hash"], config_dir=isolated_env)
    assert res2["ok"] is True

    # Database now reflects new location
    shown = reg.show_workspace("move-ws", config_dir=isolated_env)
    assert shown["canonical_path"] == str(ws_dir2.resolve())


def test_workspace_symlink_refusal(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    # 1. Symlinked .ai-orchestration directory inside workspace
    ws_dir = tmp_path / "symlink_ws"
    ws_dir.mkdir()
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()

    dot_orch = ws_dir / ".ai-orchestration"
    dot_orch.symlink_to(target_dir)

    with pytest.raises(ValueError, match="symlinked .ai-orchestration directory"):
        reg.plan_workspace_register(path=ws_dir, config_dir=isolated_env)

    # Remove symlinked .ai-orchestration
    dot_orch.unlink()

    # 2. Symlinked component inside .ai-orchestration
    dot_orch.mkdir()
    inside_symlink = dot_orch / "events"
    inside_symlink.symlink_to(target_dir)

    with pytest.raises(ValueError, match="symlinked .ai-orchestration component detected"):
        reg.plan_workspace_register(path=ws_dir, config_dir=isolated_env)

    inside_symlink.unlink()

    # 3. Symlinked .ai-orchestration.local.toml
    target_file = tmp_path / "some_file.toml"
    target_file.write_text("[test]\n", encoding="utf-8")
    local_toml = ws_dir / ".ai-orchestration.local.toml"
    local_toml.symlink_to(target_file)

    with pytest.raises(ValueError, match="symlinked .ai-orchestration component detected"):
        reg.plan_workspace_register(path=ws_dir, config_dir=isolated_env)

    local_toml.unlink()

    # 4. Symlinked workspace directory itself
    symlink_ws_path = tmp_path / "ws_link"
    symlink_ws_path.symlink_to(ws_dir)

    with pytest.raises(ValueError, match="cannot be a symlink"):
        reg.plan_workspace_register(path=symlink_ws_path, config_dir=isolated_env)


def test_workspace_device_inode_recheck_refusal(isolated_env: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws_dir = tmp_path / "recheck_ws"
    ws_dir.mkdir()

    real_stat = os.stat
    call_count = 0

    def mock_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        nonlocal call_count
        call_count += 1
        st = real_stat(path, *args, **kwargs)
        if call_count > 1 and str(path) == str(ws_dir):
            # Return different inode to simulate mismatch
            return os.stat_result((st.st_mode, 999999999, st.st_dev, st.st_nlink, st.st_uid, st.st_gid, st.st_size, st.st_atime, st.st_mtime, st.st_ctime))
        return st

    monkeypatch.setattr(os, "stat", mock_stat)
    with pytest.raises(ValueError, match="Device/inode mismatch during re-check"):
        reg.check_device_inode(ws_dir)


def test_projects_discover_proposals_and_exclusions(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    ws_dir = tmp_path / "discover_ws"
    ws_dir.mkdir()

    # Initialize a git repo so git check-ignore works
    subprocess.run(["git", "init"], cwd=str(ws_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(ws_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(ws_dir), capture_output=True, check=True)

    # 1. Root project tasks/00-INDEX.md -> _workspace
    (ws_dir / "tasks").mkdir()
    (ws_dir / "tasks" / "00-INDEX.md").write_text("# Root tasks\n", encoding="utf-8")

    # 2. Eligible subproject packages/core/tasks/00-INDEX.md
    (ws_dir / "packages" / "core" / "tasks").mkdir(parents=True)
    (ws_dir / "packages" / "core" / "tasks" / "00-INDEX.md").write_text("# Core\n", encoding="utf-8")

    # 3. Excluded dirs: hidden folder (.hidden)
    (ws_dir / ".hidden" / "tasks").mkdir(parents=True)
    (ws_dir / ".hidden" / "tasks" / "00-INDEX.md").write_text("# Hidden\n", encoding="utf-8")

    # 4. Excluded dirs: node_modules, build, dist, target, venv, scratch, fixtures, references, .kilo/worktrees
    for exc in ("node_modules/mod1", "build", "dist", "target", "venv", "scratch", "fixtures", "references", ".kilo/worktrees/wt1"):
        p = ws_dir / exc / "tasks"
        p.mkdir(parents=True)
        (p / "00-INDEX.md").write_text("# Excluded\n", encoding="utf-8")

    # 5. Git-ignored folder
    gitignore = ws_dir / ".gitignore"
    gitignore.write_text("ignored_dir/\n", encoding="utf-8")
    (ws_dir / "ignored_dir" / "tasks").mkdir(parents=True)
    (ws_dir / "ignored_dir" / "tasks" / "00-INDEX.md").write_text("# Ignored\n", encoding="utf-8")

    # 6. Inner registered workspace
    inner_dir = ws_dir / "sub_repo"
    inner_dir.mkdir()
    (inner_dir / "tasks").mkdir()
    (inner_dir / "tasks" / "00-INDEX.md").write_text("# Inner\n", encoding="utf-8")

    plan_inner = reg.plan_workspace_register(path=inner_dir, slug="inner-ws", config_dir=isolated_env)
    reg.apply_workspace_register(plan_inner, expect_hash=plan_inner["plan_hash"], config_dir=isolated_env)

    # Register outer workspace
    plan_outer = reg.plan_workspace_register(path=ws_dir, slug="outer-ws", config_dir=isolated_env)
    reg.apply_workspace_register(plan_outer, expect_hash=plan_outer["plan_hash"], config_dir=isolated_env)

    # Now run projects discover on outer workspace
    disc_plan = reg.plan_projects_discover(workspace_arg="outer-ws", config_dir=isolated_env)
    proposed = disc_plan["proposed_projects"]
    sub_workspaces = disc_plan["sub_workspaces"]

    # Verify proposed projects: only root (_workspace) and core
    proposed_paths = [p["path"] for p in proposed]
    assert "." in proposed_paths
    assert "packages/core" in proposed_paths
    assert len(proposed) == 2

    proposed_ids = [p["id"] for p in proposed]
    assert "_workspace" in proposed_ids
    assert "core" in proposed_ids

    # Verify exclusions: none of the excluded dirs appear in proposed projects
    assert not any("hidden" in p for p in proposed_paths)
    assert not any("node_modules" in p for p in proposed_paths)
    assert not any("build" in p for p in proposed_paths)
    assert not any("dist" in p for p in proposed_paths)
    assert not any("target" in p for p in proposed_paths)
    assert not any("venv" in p for p in proposed_paths)
    assert not any("scratch" in p for p in proposed_paths)
    assert not any("fixtures" in p for p in proposed_paths)
    assert not any("references" in p for p in proposed_paths)
    assert not any(".kilo" in p for p in proposed_paths)
    assert not any("ignored_dir" in p for p in proposed_paths)
    assert not any("sub_repo" in p for p in proposed_paths)

    # Verify inner workspace listed in sub_workspaces
    assert len(sub_workspaces) == 1
    assert sub_workspaces[0]["slug"] == "inner-ws"
    assert sub_workspaces[0]["path"] == "sub_repo"

    # Apply discovery proposal
    disc_res = reg.apply_projects_discover(disc_plan, expect_hash=disc_plan["plan_hash"], config_dir=isolated_env)
    assert disc_res["ok"] is True

    # Check projects list
    plist = reg.list_projects(workspace_arg="outer-ws", config_dir=isolated_env)
    assert plist["ok"] is True
    items = plist["items"]

    kind_map = {it["path"]: it["kind"] for it in items}
    assert kind_map["."] == "_workspace"
    assert kind_map["packages/core"] == "project"
    assert kind_map["sub_repo"] == "sub_workspace"


def test_nesting_plan_and_restoration(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    outer_dir = tmp_path / "outer_project"
    outer_dir.mkdir()
    inner_dir = outer_dir / "nested_sub"
    inner_dir.mkdir()

    # Register outer workspace
    plan_out = reg.plan_workspace_register(path=outer_dir, slug="outer", config_dir=isolated_env)
    reg.apply_workspace_register(plan_out, expect_hash=plan_out["plan_hash"], config_dir=isolated_env)

    # Put a project in outer that lives inside inner's directory
    cfg_out_path = pathlib.Path(plan_out["workspace"]["config_path"])
    reg.write_workspace_to_config(
        cfg_out_path,
        plan_out["workspace"]["uuid"],
        "outer",
        projects=[
            {"uuid": str(uuid.uuid4()), "id": "_workspace", "path": "."},
            {"uuid": str(uuid.uuid4()), "id": "nested-mod", "path": "nested_sub/mod"},
        ],
    )
    # Sync outer projects to sqlite
    conn = reg.get_connection(reg.get_db_path(isolated_env))
    with conn:
        conn.execute("INSERT INTO projects (uuid, workspace_uuid, slug, rel_path) VALUES (?, ?, ?, ?)",
                     ("p-nested", plan_out["workspace"]["uuid"], "nested-mod", "nested_sub/mod"))
    conn.close()

    # Register inner workspace
    plan_in = reg.plan_workspace_register(path=inner_dir, slug="inner", config_dir=isolated_env)
    assert "outer_workspace" in plan_in
    assert plan_in["outer_workspace"]["slug"] == "outer"
    leaving = plan_in["projects_leaving"]
    assert len(leaving) == 1
    assert leaving[0]["slug"] == "nested-mod"

    reg.apply_workspace_register(plan_in, expect_hash=plan_in["plan_hash"], config_dir=isolated_env)

    # After registration, inner is registered and nested-mod left outer in SQLite
    conn = reg.get_connection(reg.get_db_path(isolated_env))
    outer_projs = conn.execute("SELECT slug FROM projects WHERE workspace_uuid = ?", (plan_out["workspace"]["uuid"],)).fetchall()
    assert [p["slug"] for p in outer_projs] == []  # Leaving project removed
    conn.close()

    # Outer's projects list shows inner as sub_workspace
    outer_list = reg.list_projects("outer", config_dir=isolated_env)
    assert any(it["slug"] == "inner" and it["kind"] == "sub_workspace" for it in outer_list["items"])

    # Now unregister inner workspace
    unreg_plan = reg.plan_workspace_unregister("inner", config_dir=isolated_env)
    assert "outer_workspace" in unreg_plan
    reg.apply_workspace_unregister(unreg_plan, expect_hash=unreg_plan["plan_hash"], config_dir=isolated_env)

    # Nested project restored to outer workspace!
    conn = reg.get_connection(reg.get_db_path(isolated_env))
    restored_projs = conn.execute("SELECT slug FROM projects WHERE workspace_uuid = ?", (plan_out["workspace"]["uuid"],)).fetchall()
    assert any(p["slug"] == "nested-mod" for p in restored_projs)
    conn.close()


def test_resolve_workspace_for_path_helper(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "tree_root"
    root.mkdir()
    outer_ws = root / "outer_ws"
    outer_ws.mkdir()
    inner_ws = outer_ws / "packages" / "inner_ws"
    inner_ws.mkdir(parents=True)

    # Register outer workspace with two projects: _workspace (.) and p1 (packages/p1)
    plan_o = reg.plan_workspace_register(path=outer_ws, slug="outer-ws", config_dir=isolated_env)
    reg.apply_workspace_register(plan_o, expect_hash=plan_o["plan_hash"], config_dir=isolated_env)

    conn = reg.get_connection(reg.get_db_path(isolated_env))
    with conn:
        conn.execute("INSERT INTO projects (uuid, workspace_uuid, slug, rel_path) VALUES (?, ?, ?, ?)",
                     ("u-root", plan_o["workspace"]["uuid"], "_workspace", "."))
        conn.execute("INSERT INTO projects (uuid, workspace_uuid, slug, rel_path) VALUES (?, ?, ?, ?)",
                     ("u-p1", plan_o["workspace"]["uuid"], "p1", "packages/p1"))
    conn.close()

    # Register inner workspace with project comp1 (components/comp1)
    plan_i = reg.plan_workspace_register(path=inner_ws, slug="inner-ws", config_dir=isolated_env)
    reg.apply_workspace_register(plan_i, expect_hash=plan_i["plan_hash"], config_dir=isolated_env)

    conn = reg.get_connection(reg.get_db_path(isolated_env))
    with conn:
        conn.execute("INSERT INTO projects (uuid, workspace_uuid, slug, rel_path) VALUES (?, ?, ?, ?)",
                     ("u-inner-root", plan_i["workspace"]["uuid"], "_workspace", "."))
        conn.execute("INSERT INTO projects (uuid, workspace_uuid, slug, rel_path) VALUES (?, ?, ?, ?)",
                     ("u-comp1", plan_i["workspace"]["uuid"], "comp1", "components/comp1"))
    conn.close()

    # 1. Path in outer root
    f_root = outer_ws / "tasks" / "00-INDEX.md"
    f_root.parent.mkdir(parents=True, exist_ok=True)
    f_root.write_text("tasks\n", encoding="utf-8")
    ws_res, proj_res = reg.resolve_workspace_for_path(f_root, config_dir=isolated_env)
    assert ws_res is not None and ws_res["slug"] == "outer-ws"
    assert proj_res is not None and proj_res["slug"] == "_workspace"

    # 2. Path in outer project p1
    f_p1 = outer_ws / "packages" / "p1" / "src" / "index.ts"
    f_p1.parent.mkdir(parents=True, exist_ok=True)
    f_p1.write_text("code\n", encoding="utf-8")
    ws_res, proj_res = reg.resolve_workspace_for_path(f_p1, config_dir=isolated_env)
    assert ws_res is not None and ws_res["slug"] == "outer-ws"
    assert proj_res is not None and proj_res["slug"] == "p1"

    # 3. Path in inner workspace: nearest registered workspace wins!
    f_inner = inner_ws / "components" / "comp1" / "app.py"
    f_inner.parent.mkdir(parents=True, exist_ok=True)
    f_inner.write_text("code\n", encoding="utf-8")
    ws_res, proj_res = reg.resolve_workspace_for_path(f_inner, config_dir=isolated_env)
    assert ws_res is not None and ws_res["slug"] == "inner-ws"
    assert proj_res is not None and proj_res["slug"] == "comp1"

    # 4. Path in inner workspace root
    f_inner_root = inner_ws / "tasks" / "00-INDEX.md"
    f_inner_root.parent.mkdir(parents=True, exist_ok=True)
    f_inner_root.write_text("tasks\n", encoding="utf-8")
    ws_res, proj_res = reg.resolve_workspace_for_path(f_inner_root, config_dir=isolated_env)
    assert ws_res is not None and ws_res["slug"] == "inner-ws"
    assert proj_res is not None and proj_res["slug"] == "_workspace"

    # 5. Path outside any workspace
    f_out = tmp_path / "unregistered" / "file.txt"
    f_out.parent.mkdir(parents=True, exist_ok=True)
    f_out.write_text("outside\n", encoding="utf-8")
    ws_res, proj_res = reg.resolve_workspace_for_path(f_out, config_dir=isolated_env)
    assert ws_res is None
    assert proj_res is None


def test_workspace_stale_flag_and_unregister(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    ws_dir = tmp_path / "temp_ws"
    ws_dir.mkdir()

    plan = reg.plan_workspace_register(path=ws_dir, slug="stale-ws", config_dir=isolated_env)
    reg.apply_workspace_register(plan, expect_hash=plan["plan_hash"], config_dir=isolated_env)

    ws_list = reg.list_workspaces(config_dir=isolated_env)
    assert len(ws_list) == 1
    assert ws_list[0]["stale"] is False

    # Corrupt config or remove directory
    os.rmdir(ws_dir)
    ws_list_after = reg.list_workspaces(config_dir=isolated_env)
    assert ws_list_after[0]["stale"] is True

    shown = reg.show_workspace("stale-ws", config_dir=isolated_env)
    assert shown["stale"] is True

    # Unregister workspace
    unreg_plan = reg.plan_workspace_unregister("stale-ws", config_dir=isolated_env)
    unreg_res = reg.apply_workspace_unregister(unreg_plan, expect_hash=unreg_plan["plan_hash"], config_dir=isolated_env)
    assert unreg_res["ok"] is True
    assert reg.list_workspaces(config_dir=isolated_env) == []


def test_cli_dispatch_through_bin_ai_orch(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    ws_dir = tmp_path / "cli_ws"
    ws_dir.mkdir()

    # 1. Plan registration via bin/ai-orch
    res_plan = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "workspace", "register", str(ws_dir), "--id", "cli-ws", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    plan_data = json.loads(res_plan.stdout)
    assert plan_data["workspace"]["slug"] == "cli-ws"
    h = plan_data["plan_hash"]

    # 2. Apply registration via bin/ai-orch
    res_apply = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "workspace", "register", str(ws_dir), "--id", "cli-ws", "--apply", "--expect-hash", h, "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    apply_data = json.loads(res_apply.stdout)
    assert apply_data["ok"] is True
    assert apply_data["applied"] is True

    # 3. List via bin/ai-orch
    res_list = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "workspace", "list", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    list_data = json.loads(res_list.stdout)
    assert any(w["slug"] == "cli-ws" for w in list_data["items"])

    # 4. Show via bin/ai-orch
    res_show = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "workspace", "show", "cli-ws", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    show_data = json.loads(res_show.stdout)
    assert show_data["workspace"]["slug"] == "cli-ws"

    # 5. Projects list via bin/ai-orch
    res_plist = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "projects", "list", "cli-ws", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    plist_data = json.loads(res_plist.stdout)
    assert plist_data["ok"] is True
    assert plist_data["workspace"] == "cli-ws"


def test_discover_finds_nested_repos_under_an_allowlist_gitignore(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """A workspace that groups nested repositories under an outer repo whose .gitignore is an allowlist
    (ignore everything, re-include a few files) must still find the nested repos' task trees."""
    ws = tmp_path / "umbrella"
    (ws / "tasks").mkdir(parents=True)
    (ws / "tasks" / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")
    (ws / ".gitignore").write_text("/*\n!.gitignore\n!tasks/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    sub = ws / "subproject"
    (sub / "tasks").mkdir(parents=True)
    (sub / "tasks" / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=sub, check=True)
    (sub / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    ignored = sub / "scratch" / "copy"
    (ignored / "tasks").mkdir(parents=True)
    (ignored / "tasks" / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    assert reg.is_git_ignored(sub, ws) is False
    assert reg.is_git_ignored(ignored, ws) is True


def test_projects_discover_unregistered_workspace(isolated_env: pathlib.Path, tmp_path: pathlib.Path) -> None:
    ws_dir = tmp_path / "unregistered_ws"
    ws_dir.mkdir(parents=True)

    # 1. Root tasks/00-INDEX.md and subproject tasks/00-INDEX.md
    (ws_dir / "tasks").mkdir(parents=True)
    (ws_dir / "tasks" / "00-INDEX.md").write_text("# Root\n", encoding="utf-8")

    (ws_dir / "service-a" / "tasks").mkdir(parents=True)
    (ws_dir / "service-a" / "tasks" / "00-INDEX.md").write_text("# Service A\n", encoding="utf-8")

    # Workspace is NOT registered in SQLite
    # 2. Run projects discover in preview mode via python API
    plan = reg.plan_projects_discover(str(ws_dir), config_dir=isolated_env)
    assert plan["ok"] is True
    assert plan["workspace_registered"] is False
    assert plan["workspace_path"] == str(ws_dir.resolve())
    disc = plan["discovered"]
    assert any(p["id"] == "_workspace" and p["path"] == "." for p in disc)
    assert any(p["id"] == "service-a" and p["path"] == "service-a" for p in disc)

    # 3. Run projects discover via CLI (bin/ai-orch)
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "projects", "discover", str(ws_dir), "--config-dir", str(isolated_env), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    cli_data = json.loads(res.stdout)
    assert cli_data["ok"] is True
    assert cli_data["workspace_registered"] is False
    assert cli_data["workspace_path"] == str(ws_dir.resolve())
    assert any(p["id"] == "_workspace" for p in cli_data["discovered"])
    assert any(p["id"] == "service-a" for p in cli_data["discovered"])

    # 4. Apply discovery on unregistered workspace (automatically registers workspace and projects)
    res_apply = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "projects", "discover", str(ws_dir), "--apply", "--config-dir", str(isolated_env), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_apply.returncode == 0
    apply_data = json.loads(res_apply.stdout)
    assert apply_data["ok"] is True
    assert apply_data["workspace_registered"] is True
    assert apply_data["applied"] is True

    # 5. Verify workspace is now registered in SQLite and projects discover reports registered=True
    res_again = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "projects", "discover", str(ws_dir), "--config-dir", str(isolated_env), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_again.returncode == 0
    again_data = json.loads(res_again.stdout)
    assert again_data["ok"] is True
    assert again_data["workspace_registered"] is True


def test_discovery_hygiene_git_ignored_nested_repo_symlinks_and_projects_ignore(
    isolated_env: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Verify T049 discovery hygiene:
    1. Only folders with tasks/00-INDEX.md are proposed (never bare tasks/ like Ansible roles or bare .git).
    2. Named git-ignored folders are skipped even when they contain their own .git repo (e.g. ansible-playbooks/, security_audit/).
    3. Symlinks (to folders or to tasks/) are never followed.
    4. .ai-orchestration/projects-ignore and [workspace.discovery] exclude by project name/slug and by folder subtree, with !negation.
    """
    ws_dir = tmp_path / "hygiene_ws"
    ws_dir.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(ws_dir), check=True)
    (ws_dir / ".gitignore").write_text("/ansible-playbooks/\nsecurity_audit/\n", encoding="utf-8")

    # Root task tree
    (ws_dir / "tasks").mkdir(parents=True)
    (ws_dir / "tasks" / "00-INDEX.md").write_text("# Root\n", encoding="utf-8")

    # Git-ignored nested repo with both Ansible role tasks/main.yml AND a real tasks/00-INDEX.md inside it
    ans_repo = ws_dir / "ansible-playbooks"
    ans_repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(ans_repo), check=True)
    (ans_repo / "roles" / "389ds_backup" / "tasks").mkdir(parents=True)
    (ans_repo / "roles" / "389ds_backup" / "tasks" / "main.yml").write_text("---\n", encoding="utf-8")
    (ans_repo / "nested-with-index" / "tasks").mkdir(parents=True)
    (ans_repo / "nested-with-index" / "tasks" / "00-INDEX.md").write_text("# Should be ignored\n", encoding="utf-8")

    # Non-ignored Ansible role folder (has tasks/main.yml, no 00-INDEX.md) and bare git submodule (no tasks/00-INDEX.md)
    (ws_dir / "infrastructure" / "roles" / "apache_conf" / "tasks").mkdir(parents=True)
    (ws_dir / "infrastructure" / "roles" / "apache_conf" / "tasks" / "main.yml").write_text("---\n", encoding="utf-8")
    bare_sub = ws_dir / "modules" / "bare-git-lib"
    bare_sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(bare_sub), check=True)

    # Symlink to an external project with tasks/00-INDEX.md
    ext_proj = tmp_path / "external_lib"
    (ext_proj / "tasks").mkdir(parents=True)
    (ext_proj / "tasks" / "00-INDEX.md").write_text("# External\n", encoding="utf-8")
    (ws_dir / "libs-jdk17").symlink_to(ext_proj)

    # Real subprojects under source_codes/ and modules/
    for rel in (
        "source_codes/legacy-a",
        "source_codes/legacy-b",
        "modules/portal-accept-invite-portlet",
        "modules/portal-messages-portlet",
        "modules/active-service",
    ):
        p = ws_dir / rel / "tasks"
        p.mkdir(parents=True)
        (p / "00-INDEX.md").write_text(f"# {rel}\n", encoding="utf-8")

    # Add .ai-orchestration/projects-ignore:
    # - ignore whole subtree `source_codes/`
    # - ignore by name/slug `portal-*-portlet`
    # - re-include `!portal-messages-portlet`
    ign_file = ws_dir / ".ai-orchestration" / "projects-ignore"
    ign_file.parent.mkdir(parents=True, exist_ok=True)
    ign_file.write_text(
        "# Ignore whole source_codes subtree\n"
        "source_codes/\n"
        "# Ignore portlets by slug glob, except messages\n"
        "portal-*-portlet\n"
        "!portal-messages-portlet\n",
        encoding="utf-8",
    )

    plan = reg.plan_projects_discover(str(ws_dir), config_dir=isolated_env)
    disc_ids = [p["id"] for p in plan["discovered"]]
    assert "_workspace" in disc_ids
    assert "active-service" in disc_ids
    assert "portal-messages-portlet" in disc_ids
    assert "portal-accept-invite-portlet" not in disc_ids
    assert "legacy-a" not in disc_ids
    assert "legacy-b" not in disc_ids
    assert "389ds-backup" not in disc_ids
    assert "nested-with-index" not in disc_ids
    assert "apache-conf" not in disc_ids
    assert "bare-git-lib" not in disc_ids
    assert "libs-jdk17" not in disc_ids
    assert "external-lib" not in disc_ids
    assert set(disc_ids) == {"_workspace", "active-service", "portal-messages-portlet"}


def test_19_1_discovery_filter_all_canonical_and_legacy_config_locations_and_shadowing(
    isolated_env: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    """19.1 (B2 & B3): Workspace discovery reads `[workspace.discovery]` from every canonical
    and legacy project config location, and higher-precedence config shadows lower-precedence files."""
    positions = [
        ("local_dot", lambda ws: ws / ".ai-orchestration.local.toml"),
        ("external_projects", lambda ws: isolated_env / "projects" / ws.name / "orchestration.toml"),
        ("legacy_root", lambda ws: ws / "orchestration.toml"),
        ("legacy_dot_dir", lambda ws: ws / ".ai-orchestration" / "orchestration.toml"),
        ("legacy_tasks_dir", lambda ws: ws / "tasks" / "orchestration.toml"),
        ("legacy_dot_toml", lambda ws: ws / ".ai-orchestration.toml"),
    ]

    for pos_name, path_fn in positions:
        ws_dir = tmp_path / f"ws_{pos_name}"
        (ws_dir / "tasks").mkdir(parents=True)
        (ws_dir / "tasks" / "00-INDEX.md").write_text("# Root\n", encoding="utf-8")
        for sub in ("packages/keep-me", "packages/drop-me"):
            (ws_dir / sub / "tasks").mkdir(parents=True)
            (ws_dir / sub / "tasks" / "00-INDEX.md").write_text("# Sub\n", encoding="utf-8")

        cfg_file = path_fn(ws_dir)
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(
            '[workspace.discovery]\n'
            'include = ["packages/*"]\n'
            'exclude = ["packages/drop-me"]\n',
            encoding="utf-8",
        )

        plan = reg.plan_projects_discover(str(ws_dir), config_dir=isolated_env)
        disc_paths = [p["path"] for p in plan["discovered"]]
        assert "." in disc_paths, pos_name
        assert "packages/keep-me" in disc_paths, pos_name
        assert "packages/drop-me" not in disc_paths, pos_name

        # If a higher-precedence `.ai-orchestration.local.toml` is added that drops `keep-me` and keeps `drop-me`,
        # the lower-precedence file is shadowed and does not leak its exclude rule.
        if pos_name != "local_dot":
            (ws_dir / ".ai-orchestration.local.toml").write_text(
                '[workspace.discovery]\n'
                'include = ["packages/*"]\n'
                'exclude = ["packages/keep-me"]\n',
                encoding="utf-8",
            )
            plan2 = reg.plan_projects_discover(str(ws_dir), config_dir=isolated_env)
            disc_paths2 = [p["path"] for p in plan2["discovered"]]
            assert "packages/drop-me" in disc_paths2, pos_name
            assert "packages/keep-me" not in disc_paths2, pos_name


def _render_templated_migration_fixture(
    tmp_path: pathlib.Path,
    dest_name: str = "MIGRATION_REGISTRY.copy.json",
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    """Render `scripts/fixtures/migration_registry.json` with all roots under `tmp_path`."""
    fixture_src = SCRIPT_DIR / "fixtures" / "migration_registry.json"
    assert fixture_src.is_file()
    raw_tpl = fixture_src.read_text(encoding="utf-8")
    assert "/Users/Alfredo/works" not in raw_tpl
    assert "/home/alfredo/works" not in raw_tpl

    mac_root = tmp_path / "mac_works"
    hub_root = tmp_path / "hub_works"
    repos_root = tmp_path / "hub_git"
    mac_root.mkdir(parents=True, exist_ok=True)
    hub_root.mkdir(parents=True, exist_ok=True)
    repos_root.mkdir(parents=True, exist_ok=True)

    rendered = (
        raw_tpl.replace("{{MAC_ROOT}}", str(mac_root))
        .replace("{{HUB_ROOT}}", str(hub_root))
        .replace("{{REPOS_ROOT}}", str(repos_root))
    )
    mig_copy = tmp_path / dest_name
    mig_copy.write_text(rendered, encoding="utf-8")
    return mig_copy, mac_root, hub_root, repos_root


def test_19_16_b1_templated_fixture_isolation_and_root_guard(
    tmp_path: pathlib.Path,
) -> None:
    """19.16 (B1):
    1. `scripts/fixtures/migration_registry.json` uses templated placeholders (`{{MAC_ROOT}}`, `{{HUB_ROOT}}`, `{{REPOS_ROOT}}`), never real `~/works` paths.
    2. When checkout directories exist under `tmp_path`, applying the import writes workspace configuration strictly inside `tmp_path`.
    3. Any path outside configured roots (`hosts.<h>.root` / `allowed_roots`) is refused with a clear `ValueError`."""
    mig_copy, mac_root, hub_root, _ = _render_templated_migration_fixture(tmp_path)
    # Create actual checkout directories under `hub_root` and `mac_root` inside `tmp_path`
    for proj_dir in ("ricerca_auto", "ai-coding-tools", "d4science_kb"):
        (hub_root / proj_dir / "tasks").mkdir(parents=True, exist_ok=True)
        (mac_root / proj_dir / "tasks").mkdir(parents=True, exist_ok=True)

    hub_cfg_dir = tmp_path / "hub_cfg"
    hub_cfg_dir.mkdir(parents=True)

    plan = reg.plan_import_migration_registry(mig_copy, config_dir=hub_cfg_dir, host="alf_ubuntu")
    res = reg.apply_import_migration_registry(plan, expect_hash=plan["plan_hash"], config_dir=hub_cfg_dir)
    assert res["ok"] is True and res["applied"] is True

    # Verify all written files (configs, SQLite DB, hub_registry.json) reside strictly under tmp_path
    tmp_resolved = tmp_path.resolve()
    for p in res["projects"]:
        for hk, hp in p["paths"].items():
            rp = pathlib.Path(hp).resolve()
            assert tmp_resolved in rp.parents, f"Path {rp} for {p['slug']}@{hk} escaped tmp_path"
    for root_dir, _, files in os.walk(str(hub_cfg_dir)):
        for fn in files:
            fpath = (pathlib.Path(root_dir) / fn).resolve()
            assert tmp_resolved in fpath.parents

    # Guard check 1: unexpanded template placeholder in migration file is refused
    raw_unexpanded = tmp_path / "unexpanded.json"
    raw_unexpanded.write_text((SCRIPT_DIR / "fixtures" / "migration_registry.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpanded template placeholder"):
        reg.plan_import_migration_registry(raw_unexpanded, config_dir=hub_cfg_dir, host="alf_ubuntu")

    # Guard check 2: path outside configured `hosts.<h>.root` is refused at preview AND apply
    escaped_json = tmp_path / "escaped.json"
    outside_dir = pathlib.Path("/var/tmp/outside_allowed_roots_test_19_16")
    escaped_payload = {
        "schema_version": 1,
        "hosts": {
            "alf_ubuntu": {"root": str(hub_root)},
            "mac": {"root": str(mac_root)},
        },
        "projects": [
            {
                "id": "rogue-proj",
                "paths": {
                    "alf_ubuntu": str(outside_dir / "rogue"),
                },
            }
        ],
    }
    escaped_json.write_text(json.dumps(escaped_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="outside configured roots"):
        reg.plan_import_migration_registry(escaped_json, config_dir=hub_cfg_dir, host="alf_ubuntu")

    # Also test apply-time guard if a plan payload is tampered with an outside path
    mig_copy2, _, _, _ = _render_templated_migration_fixture(tmp_path, dest_name="MIGRATION_REGISTRY.copy2.json")
    plan2 = reg.plan_import_migration_registry(mig_copy2, config_dir=hub_cfg_dir, host="alf_ubuntu")
    tampered_plan = copy.deepcopy(plan2)
    tampered_plan["projects"][0]["paths"]["alf_ubuntu"] = str(outside_dir / "ricerca_auto")
    tampered_plan["plan_hash"] = reg.compute_plan_hash(tampered_plan)
    with pytest.raises(ValueError, match="outside configured roots"):
        reg.apply_import_migration_registry(
            tampered_plan,
            expect_hash=tampered_plan["plan_hash"],
            config_dir=hub_cfg_dir,
        )


def test_19_16_import_migration_registry_on_copy_and_same_uuid_across_hosts(
    tmp_path: pathlib.Path,
) -> None:
    """19.16 (B1 & B2): Import a copy of `MIGRATION_REGISTRY.json`; verify explicit UUID preservation,
    random UUID allocation + persistence for entries without an explicit UUID, per-host paths,
    primary host, reference_repo, mirror, and convention_version on both Mac and hub."""
    mig_copy, mac_root, hub_root, _ = _render_templated_migration_fixture(tmp_path)

    hub_cfg_dir = tmp_path / "hub_cfg"
    mac_cfg_dir = tmp_path / "mac_cfg"
    hub_cfg_dir.mkdir(parents=True)
    mac_cfg_dir.mkdir(parents=True)

    # 1. Preview import on authoritative hub (`alf_ubuntu`)
    plan_hub = reg.plan_import_migration_registry(mig_copy, config_dir=hub_cfg_dir, host="alf_ubuntu")

    assert plan_hub["ok"] is True
    assert plan_hub["imported_count"] == 3
    assert not reg.get_hub_registry_path(hub_cfg_dir).exists()

    # Refusal if --expect-hash is missing or mismatched
    with pytest.raises(ValueError, match="--expect-hash is required"):
        reg.apply_import_migration_registry(plan_hub, expect_hash=None, config_dir=hub_cfg_dir)
    with pytest.raises(ValueError, match="Hash mismatch"):
        reg.apply_import_migration_registry(plan_hub, expect_hash="bad_hash", config_dir=hub_cfg_dir)

    # Refusal if the migration file content changes between preview and apply
    mig_tampered, _, _, _ = _render_templated_migration_fixture(tmp_path, dest_name="MIGRATION_REGISTRY.tampered.json")
    plan_tamper = reg.plan_import_migration_registry(mig_tampered, config_dir=hub_cfg_dir, host="alf_ubuntu")
    mig_tampered.write_text(mig_tampered.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed between preview and apply"):
        reg.apply_import_migration_registry(plan_tamper, expect_hash=plan_tamper["plan_hash"], config_dir=hub_cfg_dir)

    # 2. Apply import on hub (persists newly generated random UUIDs into `mig_copy`), then import on Mac
    res_hub = reg.apply_import_migration_registry(plan_hub, expect_hash=plan_hub["plan_hash"], config_dir=hub_cfg_dir)
    assert res_hub["ok"] is True and res_hub["applied"] is True

    # Verify `mig_copy` now has explicit UUIDs persisted for all 3 projects
    persisted_mig = json.loads(mig_copy.read_text(encoding="utf-8"))
    for p_item in persisted_mig["projects"]:
        assert reg.is_valid_uuid4(p_item.get("uuid"))
    ai_tools_item = next(p for p in persisted_mig["projects"] if p.get("id") == "ai-coding-tools")
    assert ai_tools_item["uuid"] == "52c62ed7-47c6-45e0-8136-6aa92350e4de"

    plan_mac = reg.plan_import_migration_registry(mig_copy, config_dir=mac_cfg_dir, host="mac")
    res_mac = reg.apply_import_migration_registry(plan_mac, expect_hash=plan_mac["plan_hash"], config_dir=mac_cfg_dir)
    assert res_mac["ok"] is True and res_mac["applied"] is True

    # 3. Verify identical UUIDs and metadata on both hosts
    hub_list = {w["slug"]: w for w in reg.list_workspaces(hub_cfg_dir)}
    mac_list = {w["slug"]: w for w in reg.list_workspaces(mac_cfg_dir)}
    assert set(hub_list.keys()) == {"ai-coding-tools", "d4science-kb", "ricerca-auto"}
    assert set(mac_list.keys()) == {"ai-coding-tools", "d4science-kb", "ricerca-auto"}

    for slug in ("ai-coding-tools", "d4science-kb", "ricerca-auto"):
        assert hub_list[slug]["uuid"] == mac_list[slug]["uuid"], slug
        assert hub_list[slug]["primary_host"] == mac_list[slug]["primary_host"], slug
        assert hub_list[slug]["reference_repo"] == mac_list[slug]["reference_repo"], slug
        assert hub_list[slug]["mirror_repo"] == mac_list[slug]["mirror_repo"], slug
        assert hub_list[slug]["convention_version"] == "1.1.0", slug
        assert hub_list[slug]["paths"]["mac"].startswith(str(mac_root))
        assert hub_list[slug]["paths"]["alf_ubuntu"].startswith(str(hub_root))


def test_19_16_b2_random_uuid_allocation_and_no_slug_identity_collision(
    tmp_path: pathlib.Path,
) -> None:
    """19.16 (B2):
    1. Workspace UUIDs are randomly allocated on the authoritative hub, never a hash of the display slug.
    2. Two unrelated workspaces with the same name/slug on different isolated hubs get distinct random UUIDs.
    3. `upsert_hub_project_entry()` keys by UUID and refuses to merge two different UUIDs that share a display slug.
    4. Distributing the hub's allocated UUID to another host (via `hub_registry.json` snapshot or `[workspace] uuid`)
       preserves the exact same UUID across Mac and hub."""
    cfg_a = tmp_path / "cfg_a"
    cfg_b = tmp_path / "cfg_b"
    cfg_a.mkdir()
    cfg_b.mkdir()

    ws_a = tmp_path / "host_a" / "same_name"
    ws_b = tmp_path / "host_b" / "same_name"
    ws_a.mkdir(parents=True)
    ws_b.mkdir(parents=True)

    # Two unrelated workspaces with the same slug `same-name` allocate distinct random UUIDs
    plan_a = reg.plan_workspace_register(ws_a, slug="same-name", config_dir=cfg_a, host="alf_ubuntu")
    plan_b = reg.plan_workspace_register(ws_b, slug="same-name", config_dir=cfg_b, host="mac")
    uuid_a = plan_a["workspace"]["uuid"]
    uuid_b = plan_b["workspace"]["uuid"]
    assert reg.is_valid_uuid4(uuid_a)
    assert reg.is_valid_uuid4(uuid_b)
    assert uuid_a != uuid_b

    reg.apply_workspace_register(plan_a, expect_hash=plan_a["plan_hash"], config_dir=cfg_a)

    # Attempting to upsert a second project with a different UUID but the same slug in the same hub registry is refused
    with pytest.raises(ValueError, match="already registered in hub registry to UUID"):
        reg.upsert_hub_project_entry(
            cfg_a,
            ws_uuid=uuid_b,
            ws_slug="same-name",
            host_id="mac",
            host_path=str(ws_b),
        )

    # Distributing the hub's entry (`uuid_a`) to Mac and registering the Mac checkout preserves `uuid_a`
    cfg_mac = tmp_path / "cfg_mac"
    cfg_mac.mkdir()
    hub_doc_a = reg.load_hub_registry(cfg_a)
    reg.replace_hub_snapshot_cache(cfg_mac, hub_doc_a["projects"], host_id="mac")

    mac_checkout = tmp_path / "mac_checkouts" / "same_name"
    (mac_checkout / "tasks").mkdir(parents=True)
    (mac_checkout / "tasks" / "convention_version").write_text("1.1.0\n", encoding="utf-8")
    plan_mac_join = reg.plan_workspace_register(
        mac_checkout,
        slug="same-name",
        config_dir=cfg_mac,
        host="mac",
    )
    assert plan_mac_join["workspace"]["uuid"] == uuid_a


def test_19_16_console_status_lists_hub_projects_prunes_deleted_and_falls_back_offline(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """19.16 (B3):
    1. `ai-orch console status` lists projects from the hub registry when reachable and caches the versioned snapshot.
    2. When a project is unregistered/deleted on the hub, the next online sync atomically prunes the removed
       hub-sourced row from the client's local cache (`hub_registry.json` and `registry.sqlite`).
    3. When the hub becomes unreachable, `console status` and `workspace list` fall back to the last cached snapshot."""
    hub_cfg_dir = tmp_path / "hub_config"
    client_cfg_dir = tmp_path / "client_config"
    hub_cfg_dir.mkdir(parents=True)
    client_cfg_dir.mkdir(parents=True)

    # Seed hub registry from templated fixture copy
    mig_copy, _, _, _ = _render_templated_migration_fixture(tmp_path)
    plan_hub = reg.plan_import_migration_registry(mig_copy, config_dir=hub_cfg_dir, host="alf_ubuntu")
    reg.apply_import_migration_registry(plan_hub, expect_hash=plan_hub["plan_hash"], config_dir=hub_cfg_dir)

    # Configure client (`mac`) with `alf_ubuntu` as `role = "hub"`
    (client_cfg_dir / "orchestration.toml").write_text(
        '[host]\nid = "mac"\nrole = "client"\n\n'
        '[hosts.alf_ubuntu]\nssh_target = "alf_ubuntu"\nrole = "hub"\nagent_user = "kilo"\n',
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"

    # 1. Fake ssh succeeds and returns hub's `ai-orch workspace list --json` (3 projects)
    hub_list_res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "workspace", "list", "--config-dir", str(hub_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    hub_json_file = tmp_path / "hub_workspace_list.json"
    hub_json_file.write_text(hub_list_res.stdout, encoding="utf-8")

    fake_ssh.write_text(
        f"#!/bin/sh\ncat '{hub_json_file}'\nexit 0\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(client_cfg_dir))

    res_online = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "status", "--config-dir", str(client_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    online_data = json.loads(res_online.stdout)
    assert online_data["ok"] is True
    assert online_data["host"] == "mac"
    assert online_data["hub_host"] == "alf_ubuntu"
    assert online_data["hub_reachable"] is True
    assert online_data["registry_source"] == "hub"
    assert online_data["snapshot_version"] >= 1
    online_slugs = {p["slug"] for p in online_data["projects"]}
    assert online_slugs == {"ai-coding-tools", "d4science-kb", "ricerca-auto"}

    # 2. Delete `d4science-kb` on the hub, then refresh `console status` on the client -> pruned atomically (B3)
    unreg_plan = reg.plan_workspace_unregister("d4science-kb", config_dir=hub_cfg_dir)
    reg.apply_workspace_unregister(unreg_plan, expect_hash=unreg_plan["plan_hash"], config_dir=hub_cfg_dir)

    hub_list_res2 = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "workspace", "list", "--config-dir", str(hub_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    hub_json_file.write_text(hub_list_res2.stdout, encoding="utf-8")

    res_online2 = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "status", "--config-dir", str(client_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    online_data2 = json.loads(res_online2.stdout)
    assert online_data2["ok"] is True
    assert online_data2["hub_reachable"] is True
    assert online_data2["registry_source"] == "hub"
    assert {p["slug"] for p in online_data2["projects"]} == {"ai-coding-tools", "ricerca-auto"}
    assert {w["slug"] for w in reg.list_workspaces(client_cfg_dir)} == {"ai-coding-tools", "ricerca-auto"}

    # 3. Simulate hub unreachable (fake ssh exits 255) -> local SQLite cache remains usable with the pruned snapshot
    fake_ssh.write_text(
        "#!/bin/sh\necho 'ssh: connect to host alf_ubuntu port 22: Operation timed out' >&2\nexit 255\n",
        encoding="utf-8",
    )
    res_offline = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "status", "--all-hosts", "--config-dir", str(client_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    offline_data = json.loads(res_offline.stdout)
    assert offline_data["ok"] is True
    assert offline_data["hub_reachable"] is False
    assert offline_data["registry_source"] == "local_cache"
    assert offline_data["hosts"]["alf_ubuntu"]["reachable"] is False
    assert offline_data["hosts"]["mac"]["reachable"] is True
    offline_slugs = {p["slug"] for p in offline_data["projects"]}
    assert offline_slugs == {"ai-coding-tools", "ricerca-auto"}

    # Direct `workspace list` on client also works offline from local cache
    ws_offline = reg.list_workspaces(client_cfg_dir)
    assert {w["slug"] for w in ws_offline} == {"ai-coding-tools", "ricerca-auto"}


def _seed_project_with_tasks_questions_and_runs(
    proj_dir: pathlib.Path,
    *,
    proj_slug: str,
    host_id: str,
    tasks_spec: list[dict[str, Any]],
    questions_spec: list[dict[str, Any]],
    runs_spec: list[dict[str, Any]],
) -> None:
    """Create a realistic project tree with emergent tasks, questions, and `.ai-orchestration/runs/` records."""
    tasks_dir = proj_dir / "tasks"
    (tasks_dir / "core").mkdir(parents=True, exist_ok=True)
    (tasks_dir / "questions").mkdir(parents=True, exist_ok=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    for t in tasks_spec:
        tid = t["id"]
        title = t.get("title", f"Task {tid}")
        state = t.get("state", "open")
        thost = t.get("host", "-")
        vby = t.get("verify_by", "-")
        run_id = t.get("run_id", "-")
        t_file = tasks_dir / "core" / f"{tid}-task.md"
        opt_lines = []
        if vby != "-":
            opt_lines.append(f"- verify-by: {vby}")
        if run_id != "-":
            opt_lines.append(f"- run-id: {run_id}")
        if thost != "-":
            opt_lines.append(f"- host: {thost}")
        opt_block = ("\n".join(opt_lines) + "\n") if opt_lines else ""
        t_file.write_text(
            f"# {tid} {title}\n\n"
            f"- id: {tid}\n"
            f"- title: {title}\n"
            f"- category: core\n"
            f"- priority: {t.get('priority', 'P1')}\n"
            f"- priority-reason: core work\n"
            f"- next-up: yes\n"
            f"- state: {state}\n"
            f"- executor: {t.get('executor', 'kilo')}\n"
            f"- depends-on: -\n"
            f"- decider: owner\n"
            f"- sources: -\n"
            f"- paths: src/\n"
            f"- handoff: -\n"
            f"{opt_block}\n"
            f"## Goal\n{title}\n\n"
            f"## Steps\n- [ ] step 1\n\n"
            f"## Verification\n- pytest\n",
            encoding="utf-8",
        )

    for q in questions_spec:
        qid = q["id"]
        q_status = q.get("status", "open")
        q_title = q.get("question", f"Question {qid}?")
        q_blocks = q.get("blocks", "T001")
        q_file = tasks_dir / "questions" / f"{qid}-question.md"
        q_file.write_text(
            f"# {qid} - {q_title}\n\n"
            f"- id: {qid}\n"
            f"- status: {q_status}\n"
            f"- asked: 2026-10-30\n"
            f"- asked-by: kilo\n"
            f"- decider: owner\n"
            f"- blocks: {q_blocks}\n"
            f"- recommended: A\n"
            f"- open-answer: yes\n"
            f"- answered: {'2026-10-30' if q_status == 'answered' else '-'}\n"
            f"- answered-by: {'owner' if q_status == 'answered' else '-'}\n"
            f"- choice: {'A' if q_status == 'answered' else '-'}\n"
            f"- applied: no\n\n"
            f"## Question\n\n{q_title}\n\n"
            f"## Context\n\nContext for {qid}.\n\n"
            f"## Options\n\n### A — Option A\nDesc A.\n\n"
            f"## Answer\n\n{'A' if q_status == 'answered' else ''}\n",
            encoding="utf-8",
        )

    runs_root = proj_dir / ".ai-orchestration" / "runs"
    for r in runs_spec:
        rid = r["run_id"]
        r_dir = runs_root / rid
        r_dir.mkdir(parents=True, exist_ok=True)
        r_payload = {
            "run_id": rid,
            "task_id": r["task_id"],
            "mode": r.get("mode", "execute"),
            "tool": r.get("tool", "kilo"),
            "status": r.get("status", "running"),
            "state": r.get("state", r.get("status", "running")),
            "host": r.get("host", host_id),
            "backend": r.get("backend", "screen"),
            "screen_session": r.get("screen_session", f"agent-{proj_slug}-{r['task_id']}"),
            "session_name": r.get("screen_session", f"agent-{proj_slug}-{r['task_id']}"),
            "started_at": r.get("started_at", "2026-10-30T11:00:00+00:00"),
            "ended_at": r.get("ended_at"),
            "last_heartbeat": r.get("last_heartbeat", "2026-10-30T11:55:00+00:00"),
            "workspace": str(proj_dir),
            "cwd": str(proj_dir),
        }
        (r_dir / "run.json").write_text(json.dumps(r_payload, indent=2), encoding="utf-8")


def test_19_8_console_status_multi_host_aggregation_with_one_host_down_and_timeout(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 19.8 Verification:
    - `ai-orch console status [--all-hosts] [--json]` executes `ssh <host> ai-orch ... --json` (no daemon)
      for each declared host.
    - Simulates two remote hosts (`alf_ubuntu` up, `lab_worker` down) plus local `mac`.
    - Aggregates projects, tasks by state and host, runs (with host, task, state, age, last_heartbeat),
      open questions, and deliveries to verify.
    - Unreachable host (`lab_worker`) is shown as unreachable without blocking the others; honours per-host timeout.
    """
    hub_cfg_dir = tmp_path / "hub_cfg"
    client_cfg_dir = tmp_path / "client_cfg"
    hub_cfg_dir.mkdir(parents=True)
    client_cfg_dir.mkdir(parents=True)

    hub_ws = tmp_path / "hub_works" / "ricerca_auto"
    mac_ws = tmp_path / "mac_works" / "local_app"
    hub_ws.mkdir(parents=True)
    mac_ws.mkdir(parents=True)

    run_hub_id = "20261030-110000-T001-kilo-a1b2"
    run_mac_id = "20261030-113000-T010-kilo-c3d4"

    _seed_project_with_tasks_questions_and_runs(
        hub_ws,
        proj_slug="ricerca-auto",
        host_id="alf_ubuntu",
        tasks_spec=[
            {"id": "T001", "title": "Hub active task", "state": "in progress", "host": "alf_ubuntu", "run_id": run_hub_id},
            {"id": "T002", "title": "Hub delivered task", "state": "delivered", "host": "alf_ubuntu", "verify_by": "claude"},
            {"id": "T003", "title": "Hub open task", "state": "open", "host": "alf_ubuntu"},
        ],
        questions_spec=[
            {"id": "Q001", "question": "Which OIDC realm on hub?", "status": "open", "blocks": "T001"},
            {"id": "Q002", "question": "Already answered question", "status": "answered", "blocks": "T002"},
        ],
        runs_spec=[
            {
                "run_id": run_hub_id,
                "task_id": "T001",
                "status": "running",
                "host": "alf_ubuntu",
                "backend": "screen",
                "screen_session": "agent-ricerca-auto-T001",
                "started_at": "2026-10-30T11:00:00+00:00",
                "last_heartbeat": "2026-10-30T11:58:00+00:00",
            }
        ],
    )

    _seed_project_with_tasks_questions_and_runs(
        mac_ws,
        proj_slug="local-app",
        host_id="mac",
        tasks_spec=[
            {"id": "T010", "title": "Mac active task", "state": "in progress", "host": "mac", "run_id": run_mac_id},
            {"id": "T011", "title": "Mac delivered task", "state": "delivered", "host": "mac", "verify_by": "owner"},
        ],
        questions_spec=[
            {"id": "Q010", "question": "Mac local question?", "status": "open", "blocks": "T010"},
        ],
        runs_spec=[
            {
                "run_id": run_mac_id,
                "task_id": "T010",
                "status": "running",
                "host": "mac",
                "backend": "screen",
                "screen_session": "agent-local-app-T010",
                "started_at": "2026-10-30T11:30:00+00:00",
                "last_heartbeat": "2026-10-30T11:59:00+00:00",
            }
        ],
    )

    # Configure hub and register `ricerca-auto` on hub
    (hub_cfg_dir / "orchestration.toml").write_text(
        '[host]\nid = "alf_ubuntu"\nrole = "hub"\nagent_user = "kilo"\n',
        encoding="utf-8",
    )
    plan_hub_reg = reg.plan_workspace_register(
        hub_ws,
        slug="ricerca-auto",
        config_dir=hub_cfg_dir,
        host="alf_ubuntu",
        primary_host="alf_ubuntu",
    )
    reg.apply_workspace_register(plan_hub_reg, expect_hash=plan_hub_reg["plan_hash"], config_dir=hub_cfg_dir)

    # Configure client (`mac`) with two remote hosts: `alf_ubuntu` (up) and `lab_worker` (down, timeout=1)
    (client_cfg_dir / "orchestration.toml").write_text(
        '[host]\nid = "mac"\nrole = "client"\n\n'
        '[hosts.alf_ubuntu]\nssh_target = "alf_ubuntu"\nrole = "hub"\nagent_user = "kilo"\ntimeout = 5\n\n'
        '[hosts.lab_worker]\nssh_target = "lab_worker"\nrole = "client"\ntimeout = 1\n',
        encoding="utf-8",
    )
    plan_mac_reg = reg.plan_workspace_register(
        mac_ws,
        slug="local-app",
        config_dir=client_cfg_dir,
        host="mac",
        primary_host="mac",
    )
    reg.apply_workspace_register(plan_mac_reg, expect_hash=plan_mac_reg["plan_hash"], config_dir=client_cfg_dir)

    # Create fake `ssh` script in PATH that:
    # - records every invocation to `ssh_calls.log`
    # - for `alf_ubuntu`: runs real `bin/ai-orch console status --local --config-dir <hub_cfg_dir> --json`
    # - for `lab_worker`: simulates an unreachable host (exits 255 with connection error)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir( exist_ok=True)
    ssh_log = tmp_path / "ssh_calls.log"
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        f"""#!{sys.executable}
import os, subprocess, sys
with open({str(ssh_log)!r}, "a", encoding="utf-8") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if "lab_worker" in args:
    sys.stderr.write("ssh: connect to host lab_worker port 22: No route to host\\n")
    sys.exit(255)
if "alf_ubuntu" in args:
    env = dict(os.environ, AI_ORCHESTRATION_CONFIG={str(hub_cfg_dir)!r})
    res = subprocess.run(
        [{sys.executable!r}, {str(BIN_AI_ORCH)!r}, "console", "status", "--local", "--config-dir", {str(hub_cfg_dir)!r}, "--json"],
         env=env,
         capture_output=True,
         text=True,
    )
    sys.stdout.write(res.stdout)
    sys.stderr.write(res.stderr)
    sys.exit(res.returncode)
sys.exit(255)
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(client_cfg_dir))

    # 1. Run `ai-orch console status --all-hosts --json`
    res = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "status", "--all-hosts", "--config-dir", str(client_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["host"] == "mac"
    assert data["hub_host"] == "alf_ubuntu"
    assert data["hub_reachable"] is True

    # Verify hosts reachability: mac (local, reachable), alf_ubuntu (hub, reachable), lab_worker (client, unreachable)
    hosts = data["hosts"]
    assert hosts["mac"]["reachable"] is True and hosts["mac"]["local"] is True
    assert hosts["alf_ubuntu"]["reachable"] is True and hosts["alf_ubuntu"]["role"] == "hub"
    assert hosts["lab_worker"]["reachable"] is False
    assert hosts["lab_worker"]["timeout_sec"] == 1.0
    assert "No route to host" in hosts["lab_worker"]["error"]

    # Verify aggregated projects from both hub and local
    proj_slugs = {p["slug"] for p in data["projects"]}
    assert {"ricerca-auto", "local-app"}.issubset(proj_slugs)

    # Verify aggregated tasks by state and by host
    assert data["tasks_by_state"]["in progress"] == 2
    assert data["tasks_by_state"]["delivered"] == 2
    assert data["tasks_by_state"]["open"] == 1
    assert data["tasks_by_host"]["alf_ubuntu"] == 3
    assert data["tasks_by_host"]["mac"] == 2
    assert data["tasks_by_state_and_host"]["in progress"] == {"alf_ubuntu": 1, "mac": 1}
    assert data["tasks_by_state_and_host"]["delivered"] == {"alf_ubuntu": 1, "mac": 1}

    # Verify aggregated runs from both hosts with host, task, state, age, last_heartbeat, and screen_session
    runs_by_id = {r["run_id"]: r for r in data["runs"]}
    assert set(runs_by_id.keys()) == {run_hub_id, run_mac_id}
    r_hub = runs_by_id[run_hub_id]
    assert r_hub["host"] == "alf_ubuntu"
    assert r_hub["task_id"] == "T001"
    assert r_hub["status"] == "running"
    assert r_hub["screen_session"] == "agent-ricerca-auto-T001"
    assert r_hub["last_heartbeat"] == "2026-10-30T11:58:00+00:00"
    assert isinstance(r_hub["age_sec"], (int, float))
    assert isinstance(r_hub["heartbeat_age_sec"], (int, float))

    r_mac = runs_by_id[run_mac_id]
    assert r_mac["host"] == "mac"
    assert r_mac["task_id"] == "T010"
    assert r_mac["status"] == "running"
    assert r_mac["screen_session"] == "agent-local-app-T010"

    # Verify open questions (answered Q002 excluded)
    q_ids = {q["id"] for q in data["open_questions"]}
    assert q_ids == {"Q001", "Q010"}

    # Verify deliveries to verify
    deliv_ids = {d["id"] for d in data["deliveries_to_verify"]}
    assert deliv_ids == {"T002", "T011"}

    # 2. Verify human-readable text output of `ai-orch console status --all-hosts`
    res_txt = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "status", "--all-hosts", "--config-dir", str(client_cfg_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    out_txt = res_txt.stdout
    assert "lab_worker" in out_txt and "UNREACHABLE" in out_txt
    assert run_hub_id in out_txt and "agent-ricerca-auto-T001" in out_txt
    assert run_mac_id in out_txt and "agent-local-app-T010" in out_txt
    assert "Q001" in out_txt and "Q010" in out_txt
    assert "T002" in out_txt and "T011" in out_txt


def test_19_8_console_attach_resolves_host_and_screen_session_and_rejects_unsafe_input(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 19.8 Verification:
    - `ai-orch console attach <run|task>` resolves host and session name from the run record and
      executes `ssh -t <target> screen -x <name>` (using `agent_user` on the hub: `kilo@alf_ubuntu`).
    - Resolves both by `run_id` and by `task_id` (both local runs and remote runs fetched from hub).
    - Host and session names are resolved strictly from code/config and run records, never interpolated from free input.
    """
    hub_cfg_dir = tmp_path / "hub_cfg"
    client_cfg_dir = tmp_path / "client_cfg"
    hub_cfg_dir.mkdir(parents=True)
    client_cfg_dir.mkdir(parents=True)

    hub_ws = tmp_path / "hub_works" / "ricerca_auto"
    mac_ws = tmp_path / "mac_works" / "local_app"
    hub_ws.mkdir(parents=True)
    mac_ws.mkdir(parents=True)

    run_hub_id = "20261030-120000-T205-kilo-1111"
    run_mac_id = "20261030-120500-T010-kilo-2222"
    run_setsid_id = "20261030-121000-T012-kilo-3333"

    _seed_project_with_tasks_questions_and_runs(
        hub_ws,
        proj_slug="ricerca-auto",
        host_id="alf_ubuntu",
        tasks_spec=[
            {"id": "T205", "title": "Hub executor task", "state": "in progress", "host": "alf_ubuntu", "run_id": run_hub_id},
        ],
        questions_spec=[],
        runs_spec=[
            {
                "run_id": run_hub_id,
                "task_id": "T205",
                "status": "running",
                "host": "alf_ubuntu",
                "backend": "screen",
                "screen_session": "agent-ricerca-auto-T205",
            }
        ],
    )

    _seed_project_with_tasks_questions_and_runs(
        mac_ws,
        proj_slug="local-app",
        host_id="mac",
        tasks_spec=[
            {"id": "T010", "title": "Mac executor task", "state": "in progress", "host": "mac", "run_id": run_mac_id},
        ],
        questions_spec=[],
        runs_spec=[
            {
                "run_id": run_mac_id,
                "task_id": "T010",
                "status": "running",
                "host": "mac",
                "backend": "screen",
                "screen_session": "agent-local-app-T010",
            },
            {
                "run_id": run_setsid_id,
                "task_id": "T012",
                "status": "running",
                "host": "mac",
                "backend": "setsid",
                "screen_session": None,
            },
        ],
    )

    (hub_cfg_dir / "orchestration.toml").write_text(
        '[host]\nid = "alf_ubuntu"\nrole = "hub"\nagent_user = "kilo"\n',
        encoding="utf-8",
    )
    plan_hub = reg.plan_workspace_register(hub_ws, slug="ricerca-auto", config_dir=hub_cfg_dir, host="alf_ubuntu")
    reg.apply_workspace_register(plan_hub, expect_hash=plan_hub["plan_hash"], config_dir=hub_cfg_dir)

    (client_cfg_dir / "orchestration.toml").write_text(
        '[host]\nid = "mac"\nrole = "client"\n\n'
        '[hosts.alf_ubuntu]\nssh_target = "alf_ubuntu"\nrole = "hub"\nagent_user = "kilo"\n\n'
        '[hosts.mac]\nssh_target = "mac"\nrole = "client"\n',
        encoding="utf-8",
    )
    plan_mac = reg.plan_workspace_register(mac_ws, slug="local-app", config_dir=client_cfg_dir, host="mac")
    reg.apply_workspace_register(plan_mac, expect_hash=plan_mac["plan_hash"], config_dir=client_cfg_dir)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    attach_log = tmp_path / "attach_calls.jsonl"
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        f"""#!{sys.executable}
import json, os, subprocess, sys
args = sys.argv[1:]
if "status" in args and "--local" in args:
    env = dict(os.environ, AI_ORCHESTRATION_CONFIG={str(hub_cfg_dir)!r})
    res = subprocess.run(
        [{sys.executable!r}, {str(BIN_AI_ORCH)!r}, "console", "status", "--local", "--config-dir", {str(hub_cfg_dir)!r}, "--json"],
        env=env,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(res.stdout)
    sys.exit(res.returncode)
with open({str(attach_log)!r}, "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\\n")
sys.exit(0)
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(client_cfg_dir))

    # 1. Attach to hub run by task_id (`T205`) -> opens `ssh -t kilo@alf_ubuntu screen -x agent-ricerca-auto-T205`
    res_attach_hub = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "attach", "T205", "--config-dir", str(client_cfg_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res_attach_hub.returncode == 0
    logged_calls = [json.loads(line) for line in attach_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert logged_calls[-1] == ["-t", "kilo@alf_ubuntu", "screen", "-x", "agent-ricerca-auto-T205"]

    # 2. Attach to hub run by run_id (`run_hub_id`) with `--json`
    res_attach_hub_id = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "attach", run_hub_id, "--config-dir", str(client_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    hub_attach_data = json.loads(res_attach_hub_id.stdout)
    assert hub_attach_data["ok"] is True
    assert hub_attach_data["host"] == "alf_ubuntu"
    assert hub_attach_data["ssh_target"] == "kilo@alf_ubuntu"
    assert hub_attach_data["screen_session"] == "agent-ricerca-auto-T205"
    assert hub_attach_data["command"] == ["ssh", "-t", "kilo@alf_ubuntu", "screen", "-x", "agent-ricerca-auto-T205"]
    assert hub_attach_data["actor"] == "owner (via console@mac)"

    # 3. Attach to client run (`T010` on `mac`) -> opens `ssh -t mac screen -x agent-local-app-T010` (no `kilo@` prefix)
    res_attach_mac = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "attach", "T010", "--config-dir", str(client_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    mac_attach_data = json.loads(res_attach_mac.stdout)
    assert mac_attach_data["ok"] is True
    assert mac_attach_data["host"] == "mac"
    assert mac_attach_data["ssh_target"] == "mac"
    assert mac_attach_data["command"] == ["ssh", "-t", "mac", "screen", "-x", "agent-local-app-T010"]

    # 4. Rejects non-screen (`setsid`) run
    res_setsid = subprocess.run(
        [sys.executable, str(BIN_AI_ORCH), "console", "attach", run_setsid_id, "--config-dir", str(client_cfg_dir), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_setsid.returncode == 2
    assert "does not have a screen session" in json.loads(res_setsid.stdout)["error"]

    # 5. Rejects free-form / malicious input without invoking ssh
    call_count_before = len(attach_log.read_text(encoding="utf-8").splitlines())
    for bad_input in (
        "; rm -rf /",
        "$(whoami)",
        "-oProxyCommand=evil",
        "../T205",
        "T205 && id",
    ):
        res_bad = subprocess.run(
            [sys.executable, str(BIN_AI_ORCH), "console", "attach", bad_input, "--config-dir", str(client_cfg_dir), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res_bad.returncode == 2, bad_input
        assert json.loads(res_bad.stdout)["ok"] is False
    call_count_after = len(attach_log.read_text(encoding="utf-8").splitlines())
    assert call_count_after == call_count_before


def test_19_8_per_host_timeout_and_undeclared_host_attach_rejection(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 19.8 Verification:
    - Per-host timeout terminates a hanging SSH connection without blocking other hosts.
    - `console attach` refuses a run record referencing an undeclared host ID.
    - Hub host without explicit `agent_user` defaults to `kilo@<ssh_target>` on attach.
    """
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)

    run_hub_id = "20261030-130000-T301-kilo-aaaa"
    run_evil_id = "20261030-130500-T302-kilo-bbbb"

    _seed_project_with_tasks_questions_and_runs(
        ws,
        proj_slug="ws",
        host_id="mac",
        tasks_spec=[],
        questions_spec=[],
        runs_spec=[
            {
                "run_id": run_hub_id,
                "task_id": "T301",
                "status": "running",
                "host": "alf_ubuntu",
                "backend": "screen",
                "screen_session": "agent-ws-T301",
            },
            {
                "run_id": run_evil_id,
                "task_id": "T302",
                "status": "running",
                "host": "undeclared_box",
                "backend": "screen",
                "screen_session": "agent-ws-T302",
            },
        ],
    )

    (cfg_dir / "orchestration.toml").write_text(
        '[host]\nid = "mac"\nrole = "client"\n\n'
        '[hosts.alf_ubuntu]\nssh_target = "alf_ubuntu"\nrole = "hub"\nport = 2222\n\n'
        '[hosts.hanging_host]\nssh_target = "hanging_host"\nrole = "client"\ntimeout = 0.3\n',
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        f"""#!{sys.executable}
import json, sys, time
args = sys.argv[1:]
if "hanging_host" in args:
    time.sleep(5)
    sys.exit(0)
if "alf_ubuntu" in args and "status" in args:
    print(json.dumps({{"ok": True, "host": "alf_ubuntu", "snapshot_version": 1, "items": [], "runs": []}}))
    sys.exit(0)
sys.exit(0)
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    import time

    t0 = time.monotonic()
    res = reg.get_console_status_projects(config_dir=cfg_dir, all_hosts=True, workspace=ws)
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0
    assert res["hosts"]["alf_ubuntu"]["reachable"] is True
    assert res["hosts"]["hanging_host"]["reachable"] is False
    assert res["hosts"]["hanging_host"]["timed_out"] is True
    assert "timed out" in res["hosts"]["hanging_host"]["error"]

    # Hub without explicit agent_user defaults to `kilo@alf_ubuntu` and includes `-p 2222`
    att = reg.resolve_console_attach("T301", config_dir=cfg_dir, workspace=ws)
    assert att["ssh_target"] == "kilo@alf_ubuntu"
    assert att["command"] == ["ssh", "-t", "-p", "2222", "kilo@alf_ubuntu", "screen", "-x", "agent-ws-T301"]

    # Undeclared host in run record is rejected
    with pytest.raises(ValueError, match="not declared in \\[hosts\\]"):
        reg.resolve_console_attach(run_evil_id, config_dir=cfg_dir, workspace=ws)






