#!/usr/bin/env python3
"""Unit tests for orchestration_config.py."""
from __future__ import annotations

import difflib
import hashlib
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


def test_surgical_update_difflib_preserves_comments_and_formatting(tmp_path: pathlib.Path) -> None:
    cfg_file = tmp_path / "global" / "orchestration.toml"
    cfg_file.parent.mkdir(parents=True)

    initial_toml = """# Top-level comment
schema_version = 1
last_verified = "2026-10-15"

# Routing configuration
[routing]
default_orchestrator = "kilo" # inline comment on orchestrator
default_executor = "kilo"
default_profile = "bulk-execution"

# Verification policy
[verification]
default_mode = "cross-agent" # inline comment on verification

# Unrelated section with comments
[unrelated]
# comment in unrelated
key1 = "value1" # inline comment on key1
key2 = 42

[tools.kilo]
enabled = true

[tools.kilo.profiles.deep-reasoning]
model = "google/gemini-4-argon" # inline comment on model
variant = "high"
basis = "operator-stated"

[tools.claude]
enabled = true
"""
    cfg_file.write_text(initial_toml, encoding="utf-8")

    # 1. Test set-routing surgical edit
    res_sr = run_cli(
        "--global-config",
        str(cfg_file),
        "set-routing",
        "--orchestrator",
        "claude",
        "--scope",
        "global",
    )
    assert res_sr.returncode == 0, res_sr.stdout + res_sr.stderr

    after_routing = cfg_file.read_text(encoding="utf-8")
    diff_routing = [
        l
        for l in difflib.unified_diff(
            initial_toml.splitlines(),
            after_routing.splitlines(),
            lineterm="",
        )
        if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
    ]
    # Assert difflib: changed lines count is 2 (1 removed, 1 added) and content is ONLY the target key line
    assert len(diff_routing) == 2
    assert diff_routing[0] == '-default_orchestrator = "kilo" # inline comment on orchestrator'
    assert diff_routing[1] == '+default_orchestrator = "claude" # inline comment on orchestrator'

    # 2. Test set-profile surgical edit
    res_sp = run_cli(
        "--global-config",
        str(cfg_file),
        "set-profile",
        "kilo",
        "deep-reasoning",
        "--model",
        "custom/reasoner-v9",
        "--scope",
        "global",
    )
    assert res_sp.returncode == 0, res_sp.stdout + res_sp.stderr

    after_profile = cfg_file.read_text(encoding="utf-8")
    diff_profile = [
        l
        for l in difflib.unified_diff(
            after_routing.splitlines(),
            after_profile.splitlines(),
            lineterm="",
        )
        if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
    ]
    assert len(diff_profile) == 2
    assert diff_profile[0] == '-model = "google/gemini-4-argon" # inline comment on model'
    assert diff_profile[1] == '+model = "custom/reasoner-v9" # inline comment on model'


def test_insert_missing_key_and_missing_table(tmp_path: pathlib.Path) -> None:
    sample_toml = """# Initial config
[routing]
default_orchestrator = "kilo"

[unrelated]
foo = "bar"
"""
    # 1. Insert key into existing table
    updated1 = oc.set_toml_value(sample_toml, ["routing"], "default_executor", "claude")
    parsed1 = oc.tomllib.loads(updated1)
    assert parsed1["routing"]["default_orchestrator"] == "kilo"
    assert parsed1["routing"]["default_executor"] == "claude"
    assert parsed1["unrelated"]["foo"] == "bar"
    lines1 = updated1.splitlines()
    assert 'default_executor = "claude"' in lines1
    assert lines1.index('default_executor = "claude"') < lines1.index("[unrelated]")

    # 2. Insert new table at end of file
    updated2 = oc.set_toml_value(updated1, ["verification"], "default_mode", "independent-session")
    parsed2 = oc.tomllib.loads(updated2)
    assert parsed2["verification"]["default_mode"] == "independent-session"
    assert "[verification]" in updated2
    assert 'default_mode = "independent-session"' in updated2


def test_headless_schema_validation(tmp_path: pathlib.Path) -> None:
    valid_cfg = {
        "tools": {
            "kilo": {
                "enabled": True,
                "profiles": {p: {"model": "m"} for p in oc.PROFILES},
                "headless": {
                    "argv": ["kilo", "run", "--dir", "{cwd}", "-m", "{model}", "-f", "{prompt_file}"],
                    "resume_argv": ["kilo", "run", "-s", "{session_id}", "-f", "{prompt_file}"],
                    "prompt_via": "file",
                    "permission_mode": "acceptEdits",
                    "sandbox": "workspace-write",
                    "allowed_tools": ["edit", "bash"],
                },
            }
        }
    }
    errors, warnings = oc.validate_config(valid_cfg)
    assert errors == [], f"Expected no errors but got: {errors}"

    # Invalid placeholder in argv
    invalid_argv_cfg = {
        "tools": {
            "kilo": {
                "enabled": True,
                "profiles": {p: {"model": "m"} for p in oc.PROFILES},
                "headless": {
                    "argv": ["kilo", "run", "--bad", "{bad_placeholder}"],
                },
            }
        }
    }
    errors, _ = oc.validate_config(invalid_argv_cfg)
    assert any("{bad_placeholder}" in e for e in errors)

    # Invalid placeholder in resume_argv
    invalid_resume_cfg = {
        "tools": {
            "kilo": {
                "enabled": True,
                "profiles": {p: {"model": "m"} for p in oc.PROFILES},
                "headless": {
                    "resume_argv": ["kilo", "resume", "{invalid_resume}"],
                },
            }
        }
    }
    errors, _ = oc.validate_config(invalid_resume_cfg)
    assert any("{invalid_resume}" in e for e in errors)

    # Invalid prompt_via
    invalid_pv_cfg = {
        "tools": {
            "kilo": {
                "enabled": True,
                "profiles": {p: {"model": "m"} for p in oc.PROFILES},
                "headless": {
                    "prompt_via": "pipe",
                },
            }
        }
    }
    errors, _ = oc.validate_config(invalid_pv_cfg)
    assert any("prompt_via" in e for e in errors)


def test_rendered_agents_md_block_names_real_project_config_path(tmp_path: pathlib.Path) -> None:
    workspace = tmp_path / "my_project"
    workspace.mkdir()
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    cfg, _ = oc.resolve_config(global_cfg_path, workspace)

    expected_proj_path = oc.find_project_config_path(workspace, global_cfg_path)
    block = oc.render_agents_md_block(cfg, workspace, global_cfg_path)

    assert str(expected_proj_path) in block
    assert "tasks/orchestration.toml" not in block


def test_set_routing_validation_and_refusals(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    # 1. At least one flag required
    res_none = run_cli("--global-config", str(global_cfg_path), "set-routing", "--scope", "global")
    assert res_none.returncode != 0

    # 2. Unknown tool refused
    res_unknown = run_cli(
        "--global-config",
        str(global_cfg_path),
        "set-routing",
        "--orchestrator",
        "unknown-tool-xyz",
        "--scope",
        "global",
    )
    assert res_unknown.returncode != 0
    assert "unknown or disabled" in (res_unknown.stderr + res_unknown.stdout)

    # 3. Disabled tool refused
    global_toml = global_cfg_path.read_text(encoding="utf-8")
    global_toml = oc.set_toml_value(global_toml, ["tools", "codex"], "enabled", False)
    global_cfg_path.write_text(global_toml, encoding="utf-8")

    res_disabled = run_cli(
        "--global-config",
        str(global_cfg_path),
        "set-routing",
        "--executor",
        "codex",
        "--scope",
        "global",
    )
    assert res_disabled.returncode != 0
    assert "unknown or disabled" in (res_disabled.stderr + res_disabled.stdout)

    # 4. Invalid profile refused
    res_profile = run_cli(
        "--global-config",
        str(global_cfg_path),
        "set-routing",
        "--default-profile",
        "super-thinking",
        "--scope",
        "global",
    )
    assert res_profile.returncode != 0

    # 5. Invalid verification mode refused
    res_mode = run_cli(
        "--global-config",
        str(global_cfg_path),
        "set-routing",
        "--verification-mode",
        "no-verification",
        "--scope",
        "global",
    )
    assert res_mode.returncode != 0

    # 6. Valid set-routing in project scope
    workspace = tmp_path / "ws_routing"
    workspace.mkdir()
    res_valid = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-routing",
        "--orchestrator",
        "claude",
        "--executor",
        "kilo",
        "--default-profile",
        "orchestration",
        "--verification-mode",
        "panel",
        "--scope",
        "project",
        "--workspace",
        str(workspace),
    )
    assert res_valid.returncode == 0
    payload = json.loads(res_valid.stdout)
    assert payload["ok"] is True
    assert payload["routing"]["default_orchestrator"] == "claude"
    assert payload["routing"]["default_executor"] == "kilo"
    assert payload["routing"]["default_profile"] == "orchestration"
    assert payload["verification"]["default_mode"] == "panel"

    merged, meta = oc.resolve_config(global_cfg_path, workspace)
    assert merged["routing"]["default_orchestrator"] == "claude"
    assert merged["routing"]["default_executor"] == "kilo"
    assert merged["routing"]["default_profile"] == "orchestration"
    assert merged["verification"]["default_mode"] == "panel"


def test_set_routing_and_set_profile_diff_preview(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    before_bytes = global_cfg_path.read_bytes()
    expected_hash = hashlib.sha256(before_bytes).hexdigest()

    # 1. set-routing with --diff writes nothing and diff contains only the target line
    res_diff_sr = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-routing",
        "--orchestrator",
        "claude",
        "--scope",
        "global",
        "--diff",
    )
    assert res_diff_sr.returncode == 0, res_diff_sr.stdout + res_diff_sr.stderr
    assert global_cfg_path.read_bytes() == before_bytes  # bytes on disk unchanged!

    payload_sr = json.loads(res_diff_sr.stdout)
    assert payload_sr["ok"] is True
    assert payload_sr["changed"] is True
    assert payload_sr["path"] == str(global_cfg_path)
    assert payload_sr["hash"] == expected_hash

    diff_lines_sr = [
        l
        for l in payload_sr["diff"].splitlines()
        if (l.startswith("+") or l.startswith("-")) and not (l.startswith("+++") or l.startswith("---"))
    ]
    assert len(diff_lines_sr) == 2
    assert diff_lines_sr[0] == '-default_orchestrator = "kilo"'
    assert diff_lines_sr[1] == '+default_orchestrator = "claude"'

    # When no values change, changed is False and diff is empty
    res_no_change = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-routing",
        "--orchestrator",
        "kilo",
        "--scope",
        "global",
        "--diff",
    )
    assert res_no_change.returncode == 0
    payload_nc = json.loads(res_no_change.stdout)
    assert payload_nc["ok"] is True
    assert payload_nc["changed"] is False
    assert payload_nc["diff"] == ""

    # 2. set-profile with --diff writes nothing and diff contains only the target line
    res_diff_sp = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-profile",
        "kilo",
        "deep-reasoning",
        "--model",
        "custom/reasoner-v99",
        "--scope",
        "global",
        "--diff",
    )
    assert res_diff_sp.returncode == 0, res_diff_sp.stdout + res_diff_sp.stderr
    assert global_cfg_path.read_bytes() == before_bytes  # still unchanged!

    payload_sp = json.loads(res_diff_sp.stdout)
    assert payload_sp["ok"] is True
    assert payload_sp["changed"] is True
    assert payload_sp["path"] == str(global_cfg_path)
    assert payload_sp["hash"] == expected_hash

    diff_lines_sp = [
        l
        for l in payload_sp["diff"].splitlines()
        if (l.startswith("+") or l.startswith("-")) and not (l.startswith("+++") or l.startswith("---"))
    ]
    assert len(diff_lines_sp) == 2
    assert diff_lines_sp[0] == '-model = "google/gemini-4-argon"'
    assert diff_lines_sp[1] == '+model = "custom/reasoner-v99"'


def test_expect_hash_match_and_mismatch(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    initial_bytes = global_cfg_path.read_bytes()
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()

    # 1. Mismatch refuses and leaves file untouched
    res_mismatch = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-routing",
        "--orchestrator",
        "claude",
        "--scope",
        "global",
        "--expect-hash",
        "deadbeef" * 8,
    )
    assert res_mismatch.returncode != 0
    payload_mismatch = json.loads(res_mismatch.stdout)
    assert payload_mismatch["ok"] is False
    assert "hash mismatch" in payload_mismatch["error"]
    assert global_cfg_path.read_bytes() == initial_bytes  # file untouched!

    # 2. Match succeeds and writes file
    res_match = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-routing",
        "--orchestrator",
        "claude",
        "--scope",
        "global",
        "--expect-hash",
        initial_hash,
    )
    assert res_match.returncode == 0, res_match.stdout + res_match.stderr
    payload_match = json.loads(res_match.stdout)
    assert payload_match["ok"] is True
    assert global_cfg_path.read_bytes() != initial_bytes
    assert 'default_orchestrator = "claude"' in global_cfg_path.read_text(encoding="utf-8")

    # 3. set-profile mismatch also refuses and leaves file untouched
    current_bytes = global_cfg_path.read_bytes()
    res_sp_mismatch = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "set-profile",
        "kilo",
        "deep-reasoning",
        "--model",
        "custom/bad-model",
        "--scope",
        "global",
        "--expect-hash",
        "cafebabe" * 8,
    )
    assert res_sp_mismatch.returncode != 0
    payload_sp_mismatch = json.loads(res_sp_mismatch.stdout)
    assert payload_sp_mismatch["ok"] is False
    assert global_cfg_path.read_bytes() == current_bytes  # file untouched!


def test_missing_file_diff_returns_hash_of_empty(tmp_path: pathlib.Path) -> None:
    missing_cfg = tmp_path / "nonexistent" / "orchestration.toml"
    assert not missing_cfg.exists()
    empty_hash = hashlib.sha256(b"").hexdigest()

    # --diff on missing file returns hash of empty bytes and writes nothing
    res_diff = run_cli(
        "--global-config",
        str(missing_cfg),
        "--json",
        "set-routing",
        "--orchestrator",
        "claude",
        "--scope",
        "global",
        "--diff",
    )
    assert res_diff.returncode == 0, res_diff.stdout + res_diff.stderr
    payload = json.loads(res_diff.stdout)
    assert payload["ok"] is True
    assert payload["hash"] == empty_hash
    assert payload["changed"] is True
    assert not missing_cfg.exists()

    # --expect-hash mismatch on missing file refuses and creates nothing
    res_refused = run_cli(
        "--global-config",
        str(missing_cfg),
        "--json",
        "set-routing",
        "--orchestrator",
        "claude",
        "--scope",
        "global",
        "--expect-hash",
        "0000" * 16,
    )
    assert res_refused.returncode != 0
    assert not missing_cfg.exists()

    # --expect-hash match with empty_hash succeeds and creates the file
    res_created = run_cli(
        "--global-config",
        str(missing_cfg),
        "--json",
        "set-routing",
        "--orchestrator",
        "claude",
        "--scope",
        "global",
        "--expect-hash",
        empty_hash,
    )
    assert res_created.returncode == 0, res_created.stdout + res_created.stderr
    assert missing_cfg.exists()
    assert 'default_orchestrator = "claude"' in missing_cfg.read_text(encoding="utf-8")


def test_effort_placeholder_accepted() -> None:
    assert "effort" in oc.ALLOWED_PLACEHOLDERS

    cfg = {
        "tools": {
            "claude": {
                "enabled": True,
                "profiles": {p: {"model": "m"} for p in oc.PROFILES},
                "headless": {
                    "argv": ["claude", "-m", "{model}", "--effort", "{effort}", "--dir", "{cwd}"],
                    "resume_argv": ["claude", "resume", "{session_id}", "--effort", "{effort}"],
                    "prompt_via": "stdin",
                },
            }
        }
    }
    errors, warnings = oc.validate_config(cfg)
    assert errors == [], f"Expected no errors for {{effort}} placeholder but got: {errors}"


def test_ai_orch_describe_catalog_entries() -> None:
    bin_ai_orch = REPO_ROOT / "bin" / "ai-orch"
    proc = subprocess.run([sys.executable, str(bin_ai_orch), "describe", "--json"], capture_output=True, text=True, check=True)
    catalog = json.loads(proc.stdout)
    config_subs = catalog["commands"]["config"]["subcommands"]

    assert "--diff" in config_subs["set-routing"]["usage"]
    assert "--expect-hash" in config_subs["set-routing"]["usage"]
    assert "--diff" in config_subs["set-profile"]["usage"]
    assert "--expect-hash" in config_subs["set-profile"]["usage"]
    assert "--diff" in config_subs["render-agents-md"]["usage"]
    assert "--expect-hash" in config_subs["render-agents-md"]["usage"]
    assert "--diff" in catalog["commands"]["render-agents-md"]["usage"]
    assert "--expect-hash" in catalog["commands"]["render-agents-md"]["usage"]


def test_render_agents_md_diff_scenarios(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    # 1. Missing AGENTS.md: returns hash of b"", changed=True, diff has additions, file untouched
    ws_missing = tmp_path / "ws_missing"
    ws_missing.mkdir()
    agents_missing = ws_missing / "AGENTS.md"
    assert not agents_missing.exists()

    empty_hash = hashlib.sha256(b"").hexdigest()
    res_missing = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_missing),
        "--diff",
    )
    assert res_missing.returncode == 0, res_missing.stdout + res_missing.stderr
    payload_missing = json.loads(res_missing.stdout)
    assert payload_missing["ok"] is True
    assert payload_missing["path"] == str(agents_missing)
    assert payload_missing["hash"] == empty_hash
    assert payload_missing["changed"] is True
    assert "+<!-- BEGIN ai-orchestration -->" in payload_missing["diff"]
    assert not agents_missing.exists()  # file was not created or modified

    # 2. AGENTS.md without the block: returns current file hash, changed=True, diff shows insertion, file bytes unchanged
    ws_noblock = tmp_path / "ws_noblock"
    ws_noblock.mkdir()
    agents_noblock = ws_noblock / "AGENTS.md"
    initial_noblock = "# My Project\n\nExisting notes without block.\n"
    agents_noblock.write_text(initial_noblock, encoding="utf-8")
    before_bytes_noblock = agents_noblock.read_bytes()
    before_hash_noblock = hashlib.sha256(before_bytes_noblock).hexdigest()

    res_noblock = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_noblock),
        "--diff",
    )
    assert res_noblock.returncode == 0, res_noblock.stdout + res_noblock.stderr
    payload_noblock = json.loads(res_noblock.stdout)
    assert payload_noblock["ok"] is True
    assert payload_noblock["path"] == str(agents_noblock)
    assert payload_noblock["hash"] == before_hash_noblock
    assert payload_noblock["changed"] is True
    assert "+<!-- BEGIN ai-orchestration -->" in payload_noblock["diff"]
    assert agents_noblock.read_bytes() == before_bytes_noblock  # file untouched!

    # 3. AGENTS.md with an outdated block: returns current file hash, changed=True, diff shows replacement, file bytes unchanged
    ws_outdated = tmp_path / "ws_outdated"
    ws_outdated.mkdir()
    agents_outdated = ws_outdated / "AGENTS.md"
    initial_outdated = (
        "# Header\n\nIntro notes.\n\n"
        "<!-- BEGIN ai-orchestration -->\n"
        "OLD STALE ORCHESTRATION CONTENT\n"
        "<!-- END ai-orchestration -->\n\n"
        "## Footer\nKeep this footer.\n"
    )
    agents_outdated.write_text(initial_outdated, encoding="utf-8")
    before_bytes_outdated = agents_outdated.read_bytes()
    before_hash_outdated = hashlib.sha256(before_bytes_outdated).hexdigest()

    res_outdated = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_outdated),
        "--diff",
    )
    assert res_outdated.returncode == 0, res_outdated.stdout + res_outdated.stderr
    payload_outdated = json.loads(res_outdated.stdout)
    assert payload_outdated["ok"] is True
    assert payload_outdated["path"] == str(agents_outdated)
    assert payload_outdated["hash"] == before_hash_outdated
    assert payload_outdated["changed"] is True
    assert "-OLD STALE ORCHESTRATION CONTENT" in payload_outdated["diff"]
    assert "+> **Managed by `ai-orchestration`" in payload_outdated["diff"]
    assert agents_outdated.read_bytes() == before_bytes_outdated  # file untouched!

    # 4. AGENTS.md already up to date: returns current file hash, changed=False, diff="", file bytes unchanged
    res_apply = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_outdated),
        "--apply",
        "--allow-global-routing",
    )
    assert res_apply.returncode == 0
    up_to_date_bytes = agents_outdated.read_bytes()
    up_to_date_hash = hashlib.sha256(up_to_date_bytes).hexdigest()

    res_uptodate = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_outdated),
        "--diff",
    )
    assert res_uptodate.returncode == 0, res_uptodate.stdout + res_uptodate.stderr
    payload_uptodate = json.loads(res_uptodate.stdout)
    assert payload_uptodate["ok"] is True
    assert payload_uptodate["path"] == str(agents_outdated)
    assert payload_uptodate["hash"] == up_to_date_hash
    assert payload_uptodate["changed"] is False
    assert payload_uptodate["diff"] == ""
    assert agents_outdated.read_bytes() == up_to_date_bytes  # file untouched!

    # Also test non-JSON text output
    res_text = run_cli(
        "--global-config",
        str(global_cfg_path),
        "render-agents-md",
        "--workspace",
        str(ws_outdated),
        "--diff",
    )
    assert res_text.returncode == 0
    assert f"[ok] no changes in {agents_outdated}" in res_text.stdout


def test_render_agents_md_expect_hash_match_and_mismatch(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    ws = tmp_path / "ws_expect_hash"
    ws.mkdir()
    agents_md = ws / "AGENTS.md"
    initial_content = (
        "# Header\n\n"
        "<!-- BEGIN ai-orchestration -->\n"
        "STALE BLOCK\n"
        "<!-- END ai-orchestration -->\n\n"
        "# Footer\n"
    )
    agents_md.write_text(initial_content, encoding="utf-8")
    initial_bytes = agents_md.read_bytes()
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()

    # 1. Mismatch on existing file -> refused (non-zero exit) and file untouched
    res_mismatch = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--apply",
        "--expect-hash",
        "badbeef0" * 8,
    )
    assert res_mismatch.returncode != 0
    payload_mismatch = json.loads(res_mismatch.stdout)
    assert payload_mismatch["ok"] is False
    assert "hash mismatch" in payload_mismatch["error"]
    assert payload_mismatch["actual_hash"] == initial_hash
    assert agents_md.read_bytes() == initial_bytes  # file untouched!

    # 2. Match on existing file -> written atomically
    res_match = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--apply",
        "--expect-hash",
        initial_hash,
        "--allow-global-routing",
    )
    assert res_match.returncode == 0, res_match.stdout + res_match.stderr
    payload_match = json.loads(res_match.stdout)
    assert payload_match["ok"] is True
    assert payload_match["applied"] is True
    assert agents_md.read_bytes() != initial_bytes
    assert "STALE BLOCK" not in agents_md.read_text(encoding="utf-8")

    # 3. Missing file mismatch -> refused and file not created
    ws_missing = tmp_path / "ws_missing_apply"
    ws_missing.mkdir()
    agents_missing = ws_missing / "AGENTS.md"
    assert not agents_missing.exists()

    res_missing_mismatch = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_missing),
        "--apply",
        "--expect-hash",
        "deadbeef" * 8,
        "--allow-global-routing",
    )
    assert res_missing_mismatch.returncode != 0
    payload_mm = json.loads(res_missing_mismatch.stdout)
    assert payload_mm["ok"] is False
    assert payload_mm["actual_hash"] == hashlib.sha256(b"").hexdigest()
    assert not agents_missing.exists()

    # 4. Missing file match with hash of empty bytes -> written
    empty_hash = hashlib.sha256(b"").hexdigest()
    res_missing_match = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_missing),
        "--apply",
        "--expect-hash",
        empty_hash,
        "--allow-global-routing",
    )
    assert res_missing_match.returncode == 0, res_missing_match.stdout + res_missing_match.stderr
    payload_m_match = json.loads(res_missing_match.stdout)
    assert payload_m_match["ok"] is True
    assert payload_m_match["applied"] is True
    assert agents_missing.exists()

    # 5. --apply without --expect-hash keeps working (CLI convenience)
    res_no_hash = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--apply",
        "--allow-global-routing",
    )
    assert res_no_hash.returncode == 0

    # 6. --expect-hash without --apply refuses
    res_no_apply = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--expect-hash",
        hashlib.sha256(agents_md.read_bytes()).hexdigest(),
    )
    assert res_no_apply.returncode != 0


def test_render_agents_md_handwritten_content_byte_identical_after_apply(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    header_text = (
        "# Custom Project Title\n\n"
        "Intro with special characters: 🌟, emojis 🤖, tabs \t, and unicode quotes '“”'.\n\n"
        "## Pre-existing Architecture\n\n"
        "Details about custom subsystems.\n\n"
    )
    footer_text = (
        "\n\n## Custom Footer Section\n\n"
        "Preserve every single byte here verbatim.\n"
        "Line 2 of footer.\n"
    )
    stale_block = (
        "<!-- BEGIN ai-orchestration -->\n"
        "OUTDATED MANAGED BLOCK THAT MUST BE REPLACED\n"
        "<!-- END ai-orchestration -->"
    )
    full_content = header_text + stale_block + footer_text

    ws = tmp_path / "ws_byte_identical"
    ws.mkdir()
    agents_md = ws / "AGENTS.md"
    agents_md.write_text(full_content, encoding="utf-8")

    before_bytes = agents_md.read_bytes()
    before_hash = hashlib.sha256(before_bytes).hexdigest()

    res = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--apply",
        "--expect-hash",
        before_hash,
        "--allow-global-routing",
    )
    assert res.returncode == 0, res.stdout + res.stderr

    after_text = agents_md.read_text(encoding="utf-8")
    assert oc.BEGIN_MARKER in after_text
    assert oc.END_MARKER in after_text

    # Verify text before BEGIN_MARKER is byte-identical
    begin_idx = after_text.index(oc.BEGIN_MARKER)
    assert after_text[:begin_idx] == header_text

    # Verify text after END_MARKER is byte-identical
    end_idx = after_text.index(oc.END_MARKER) + len(oc.END_MARKER)
    assert after_text[end_idx:] == footer_text


def test_render_agents_md_three_topology_pairs(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    # Pair 1: claude -> kilo (multi-framework MCP)
    ws_claude_kilo = tmp_path / "ws_claude_kilo"
    ws_claude_kilo.mkdir()
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws_claude_kilo),
        "--orchestrator",
        "claude",
        "--executor",
        "kilo",
    )
    res_ck = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_claude_kilo),
    )
    assert res_ck.returncode == 0
    block_ck = json.loads(res_ck.stdout)["rendered_block"]
    assert '`kilo_implement(isolation="worktree")`' in block_ck
    assert "agent_manager" not in block_ck
    assert '`primary_orchestrator = "claude"`' in block_ck
    assert '`default_executor = "kilo"`' in block_ck

    # Pair 2: kilo -> kilo (single-framework native)
    ws_kilo_kilo = tmp_path / "ws_kilo_kilo"
    ws_kilo_kilo.mkdir()
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws_kilo_kilo),
        "--orchestrator",
        "kilo",
        "--executor",
        "kilo",
        "--verification-mode",
        "independent-session",
    )
    res_kk = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_kilo_kilo),
    )
    assert res_kk.returncode == 0
    block_kk = json.loads(res_kk.stdout)["rendered_block"]
    assert '`agent_manager(mode="worktree")`' in block_kk
    assert "`task`" in block_kk
    assert "kilo_implement" not in block_kk
    assert '`primary_orchestrator = "kilo"`' in block_kk
    assert '`default_executor = "kilo"`' in block_kk

    # Pair 3: codex -> kilo (multi-framework MCP)
    ws_codex_kilo = tmp_path / "ws_codex_kilo"
    ws_codex_kilo.mkdir()
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws_codex_kilo),
        "--orchestrator",
        "codex",
        "--executor",
        "kilo",
    )
    res_co_k = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_codex_kilo),
    )
    assert res_co_k.returncode == 0
    block_co_k = json.loads(res_co_k.stdout)["rendered_block"]
    assert '`kilo_implement(isolation="worktree")`' in block_co_k
    assert "agent_manager" not in block_co_k
    assert '`primary_orchestrator = "codex"`' in block_co_k
    assert '`default_executor = "kilo"`' in block_co_k


def test_render_agents_md_no_silent_global_defaults(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    ws = tmp_path / "ws_unconfigured"
    ws.mkdir()
    agents_md = ws / "AGENTS.md"

    # 1. --apply without project config and without --allow-global-routing refuses
    res_refuse = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--apply",
    )
    assert res_refuse.returncode != 0
    payload_refuse = json.loads(res_refuse.stdout)
    assert payload_refuse["ok"] is False
    assert "workspace has no project config" in payload_refuse["error"]
    assert "orchestrator='kilo'" in payload_refuse["error"]
    assert not agents_md.exists()

    # 2. --apply with --allow-global-routing succeeds
    res_allow = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--apply",
        "--allow-global-routing",
    )
    assert res_allow.returncode == 0
    payload_allow = json.loads(res_allow.stdout)
    assert payload_allow["ok"] is True
    assert agents_md.exists()

    # 3. --diff on unconfigured workspace returns warnings containing routing notice
    res_diff = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--diff",
    )
    assert res_diff.returncode == 0
    payload_diff = json.loads(res_diff.stdout)
    assert payload_diff["ok"] is True
    assert any("Workspace has no project config; using global routing" in w for w in payload_diff["warnings"])

    # 4. Workspace WITH project config does NOT show routing warning
    ws_configured = tmp_path / "ws_configured"
    ws_configured.mkdir()
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws_configured),
        "--orchestrator",
        "claude",
        "--executor",
        "kilo",
    )
    res_diff_conf = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_configured),
        "--diff",
    )
    assert res_diff_conf.returncode == 0
    payload_diff_conf = json.loads(res_diff_conf.stdout)
    assert not any("Workspace has no project config" in w for w in payload_diff_conf["warnings"])


def test_render_agents_md_strict_main_session_rule(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    # 1. Default (strict_main_session = false) -> softer wording
    ws_soft = tmp_path / "ws_soft"
    ws_soft.mkdir()
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws_soft),
    )
    res_soft = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_soft),
    )
    assert res_soft.returncode == 0
    block_soft = json.loads(res_soft.stdout)["rendered_block"]
    assert "Rule 1: Focus the Main Session on Architecture & Orchestration" in block_soft
    assert "Prefer delegating multi-file implementations" in block_soft
    assert '("it\'s small, I\'ll just do it" is forbidden)' not in block_soft

    # 2. strict_main_session = true -> strict wording
    ws_strict = tmp_path / "ws_strict"
    ws_strict.mkdir()
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws_strict),
    )
    proj_cfg = oc.find_project_config_path(ws_strict, global_cfg_path)
    proj_cfg_text = proj_cfg.read_text(encoding="utf-8")
    proj_cfg_text += "\n[agents_md]\nstrict_main_session = true\n"
    proj_cfg.write_text(proj_cfg_text, encoding="utf-8")

    res_strict = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws_strict),
    )
    assert res_strict.returncode == 0
    block_strict = json.loads(res_strict.stdout)["rendered_block"]
    assert "Rule 1: Keep the Main Session Free (Orchestrate, Don't Implement)" in block_strict
    assert '("it\'s small, I\'ll just do it" is forbidden)' in block_strict


def test_render_agents_md_model_catalog_validation(tmp_path: pathlib.Path) -> None:
    global_cfg_path = tmp_path / "global" / "orchestration.toml"
    run_cli("--global-config", str(global_cfg_path), "init-global")

    ws = tmp_path / "ws_models"
    ws.mkdir()
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "init-project",
        "--workspace",
        str(ws),
        "--orchestrator",
        "claude",
        "--executor",
        "kilo",
    )

    # Unknown model for kilo
    run_cli(
        "--global-config",
        str(global_cfg_path),
        "set-profile",
        "kilo",
        "bulk-execution",
        "--model",
        "unknown-provider/fake-model-xyz",
        "--scope",
        "project",
        "--workspace",
        str(ws),
    )

    # 1. --diff lists the unknown model and skipped validation for claude
    res_diff = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--diff",
    )
    assert res_diff.returncode == 0
    payload_diff = json.loads(res_diff.stdout)
    assert any("unknown-provider/fake-model-xyz" in w for w in payload_diff["warnings"])
    assert any("Skipping model catalog validation for 'claude'" in w for w in payload_diff["warnings"])

    # 2. --apply refuses without --allow-unknown-models
    res_apply_refuse = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--apply",
    )
    assert res_apply_refuse.returncode != 0
    payload_refuse = json.loads(res_apply_refuse.stdout)
    assert payload_refuse["ok"] is False
    assert "unknown model id(s)" in payload_refuse["error"]

    # 3. --apply with --allow-unknown-models succeeds
    res_apply_allow = run_cli(
        "--global-config",
        str(global_cfg_path),
        "--json",
        "render-agents-md",
        "--workspace",
        str(ws),
        "--apply",
        "--allow-unknown-models",
    )
    assert res_apply_allow.returncode == 0
    payload_allow = json.loads(res_apply_allow.stdout)
    assert payload_allow["ok"] is True
    assert (ws / "AGENTS.md").exists()
