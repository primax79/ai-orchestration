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
import re
import shutil
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
    discover_emergent_tasks,
    load_run_record,
    list_run_records,
    ensure_git_exclude,
    run_lock,
    get_allowed_modes_for_state,
    get_default_mode_for_state,
    ALLOWED_MODES_PER_STATE,
    TERMINAL_STATES,
    reconcile,
    get_process_start_time,
    is_process_alive,
    kill_process_group,
    resolve_claude_allowed_tools,
    check_claude_allowed_tools,
    DEFAULT_CLAUDE_ALLOWED_TOOLS,
    resolve_kilo_agent,
    check_kilo_agent,
    DEFAULT_KILO_AGENTS,
    resolve_task_by_id,
)

SCRIPT = pathlib.Path(__file__).resolve().parent / "orchestration_runs.py"
BIN_AI_ORCH = pathlib.Path(__file__).resolve().parent.parent / "bin" / "ai-orch"
STUB_AGENT = pathlib.Path(__file__).resolve().parent / "fixtures" / "runs" / "stub_agent.py"


@pytest.fixture(autouse=True)
def _no_real_agent_clis(tmp_path_factory, monkeypatch):
    """Tests must never reach the real kilo/claude/codex CLIs (they call real models).

    Fake executables that fail loudly shadow them on PATH for every test; a test
    that needs an agent configures `[tools.<t>.headless] argv` with STUB_AGENT.
    """
    fake_bin = tmp_path_factory.mktemp("fake-agent-clis")
    for name in ("kilo", "claude", "codex"):
        exe = fake_bin / name
        # Availability probes (--version, `kilo models`) answer; anything that would run an agent fails.
        exe.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            f'  --version) echo "{name} 0.0.0-test-fake"; exit 0 ;;\n'
            '  models) echo "google/gemini-3.8-flash"; exit 0 ;;\n'
            "esac\n"
            f"echo 'REAL {name} CLI CALLED FROM A TEST: configure a stub argv' >&2\n"
            "exit 97\n"
        )
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")


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


def test_check_task_id_accepts_emergent_and_child_and_initiative():
    # Valid emergent IDs
    for tid in ("T001", "T007", "T1234", "T001.1", "T001.2.1"):
        ok, err = check_task_id(tid)
        assert ok is True and err is None

    # Initiative subtasks (NN.T) supported in 11.2
    for init_id in ("07.2", "01.T1", "12.T3", "08.1"):
        ok, err = check_task_id(init_id)
        assert ok is True and err is None

    # Placeholder NN.T refused
    ok, err = check_task_id("NN.T")
    assert ok is False
    assert "placeholder" in (err or "").lower()

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


def test_tool_availability_default_version_probe_with_fake_binary(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Explicit opt-out from AI_ORCH_TEST_CLI_VERSIONS to test real subprocess version probing against a fake binary."""
    monkeypatch.delenv("AI_ORCH_TEST_CLI_VERSIONS", raising=False)
    fake_kilo = tmp_path / "kilo"
    fake_kilo.write_text("#!/bin/sh\necho 'kilo 9.8.7-custom-fake'\nexit 0\n", encoding="utf-8")
    fake_kilo.chmod(0o755)

    ok, ver, err = check_tool_availability(
        "kilo",
        {"enabled": True, "cli_command": "kilo"},
        which_fn=lambda cmd: str(fake_kilo),
    )
    assert ok is True
    assert ver == "kilo 9.8.7-custom-fake"
    assert err is None

    # Failing binary returns exit code error
    fake_kilo.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    ok_fail, ver_fail, err_fail = check_tool_availability(
        "kilo",
        {"enabled": True, "cli_command": "kilo"},
        which_fn=lambda cmd: str(fake_kilo),
    )
    assert ok_fail is False
    assert ver_fail is None
    assert "returned exit code 99" in (err_fail or "")



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
    subprocess.run(["git", "status"], cwd=str(ws), check=True, capture_output=True)
    return ws


def get_tree_map(root: pathlib.Path) -> dict[str, bytes]:
    res = {}
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = pathlib.Path(dirpath) / fname
            rel = fpath.relative_to(root).as_posix()
            try:
                res[rel] = fpath.read_bytes()
            except OSError:
                pass
    return res


def test_preview_side_effect_free(sample_workspace: pathlib.Path):
    map_before = get_tree_map(sample_workspace)
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
    map_after = get_tree_map(sample_workspace)
    tree_hash_after = compute_tree_hash(sample_workspace)
    if tree_hash_before != tree_hash_after:
        added = set(map_after) - set(map_before)
        removed = set(map_before) - set(map_after)
        modified = [k for k in set(map_before) & set(map_after) if map_before[k] != map_after[k]]
        raise AssertionError(f"Tree hash differs! added={added}, removed={removed}, modified={modified}")
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
    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
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

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
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

    gc_pid = None
    agent_pid = None
    try:
        # Wait for grandchild PID to be written and supervisor to record agent pid/pgid/start_time
        deadline = time.time() + 30.0
        record = None
        while time.time() < deadline:
            if gc_pid_file.is_file() and gc_pid_file.read_text(encoding="utf-8").strip():
                record = load_run_record(sample_workspace, run_id)
                agent = (record or {}).get("agent", {})
                if agent.get("pid") and agent.get("pgid") and agent.get("start_time"):
                    break
            time.sleep(0.1)

        assert gc_pid_file.is_file()
        gc_pid = int(gc_pid_file.read_text(encoding="utf-8").strip())

        # Get agent pid
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
        deadline = time.time() + 30.0
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
    finally:
        for p in (gc_pid, agent_pid):
            if p:
                try:
                    os.kill(p, signal.SIGKILL)
                except OSError:
                    pass


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

    gc_pid = None
    agent_pid = None
    sup_pid = None
    try:
        # Wait for running
        deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
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
    finally:
        for p in (gc_pid, agent_pid, sup_pid):
            if p:
                try:
                    os.kill(p, signal.SIGKILL)
                except OSError:
                    pass


def test_reconcile_pid_reuse_simulated_does_not_kill(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")

    fifo_path = sample_workspace / "helper.fifo"
    os.mkfifo(fifo_path)
    fifo_fd = os.open(str(fifo_path), os.O_RDWR)

    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "-c", "import sys; open(sys.argv[1], \\"rb\\").read()", "{fifo_path}"]\n',
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

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    record = None
    while time.time() < deadline:
        record = load_run_record(sample_workspace, run_id)
        if record and record.get("status") == "running":
            break
        time.sleep(0.1)

    assert record is not None
    sup_pid = record["supervisor"]["pid"]
    agent_pid = record["agent"]["pid"]

    try:
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
    finally:
        try:
            os.close(fifo_fd)
        except Exception:
            pass
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

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    record = None
    while time.time() < deadline:
        record = load_run_record(sample_workspace, run_id)
        if record and record.get("status") == "running":
            break
        time.sleep(0.1)

    assert record is not None
    agent_pid = record["agent"]["pid"]

    try:
        # Check ps -o args= -p <agent_pid>
        res_ps = subprocess.run(["ps", "-o", "args=", "-p", str(agent_pid)], capture_output=True, text=True, check=True)
        ps_output = res_ps.stdout
        assert canary not in ps_output
    finally:
        # Cancel to cleanup
        subprocess.run([str(BIN_AI_ORCH), "run", "cancel", run_id, "--workspace", str(sample_workspace)], check=False)
        try:
            os.kill(agent_pid, signal.SIGKILL)
        except OSError:
            pass


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

    run_id = None
    try:
        succ_data = json.loads(successful.stdout)
        assert succ_data["ok"] is True
        run_id = succ_data["run_id"]

        fail_data = json.loads(failed.stdout)
        assert fail_data["ok"] is False
        assert fail_data["reason"] == "same-task-active"
    finally:
        # Cleanup
        if run_id:
            subprocess.run([str(BIN_AI_ORCH), "run", "cancel", run_id, "--workspace", str(sample_workspace)], check=False)


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

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
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
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    proj_cfg.write_text(
        proj_cfg.read_text(encoding="utf-8")
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "30"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "stub agent"], cwd=str(sample_workspace), check=True, capture_output=True)
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

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    while time.time() < deadline:
        content = task_file.read_text(encoding="utf-8")
        if "state: in progress" in content:
            break
        time.sleep(0.1)

    final_content = task_file.read_text(encoding="utf-8")
    assert "state: in progress" in final_content


def wait_for_terminal(ws: pathlib.Path, run_id: str, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = load_run_record(ws, run_id)
        if rec and rec.get("status") in ("succeeded", "failed", "cancelled", "lost"):
            return rec
        time.sleep(0.1)
    raise TimeoutError(f"Run {run_id} did not reach terminal state within {timeout}s")


def test_dirty_repo_refusal_and_allow_dirty_base(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    proj_cfg.write_text(
        proj_cfg.read_text(encoding="utf-8")
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--exit-code", "0"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "stub agent"], cwd=str(sample_workspace), check=True, capture_output=True)
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


# ---------------------------------------------------------------------------
# Task 09.4 — Agent Triage Mode, Proposal Parsing, and Accept-Triage
# ---------------------------------------------------------------------------

def test_triage_permission_list_contains_no_write_tools():
    """Verify that DEFAULT_CLAUDE_ALLOWED_TOOLS['triage'] contains no write tools."""
    assert "triage" in DEFAULT_CLAUDE_ALLOWED_TOOLS
    tools = DEFAULT_CLAUDE_ALLOWED_TOOLS["triage"]
    assert "Read" in tools
    assert "Glob" in tools
    assert "Grep" in tools

    # Strictly forbidden write tools
    forbidden = ["Edit", "Write", "Bash(git add:*)", "Bash(git commit:*)", "Bash(pytest:*)", "Bash(npm test:*)"]
    for f in forbidden:
        assert f not in tools, f"Write tool '{f}' must not be in triage permissions"

    # All Bash commands must be read-only
    for t in tools:
        if t.startswith("Bash("):
            cmd_name = t[5:-1].strip()
            assert any(cmd_name.startswith(ro) for ro in ("git status", "git diff", "git log", "git show")), (
                f"Bash tool '{t}' is not recognized as a read-only command"
            )


def test_triage_preview_and_adapter_flags(sample_workspace: pathlib.Path):
    """Test preview for triage mode: prompt contents, no worktree, read-only tools, attachment passing."""
    tasks_dir = sample_workspace / "tasks"

    # Create note N001
    res = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "UI button alignment bug",
            "--kind",
            "bug",
            "--body",
            "Button overlaps header on mobile screens.",
            "--about",
            "frontend/components/button.tsx",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res.stdout)["id"]

    # Attach an image
    img = sample_workspace / "screenshot.png"
    img.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "attach",
            note_id,
            "--file",
            str(img),
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # Preview with --note
    res_p1 = subprocess.run(
        [str(BIN_AI_ORCH), "run", "preview", "--note", note_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    prev1 = json.loads(res_p1.stdout)
    assert prev1["ok"] is True
    assert prev1["planned_worktree"] is None
    assert prev1["planned_branch"] is None
    assert prev1["cwd"] == str(sample_workspace)

    prompt = prev1["prompt"]
    assert note_id in prompt
    assert "UI button alignment bug" in prompt
    assert "Button overlaps header on mobile screens." in prompt
    assert "01-screenshot.png" in prompt
    assert "frontend/components/button.tsx" in prompt
    assert "tasks/00-INDEX.md" in prompt
    assert "plugins/architect-side/skills/task-pipeline/SKILL.md" in prompt
    assert "```ai-orch-triage" in prompt

    # Preview with --task N001 also works consistently
    res_p2 = subprocess.run(
        [str(BIN_AI_ORCH), "run", "preview", "--task", note_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    prev2 = json.loads(res_p2.stdout)
    assert prev2["ok"] is True
    assert prev2["plan_hash"] == prev1["plan_hash"]

    # Preview with tool=kilo: verify -f <attachment> in argv
    res_kilo = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "preview",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    prev_kilo = json.loads(res_kilo.stdout)
    argv_kilo = prev_kilo["argv_display"]
    assert "-f" in argv_kilo
    # An attachment path should appear after -f
    f_indices = [i for i, x in enumerate(argv_kilo) if x == "-f"]
    assert len(f_indices) >= 2  # prompt file and attachment
    assert any("01-screenshot.png" in argv_kilo[i + 1] for i in f_indices)

    # Preview with tool=codex: verify -i <attachment> in argv
    res_codex = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "preview",
            "--note",
            note_id,
            "--tool",
            "codex",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    prev_codex = json.loads(res_codex.stdout)
    argv_codex = prev_codex["argv_display"]
    assert "-i" in argv_codex
    i_indices = [i for i, x in enumerate(argv_codex) if x == "-i"]
    assert any("01-screenshot.png" in argv_codex[idx + 1] for idx in i_indices)
    assert "-s" in argv_codex
    s_idx = argv_codex.index("-s")
    assert argv_codex[s_idx + 1] == "read-only"


def test_triage_rejects_task_target_and_non_triage_rejects_note_target(sample_workspace: pathlib.Path):
    """Test target validation: triage requires note (N###), non-triage requires task (T###)."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Target validation note",
            "--body",
            "Body",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    # T### task cannot be triaged
    res_t = subprocess.run(
        [str(BIN_AI_ORCH), "run", "preview", "--task", "T007", "--mode", "triage", "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_t.returncode != 0
    data_t = json.loads(res_t.stdout)
    assert data_t["reason"] == "invalid-target-for-triage"

    # N### note cannot be executed, verified, or orchestrated
    for bad_mode in ("execute", "verify", "orchestrate"):
        res_n = subprocess.run(
            [str(BIN_AI_ORCH), "run", "preview", "--note", note_id, "--mode", bad_mode, "--workspace", str(sample_workspace), "--json"],
            capture_output=True,
            text=True,
        )
        assert res_n.returncode != 0
        data_n = json.loads(res_n.stdout)
        assert data_n["reason"] == "invalid-mode-for-note"


def test_triage_options_command(sample_workspace: pathlib.Path):
    """Test options command for an inbox note."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Options test note",
            "--body",
            "Body",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    res_opt = subprocess.run(
        [str(BIN_AI_ORCH), "run", "options", "--note", note_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    opt_data = json.loads(res_opt.stdout)
    assert opt_data["ok"] is True
    assert opt_data["allowed_modes"] == ["triage"]
    assert opt_data["default_mode"] == "triage"
    assert "triage" in opt_data["resolved_defaults"]
    assert opt_data["resolved_defaults"]["triage"]["profile"] == "deep-reasoning"


def test_triage_valid_proposal_stored(sample_workspace: pathlib.Path):
    """Test that a triage run completes and stores triage-proposal.json with pending status."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Memory leak in session manager",
            "--body",
            "Analyze and fix memory leak",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proposal = {
        "tasks": [
            {
                "title": "Fix session cache leak",
                "category": "server",
                "priority": "P1",
                "priority_reason": "High memory consumption",
                "goal": "Introduce LRU cache for expired sessions",
                "steps": ["Implement LRU cache", "Add eviction unit test"],
                "verification": ["Run pytest tests/cache"],
            },
            {
                "title": "Add session lifecycle metrics",
                "category": "server",
                "priority": "P2",
                "priority_reason": "Monitoring improvement",
                "goal": "Emit session open and close metrics",
                "steps": ["Add prometheus counter", "Test metrics emission"],
                "verification": ["Run pytest tests/metrics"],
            },
        ],
        "updates": [],
        "spec": None,
        "questions": [],
    }

    mock_agent = sample_workspace / "triage_agent.py"
    msg = "Triage recommendations:\n```ai-orch-triage\n" + json.dumps(proposal) + "\n```\n"
    evt = {"type": "message", "role": "assistant", "content": msg}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure triage agent"], cwd=str(sample_workspace), check=True)

    # Count task files before run
    tasks_before = list(tasks_dir.glob("*/*.md"))

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["proposal_status"] == "pending"

    # Triage proposal file exists and matches
    prop_path = sample_workspace / ".ai-orchestration" / "runs" / run_id / "triage-proposal.json"
    assert prop_path.is_file()
    saved_prop = json.loads(prop_path.read_text(encoding="utf-8"))
    assert len(saved_prop["tasks"]) == 2
    assert saved_prop["tasks"][0]["title"] == "Fix session cache leak"

    # MANDATORY RULE 6: No writes to tasks/ during the run itself
    tasks_after = list(tasks_dir.glob("*/*.md"))
    assert len(tasks_after) == len(tasks_before), "No task files should be written to tasks/ during the triage run"


def test_accept_triage_creates_tasks_and_resolves_note(sample_workspace: pathlib.Path):
    """Test accept-triage: creates tasks in tasks/ and resolves inbox note to analyzed/."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Accept triage test note",
            "--body",
            "Propose new task",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proposal = {
        "tasks": [
            {
                "title": "Implement auth token refresh",
                "category": "server",
                "priority": "P1",
                "priority_reason": "Security requirement",
                "goal": "Refresh tokens before expiration",
                "steps": ["Implement refresh endpoint", "Add refresh test"],
                "verification": ["Run pytest tests/token_refresh"],
            }
        ],
        "updates": [],
        "spec": None,
        "questions": [],
    }

    mock_agent = sample_workspace / "accept_agent.py"
    msg = "Triage recommendations:\n```ai-orch-triage\n" + json.dumps(proposal) + "\n```\n"
    evt = {"type": "message", "role": "assistant", "content": msg}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure accept agent"], cwd=str(sample_workspace), check=True)

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["proposal_status"] == "pending"

    # Accept triage
    res_acc = subprocess.run(
        [str(BIN_AI_ORCH), "run", "accept-triage", run_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    acc_data = json.loads(res_acc.stdout)
    assert acc_data["ok"] is True
    assert acc_data["proposal_status"] == "accepted"
    new_task_ids = acc_data["tasks_created"]
    assert len(new_task_ids) == 1
    new_tid = new_task_ids[0]

    # Verify task file exists on disk
    task_files = list((tasks_dir / "server").glob(f"{new_tid}-*.md"))
    assert len(task_files) == 1
    task_content = task_files[0].read_text(encoding="utf-8")
    assert "## Goal\n\nRefresh tokens before expiration" in task_content
    assert "- [ ] Implement refresh endpoint" in task_content
    assert "- [ ] Run pytest tests/token_refresh" in task_content
    assert f"sources: _inbox/analyzed/" in task_content

    # Validate tasks tree is clean
    res_val = subprocess.run(
        [str(BIN_AI_ORCH), "tasks", "validate", "--tasks-dir", str(tasks_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    val_data = json.loads(res_val.stdout)
    assert val_data["errors"] == []

    # Verify note was moved to analyzed/ and resolved
    analyzed_notes = list((tasks_dir / "_inbox" / "analyzed").glob("*/note.md"))
    assert len(analyzed_notes) >= 1
    note_content = next(p.read_text(encoding="utf-8") for p in analyzed_notes if f"id: {note_id}" in p.read_text(encoding="utf-8"))
    assert "status: processed" in note_content
    assert f"produced: {new_tid}" in note_content
    assert f"processed-by: kilo:deep-reasoning (run {run_id})" in note_content


def test_accept_triage_only_subset(sample_workspace: pathlib.Path):
    """Test accept-triage --only creates only the selected subset of tasks."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Subset test note",
            "--body",
            "Propose 3 tasks",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proposal = {
        "tasks": [
            {
                "title": "Task Alpha",
                "category": "server",
                "priority": "P1",
                "priority_reason": "Alpha reason",
                "goal": "Goal Alpha",
                "steps": ["Step A"],
                "verification": ["Ver A"],
            },
            {
                "title": "Task Beta",
                "category": "server",
                "priority": "P2",
                "priority_reason": "Beta reason",
                "goal": "Goal Beta",
                "steps": ["Step B"],
                "verification": ["Ver B"],
            },
            {
                "title": "Task Gamma",
                "category": "server",
                "priority": "P3",
                "priority_reason": "Gamma reason",
                "goal": "Goal Gamma",
                "steps": ["Step C"],
                "verification": ["Ver C"],
            },
        ],
        "updates": [],
        "spec": None,
        "questions": [],
    }

    mock_agent = sample_workspace / "subset_agent.py"
    msg = "```ai-orch-triage\n" + json.dumps(proposal) + "\n```\n"
    evt = {"type": "message", "role": "assistant", "content": msg}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure subset agent"], cwd=str(sample_workspace), check=True)

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["proposal_status"] == "pending"

    # Accept only index 0 and index 2 (Task Alpha and Task Gamma)
    res_acc = subprocess.run(
        [str(BIN_AI_ORCH), "run", "accept-triage", run_id, "--only", "0,2", "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    acc_data = json.loads(res_acc.stdout)
    assert acc_data["ok"] is True
    created = acc_data["tasks_created"]
    assert len(created) == 2

    # Task Beta should NOT have been created
    all_server_files = [p.name for p in (tasks_dir / "server").glob("*.md")]
    assert not any("task-beta" in name.lower() for name in all_server_files)
    assert any("task-alpha" in name.lower() for name in all_server_files)
    assert any("task-gamma" in name.lower() for name in all_server_files)

    # Note resolved with only the 2 created task IDs
    assert acc_data["produced"] == f"{created[0]}, {created[1]}"


def test_accept_triage_refuses_stale_note_hash(sample_workspace: pathlib.Path):
    """Test that accept-triage refuses when note content changed or --expect-note-hash mismatches."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Stale hash test note",
            "--body",
            "Original content",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proposal = {
        "tasks": [
            {
                "title": "Task for stale test",
                "category": "server",
                "priority": "P2",
                "priority_reason": "Reason",
                "goal": "Goal",
                "steps": ["Step"],
                "verification": ["Ver"],
            }
        ],
        "updates": [],
        "spec": None,
        "questions": [],
    }

    mock_agent = sample_workspace / "stale_agent.py"
    msg = "```ai-orch-triage\n" + json.dumps(proposal) + "\n```\n"
    evt = {"type": "message", "role": "assistant", "content": msg}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure stale agent"], cwd=str(sample_workspace), check=True)

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["proposal_status"] == "pending"

    # Test wrong expect-note-hash
    res_mismatch = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "accept-triage",
            run_id,
            "--expect-note-hash",
            "0000000000000000000000000000000000000000000000000000000000000000",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert res_mismatch.returncode != 0
    data_mismatch = json.loads(res_mismatch.stdout)
    assert data_mismatch["reason"] == "note-hash-mismatch"

    # Modify note body to simulate external modification
    note_files = list((tasks_dir / "_inbox" / "to-analyze").glob("*/note.md"))
    target_note_file = next(p for p in note_files if f"id: {note_id}" in p.read_text(encoding="utf-8"))
    target_note_file.write_text(target_note_file.read_text(encoding="utf-8") + "\nEdited after run.", encoding="utf-8")

    # Accept should now be refused with stale-note-hash
    res_stale = subprocess.run(
        [str(BIN_AI_ORCH), "run", "accept-triage", run_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_stale.returncode != 0
    data_stale = json.loads(res_stale.stdout)
    assert data_stale["reason"] == "stale-note-hash"


def test_accept_triage_with_edits_file(sample_workspace: pathlib.Path):
    """Test accept-triage --edits-file overrides task fields and land in created task (Task 09.10)."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Edits test note",
            "--body",
            "Propose task to be edited",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proposal = {
        "tasks": [
            {
                "title": "Original Task Title",
                "category": "server",
                "priority": "P2",
                "priority_reason": "Original reason",
                "goal": "Original goal statement",
                "steps": ["Original step 1", "Original step 2"],
                "verification": ["Original ver 1"],
            }
        ],
        "updates": [],
        "spec": None,
        "questions": [],
    }

    mock_agent = sample_workspace / "edits_agent.py"
    msg = "Triage recommendations:\n```ai-orch-triage\n" + json.dumps(proposal) + "\n```\n"
    evt = {"type": "message", "role": "assistant", "content": msg}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure edits agent"], cwd=str(sample_workspace), check=True)

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["proposal_status"] == "pending"

    # Write edits file
    edits_file = sample_workspace / "task_edits.json"
    edits_payload = {
        "0": {
            "title": "Edited Task Title",
            "priority": "P0",
            "priority_reason": "Urgent security audit requirement",
            "goal": "Edited goal statement",
            "steps": ["Step 1 edited", "Step 2 edited"],
            "verification": ["Verify 1 edited"],
            "kind": "feature",
            "labels": ["security", "auth"],
        }
    }
    edits_file.write_text(json.dumps(edits_payload, indent=2), encoding="utf-8")

    # Accept triage with --edits-file
    res_acc = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "accept-triage",
            run_id,
            "--edits-file",
            str(edits_file),
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    acc_data = json.loads(res_acc.stdout)
    assert acc_data["ok"] is True
    assert acc_data["proposal_status"] == "accepted"
    assert "0" in acc_data["edits_applied"]
    assert acc_data["edits_applied"]["0"]["title"] == "Edited Task Title"
    assert acc_data["edits_applied"]["0"]["priority"] == "P0"

    new_task_ids = acc_data["tasks_created"]
    assert len(new_task_ids) == 1
    new_tid = new_task_ids[0]

    # Verify task file on disk has edited fields
    task_files = list((tasks_dir / "server").glob(f"{new_tid}-*.md"))
    assert len(task_files) == 1
    task_file = task_files[0]
    assert "edited-task-title" in task_file.name
    task_content = task_file.read_text(encoding="utf-8")
    assert "- title: Edited Task Title" in task_content
    assert "- priority: P0" in task_content
    assert "- priority-reason: Urgent security audit requirement" in task_content
    assert "- kind: feature" in task_content
    assert "- labels: security, auth" in task_content
    assert "## Goal\n\nEdited goal statement" in task_content
    assert "- [ ] Step 1 edited" in task_content
    assert "- [ ] Verify 1 edited" in task_content

    # Validate tasks tree is clean
    res_val = subprocess.run(
        [str(BIN_AI_ORCH), "tasks", "validate", "--tasks-dir", str(tasks_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    val_data = json.loads(res_val.stdout)
    assert val_data["errors"] == []

    # Verify stored triage-proposal.json records proposal_status accepted and edits_applied
    prop_path = sample_workspace / ".ai-orchestration" / "runs" / run_id / "triage-proposal.json"
    prop_data = json.loads(prop_path.read_text(encoding="utf-8"))
    assert prop_data["proposal_status"] == "accepted"
    assert prop_data["edits_applied"]["0"]["title"] == "Edited Task Title"
    assert prop_data["tasks"][0]["title"] == "Edited Task Title"


def test_accept_triage_invalid_edits_refuses_and_creates_nothing(sample_workspace: pathlib.Path):
    """Test that invalid edit (bad priority, unknown key, empty fields, bad category) refuses and creates nothing (Task 09.10)."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Invalid edit note",
            "--body",
            "Body",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proposal = {
        "tasks": [
            {
                "title": "Valid Initial Task",
                "category": "server",
                "priority": "P2",
                "priority_reason": "Reason",
                "goal": "Goal",
                "steps": ["Step 1"],
                "verification": ["Ver 1"],
            }
        ],
        "updates": [],
        "spec": None,
        "questions": [],
    }

    mock_agent = sample_workspace / "inv_agent.py"
    msg = "```ai-orch-triage\n" + json.dumps(proposal) + "\n```\n"
    evt = {"type": "message", "role": "assistant", "content": msg}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure invalid edit agent"], cwd=str(sample_workspace), check=True)

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    wait_for_terminal(sample_workspace, run_id)

    tasks_before = list(tasks_dir.glob("*/*.md"))

    # 1. Bad priority (e.g. P99)
    bad_pri_file = sample_workspace / "bad_pri.json"
    bad_pri_file.write_text(json.dumps({"0": {"priority": "P99"}}), encoding="utf-8")
    res_bad_pri = subprocess.run(
        [str(BIN_AI_ORCH), "run", "accept-triage", run_id, "--edits-file", str(bad_pri_file), "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_bad_pri.returncode != 0
    err_pri = json.loads(res_bad_pri.stdout)
    assert err_pri["reason"] == "invalid-edit"
    assert "Invalid priority" in err_pri["error"]
    assert len(list(tasks_dir.glob("*/*.md"))) == len(tasks_before)

    # 2. Unknown key in edits
    unknown_key_file = sample_workspace / "unknown_key.json"
    unknown_key_file.write_text(json.dumps({"0": {"unknown_field": "disallowed"}}), encoding="utf-8")
    res_unk = subprocess.run(
        [str(BIN_AI_ORCH), "run", "accept-triage", run_id, "--edits-file", str(unknown_key_file), "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_unk.returncode != 0
    err_unk = json.loads(res_unk.stdout)
    assert err_unk["reason"] == "invalid-edit"
    assert "Unknown field 'unknown_field'" in err_unk["error"]
    assert len(list(tasks_dir.glob("*/*.md"))) == len(tasks_before)

    # 3. Empty title
    empty_title_file = sample_workspace / "empty_title.json"
    empty_title_file.write_text(json.dumps({"0": {"title": "   "}}), encoding="utf-8")
    res_title = subprocess.run(
        [str(BIN_AI_ORCH), "run", "accept-triage", run_id, "--edits-file", str(empty_title_file), "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_title.returncode != 0
    err_title = json.loads(res_title.stdout)
    assert err_title["reason"] == "invalid-edit"
    assert "title" in err_title["error"].lower()
    assert len(list(tasks_dir.glob("*/*.md"))) == len(tasks_before)

    # 4. Invalid category (reserved directory)
    bad_cat_file = sample_workspace / "bad_cat.json"
    bad_cat_file.write_text(json.dumps({"0": {"category": "_inbox"}}), encoding="utf-8")
    res_cat = subprocess.run(
        [str(BIN_AI_ORCH), "run", "accept-triage", run_id, "--edits-file", str(bad_cat_file), "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_cat.returncode != 0
    err_cat = json.loads(res_cat.stdout)
    assert err_cat["reason"] == "invalid-edit"
    assert "category" in err_cat["error"].lower()
    assert len(list(tasks_dir.glob("*/*.md"))) == len(tasks_before)

    # Ensure run record still pending and note still in to-analyze/
    rec_after = load_run_record(sample_workspace, run_id)
    assert rec_after["proposal_status"] == "pending"
    note_files = list((tasks_dir / "_inbox" / "to-analyze").glob("*/note.md"))
    assert any(f"id: {note_id}" in p.read_text(encoding="utf-8") for p in note_files)


def test_accept_triage_edits_combined_with_only(sample_workspace: pathlib.Path):
    """Test edits combined with --only ignores edits for non-accepted indices with warning (Task 09.10)."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Edits plus only note",
            "--body",
            "Body",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proposal = {
        "tasks": [
            {
                "title": "Task Zero Original",
                "category": "server",
                "priority": "P2",
                "priority_reason": "Zero reason",
                "goal": "Goal 0",
                "steps": ["Step 0"],
                "verification": ["Ver 0"],
            },
            {
                "title": "Task One Original",
                "category": "server",
                "priority": "P3",
                "priority_reason": "One reason",
                "goal": "Goal 1",
                "steps": ["Step 1"],
                "verification": ["Ver 1"],
            },
        ],
        "updates": [],
        "spec": None,
        "questions": [],
    }

    mock_agent = sample_workspace / "only_edits_agent.py"
    msg = "```ai-orch-triage\n" + json.dumps(proposal) + "\n```\n"
    evt = {"type": "message", "role": "assistant", "content": msg}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure only edits agent"], cwd=str(sample_workspace), check=True)

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    wait_for_terminal(sample_workspace, run_id)

    # Provide edits for both index 0 and index 1
    edits_file = sample_workspace / "multi_edits.json"
    edits_payload = {
        "0": {"title": "Task Zero Edited", "priority": "P1"},
        "1": {"title": "Task One Edited", "priority": "P0"},
    }
    edits_file.write_text(json.dumps(edits_payload), encoding="utf-8")

    # Accept with --only 0
    res_acc = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "accept-triage",
            run_id,
            "--only",
            "0",
            "--edits-file",
            str(edits_file),
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    acc_data = json.loads(res_acc.stdout)
    assert acc_data["ok"] is True
    assert acc_data["proposal_status"] == "accepted"
    created = acc_data["tasks_created"]
    assert len(created) == 1

    # Task 0 has edited title and priority
    task_files = list((tasks_dir / "server").glob(f"{created[0]}-*.md"))
    assert len(task_files) == 1
    content = task_files[0].read_text(encoding="utf-8")
    assert "- title: Task Zero Edited" in content
    assert "- priority: P1" in content

    # Task 1 was NOT created
    all_server_files = [p.name for p in (tasks_dir / "server").glob("*.md")]
    assert not any("task-one" in name.lower() for name in all_server_files)

    # Result records warning for index 1
    warnings = acc_data.get("warnings", [])
    assert any("1" in w for w in warnings)
    assert "0" in acc_data["edits_applied"]
    assert "1" not in acc_data["edits_applied"]


def test_accept_triage_edits_refuses_stale_note_hash(sample_workspace: pathlib.Path):
    """Test that accept-triage with --edits-file still refuses stale note hash (Task 09.10)."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Stale with edits note",
            "--body",
            "Initial text",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proposal = {
        "tasks": [
            {
                "title": "Stale Test Task",
                "category": "server",
                "priority": "P2",
                "priority_reason": "Reason",
                "goal": "Goal",
                "steps": ["Step"],
                "verification": ["Ver"],
            }
        ],
        "updates": [],
        "spec": None,
        "questions": [],
    }

    mock_agent = sample_workspace / "stale_agent.py"
    msg = "```ai-orch-triage\n" + json.dumps(proposal) + "\n```\n"
    evt = {"type": "message", "role": "assistant", "content": msg}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure stale agent"], cwd=str(sample_workspace), check=True)

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    wait_for_terminal(sample_workspace, run_id)

    tasks_before = list(tasks_dir.glob("*/*.md"))

    edits_file = sample_workspace / "valid_edits.json"
    edits_file.write_text(json.dumps({"0": {"title": "Edited Title"}}), encoding="utf-8")

    # 1. Expect note hash mismatch
    res_mismatch = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "accept-triage",
            run_id,
            "--expect-note-hash",
            "0000000000000000000000000000000000000000000000000000000000000000",
            "--edits-file",
            str(edits_file),
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert res_mismatch.returncode != 0
    data_mismatch = json.loads(res_mismatch.stdout)
    assert data_mismatch["reason"] == "note-hash-mismatch"
    assert len(list(tasks_dir.glob("*/*.md"))) == len(tasks_before)

    # 2. Mutate note file to trigger stale-note-hash
    note_files = list((tasks_dir / "_inbox" / "to-analyze").glob("*/note.md"))
    note_md = next(p for p in note_files if f"id: {note_id}" in p.read_text(encoding="utf-8"))
    note_md.write_text(note_md.read_text(encoding="utf-8") + "\nappended changed content\n", encoding="utf-8")

    res_stale = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "accept-triage",
            run_id,
            "--edits-file",
            str(edits_file),
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert res_stale.returncode != 0
    err_data = json.loads(res_stale.stdout)
    assert err_data["reason"] == "stale-note-hash"
    assert len(list(tasks_dir.glob("*/*.md"))) == len(tasks_before)
    assert not any("edited-title" in p.name.lower() for p in tasks_dir.glob("*/*.md"))


def test_triage_missing_or_invalid_block_records_invalid_status(sample_workspace: pathlib.Path):
    """Test that missing or invalid ai-orch-triage block results in proposal_status == 'invalid'."""
    tasks_dir = sample_workspace / "tasks"

    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Invalid block test note",
            "--body",
            "Body",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    # 1. Agent emitting NO triage block
    mock_agent = sample_workspace / "no_triage_agent.py"
    evt = {"type": "message", "role": "assistant", "content": "Just a normal chat message with no block."}
    mock_agent.write_text(
        f"import sys, json\n"
        f"sys.stdout.write(json.dumps({json.dumps(evt)}) + '\\n')\n"
        f"sys.stdout.flush()\n",
        encoding="utf-8",
    )

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{mock_agent}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "configure no triage agent"], cwd=str(sample_workspace), check=True)

    res_start = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id = json.loads(res_start.stdout)["run_id"]
    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["proposal_status"] == "invalid"
    assert "Missing ```ai-orch-triage block" in rec["proposal_error"]

    # Attempting to accept refuses
    res_acc = subprocess.run(
        [str(BIN_AI_ORCH), "run", "accept-triage", run_id, "--workspace", str(sample_workspace), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_acc.returncode != 0
    data_acc = json.loads(res_acc.stdout)
    assert data_acc["reason"] == "proposal-not-pending"

    # 2. Agent emitting MALFORMED json block
    mock_agent.write_text(
        "import sys, json\n"
        "evt = {'type': 'message', 'role': 'assistant', 'content': '```ai-orch-triage\\n{not valid json}\\n```'}\n"
        "sys.stdout.write(json.dumps(evt) + '\\n')\n"
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )
    res_start2 = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "run",
            "start",
            "--note",
            note_id,
            "--tool",
            "kilo",
            "--force",
            "--workspace",
            str(sample_workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    run_id2 = json.loads(res_start2.stdout)["run_id"]
    rec2 = wait_for_terminal(sample_workspace, run_id2)
    assert rec2["status"] == "succeeded"
    assert rec2["proposal_status"] == "invalid"
    assert "Invalid JSON in ai-orch-triage block" in rec2["proposal_error"]





def test_codex_triage_passes_only_images_with_dash_i():
    import orchestration_runs as orr

    argv = orr.build_adapter_argv(
        tool="codex",
        tool_cfg={"headless": {}},
        mode="triage",
        cwd=".",
        model="gpt-5-codex",
        variant=None,
        effort=None,
        session_id=None,
        prompt_file="p.md",
        attachment_paths=["n/attachments/01-shot.PNG", "n/attachments/02-app.log", "n/attachments/03-spec.pdf"],
    )
    pairs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
    assert pairs == ["n/attachments/01-shot.PNG"]


def test_runs_on_child_task_and_initiative_subtask(sample_workspace: pathlib.Path):
    init_dir = sample_workspace / "tasks" / "05-feature"
    init_dir.mkdir(parents=True)
    plan_text = (
        "# 05 - Feature Initiative\n\n"
        "> **Goal:** High-level initiative\n\n"
        "## Tasks\n\n"
        "### 05.1 - First Subtask\n"
        "- **Status:** `open`\n"
        "- **Priority:** `P1`\n"
        "- **Goal:** Implement core module\n"
        "- **Verification:** `pytest test_core.py`\n\n"
        "### 05.2 - Second Subtask\n"
        "- **Status:** `open`\n"
    )
    (init_dir / "plan.md").write_text(plan_text, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "add initiative 05"], cwd=str(sample_workspace), check=True)

    # 1. Test options on 05.1
    cmd_opt = [str(BIN_AI_ORCH), "run", "options", "--task", "05.1", "--workspace", str(sample_workspace), "--json"]
    res_opt = subprocess.run(cmd_opt, capture_output=True, text=True, check=True)
    data_opt = json.loads(res_opt.stdout)
    assert data_opt["ok"] is True
    assert data_opt["task"]["id"] == "05.1"
    assert "execute" in data_opt["allowed_modes"]

    # 2. Test preview on 05.1
    cmd_prev = [str(BIN_AI_ORCH), "run", "preview", "--task", "05.1", "--mode", "execute", "--workspace", str(sample_workspace), "--json"]
    res_prev = subprocess.run(cmd_prev, capture_output=True, text=True, check=True)
    data_prev = json.loads(res_prev.stdout)
    assert data_prev["ok"] is True
    assert "Parent Context (plan.md)" in data_prev["prompt"]
    assert "05.1 - First Subtask" in data_prev["prompt"]


# ---------------------------------------------------------------------------
# 07.5 / 12.1: parsers against live-captured streams (scrubbed fixtures; no CLI runs)
# ---------------------------------------------------------------------------

FIXTURES_RUNS = pathlib.Path(__file__).resolve().parent / "fixtures" / "runs"

import orchestration_runs as _runs  # noqa: E402

KILO_SESSION = "ses_eb3d8ca0cffe7qLxcN47nwQ9jO"
CLAUDE_SESSION = "fb2689fd-5a34-4749-b30e-8d1e17d70ab2"
CODEX_SESSION = "01a14c2b-c204-71e0-a2c6-f0290b283bbe"


def _fixture_run_dir(tmp_path: pathlib.Path, name: str) -> pathlib.Path:
    """A run directory whose only stream chunk is the named fixture."""
    run_dir = tmp_path / name
    run_dir.mkdir(exist_ok=True)
    (run_dir / "events.000.jsonl").write_bytes((FIXTURES_RUNS / f"{name}.jsonl").read_bytes())
    return run_dir


def test_fixtures_are_scrubbed():
    for f in FIXTURES_RUNS.glob("*.jsonl"):
        text = f.read_text(encoding="utf-8")
        assert "/Users/" not in text, f.name
        assert "@isti.cnr.it" not in text, f.name
        for line in text.splitlines():
            if line.strip():
                json.loads(line)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("kilo-execute", KILO_SESSION),
        ("kilo-continue", KILO_SESSION),
        ("claude-execute", CLAUDE_SESSION),
        ("claude-continue", CLAUDE_SESSION),
        ("claude-killed", CLAUDE_SESSION),
        ("codex-execute", CODEX_SESSION),
        ("codex-continue", CODEX_SESSION),
    ],
)
def test_fixture_session_id_and_continuation_same_session(tmp_path, name, expected):
    assert _runs.extract_session_id_from_run(_fixture_run_dir(tmp_path, name)) == expected


def test_fixture_verify_runs_have_their_own_session(tmp_path):
    assert _runs.extract_session_id_from_run(_fixture_run_dir(tmp_path, "kilo-verify")).startswith("ses_")
    assert _runs.extract_session_id_from_run(_fixture_run_dir(tmp_path, "kilo-verify")) != KILO_SESSION
    assert _runs.extract_session_id_from_run(_fixture_run_dir(tmp_path, "codex-verify")) == "01a14c2d-9ffe-7113-91e8-cf3867a87261"
    assert _runs.extract_session_id_from_run(_fixture_run_dir(tmp_path, "claude-verify")) == "0b34e320-fea4-4102-a8ab-6e92ea9dcffb"


@pytest.mark.parametrize("tool", ["kilo", "claude", "codex"])
def test_fixture_final_report_is_clean_text(tmp_path, tool):
    report = _runs.extract_final_report_from_run(_fixture_run_dir(tmp_path, f"{tool}-execute"))
    assert report is not None
    assert report.startswith("## Final Report\n")
    assert "**Outcome**" in report
    assert "**Issues**" in report
    # Not raw JSON: real newlines, no trailing event payload.
    assert report.count("\n") >= 5
    assert '"time"' not in report and '"part"' not in report and '"usage"' not in report
    assert '"type"' not in report and "session_id" not in report


def test_fixture_final_report_claude_uses_result_text(tmp_path):
    run_dir = _fixture_run_dir(tmp_path, "claude-continue")
    final = _runs.extract_final_assistant_message(run_dir)
    assert final is not None and final.startswith("The command ran")
    assert _runs.extract_final_report_from_run(run_dir).startswith("## Final Report\n- **Outcome**: `partial`")


def test_fixture_no_final_report_in_short_continuations(tmp_path):
    assert _runs.extract_final_report_from_run(_fixture_run_dir(tmp_path, "kilo-continue")) is None
    assert _runs.extract_final_assistant_message(_fixture_run_dir(tmp_path, "kilo-continue")) == "DELTA"
    assert _runs.extract_final_report_from_run(_fixture_run_dir(tmp_path, "codex-continue")) is None


@pytest.mark.parametrize(
    "name, verdict",
    [("kilo-verify", "verified"), ("claude-verify", "bounced"), ("codex-verify", "verified")],
)
def test_fixture_verdict(tmp_path, name, verdict):
    v = _runs.extract_verdict_from_run(_fixture_run_dir(tmp_path, name))
    assert v is not None
    assert v["verdict"] == verdict
    assert v["checks"] and all({"step", "result", "evidence"} <= set(c) for c in v["checks"])
    if verdict == "bounced":
        assert v["findings"][0]["severity"] == "major"


def test_fixture_assistant_messages_skip_tools_and_thinking(tmp_path):
    msgs = _runs.extract_assistant_messages(_fixture_run_dir(tmp_path, "claude-execute"))
    assert msgs and all(m.strip() for m in msgs)
    assert msgs[-1].startswith("## Final Report")
    kilo = _runs.extract_assistant_messages(_fixture_run_dir(tmp_path, "kilo-execute"))
    assert kilo[-1].startswith("## Final Report")
    codex = _runs.extract_assistant_messages(_fixture_run_dir(tmp_path, "codex-execute"))
    assert codex[0].startswith("I’m applying") or codex[0]
    assert codex[-1].startswith("## Final Report")


def test_fixture_usage_kilo(tmp_path):
    u = _runs.extract_usage_from_run(_fixture_run_dir(tmp_path, "kilo-execute"))
    assert set(_runs.USAGE_FIELDS) <= set(u)
    assert u["source"] == "kilo"
    assert u["input_tokens"] == 54367 and u["cache_read"] == 283061 and u["cache_write"] == 0
    assert u["output_tokens"] == 750
    # context at the last step = its tokens.total
    assert u["estimated_context_tokens"] == 38210
    assert u["cost_usd"] == pytest.approx(0.064817, abs=1e-6)


def test_fixture_usage_claude(tmp_path):
    u = _runs.extract_usage_from_run(_fixture_run_dir(tmp_path, "claude-execute"))
    assert u["source"] == "claude"
    assert (u["input_tokens"], u["cache_read"], u["cache_write"], u["output_tokens"]) == (12, 338095, 40482, 1839)
    # last API call (result.usage.iterations[-1]): 2 + 63947 + 462 + 441
    assert u["estimated_context_tokens"] == 64852
    assert u["cost_usd"] == pytest.approx(0.0126, abs=1e-4)


def test_fixture_usage_claude_killed_counts_each_message_once(tmp_path):
    u = _runs.extract_usage_from_run(_fixture_run_dir(tmp_path, "claude-killed"))
    assert u["source"] == "claude"
    assert u["cost_usd"] is None  # no closing result event
    assert u["estimated_context_tokens"] == u["input_tokens"] + u["cache_read"] + u["cache_write"] + u["output_tokens"]
    assert u["estimated_context_tokens"] == 65743


def test_fixture_usage_codex_is_cumulative_per_thread(tmp_path):
    first = _runs.extract_usage_from_run(_fixture_run_dir(tmp_path, "codex-execute"))
    assert first["source"] == "codex"
    assert first["session_totals"] == {"input_tokens": 6735, "cache_read": 97920, "cache_write": 0, "output_tokens": 1298}
    assert first["input_tokens"] == 6735 and first["estimated_context_tokens"] is None
    second = _runs.extract_usage_from_run(_fixture_run_dir(tmp_path, "codex-continue"), first["session_totals"])
    assert (second["input_tokens"], second["cache_read"], second["output_tokens"]) == (392, 15616, 33)
    assert second["session_totals"]["cache_read"] == 113536


def test_codex_rollout_last_context(tmp_path):
    day = tmp_path / "sessions" / "2026" / "10" / "18"
    day.mkdir(parents=True)
    tid = "01a14c2b-c204-71e0-a2c6-f0290b283bbe"
    lines = [
        {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 100, "output_tokens": 5}}}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 16008, "output_tokens": 33}}}},
    ]
    (day / f"rollout-2026-10-18T01-21-38-{tid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    assert _runs.codex_rollout_last_context(tid, codex_home=tmp_path) == 16041
    assert _runs.codex_rollout_last_context("missing", codex_home=tmp_path) is None
    assert _runs.codex_rollout_last_context("../etc", codex_home=tmp_path) is None


@pytest.mark.parametrize(
    "name, needle",
    [
        ("kilo-resume-other-project", "Unexpected server error"),
        ("claude-resume-invalid-session", "No conversation found with session ID"),
        ("codex-model-unsupported", "not supported when using Codex with a ChatGPT account"),
    ],
)
def test_fixture_agent_error(tmp_path, name, needle):
    err = _runs.agent_error_from_objects(_runs.read_stream_objects(_fixture_run_dir(tmp_path, name)))
    assert err and needle in err


def test_fixture_codex_resume_by_name_starts_a_new_thread(tmp_path):
    # `codex exec resume not-a-thread`: no thread named so; Codex silently starts a new one.
    sid = _runs.extract_session_id_from_run(_fixture_run_dir(tmp_path, "codex-resume-name-fallback"))
    assert sid and sid != "not-a-thread" and sid != CODEX_SESSION


def test_fixture_log_events_show_text_and_tools(tmp_path):
    for tool in ("kilo", "claude", "codex"):
        events = _runs.parse_log_events((FIXTURES_RUNS / f"{tool}-execute.jsonl").read_bytes())
        texts = [e["text"] for e in events if e.get("text")]
        assert any(t.startswith("## Final Report") for t in texts), tool
        assert any(e.get("tool_call") for e in events), tool
        assert not any(t.lstrip().startswith("{") for t in texts), tool


def test_adapter_argv_live_flag_corrections():
    # Kilo: `-f` is an array option, so the message needs `--` (resume included).
    argv = build_adapter_argv("kilo", {}, "execute", "/w", "google/gemini-3.8-flash", session_id="ses_x", prompt_file="/p.md", is_resume=True)
    assert argv[-3:] == ["/p.md", "--", "Continue."]
    # Codex execute in a worktree: the main repo's .git is a sandbox writable root, start and resume.
    start = build_adapter_argv("codex", {}, "execute", "/w", "m", git_common_dir="/repo/.git")
    assert 'sandbox_workspace_write.writable_roots=["/repo/.git"]' in start
    assert start[-1] == "-"
    resume = build_adapter_argv("codex", {}, "execute", "/w", "m", session_id="t", is_resume=True, git_common_dir="/repo/.git")
    assert 'sandbox_workspace_write.writable_roots=["/repo/.git"]' in resume
    ro = build_adapter_argv("codex", {"headless": {"sandbox": "read-only"}}, "execute", "/w", "m", git_common_dir="/repo/.git")
    assert not any("writable_roots" in a for a in ro)
    # Claude: python3 -m pytest is allowed in execute and verify (Homebrew/macOS have no `python`).
    for mode in ("execute", "verify", "orchestrate"):
        assert "Bash(python3 -m pytest:*)" in DEFAULT_CLAUDE_ALLOWED_TOOLS[mode]


def test_kilo_unattended_turn_enforces_restricted_agent():
    """T028: Unattended Kilo turns (mode=triage) use the verified restricted agent; orchestrate turns remain unchanged."""
    # Start: triage mode adds --agent ask
    start_triage = build_adapter_argv("kilo", {}, "triage", "/w", "google/gemini-3.8-flash", prompt_file="/p.md")
    assert "--agent" in start_triage
    idx = start_triage.index("--agent")
    assert start_triage[idx + 1] == "aio-unattended"

    # Resume: triage mode adds --agent ask
    resume_triage = build_adapter_argv(
        "kilo", {}, "triage", "/w", "google/gemini-3.8-flash", session_id="ses_x", prompt_file="/p.md", is_resume=True
    )
    assert "--agent" in resume_triage
    idx = resume_triage.index("--agent")
    assert resume_triage[idx + 1] == "aio-unattended"
    assert resume_triage[-3:] == ["/p.md", "--", "Continue."]

    # Owner orchestrate turn: unchanged (no --agent)
    start_orch = build_adapter_argv("kilo", {}, "orchestrate", "/w", "google/gemini-3.8-flash", prompt_file="/p.md")
    assert "--agent" not in start_orch
    assert start_orch[-2:] == ["--", "Follow the attached task prompt."]

    resume_orch = build_adapter_argv(
        "kilo", {}, "orchestrate", "/w", "google/gemini-3.8-flash", session_id="ses_x", prompt_file="/p.md", is_resume=True
    )
    assert "--agent" not in resume_orch
    assert resume_orch[-3:] == ["/p.md", "--", "Continue."]

    # Custom configured restricted agent in headless
    custom_cfg = {"headless": {"agent": {"triage": "custom-ask"}}}
    custom_argv = build_adapter_argv("kilo", custom_cfg, "triage", "/w", "google/gemini-3.8-flash", prompt_file="/p.md")
    assert "--agent" in custom_argv
    assert custom_argv[custom_argv.index("--agent") + 1] == "custom-ask"

    # If no restricted agent can be enforced for triage: run is refused (fail closed)
    disabled_cfg = {"headless": {"agent": {"triage": ""}}}
    with pytest.raises(ValueError, match="Kilo requires a restricted agent"):
        build_adapter_argv("kilo", disabled_cfg, "triage", "/w", "google/gemini-3.8-flash", prompt_file="/p.md")

    ok_agent, err_msg = check_kilo_agent(disabled_cfg["headless"], "triage")
    assert not ok_agent
    assert "Kilo requires a restricted agent" in err_msg

    # The default agent is accepted only when Kilo's resolved permissions really deny everything but reading
    import orchestration_runs as _runs
    _runs._kilo_agent_cache.clear()
    _runs._kilo_agent_cache["aio-unattended"] = (True, None)
    ok_default, _ = check_kilo_agent({}, "triage")
    assert ok_default
    _runs._kilo_agent_cache["aio-unattended"] = (False, "Kilo agent 'aio-unattended' is not installed")
    ok_missing, err_missing = check_kilo_agent({}, "triage")
    assert not ok_missing and "not installed" in err_missing
    _runs._kilo_agent_cache.clear()
    ok_orch, _ = check_kilo_agent({}, "orchestrate")
    assert ok_orch


def test_kilo_triage_refused_when_no_restricted_agent_configured(sample_workspace: pathlib.Path):
    """T028: Kilo run start for triage mode is refused when no restricted agent is configured."""
    tasks_dir = sample_workspace / "tasks"
    res_add = subprocess.run(
        [
            str(BIN_AI_ORCH),
            "tasks",
            "inbox",
            "add",
            "--title",
            "Test note for kilo triage",
            "--body",
            "Analyze something",
            "--status",
            "ready",
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    note_id = json.loads(res_add.stdout)["id"]

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    # Explicitly disable agent for triage
    proj_cfg.write_text(
        orig_cfg + '\n[tools.kilo.headless.agent]\ntriage = ""\n',
        encoding="utf-8",
    )

    # Preview should include warning
    cmd_prev = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--note",
        note_id,
        "--tool",
        "kilo",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_prev = subprocess.run(cmd_prev, capture_output=True, text=True, check=True)
    data_prev = json.loads(res_prev.stdout)
    assert any("restricted agent" in w for w in data_prev.get("warnings", []))

    # Start must be refused
    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--note",
        note_id,
        "--tool",
        "kilo",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=False)
    assert res_start.returncode != 0
    data_start = json.loads(res_start.stdout)
    assert data_start["ok"] is False
    assert data_start["reason"] == "missing-restricted-agent"


def test_git_common_dir_of_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"], cwd=repo, check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt)], cwd=repo, check=True)
    assert pathlib.Path(_runs.git_common_dir_of(wt)).resolve() == (repo / ".git").resolve()


def test_continue_refused_while_session_busy_and_mismatch_fails(sample_workspace: pathlib.Path):
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "sess-init"]\n'
        f'resume_argv = ["{sys.executable}", "{STUB_AGENT}", "--session-id", "sess-fresh-thread"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg busy"], cwd=str(sample_workspace), check=True)

    def ai_orch(*args: str, check: bool = True) -> dict:
        res = subprocess.run(
            [str(BIN_AI_ORCH), "run", *args, "--workspace", str(sample_workspace), "--json"],
            capture_output=True, text=True, check=check,
        )
        return json.loads(res.stdout)

    r1 = ai_orch("start", "--task", "T007", "--mode", "execute", "--isolation", "worktree")["run_id"]
    rec1 = wait_for_terminal(sample_workspace, r1)
    assert rec1["status"] == "succeeded" and rec1["session_id"] == "sess-init"

    # An active run holding the same session (this test process stands in for its supervisor).
    busy = dict(rec1)
    busy.update({
        "run_id": "20261017-000001-T007-kilo-b0b0",
        "status": "running",
        "continued_from": r1,
        "supervisor": {"pid": os.getpid(), "start_time": get_process_start_time(os.getpid())},
    })
    save_run_record(sample_workspace, busy)
    refused = ai_orch("start", "--continue", r1, "--instructions", "x", check=False)
    assert refused["ok"] is False and refused["reason"] == "session-busy"
    assert busy["run_id"] in refused["error"]

    busy["status"] = "succeeded"
    save_run_record(sample_workspace, busy)
    # The resumed agent reports another session: the continuation fails, never silently forks.
    r2 = ai_orch("start", "--continue", r1, "--instructions", "x")["run_id"]
    rec2 = wait_for_terminal(sample_workspace, r2)
    assert rec2["status"] == "failed"
    assert rec2["session_mismatch"] is True
    assert rec2["observed_session_id"] == "sess-fresh-thread"
    assert rec2["session_id"] == "sess-init"
    assert "did not land in session" in rec2["invariant_error"]


# ---------------------------------------------------------------------------
# T022: Run Engine Fixes
# ---------------------------------------------------------------------------

def test_t022_cancel_stops_tool_children_in_new_session(sample_workspace: pathlib.Path):
    """Item 1: run cancel terminates descendants of agent pid (including new session / setsid)."""
    gc_pid_file = sample_workspace / "gc_setsid.pid"
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "30", "--grandchild-pid-file", "{gc_pid_file}", "--grandchild-sleep", "60", "--grandchild-setsid"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg cancel setsid"], cwd=str(sample_workspace), check=True)

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

    gc_pid = None
    agent_pid = None
    try:
        # Poll up to 30s for both grandchild PID file and supervisor recording agent identity
        deadline = time.time() + 30.0
        rec = None
        while time.time() < deadline:
            if gc_pid_file.is_file() and gc_pid_file.read_text(encoding="utf-8").strip():
                rec = load_run_record(sample_workspace, run_id)
                agent = (rec or {}).get("agent", {})
                if agent.get("pid") and agent.get("pgid") and agent.get("start_time"):
                    break
            time.sleep(0.05)

        assert gc_pid_file.is_file()
        gc_pid = int(gc_pid_file.read_text(encoding="utf-8").strip())

        assert rec is not None
        agent = rec.get("agent", {})
        agent_pid = agent.get("pid")
        agent_pgid = agent.get("pgid")
        assert agent_pid is not None
        assert agent_pgid is not None
        assert is_process_alive(agent_pid)
        assert is_process_alive(gc_pid)

        # Verify grandchild is indeed in a different process group / session
        gc_pgid = os.getpgid(gc_pid)
        assert gc_pgid != agent_pgid, f"Grandchild pgid {gc_pgid} must differ from agent pgid {agent_pgid}"

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
        assert json.loads(res_cancel.stdout)["ok"] is True

        # Both agent and grandchild must be dead (poll up to 30s)
        deadline = time.time() + 30.0
        while time.time() < deadline:
            if not is_process_alive(agent_pid) and not is_process_alive(gc_pid):
                break
            time.sleep(0.05)
        assert not is_process_alive(agent_pid), f"Agent PID {agent_pid} should be dead"
        assert not is_process_alive(gc_pid), f"Grandchild PID {gc_pid} in new session should be terminated by cancel"
    finally:
        for p in (gc_pid, agent_pid):
            if p:
                try:
                    os.kill(p, signal.SIGKILL)
                except OSError:
                    pass



def test_t022_continue_refused_for_verify_or_missing_worktree(sample_workspace: pathlib.Path):
    """Item 2: continuing verify run or run whose worktree is missing is refused."""
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "sess-test"]\n'
        + f'[tools.claude.headless]\nallowed_tools = ["test"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified", "--session-id", "sess-ver"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg cont test"], cwd=str(sample_workspace), check=True)

    # 1. Execute run
    cmd_exec = [
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
    res_exec = subprocess.run(cmd_exec, capture_output=True, text=True, check=True)
    r_exec_id = json.loads(res_exec.stdout)["run_id"]
    rec_exec = wait_for_terminal(sample_workspace, r_exec_id)
    assert rec_exec["status"] == "succeeded"

    # Set task to delivered so verify run can run
    task_file = sample_workspace / "tasks" / "server" / "T007-verification-gate.md"
    task_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(re.sub(r"state: [^\n]+", "state: delivered", task_text), encoding="utf-8")

    # 2. Verify run
    cmd_ver = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--target-run",
        r_exec_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_ver = subprocess.run(cmd_ver, capture_output=True, text=True, check=True)
    r_ver_id = json.loads(res_ver.stdout)["run_id"]
    rec_ver = wait_for_terminal(sample_workspace, r_ver_id)
    assert rec_ver["status"] == "succeeded"

    # Attempt to continue verify run -> must be refused
    cmd_cont_ver = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--continue",
        r_ver_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_cont_ver = subprocess.run(cmd_cont_ver, capture_output=True, text=True, check=False)
    assert res_cont_ver.returncode != 0
    data_cont_ver = json.loads(res_cont_ver.stdout)
    assert data_cont_ver["ok"] is False
    assert data_cont_ver["reason"] == "verify-cannot-continue"

    # Attempt to continue execute run whose worktree is deleted -> must be refused
    wt_dir = pathlib.Path(rec_exec["worktree_path"])
    shutil.rmtree(wt_dir, ignore_errors=True)
    assert not wt_dir.exists()

    cmd_cont_exec = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--continue",
        r_exec_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_cont_exec = subprocess.run(cmd_cont_exec, capture_output=True, text=True, check=False)
    assert res_cont_exec.returncode != 0
    data_cont_exec = json.loads(res_cont_exec.stdout)
    assert data_cont_exec["ok"] is False
    assert data_cont_exec["reason"] == "worktree-missing"


def test_t022_verify_removes_only_created_worktrees(sample_workspace: pathlib.Path):
    """Item 3: verify run never removes an inherited/foreign worktree."""
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report"]\n'
        + f'[tools.claude.headless]\nallowed_tools = ["test"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg verify remove"], cwd=str(sample_workspace), check=True)

    cmd_exec = [
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
    res_exec = subprocess.run(cmd_exec, capture_output=True, text=True, check=True)
    r_exec_id = json.loads(res_exec.stdout)["run_id"]
    rec_exec = wait_for_terminal(sample_workspace, r_exec_id)
    assert rec_exec["status"] == "succeeded"
    wt_dir = pathlib.Path(rec_exec["worktree_path"])
    assert wt_dir.is_dir()

    # Manually forge a verify run record pointing at r_exec's worktree but without created_worktree
    r_ver_id = "20261017-120000-T007-claude-9999"
    r_ver_dir = sample_workspace / ".ai-orchestration" / "runs" / r_ver_id
    r_ver_dir.mkdir(parents=True, exist_ok=True)
    p_prompt = r_ver_dir / "prompt.md"
    p_prompt.write_text("verify prompt", encoding="utf-8")

    rec_ver = create_run_record(
        run_id=r_ver_id,
        task_id="T007",
        mode="verify",
        tool="claude",
        profile="deep-reasoning",
        model="claude-opus",
        variant=None,
        effort=None,
        requested_by="cli",
        workspace=str(sample_workspace),
        cwd=str(wt_dir),
        isolation="worktree",
        task_bundle_sha256="",
        argv_display=[],
        plan_hash="",
        worktree_path=str(wt_dir),
        branch=None,
        target_run=r_exec_id,
        target_commit=rec_exec["final_commit"],
        verification_mode="cross-agent",
        created_worktree=None,  # verify run did NOT create this worktree!
    )
    save_run_record(sample_workspace, rec_ver)

    # Supervise the verify run
    runs_script = pathlib.Path(BIN_AI_ORCH).parent.parent / "scripts" / "orchestration_runs.py"
    sup_cmd = [
        sys.executable,
        str(runs_script.resolve()),
        "_supervise",
        str(r_ver_dir),
    ]
    subprocess.run(sup_cmd, capture_output=True, text=True, check=True)
    rec_after = load_run_record(sample_workspace, r_ver_id)
    assert rec_after["status"] == "succeeded"
    assert rec_after["worktree_removed"] is False
    assert wt_dir.is_dir(), "Foreign worktree must remain intact"


def test_t022_supervisor_in_progress_does_not_block_second_execute(sample_workspace: pathlib.Path):
    """Item 4: task state transition to in progress must not block sequential execute runs in same repo."""
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report"]\n',
        encoding="utf-8",
    )

    # Create task T008 in tasks/server
    task_t008 = sample_workspace / "tasks" / "server" / "T008-second-task.md"
    task_t008.write_text(
        "# T008 Second Task\n\n- id: T008\n- title: Second Task\n- category: server\n- priority: P2\n- state: open\n- executor: kilo\n- next-up: yes\n- paths: -\n- depends-on: -\n- decider: -\n- sources: -\n- handoff: none\n\n## Goal\nGoal\n\n## Verification\npytest\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "setup two tasks"], cwd=str(sample_workspace), check=True)

    # Start first execute run (T007)
    cmd_r1 = [
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
    res_r1 = subprocess.run(cmd_r1, capture_output=True, text=True, check=True)
    r1_id = json.loads(res_r1.stdout)["run_id"]
    rec1 = wait_for_terminal(sample_workspace, r1_id)
    assert rec1["status"] == "succeeded"

    # Verify tasks/ is now modified/uncommitted in sample_workspace (due to supervisor transition)
    res_status = subprocess.run(["git", "status", "--porcelain"], cwd=str(sample_workspace), capture_output=True, text=True)
    assert any("tasks/" in ln for ln in res_status.stdout.splitlines()), "Expected tasks/ to have uncommitted changes"

    # Start second execute run (T008) in same repo without committing tasks/
    cmd_r2 = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T008",
        "--mode",
        "execute",
        "--isolation",
        "worktree",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_r2 = subprocess.run(cmd_r2, capture_output=True, text=True, check=True)
    data_r2 = json.loads(res_r2.stdout)
    assert data_r2["ok"] is True
    r2_id = data_r2["run_id"]
    rec2 = wait_for_terminal(sample_workspace, r2_id)
    assert rec2["status"] == "succeeded"


def test_t022_failed_execute_run_transitions_task_to_blocked(sample_workspace: pathlib.Path):
    """Item 5: failed execute run sets task back to blocked recording failure reason."""
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--exit-code", "42"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg failing stub"], cwd=str(sample_workspace), check=True)

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
    assert rec["status"] == "failed"
    assert rec["exit_code"] == 42

    # Check task state
    tasks_dir = sample_workspace / "tasks"
    tasks = discover_emergent_tasks(tasks_dir)
    t = next(t for t in tasks if t["id"] == "T007")
    assert t["canonical_state"] == "blocked"
    # Check that failure reason is recorded in task file / progress log
    task_file_content = pathlib.Path(t["file_path"]).read_text(encoding="utf-8")
    assert "exit code 42" in task_file_content or "failed" in task_file_content


def test_t022_kilo_resume_only_from_original_repo(sample_workspace: pathlib.Path, tmp_path: pathlib.Path):
    """Item 6: Kilo session resume from another repo is refused, naming original repo."""
    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "sess-kilo-orig"]\n'
        + f'resume_argv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "{{session_id}}"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "cfg kilo resume"], cwd=str(sample_workspace), check=True)

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

    # Create a second separate git repository
    other_ws = tmp_path / "other_repo"
    other_ws.mkdir()
    subprocess.run(["git", "init"], cwd=str(other_ws), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(other_ws), check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(other_ws), check=True)
    (other_ws / "dummy.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(other_ws), check=True)
    subprocess.run(["git", "commit", "-m", "init other"], cwd=str(other_ws), check=True)

    # Copy the run record into other_ws
    other_run_dir = other_ws / ".ai-orchestration" / "runs" / run_id
    other_run_dir.mkdir(parents=True, exist_ok=True)
    (other_run_dir / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    (other_run_dir / "prompt.md").write_text("prompt", encoding="utf-8")

    # Attempt to continue from other_ws
    cmd_cont = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--continue",
        run_id,
        "--workspace",
        str(other_ws),
        "--json",
    ]
    res_cont = subprocess.run(cmd_cont, capture_output=True, text=True, check=False)
    assert res_cont.returncode != 0
    data_cont = json.loads(res_cont.stdout)
    assert data_cont["ok"] is False
    assert data_cont["reason"] == "kilo-resume-repo-mismatch"
    assert str(sample_workspace.resolve()) in data_cont["error"]


def test_t022_verify_without_profile_uses_configured_profile(tmp_path: pathlib.Path):
    """Item 7: Verify run without --profile resolves via configured routing/profiles and never defaults to expensive models."""
    ws = tmp_path / "verify_profile_ws"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(ws), check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(ws), check=True)

    tasks_dir = ws / "tasks" / "server"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "T007-verification-gate.md"
    task_file.write_text(
        "# T007\n\n- id: T007\n- title: T\n- category: server\n- priority: P2\n- state: delivered\n- executor: claude\n- paths: -\n- depends-on: -\n- decider: -\n- sources: -\n- handoff: none\n\n## Goal\nGoal\n\n## Verification\npytest\n",
        encoding="utf-8",
    )

    # Config defining ONLY bulk-execution for kilo
    proj_cfg = ws / ".ai-orchestration.local.toml"
    proj_cfg.write_text(
        '[project]\nname = "test"\nprimary_orchestrator = "kilo"\n\n'
        '[routing]\ndefault_executor = "kilo"\ndefault_orchestrator = "kilo"\ndefault_profile = "bulk-execution"\n\n'
        '[verification]\ndefault_mode = "cross-agent"\ncross_agent_order = ["kilo:bulk-execution"]\n\n'
        '[tools.kilo.profiles.bulk-execution]\nmodel = "google/gemini-3.8-flash"\nvariant = "low"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(ws), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(ws), check=True)

    # Preview verify mode without --profile
    cmd_prev = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--workspace",
        str(ws),
        "--json",
    ]
    res_prev = subprocess.run(cmd_prev, capture_output=True, text=True, check=True)
    data_prev = json.loads(res_prev.stdout)
    assert data_prev["ok"] is True
    assert data_prev["profile"] == "bulk-execution", "Must resolve to configured default profile"
    assert data_prev["model"] == "google/gemini-3.8-flash", "Must use configured model, not built-in expensive model"
    assert data_prev["model"] != "google/gemini-4-argon"

    # If --profile deep-reasoning is explicitly requested when not configured, it must fail
    cmd_dr = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--mode",
        "verify",
        "--profile",
        "deep-reasoning",
        "--workspace",
        str(ws),
        "--json",
    ]
    res_dr = subprocess.run(cmd_dr, capture_output=True, text=True, check=False)
    assert res_dr.returncode != 0
    data_dr = json.loads(res_dr.stdout)
    assert data_dr["ok"] is False
    assert data_dr["reason"] == "model-not-configured"


# ---------------------------------------------------------------------------
# Task 07.11: Batch runs for microtasks
# ---------------------------------------------------------------------------

def create_microtask(
    ws: pathlib.Path,
    task_id: str,
    title: str,
    paths: str = "-",
    state: str = "open",
    kind: str = "chore",
) -> pathlib.Path:
    micro_dir = ws / "tasks" / "micro"
    micro_dir.mkdir(parents=True, exist_ok=True)
    readme = micro_dir / "README.md"
    if not readme.exists():
        readme.write_text("# micro tasks\n", encoding="utf-8")
    slug = title.lower().replace(" ", "-")
    task_file = micro_dir / f"{task_id}-{slug}.md"
    content = (
        f"# {task_id} {title}\n\n"
        f"- id: {task_id}\n"
        f"- title: {title}\n"
        f"- kind: {kind}\n"
        f"- priority: P2\n"
        f"- state: {state}\n"
        f"- executor: kilo\n"
        f"- paths: {paths}\n"
        f"- depends-on: -\n"
        f"- size: XS\n"
        f"- labels: -\n\n"
        f"## What\n\n"
        f"Implementation details for {title}.\n"
    )
    task_file.write_text(content, encoding="utf-8")
    return task_file


def test_batch_run_validation_mixed_repo_refused(sample_workspace: pathlib.Path, tmp_path: pathlib.Path):
    other_repo = tmp_path / "other_repo"
    other_repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(other_repo), check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(other_repo), check=True)
    other_file = other_repo / "foo.py"
    other_file.write_text("print('other')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(other_repo), check=True)
    subprocess.run(["git", "commit", "-m", "init other"], cwd=str(other_repo), check=True)

    create_microtask(sample_workspace, "T011", "First microtask", paths="-")
    create_microtask(sample_workspace, "T012", "Second microtask", paths=str(other_file))
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "add microtasks"], cwd=str(sample_workspace), check=True)

    cmd = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--batch",
        "T011,T012",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode != 0
    data = json.loads(res.stdout)
    assert data["ok"] is False
    assert data["reason"] == "mixed-target-repos"


def test_batch_run_validation_non_micro_refused(sample_workspace: pathlib.Path):
    create_microtask(sample_workspace, "T013", "Third microtask")
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "add T013"], cwd=str(sample_workspace), check=True)

    cmd = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--batch",
        "T013,T007",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode != 0
    data = json.loads(res.stdout)
    assert data["ok"] is False
    assert data["reason"] == "non-microtask-refused"


def test_batch_run_validation_exclusivity_and_state(sample_workspace: pathlib.Path):
    create_microtask(sample_workspace, "T014", "Task 14", state="open")
    create_microtask(sample_workspace, "T015", "Task 15", state="open")
    create_microtask(sample_workspace, "T016", "Task 16", state="delivered")
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "add microtasks"], cwd=str(sample_workspace), check=True)

    # Exclusivity with --task
    cmd_excl = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--batch",
        "T014,T015",
        "--task",
        "T014",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_excl = subprocess.run(cmd_excl, capture_output=True, text=True, check=False)
    assert res_excl.returncode != 0
    data_excl = json.loads(res_excl.stdout)
    assert data_excl["reason"] == "mutually-exclusive-targets"

    # State not open or bounced
    cmd_state = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--batch",
        "T014,T016",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_state = subprocess.run(cmd_state, capture_output=True, text=True, check=False)
    assert res_state.returncode != 0
    data_state = json.loads(res_state.stdout)
    assert data_state["reason"] == "invalid-task-state"


def test_batch_run_execution_all_delivered(sample_workspace: pathlib.Path):
    create_microtask(sample_workspace, "T021", "Task 21")
    create_microtask(sample_workspace, "T022", "Task 22")
    create_microtask(sample_workspace, "T023", "Task 23")

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit-msg", "T021: work on 21", "--commit-msg", "T022: work on 22", "--commit-msg", "T023: work on 23", "--final-report", "--exit-code", "0"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "setup batch 21-23"], cwd=str(sample_workspace), check=True)

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--batch",
        "T021,T022,T023",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    data_start = json.loads(res_start.stdout)
    assert data_start["ok"] is True
    assert data_start["is_batch"] is True
    assert data_start["batch_members"] == ["T021", "T022", "T023"]
    run_id = data_start["run_id"]

    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["is_batch"] is True
    assert rec["commits_after_base"] == 3
    assert rec["members"]["T021"]["delivered"] is True
    assert rec["members"]["T022"]["delivered"] is True
    assert rec["members"]["T023"]["delivered"] is True

    tasks_dir = sample_workspace / "tasks"
    for tid in ("T021", "T022", "T023"):
        t = resolve_task_by_id(tasks_dir, tid)
        assert t is not None
        assert t["canonical_state"] == "delivered"


def test_batch_run_execution_partial_commit_and_mark_delivered(sample_workspace: pathlib.Path):
    create_microtask(sample_workspace, "T031", "Task 31")
    create_microtask(sample_workspace, "T032", "Task 32")
    create_microtask(sample_workspace, "T033", "Task 33")

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit-msg", "T031: work on 31", "--commit-msg", "T033: work on 33", "--final-report", "--exit-code", "0"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "setup batch 31-33"], cwd=str(sample_workspace), check=True)

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--batch",
        "T031,T032,T033",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res_start.stdout)["run_id"]

    rec = wait_for_terminal(sample_workspace, run_id)
    assert rec["status"] == "succeeded"
    assert rec["members"]["T031"]["delivered"] is True
    assert rec["members"]["T033"]["delivered"] is True
    assert rec["members"]["T032"]["delivered"] is False
    assert "No commit produced with prefix T032:" in rec["members"]["T032"]["reason"]

    tasks_dir = sample_workspace / "tasks"
    t31 = resolve_task_by_id(tasks_dir, "T031")
    t32 = resolve_task_by_id(tasks_dir, "T032")
    t33 = resolve_task_by_id(tasks_dir, "T033")
    assert t31["canonical_state"] == "delivered"
    assert t33["canonical_state"] == "delivered"
    assert t32["canonical_state"] == "in progress"
    assert "No commit produced with prefix T032:" in t32["state"]

    # Mark delivered per member
    cmd_deliv = [
        str(BIN_AI_ORCH),
        "run",
        "mark-delivered",
        run_id,
        "--member",
        "T032",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_deliv = subprocess.run(cmd_deliv, capture_output=True, text=True, check=True)
    data_deliv = json.loads(res_deliv.stdout)
    assert data_deliv["ok"] is True
    assert "T032" in data_deliv["members"]

    t32_after = resolve_task_by_id(tasks_dir, "T032")
    assert t32_after["canonical_state"] == "delivered"

    rec_after = load_run_record(sample_workspace, run_id)
    assert rec_after["members"]["T032"]["delivered"] is True


def test_batch_run_verify_per_member_and_whole_batch(sample_workspace: pathlib.Path):
    create_microtask(sample_workspace, "T041", "Task 41")
    create_microtask(sample_workspace, "T042", "Task 42")

    proj_cfg = sample_workspace / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit-msg", "T041: 41", "--commit-msg", "T042: 42", "--final-report", "--exit-code", "0"]\n'
        + f'[tools.claude.headless]\nallowed_tools = ["test"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(sample_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "setup batch 41-42"], cwd=str(sample_workspace), check=True)

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--batch",
        "T041,T042",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    exec_run_id = json.loads(res_start.stdout)["run_id"]

    rec_exec = wait_for_terminal(sample_workspace, exec_run_id)
    assert rec_exec["status"] == "succeeded"

    tasks_dir = sample_workspace / "tasks"
    assert resolve_task_by_id(tasks_dir, "T041")["canonical_state"] == "delivered"
    assert resolve_task_by_id(tasks_dir, "T042")["canonical_state"] == "delivered"

    # 1. Verify per member: T041
    cmd_ver_single = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T041",
        "--mode",
        "verify",
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_ver_single = subprocess.run(cmd_ver_single, capture_output=True, text=True, check=True)
    ver_run_id = json.loads(res_ver_single.stdout)["run_id"]
    rec_ver = wait_for_terminal(sample_workspace, ver_run_id)
    assert rec_ver["status"] == "succeeded"
    assert rec_ver["target_run"] == exec_run_id

    cmd_app = [
        str(BIN_AI_ORCH),
        "run",
        "apply-verdict",
        ver_run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_app = subprocess.run(cmd_app, capture_output=True, text=True, check=True)
    assert json.loads(res_app.stdout)["ok"] is True
    assert resolve_task_by_id(tasks_dir, "T041")["canonical_state"] == "verified"

    # 2. Whole batch verify: T042
    cmd_ver_batch = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--batch",
        "T042",
        "--mode",
        "verify",
        "--target-run",
        exec_run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_ver_batch = subprocess.run(cmd_ver_batch, capture_output=True, text=True, check=True)
    batch_ver_run_id = json.loads(res_ver_batch.stdout)["run_id"]
    rec_bver = wait_for_terminal(sample_workspace, batch_ver_run_id)
    assert rec_bver["status"] == "succeeded"
    assert rec_bver["is_batch"] is True

    cmd_app_batch = [
        str(BIN_AI_ORCH),
        "run",
        "apply-verdict",
        batch_ver_run_id,
        "--workspace",
        str(sample_workspace),
        "--json",
    ]
    res_app_b = subprocess.run(cmd_app_batch, capture_output=True, text=True, check=True)
    assert json.loads(res_app_b.stdout)["ok"] is True
    assert resolve_task_by_id(tasks_dir, "T042")["canonical_state"] == "verified"


# ---------------------------------------------------------------------------
# Task 12.13: Run Event Emissions and Supervised Invocation Primitive Tests
# ---------------------------------------------------------------------------

def test_run_events_lifecycle_and_ordering(sample_workspace: pathlib.Path):
    """Verify events emitted per state change: start -> supervisor start -> finished.
    Checks seq ordering, source, subject=run_id, data fields, and timestamps."""
    ws = sample_workspace
    import orchestration_events

    proj_cfg = ws / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "sess-kilo-001", "--exit-code", "0"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--workspace",
        str(ws),
        "--origin-session",
        "sess-orch-main",
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    out = json.loads(res.stdout)
    assert out["ok"] is True
    run_id = out["run_id"]

    # Wait for run to finish
    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    while time.time() < deadline:
        rec = load_run_record(ws, run_id)
        if rec and rec.get("status") in TERMINAL_STATES and rec.get("finalized_at"):
            break
        time.sleep(0.1)

    rec = load_run_record(ws, run_id)
    assert rec["status"] == "succeeded"

    events = orchestration_events.read_events(ws)
    assert len(events) >= 3

    # Check ordering
    assert events[0]["type"] == "run.started"
    assert events[0]["subject"] == run_id
    assert events[0]["source"] == "orchestration_runs"
    assert events[0]["origin_session"] == "sess-orch-main"
    assert events[0]["data"]["status"] == "starting"
    assert events[0]["data"]["task_id"] == "T007"
    assert events[0]["data"]["run_id"] == run_id

    assert events[1]["type"] == "run.started"
    assert events[1]["subject"] == run_id
    assert events[1]["source"] == "orchestration_runs"
    assert events[1]["data"]["status"] == "running"
    assert events[1]["data"]["agent"]["pid"] > 0

    # Last event is run.finished
    fin = next(e for e in events if e["type"] == "run.finished")
    assert fin["subject"] == run_id
    assert fin["source"] == "orchestration_runs"
    assert fin["data"]["status"] == "succeeded"
    assert fin["data"]["exit_code"] == 0
    assert fin["data"]["session_id"] == "sess-kilo-001"
    assert fin["session"] == "sess-kilo-001"

    # Monotonic seq
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)


def test_run_events_no_events_on_preview_and_refusal(sample_workspace: pathlib.Path):
    """Verify that preview commands and refused/failed launches emit zero events."""
    ws = sample_workspace
    import orchestration_events

    # 1. Preview
    cmd_prev = [
        str(BIN_AI_ORCH),
        "run",
        "preview",
        "--task",
        "T007",
        "--workspace",
        str(ws),
        "--json",
    ]
    res_prev = subprocess.run(cmd_prev, capture_output=True, text=True, check=True)
    assert json.loads(res_prev.stdout)["ok"] is True
    assert len(orchestration_events.read_events(ws)) == 0

    # 2. Refusal on missing task
    cmd_bad = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T999",
        "--workspace",
        str(ws),
        "--json",
    ]
    res_bad = subprocess.run(cmd_bad, capture_output=True, text=True)
    assert res_bad.returncode != 0
    assert len(orchestration_events.read_events(ws)) == 0


def test_run_events_cancel(sample_workspace: pathlib.Path):
    """Verify run.cancelled event emitted on run cancel."""
    ws = sample_workspace
    import orchestration_events

    proj_cfg = ws / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--sleep", "30"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--workspace",
        str(ws),
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res.stdout)["run_id"]

    # Wait for run to enter running state
    deadline = time.time() + 30.0
    rec = None
    while time.time() < deadline:
        rec = load_run_record(ws, run_id)
        if rec and rec.get("status") == "running" and (rec.get("agent") or {}).get("pid"):
            break
        time.sleep(0.05)

    cmd_cancel = [
        str(BIN_AI_ORCH),
        "run",
        "cancel",
        run_id,
        "--workspace",
        str(ws),
        "--json",
    ]
    res_cancel = subprocess.run(cmd_cancel, capture_output=True, text=True, check=True)
    assert json.loads(res_cancel.stdout)["ok"] is True

    canc_events = orchestration_events.read_events(ws, types=["run.cancelled"])
    assert len(canc_events) == 1
    assert canc_events[0]["subject"] == run_id
    assert canc_events[0]["source"] == "orchestration_runs"
    assert canc_events[0]["data"]["status"] == "cancelled"



def test_run_events_lost_reconciliation(sample_workspace: pathlib.Path):
    """Verify run.lost event emitted when reconciling a dead supervisor run."""
    ws = sample_workspace
    import orchestration_events

    record = create_run_record(
        run_id="20261018-020000-T007-kilo-0001",
        task_id="T007",
        mode="execute",
        tool="kilo",
        profile="bulk-execution",
        model="test",
        variant=None,
        effort=None,
        requested_by="cli",
        workspace=str(ws),
        cwd=str(ws),
        isolation="none",
        task_bundle_sha256="",
        argv_display=["kilo"],
        plan_hash="",
    )
    record["status"] = "running"
    record["supervisor"] = {"pid": 99999999, "start_time": "Sat Oct 17 00:00:00 2026"}
    save_run_record(ws, record)

    reconcile(record, workspace=ws)

    lost_events = orchestration_events.read_events(ws, types=["run.lost"])
    assert len(lost_events) == 1
    assert lost_events[0]["subject"] == "20261018-020000-T007-kilo-0001"
    assert lost_events[0]["source"] == "orchestration_runs"
    assert lost_events[0]["data"]["status"] == "lost"


def test_run_events_mark_delivered(sample_workspace: pathlib.Path):
    """Verify run.delivered event emitted on mark-delivered."""
    ws = sample_workspace
    import orchestration_events

    proj_cfg = ws / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--exit-code", "0"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--workspace",
        str(ws),
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res.stdout)["run_id"]

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    while time.time() < deadline:
        rec = load_run_record(ws, run_id)
        if rec and rec.get("status") == "succeeded":
            break
        time.sleep(0.1)

    cmd_deliv = [
        str(BIN_AI_ORCH),
        "run",
        "mark-delivered",
        run_id,
        "--workspace",
        str(ws),
        "--json",
    ]
    res_deliv = subprocess.run(cmd_deliv, capture_output=True, text=True, check=True)
    assert json.loads(res_deliv.stdout)["ok"] is True

    deliv_events = orchestration_events.read_events(ws, types=["run.delivered"])
    assert len(deliv_events) == 1
    assert deliv_events[0]["subject"] == run_id
    assert deliv_events[0]["source"] == "orchestration_runs"
    assert deliv_events[0]["data"]["task_id"] == "T007"
    assert deliv_events[0]["data"]["state"] == "delivered"


def test_run_events_apply_verdict(sample_workspace: pathlib.Path):
    """Verify verdict.applied event emitted on apply-verdict."""
    ws = sample_workspace
    import orchestration_events

    # First deliver task
    task_file = ws / "tasks" / "server" / "T007-verification-gate.md"
    content = task_file.read_text(encoding="utf-8")
    task_file.write_text(content.replace("- state: open", "- state: delivered"), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(ws), check=True)
    subprocess.run(["git", "commit", "-m", "deliver T007"], cwd=str(ws), check=True)

    proj_cfg = ws / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.claude.headless]\nallowed_tools = ["test"]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--verdict", "verified"]\n',
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
        "claude",
        "--workspace",
        str(ws),
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    ver_run_id = json.loads(res.stdout)["run_id"]

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    while time.time() < deadline:
        rec = load_run_record(ws, ver_run_id)
        if rec and rec.get("status") == "succeeded":
            break
        time.sleep(0.1)

    cmd_apply = [
        str(BIN_AI_ORCH),
        "run",
        "apply-verdict",
        ver_run_id,
        "--workspace",
        str(ws),
        "--json",
    ]
    res_apply = subprocess.run(cmd_apply, capture_output=True, text=True, check=True)
    assert json.loads(res_apply.stdout)["ok"] is True

    verdict_events = orchestration_events.read_events(ws, types=["verdict.applied"])
    assert len(verdict_events) == 1
    assert verdict_events[0]["subject"] == ver_run_id
    assert verdict_events[0]["source"] == "orchestration_runs"
    assert verdict_events[0]["data"]["task_id"] == "T007"
    assert verdict_events[0]["data"]["verdict"] == "verified"


def test_run_events_cleanup(sample_workspace: pathlib.Path):
    """Verify run.cleaned event emitted on cleanup."""
    ws = sample_workspace
    import orchestration_events

    record = create_run_record(
        run_id="20261018-020000-T007-kilo-0002",
        task_id="T007",
        mode="execute",
        tool="kilo",
        profile="bulk-execution",
        model="test",
        variant=None,
        effort=None,
        requested_by="cli",
        workspace=str(ws),
        cwd=str(ws),
        isolation="worktree",
        task_bundle_sha256="",
        argv_display=["kilo"],
        plan_hash="",
    )
    record["status"] = "succeeded"
    save_run_record(ws, record)

    cmd_cleanup = [
        str(BIN_AI_ORCH),
        "run",
        "cleanup",
        "20261018-020000-T007-kilo-0002",
        "--workspace",
        str(ws),
        "--json",
    ]
    res = subprocess.run(cmd_cleanup, capture_output=True, text=True, check=True)
    assert json.loads(res.stdout)["ok"] is True

    clean_events = orchestration_events.read_events(ws, types=["run.cleaned"])
    assert len(clean_events) == 1
    assert clean_events[0]["subject"] == "20261018-020000-T007-kilo-0002"
    assert clean_events[0]["source"] == "orchestration_runs"
    assert clean_events[0]["data"]["cleaned"] is True


def test_run_events_batch_member_outcomes(sample_workspace: pathlib.Path):
    """Verify run.batch_member events emitted for batch member tasks."""
    ws = sample_workspace
    import orchestration_events

    create_microtask(ws, "T011", "Task 11")
    create_microtask(ws, "T012", "Task 12")
    subprocess.run(["git", "add", "."], cwd=str(ws), check=True)
    subprocess.run(["git", "commit", "-m", "add batch tasks"], cwd=str(ws), check=True)

    proj_cfg = ws / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit-msg", "T011: commit for 11", "--final-report", "--exit-code", "0"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--batch",
        "T011,T012",
        "--workspace",
        str(ws),
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    batch_run_id = json.loads(res.stdout)["run_id"]

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    while time.time() < deadline:
        rec = load_run_record(ws, batch_run_id)
        if rec and rec.get("status") == "succeeded":
            break
        time.sleep(0.1)

    member_events = orchestration_events.read_events(ws, types=["run.batch_member"])
    assert len(member_events) == 2
    t11_ev = next(e for e in member_events if e["data"]["task_id"] == "T011")
    t12_ev = next(e for e in member_events if e["data"]["task_id"] == "T012")
    assert t11_ev["data"]["delivered"] is True
    assert t11_ev["data"]["state"] == "delivered"
    assert t12_ev["data"]["delivered"] is False
    assert t12_ev["data"]["state"] == "in progress"


def test_run_events_question_filed_by_run(sample_workspace: pathlib.Path):
    """Verify question.asked emitted when run files a question."""
    ws = sample_workspace
    import orchestration_events

    q_json = {
        "question": "Which database should we use?",
        "context": "Need storage engine for events",
        "options": ["sqlite", "postgres"],
        "recommended": "sqlite",
    }
    proj_cfg = ws / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--question", {json.dumps(json.dumps(q_json))}, "--exit-code", "0"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--workspace",
        str(ws),
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res.stdout)["run_id"]

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    while time.time() < deadline:
        rec = load_run_record(ws, run_id)
        if rec and rec.get("status") == "succeeded":
            break
        time.sleep(0.1)

    q_events = orchestration_events.read_events(ws, types=["question.asked"])
    assert len(q_events) >= 1
    assert q_events[0]["data"]["origin_run"] == run_id
    assert q_events[0]["data"]["question"] == "Which database should we use?"


def test_run_events_session_filter(sample_workspace: pathlib.Path):
    """Verify events tail --session filter matches runs by session."""
    ws = sample_workspace

    proj_cfg = ws / ".ai-orchestration.local.toml"
    orig_cfg = proj_cfg.read_text(encoding="utf-8")
    proj_cfg.write_text(
        orig_cfg
        + f'\n[tools.kilo.headless]\nargv = ["{sys.executable}", "{STUB_AGENT}", "--commit", "--final-report", "--session-id", "sess-kilo-target", "--exit-code", "0"]\n',
        encoding="utf-8",
    )

    cmd_start = [
        str(BIN_AI_ORCH),
        "run",
        "start",
        "--task",
        "T007",
        "--workspace",
        str(ws),
        "--origin-session",
        "sess-origin-xyz",
        "--json",
    ]
    res = subprocess.run(cmd_start, capture_output=True, text=True, check=True)
    run_id = json.loads(res.stdout)["run_id"]

    deadline = time.time() + 60.0  # generous under load; loops break as soon as the state is reached
    while time.time() < deadline:
        rec = load_run_record(ws, run_id)
        if rec and rec.get("status") == "succeeded" and rec.get("finalized_at"):
            break
        time.sleep(0.1)

    # Filter by origin-session
    cmd_tail_orig = [
        str(BIN_AI_ORCH),
        "events",
        "tail",
        "--workspace",
        str(ws),
        "--session",
        "sess-origin-xyz",
        "--json",
    ]
    res_orig = subprocess.run(cmd_tail_orig, capture_output=True, text=True, check=True)
    out_orig = json.loads(res_orig.stdout)
    assert out_orig["ok"] is True
    assert out_orig["count"] >= 2
    assert all(e["subject"] == run_id for e in out_orig["events"])

    # Filter by agent session-id
    cmd_tail_agent = [
        str(BIN_AI_ORCH),
        "events",
        "tail",
        "--workspace",
        str(ws),
        "--session",
        "sess-kilo-target",
        "--json",
    ]
    res_agent = subprocess.run(cmd_tail_agent, capture_output=True, text=True, check=True)
    out_agent = json.loads(res_agent.stdout)
    assert out_agent["ok"] is True
    assert out_agent["count"] >= 1
    assert any(e["type"] == "run.finished" for e in out_agent["events"])




SYNTHETIC_KILO_AGENT_LIST = """ask (primary)
[
  {"permission": "*", "action": "allow", "pattern": "*"},
  {"permission": "edit", "pattern": "*", "action": "allow"},
  {"permission": "bash", "pattern": "*", "action": "allow"},
  {"permission": "edit", "pattern": "*", "action": "deny"},
  {"permission": "bash", "pattern": "*", "action": "deny"},
  {"permission": "bash", "pattern": "cp *", "action": "allow"},
  {"permission": "webfetch", "pattern": "*", "action": "allow"},
  {"permission": "codex-mcp_*", "pattern": "*", "action": "ask"}
]
aio-unattended (primary)
[
  {"permission": "*", "action": "allow", "pattern": "*"},
  {"permission": "edit", "pattern": "*", "action": "allow"},
  {"permission": "bash", "pattern": "*", "action": "allow"},
  {"permission": "task", "pattern": "*", "action": "allow"},
  {"permission": "*", "pattern": "*", "action": "deny"},
  {"permission": "read", "pattern": "*", "action": "allow"},
  {"permission": "glob", "pattern": "*", "action": "allow"},
  {"permission": "grep", "pattern": "*", "action": "allow"},
  {"permission": "list", "pattern": "*", "action": "allow"}
]
leaky (primary)
[
  {"permission": "*", "pattern": "*", "action": "deny"},
  {"permission": "read", "pattern": "*", "action": "allow"},
  {"permission": "bash", "pattern": "*", "action": "allow"}
]
"""


def test_kilo_agent_restriction_uses_last_matching_rule():
    """T028: Kilo merges global permissions into every agent and evaluates with "last matching rule wins";
    only an agent whose effective permissions deny every probe is accepted for unattended turns."""
    import orchestration_runs as _runs

    ok, reason = _runs.kilo_agent_is_restricted("aio-unattended", SYNTHETIC_KILO_AGENT_LIST)
    assert ok, reason
    ok_ask, reason_ask = _runs.kilo_agent_is_restricted("ask", SYNTHETIC_KILO_AGENT_LIST)
    assert not ok_ask and "bash cp a b" in reason_ask
    ok_leaky, reason_leaky = _runs.kilo_agent_is_restricted("leaky", SYNTHETIC_KILO_AGENT_LIST)
    assert not ok_leaky and "bash rm -rf build" in reason_leaky
    ok_missing, reason_missing = _runs.kilo_agent_is_restricted("nope", SYNTHETIC_KILO_AGENT_LIST)
    assert not ok_missing and "not installed" in reason_missing


def test_kilo_agent_command_preview_and_apply(tmp_path: pathlib.Path):
    """T028: `ai-orch run kilo-agent` previews by default and writes only with --apply (never replacing silently)."""
    env = dict(os.environ, AI_ORCH_KILO_AGENT_DIR=str(tmp_path))
    prev = subprocess.run([str(BIN_AI_ORCH), "run", "kilo-agent", "--json"], capture_output=True, text=True, env=env, check=True)
    assert json.loads(prev.stdout)["plan"]["action"] == "create"
    assert not (tmp_path / "aio-unattended.md").exists()
    subprocess.run([str(BIN_AI_ORCH), "run", "kilo-agent", "--apply", "--json"], capture_output=True, text=True, env=env, check=True)
    content = (tmp_path / "aio-unattended.md").read_text(encoding="utf-8")
    assert '"*": deny' in content and "read: allow" in content
    (tmp_path / "aio-unattended.md").write_text("changed", encoding="utf-8")
    refused = subprocess.run([str(BIN_AI_ORCH), "run", "kilo-agent", "--apply", "--json"], capture_output=True, text=True, env=env)
    assert refused.returncode == 1
    assert (tmp_path / "aio-unattended.md").read_text(encoding="utf-8") == "changed"


def test_19_4_new_run_has_host_and_existing_runs_without_host_remain_valid(
    sample_workspace: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Task 19.4: a new run has host in run.json and events; existing runs without host remain valid."""
    import orchestration_runs as _runs

    cfg_file = tmp_path / "orchestration.toml"
    cfg_file.write_text('[host]\nid = "alf_ubuntu"\n', encoding="utf-8")
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(cfg_file))

    rec = _runs.create_run_record(
        run_id="20261029-120000-T001-kilo-1234",
        task_id="T001",
        mode="execute",
        tool="kilo",
        profile="bulk-execution",
        model="google/gemini-3-flash-preview",
        variant=None,
        effort=None,
        requested_by="owner",
        workspace=str(sample_workspace),
        cwd=str(sample_workspace),
        isolation="inplace",
        task_bundle_sha256="a" * 64,
        argv_display=["kilo", "run"],
        plan_hash="b" * 64,
    )
    assert rec["host"] == "alf_ubuntu"

    # Existing run.json without 'host' remains valid when loaded/listed/reconciled
    legacy_run_id = "20261029-110000-T001-kilo-abcd"
    run_dir = sample_workspace / ".ai-orchestration" / "runs" / legacy_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    legacy_rec = dict(rec)
    legacy_rec["run_id"] = legacy_run_id
    legacy_rec["status"] = "succeeded"
    legacy_rec["exit_code"] = 0
    legacy_rec.pop("host", None)
    (run_dir / "run.json").write_text(json.dumps(legacy_rec, indent=2), encoding="utf-8")

    loaded = _runs.load_run_record(sample_workspace, legacy_run_id)
    assert loaded is not None
    assert loaded["run_id"] == legacy_run_id
    assert "host" not in loaded
    reconciled = _runs.reconcile(loaded, sample_workspace)
    assert reconciled["status"] == "succeeded"
    all_runs = _runs.list_run_records(sample_workspace)
    assert any(r["run_id"] == legacy_run_id for r in all_runs)

    # Also verify a real launched run via CLI writes 'host' in run.json
    env = dict(os.environ, AI_ORCHESTRATION_CONFIG=str(cfg_file))
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
    res_start = subprocess.run(cmd_start, capture_output=True, text=True, env=env, check=True)
    new_run_id = json.loads(res_start.stdout)["run_id"]
    term_rec = wait_for_terminal(sample_workspace, new_run_id)
    assert term_rec["host"] == "alf_ubuntu"

