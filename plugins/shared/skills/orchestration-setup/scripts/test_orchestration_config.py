#!/usr/bin/env python3
"""Unit tests for orchestration_config.py."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import orchestration_config as oc  # noqa: E402

SCRIPT_PATH = SCRIPT_DIR / "orchestration_config.py"
REPO_ROOT = SCRIPT_DIR.parents[4]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_init_global_and_project_deep_merge(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    res_g = run_cli("--global-config", str(global_cfg_path), "--json", "init-global")
    assert res_g.returncode == 0
    payload_g = json.loads(res_g.stdout)
    assert payload_g["ok"] is True
    assert global_cfg_path.exists()

    res_p = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "init-project",
        "--workspace",
        str(workspace),
        "--name",
        "demo-project",
        "--orchestrator",
        "claude",
        "--executor",
        "kilo",
        "--verification-mode",
        "cross-agent",
    )
    assert res_p.returncode == 0
    payload_p = json.loads(res_p.stdout)
    assert payload_p["ok"] is True
    # Ensure project agent config is stored outside the repo (never inside versioned tasks/)
    assert not (workspace / "tasks" / "orchestration.toml").exists()
    assert pathlib.Path(payload_p["path"]).exists()
    assert not pathlib.Path(payload_p["path"]).is_relative_to(workspace)

    merged, meta = oc.resolve_config(global_cfg_path, workspace)
    assert meta["global_config_exists"] is True
    assert meta["project_config_exists"] is True
    assert merged["project"]["name"] == "demo-project"
    assert merged["project"]["primary_orchestrator"] == "claude"
    assert merged["routing"]["default_executor"] == "kilo"
    assert merged["verification"]["default_mode"] == "cross-agent"
    # Deep merge preserves global tool definitions while applying project overrides
    assert "kilo" in merged["tools"]
    assert "claude" in merged["tools"]


def test_set_profile_global_and_project_scope(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Global scope update
    res_global = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-profile",
        "kilo",
        "deep-reasoning",
        "--model",
        "custom/reasoner-v1",
        "--variant",
        "high",
        "--basis",
        "host-metadata",
        "--scope",
        "global",
    )
    assert res_global.returncode == 0
    out_global = json.loads(res_global.stdout)
    assert out_global["ok"] is True
    assert out_global["entry"]["model"] == "custom/reasoner-v1"
    assert out_global["entry"]["variant"] == "high"
    assert out_global["entry"]["basis"] == "host-metadata"

    # Project scope override
    res_proj = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-profile",
        "kilo",
        "bulk-execution",
        "--model",
        "custom/fast-coder-v2",
        "--effort",
        "medium",
        "--basis",
        "operator-stated",
        "--scope",
        "project",
        "--workspace",
        str(workspace),
    )
    assert res_proj.returncode == 0
    out_proj = json.loads(res_proj.stdout)
    assert out_proj["ok"] is True

    merged, _ = oc.resolve_config(global_cfg_path, workspace)
    assert merged["tools"]["kilo"]["profiles"]["deep-reasoning"]["model"] == "custom/reasoner-v1"
    assert merged["tools"]["kilo"]["profiles"]["bulk-execution"]["model"] == "custom/fast-coder-v2"
    assert merged["tools"]["kilo"]["profiles"]["bulk-execution"]["effort"] == "medium"


def test_validate_catches_xhigh_on_opus_4_6_and_invalid_verification_mode(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    workspace = tmp_path / "workspace"
    (workspace / "tasks").mkdir(parents=True)

    run_cli("--global-config", str(global_cfg_path), "init-global")
    # Pin xhigh on opus-4.6 in global config
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "set-profile",
        "claude",
        "deep-reasoning",
        "--model",
        "claude-opus-4.6",
        "--effort",
        "xhigh",
        "--scope",
        "global",
    )

    # Write invalid verification.default_mode in unversioned project config
    proj_toml = oc.find_project_config_path(workspace, global_cfg_path)
    proj_toml.parent.mkdir(parents=True, exist_ok=True)
    proj_toml.write_text(
        '[verification]\ndefault_mode = "invalid-mode"\n',
        encoding="utf-8",
    )

    res = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "validate",
        "--workspace",
        str(workspace),
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    error_text = "\n".join(payload["errors"])
    assert "xhigh" in error_text
    assert "claude-opus-4.6" in error_text
    assert "invalid-mode" in error_text


def test_validate_kit_internal_plugins(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    res = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "validate",
        "--plugin-dir",
        str(REPO_ROOT / "plugins" / "architect-side"),
        "--plugin-dir",
        str(REPO_ROOT / "plugins" / "executor-side"),
        "--plugin-dir",
        str(REPO_ROOT / "plugins" / "shared"),
    )
    assert res.returncode == 0, res.stdout + res.stderr
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["kit_internal_ok"] is True


def test_render_agents_md_use_case_1_single_framework_and_use_case_2_multi_framework(
    tmp_path: pathlib.Path,
) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    # --- Use Case 1: Single-Framework Native (kilo == kilo, independent-session) ---
    ws1 = tmp_path / "uc1_kilo_native"
    ws1.mkdir()
    agents1 = ws1 / "AGENTS.md"
    agents1.write_text(
        "# Custom Header\n\nProject-specific intro paragraph.\n\n"
        "<!-- BEGIN ai-orchestration -->\nOLD STALE BLOCK\n<!-- END ai-orchestration -->\n\n"
        "## Custom Footer\nKeep this footer intact.\n",
        encoding="utf-8",
    )

    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws1),
        "--name",
        "uc1-app",
        "--orchestrator",
        "kilo",
        "--executor",
        "kilo",
        "--verification-mode",
        "independent-session",
    )

    # --check before --apply should fail (out of sync)
    chk_before = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws1),
        "--check",
    )
    assert chk_before.returncode == 1

    # --apply updates in place
    apply_res = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws1),
        "--apply",
    )
    assert apply_res.returncode == 0
    content1 = agents1.read_text(encoding="utf-8")
    assert "# Custom Header" in content1
    assert "Project-specific intro paragraph." in content1
    assert "## Custom Footer\nKeep this footer intact." in content1
    assert "OLD STALE BLOCK" not in content1
    assert '`primary_orchestrator = "kilo"`, `default_executor = "kilo"`, `verification_mode = "independent-session"`' in content1
    assert '`agent_manager(mode="worktree")`' in content1
    # In Single-Framework Native mode, MCP implement tool note is omitted
    assert 'kilo_implement(isolation="worktree")' not in content1

    # --check after --apply should pass
    chk_after = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws1),
        "--check",
    )
    assert chk_after.returncode == 0

    # --- Use Case 2: Multi-Framework MCP (orchestrator = claude, executor = kilo, cross-agent) ---
    ws2 = tmp_path / "uc2_multi_mcp"
    ws2.mkdir()
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws2),
        "--name",
        "uc2-app",
        "--orchestrator",
        "claude",
        "--executor",
        "kilo",
        "--verification-mode",
        "cross-agent",
    )
    apply_res2 = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws2),
        "--apply",
    )
    assert apply_res2.returncode == 0
    content2 = (ws2 / "AGENTS.md").read_text(encoding="utf-8")
    assert '`primary_orchestrator = "claude"`, `default_executor = "kilo"`, `verification_mode = "cross-agent"`' in content2
    assert 'kilo_implement(isolation="worktree")' in content2
    assert "**claude**:" in content2
    assert "**kilo**:" in content2
