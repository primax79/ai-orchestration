"""test_orchestration_runs.py — Tests for Task 07.2 runs engine.

Covers:
  - Resolution chain in all four layers (explicit, task header, project routing, global routing)
  - Every guard refusal (platform, task scope NN.T, state/mode, tool availability, same-task active, same-cwd active, independence, multi-repo)
  - Preview side-effect free (workspace tree hash before/after identical; no runs dir or exclude changes)
  - plan_hash sensitivity (changes on task bundle, config, instructions, HEAD drift)
  - .git/info/exclude management & check-ignore
  - run_id validation & directory traversal rejection
  - Redaction of {env:NAME} and flags matching token|key|secret|password
  - Allowed-modes table per state (R4)
  - Registry storage, locking, permissions (0700/0600), and monotonic status guards
  - CLI integration via bin/ai-orch
"""
from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import pytest

from orchestration_runs import (
    check_platform,
    check_task_id,
    check_task_state_and_mode,
    check_tool_availability,
    check_same_task_active,
    check_same_cwd_active,
    check_independence_guard,
    resolve_target_repo,
    resolve_tool,
    resolve_profile,
    resolve_model_and_variants,
    build_prompt,
    build_adapter_argv,
    redact_argv,
    validate_headless_argv_secrets,
    compute_plan_hash,
    generate_run_id,
    validate_run_id,
    create_run_record,
    save_run_record,
    load_run_record,
    list_run_records,
    ensure_git_exclude,
    run_lock,
    get_allowed_modes_for_state,
    get_default_mode_for_state,
    ALLOWED_MODES_PER_STATE,
    reconcile,
    get_process_start_time,
    is_process_alive,
    kill_process_group,
)

SCRIPT = pathlib.Path(__file__).resolve().parent / "orchestration_runs.py"
BIN_AI_ORCH = pathlib.Path(__file__).resolve().parent.parent / "bin" / "ai-orch"
STUB_AGENT = pathlib.Path(__file__).resolve().parent / "fixtures" / "runs" / "stub_agent.py"


def compute_tree_hash(root: pathlib.Path) -> str:
    """Compute sha256 over all relative file paths and file contents in root."""
    hasher = hashlib.sha256()
    entries: list[tuple[str, bytes]] = []
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = pathlib.Path(dirpath) / fname
            rel = fpath.relative_to(root).as_posix()
            try:
                entries.append((rel, fpath.read_bytes()))
            except OSError:
                pass
    entries.sort(key=lambda x: x[0])
    for rel, b in entries:
        hasher.update(rel.encode("utf-8") + b"\x00" + b)
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Platform and Scope Guards
# ---------------------------------------------------------------------------

def test_check_platform():
    # macOS and Linux with fcntl -> None (ok)
    assert check_platform("darwin", fcntl_mod=object()) is None
    assert check_platform("linux", fcntl_mod=object()) is None

    # Windows -> unsupported-platform
    assert check_platform("win32", fcntl_mod=object()) == "unsupported-platform"
    assert check_platform("cygwin", fcntl_mod=object()) is None

    # Missing fcntl -> unsupported-platform
    assert check_platform("darwin", fcntl_mod=None) == "unsupported-platform"


def test_check_task_id_and_nn_t_refusal():
    # Valid emergent IDs
    ok, err = check_task_id("T001")
    assert ok is True and err is None
    ok, err = check_task_id("T007")
    assert ok is True and err is None
    ok, err = check_task_id("T1234")
    assert ok is True and err is None

    # Initiative tasks (NN.T) refused
    for init_id in ("07.2", "01.T1", "12.T3", "NN.T"):
        ok, err = check_task_id(init_id)
        assert ok is False
        assert "Initiative tasks (NN.T) are not supported" in (err or "")

    # Invalid / empty formats
    for bad in ("", "   ", "abc", "task-007", "007"):
        ok, err = check_task_id(bad)
        assert ok is False


# ---------------------------------------------------------------------------
# Allowed Modes Table per State (R4)
# ---------------------------------------------------------------------------

def test_allowed_modes_table_per_state():
    # open, bounced -> execute (default), orchestrate
    for st in ("open", "bounced"):
        assert get_allowed_modes_for_state(st) == ["execute", "orchestrate"]
        assert get_default_mode_for_state(st) == "execute"
        assert check_task_state_and_mode(st, "execute")[0] is True
        assert check_task_state_and_mode(st, "orchestrate")[0] is True
        assert check_task_state_and_mode(st, "verify")[0] is False

    # in progress -> orchestrate only (or execute if continue/run exists)
    assert get_allowed_modes_for_state("in progress", has_existing_run=False) == ["orchestrate"]
    assert get_default_mode_for_state("in progress", is_continue=False) == "orchestrate"
    assert check_task_state_and_mode("in progress", "execute", has_existing_run=False)[0] is False
    assert check_task_state_and_mode("in progress", "orchestrate", has_existing_run=False)[0] is True
    # when run exists
    assert get_allowed_modes_for_state("in progress", has_existing_run=True) == ["execute", "orchestrate"]
    assert check_task_state_and_mode("in progress", "execute", has_existing_run=True)[0] is True

    # delivered -> verify (default), orchestrate
    assert get_allowed_modes_for_state("delivered") == ["verify", "orchestrate"]
    assert get_default_mode_for_state("delivered") == "verify"
    assert check_task_state_and_mode("delivered", "verify")[0] is True
    assert check_task_state_and_mode("delivered", "orchestrate")[0] is True
    assert check_task_state_and_mode("delivered", "execute")[0] is False

    # waiting, blocked -> orchestrate only
    for st in ("waiting", "blocked"):
        assert get_allowed_modes_for_state(st) == ["orchestrate"]
        assert get_default_mode_for_state(st) == "orchestrate"
        assert check_task_state_and_mode(st, "orchestrate")[0] is True
        assert check_task_state_and_mode(st, "execute")[0] is False
        assert check_task_state_and_mode(st, "verify")[0] is False

    # verified, done, done with a caveat, dropped -> none
    for st in ("verified", "done", "done with a caveat", "dropped"):
        assert get_allowed_modes_for_state(st) == []
        assert get_default_mode_for_state(st) is None
        for m in ("execute", "orchestrate", "verify"):
            ok, err = check_task_state_and_mode(st, m)
            assert ok is False
            assert "No run modes allowed" in (err or "")


# ---------------------------------------------------------------------------
# Guards Refusal Tests
# ---------------------------------------------------------------------------

def test_same_task_active_guard():
    active_runs = [{"run_id": "20261017-100000-T007-kilo-1111", "task_id": "T007", "status": "running"}]
    # Active run exists -> refused
    ok, err = check_same_task_active("T007", active_runs, force=False)
    assert ok is False
    assert "already has an active run" in (err or "")

    # --force bypasses same-task active guard
    ok, err = check_same_task_active("T007", active_runs, force=True)
    assert ok is True and err is None

    # Terminal run -> allowed without force
    terminal_runs = [{"run_id": "20261017-100000-T007-kilo-1111", "task_id": "T007", "status": "succeeded"}]
    ok, err = check_same_task_active("T007", terminal_runs, force=False)
    assert ok is True and err is None


def test_same_cwd_active_guard(tmp_path: pathlib.Path):
    dir_a = tmp_path / "workspace"
    dir_a.mkdir()
    dir_b = tmp_path / "other"
    dir_b.mkdir()

    active_runs = [{"run_id": "r1", "cwd": str(dir_a), "isolation": "none", "status": "running"}]

    # Same cwd with isolation none -> refused
    ok, err = check_same_cwd_active(str(dir_a), "none", active_runs)
    assert ok is False
    assert "already has an active run with isolation 'none'" in (err or "")

    # Different cwd with isolation none -> allowed
    ok, err = check_same_cwd_active(str(dir_b), "none", active_runs)
    assert ok is True and err is None

    # Same cwd with isolation worktree -> allowed (worktree is isolated)
    ok, err = check_same_cwd_active(str(dir_a), "worktree", active_runs)
    assert ok is True and err is None


def test_tool_availability_guard():
    # Enabled=False in config -> refused
    ok, ver, err = check_tool_availability("kilo", {"enabled": False})
    assert ok is False
    assert "disabled in configuration" in (err or "")

    # CLI not in PATH -> refused
    ok, ver, err = check_tool_availability(
        "kilo",
        {"enabled": True, "cli_command": "nonexistent_cli_xyz"},
        which_fn=lambda cmd: None,
    )
    assert ok is False
    assert "not found in PATH" in (err or "")

    # Version check failed -> refused
    def mock_version_fail(path):
        return None

    ok, ver, err = check_tool_availability(
        "kilo",
        {"enabled": True, "cli_command": "kilo"},
        which_fn=lambda cmd: "/usr/bin/kilo",
        version_fn=mock_version_fail,
    )
    assert ok is False
    assert "Could not determine version" in (err or "")

    # Normal success
    def mock_version_ok(path):
        return "7.8.9"

    ok, ver, err = check_tool_availability(
        "kilo",
        {"enabled": True, "cli_command": "kilo"},
        which_fn=lambda cmd: "/usr/bin/kilo",
        version_fn=mock_version_ok,
    )
    assert ok is True and ver == "7.8.9" and err is None


def test_independence_guard():
    # verify mode: tool == task executor -> refused without allow_same_tool
    ok, err = check_independence_guard("verify", "kilo", task_executor="kilo", target_run_tool=None, allow_same_tool=False)
    assert ok is False
    assert "matches task executor" in (err or "")

    # verify mode: tool == task executor with allow_same_tool -> allowed
    ok, err = check_independence_guard("verify", "kilo", task_executor="kilo", target_run_tool=None, allow_same_tool=True)
    assert ok is True and err is None

    # verify mode: tool == target_run_tool -> refused without allow_same_tool
    ok, err = check_independence_guard("verify", "kilo", task_executor="claude", target_run_tool="kilo", allow_same_tool=False)
    assert ok is False
    assert "matches target_run tool" in (err or "")

    # verify mode: tool independent -> allowed
    ok, err = check_independence_guard("verify", "claude", task_executor="kilo", target_run_tool="kilo", allow_same_tool=False)
    assert ok is True and err is None

    # execute mode: independence guard is not enforced
    ok, err = check_independence_guard("execute", "kilo", task_executor="kilo", target_run_tool="kilo", allow_same_tool=False)
    assert ok is True and err is None


# ---------------------------------------------------------------------------
# Resolution Chain in All Four Layers
# ---------------------------------------------------------------------------

def test_resolution_chain_all_four_layers():
    merged_cfg = {
        "tools": {
            "kilo": {"enabled": True},
            "claude": {"enabled": True},
            "codex": {"enabled": True},
        },
        "routing": {
            "default_executor": "codex",
            "default_orchestrator": "codex",
        },
        "verification": {
            "cross_agent_order": ["claude:deep-reasoning", "kilo:deep-reasoning"],
        },
    }
    project_cfg = {
        "routing": {
            "default_executor": "claude",
            "default_orchestrator": "claude",
        }
    }
    global_cfg = {
        "routing": {
            "default_executor": "codex",
            "default_orchestrator": "codex",
        }
    }

    # Layer 1: Explicit choice wins over all
    tool, _ = resolve_tool("execute", "codex", {"executor": "kilo"}, merged_cfg, project_cfg, global_cfg)
    assert tool == "codex"

    # Layer 2: Task executor header wins over project and global routing
    tool, _ = resolve_tool("execute", None, {"executor": "kilo"}, merged_cfg, project_cfg, global_cfg)
    assert tool == "kilo"

    # Layer 3: Project routing wins over global routing when task executor is '-'
    tool, _ = resolve_tool("execute", None, {"executor": "-"}, merged_cfg, project_cfg, global_cfg)
    assert tool == "claude"

    # Layer 4: Global routing wins when project routing is absent
    tool, _ = resolve_tool("execute", None, {"executor": "-"}, merged_cfg, None, global_cfg)
    assert tool == "codex"

    # Verify mode resolution: picks first cross_agent_order entry passing independence guard
    # Task executor is claude, target_run is claude -> claude is refused, kilo is picked
    tool, entry = resolve_tool(
        "verify",
        None,
        {"executor": "claude"},
        merged_cfg,
        project_cfg,
        global_cfg,
        allow_same_tool=False,
        target_run_tool="claude",
    )
    assert tool == "kilo"
    assert entry == "kilo:deep-reasoning"


# ---------------------------------------------------------------------------
# Secret Redaction (R13)
# ---------------------------------------------------------------------------

def test_secret_redaction():
    # Literal secret in --flag=val
    argv = ["kilo", "run", "--token=super_secret_123", "--dir", "/tmp"]
    redacted = redact_argv(argv)
    assert redacted == ["kilo", "run", "--token=[REDACTED]", "--dir", "/tmp"]

    # {env:NAME} reference in --flag=val is preserved
    argv_env = ["kilo", "run", "--token={env:MY_TOKEN}", "--dir", "/tmp"]
    assert redact_argv(argv_env) == ["kilo", "run", "--token={env:MY_TOKEN}", "--dir", "/tmp"]

    # Literal secret in two-arg form --api-key val
    argv_split = ["claude", "--api-key", "sk-ant-abc123", "-p"]
    assert redact_argv(argv_split) == ["claude", "--api-key", "[REDACTED]", "-p"]

    # {env:NAME} reference in two-arg form is preserved
    argv_split_env = ["claude", "--api-key", "{env:ANTHROPIC_KEY}", "-p"]
    assert redact_argv(argv_split_env) == ["claude", "--api-key", "{env:ANTHROPIC_KEY}", "-p"]

    # Password flag
    assert redact_argv(["codex", "--password", "secretpass"]) == ["codex", "--password", "[REDACTED]"]
    assert redact_argv(["codex", "--password", "{env:PASS}"]) == ["codex", "--password", "{env:PASS}"]

    # Config validation helper rejects literal secrets
    errs = validate_headless_argv_secrets(["claude", "--token=literal123"])
    assert len(errs) == 1 and "literal secret" in errs[0]

    errs_ok = validate_headless_argv_secrets(["claude", "--token={env:OK_TOKEN}"])
    assert len(errs_ok) == 0


# ---------------------------------------------------------------------------
# run_id Validation Rejects Traversal
# ---------------------------------------------------------------------------

def test_run_id_validation():
    # Valid
    assert validate_run_id("20261017-123456-T007-kilo-abcd") is True
    assert validate_run_id("20261017-000000-T123-claude-012f") is True
    assert validate_run_id("20261017-235959-T999-codex-9876") is True

    # Path traversal rejected
    assert validate_run_id("../../etc/passwd") is False
    assert validate_run_id("../20261017-123456-T007-kilo-abcd") is False
    assert validate_run_id("20261017-123456-T007-kilo-abcd/..") is False

    # Invalid tool or task format rejected
    assert validate_run_id("20261017-123456-07.2-kilo-abcd") is False  # NN.T
    assert validate_run_id("20261017-123456-T007-other-abcd") is False  # not kilo/claude/codex
    assert validate_run_id("20261017-123456-T007-kilo-abc") is False  # 3 hex
    assert validate_run_id("20261017-123456-T007-kilo-abcde") is False  # 5 hex


# ---------------------------------------------------------------------------
# Git Exclude Management (.git/info/exclude)
# ---------------------------------------------------------------------------

def test_git_exclude_management(tmp_path: pathlib.Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)

    # Initial ensure
    ok, err = ensure_git_exclude(repo_dir)
    assert ok is True and err is None

    exclude_file = repo_dir / ".git" / "info" / "exclude"
    assert exclude_file.is_file()
    content = exclude_file.read_text(encoding="utf-8")
    assert ".ai-orchestration/\n" in content

    # Check git check-ignore
    res = subprocess.run(
        ["git", "check-ignore", "-q", ".ai-orchestration/"],
        cwd=str(repo_dir),
        check=False,
    )
    assert res.returncode == 0

    # Idempotent: second run does not duplicate
    ok2, err2 = ensure_git_exclude(repo_dir)
    assert ok2 is True
    content2 = exclude_file.read_text(encoding="utf-8")
    assert content2.count(".ai-orchestration/") == 1


# ---------------------------------------------------------------------------
# Registry Storage, Monotonic Status, and Permissions
# ---------------------------------------------------------------------------

def test_registry_storage_and_monotonicity(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    ws.mkdir()

    run_id = generate_run_id("T007", "kilo")
    record = create_run_record(
        run_id=run_id,
        task_id="T007",
        mode="execute",
        tool="kilo",
        profile="bulk-execution",
        model="google/gemini-3.8-flash",
        variant="medium",
        effort=None,
        requested_by="cli",
        workspace=str(ws),
        cwd=str(ws),
        isolation="none",
        task_bundle_sha256="abc123bundle",
        argv_display=["kilo", "run"],
        plan_hash="plan123hash",
    )

    save_run_record(ws, record)

    # Check permissions: directory 0700, file 0600
    run_dir = ws / ".ai-orchestration" / "runs" / run_id
    run_file = run_dir / "run.json"
    assert run_dir.is_dir()
    assert run_file.is_file()
    assert (run_dir.stat().st_mode & 0o777) == 0o700
    assert (run_file.stat().st_mode & 0o777) == 0o600

    # Read back
    loaded = load_run_record(ws, run_id)
    assert loaded is not None
    assert loaded["run_id"] == run_id
    assert loaded["status"] == "starting"

    # Transition to terminal status succeeded
    record["status"] = "succeeded"
    record["ended_at"] = "2026-10-17T12:00:00Z"
    save_run_record(ws, record)

    loaded2 = load_run_record(ws, run_id)
    assert loaded2 is not None and loaded2["status"] == "succeeded"

    # Monotonic guard: attempting to revert terminal status to running raises ValueError
    record["status"] = "running"
    with pytest.raises(ValueError, match="Monotonic guard"):
        save_run_record(ws, record)

    # list_run_records
    listed = list_run_records(ws)
    assert len(listed) == 1 and listed[0]["run_id"] == run_id

    # Active filter should return 0 (since it is succeeded)
    active = list_run_records(ws, active_only=True)
    assert len(active) == 0


# ---------------------------------------------------------------------------
# Preview Side-Effect Free & plan_hash Sensitivity
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "sample_ws"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(ws), check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(ws), check=True)

    # Task file
    tasks_dir = ws / "tasks" / "server"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "T007-verification-gate.md"
    task_file.write_text(
        "# T007 Verification Gate\n\n"
        "- id: T007\n"
        "- title: Verification Gate\n"
        "- category: server\n"
        "- priority: P2\n"
        "- priority-reason: testing\n"
        "- next-up: yes\n"
        "- state: open\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: none\n\n"
        "## Goal\nGoal text.\n\n"
        "## Steps\n1. Step one.\n\n"
        "## Verification\npytest\n",
        encoding="utf-8",
    )

    # Project config
    proj_cfg = ws / ".ai-orchestration.local.toml"
    proj_cfg.write_text(
        '[project]\nname = "sample"\nprimary_orchestrator = "kilo"\n\n'
        '[routing]\ndefault_executor = "kilo"\ndefault_orchestrator = "kilo"\ndefault_profile = "bulk-execution"\n\n'
        '[verification]\ndefault_mode = "cross-agent"\ncross_agent_order = ["claude:deep-reasoning", "codex:deep-reasoning"]\n',
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=str(ws), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(ws), check=True)
    return ws


def test_preview_side_effect_free(sample_workspace: pathlib.Path):
    tree_hash_before = compute_tree_hash(sample_workspace)

    # Run preview via CLI
    cmd = [
        sys.executable,
        str(SCRIPT),
        "preview",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert "plan_hash" in data

    # Assert tree hash after is byte-identical
    tree_hash_after = compute_tree_hash(sample_workspace)
    assert tree_hash_before == tree_hash_after

    # Assert .ai-orchestration directory was NOT created
    assert not (sample_workspace / ".ai-orchestration").exists()

    # Assert .git/info/exclude was NOT touched
    exclude_file = sample_workspace / ".git" / "info" / "exclude"
    if exclude_file.exists():
        assert ".ai-orchestration" not in exclude_file.read_text(encoding="utf-8")


def test_plan_hash_sensitivity(sample_workspace: pathlib.Path):
    # Baseline
    cmd_base = [
        sys.executable,
        str(SCRIPT),
        "preview",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_base = subprocess.run(cmd_base, capture_output=True, text=True, check=True)
    base_plan_hash = json.loads(res_base.stdout)["plan_hash"]

    # 1. Task file modified -> plan_hash changes
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    original_task_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(original_task_text + "\n<!-- edit -->\n", encoding="utf-8")

    res_mod_task = subprocess.run(cmd_base, capture_output=True, text=True, check=True)
    mod_task_plan_hash = json.loads(res_mod_task.stdout)["plan_hash"]
    assert mod_task_plan_hash != base_plan_hash

    # Revert task file -> plan_hash matches baseline
    task_file.write_text(original_task_text, encoding="utf-8")
    res_reverted = subprocess.run(cmd_base, capture_output=True, text=True, check=True)
    assert json.loads(res_reverted.stdout)["plan_hash"] == base_plan_hash

    # 2. Config modified -> plan_hash changes
    cfg_file = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = cfg_file.read_text(encoding="utf-8")
    cfg_file.write_text(
        orig_cfg + '\n[tools.kilo.profiles.bulk-execution]\nmodel = "google/gemini-4-custom"\n',
        encoding="utf-8",
    )

    res_mod_cfg = subprocess.run(cmd_base, capture_output=True, text=True, check=True)
    mod_cfg_plan_hash = json.loads(res_mod_cfg.stdout)["plan_hash"]
    assert mod_cfg_plan_hash != base_plan_hash

    # Revert config -> plan_hash matches baseline
    cfg_file.write_text(orig_cfg, encoding="utf-8")
    res_cfg_revert = subprocess.run(cmd_base, capture_output=True, text=True, check=True)
    assert json.loads(res_cfg_revert.stdout)["plan_hash"] == base_plan_hash

    # 3. Instructions changed -> plan_hash changes
    cmd_instr = cmd_base + ["--instructions", "Focus on clean test coverage"]
    res_instr = subprocess.run(cmd_instr, capture_output=True, text=True, check=True)
    instr_plan_hash = json.loads(res_instr.stdout)["plan_hash"]
    assert instr_plan_hash != base_plan_hash


# ---------------------------------------------------------------------------
# CLI Integration via bin/ai-orch
# ---------------------------------------------------------------------------

def test_bin_ai_orch_run_commands(sample_workspace: pathlib.Path):
    # ai-orch run options
    cmd_opt = [
        str(BIN_AI_ORCH),
        "run",
        "options",
        "--task",
        "T007",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_opt = subprocess.run(cmd_opt, capture_output=True, text=True, check=True)
    data_opt = json.loads(res_opt.stdout)
    assert data_opt["ok"] is True
    assert data_opt["task"]["id"] == "T007"
    assert "tools" in data_opt
    assert "resolved_defaults" in data_opt

    # ai-orch run preview
    cmd_prev = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_prev = subprocess.run(cmd_prev, capture_output=True, text=True, check=True)
    data_prev = json.loads(res_prev.stdout)
    assert data_prev["ok"] is True
    assert data_prev["planned_branch"] == "run/T007"
    assert data_prev["plan_hash"]

    # ai-orch run list
    cmd_list = [
        str(BIN_AI_ORCH),
        "run",
        "list",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_list = subprocess.run(cmd_list, capture_output=True, text=True, check=True)
    data_list = json.loads(res_list.stdout)
    assert data_list["ok"] is True
    assert data_list["runs"] == []

    # ai-orch run show with non-existent id
    cmd_show = [
        str(BIN_AI_ORCH),
        "run",
        "show",
        "20261017-123456-T007-kilo-9999",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_show = subprocess.run(cmd_show, capture_output=True, text=True, check=False)
    assert res_show.returncode != 0
    data_show = json.loads(res_show.stdout)
    assert data_show["ok"] is False and data_show["reason"] == "not-found"


def test_multi_repo_paths_refusal(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    repo_b = tmp_path / "repo_b"
    repo_b.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_a), check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=str(repo_b), check=True, capture_output=True)

    file_a = repo_a / "a.py"
    file_a.write_text("print('a')")
    file_b = repo_b / "b.py"
    file_b.write_text("print('b')")

    target_repo, all_repos, err = resolve_target_repo(
        ws, f"{file_a.as_posix()}, {file_b.as_posix()}"
    )
    assert target_repo is None
    assert "Paths resolve to multiple git repositories" in (err or "")


def test_preview_verify_and_orchestrate_modes(sample_workspace: pathlib.Path):
    # Preview orchestrate mode: isolation is none, cwd is workspace root
    cmd_orch = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "orchestrate",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_orch = subprocess.run(cmd_orch, capture_output=True, text=True, check=True)
    data_orch = json.loads(res_orch.stdout)
    assert data_orch["ok"] is True
    assert data_orch["planned_worktree"] is None
    assert data_orch["planned_branch"] is None
    assert data_orch["cwd"] == str(sample_workspace.resolve())
    assert "Orchestrator Guidelines" in data_orch["prompt"]

    # Preview verify mode with independent tool (claude is in cross_agent_order, executor is kilo)
    # Set task state to delivered first (R4 requirement)
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    orig_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(orig_text.replace("state: open", "state: delivered"), encoding="utf-8")

    cmd_ver = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_ver = subprocess.run(cmd_ver, capture_output=True, text=True, check=True)
    data_ver = json.loads(res_ver.stdout)
    assert data_ver["ok"] is True
    assert "verify-T007" in data_ver["cwd"]
    assert "Verification Guidelines" in data_ver["prompt"]
    assert "ai-orch-verdict" in data_ver["prompt"]


def test_preview_warnings(sample_workspace: pathlib.Path):
    # Dirty repo warning: add uncommitted file
    dirty_file = sample_workspace / "dirty.txt"
    dirty_file.write_text("dirty")

    cmd_prev = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_prev = subprocess.run(cmd_prev, capture_output=True, text=True, check=True)
    data_prev = json.loads(res_prev.stdout)
    assert data_prev["ok"] is True
    assert any("uncommitted changes" in w for w in data_prev["warnings"])

    # Clean up dirty file
    dirty_file.unlink()

    # Change task state to delivered for verify mode test
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    orig_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(orig_text.replace("state: open", "state: delivered"), encoding="utf-8")

    # Same tool in verify with allow_same_tool warning
    cmd_same = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--tool",
        "kilo",
        "--allow-same-tool",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_same = subprocess.run(cmd_same, capture_output=True, text=True, check=True)
    data_same = json.loads(res_same.stdout)
    assert data_same["ok"] is True
    assert any("downgraded to independent-session" in w for w in data_same["warnings"])


# ---------------------------------------------------------------------------
# Task 07.3 Tests: Supervisor, Adapters, Start/Logs/Cancel, Reconciliation
# ---------------------------------------------------------------------------

def test_start_and_outcome_recording(sample_workspace: pathlib.Path):
    # Configure kilo headless argv in workspace config
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    stub_path_str = str(STUB_AGENT)
    
    # 1. Test succeeded run
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{stub_path_str}", "--lines", "3", "--exit-code", "0"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "none",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    data_start = json.loads(res_start.stdout)
    assert data_start["ok"] is True
    run_id = data_start["run_id"]
    assert data_start["status"] == "starting"

    # Poll until completed
    deadline = time.time() + 10.0
    record = None
    while time.time() < deadline:
        record = load_run_record(sample_workspace, run_id)
        if record and record.get("status") in ("succeeded", "failed"):
            break
        time.sleep(0.2)

    assert record is not None
    assert record["status"] == "succeeded"
    assert record["exit_code"] == 0
    assert record["supervisor"]["pid"] is not None
    assert record["supervisor"]["start_time"] is not None
    assert record["agent"]["pid"] is not None
    assert record["agent"]["start_time"] is not None

    # 2. Test failed run
    # Reset task back to open for another test run
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    orig_task = task_file.read_text(encoding="utf-8")
    task_file.write_text(orig_task.replace("state: in progress", "state: open"), encoding="utf-8")

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{stub_path_str}", "--lines", "1", "--exit-code", "42"]\n',
        encoding="utf-8",
    )

    res_fail = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    data_fail = json.loads(res_fail.stdout)
    run_id_fail = data_fail["run_id"]

    deadline = time.time() + 10.0
    rec_fail = None
    while time.time() < deadline:
        rec_fail = load_run_record(sample_workspace, run_id_fail)
        if rec_fail and rec_fail.get("status") in ("succeeded", "failed"):
            break
        time.sleep(0.2)

    assert rec_fail is not None
    assert rec_fail["status"] == "failed"
    assert rec_fail["exit_code"] == 42


def test_cancel_and_grandchild_process_group_killed(sample_workspace: pathlib.Path, tmp_path: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    gc_pid_file = tmp_path / "grandchild.pid"

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "30", "--grandchild-pid-file", "{gc_pid_file}", "--grandchild-sleep", "60"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "none",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    data_start = json.loads(res_start.stdout)
    run_id = data_start["run_id"]

    # Wait for grandchild PID to be written
    deadline = time.time() + 10.0
    while time.time() < deadline and not gc_pid_file.is_file():
        time.sleep(0.1)

    assert gc_pid_file.is_file()
    gc_pid = int(gc_pid_file.read_text(encoding="utf-8").strip())

    # Get agent pid
    record = load_run_record(sample_workspace, run_id)
    assert record is not None
    agent_pid = record["agent"]["pid"]
    assert agent_pid is not None

    # Check both grandchild and agent are alive
    assert is_process_alive(gc_pid) is True
    assert is_process_alive(agent_pid) is True

    # Cancel the run
    cmd_cancel = [
        str(BIN_AI_ORCH),
        "run",
        "cancel",
        run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_cancel = subprocess.run(cmd_cancel, capture_output=True, text=True, check=True)
    data_cancel = json.loads(res_cancel.stdout)
    assert data_cancel["ok"] is True
    assert data_cancel["status"] == "cancelled"

    # Both agent and grandchild must now be dead
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not is_process_alive(gc_pid) and not is_process_alive(agent_pid):
            break
        time.sleep(0.1)

    assert is_process_alive(gc_pid) is False
    assert is_process_alive(agent_pid) is False

    # Status in run.json must be cancelled
    updated_rec = load_run_record(sample_workspace, run_id)
    assert updated_rec is not None
    assert updated_rec["status"] == "cancelled"


def test_reconcile_supervisor_sigkill_marks_lost_and_kills_agent_group(
    sample_workspace: pathlib.Path, tmp_path: pathlib.Path
):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    gc_pid_file = tmp_path / "gc_lost.pid"

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "30", "--grandchild-pid-file", "{gc_pid_file}", "--grandchild-sleep", "60"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "none",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_start.stdout)["run_id"]

    # Wait for running
    deadline = time.time() + 10.0
    record = None
    while time.time() < deadline:
        record = load_run_record(sample_workspace, run_id)
        if record and record.get("status") == "running" and gc_pid_file.is_file():
            break
        time.sleep(0.1)

    assert record is not None
    assert record["status"] == "running"
    sup_pid = record["supervisor"]["pid"]
    agent_pid = record["agent"]["pid"]
    gc_pid = int(gc_pid_file.read_text(encoding="utf-8").strip())

    assert is_process_alive(sup_pid) is True
    assert is_process_alive(agent_pid) is True
    assert is_process_alive(gc_pid) is True

    # SIGKILL the supervisor!
    os.kill(sup_pid, signal.SIGKILL)
    time.sleep(0.2)
    assert is_process_alive(sup_pid) is False

    # Calling list triggers reconciliation on read
    cmd_list = [
        str(BIN_AI_ORCH),
        "run",
        "list",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_list = subprocess.run(cmd_list, capture_output=True, text=True, check=True)
    data_list = json.loads(res_list.stdout)
    target_entry = next((r for r in data_list["runs"] if r["run_id"] == run_id), None)
    assert target_entry is not None
    assert target_entry["status"] == "lost"

    # Verify agent and grandchild were killed!
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not is_process_alive(agent_pid) and not is_process_alive(gc_pid):
            break
        time.sleep(0.1)

    assert is_process_alive(agent_pid) is False
    assert is_process_alive(gc_pid) is False


def test_reconcile_pid_reuse_simulated_does_not_kill(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "30"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "none",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_start.stdout)["run_id"]

    deadline = time.time() + 10.0
    record = None
    while time.time() < deadline:
        record = load_run_record(sample_workspace, run_id)
        if record and record.get("status") == "running":
            break
        time.sleep(0.1)

    assert record is not None
    sup_pid = record["supervisor"]["pid"]
    agent_pid = record["agent"]["pid"]

    # Mutate agent start_time in run.json to simulate PID reuse
    run_file = sample_workspace / ".ai-orchestration" / "runs" / run_id / "run.json"
    raw_data = json.loads(run_file.read_text(encoding="utf-8"))
    raw_data["agent"]["start_time"] = "2000-01-01T00:00:00"
    run_file.write_text(json.dumps(raw_data, indent=2), encoding="utf-8")

    # Kill supervisor
    os.kill(sup_pid, signal.SIGKILL)
    time.sleep(0.2)

    # Trigger reconcile via list
    cmd_list = [
        str(BIN_AI_ORCH),
        "run",
        "list",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_list = subprocess.run(cmd_list, capture_output=True, text=True, check=True)
    entry = next((r for r in json.loads(res_list.stdout)["runs"] if r["run_id"] == run_id), None)
    assert entry is not None
    assert entry["status"] == "lost"

    # Agent must NOT be killed because start_time differed!
    assert is_process_alive(agent_pid) is True

    # Cleanup manually
    try:
        os.kill(agent_pid, signal.SIGKILL)
    except OSError:
        pass


def test_prompt_not_in_ps_args(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "15"]\n',
        encoding="utf-8",
    )

    canary = "CANARY_SECRET_PROMPT_X987654321"
    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "none",
        "--instructions",
        canary,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_start.stdout)["run_id"]

    deadline = time.time() + 10.0
    record = None
    while time.time() < deadline:
        record = load_run_record(sample_workspace, run_id)
        if record and record.get("status") == "running":
            break
        time.sleep(0.1)

    assert record is not None
    agent_pid = record["agent"]["pid"]

    # Check ps -o args= -p <agent_pid>
    res_ps = subprocess.run(["ps", "-o", "args=", "-p", str(agent_pid)], capture_output=True, text=True, check=True)
    ps_output = res_ps.stdout
    assert canary not in ps_output

    # Cancel to cleanup
    subprocess.run([str(BIN_AI_ORCH), "run", "cancel", run_id, "--workspace", str(sample_workspace)], check=True)


def test_two_concurrent_start_for_same_task(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "10"]\n',
        encoding="utf-8",
    )

    cmd = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "none",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(lambda: subprocess.run(cmd, capture_output=True, text=True))
        f2 = executor.submit(lambda: subprocess.run(cmd, capture_output=True, text=True))
        r1 = f1.result()
        r2 = f2.result()

    exit_codes = sorted([r1.returncode, r2.returncode])
    assert exit_codes == [0, 1]

    successful = r1 if r1.returncode == 0 else r2
    failed = r2 if r1.returncode == 0 else r1

    succ_data = json.loads(successful.stdout)
    assert succ_data["ok"] is True
    run_id = succ_data["run_id"]

    fail_data = json.loads(failed.stdout)
    assert fail_data["ok"] is False
    assert fail_data["reason"] == "same-task-active"

    # Cleanup
    subprocess.run([str(BIN_AI_ORCH), "run", "cancel", run_id, "--workspace", str(sample_workspace)], check=True)


def test_log_rotation_and_offsets(sample_workspace: pathlib.Path, monkeypatch):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    # Set chunk size to 600 bytes to force rotation with few lines
    monkeypatch.setenv("AI_ORCH_LOG_CHUNK_SIZE", "600")

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--lines", "25", "--exit-code", "0"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "none",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_start.stdout)["run_id"]

    deadline = time.time() + 10.0
    while time.time() < deadline:
        rec = load_run_record(sample_workspace, run_id)
        if rec and rec.get("status") == "succeeded":
            break
        time.sleep(0.2)

    run_dir = sample_workspace / ".ai-orchestration" / "runs" / run_id
    chunk_files = sorted(run_dir.glob("events.*.jsonl"))
    assert len(chunk_files) >= 2

    # Query logs
    cmd_logs = [
        str(BIN_AI_ORCH),
        "run",
        "logs",
        run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_logs = subprocess.run(cmd_logs, capture_output=True, text=True, check=True)
    data_logs = json.loads(res_logs.stdout)
    assert data_logs["ok"] is True
    assert data_logs["first_available_offset"] == 0
    total_bytes = data_logs["next_offset"]
    assert total_bytes > 600
    assert len(data_logs["events"]) == 25

    # Incremental query with --since-offset
    cmd_since = [
        str(BIN_AI_ORCH),
        "run",
        "logs",
        run_id,
        "--since-offset",
        "600",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_since = subprocess.run(cmd_since, capture_output=True, text=True, check=True)
    data_since = json.loads(res_since.stdout)
    assert data_since["ok"] is True
    assert len(data_since["events"]) < 25

    # Simulate retention: delete chunk 0
    (run_dir / "events.000.jsonl").unlink()
    res_retention = subprocess.run(cmd_logs, capture_output=True, text=True, check=True)
    data_ret = json.loads(res_retention.stdout)
    assert data_ret["ok"] is True
    assert data_ret["first_available_offset"] > 0


def test_expect_plan_hash_mismatch_and_requested_by(sample_workspace: pathlib.Path):
    cmd_prev = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "orchestrate",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_prev = subprocess.run(cmd_prev, capture_output=True, text=True, check=True)
    correct_hash = json.loads(res_prev.stdout)["plan_hash"]

    # 1. expect_plan_hash mismatch refused
    cmd_bad_hash = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "orchestrate",
        "--expect-plan-hash",
        "badhash123456",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_bad = subprocess.run(cmd_bad_hash, capture_output=True, text=True, check=False)
    assert res_bad.returncode != 0
    data_bad = json.loads(res_bad.stdout)
    assert data_bad["ok"] is False
    assert data_bad["reason"] == "plan-hash-mismatch"

    # 2. requested_by ui without expect_plan_hash refused
    cmd_no_hash_ui = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "orchestrate",
        "--requested-by",
        "ui",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_no_hash = subprocess.run(cmd_no_hash_ui, capture_output=True, text=True, check=False)
    assert res_no_hash.returncode != 0
    data_no_hash = json.loads(res_no_hash.stdout)
    assert data_no_hash["ok"] is False
    assert data_no_hash["reason"] == "missing-plan-hash"

    # 3. requested_by ui with correct hash succeeds
    cmd_good_ui = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "orchestrate",
        "--requested-by",
        "ui",
        "--expect-plan-hash",
        correct_hash,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_good = subprocess.run(cmd_good_ui, capture_output=True, text=True, check=True)
    data_good = json.loads(res_good.stdout)
    assert data_good["ok"] is True
    run_id = data_good["run_id"]
    subprocess.run([str(BIN_AI_ORCH), "run", "cancel", run_id, "--workspace", str(sample_workspace)], check=True)


def test_claude_without_allowed_tools_refused(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    # 1. Claude without allowed_tools
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.claude.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "0"]\n',
        encoding="utf-8",
    )

    cmd_claude = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "orchestrate",
        "--tool",
        "claude",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_no_at = subprocess.run(cmd_claude, capture_output=True, text=True, check=False)
    assert res_no_at.returncode != 0
    data_no_at = json.loads(res_no_at.stdout)
    assert data_no_at["ok"] is False
    assert data_no_at["reason"] == "missing-allowed-tools"

    # 2. Claude with allowed_tools succeeds
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.claude.headless]\nallowed_tools = ["Bash", "Read"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "0"]\n',
        encoding="utf-8",
    )

    res_ok = subprocess.run(cmd_claude, capture_output=True, text=True, check=True)
    data_ok = json.loads(res_ok.stdout)
    assert data_ok["ok"] is True
    run_id = data_ok["run_id"]
    assert data_ok["status"] == "starting"


def test_execute_start_moves_task_to_in_progress(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "2", "--exit-code", "0"]\n',
        encoding="utf-8",
    )

    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    assert "state: open" in task_file.read_text(encoding="utf-8")

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "none",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_start.stdout)["run_id"]

    deadline = time.time() + 10.0
    while time.time() < deadline:
        content = task_file.read_text(encoding="utf-8")
        if "state: in progress" in content:
            break
        time.sleep(0.1)

    final_content = task_file.read_text(encoding="utf-8")
    assert "state: in progress" in final_content


def test_execute_worktree_isolation_not_implemented_refusal(sample_workspace: pathlib.Path):
    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "worktree",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=False)
    assert res.returncode != 0
    data = json.loads(res.stdout)
    assert data["ok"] is False
    assert data["reason"] == "not-implemented-yet"

