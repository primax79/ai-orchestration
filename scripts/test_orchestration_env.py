"""Unit tests for scripts/orchestration_env.py (skill installation, MCP registration, status & drift detection across kilo, claude, and codex)."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parent / "orchestration_env.py"


def run_env(args: list[str], home: pathlib.Path) -> dict:
    cmd = [sys.executable, str(SCRIPT), "--home", str(home), "--json", *args]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def test_install_skills_and_status_across_kilo_claude_codex(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_ws = tmp_path / "project"
    fake_home.mkdir()
    fake_ws.mkdir()

    # 1. Install skills globally across all 3 assistants (kilo, claude, codex)
    inst = run_env(["install-skills", "--assistants", "all", "--scope", "global"], fake_home)
    assert inst["ok"] is True
    assert inst["installed_count"] >= 24  # 8 skills * 3 assistants

    # 2. Verify status reports all 8 skills as up-to-date in kilo, claude, and codex
    st = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    for assistant in ("kilo", "claude", "codex"):
        g_env = st["environments"][assistant]["global"]
        assert g_env["installed_count"] == 8
        assert g_env["conflicts"] == []
        for sname, sdata in g_env["skills"].items():
            assert sdata["state"] == "up-to-date", f"{assistant}/{sname} not up-to-date"

    # 3. Modify one installed skill locally and verify drift detection
    modified_skill_md = fake_home / ".codex" / "skills" / "orchestration-workflow" / "SKILL.md"
    modified_skill_md.write_text(modified_skill_md.read_text() + "\n<!-- local edit -->\n")

    st2 = run_env(["status"], fake_home)
    assert (
        st2["environments"]["codex"]["global"]["skills"]["orchestration-workflow"]["state"]
        == "modified-or-outdated"
    )


def test_conflict_detection_when_generic_and_bound_both_installed(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    st = run_env(["status"], fake_home)
    conflicts = st["environments"]["claude"]["global"]["conflicts"]
    assert len(conflicts) == 1
    assert "orchestration-workflow" in conflicts[0]
    assert "kilo-mcp-orchestrator" in conflicts[0]

    # Test auto-resolve conflicts
    rc = run_env(["resolve-conflicts"], fake_home)
    assert rc["ok"] is True
    assert rc["resolved_count"] == 1
    assert rc["resolved"][0]["assistant"] == "claude"
    assert rc["resolved"][0]["removed"] == "orchestration-workflow"
    assert rc["resolved"][0]["kept"] == "kilo-mcp-orchestrator"

    # Verify conflict is now gone
    st_after = run_env(["status"], fake_home)
    assert st_after["environments"]["claude"]["global"]["conflicts"] == []

    # Test individual skill removal
    rm = run_env(["remove-skill", "kilo-mcp-orchestrator", "--assistant", "claude"], fake_home)
    assert rm["ok"] is True
    st_empty = run_env(["status"], fake_home)
    assert "kilo-mcp-orchestrator" not in st_empty["environments"]["claude"]["global"]["skills"]


def test_register_mcp_across_kilo_claude_codex(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    reg = run_env(["register-mcp", "kilo-mcp", "--assistants", "all", "--scope", "global"], fake_home)
    assert reg["ok"] is True
    assert len(reg["updated_configs"]) == 3

    reg_codex = run_env(["register-mcp", "codex-mcp", "--assistants", "claude", "kilo", "--scope", "global"], fake_home)
    assert reg_codex["ok"] is True

    st = run_env(["status"], fake_home)
    assert "kilo-mcp" in st["environments"]["claude"]["global"]["registered_mcps"]
    assert "codex-mcp" in st["environments"]["claude"]["global"]["registered_mcps"]
    assert "kilo-mcp" in st["environments"]["kilo"]["global"]["registered_mcps"]
    assert "kilo-mcp" in st["environments"]["codex"]["global"]["registered_mcps"]


def run_env_raw(args: list[str], home: pathlib.Path) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT), "--home", str(home), "--json", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_remove_skill_rejects_path_traversal(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    (fake_home / ".claude" / "skills" / "foo").mkdir(parents=True)
    (fake_home / ".claude" / "skills" / "foo" / "SKILL.md").write_text("x")
    (fake_home / ".claude" / "settings.json").write_text("keep")
    (fake_home / "precious.txt").write_text("keep")

    for bad in ("..", "../..", "foo/../..", ".", "", "/etc", "a/b"):
        res = run_env_raw(["remove-skill", bad, "--assistant", "claude", "--scope", "global"], fake_home)
        assert res.returncode != 0, bad
        assert json.loads(res.stdout)["ok"] is False, bad

    assert (fake_home / ".claude" / "settings.json").read_text() == "keep"
    assert (fake_home / "precious.txt").read_text() == "keep"
    assert (fake_home / ".claude" / "skills" / "foo" / "SKILL.md").is_file()

    ok = run_env(["remove-skill", "foo", "--assistant", "claude", "--scope", "global"], fake_home)
    assert ok["ok"] is True
    assert not (fake_home / ".claude" / "skills" / "foo").exists()


def test_register_mcp_refuses_to_overwrite_unparseable_config(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    claude_json = fake_home / ".claude.json"
    original = '{"projects": {"x": 1}, // not strict JSON\n "mcpServers": {}}'
    claude_json.write_text(original)

    res = run_env_raw(["register-mcp", "codex-mcp", "--assistants", "claude", "--scope", "global"], fake_home)
    assert res.returncode != 0
    assert json.loads(res.stdout)["ok"] is False
    assert claude_json.read_text() == original


def test_register_mcp_preserves_other_keys_and_keeps_backup(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    claude_json = fake_home / ".claude.json"
    claude_json.write_text(json.dumps({"projects": {"x": 1}, "mcpServers": {"other": {"command": "y"}}}))

    run_env(["register-mcp", "codex-mcp", "--assistants", "claude", "--scope", "global"], fake_home)
    data = json.loads(claude_json.read_text())
    assert data["projects"] == {"x": 1}
    assert set(data["mcpServers"]) == {"other", "codex-mcp"}
    assert (fake_home / ".claude.json.ai-orch.bak").is_file()
