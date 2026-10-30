#!/usr/bin/env python3
"""test_orchestration_registry.py — Tests for workspace identity, explicit projects, nesting & registry."""
from __future__ import annotations

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


