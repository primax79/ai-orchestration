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
    resolve_claude_allowed_tools,
    check_claude_allowed_tools,
    DEFAULT_CLAUDE_ALLOWED_TOOLS,
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


def test_resolve_claude_allowed_tools_precedence():
    # 1. Built-in defaults per mode
    exec_tools, exec_src = resolve_claude_allowed_tools({}, "execute")
    assert exec_src == "default"
    assert exec_tools == DEFAULT_CLAUDE_ALLOWED_TOOLS["execute"]
    assert "Read" in exec_tools
    assert "Edit" in exec_tools
    assert "Write" in exec_tools
    assert "mcp__kilo-mcp__*" not in exec_tools

    ver_tools, ver_src = resolve_claude_allowed_tools({}, "verify")
    assert ver_src == "default"
    assert ver_tools == DEFAULT_CLAUDE_ALLOWED_TOOLS["verify"]
    assert "Read" in ver_tools
    assert "Edit" not in ver_tools
    assert "Write" not in ver_tools
    assert "mcp__kilo-mcp__*" not in ver_tools

    orch_tools, orch_src = resolve_claude_allowed_tools({}, "orchestrate")
    assert orch_src == "default"
    assert orch_tools == DEFAULT_CLAUDE_ALLOWED_TOOLS["orchestrate"]
    assert "Read" in orch_tools
    assert "Edit" in orch_tools
    assert "Write" in orch_tools
    assert "mcp__kilo-mcp__*" in orch_tools

    # 2. Config single list overrides default for all modes
    single_cfg = {"allowed_tools": ["Bash", "Read"]}
    tools, src = resolve_claude_allowed_tools(single_cfg, "execute")
    assert src == "config:all"
    assert tools == ["Bash", "Read"]

    tools, src = resolve_claude_allowed_tools(single_cfg, "verify")
    assert src == "config:all"
    assert tools == ["Bash", "Read"]

    # 3. Config per-mode overrides both single list and default
    per_mode_cfg = {
        "allowed_tools": {
            "execute": ["EditOnly"],
            "verify": ["ReadOnly"],
        }
    }
    tools, src = resolve_claude_allowed_tools(per_mode_cfg, "execute")
    assert src == "config:execute"
    assert tools == ["EditOnly"]

    tools, src = resolve_claude_allowed_tools(per_mode_cfg, "verify")
    assert src == "config:verify"
    assert tools == ["ReadOnly"]

    # Mode not in per-mode table falls back to default
    tools, src = resolve_claude_allowed_tools(per_mode_cfg, "orchestrate")
    assert src == "default"
    assert tools == DEFAULT_CLAUDE_ALLOWED_TOOLS["orchestrate"]

    # 4. Check function
    ok, err = check_claude_allowed_tools({}, "execute")
    assert ok is True
    assert err is None

    ok, err = check_claude_allowed_tools({"allowed_tools": []}, "execute")
    assert ok is False
    assert "non-empty 'allowed_tools'" in (err or "")


def test_claude_allowed_tools_defaults_and_preview(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    # 1. Default applied per mode when config has none
    # Check preview for execute mode
    cmd_prev_exec = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--tool",
        "claude",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_exec = subprocess.run(cmd_prev_exec, capture_output=True, text=True, check=True)
    data_exec = json.loads(res_exec.stdout)
    assert data_exec["ok"] is True
    assert data_exec["allowed_tools_source"] == "default"
    assert "Read" in data_exec["allowed_tools"]
    assert "Edit" in data_exec["allowed_tools"]
    assert "Write" in data_exec["allowed_tools"]
    assert "mcp__kilo-mcp__*" not in data_exec["allowed_tools"]
    assert any("--allowedTools" in arg for arg in data_exec["argv_display"])
    assert not any("--dangerously" in arg for arg in data_exec["argv_display"])

    # Check preview for verify mode (minus Edit and Write)
    # Set task to delivered for verify mode
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    orig_task_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(orig_task_text.replace("state: open", "state: delivered"), encoding="utf-8")

    cmd_prev_ver = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--tool",
        "claude",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_ver = subprocess.run(cmd_prev_ver, capture_output=True, text=True, check=True)
    data_ver = json.loads(res_ver.stdout)
    assert data_ver["ok"] is True
    assert data_ver["allowed_tools_source"] == "default"
    assert "Read" in data_ver["allowed_tools"]
    assert "Edit" not in data_ver["allowed_tools"]
    assert "Write" not in data_ver["allowed_tools"]
    assert "mcp__kilo-mcp__*" not in data_ver["allowed_tools"]

    # Check preview for orchestrate mode (includes mcp__kilo-mcp__*)
    cmd_prev_orch = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
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
    res_orch = subprocess.run(cmd_prev_orch, capture_output=True, text=True, check=True)
    data_orch = json.loads(res_orch.stdout)
    assert data_orch["ok"] is True
    assert data_orch["allowed_tools_source"] == "default"
    assert "Read" in data_orch["allowed_tools"]
    assert "Edit" in data_orch["allowed_tools"]
    assert "Write" in data_orch["allowed_tools"]
    assert "mcp__kilo-mcp__*" in data_orch["allowed_tools"]

    # Claude with default allowed_tools launches successfully without missing-allowed-tools refusal
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.claude.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "0"]\n',
        encoding="utf-8",
    )
    cmd_start = [
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
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    data_start = json.loads(res_start.stdout)
    assert data_start["ok"] is True
    assert data_start["status"] == "starting"


def test_claude_allowed_tools_overrides_and_empty_refusal(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    cmd_prev_exec = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--tool",
        "claude",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]

    # 1. Per-mode override
    proj_cfg.write_text(
        orig_cfg + '\n[tools.claude.headless.allowed_tools]\nexecute = ["Read", "CustomTool"]\n',
        encoding="utf-8",
    )
    res_exec = subprocess.run(cmd_prev_exec, capture_output=True, text=True, check=True)
    data_exec = json.loads(res_exec.stdout)
    assert data_exec["allowed_tools"] == ["Read", "CustomTool"]
    assert data_exec["allowed_tools_source"] == "config:execute"

    # Orchestrate mode in same config falls back to default
    cmd_prev_orch = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
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
    res_orch = subprocess.run(cmd_prev_orch, capture_output=True, text=True, check=True)
    data_orch = json.loads(res_orch.stdout)
    assert data_orch["allowed_tools_source"] == "default"

    # 2. Single-list override
    proj_cfg.write_text(
        orig_cfg + '\n[tools.claude.headless]\nallowed_tools = ["ToolA", "ToolB"]\n',
        encoding="utf-8",
    )
    res_single = subprocess.run(cmd_prev_exec, capture_output=True, text=True, check=True)
    data_single = json.loads(res_single.stdout)
    assert data_single["allowed_tools"] == ["ToolA", "ToolB"]
    assert data_single["allowed_tools_source"] == "config:all"

    # 3. Empty list refused
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.claude.headless]\nallowed_tools = []\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "0"]\n',
        encoding="utf-8",
    )
    # Preview shows empty list, config:all, and warning
    res_empty_prev = subprocess.run(cmd_prev_exec, capture_output=True, text=True, check=True)
    data_empty_prev = json.loads(res_empty_prev.stdout)
    assert data_empty_prev["allowed_tools"] == []
    assert data_empty_prev["allowed_tools_source"] == "config:all"
    assert any("empty" in w for w in data_empty_prev["warnings"])

    # Start refused with missing-allowed-tools
    cmd_start_exec = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--tool",
        "claude",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_empty_start = subprocess.run(cmd_start_exec, capture_output=True, text=True, check=False)
    assert res_empty_start.returncode != 0
    data_empty_start = json.loads(res_empty_start.stdout)
    assert data_empty_start["ok"] is False
    assert data_empty_start["reason"] == "missing-allowed-tools"

    # Per-mode empty list also refused
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.claude.headless.allowed_tools]\nexecute = []\n[tools.claude.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "0"]\n',
        encoding="utf-8",
    )
    res_pm_empty = subprocess.run(cmd_start_exec, capture_output=True, text=True, check=False)
    assert res_pm_empty.returncode != 0
    data_pm_empty = json.loads(res_pm_empty.stdout)
    assert data_pm_empty["ok"] is False
    assert data_pm_empty["reason"] == "missing-allowed-tools"


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


def wait_for_terminal(ws: pathlib.Path, run_id: str, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = load_run_record(ws, run_id)
        if rec and rec.get("status") in ("succeeded", "failed", "cancelled", "lost"):
            return rec
        time.sleep(0.1)
    raise TimeoutError(f"Run {run_id} did not reach terminal state within {timeout}s")


def test_dirty_repo_refusal_and_allow_dirty_base(sample_workspace: pathlib.Path):
    dirty_file = sample_workspace / "dirty_base.txt"
    dirty_file.write_text("uncommitted dirty file")

    cmd_refuse = [
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
    res_refuse = subprocess.run(cmd_refuse, capture_output=True, text=True, check=False)
    assert res_refuse.returncode != 0
    data_refuse = json.loads(res_refuse.stdout)
    assert data_refuse["ok"] is False
    assert data_refuse["reason"] == "dirty-repo"
    assert "dirty_base.txt" in data_refuse["error"]

    cmd_allow = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "execute",
        "--isolation",
        "worktree",
        "--allow-dirty-base",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_allow = subprocess.run(cmd_allow, capture_output=True, text=True, check=True)
    data_allow = json.loads(res_allow.stdout)
    assert data_allow["ok"] is True
    assert data_allow["status"] == "starting"
    dirty_file.unlink()


def test_worktree_and_branch_creation_and_base_final_commits(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "test-sess-001", "--exit-code", "0"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "update config"], cwd=str(sample_workspace), check=True)

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
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_start.stdout)["run_id"]

    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["branch"] == f"run/{run_id}"
    assert pathlib.Path(rec["worktree_path"]).is_dir()
    assert rec["base_commit"] is not None
    assert rec["final_commit"] is not None
    assert rec["final_commit"] != rec["base_commit"]
    assert rec["commits_after_base"] == 1
    assert rec["final_report"] is not None
    assert "## Final Report" in rec["final_report"]
    assert rec["session_id"] == "test-sess-001"


def test_invariant_failure_switched_branch(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--switch-branch", "rogue-branch"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "update config rogue"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res.stdout)["run_id"]

    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "failed"
    assert "branch" in (rec.get("invariant_error") or "").lower()
    assert rec.get("final_commit") is None


def test_invariant_failure_dirty_worktree(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--dirty-tree"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "update config dirty"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res.stdout)["run_id"]

    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "failed"
    assert "uncommitted changes" in (rec.get("invariant_error") or "").lower()
    assert rec.get("final_commit") is None


def test_mark_delivered_success_and_refusals(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "update config for mark-delivered"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_start.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"

    wt_path = pathlib.Path(rec["worktree_path"])

    # 1. Refusal: expect-task-hash mismatch
    cmd_hash_err = [
        str(BIN_AI_ORCH),
        "run",
        "mark-delivered",
        run_id,
        "--expect-task-hash",
        "badhash123",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_hash_err = subprocess.run(cmd_hash_err, capture_output=True, text=True, check=False)
    assert res_hash_err.returncode != 0
    assert "transition-failed" in json.loads(res_hash_err.stdout)["reason"]

    # 2. Refusal: branch mismatch
    subprocess.run(["git", "checkout", "HEAD~1"], cwd=str(wt_path), check=True, capture_output=True)
    cmd_b_err = [
        str(BIN_AI_ORCH),
        "run",
        "mark-delivered",
        run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_b_err = subprocess.run(cmd_b_err, capture_output=True, text=True, check=False)
    assert res_b_err.returncode != 0
    assert json.loads(res_b_err.stdout)["reason"] == "branch-mismatch"
    subprocess.run(["git", "checkout", f"run/{run_id}"], cwd=str(wt_path), check=True, capture_output=True)

    # 3. Refusal: dirty worktree
    dirty = wt_path / "dirty.tmp"
    dirty.write_text("dirty")
    res_dirty_err = subprocess.run(cmd_b_err, capture_output=True, text=True, check=False)
    assert res_dirty_err.returncode != 0
    assert json.loads(res_dirty_err.stdout)["reason"] == "worktree-dirty"
    dirty.unlink()

    # 4. Refusal: HEAD != final_commit
    extra = wt_path / "extra.txt"
    extra.write_text("extra")
    subprocess.run(["git", "add", "."], cwd=str(wt_path), check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "extra"], cwd=str(wt_path), check=True)
    res_head_err = subprocess.run(cmd_b_err, capture_output=True, text=True, check=False)
    assert res_head_err.returncode != 0
    assert json.loads(res_head_err.stdout)["reason"] == "head-mismatch"
    subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=str(wt_path), check=True)

    # 5. Success
    cmd_ok = [
        str(BIN_AI_ORCH),
        "run",
        "mark-delivered",
        run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_ok = subprocess.run(cmd_ok, capture_output=True, text=True, check=True)
    data_ok = json.loads(res_ok.stdout)
    assert data_ok["ok"] is True
    assert data_ok["state"] == "delivered"

    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    assert "state: delivered" in task_file.read_text(encoding="utf-8")


def test_verify_in_detached_worktree_at_final_commit(sample_workspace: pathlib.Path):
    # Set task to delivered
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    orig_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(orig_text.replace("state: open", "state: delivered"), encoding="utf-8")

    # Configure claude headless
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.claude.headless]\nallowed_tools = ["test"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg verify"], cwd=str(sample_workspace), check=True)

    cmd_verify = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--tool",
        "claude",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_v = subprocess.run(cmd_verify, capture_output=True, text=True, check=True)
    v_run_id = json.loads(res_v.stdout)["run_id"]

    v_rec = wait_for_terminal(sample_workspace, v_run_id)
    assert v_rec["status"] == "succeeded"
    assert v_rec["mode"] == "verify"
    assert v_rec["branch"] is None
    assert v_rec["worktree_removed"] is True
    assert not pathlib.Path(v_rec["worktree_path"]).exists()
    assert v_rec["verdict"] is not None
    assert v_rec["verdict"]["verdict"] == "verified"

    # Verify run cleanup on already-removed worktree is a no-op success (07.10)
    cmd_clean = [
        str(BIN_AI_ORCH),
        "run",
        "cleanup",
        v_run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_clean = subprocess.run(cmd_clean, capture_output=True, text=True, check=True)
    assert json.loads(res_clean.stdout)["cleaned"] is True

    # Verify run with --keep-worktree keeps worktree intact (07.10)
    cmd_verify_keep = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--tool",
        "claude",
        "--keep-worktree",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_vk = subprocess.run(cmd_verify_keep, capture_output=True, text=True, check=True)
    vk_run_id = json.loads(res_vk.stdout)["run_id"]
    vk_rec = wait_for_terminal(sample_workspace, vk_run_id)
    assert vk_rec["status"] == "succeeded"
    assert vk_rec["worktree_removed"] is False
    assert pathlib.Path(vk_rec["worktree_path"]).is_dir()


def test_independence_guard_and_modes(sample_workspace: pathlib.Path):
    # Set task to delivered state for verify mode tests
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    orig_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(orig_text.replace("state: open", "state: delivered"), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "delivered state for verify"], cwd=str(sample_workspace), check=True)

    # Task executor is kilo
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
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_same = subprocess.run(cmd_same, capture_output=True, text=True, check=False)
    assert res_same.returncode != 0
    assert json.loads(res_same.stdout)["reason"] == "independence-violation"

    # With allow-same-tool -> allowed
    cmd_same_allow = cmd_same + ["--allow-same-tool"]
    res_same_allow = subprocess.run(cmd_same_allow, capture_output=True, text=True, check=True)
    assert json.loads(res_same_allow.stdout)["ok"] is True

    # verification-mode: owner refusal
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    orig_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(orig_text.replace("- handoff: none", "- handoff: none\n- verification-mode: owner"), encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "owner mode"], cwd=str(sample_workspace), check=True)
    cmd_owner = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--tool",
        "claude",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_owner = subprocess.run(cmd_owner, capture_output=True, text=True, check=False)
    assert res_owner.returncode != 0
    assert json.loads(res_owner.stdout)["reason"] == "verification-mode-owner"

    # verification-mode: self refusal
    task_file.write_text(orig_text.replace("- handoff: none", "- handoff: none\n- verification-mode: self"), encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "self mode"], cwd=str(sample_workspace), check=True)
    res_self = subprocess.run(cmd_owner, capture_output=True, text=True, check=False)
    assert res_self.returncode != 0
    assert json.loads(res_self.stdout)["reason"] == "verification-mode-self"


def test_panel_aggregation_verified_and_bounced(sample_workspace: pathlib.Path):
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    task_file.write_text(
        "# T007\n\n- id: T007\n- title: T\n- category: server\n- priority: P2\n- state: delivered\n- executor: codex\n- verification-mode: panel\n\n## Verification\npytest\n",
        encoding="utf-8",
    )
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    proj_cfg.write_text(
        '[project]\nname = "p"\nprimary_orchestrator = "kilo"\n\n'
        '[verification]\ndefault_mode = "panel"\npanel_reviewers = ["kilo:deep-reasoning", "claude:deep-reasoning"]\n\n'
        f'[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n\n'
        f'[tools.claude.headless]\nallowed_tools = ["test"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "setup panel"], cwd=str(sample_workspace), check=True)

    # Launch panel (both verified)
    cmd_panel = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_p = subprocess.run(cmd_panel, capture_output=True, text=True, check=True)
    data_p = json.loads(res_p.stdout)
    assert data_p["ok"] is True
    panel_id = data_p["panel_id"]
    assert len(data_p["run_ids"]) == 2

    for rid in data_p["run_ids"]:
        wait_for_terminal(sample_workspace, rid)

    # Apply verdict for panel
    cmd_app = [
        str(BIN_AI_ORCH),
        "run",
        "apply-verdict",
        "--panel",
        panel_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_app = subprocess.run(cmd_app, capture_output=True, text=True, check=True)
    data_app = json.loads(res_app.stdout)
    assert data_app["ok"] is True
    assert data_app["state"] == "verified"
    assert "state: verified" in task_file.read_text(encoding="utf-8")

    # Test bounced in panel
    task_file.write_text(
        task_file.read_text(encoding="utf-8").replace("state: verified", "state: delivered"),
        encoding="utf-8",
    )
    proj_cfg.write_text(
        proj_cfg.read_text(encoding="utf-8").replace(
            f'argv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n',
            f'argv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "bounced", "--verdict-finding", "B1:major:security flaw"]\n',
            1
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "bounced panel cfg"], cwd=str(sample_workspace), check=True)

    res_p2 = subprocess.run(cmd_panel, capture_output=True, text=True, check=True)
    panel_id2 = json.loads(res_p2.stdout)["panel_id"]
    for rid in json.loads(res_p2.stdout)["run_ids"]:
        wait_for_terminal(sample_workspace, rid)

    cmd_app2 = [
        str(BIN_AI_ORCH),
        "run",
        "apply-verdict",
        "--panel",
        panel_id2,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_app2 = subprocess.run(cmd_app2, capture_output=True, text=True, check=True)
    data_app2 = json.loads(res_app2.stdout)
    assert data_app2["ok"] is True
    assert data_app2["state"] == "bounced"
    assert "state: bounced" in task_file.read_text(encoding="utf-8")


def test_verdict_only_from_final_assistant_message(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    # Run 1: earlier verdict only -> final is None
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--earlier-verdict", "verified"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg earlier verdict"], cwd=str(sample_workspace), check=True)

    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    task_file.write_text(
        "# T007\n\n- id: T007\n- title: T\n- category: server\n- priority: P2\n- state: delivered\n- executor: codex\n\n## Verification\npytest\n",
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--tool",
        "kilo",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res1 = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id1 = json.loads(res1.stdout)["run_id"]
    rec1 = wait_for_terminal(sample_workspace, run_id1)
    assert rec1["status"] == "succeeded"
    assert rec1.get("verdict") is None

    # Run 2: earlier bounced, final verified -> verdict is verified
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--earlier-verdict", "bounced", "--verdict", "verified"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg earlier bounced final verified"], cwd=str(sample_workspace), check=True)

    res2 = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id2 = json.loads(res2.stdout)["run_id"]
    rec2 = wait_for_terminal(sample_workspace, run_id2)
    assert rec2["status"] == "succeeded"
    assert rec2.get("verdict") is not None
    assert rec2["verdict"]["verdict"] == "verified"


def test_apply_verdict_refusals_task_changed_and_branch_drift(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report"]\n'
        f'[tools.claude.headless]\nallowed_tools = ["test"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg execute & verify"], cwd=str(sample_workspace), check=True)

    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    task_file.write_text(
        "# T007\n\n- id: T007\n- title: T\n- category: server\n- priority: P2\n- state: open\n- executor: kilo\n\n## Verification\npytest\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-am", "task file open"], cwd=str(sample_workspace), check=True)

    # 1. Execute run
    res_e = subprocess.run(
        [str(BIN_AI_ORCH), "run", "start", "--task", "T007", "--mode", "execute", "--isolation", "worktree", "--workspace", str(sample_workspace), "--json"],
        capture_output=True, text=True, check=True
    )
    exec_run_id = json.loads(res_e.stdout)["run_id"]
    exec_rec = wait_for_terminal(sample_workspace, exec_run_id)
    assert exec_rec["status"] == "succeeded"

    # Mark delivered
    subprocess.run([str(BIN_AI_ORCH), "run", "mark-delivered", exec_run_id, "--workspace", str(sample_workspace)], check=True)

    # 2. Verify run
    res_v = subprocess.run(
        [str(BIN_AI_ORCH), "run", "start", "--task", "T007", "--mode", "verify", "--tool", "claude", "--workspace", str(sample_workspace), "--json"],
        capture_output=True, text=True, check=True
    )
    ver_run_id = json.loads(res_v.stdout)["run_id"]
    ver_rec = wait_for_terminal(sample_workspace, ver_run_id)
    assert ver_rec["status"] == "succeeded"
    assert ver_rec["verdict"]["verdict"] == "verified"

    # Refusal 1: task file modified -> bundle hash drift
    orig_t_content = task_file.read_text(encoding="utf-8")
    task_file.write_text(orig_t_content + "\n<!-- task edit -->\n", encoding="utf-8")
    res_t_drift = subprocess.run(
        [str(BIN_AI_ORCH), "run", "apply-verdict", ver_run_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True, text=True, check=False
    )
    assert res_t_drift.returncode != 0
    assert json.loads(res_t_drift.stdout)["reason"] == "task-bundle-hash-drift"
    task_file.write_text(orig_t_content, encoding="utf-8")

    # Refusal 2: target branch advanced
    target_wt = pathlib.Path(exec_rec["worktree_path"])
    extra = target_wt / "advance.txt"
    extra.write_text("advance")
    subprocess.run(["git", "add", "."], cwd=str(target_wt), check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "advance branch"], cwd=str(target_wt), check=True)

    res_b_drift = subprocess.run(
        [str(BIN_AI_ORCH), "run", "apply-verdict", ver_run_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True, text=True, check=False
    )
    assert res_b_drift.returncode != 0
    assert json.loads(res_b_drift.stdout)["reason"] == "target-branch-head-drift"

    # Refusal 3: target branch reset
    subprocess.run(["git", "reset", "--hard", "HEAD~2"], cwd=str(target_wt), check=True)
    res_b_reset = subprocess.run(
        [str(BIN_AI_ORCH), "run", "apply-verdict", ver_run_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True, text=True, check=False
    )
    assert res_b_reset.returncode != 0
    assert json.loads(res_b_reset.stdout)["reason"] == "target-branch-head-drift"


def test_target_run_none_and_head_drift(sample_workspace: pathlib.Path):
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    task_file.write_text(
        "# T007\n\n- id: T007\n- title: T\n- category: server\n- priority: P2\n- state: delivered\n- executor: kilo\n\n## Verification\npytest\n",
        encoding="utf-8",
    )
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.claude.headless]\nallowed_tools = ["test"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "setup target run none"], cwd=str(sample_workspace), check=True)

    # Verify with target-run none
    cmd_v = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--tool",
        "claude",
        "--target-run",
        "none",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_v = subprocess.run(cmd_v, capture_output=True, text=True, check=True)
    v_id = json.loads(res_v.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, v_id)
    assert rec["status"] == "succeeded"

    # Make new commit in target repo -> HEAD drifts
    drift_f = sample_workspace / "drift.txt"
    drift_f.write_text("drift")
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "drift commit"], cwd=str(sample_workspace), check=True)

    cmd_app = [
        str(BIN_AI_ORCH),
        "run",
        "apply-verdict",
        v_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_app = subprocess.run(cmd_app, capture_output=True, text=True, check=False)
    assert res_app.returncode != 0
    assert json.loads(res_app.stdout)["reason"] == "target-head-drift"


def test_continue_invariants_and_refusals(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "sess-init"]\n'
        f'resume_argv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "{{session_id}}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg continue"], cwd=str(sample_workspace), check=True)

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
    res1 = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    r1_id = json.loads(res1.stdout)["run_id"]
    rec1 = wait_for_terminal(sample_workspace, r1_id)
    assert rec1["status"] == "succeeded"

    # Refusal: passing tool flag
    cmd_lock = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--continue",
        r1_id,
        "--tool",
        "claude",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_lock = subprocess.run(cmd_lock, capture_output=True, text=True, check=False)
    assert res_lock.returncode != 0
    assert json.loads(res_lock.stdout)["reason"] == "continue-locked-fields"

    # Refusal: missing session_id
    rec1_no_sid = dict(rec1)
    rec1_no_sid["run_id"] = "20261017-000000-T007-kilo-9999"
    rec1_no_sid["session_id"] = None
    save_run_record(sample_workspace, rec1_no_sid)
    cmd_no_sid = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--continue",
        rec1_no_sid["run_id"],
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_no_sid = subprocess.run(cmd_no_sid, capture_output=True, text=True, check=False)
    assert res_no_sid.returncode != 0
    assert json.loads(res_no_sid.stdout)["reason"] == "missing-session-id"

    # Success: valid continue
    cmd_cont = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--continue",
        r1_id,
        "--instructions",
        "Follow up step",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_cont = subprocess.run(cmd_cont, capture_output=True, text=True, check=True)
    data_cont = json.loads(res_cont.stdout)
    assert data_cont["ok"] is True
    assert data_cont["continued_from"] == r1_id
    r2_id = data_cont["run_id"]
    rec2 = wait_for_terminal(sample_workspace, r2_id)
    assert rec2["status"] == "succeeded"
    assert rec2["continued_from"] == r1_id
    assert rec2["session_id"] == "sess-init"
    assert rec2["worktree_path"] == rec1["worktree_path"]


def test_cleanup_invariants_and_refusals(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg cleanup"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_s = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_s.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"

    wt_path = pathlib.Path(rec["worktree_path"])
    assert wt_path.is_dir()

    # Refusal: branch not merged
    cmd_clean = [
        str(BIN_AI_ORCH),
        "run",
        "cleanup",
        run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_clean_unmerged = subprocess.run(cmd_clean, capture_output=True, text=True, check=False)
    assert res_clean_unmerged.returncode != 0
    assert json.loads(res_clean_unmerged.stdout)["reason"] == "branch-not-merged"

    # Dry-run
    cmd_dry = cmd_clean + ["--dry-run"]
    res_dry = subprocess.run(cmd_dry, capture_output=True, text=True, check=True)
    assert json.loads(res_dry.stdout)["dry_run"] is True
    assert wt_path.is_dir()

    # Refusal: active run in continuation chain
    active_rec = dict(rec)
    active_rec["run_id"] = "20261017-000000-T007-kilo-7777"
    active_rec["status"] = "running"
    my_pid = os.getpid()
    active_rec["supervisor"] = {"pid": my_pid, "start_time": get_process_start_time(my_pid)}
    save_run_record(sample_workspace, active_rec)
    res_act = subprocess.run(cmd_clean + ["--discard"], capture_output=True, text=True, check=False)
    assert res_act.returncode != 0
    assert json.loads(res_act.stdout)["reason"] == "active-chain-run"

    # Remove active run
    active_rec["status"] = "failed"
    save_run_record(sample_workspace, active_rec)

    # Success with --discard
    res_ok = subprocess.run(cmd_clean + ["--discard"], capture_output=True, text=True, check=True)
    assert json.loads(res_ok.stdout)["ok"] is True
    assert not wt_path.exists()

    # Check record still exists
    kept_rec = load_run_record(sample_workspace, run_id)
    assert kept_rec is not None
    assert kept_rec.get("cleaned_at") is not None


# ---------------------------------------------------------------------------
# Task 07.10 Tests: Supervisor Questions Integration
# ---------------------------------------------------------------------------

def test_supervisor_files_valid_question_block(sample_workspace: pathlib.Path):
    q_data = {
        "question": "Which cache backend should be used?",
        "context": "Redis and Memcached are both viable options for session storage.",
        "options": [
            {"label": "A", "title": "Redis", "consequence": "Persistence supported."},
            {"label": "B", "title": "Memcached", "consequence": "Simple in-memory caching."},
        ],
        "recommended": "A",
        "open_answer": False,
    }
    q_json = json.dumps(q_data)

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--question", {json.dumps(q_json)}]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg question test"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_s = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_s.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"

    assert len(rec.get("questions", [])) == 1
    assert rec.get("question_errors", []) == []
    q_id = rec["questions"][0]

    q_file = sample_workspace / "tasks" / "questions" / f"{q_id}-which-cache-backend-should-be-used.md"
    assert q_file.is_file()
    content = q_file.read_text(encoding="utf-8")
    assert f"- id: {q_id}" in content
    assert "- question: Which cache backend should be used?" in content
    assert "- status: open" in content
    assert "- blocks: T007 (in progress)" in content
    assert "- decider: owner" in content
    assert "- asked-by: kilo:bulk-execution" in content
    assert f"- origin-run: {run_id}" in content
    assert "- open-answer: no" in content
    assert "- recommended: A" in content
    assert "Redis and Memcached are both viable" in content
    assert "- **A** — Redis: Persistence supported." in content
    assert "- **B** — Memcached: Simple in-memory caching." in content

    # Task moved to waiting
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    t_content = task_file.read_text(encoding="utf-8")
    assert "state: waiting" in t_content
    assert f"decider: {q_id}" in t_content


def test_supervisor_forces_run_task_in_blocks_ignoring_block_values(sample_workspace: pathlib.Path):
    q_data = {
        "question": "Which protocol version should be used?",
        "context": "Protocol v1 vs v2 context.",
        "options": [
            {"label": "A", "title": "v1", "consequence": "Legacy"},
            {"label": "B", "title": "v2", "consequence": "Modern"},
        ],
        "recommended": "B",
        "blocks": ["T999"],
        "asked-by": "untrusted:role",
        "origin-run": "fake-run-id",
        "decider": "somebody-else",
    }
    q_json = json.dumps(q_data)

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--question", {json.dumps(q_json)}]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg question force test"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_s = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_s.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"

    assert len(rec.get("questions", [])) == 1
    q_id = rec["questions"][0]

    q_file = sample_workspace / "tasks" / "questions" / f"{q_id}-which-protocol-version-should-be-used.md"
    assert q_file.is_file()
    content = q_file.read_text(encoding="utf-8")
    # Must be forced to the run's task T007, supervisor tool:profile, run_id, and owner
    assert "- blocks: T007 (in progress)" in content
    assert "T999" not in content
    assert "- asked-by: kilo:bulk-execution" in content
    assert "untrusted:role" not in content
    assert f"- origin-run: {run_id}" in content
    assert "fake-run-id" not in content
    assert "- decider: owner" in content
    assert "somebody-else" not in content

    # Task T007 is waiting
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    t_content = task_file.read_text(encoding="utf-8")
    assert "state: waiting" in t_content
    assert f"decider: {q_id}" in t_content


def test_supervisor_handles_malformed_question_json(sample_workspace: pathlib.Path):
    malformed_raw = '{"question": "Broken JSON...'

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--question", {json.dumps(malformed_raw)}]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg malformed question test"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_s = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_s.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"

    assert rec.get("questions") == []
    errors = rec.get("question_errors", [])
    assert len(errors) == 1
    assert errors[0]["index"] == 0
    assert "Invalid JSON" in errors[0]["error"]

    # No question files created
    q_dir = sample_workspace / "tasks" / "questions"
    if q_dir.is_dir():
        assert list(q_dir.glob("Q*.md")) == []

    # Task was NOT moved to waiting
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    t_content = task_file.read_text(encoding="utf-8")
    assert "state: waiting" not in t_content


def test_supervisor_ignores_question_in_earlier_message(sample_workspace: pathlib.Path):
    q_data = {
        "question": "Should this earlier question be ignored?",
        "context": "Context for earlier question.",
        "options": [
            {"label": "A", "title": "Yes", "consequence": "Ignored"},
            {"label": "B", "title": "No", "consequence": "Error"},
        ],
        "recommended": "A",
    }
    q_json = json.dumps(q_data)

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--earlier-question", {json.dumps(q_json)}]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg earlier question test"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_s = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_s.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"

    assert rec.get("questions") == []
    assert rec.get("question_errors", []) == []

    # No question files created
    q_dir = sample_workspace / "tasks" / "questions"
    if q_dir.is_dir():
        assert list(q_dir.glob("Q*.md")) == []

    # Task was NOT moved to waiting
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    t_content = task_file.read_text(encoding="utf-8")
    assert "state: waiting" not in t_content


def test_supervisor_multiple_questions_in_final_message(sample_workspace: pathlib.Path):
    q1 = {
        "question": "Which storage engine?",
        "context": "Storage engine context.",
        "options": [
            {"label": "A", "title": "Postgres", "consequence": "SQL"},
            {"label": "B", "title": "Mongo", "consequence": "NoSQL"},
        ],
        "recommended": "A",
    }
    q2 = {
        "question": "Which auth provider?",
        "context": "Auth provider context.",
        "options": [
            {"label": "A", "title": "OAuth", "consequence": "Standard"},
            {"label": "B", "title": "SAML", "consequence": "Enterprise"},
        ],
        "recommended": "A",
    }

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--question", {json.dumps(json.dumps(q1))}, "--question", {json.dumps(json.dumps(q2))}]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg multiple questions test"], cwd=str(sample_workspace), check=True)

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
        "--force",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_s = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_s.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"

    assert len(rec.get("questions", [])) == 2
    q1_id, q2_id = rec["questions"]
    assert q1_id != q2_id

    # Both question files exist
    assert (sample_workspace / "tasks" / "questions" / f"{q1_id}-which-storage-engine.md").is_file()
    assert (sample_workspace / "tasks" / "questions" / f"{q2_id}-which-auth-provider.md").is_file()

    # Task decider has both questions
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    t_content = task_file.read_text(encoding="utf-8")
    assert "state: waiting" in t_content
    assert f"decider: {q1_id}, {q2_id}" in t_content


