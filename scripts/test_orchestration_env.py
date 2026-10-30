"""Unit tests for scripts/orchestration_env.py (skill installation, MCP registration, status & drift detection across kilo, claude, and codex)."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent / "orchestration_env.py"


@pytest.fixture(autouse=True)
def _stub_agent_clis(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub kilo/claude/codex CLIs so env tests never execute real agent binaries."""
    fake_bin = tmp_path_factory.mktemp("fake-env-clis")
    for name in ("kilo", "claude", "codex"):
        exe = fake_bin / name
        exe.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            f"name = {name!r}\n"
            "args = sys.argv[1:]\n"
            "if args and args[0] == '--version':\n"
            "    print(f'{name} 0.0.0-test-fake')\n"
            "    sys.exit(0)\n"
            "if name == 'claude' and args[:2] == ['mcp', 'add'] and '--' in args:\n"
            "    idx = args.index('--')\n"
            "    srv = args[idx - 1]\n"
            "    cmd_list = args[idx + 1:]\n"
            "    scope = args[args.index('--scope') + 1] if '--scope' in args else 'user'\n"
            "    cfg = (pathlib.Path(os.environ.get('HOME', '~')).expanduser() / '.claude.json') if scope == 'user' else (pathlib.Path.cwd() / '.mcp.json')\n"
            "    data = json.loads(cfg.read_text()) if cfg.exists() else {}\n"
            "    data.setdefault('mcpServers', {})[srv] = {'type': 'stdio', 'command': cmd_list[0], 'args': cmd_list[1:]}\n"
            "    cfg.parent.mkdir(parents=True, exist_ok=True)\n"
            "    cfg.write_text(json.dumps(data, indent=2) + '\\n')\n"
            "    sys.exit(0)\n"
            "if name == 'codex' and args[:2] == ['mcp', 'add'] and '--' in args:\n"
            "    idx = args.index('--')\n"
            "    srv = args[idx - 1]\n"
            "    cmd_list = args[idx + 1:]\n"
            "    cfg = pathlib.Path(os.environ.get('HOME', '~')).expanduser() / '.codex' / 'config.toml'\n"
            "    cfg.parent.mkdir(parents=True, exist_ok=True)\n"
            "    existing = cfg.read_text() if cfg.exists() else ''\n"
            "    block = f'\\n[mcp_servers.{srv}]\\ncommand = {json.dumps(cmd_list[0])}\\nargs = {json.dumps(cmd_list[1:])}\\n'\n"
            "    cfg.write_text(existing + block)\n"
            "    sys.exit(0)\n"
            "sys.stderr.write(f'REAL {name} CLI CALLED FROM A TEST: {args}\\n')\n"
            "sys.exit(97)\n",
            encoding="utf-8",
        )
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")



def run_env(args: list[str], home: pathlib.Path, env: dict | None = None) -> dict:
    cmd = [sys.executable, str(SCRIPT), "--home", str(home), "--json", *args]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
    return json.loads(res.stdout)


def test_install_skills_and_status_across_kilo_claude_codex(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_ws = tmp_path / "project"
    fake_home.mkdir()
    fake_ws.mkdir()

    # 1. Install skills globally across all 3 assistants (kilo, claude, codex)
    inst = run_env(["install-skills", "--assistants", "all", "--scope", "global", "--force"], fake_home)
    assert inst["ok"] is True
    assert inst["installed_count"] >= 24  # 8 skills * 3 assistants

    # 2. Verify status reports all 8 skills as up-to-date in kilo, claude, and codex
    st = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    assert "kilo_effective" in st
    assert len(st["kilo_effective"]) == 8
    for assistant in ("kilo", "claude", "codex"):
        g_env = st["environments"][assistant]["global"]
        assert g_env["installed_count"] == 8
        # T064: one identical copy per assistant root (kilo also reads ~/.claude/skills) is not a duplicate.
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

    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration", "--force"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    st = run_env(["status"], fake_home)
    conflicts = st["environments"]["claude"]["global"]["conflicts"]
    assert len(conflicts) == 4
    assert any("orchestration-workflow" in c and "kilo-mcp-orchestrator" in c for c in conflicts)

    # Test auto-resolve conflicts
    rc = run_env(["resolve-conflicts"], fake_home)
    assert rc["ok"] is True
    assert rc["resolved_count"] == 4
    resolved_map = {r["removed"]: r["kept"] for r in rc["resolved"] if r["assistant"] == "claude"}
    assert resolved_map["orchestration-workflow"] == "kilo-mcp-orchestrator"
    assert resolved_map["executor-contract"] == "kilo-mcp-executor-contract"
    assert resolved_map["conflict-resolver"] == "kilo-mcp-conflict-resolver"
    assert resolved_map["orchestration-metrics"] == "kilo-mcp-metrics-analyst"

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

    reg = run_env(["register-mcp", "kilo-mcp", "--assistants", "claude", "codex", "kilo", "--scope", "global"], fake_home)
    assert reg["ok"] is True
    assert len(reg["updated_configs"]) == 3

    reg_codex = run_env(["register-mcp", "codex-mcp", "--assistants", "claude", "kilo", "--scope", "global"], fake_home)
    assert reg_codex["ok"] is True

    st = run_env(["status"], fake_home)
    assert "kilo-mcp" in st["environments"]["claude"]["global"]["registered_mcps"]
    assert "codex-mcp" in st["environments"]["claude"]["global"]["registered_mcps"]
    assert "kilo-mcp" in st["environments"]["kilo"]["global"]["registered_mcps"]
    assert "kilo-mcp" in st["environments"]["codex"]["global"]["registered_mcps"]


def run_env_raw(args: list[str], home: pathlib.Path, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT), "--home", str(home), "--json", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)


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


def hash_tree(path: pathlib.Path) -> str:
    """Deterministic hash of an entire directory tree (names, contents, symlinks)."""
    import hashlib
    import os
    h = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for d in dirs:
            dp = pathlib.Path(root) / d
            if dp.is_symlink():
                h.update(f"L:{dp.relative_to(path)}->{dp.readlink()}\n".encode("utf-8"))
            else:
                h.update(f"D:{dp.relative_to(path)}\n".encode("utf-8"))
        for f in sorted(files):
            fp = pathlib.Path(root) / f
            if fp.is_symlink():
                h.update(f"L:{fp.relative_to(path)}->{fp.readlink()}\n".encode("utf-8"))
            else:
                h.update(f"F:{fp.relative_to(path)}\n".encode("utf-8"))
                h.update(fp.read_bytes())
    return h.hexdigest()


def test_no_clobber_install_and_overwrite_and_trash(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    claude_skills = fake_home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)

    # 1. Unmanaged skill
    unmanaged_dir = claude_skills / "my-unmanaged-skill"
    unmanaged_dir.mkdir()
    (unmanaged_dir / "SKILL.md").write_text("# Unmanaged\n")

    # 2. Foreign skill: matches catalog name 'orchestration-workflow' but has no marker and different content
    foreign_dir = claude_skills / "orchestration-workflow"
    foreign_dir.mkdir()
    (foreign_dir / "SKILL.md").write_text("# Foreign Orchestration\n")

    # 3. Locally modified skill: matches catalog 'executor-contract', has .ai-orch-source.json marker
    modified_dir = claude_skills / "executor-contract"
    modified_dir.mkdir()
    (modified_dir / "SKILL.md").write_text("# Local Edit of Executor\n")
    (modified_dir / ".ai-orch-source.json").write_text(
        json.dumps({
            "repo": "ai-orchestration",
            "plugin": "executor-side",
            "name": "executor-contract",
            "hash": "0000000000000000",
        })
    )

    # Verify status detects foreign, modified-or-outdated, and unmanaged correctly
    st = run_env(["status"], fake_home)
    c_skills = st["environments"]["claude"]["global"]["skills"]
    assert c_skills["my-unmanaged-skill"]["state"] == "unmanaged"
    assert c_skills["orchestration-workflow"]["state"] == "foreign"
    assert c_skills["executor-contract"]["state"] == "modified-or-outdated"

    # Install without --overwrite: should skip foreign and modified-or-outdated skills
    inst1 = run_env(["install-skills", "--assistants", "claude", "--scope", "global"], fake_home)
    assert inst1["ok"] is True
    plan = inst1["plan"]
    plan_by_path = {item["path"]: item for item in plan}

    assert plan_by_path[str(foreign_dir)]["action"] == "skip"
    assert plan_by_path[str(foreign_dir)]["current_state"] == "foreign"
    assert plan_by_path[str(modified_dir)]["action"] == "skip"
    assert plan_by_path[str(modified_dir)]["current_state"] == "modified-or-outdated"

    # Disk was NOT clobbered
    assert (foreign_dir / "SKILL.md").read_text() == "# Foreign Orchestration\n"
    assert (modified_dir / "SKILL.md").read_text() == "# Local Edit of Executor\n"
    assert (unmanaged_dir / "SKILL.md").read_text() == "# Unmanaged\n"

    # Overwrite only orchestration-workflow
    inst2 = run_env(
        ["install-skills", "--assistants", "claude", "--scope", "global", "--overwrite", "orchestration-workflow"],
        fake_home,
    )
    assert inst2["ok"] is True
    plan2_by_path = {item["path"]: item for item in inst2["plan"]}
    assert plan2_by_path[str(foreign_dir)]["action"] == "replace"
    assert plan2_by_path[str(modified_dir)]["action"] == "skip"

    # Verify old copy was moved to centralized trash outside assistant directory
    assert not (claude_skills / ".ai-orch-trash").exists()
    trash_base = fake_home / ".config" / "ai-orchestration" / "trash" / "claude" / "global"
    trashed_foreign = list(trash_base.glob("*/skills/orchestration-workflow/SKILL.md"))
    assert len(trashed_foreign) == 1
    assert trashed_foreign[0].read_text() == "# Foreign Orchestration\n"

    # Verify manifest exists and records the trashed item
    manifests = list(trash_base.glob("*/manifest.json"))
    assert len(manifests) >= 1
    m_entries = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert any(m["original_path"] == str(foreign_dir) for m in m_entries)

    # Verify new copy was installed with .ai-orch-source.json
    assert (foreign_dir / "SKILL.md").read_text() != "# Foreign Orchestration\n"
    assert (foreign_dir / ".ai-orch-source.json").is_file()

    # Now overwrite executor-contract as well
    inst3 = run_env(
        ["install-skills", "--assistants", "claude", "--scope", "global", "--overwrite", "executor-contract"],
        fake_home,
    )
    assert inst3["ok"] is True
    trashed_modified = list(trash_base.glob("*/skills/executor-contract/SKILL.md"))
    assert len(trashed_modified) == 1
    assert trashed_modified[0].read_text() == "# Local Edit of Executor\n"

    # Verify nothing under skills_dir except installed skills (no trash dir)
    for child in claude_skills.iterdir():
        assert child.is_dir()
        assert not child.name.startswith(".")
        assert (child / "SKILL.md").is_file()


def test_dry_run_leaves_disk_completely_unchanged(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / "some-file.txt").write_text("hello")

    tree_before = hash_tree(fake_home)

    # 1. install-skills --dry-run
    res_inst = run_env(["install-skills", "--assistants", "all", "--scope", "global", "--dry-run"], fake_home)
    assert res_inst["ok"] is True
    assert res_inst["dry_run"] is True
    assert len(res_inst["plan"]) > 0
    assert len(res_inst["plan_hash"]) == 64
    assert hash_tree(fake_home) == tree_before

    # 2. register-mcp --dry-run
    res_mcp = run_env(["register-mcp", "codex-mcp", "--assistants", "claude", "--scope", "global", "--dry-run"], fake_home)
    assert res_mcp["ok"] is True
    assert res_mcp["dry_run"] is True
    assert len(res_mcp["plan"]) > 0
    assert len(res_mcp["plan_hash"]) == 64
    assert hash_tree(fake_home) == tree_before

    # 3. resolve-conflicts --dry-run
    res_conf = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert res_conf["ok"] is True
    assert res_conf["dry_run"] is True
    assert len(res_conf["plan_hash"]) == 64
    assert hash_tree(fake_home) == tree_before

    # 4. remove-skill --dry-run on existing skill
    (fake_home / ".claude" / "skills" / "foo").mkdir(parents=True)
    (fake_home / ".claude" / "skills" / "foo" / "SKILL.md").write_text("dummy")
    tree_with_foo = hash_tree(fake_home)

    res_rm = run_env(["remove-skill", "foo", "--assistant", "claude", "--scope", "global", "--dry-run"], fake_home)
    assert res_rm["ok"] is True
    assert res_rm["dry_run"] is True
    assert res_rm["plan"][0]["action"] == "trash"
    assert len(res_rm["plan_hash"]) == 64
    assert hash_tree(fake_home) == tree_with_foo


def test_expect_plan_hash_validation(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    tree_before = hash_tree(fake_home)

    # Mismatched hash -> refused, non-zero returncode, disk unchanged
    bad_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    res_bad = run_env_raw(
        ["install-skills", "--assistants", "claude", "--scope", "global", "--expect-plan-hash", bad_hash],
        fake_home,
    )
    assert res_bad.returncode != 0
    bad_json = json.loads(res_bad.stdout)
    assert bad_json["ok"] is False
    assert "Plan hash mismatch" in bad_json["error"]
    assert hash_tree(fake_home) == tree_before

    # Get exact plan_hash via dry-run
    dry = run_env(["install-skills", "--assistants", "claude", "--scope", "global", "--dry-run"], fake_home)
    expected_hash = dry["plan_hash"]

    # Run with matching expect-plan-hash -> succeeds!
    res_good = run_env(
        ["install-skills", "--assistants", "claude", "--scope", "global", "--expect-plan-hash", expected_hash],
        fake_home,
    )
    assert res_good["ok"] is True
    assert res_good["plan_hash"] == expected_hash
    assert res_good["installed_count"] >= 7

    # Stale expect-plan-hash on second run -> recomputed plan now has 'replace' instead of 'create', so mismatch
    res_stale = run_env_raw(
        ["install-skills", "--assistants", "claude", "--scope", "global", "--expect-plan-hash", expected_hash],
        fake_home,
    )
    assert res_stale.returncode != 0
    assert json.loads(res_stale.stdout)["ok"] is False


def test_obsolete_renames_in_plan_and_trashed_only_on_apply(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Pre-create obsolete skill directory and obsolete agent file
    obs_skill = fake_home / ".claude" / "skills" / "interactive-role-setup"
    obs_skill.mkdir(parents=True)
    (obs_skill / "SKILL.md").write_text("# Obsolete Skill\n")

    kilo_agents = fake_home / ".config" / "kilo" / "agents"
    kilo_agents.mkdir(parents=True)
    obs_agent = kilo_agents / "mcp-orchestrator-agent.md"
    obs_agent.write_text("# Obsolete Agent\n")

    # Dry-run: obsolete items appear in plan as action: "trash"
    dry = run_env(["install-skills", "--assistants", "all", "--scope", "global", "--dry-run"], fake_home)
    assert dry["ok"] is True
    plan = dry["plan"]

    obs_skill_item = next(p for p in plan if p["path"] == str(obs_skill))
    assert obs_skill_item["action"] == "trash"
    assert "obsolete pre-rename name of orchestration-setup" in obs_skill_item["reason"]

    obs_agent_item = next(p for p in plan if p["path"] == str(obs_agent))
    assert obs_agent_item["action"] == "trash"
    assert "obsolete pre-rename name of kilo-mcp-orchestrator-agent.md" in obs_agent_item["reason"]

    # Obsolete files are STILL on disk during dry-run!
    assert obs_skill.is_dir()
    assert obs_agent.is_file()

    # Apply install
    apply_res = run_env(["install-skills", "--assistants", "all", "--scope", "global"], fake_home)
    assert apply_res["ok"] is True
    assert str(obs_skill) in apply_res["removed_obsolete"]
    assert str(obs_agent) in apply_res["removed_obsolete"]

    # Original paths are gone
    assert not obs_skill.exists()
    assert not obs_agent.exists()

    # Preserved in centralized trash outside assistant dirs
    assert not (fake_home / ".claude" / "skills" / ".ai-orch-trash").exists()
    assert not (kilo_agents / ".ai-orch-trash").exists()

    claude_trash = fake_home / ".config" / "ai-orchestration" / "trash" / "claude" / "global"
    trashed_skill = list(claude_trash.glob("*/skills/interactive-role-setup/SKILL.md"))
    assert len(trashed_skill) == 1
    assert trashed_skill[0].read_text() == "# Obsolete Skill\n"

    kilo_trash = fake_home / ".config" / "ai-orchestration" / "trash" / "kilo" / "global"
    trashed_agent = list(kilo_trash.glob("*/agents/mcp-orchestrator-agent.md"))
    assert len(trashed_agent) == 1
    assert trashed_agent[0].read_text() == "# Obsolete Agent\n"

    # Manifest exists and records the trashed items
    skill_manifest = json.loads(list(claude_trash.glob("*/manifest.json"))[0].read_text(encoding="utf-8"))
    assert any(m["original_path"] == str(obs_skill) for m in skill_manifest)


def test_remove_skill_and_resolve_conflicts_trash_instead_of_delete(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Install generic and bound skills to induce conflict in claude
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration", "--force"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    claude_skills = fake_home / ".claude" / "skills"
    assert (claude_skills / "orchestration-workflow").is_dir()
    assert (claude_skills / "kilo-mcp-orchestrator").is_dir()

    # Resolve conflicts -> moves generic 'orchestration-workflow' to centralized trash
    rc = run_env(["resolve-conflicts"], fake_home)
    assert rc["ok"] is True
    assert not (claude_skills / "orchestration-workflow").exists()
    assert (claude_skills / "kilo-mcp-orchestrator").is_dir()
    assert not (claude_skills / ".ai-orch-trash").exists()

    claude_trash = fake_home / ".config" / "ai-orchestration" / "trash" / "claude" / "global"
    trashed_conflict = list(claude_trash.glob("*/skills/orchestration-workflow/SKILL.md"))
    assert len(trashed_conflict) == 1

    # Remove skill -> moves 'kilo-mcp-orchestrator' to centralized trash
    rm = run_env(["remove-skill", "kilo-mcp-orchestrator", "--assistant", "claude"], fake_home)
    assert rm["ok"] is True
    assert not (claude_skills / "kilo-mcp-orchestrator").exists()

    trashed_rm = list(claude_trash.glob("*/skills/kilo-mcp-orchestrator/SKILL.md"))
    assert len(trashed_rm) == 1


def test_resolve_conflicts_policy_from_config(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Write custom policy in orchestration.toml:
    # kilo keeps bound, claude keeps generic (opposite of default!)
    cfg_dir = fake_home / ".config" / "ai-orchestration"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "orchestration.toml").write_text(
        """
[env.conflicts.keep]
kilo = "bound"
claude = "generic"
"""
    )

    # Install both generic and bound for kilo and claude
    run_env(["install-skills", "--assistants", "kilo", "claude", "--repo", "ai-orchestration", "--force"], fake_home)
    run_env(["install-skills", "--assistants", "kilo", "claude", "--repo", "kilo-mcp", "--force"], fake_home)

    rc = run_env(["resolve-conflicts"], fake_home)
    assert rc["ok"] is True
    assert rc["resolved_count"] == 8

    kilo_res = next(r for r in rc["resolved"] if r["assistant"] == "kilo" and r["removed"] == "orchestration-workflow")
    assert kilo_res["kept"] == "kilo-mcp-orchestrator"
    assert kilo_res["removed"] == "orchestration-workflow"

    claude_res = next(r for r in rc["resolved"] if r["assistant"] == "claude" and r["kept"] == "orchestration-workflow")
    assert claude_res["kept"] == "orchestration-workflow"
    assert claude_res["removed"] == "kilo-mcp-orchestrator"


def test_modify_source_skill_refuses_stale_plan_hash(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Create mock repo in cache dir
    mock_repo = fake_home / ".ai-orchestration" / "repos" / "claude-mcp"
    skill_dir = mock_repo / "plugins" / "architect-side" / "skills" / "my-mock-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Initial Version\n")

    # Dry-run computes plan hash
    dry = run_env(["install-skills", "--repo", "claude-mcp", "--assistants", "claude", "--dry-run"], fake_home)
    assert dry["ok"] is True
    plan_hash = dry["plan_hash"]

    # Modify the source skill file
    skill_file.write_text("# Mutated Version After Dry Run\n")

    # Apply with stale expect-plan-hash -> refused!
    res = run_env_raw(
        ["install-skills", "--repo", "claude-mcp", "--assistants", "claude", "--expect-plan-hash", plan_hash],
        fake_home,
    )
    assert res.returncode != 0
    data = json.loads(res.stdout)
    assert data["ok"] is False
    assert "Plan hash mismatch" in data["error"]
    assert not (fake_home / ".claude" / "skills" / "my-mock-skill").exists()


def test_project_scope_trash_location_and_manifest(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    ws = tmp_path / "my-project"
    ws.mkdir()

    # Install skills into project scope for kilo
    run_env(["install-skills", "--assistants", "kilo", "--scope", "project", "--workspace", str(ws)], fake_home)

    target_skill = ws / ".kilo" / "skills" / "orchestration-workflow"
    assert (target_skill / "SKILL.md").is_file()

    # Modify the installed skill to make it modified-or-outdated
    (target_skill / "SKILL.md").write_text("# Project modified content\n")

    # Overwrite it so it gets trashed
    run_env(
        ["install-skills", "--assistants", "kilo", "--scope", "project", "--workspace", str(ws), "--overwrite", "orchestration-workflow"],
        fake_home,
    )

    ws_abs = str(ws.resolve())
    ws_hash = hashlib.sha256(ws_abs.encode("utf-8")).hexdigest()[:8]
    scope_segment = f"project-{ws.name}-{ws_hash}"

    trash_base = fake_home / ".config" / "ai-orchestration" / "trash" / "kilo" / scope_segment
    assert trash_base.is_dir()

    trashed_files = list(trash_base.glob("*/skills/orchestration-workflow/SKILL.md"))
    assert len(trashed_files) == 1
    assert trashed_files[0].read_text() == "# Project modified content\n"

    manifest_files = list(trash_base.glob("*/manifest.json"))
    assert len(manifest_files) >= 1
    manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    assert any(m["original_path"] == str(target_skill) for m in manifest)

    # Nothing in project skills except valid skills
    for child in (ws / ".kilo" / "skills").iterdir():
        assert child.is_dir()
        assert not child.name.startswith(".")
        assert (child / "SKILL.md").is_file()


def test_agent_receipts_no_clobber_and_trash(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    kilo_agents = fake_home / ".config" / "kilo" / "agents"

    # Install skills & agents from kilo-mcp (which contains kilo-mcp-orchestrator-agent.md)
    run_env(["install-skills", "--assistants", "kilo", "--scope", "global", "--repo", "kilo-mcp"], fake_home)

    # Verify receipts file exists and is not a .md file
    receipts_file = kilo_agents / ".ai-orch-receipts.json"
    assert receipts_file.is_file()
    receipts = json.loads(receipts_file.read_text(encoding="utf-8"))

    agent_name = "kilo-mcp-orchestrator-agent.md"
    assert agent_name in receipts
    r = receipts[agent_name]
    assert set(r.keys()) == {"repo", "plugin", "name", "source_hash", "installed_at", "mode"}
    assert r["repo"] == "kilo-mcp"
    assert r["name"] == agent_name
    assert r["mode"] == "copy"

    # Locally modify the agent
    agent_path = kilo_agents / agent_name
    agent_path.write_text("# Local modified agent content\n")

    # Status identifies it as modified-or-outdated
    st = run_env(["status"], fake_home)
    assert st["environments"]["kilo"]["global"]["agents"][agent_name]["state"] == "modified-or-outdated"

    # Install without --overwrite: skips it, leaves modified content intact
    inst_skip = run_env(["install-skills", "--assistants", "kilo", "--scope", "global", "--repo", "kilo-mcp"], fake_home)
    plan_by_path = {p["path"]: p for p in inst_skip["plan"]}
    assert plan_by_path[str(agent_path)]["action"] == "skip"
    assert agent_path.read_text() == "# Local modified agent content\n"

    # Install with --overwrite: replaces and trashes
    inst_ovw = run_env(["install-skills", "--assistants", "kilo", "--scope", "global", "--repo", "kilo-mcp", "--overwrite", agent_name], fake_home)
    assert inst_ovw["ok"] is True
    assert agent_path.read_text() != "# Local modified agent content\n"

    trash_base = fake_home / ".config" / "ai-orchestration" / "trash" / "kilo" / "global"
    trashed_agents = list(trash_base.glob(f"*/agents/{agent_name}"))
    assert len(trashed_agents) == 1
    assert trashed_agents[0].read_text() == "# Local modified agent content\n"

    manifest_files = list(trash_base.glob("*/manifest.json"))
    assert len(manifest_files) >= 1
    manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    assert any(m["original_path"] == str(agent_path) for m in manifest)

    # Ensure no trash dir under agents
    assert not (kilo_agents / ".ai-orch-trash").exists()


def test_fetch_repos_dry_run_and_plan_hashes(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    res = run_env(["fetch-repos", "--dry-run"], fake_home)
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert len(res["plan"]) > 0
    assert len(res["plan_hash"]) == 64

    for item in res["plan"]:
        assert item["action"] in ("git-clone", "git-pull", "skip")
        assert "before_sha256" in item
        assert "after_sha256" in item


def test_register_mcp_provision_venv_dry_run_and_plan_hashes(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    res = run_env(["register-mcp", "kilo-mcp", "--provision-venv", "--dry-run", "--assistants", "claude"], fake_home)
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert len(res["plan"]) > 0
    assert len(res["plan_hash"]) == 64

    actions = [item["action"] for item in res["plan"]]
    assert any(a in actions for a in ("edit", "cli"))

    for item in res["plan"]:
        assert "before_sha256" in item
        assert "after_sha256" in item


def test_receipt_file_excluded_from_hash_directory(tmp_path: pathlib.Path) -> None:
    from orchestration_env import hash_directory

    test_dir = tmp_path / "my-skill"
    test_dir.mkdir()
    (test_dir / "SKILL.md").write_text("# My Skill\n")

    h_before = hash_directory(test_dir)

    # Write .ai-orch-source.json inside skill directory
    (test_dir / ".ai-orch-source.json").write_text(json.dumps({"dummy": "receipt"}))

    h_after = hash_directory(test_dir)
    assert h_before == h_after


def test_env_lock_held_during_execution(tmp_path: pathlib.Path) -> None:
    import fcntl
    import pytest
    from orchestration_env import env_lock, get_env_lock_path

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # When lock is held, attempting non-blocking lock fails with BlockingIOError / OSError
    with env_lock(fake_home):
        lock_path = get_env_lock_path(fake_home)
        assert lock_path.is_file()
        with open(lock_path, "a") as f2:
            with pytest.raises((BlockingIOError, OSError)):
                fcntl.flock(f2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    # Once released, lock can be acquired again non-blocking
    with open(lock_path, "a") as f3:
        fcntl.flock(f3.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f3.fileno(), fcntl.LOCK_UN)


def test_reinstall_of_identical_skills_is_a_noop(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    run_env(["install-skills", "--assistants", "claude", "--scope", "global", "--force"], fake_home)
    trash_root = fake_home / ".config" / "ai-orchestration" / "trash"
    before = sorted(p for p in trash_root.rglob("*")) if trash_root.exists() else []

    plan = run_env(["install-skills", "--dry-run", "--assistants", "claude", "--scope", "global", "--force"], fake_home)
    skill_actions = {e["action"] for e in plan["plan"] if "/skills/" in e["path"]}
    assert skill_actions == {"noop"}, skill_actions

    run_env(["install-skills", "--assistants", "claude", "--scope", "global", "--force"], fake_home)
    after = sorted(p for p in trash_root.rglob("*")) if trash_root.exists() else []
    assert after == before


def test_claude_plugin_skills_inventory_and_settings_enablement(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_ws = tmp_path / "project"
    other_ws = tmp_path / "other_project"
    fake_home.mkdir()
    fake_ws.mkdir()
    other_ws.mkdir()

    # Create plugin cache directories with skills
    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_generic_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    p_bound_skills = plugins_cache / "kilo-mcp" / "architect-side" / "0.2.2" / "skills"
    p_other_skills = plugins_cache / "other" / "project-plugin" / "0.1.0" / "skills"

    (p_generic_skills / "orchestration-workflow").mkdir(parents=True)
    (p_generic_skills / "orchestration-workflow" / "SKILL.md").write_text("---\nname: orchestration-workflow\n---\n# Generic Workflow\n")

    (p_bound_skills / "kilo-mcp-orchestrator").mkdir(parents=True)
    (p_bound_skills / "kilo-mcp-orchestrator" / "SKILL.md").write_text("---\nname: kilo-mcp-orchestrator\n---\n# Bound Orchestrator\n")

    (p_other_skills / "other-tool").mkdir(parents=True)
    (p_other_skills / "other-tool" / "SKILL.md").write_text("---\nname: other-tool\n---\n# Other Tool\n")

    # Write installed_plugins.json
    installed_plugins_data = {
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_generic_skills.parent),
                    "version": "0.3.0",
                }
            ],
            "architect-side@kilo-mcp": [
                {
                    "scope": "user",
                    "installPath": str(p_bound_skills.parent),
                    "version": "0.2.2",
                }
            ],
            "project-plugin@other": [
                {
                    "scope": "project",
                    "projectPath": str(other_ws),
                    "installPath": str(p_other_skills.parent),
                    "version": "0.1.0",
                }
            ],
        },
    }
    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps(installed_plugins_data, indent=2))

    # User settings: architect-side@ai-orchestration enabled, architect-side@kilo-mcp disabled
    user_settings = {
        "enabledPlugins": {
            "architect-side@ai-orchestration": True,
            "architect-side@kilo-mcp": False,
        }
    }
    settings_file = fake_home / ".claude" / "settings.json"
    settings_file.write_text(json.dumps(user_settings, indent=2))

    # Status check with workspace = fake_ws
    st = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    claude_global = st["environments"]["claude"]["global"]
    entries = claude_global["skill_entries"]

    # Verify skill_entries list structure
    generic_entry = next((e for e in entries if e["name"] == "orchestration-workflow"), None)
    assert generic_entry is not None
    assert generic_entry["origin"] == "plugin:architect-side@ai-orchestration"
    assert generic_entry["scope"] == "user"
    assert generic_entry["enabled"] is True
    assert generic_entry["state"] == "plugin"

    bound_entry = next((e for e in entries if e["name"] == "kilo-mcp-orchestrator"), None)
    assert bound_entry is not None
    assert bound_entry["origin"] == "plugin:architect-side@kilo-mcp"
    assert bound_entry["scope"] == "user"
    assert bound_entry["enabled"] is False
    assert bound_entry["state"] == "plugin"

    # other-tool is for other_ws, so must NOT appear in global or fake_ws project entries
    assert not any(e["name"] == "other-tool" for e in entries)
    claude_project = st["environments"]["claude"]["project"]
    assert not any(e["name"] == "other-tool" for e in claude_project["skill_entries"])

    # Because kilo-mcp-orchestrator is disabled in settings, no conflict is reported
    assert claude_global["conflicts"] == []
    assert claude_global["structured_conflicts"] == []

    # Project settings override: enable architect-side@kilo-mcp in fake_ws
    ws_claude = fake_ws / ".claude"
    ws_claude.mkdir(parents=True)
    (ws_claude / "settings.json").write_text(json.dumps({
        "enabledPlugins": {
            "architect-side@kilo-mcp": True,
        }
    }))

    st2 = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    # Global still sees disabled kilo-mcp-orchestrator (user settings)
    assert st2["environments"]["claude"]["global"]["conflicts"] == []
    # Project view sees effective enabled kilo-mcp-orchestrator -> conflict reported!
    proj_conflicts = st2["environments"]["claude"]["project"]["structured_conflicts"]
    assert len(proj_conflicts) == 1
    assert proj_conflicts[0]["kind"] == "trigger-conflict"
    assert set(proj_conflicts[0]["names"]) == {"orchestration-workflow", "kilo-mcp-orchestrator"}


def test_duplicate_name_conflict_between_standalone_and_plugin(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Install standalone orchestration-workflow
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration", "--force"], fake_home)

    # Set up enabled plugin providing orchestration-workflow
    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_generic_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_generic_skills / "orchestration-workflow").mkdir(parents=True)
    (p_generic_skills / "orchestration-workflow" / "SKILL.md").write_text("# Plugin Generic Workflow\n")

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_generic_skills.parent),
                }
            ]
        }
    }))

    # Verify duplicate-name conflict is detected
    st = run_env(["status"], fake_home)
    s_conflicts = st["environments"]["claude"]["global"]["structured_conflicts"]
    dup_conflicts = [c for c in s_conflicts if c["kind"] == "duplicate-name" and c["names"] == ["orchestration-workflow"]]
    assert len(dup_conflicts) == 1
    dup_entry = dup_conflicts[0]
    assert len(dup_entry["entries"]) == 2
    origins = {e["origin"] for e in dup_entry["entries"]}
    assert origins == {"standalone", "plugin:architect-side@ai-orchestration"}
    assert any("Duplicate skill 'orchestration-workflow'" in c for c in st["environments"]["claude"]["global"]["conflicts"])


def test_resolve_conflicts_plan_never_contains_non_advise_action_on_plugin_path(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Install standalone orchestration-workflow
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration", "--force"], fake_home)

    # Set up plugin providing kilo-mcp-orchestrator AND plugin providing orchestration-workflow
    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_bound_skills = plugins_cache / "kilo-mcp" / "architect-side" / "0.2.2" / "skills"
    (p_bound_skills / "kilo-mcp-orchestrator").mkdir(parents=True)
    (p_bound_skills / "kilo-mcp-orchestrator" / "SKILL.md").write_text("# Bound Orchestrator\n")

    p_generic_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_generic_skills / "orchestration-workflow").mkdir(parents=True)
    (p_generic_skills / "orchestration-workflow" / "SKILL.md").write_text("# Plugin Generic Workflow\n")

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@kilo-mcp": [
                {
                    "scope": "user",
                    "installPath": str(p_bound_skills.parent),
                }
            ],
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_generic_skills.parent),
                }
            ],
        }
    }))

    # 1. Check resolve-conflicts dry-run plan
    rc = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc["ok"] is True
    plan = rc["plan"]
    assert len(plan) > 0

    # Rule: plan never contains a non-advise action on a plugin path
    plugin_cache_str = str(plugins_cache)
    for item in plan:
        path = item["path"]
        if plugin_cache_str in path:
            assert item["action"] == "advise", f"Expected 'advise' for plugin path, got {item['action']}: {item}"
            assert "disable plugin" in item["reason"]
            assert "(enabledPlugins) or uninstall it" in item["reason"]
        else:
            assert item["action"] == "trash"

    # 2. Check execute (non-dry-run)
    rc_exec = run_env(["resolve-conflicts"], fake_home)
    assert rc_exec["ok"] is True
    # Plugin directories are never removed or modified
    assert (p_bound_skills / "kilo-mcp-orchestrator" / "SKILL.md").is_file()
    assert (p_generic_skills / "orchestration-workflow" / "SKILL.md").is_file()
    # Standalone generic copy was trashed
    assert not (fake_home / ".claude" / "skills" / "orchestration-workflow").exists()


def test_duplicate_name_standalone_identical_to_plugin_trashes_standalone(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_skills / "task-pipeline").mkdir(parents=True)
    (p_skills / "task-pipeline" / "SKILL.md").write_text("# Task Pipeline Plugin\n")

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    standalone_dir = fake_home / ".claude" / "skills" / "task-pipeline"
    standalone_dir.mkdir(parents=True)
    (standalone_dir / "SKILL.md").write_text("# Task Pipeline Plugin\n")

    rc = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc["ok"] is True
    plan = rc["plan"]
    assert len(plan) == 1
    assert plan[0]["action"] == "trash"
    assert plan[0]["path"] == str(standalone_dir)
    assert plan[0]["reason"] == "duplicate of plugin architect-side@ai-orchestration; plugin copy kept"
    assert not any(item["action"] == "advise" for item in plan)

    rc_exec = run_env(["resolve-conflicts"], fake_home)
    assert rc_exec["ok"] is True
    assert rc_exec["resolved_count"] == 1
    assert not standalone_dir.exists()
    assert (p_skills / "task-pipeline" / "SKILL.md").is_file()


def test_duplicate_name_standalone_modified_vs_plugin_advises(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_skills / "task-pipeline").mkdir(parents=True)
    (p_skills / "task-pipeline" / "SKILL.md").write_text("# Task Pipeline Plugin\n")

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    standalone_dir = fake_home / ".claude" / "skills" / "task-pipeline"
    standalone_dir.mkdir(parents=True)
    (standalone_dir / "SKILL.md").write_text("# Locally Modified Task Pipeline\n")

    rc = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc["ok"] is True
    plan = rc["plan"]
    assert len(plan) == 1
    assert plan[0]["action"] == "advise"
    assert plan[0]["path"] == str(standalone_dir)
    assert plan[0]["reason"] == "standalone copy differs from plugin architect-side@ai-orchestration: review and remove one manually"
    assert not any(item["action"] == "trash" for item in plan)

    rc_exec = run_env(["resolve-conflicts"], fake_home)
    assert rc_exec["ok"] is True
    assert rc_exec["resolved_count"] == 0
    assert standalone_dir.exists()
    assert (p_skills / "task-pipeline" / "SKILL.md").is_file()


def test_duplicate_name_two_plugins_same_name_single_advise(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p1_skills = plugins_cache / "market-a" / "plugin-a" / "1.0.0" / "skills"
    (p1_skills / "shared-skill").mkdir(parents=True)
    (p1_skills / "shared-skill" / "SKILL.md").write_text("# Shared Skill in Plugin A\n")

    p2_skills = plugins_cache / "market-b" / "plugin-b" / "2.0.0" / "skills"
    (p2_skills / "shared-skill").mkdir(parents=True)
    (p2_skills / "shared-skill" / "SKILL.md").write_text("# Shared Skill in Plugin B\n")

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "plugin-a@market-a": [
                {
                    "scope": "user",
                    "installPath": str(p1_skills.parent),
                }
            ],
            "plugin-b@market-b": [
                {
                    "scope": "user",
                    "installPath": str(p2_skills.parent),
                }
            ],
        }
    }))

    rc = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc["ok"] is True
    plan = rc["plan"]
    assert len(plan) == 1
    assert plan[0]["action"] == "advise"
    assert plan[0]["reason"] == "same skill name provided by plugins plugin-a@market-a, plugin-b@market-b: disable one in enabledPlugins"
    assert not any(item["action"] == "trash" for item in plan)


def test_trigger_conflict_standalone_dropped_vs_plugin_only_dropped(tmp_path: pathlib.Path) -> None:
    # Part A: Dropped copy is standalone -> trash
    fake_home_a = tmp_path / "home_a"
    fake_home_a.mkdir()

    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration", "--force"], fake_home_a)

    plugins_cache_a = fake_home_a / ".claude" / "plugins" / "cache"
    p_bound_a = plugins_cache_a / "kilo-mcp" / "architect-side" / "0.2.2" / "skills"
    (p_bound_a / "kilo-mcp-orchestrator").mkdir(parents=True)
    (p_bound_a / "kilo-mcp-orchestrator" / "SKILL.md").write_text("# Bound Orchestrator\n")

    reg_a = fake_home_a / ".claude" / "plugins" / "installed_plugins.json"
    reg_a.parent.mkdir(parents=True, exist_ok=True)
    reg_a.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@kilo-mcp": [
                {
                    "scope": "user",
                    "installPath": str(p_bound_a.parent),
                }
            ]
        }
    }))

    rc_a = run_env(["resolve-conflicts", "--dry-run"], fake_home_a)
    assert rc_a["ok"] is True
    plan_a = rc_a["plan"]
    assert len(plan_a) == 1
    assert plan_a[0]["action"] == "trash"
    assert plan_a[0]["path"] == str(fake_home_a / ".claude" / "skills" / "orchestration-workflow")

    # Part B: Dropped copy is plugin-only (no standalone) -> advise
    fake_home_b = tmp_path / "home_b"
    fake_home_b.mkdir()

    plugins_cache_b = fake_home_b / ".claude" / "plugins" / "cache"
    p_generic_b = plugins_cache_b / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_generic_b / "orchestration-workflow").mkdir(parents=True)
    (p_generic_b / "orchestration-workflow" / "SKILL.md").write_text("# Plugin Generic\n")

    p_bound_b = plugins_cache_b / "kilo-mcp" / "architect-side" / "0.2.2" / "skills"
    (p_bound_b / "kilo-mcp-orchestrator").mkdir(parents=True)
    (p_bound_b / "kilo-mcp-orchestrator" / "SKILL.md").write_text("# Bound Orchestrator\n")

    reg_b = fake_home_b / ".claude" / "plugins" / "installed_plugins.json"
    reg_b.parent.mkdir(parents=True, exist_ok=True)
    reg_b.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_generic_b.parent),
                }
            ],
            "architect-side@kilo-mcp": [
                {
                    "scope": "user",
                    "installPath": str(p_bound_b.parent),
                }
            ]
        }
    }))

    rc_b = run_env(["resolve-conflicts", "--dry-run"], fake_home_b)
    assert rc_b["ok"] is True
    plan_b = rc_b["plan"]
    assert len(plan_b) == 1
    assert plan_b[0]["action"] == "advise"
    assert plan_b[0]["path"] == str(p_generic_b / "orchestration-workflow")
    assert "architect-side@ai-orchestration provides 5 essential orchestration skills" in plan_b[0]["reason"]
    assert "disable plugin" not in plan_b[0]["reason"]
    assert not any(item["action"] == "trash" for item in plan_b)


def test_no_duplicate_conflict_entries_and_plan_paths(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_ws = tmp_path / "workspace"
    fake_ws.mkdir()

    # Install standalone orchestration-workflow globally
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)

    # Install standalone kilo-mcp-orchestrator globally
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    # Also install plugins for both
    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_generic = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_generic / "orchestration-workflow").mkdir(parents=True)
    (p_generic / "orchestration-workflow" / "SKILL.md").write_text("# Plugin Generic\n")

    p_bound = plugins_cache / "kilo-mcp" / "architect-side" / "0.2.2" / "skills"
    (p_bound / "kilo-mcp-orchestrator").mkdir(parents=True)
    (p_bound / "kilo-mcp-orchestrator" / "SKILL.md").write_text("# Plugin Bound\n")

    reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_generic.parent),
                }
            ],
            "architect-side@kilo-mcp": [
                {
                    "scope": "user",
                    "installPath": str(p_bound.parent),
                }
            ]
        }
    }))

    # 1. Verify structured_conflicts deduplication in status
    st = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    for assistant in ["claude"]:
        for scope in ["global", "project"]:
            scs = st["environments"][assistant][scope]["structured_conflicts"]
            seen_keys = set()
            for sc in scs:
                key = (sc["kind"], tuple(sorted(sc["names"])))
                assert key not in seen_keys, f"Duplicate conflict key {key} in {assistant} {scope}"
                seen_keys.add(key)

            tcs = [sc for sc in scs if sc["kind"] == "trigger-conflict"]
            expected_tcs = 4 if scope == "global" else 0
            assert len(tcs) == expected_tcs

    # 2. Verify plan has no duplicate paths
    rc = run_env(["resolve-conflicts", "--dry-run", "--workspace", str(fake_ws)], fake_home)
    assert rc["ok"] is True
    plan = rc["plan"]
    plan_paths = [item["path"] for item in plan]
    assert len(plan_paths) == len(set(plan_paths)), f"Duplicate paths found in plan: {plan_paths}"


# ---------------------------------------------------------------------------
# Task 06.4: Real MCP Configs Tests
# ---------------------------------------------------------------------------

def test_jsonc_stripper_and_parser() -> None:
    from orchestration_env import strip_jsonc_comments, strip_trailing_commas, parse_jsonc

    # 1. Line and block comments outside strings
    sample = """
    {
      // single line comment
      "key1": "value1", /* inline block comment */
      /*
         multiline
         block comment
      */
      "key2": 123
    }
    """
    res = parse_jsonc(sample)
    assert res == {"key1": "value1", "key2": 123}

    # 2. Comments inside strings preserved
    sample_strings = """
    {
      "url": "https://example.com/api//test",
      "comment_like": "/* not a comment */ and // not line comment",
      "escaped_quote": "text \\" // still inside string",
      "double_slash_escaped": "path\\\\//still not comment",
      "trailing_comma_in_string": "value, }"
    }
    """
    res2 = parse_jsonc(sample_strings)
    assert res2["url"] == "https://example.com/api//test"
    assert res2["comment_like"] == "/* not a comment */ and // not line comment"
    assert res2["escaped_quote"] == 'text " // still inside string'
    assert res2["trailing_comma_in_string"] == "value, }"

    # 3. Trailing commas in arrays and objects
    sample_commas = """
    {
      "arr": [1, 2, 3, ],
      "obj": {
        "a": "b",
      },
    }
    """
    res3 = parse_jsonc(sample_commas)
    assert res3 == {"arr": [1, 2, 3], "obj": {"a": "b"}}


def test_kilo_merged_view_provenance_and_overrides(tmp_path: pathlib.Path) -> None:
    from orchestration_env import inspect_environment

    fake_home = tmp_path / "home"
    kilo_dir = fake_home / ".config" / "kilo"
    kilo_dir.mkdir(parents=True)

    # 1. config.json (lowest precedence)
    (kilo_dir / "config.json").write_text(json.dumps({
        "mcp": {
            "server-base": {"command": "cmd-base"},
            "server-shared": {"command": "cmd-base-shared"},
        }
    }))

    # 2. kilo.json (overrides config.json)
    (kilo_dir / "kilo.json").write_text(json.dumps({
        "mcp": {
            "server-shared": {"command": "cmd-kilo-shared"},
            "server-kilo": {"command": "cmd-kilo"},
        }
    }))

    # 3. kilo.jsonc (overrides kilo.json, contains JSONC comments)
    (kilo_dir / "kilo.jsonc").write_text("""
    {
      // Kilo JSONC config
      "mcp": {
        /* overrides shared */
        "server-shared": {"command": "cmd-jsonc-shared"},
        "server-jsonc": {"command": "cmd-jsonc"},
      },
    }
    """)

    st = inspect_environment(home=fake_home)
    k_env = st["environments"]["kilo"]["global"]
    assert k_env["registered_mcps"] == ["server-base", "server-jsonc", "server-kilo", "server-shared"]

    mcp_servers = k_env["mcp_servers"]
    assert mcp_servers["server-base"]["provenance"] == str(kilo_dir / "config.json")
    assert mcp_servers["server-base"]["overrides"] == []
    assert mcp_servers["server-base"]["command"] == "cmd-base"

    assert mcp_servers["server-kilo"]["provenance"] == str(kilo_dir / "kilo.json")
    assert mcp_servers["server-kilo"]["overrides"] == []

    assert mcp_servers["server-jsonc"]["provenance"] == str(kilo_dir / "kilo.jsonc")
    assert mcp_servers["server-jsonc"]["overrides"] == []

    assert mcp_servers["server-shared"]["provenance"] == str(kilo_dir / "kilo.jsonc")
    assert mcp_servers["server-shared"]["overrides"] == [
        str(kilo_dir / "config.json"),
        str(kilo_dir / "kilo.json"),
    ]
    assert mcp_servers["server-shared"]["command"] == "cmd-jsonc-shared"


def test_stray_codex_config_json_reported_without_deletion(tmp_path: pathlib.Path) -> None:
    from orchestration_env import inspect_environment

    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)

    # Stray config.json
    stray_file = codex_dir / "config.json"
    stray_file.write_text(json.dumps({"mcpServers": {"old-server": {"command": "old"}}}))

    # Real config.toml
    (codex_dir / "config.toml").write_text("""
    [mcp_servers.real-server]
    command = "python"
    args = ["server.py"]
    """)

    st = inspect_environment(home=fake_home)
    assert st["stray"] == [str(stray_file)]
    assert stray_file.is_file()  # Never deleted
    assert st["environments"]["codex"]["global"]["registered_mcps"] == ["real-server"]


def test_cli_registration_with_stubs(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest
    from orchestration_env import register_mcp_server

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    log_file = tmp_path / "cli.log"

    claude_stub = stub_dir / "claude"
    claude_stub.write_text(f"""#!/bin/sh
echo "claude $@" >> "{log_file}"
""")
    claude_stub.chmod(0o755)

    codex_stub = stub_dir / "codex"
    codex_stub.write_text(f"""#!/bin/sh
echo "codex $@" >> "{log_file}"
""")
    codex_stub.chmod(0o755)

    monkeypatch.setenv("PATH", f"{stub_dir}:{os.environ['PATH']}")

    # 1. Dry run produces plan with action: "cli"
    dry = register_mcp_server(
        "kilo-mcp",
        assistants=["claude", "codex", "kilo"],
        scope="global",
        home=fake_home,
        dry_run=True,
    )
    assert dry["ok"] is True
    plan_by_asst = {item.get("assistant"): item for item in dry["plan"]}
    assert plan_by_asst["claude"]["action"] == "cli"
    assert plan_by_asst["claude"]["argv"][:7] == ["claude", "mcp", "add", "--transport", "stdio", "--scope", "user"]
    assert plan_by_asst["claude"]["argv"][7] == "kilo-mcp"
    assert plan_by_asst["claude"]["argv"][8] == "--"

    assert plan_by_asst["codex"]["action"] == "cli"
    assert plan_by_asst["codex"]["argv"][:5] == ["codex", "mcp", "add", "kilo-mcp", "--"]

    assert plan_by_asst[None]["action"] == "edit"  # Kilo edit
    assert plan_by_asst[None]["path"] == str(fake_home / ".config" / "kilo" / "kilo.json")

    # 2. Execution runs stubs and records invocations
    res = register_mcp_server(
        "kilo-mcp",
        assistants=["claude", "codex", "kilo"],
        scope="global",
        home=fake_home,
        dry_run=False,
    )
    assert res["ok"] is True
    assert len(res["updated_configs"]) == 3

    log_lines = log_file.read_text().splitlines()
    assert any("claude mcp add --transport stdio --scope user kilo-mcp --" in line for line in log_lines)
    assert any("codex mcp add kilo-mcp --" in line for line in log_lines)


def test_codex_project_scope_refused(tmp_path: pathlib.Path) -> None:
    from orchestration_env import register_mcp_server
    import pytest

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    with pytest.raises(ValueError, match="Codex does not support project-scoped MCP registration"):
        register_mcp_server("kilo-mcp", assistants=["codex"], scope="project", home=fake_home)


def test_codex_toml_fallback_refused_on_existing_table(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestration_env import register_mcp_server
    import pytest

    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    cfg_file = codex_dir / "config.toml"
    cfg_file.write_text("""
[mcp_servers.kilo-mcp]
command = "python"
args = ["server.py"]
""")
    original_text = cfg_file.read_text()

    monkeypatch.setenv("PATH", "")

    with pytest.raises(ValueError, match="already exists"):
        register_mcp_server("kilo-mcp", assistants=["codex"], scope="global", home=fake_home)

    assert cfg_file.read_text() == original_text


def test_codex_toml_fallback_surgical_append(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestration_env import register_mcp_server, inspect_environment

    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    cfg_file = codex_dir / "config.toml"
    initial_toml = """[projects."/my/project"]
trust_level = "trusted"

[mcp_servers.other]
command = "node"
args = ["other.js"]
"""
    cfg_file.write_text(initial_toml)

    monkeypatch.setenv("PATH", "")

    res = register_mcp_server("kilo-mcp", assistants=["codex"], scope="global", home=fake_home)
    assert res["ok"] is True

    updated_toml = cfg_file.read_text()
    assert '[projects."/my/project"]' in updated_toml
    assert "[mcp_servers.other]" in updated_toml
    assert "[mcp_servers.kilo-mcp]" in updated_toml
    assert (codex_dir / "config.toml.ai-orch.bak").is_file()

    st = inspect_environment(home=fake_home)
    assert set(st["environments"]["codex"]["global"]["registered_mcps"]) == {"other", "kilo-mcp"}


def test_claude_fallback_refused_while_process_running(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestration_env import register_mcp_server
    import pytest

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    monkeypatch.setenv("PATH", "")

    with pytest.raises(ValueError, match="a claude process is running"):
        register_mcp_server(
            "kilo-mcp",
            assistants=["claude"],
            scope="global",
            home=fake_home,
            claude_running_detector=lambda: True,
        )

    res = register_mcp_server(
        "kilo-mcp",
        assistants=["claude"],
        scope="global",
        home=fake_home,
        claude_running_detector=lambda: False,
    )
    assert res["ok"] is True
    claude_json = fake_home / ".claude.json"
    assert claude_json.is_file()
    data = json.loads(claude_json.read_text())
    assert "kilo-mcp" in data["mcpServers"]


# ---------------------------------------------------------------------------
# Task 13.1: Doctor fixable flag, advice-only plans, project scope deduplication
# ---------------------------------------------------------------------------

def test_doctor_fixable_finding_carries_flag_and_actions(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Install generic and bound skills globally in claude
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration", "--force"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    # 1. Status inspection: conflict carries fixable=True, actions non-empty, scope='global'
    st = run_env(["status"], fake_home)
    scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    assert len(scs) == 4
    sc = next(s for s in scs if set(s["names"]) == {"orchestration-workflow", "kilo-mcp-orchestrator"})
    assert sc["kind"] == "trigger-conflict"
    assert sc["scope"] == "global"
    assert sc["fixable"] is True
    assert sc["actionable"] is True
    assert len(sc["actions"]) == 1
    assert sc["actions"][0]["action"] == "trash"
    assert sc["actions"][0]["path"].endswith("orchestration-workflow")
    assert sc["advice"] == []

    # 2. Dry-run resolution: plan contains executable actions, applied=0, resolved_count=4
    rc_dry = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc_dry["ok"] is True
    assert rc_dry["dry_run"] is True
    assert len(rc_dry["actions"]) == 4
    assert rc_dry["applied"] == 0
    assert rc_dry["resolved_count"] == 4
    assert rc_dry["resolved"] == []

    # 3. Apply resolution: executing plan performs action, returns applied=4, resolved_count=4
    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 4
    assert rc_apply["resolved_count"] == 4
    res_map = {r["removed"]: r["kept"] for r in rc_apply["resolved"] if r["assistant"] == "claude"}
    assert res_map["orchestration-workflow"] == "kilo-mcp-orchestrator"
    assert res_map["executor-contract"] == "kilo-mcp-executor-contract"
    assert res_map["conflict-resolver"] == "kilo-mcp-conflict-resolver"
    assert res_map["orchestration-metrics"] == "kilo-mcp-metrics-analyst"

    # Confirmed resolved in status
    st_after = run_env(["status"], fake_home)
    assert st_after["environments"]["claude"]["global"]["structured_conflicts"] == []


def test_doctor_advice_only_finding_carries_flag_and_apply_is_noop(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Set up two plugins in cache creating a trigger conflict with NO standalone copy
    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_generic = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_generic / "orchestration-workflow").mkdir(parents=True)
    (p_generic / "orchestration-workflow" / "SKILL.md").write_text("# Plugin Generic\n")

    p_bound = plugins_cache / "kilo-mcp" / "architect-side" / "0.2.2" / "skills"
    (p_bound / "kilo-mcp-orchestrator").mkdir(parents=True)
    (p_bound / "kilo-mcp-orchestrator" / "SKILL.md").write_text("# Plugin Bound\n")

    reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_generic.parent),
                }
            ],
            "architect-side@kilo-mcp": [
                {
                    "scope": "user",
                    "installPath": str(p_bound.parent),
                }
            ]
        }
    }))

    # 1. Status inspection: conflict carries fixable=False, actions=[], advice has guidance
    st = run_env(["status"], fake_home)
    scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    assert len(scs) == 1
    sc = scs[0]
    assert sc["kind"] == "trigger-conflict"
    assert sc["scope"] == "global"
    assert sc["fixable"] is False
    assert sc["actionable"] is False
    assert sc["actions"] == []
    assert len(sc["advice"]) == 1
    assert "architect-side@ai-orchestration" in sc["advice"][0]
    assert "disable plugin" not in sc["advice"][0]
    assert sc["severity"] == "warning"
    assert sc["acknowledged"] is False

    # 2. Dry-run resolution: explicitly states actions=[] and advice=[...]
    rc_dry = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc_dry["ok"] is True
    assert rc_dry["dry_run"] is True
    assert rc_dry["actions"] == []
    assert len(rc_dry["advice"]) == 1
    assert "architect-side@ai-orchestration" in rc_dry["advice"][0]
    assert "disable plugin" not in rc_dry["advice"][0]
    assert rc_dry["applied"] == 0
    assert rc_dry["resolved_count"] == 0

    # 3. Apply resolution: advice-only plan is a no-op returning ok=True, applied=0
    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 0
    assert rc_apply["resolved_count"] == 0
    assert rc_apply["actions"] == []
    assert len(rc_apply["advice"]) == 1
    assert rc_apply["resolved"] == []

    # Plugin directories remain untouched
    assert (p_generic / "orchestration-workflow" / "SKILL.md").is_file()
    assert (p_bound / "kilo-mcp-orchestrator" / "SKILL.md").is_file()


def test_doctor_project_scope_does_not_repeat_global_findings(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_ws = tmp_path / "project"
    fake_home.mkdir()
    fake_ws.mkdir()

    # Install global trigger conflict in claude
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration", "--force"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    # 1. Status with project workspace:
    # Finding appears in global section (scope="global"), but is NOT repeated in project section
    st = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    global_scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    assert len(global_scs) == 4
    assert all(s["kind"] == "trigger-conflict" for s in global_scs)
    assert all(s["scope"] == "global" for s in global_scs)

    project_scs = st["environments"]["claude"]["project"]["structured_conflicts"]
    assert project_scs == []
    assert st["environments"]["claude"]["project"]["conflicts"] == []

    # 2. Add a project-specific skill that duplicates a global skill
    proj_skills = fake_ws / ".claude" / "skills" / "project-dup-skill"
    proj_skills.mkdir(parents=True)
    (proj_skills / "SKILL.md").write_text("# Project Copy\n")

    global_skills = fake_home / ".claude" / "skills" / "project-dup-skill"
    global_skills.mkdir(parents=True)
    (global_skills / "SKILL.md").write_text("# Global Copy\n")

    st2 = run_env(["status", "--workspace", str(fake_ws)], fake_home)

    # Global scope does not scan project workspace, so it does not see the duplicate
    g_scs2 = st2["environments"]["claude"]["global"]["structured_conflicts"]
    assert len(g_scs2) == 4
    assert all(sc["kind"] == "trigger-conflict" for sc in g_scs2)

    # Project scope sees the duplicate because it involves a project-scope entry!
    p_scs2 = st2["environments"]["claude"]["project"]["structured_conflicts"]
    assert len(p_scs2) == 1
    assert p_scs2[0]["kind"] == "duplicate-name"
    assert p_scs2[0]["names"] == ["project-dup-skill"]
    assert p_scs2[0]["scope"] == "project"
    assert p_scs2[0]["fixable"] is False
    assert p_scs2[0]["actions"] == []
    assert len(p_scs2[0]["advice"]) == 1
    # Global trigger-conflict is STILL NOT repeated in project scope
    assert not any(sc["kind"] == "trigger-conflict" for sc in p_scs2)


# ---------------------------------------------------------------------------
# Task 13.4: Doctor Stale Claude Plugin Detection
# ---------------------------------------------------------------------------

def test_stale_plugin_detection_older_commit_distance_n(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # 1. Set up marketplace clone with git repo
    mkt_dir = fake_home / ".claude" / "plugins" / "marketplaces" / "test-marketplace"
    mkt_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=mkt_dir, check=True, capture_output=True)

    # Plugin structure in marketplace clone
    plugin_dir = mkt_dir / "plugins" / "demo-plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))
    (plugin_dir / "skills" / "demo-skill").mkdir(parents=True)
    (plugin_dir / "skills" / "demo-skill" / "SKILL.md").write_text("# Demo Skill v1\n")

    # Initial commit (commit 1)
    subprocess.run(["git", "add", "."], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "commit 1"], cwd=mkt_dir, check=True, capture_output=True)
    sha1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=mkt_dir, check=True, capture_output=True, text=True).stdout.strip()

    # 2. Set up cached copy identical to commit 1
    cache_dir = fake_home / ".claude" / "plugins" / "cache" / "test-marketplace" / "demo-plugin" / "1.0.0"
    (cache_dir / ".claude-plugin").mkdir(parents=True)
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))
    (cache_dir / "skills" / "demo-skill").mkdir(parents=True)
    (cache_dir / "skills" / "demo-skill" / "SKILL.md").write_text("# Demo Skill v1\n")

    # 3. Create 2 new commits touching the plugin directory in the marketplace clone
    (plugin_dir / "skills" / "demo-skill" / "SKILL.md").write_text("# Demo Skill v2\n")
    subprocess.run(["git", "add", "."], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "commit 2"], cwd=mkt_dir, check=True, capture_output=True)

    (plugin_dir / "skills" / "demo-skill" / "SKILL.md").write_text("# Demo Skill v3\n")
    subprocess.run(["git", "add", "."], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "commit 3"], cwd=mkt_dir, check=True, capture_output=True)

    # 4. Set up installed_plugins.json recording sha1 and version 1.0.0
    installed_reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    installed_reg.parent.mkdir(parents=True, exist_ok=True)
    installed_reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "demo-plugin@test-marketplace": [
                {
                    "scope": "user",
                    "installPath": str(cache_dir),
                    "version": "1.0.0",
                    "installedAt": "2026-10-01T00:00:00.000Z",
                    "lastUpdated": "2026-10-01T00:00:00.000Z",
                    "gitCommitSha": sha1,
                }
            ]
        }
    }))

    # 5. Run status
    st = run_env(["status"], fake_home)
    claude_global = st["environments"]["claude"]["global"]
    stale_list = claude_global["stale_plugins"]
    assert len(stale_list) == 1
    sp = stale_list[0]
    assert sp["plugin_id"] == "demo-plugin@test-marketplace"
    assert sp["cached_version"] == "1.0.0"
    assert sp["source_version"] == "1.0.0"
    assert sp["versions_equal"] is True
    assert sp["commit_distance"] == 2
    assert sp["content_differs"] is True
    assert "bump the plugin version" in sp["advice"]
    assert "claude plugin marketplace update test-marketplace" in sp["advice"]
    assert "claude plugin update demo-plugin@test-marketplace" in sp["advice"]

    # Also verify structured_conflicts has stale-plugin-copy with fixable: False
    scs = claude_global["structured_conflicts"]
    stale_scs = [sc for sc in scs if sc["kind"] == "stale-plugin-copy"]
    assert len(stale_scs) == 1
    assert stale_scs[0]["fixable"] is False
    assert stale_scs[0]["actionable"] is False
    assert stale_scs[0]["advice"] == [sp["advice"]]


def test_stale_plugin_equal_is_not_stale(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    mkt_dir = fake_home / ".claude" / "plugins" / "marketplaces" / "test-marketplace"
    mkt_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=mkt_dir, check=True, capture_output=True)

    plugin_dir = mkt_dir / "plugins" / "demo-plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))
    (plugin_dir / "skills" / "demo-skill").mkdir(parents=True)
    (plugin_dir / "skills" / "demo-skill" / "SKILL.md").write_text("# Demo Skill v1\n")

    subprocess.run(["git", "add", "."], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "commit 1"], cwd=mkt_dir, check=True, capture_output=True)
    sha1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=mkt_dir, check=True, capture_output=True, text=True).stdout.strip()

    # Cache copy matching commit 1 exactly
    cache_dir = fake_home / ".claude" / "plugins" / "cache" / "test-marketplace" / "demo-plugin" / "1.0.0"
    (cache_dir / ".claude-plugin").mkdir(parents=True)
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))
    (cache_dir / "skills" / "demo-skill").mkdir(parents=True)
    (cache_dir / "skills" / "demo-skill" / "SKILL.md").write_text("# Demo Skill v1\n")

    installed_reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    installed_reg.parent.mkdir(parents=True, exist_ok=True)
    installed_reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "demo-plugin@test-marketplace": [
                {
                    "scope": "user",
                    "installPath": str(cache_dir),
                    "version": "1.0.0",
                    "gitCommitSha": sha1,
                }
            ]
        }
    }))

    st = run_env(["status"], fake_home)
    assert st["environments"]["claude"]["global"]["stale_plugins"] == []
    scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    assert not any(sc["kind"] == "stale-plugin-copy" for sc in scs)


def test_stale_plugin_version_bumped_advice(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    mkt_dir = fake_home / ".claude" / "plugins" / "marketplaces" / "test-marketplace"
    mkt_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=mkt_dir, check=True, capture_output=True)

    plugin_dir = mkt_dir / "plugins" / "demo-plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))
    subprocess.run(["git", "add", "."], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "v1.0.0"], cwd=mkt_dir, check=True, capture_output=True)
    sha1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=mkt_dir, check=True, capture_output=True, text=True).stdout.strip()

    # Cached copy at 1.0.0
    cache_dir = fake_home / ".claude" / "plugins" / "cache" / "test-marketplace" / "demo-plugin" / "1.0.0"
    (cache_dir / ".claude-plugin").mkdir(parents=True)
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))

    # Bump version in marketplace clone to 1.1.0
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.1.0",
        "description": "Demo Plugin"
    }))
    subprocess.run(["git", "add", "."], cwd=mkt_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "bump to 1.1.0"], cwd=mkt_dir, check=True, capture_output=True)

    installed_reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    installed_reg.parent.mkdir(parents=True, exist_ok=True)
    installed_reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "demo-plugin@test-marketplace": [
                {
                    "scope": "user",
                    "installPath": str(cache_dir),
                    "version": "1.0.0",
                    "gitCommitSha": sha1,
                }
            ]
        }
    }))

    st = run_env(["status"], fake_home)
    stale_list = st["environments"]["claude"]["global"]["stale_plugins"]
    assert len(stale_list) == 1
    sp = stale_list[0]
    assert sp["cached_version"] == "1.0.0"
    assert sp["source_version"] == "1.1.0"
    assert sp["versions_equal"] is False
    assert sp["commit_distance"] == 1
    assert "plugin update" in sp["advice"]
    assert sp["advice"] == "run `claude plugin update demo-plugin@test-marketplace`"


def test_stale_plugin_missing_git_degrades_to_unknown_no_crash(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Marketplace clone WITHOUT .git directory (e.g. downloaded archive or git missing)
    mkt_dir = fake_home / ".claude" / "plugins" / "marketplaces" / "test-marketplace"
    plugin_dir = mkt_dir / "plugins" / "demo-plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))
    (plugin_dir / "skills" / "demo-skill").mkdir(parents=True)
    (plugin_dir / "skills" / "demo-skill" / "SKILL.md").write_text("# Newer content in clone\n")

    # Cache copy with older / different content
    cache_dir = fake_home / ".claude" / "plugins" / "cache" / "test-marketplace" / "demo-plugin" / "1.0.0"
    (cache_dir / ".claude-plugin").mkdir(parents=True)
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))
    (cache_dir / "skills" / "demo-skill").mkdir(parents=True)
    (cache_dir / "skills" / "demo-skill" / "SKILL.md").write_text("# Older content in cache\n")

    installed_reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    installed_reg.parent.mkdir(parents=True, exist_ok=True)
    installed_reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "demo-plugin@test-marketplace": [
                {
                    "scope": "user",
                    "installPath": str(cache_dir),
                    "version": "1.0.0",
                    "gitCommitSha": "some-random-sha-not-in-git",
                }
            ]
        }
    }))

    # Must not crash, commit_distance degrades to "unknown"
    st = run_env(["status"], fake_home)
    stale_list = st["environments"]["claude"]["global"]["stale_plugins"]
    assert len(stale_list) == 1
    sp = stale_list[0]
    assert sp["commit_distance"] == "unknown"
    assert sp["content_differs"] is True
    assert sp["versions_equal"] is True
    assert "bump the plugin version" in sp["advice"]


def test_stale_plugin_disabled_plugin_not_reported(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Disable the plugin in ~/.claude/settings.json
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text(json.dumps({
        "enabledPlugins": {
            "demo-plugin@test-marketplace": False
        }
    }))

    mkt_dir = fake_home / ".claude" / "plugins" / "marketplaces" / "test-marketplace"
    plugin_dir = mkt_dir / "plugins" / "demo-plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "2.0.0",
        "description": "Demo Plugin"
    }))

    cache_dir = fake_home / ".claude" / "plugins" / "cache" / "test-marketplace" / "demo-plugin" / "1.0.0"
    (cache_dir / ".claude-plugin").mkdir(parents=True)
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin",
        "version": "1.0.0",
        "description": "Demo Plugin"
    }))

    installed_reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    installed_reg.parent.mkdir(parents=True, exist_ok=True)
    installed_reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "demo-plugin@test-marketplace": [
                {
                    "scope": "user",
                    "installPath": str(cache_dir),
                    "version": "1.0.0",
                }
            ]
        }
    }))

    st = run_env(["status"], fake_home)
    assert st["environments"]["claude"]["global"]["stale_plugins"] == []


# ---------------------------------------------------------------------------
# Task 13.5: History-aware legacy classification and standalone duplicates (P2-a, P2-d)
# ---------------------------------------------------------------------------

def _setup_mock_source_repo_with_history(fake_home: pathlib.Path, skill_name: str = "demo-legacy-skill") -> tuple[pathlib.Path, list[str]]:
    """Create a mock git repository in ~/.ai-orchestration/repos/ai-orchestration with 3 commits of a skill."""
    repo = fake_home / ".ai-orchestration" / "repos" / "ai-orchestration"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)

    skill_dir = repo / "plugins" / "architect-side" / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Commit 1
    (skill_dir / "SKILL.md").write_text("# Demo Legacy Skill v1\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "Commit 1"], check=True, capture_output=True)
    c1_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    # Commit 2
    (skill_dir / "SKILL.md").write_text("# Demo Legacy Skill v2\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "Commit 2"], check=True, capture_output=True)
    c2_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    # Commit 3 (HEAD)
    (skill_dir / "SKILL.md").write_text("# Demo Legacy Skill v3 (HEAD)\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "Commit 3"], check=True, capture_output=True)
    c3_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    return repo, [c1_sha, c2_sha, c3_sha]


def test_history_aware_legacy_outdated_classification_and_update(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    repo, shas = _setup_mock_source_repo_with_history(fake_home, "demo-legacy-skill")

    # Install a standalone copy with content matching Commit 1 (without receipt)
    claude_skills = fake_home / ".claude" / "skills"
    installed_dir = claude_skills / "demo-legacy-skill"
    installed_dir.mkdir(parents=True)
    (installed_dir / "SKILL.md").write_text("# Demo Legacy Skill v1\n")

    # 1. Status: classified as outdated-legacy, fixable=True, action=update
    st = run_env(["status"], fake_home)
    c_skills = st["environments"]["claude"]["global"]["skills"]
    assert c_skills["demo-legacy-skill"]["state"] == "outdated-legacy"

    scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    outdated_scs = [sc for sc in scs if sc["kind"] == "outdated-legacy" and sc["names"] == ["demo-legacy-skill"]]
    assert len(outdated_scs) == 1
    sc = outdated_scs[0]
    assert sc["fixable"] is True
    assert sc["actionable"] is True
    assert len(sc["actions"]) == 1
    action = sc["actions"][0]
    assert action["action"] == "update"
    assert action["path"] == str(installed_dir)
    assert action["current_state"] == "outdated-legacy"
    assert sc["advice"] == []

    # 2. Dry-run resolution: dry_run=True, applied=0, disk unmodified
    rc_dry = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc_dry["ok"] is True
    assert rc_dry["dry_run"] is True
    assert rc_dry["applied"] == 0
    assert rc_dry["resolved_count"] == 1
    assert len(rc_dry["actions"]) == 1
    assert rc_dry["actions"][0]["action"] == "update"
    assert (installed_dir / "SKILL.md").read_text() == "# Demo Legacy Skill v1\n"
    assert not (installed_dir / ".ai-orch-source.json").exists()

    # 3. Apply resolution: updates skill, writes receipt, trashes old copy
    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 1
    assert rc_apply["resolved_count"] == 1
    assert rc_apply["resolved"][0]["action"] == "update"
    assert rc_apply["resolved"][0]["skill"] == "demo-legacy-skill"

    # Disk has current version (Commit 3) and receipt
    assert (installed_dir / "SKILL.md").read_text() == "# Demo Legacy Skill v3 (HEAD)\n"
    assert (installed_dir / ".ai-orch-source.json").is_file()
    receipt = json.loads((installed_dir / ".ai-orch-source.json").read_text(encoding="utf-8"))
    assert receipt["repo"] == "ai-orchestration"
    assert receipt["name"] == "demo-legacy-skill"

    # Old version was moved to centralized trash
    trash_base = fake_home / ".config" / "ai-orchestration" / "trash" / "claude" / "global"
    trashed = list(trash_base.glob("*/skills/demo-legacy-skill/SKILL.md"))
    assert len(trashed) >= 1
    assert trashed[0].read_text() == "# Demo Legacy Skill v1\n"

    # Next status check: up-to-date and no conflicts
    st2 = run_env(["status"], fake_home)
    assert st2["environments"]["claude"]["global"]["skills"]["demo-legacy-skill"]["state"] == "up-to-date"
    assert st2["environments"]["claude"]["global"]["structured_conflicts"] == []


def test_history_aware_legacy_adopt_and_foreign_classification(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    _setup_mock_source_repo_with_history(fake_home, "demo-legacy-skill")

    claude_skills = fake_home / ".claude" / "skills"
    installed_dir = claude_skills / "demo-legacy-skill"
    installed_dir.mkdir(parents=True)

    # 1. Test up-to-date-legacy: content matching HEAD but no receipt
    (installed_dir / "SKILL.md").write_text("# Demo Legacy Skill v3 (HEAD)\n")

    st = run_env(["status"], fake_home)
    assert st["environments"]["claude"]["global"]["skills"]["demo-legacy-skill"]["state"] == "up-to-date-legacy"
    scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    adopt_scs = [sc for sc in scs if sc["kind"] == "up-to-date-legacy" and sc["names"] == ["demo-legacy-skill"]]
    assert len(adopt_scs) == 1
    assert adopt_scs[0]["fixable"] is True
    assert adopt_scs[0]["actions"][0]["action"] == "adopt"

    # Dry-run writes nothing
    rc_dry = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc_dry["ok"] is True
    assert rc_dry["applied"] == 0
    assert not (installed_dir / ".ai-orch-source.json").exists()

    # Apply adopts and writes receipt
    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 1
    assert rc_apply["resolved"][0]["action"] == "adopt"
    assert (installed_dir / ".ai-orch-source.json").is_file()

    st2 = run_env(["status"], fake_home)
    assert st2["environments"]["claude"]["global"]["skills"]["demo-legacy-skill"]["state"] == "up-to-date"
    assert st2["environments"]["claude"]["global"]["structured_conflicts"] == []

    # 2. Test foreign: modified content that does not match any git history commit
    (installed_dir / ".ai-orch-source.json").unlink()
    (installed_dir / "SKILL.md").write_text("# Modified Content Completely Foreign\n")

    st3 = run_env(["status"], fake_home)
    assert st3["environments"]["claude"]["global"]["skills"]["demo-legacy-skill"]["state"] == "foreign"
    foreign_scs = [sc for sc in st3["environments"]["claude"]["global"]["structured_conflicts"] if sc["kind"] == "foreign"]
    assert len(foreign_scs) == 1
    assert foreign_scs[0]["fixable"] is False
    assert foreign_scs[0]["actions"] == []
    assert len(foreign_scs[0]["advice"]) == 1

    # Apply is no-op (advice only)
    rc_apply_foreign = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply_foreign["ok"] is True
    assert rc_apply_foreign["applied"] == 0
    assert rc_apply_foreign["actions"] == []
    assert len(rc_apply_foreign["advice"]) == 1
    assert (installed_dir / "SKILL.md").read_text() == "# Modified Content Completely Foreign\n"


def test_standalone_only_duplicates_p2d_resolution(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_ws = tmp_path / "project"
    fake_home.mkdir()
    fake_ws.mkdir()

    _setup_mock_source_repo_with_history(fake_home, "demo-dup-skill")

    global_skill = fake_home / ".claude" / "skills" / "demo-dup-skill"
    project_skill = fake_ws / ".claude" / "skills" / "demo-dup-skill"
    global_skill.mkdir(parents=True)
    project_skill.mkdir(parents=True)

    # Case A: One copy matches current source (HEAD), the other is outdated-legacy (Commit 1)
    # Project copy is HEAD, global copy is Commit 1
    project_skill_md = project_skill / "SKILL.md"
    global_skill_md = global_skill / "SKILL.md"
    project_skill_md.write_text("# Demo Legacy Skill v3 (HEAD)\n")
    global_skill_md.write_text("# Demo Legacy Skill v1\n")

    st = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    p_scs = st["environments"]["claude"]["project"]["structured_conflicts"]
    dup_scs = [sc for sc in p_scs if sc["kind"] == "duplicate-name" and sc["names"] == ["demo-dup-skill"]]
    assert len(dup_scs) == 1
    dup_sc = dup_scs[0]
    assert dup_sc["fixable"] is True
    assert dup_sc["actionable"] is True
    assert len(dup_sc["actions"]) == 1
    assert dup_sc["actions"][0]["action"] == "trash"
    assert dup_sc["actions"][0]["path"] == str(global_skill)

    # Dry-run: writes nothing
    rc_dry = run_env(["resolve-conflicts", "--workspace", str(fake_ws), "--dry-run"], fake_home)
    assert rc_dry["ok"] is True
    assert rc_dry["dry_run"] is True
    assert rc_dry["applied"] == 0
    assert global_skill.exists()
    assert project_skill.exists()

    # Apply: trashes global copy, keeps project copy
    rc_apply = run_env(["resolve-conflicts", "--workspace", str(fake_ws), "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] >= 1
    assert not global_skill.exists()
    assert project_skill.exists()
    assert project_skill_md.read_text() == "# Demo Legacy Skill v3 (HEAD)\n"

    # Case B: Both copies differ from every source version -> advice only
    global_skill.mkdir(parents=True)
    global_skill_md.write_text("# Foreign Global Edit\n")
    project_skill_md.write_text("# Foreign Project Edit\n")

    st2 = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    p_scs2 = st2["environments"]["claude"]["project"]["structured_conflicts"]
    dup_scs2 = [sc for sc in p_scs2 if sc["kind"] == "duplicate-name" and sc["names"] == ["demo-dup-skill"]]
    assert len(dup_scs2) == 1
    dup_sc2 = dup_scs2[0]
    assert dup_sc2["fixable"] is False
    assert dup_sc2["actionable"] is False
    assert dup_sc2["actions"] == []
    assert len(dup_sc2["advice"]) == 1

    rc_apply2 = run_env(["resolve-conflicts", "--workspace", str(fake_ws), "--apply"], fake_home)
    assert rc_apply2["ok"] is True
    assert rc_apply2["applied"] == 0
    assert global_skill.exists()
    assert project_skill.exists()

    # Case C: Both copies identical (both Commit 1, neither HEAD) -> fixable, keeps global by default
    global_skill_md.write_text("# Demo Legacy Skill v1\n")
    project_skill_md.write_text("# Demo Legacy Skill v1\n")

    st3 = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    p_scs3 = st3["environments"]["claude"]["project"]["structured_conflicts"]
    dup_scs3 = [sc for sc in p_scs3 if sc["kind"] == "duplicate-name" and sc["names"] == ["demo-dup-skill"]]
    assert len(dup_scs3) == 1
    dup_sc3 = dup_scs3[0]
    assert dup_sc3["fixable"] is True
    assert dup_sc3["actions"][0]["action"] == "trash"
    assert dup_sc3["actions"][0]["path"] == str(project_skill)

    rc_apply3 = run_env(["resolve-conflicts", "--workspace", str(fake_ws), "--apply"], fake_home)
    assert rc_apply3["ok"] is True
    assert rc_apply3["applied"] >= 1
    assert global_skill.exists()
    assert not project_skill.exists()

    # Case D: Both copies match HEAD, with keep_scope = "project" in orchestration.toml
    project_skill.mkdir(parents=True)
    project_skill_md.write_text("# Demo Legacy Skill v3 (HEAD)\n")
    global_skill_md.write_text("# Demo Legacy Skill v3 (HEAD)\n")

    cfg_dir = fake_home / ".config" / "ai-orchestration"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "orchestration.toml").write_text(
        '[env.conflicts]\nkeep_scope = "project"\n',
        encoding="utf-8",
    )

    st4 = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    p_scs4 = st4["environments"]["claude"]["project"]["structured_conflicts"]
    dup_scs4 = [sc for sc in p_scs4 if sc["kind"] == "duplicate-name" and sc["names"] == ["demo-dup-skill"]]
    assert len(dup_scs4) == 1
    dup_sc4 = dup_scs4[0]
    assert dup_sc4["fixable"] is True
    assert dup_sc4["actions"][0]["action"] == "trash"
    assert dup_sc4["actions"][0]["path"] == str(global_skill)

    rc_apply4 = run_env(["resolve-conflicts", "--workspace", str(fake_ws), "--apply"], fake_home)
    assert rc_apply4["ok"] is True
    assert rc_apply4["applied"] >= 1
    assert not global_skill.exists()
    assert project_skill.exists()


def test_doctor_severity_model_and_unmanaged_skills(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # 1. Create unmanaged third-party skill (e.g. impeccable) with no conflict
    kilo_skills = fake_home / ".kilo" / "skills"
    unmanaged_dir = kilo_skills / "impeccable"
    unmanaged_dir.mkdir(parents=True)
    (unmanaged_dir / "SKILL.md").write_text("# Impeccable Design\n")

    st = run_env(["status"], fake_home)
    entries = st["environments"]["kilo"]["global"]["skill_entries"]
    imp_entry = next((e for e in entries if e["name"] == "impeccable"), None)
    assert imp_entry is not None
    assert imp_entry["state"] == "unmanaged"
    assert imp_entry["severity"] == "info"

    # Verify four severity levels are defined in the severity model
    from orchestration_env import SEVERITY_LEVELS
    assert SEVERITY_LEVELS == ("error", "warning", "info", "neutral")


def test_doctor_cross_assistant_grouping_and_summary_counts(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Standalone + plugin in claude
    c_skills = fake_home / ".claude" / "skills" / "shared-skill"
    c_skills.mkdir(parents=True)
    (c_skills / "SKILL.md").write_text("# Standalone v1\n")

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "test-plugin" / "pkg" / "1.0.0" / "skills"
    (p_skills / "shared-skill").mkdir(parents=True)
    (p_skills / "shared-skill" / "SKILL.md").write_text("# Plugin v2 (differs)\n")

    reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "pkg@test-plugin": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    # Also duplicate name across project scope
    fake_ws = tmp_path / "workspace"
    fake_ws.mkdir()
    ws_claude_skill = fake_ws / ".claude" / "skills" / "shared-skill"
    ws_claude_skill.mkdir(parents=True)
    (ws_claude_skill / "SKILL.md").write_text("# Project copy\n")

    st = run_env(["status", "--workspace", str(fake_ws)], fake_home)

    scs_claude = st["environments"]["claude"]["global"]["structured_conflicts"]
    assert len(scs_claude) >= 1
    sc = scs_claude[0]
    assert sc["group_key"] == "duplicate-name:shared-skill"
    assert "severity" in sc
    assert "acknowledged" in sc
    assert "locations" in sc
    assert {"assistant": "claude", "scope": "global"} in sc["locations"]

    # Verify finding_groups at top level
    fg = st["finding_groups"]
    group = next((g for g in fg if g["group_key"] == "duplicate-name:shared-skill"), None)
    assert group is not None
    assert group["kind"] == "duplicate-name"
    assert group["names"] == ["shared-skill"]

    # Summary counts reflect groups
    sm = st["summary"]
    assert sm["total_groups"] == len(fg)
    assert sm[group["severity"]] >= 1


def test_doctor_trigger_conflict_automatic_precedence_and_no_disabling(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Plugins cache with Precedence in BOTH skills
    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_generic = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_generic / "orchestration-workflow").mkdir(parents=True)
    (p_generic / "orchestration-workflow" / "SKILL.md").write_text("# Generic\n\n### Precedence with Bound Skills\nWhen bound skill loaded, defer...\n")

    p_bound = plugins_cache / "kilo-mcp" / "architect-side" / "0.2.2" / "skills"
    (p_bound / "kilo-mcp-orchestrator").mkdir(parents=True)
    (p_bound / "kilo-mcp-orchestrator" / "SKILL.md").write_text("# Bound\n\n### Precedence with Generic Skills\nSpecializes tool calls...\n")

    reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_generic.parent),
                }
            ],
            "architect-side@kilo-mcp": [
                {
                    "scope": "user",
                    "installPath": str(p_bound.parent),
                }
            ]
        }
    }))

    st = run_env(["status"], fake_home)
    scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    assert len(scs) == 1
    sc = scs[0]
    assert sc["kind"] == "trigger-conflict"
    # Automatically acknowledged and info severity!
    assert sc["acknowledged"] is True
    assert sc["severity"] == "info"
    assert "Precedence" in sc["advice"][0]
    assert st["summary"]["acknowledged"] >= 1

    # Now remove Precedence section from one of the copies
    (p_bound / "kilo-mcp-orchestrator" / "SKILL.md").write_text("# Bound without precedence section\n")
    st_noprec = run_env(["status"], fake_home)
    sc_noprec = st_noprec["environments"]["claude"]["global"]["structured_conflicts"][0]
    assert sc_noprec["acknowledged"] is False
    assert sc_noprec["severity"] == "warning"
    # Crucial: never advise disabling architect-side@ai-orchestration
    assert "disable plugin" not in sc_noprec["advice"][0]
    assert "architect-side@ai-orchestration" in sc_noprec["advice"][0]


def test_doctor_persistent_ack_and_unack_cli(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Create a duplicate name conflict (advice only)
    c_skills = fake_home / ".claude" / "skills" / "demo-ack-skill"
    c_skills.mkdir(parents=True)
    c_skill_md = c_skills / "SKILL.md"
    c_skill_md.write_text("# Standalone Copy v1\n")

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "demo-pkg" / "demo" / "1.0.0" / "skills"
    (p_skills / "demo-ack-skill").mkdir(parents=True)
    (p_skills / "demo-ack-skill" / "SKILL.md").write_text("# Plugin Copy v2 (different)\n")

    reg = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "demo@demo-pkg": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    # 1. Status before ack: unacknowledged
    st1 = run_env(["status"], fake_home)
    sc1 = st1["environments"]["claude"]["global"]["structured_conflicts"][0]
    assert sc1["acknowledged"] is False
    assert st1["summary"]["acknowledged"] == 0
    gkey = sc1["group_key"]
    assert gkey == "duplicate-name:demo-ack-skill"

    # 2. Test dry-run ack
    ack_dry = run_env(["ack", gkey, "--note", "Testing ack", "--dry-run"], fake_home)
    assert ack_dry["ok"] is True
    assert ack_dry["dry_run"] is True
    assert len(ack_dry["plan"]) == 1
    plan_hash = ack_dry["plan_hash"]

    # Status unchanged after dry-run
    st_dry = run_env(["status"], fake_home)
    assert st_dry["environments"]["claude"]["global"]["structured_conflicts"][0]["acknowledged"] is False

    # 3. Test apply ack with expect-plan-hash
    ack_res = run_env(["ack", gkey, "--note", "Testing ack", "--expect-plan-hash", plan_hash], fake_home)
    assert ack_res["ok"] is True
    assert ack_res["acknowledged"] is True

    # Check persistence in doctor-ack.json
    ack_file = fake_home / ".config" / "ai-orchestration" / "doctor-ack.json"
    assert ack_file.is_file()
    ack_data = json.loads(ack_file.read_text(encoding="utf-8"))
    assert "acknowledgments" in ack_data
    assert len(ack_data["acknowledgments"]) == 1

    # 4. Status after ack: acknowledged=True, severity=info, summary shows acknowledged
    st2 = run_env(["status"], fake_home)
    sc2 = st2["environments"]["claude"]["global"]["structured_conflicts"][0]
    assert sc2["acknowledged"] is True
    assert sc2["severity"] == "info"
    assert st2["summary"]["acknowledged"] == 1

    # 5. Content modification causes ack to lapse automatically!
    c_skill_md.write_text("# Standalone Copy v1 (MODIFIED CONTENT)\n")
    st3 = run_env(["status"], fake_home)
    sc3 = st3["environments"]["claude"]["global"]["structured_conflicts"][0]
    assert sc3["acknowledged"] is False
    assert st3["summary"]["acknowledged"] == 0

    # Re-ack modified content
    run_env(["ack", gkey, "--note", "Re-ack after edit"], fake_home)
    st4 = run_env(["status"], fake_home)
    assert st4["environments"]["claude"]["global"]["structured_conflicts"][0]["acknowledged"] is True

    # 6. Test unack
    unack_res = run_env(["unack", gkey], fake_home)
    assert unack_res["ok"] is True
    assert unack_res["unacknowledged"] is True

    st5 = run_env(["status"], fake_home)
    assert st5["environments"]["claude"]["global"]["structured_conflicts"][0]["acknowledged"] is False
    assert st5["summary"]["acknowledged"] == 0


def test_doctor_json_backward_compatibility(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    st = run_env(["status"], fake_home)
    expected_top_keys = {"clis", "source_repos", "available_catalog_count", "environments", "stray", "finding_groups", "groups", "summary", "severity_counts"}
    assert expected_top_keys.issubset(set(st.keys()))

    kilo_env = st["environments"]["kilo"]["global"]
    expected_env_keys = {
        "skills_dir", "installed_count", "skills", "skill_entries",
        "agents_dir", "agents", "conflicts", "structured_conflicts",
        "stale_plugins", "mcp_config_path", "registered_mcps", "mcp_servers",
    }
    assert expected_env_keys.issubset(set(kilo_env.keys()))


# ---------------------------------------------------------------------------
# Initiative 13.3 Tests: Smarter Duplicate Resolution (Equality & History)
# ---------------------------------------------------------------------------

def test_duplicate_name_reserialized_frontmatter_resolves_to_trash(tmp_path: pathlib.Path) -> None:
    """Standalone copy with re-serialized/flattened frontmatter (equal to plugin after normalization) auto-resolves to trash."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "gcube-ai-toolkit" / "gcube-developer-tools" / "0.2.1" / "skills"
    (p_skills / "gcube-component-release").mkdir(parents=True)
    plugin_skill_md = p_skills / "gcube-component-release" / "SKILL.md"
    plugin_skill_md.write_text(
        "---\n"
        "name: gcube-component-release\n"
        "description: \"Release gcube components\"\n"
        "metadata:\n"
        "  author: Alfredo Oliviero\n"
        "  version: 1.0.0\n"
        "---\n\n"
        "# gCube Component Release\n\n"
        "Release lifecycle documentation.\n"
    )

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "gcube-developer-tools@gcube-ai-toolkit": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    standalone_dir = fake_home / ".claude" / "skills" / "gcube-component-release"
    standalone_dir.mkdir(parents=True)
    standalone_skill_md = standalone_dir / "SKILL.md"
    # Flattened metadata (metadata: "") written by early installer
    standalone_skill_md.write_text(
        "---\n"
        "name: gcube-component-release\n"
        "description: \"Release gcube components\"\n"
        "metadata: \"\"\n"
        "author: Alfredo Oliviero\n"
        "version: 1.0.0\n"
        "---\n\n"
        "# gCube Component Release\n\n"
        "Release lifecycle documentation.\n"
    )

    st = run_env(["status"], fake_home)
    dup_scs = [sc for sc in st["environments"]["claude"]["global"]["structured_conflicts"] if sc["kind"] == "duplicate-name"]
    assert len(dup_scs) == 1
    dup_sc = dup_scs[0]
    assert dup_sc["fixable"] is True
    assert dup_sc["actionable"] is True
    assert len(dup_sc["actions"]) == 1
    assert dup_sc["actions"][0]["action"] == "trash"
    assert dup_sc["actions"][0]["path"] == str(standalone_dir)

    # Dry-run writes nothing
    rc_dry = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc_dry["ok"] is True
    assert rc_dry["dry_run"] is True
    assert rc_dry["applied"] == 0
    assert standalone_dir.exists()

    # Apply trashes standalone and keeps plugin
    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 1
    assert not standalone_dir.exists()
    assert plugin_skill_md.is_file()


def test_duplicate_name_folded_description_and_whitespace_resolves_to_trash(tmp_path: pathlib.Path) -> None:
    """Folded description (>-) vs quoted string, CRLF vs LF line endings, and trailing whitespace normalize equal."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.4.0" / "skills"
    (p_skills / "demo-folded-skill").mkdir(parents=True)
    (p_skills / "demo-folded-skill" / "SKILL.md").write_text(
        "---\n"
        "name: demo-folded-skill\n"
        "description: >-\n"
        "  Create distinctive frontend interfaces\n"
        "  with high design quality.\n"
        "license: Apache-2.0\n"
        "---\n\n"
        "# Body content line 1\n"
        "# Body content line 2\n"
    )

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    standalone_dir = fake_home / ".claude" / "skills" / "demo-folded-skill"
    standalone_dir.mkdir(parents=True)
    # Quoted description on single line, CRLF line endings, trailing spaces on lines
    (standalone_dir / "SKILL.md").write_text(
        "---\r\n"
        "name: demo-folded-skill\r\n"
        "description: \"Create distinctive frontend interfaces with high design quality.\"\r\n"
        "license: Apache-2.0   \r\n"
        "---\r\n\r\n"
        "# Body content line 1  \r\n"
        "# Body content line 2\r\n\r\n"
    )

    st = run_env(["status"], fake_home)
    dup_scs = [sc for sc in st["environments"]["claude"]["global"]["structured_conflicts"] if sc["kind"] == "duplicate-name"]
    assert len(dup_scs) == 1
    assert dup_scs[0]["fixable"] is True
    assert dup_scs[0]["actions"][0]["action"] == "trash"


def test_duplicate_name_older_cached_plugin_resolves_to_trash(tmp_path: pathlib.Path) -> None:
    """Standalone copy matching an earlier cached version of the plugin resolves to trash."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Cached plugin has 0.1.0 and 0.2.0
    plugins_cache = fake_home / ".claude" / "plugins" / "cache" / "agentic-coding-kit" / "agent-tooling-meta"
    p_010 = plugins_cache / "0.1.0" / "skills" / "framework-skillset-generator"
    p_020 = plugins_cache / "0.2.0" / "skills" / "framework-skillset-generator"
    p_010.mkdir(parents=True)
    p_020.mkdir(parents=True)

    (p_010 / "SKILL.md").write_text("# Framework Skillset Generator v1.0\nLegacy initial draft.\n")
    (p_020 / "SKILL.md").write_text("# Framework Skillset Generator v2.0\nModern overhauled version.\n")

    # Active install in installed_plugins.json points to 0.2.0
    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "agent-tooling-meta@agentic-coding-kit": [
                {
                    "scope": "user",
                    "installPath": str(plugins_cache / "0.2.0"),
                    "version": "0.2.0",
                }
            ]
        }
    }))

    # Standalone copy matches older cached version 0.1.0
    standalone_dir = fake_home / ".claude" / "skills" / "framework-skillset-generator"
    standalone_dir.mkdir(parents=True)
    (standalone_dir / "SKILL.md").write_text("# Framework Skillset Generator v1.0\nLegacy initial draft.\n")

    st = run_env(["status"], fake_home)
    dup_scs = [sc for sc in st["environments"]["claude"]["global"]["structured_conflicts"] if sc["kind"] == "duplicate-name"]
    assert len(dup_scs) == 1
    dup_sc = dup_scs[0]
    assert dup_sc["fixable"] is True
    assert dup_sc["actionable"] is True
    assert dup_sc["actions"][0]["action"] == "trash"
    assert dup_sc["actions"][0]["path"] == str(standalone_dir)

    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 1
    assert not standalone_dir.exists()


def test_duplicate_name_older_git_history_copy_resolves_to_trash(tmp_path: pathlib.Path) -> None:
    """Standalone copy matching an earlier commit in source repo history resolves to trash."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    repo, shas = _setup_mock_source_repo_with_history(fake_home, "task-spec-authoring")
    # Commit plugin.json in repo so plugin is recognized as up to date (not stale)
    p_repo_dir = repo / "plugins" / "architect-side"
    (p_repo_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (p_repo_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "0.5.4"}))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "Add plugin.json"], check=True)
    head_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.5.4" / "skills"
    p_sdir = p_skills / "task-spec-authoring"
    p_sdir.mkdir(parents=True)
    (p_sdir / "SKILL.md").write_text("# Demo Legacy Skill v3 (HEAD)\n")
    (p_skills.parent / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (p_skills.parent / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "0.5.4"}))

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                    "version": "0.5.4",
                    "gitCommitSha": head_sha,
                }
            ]
        }
    }))

    # Standalone copy matches Commit 1 (older commit in git history)
    standalone_dir = fake_home / ".claude" / "skills" / "task-spec-authoring"
    standalone_dir.mkdir(parents=True)
    (standalone_dir / "SKILL.md").write_text("# Demo Legacy Skill v1\n")

    st = run_env(["status"], fake_home)
    dup_scs = [sc for sc in st["environments"]["claude"]["global"]["structured_conflicts"] if sc["kind"] == "duplicate-name"]
    assert len(dup_scs) == 1
    dup_sc = dup_scs[0]
    assert dup_sc["fixable"] is True
    assert dup_sc["actionable"] is True
    assert dup_sc["actions"][0]["action"] == "trash"
    assert dup_sc["actions"][0]["path"] == str(standalone_dir)

    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 1
    assert not standalone_dir.exists()


def test_duplicate_name_real_divergence_stays_advice_with_diff_summary(tmp_path: pathlib.Path) -> None:
    """Real divergences stay advice, with a short diff summary (files and changed frontmatter keys)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.5.4" / "skills"
    (p_skills / "custom-workflow").mkdir(parents=True)
    (p_skills / "custom-workflow" / "SKILL.md").write_text(
        "---\n"
        "name: custom-workflow\n"
        "description: \"Standard workflow description\"\n"
        "version: 1.0.0\n"
        "---\n\n"
        "# Standard Workflow Body\n"
    )

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    standalone_dir = fake_home / ".claude" / "skills" / "custom-workflow"
    standalone_dir.mkdir(parents=True)
    # Standalone has different version, different body, and extra file
    (standalone_dir / "SKILL.md").write_text(
        "---\n"
        "name: custom-workflow\n"
        "description: \"Standard workflow description\"\n"
        "version: 2.5.0\n"
        "---\n\n"
        "# Diverged Workflow Body\n"
    )
    (standalone_dir / "extra-script.py").write_text("print('extra file')\n")

    st = run_env(["status"], fake_home)
    dup_scs = [sc for sc in st["environments"]["claude"]["global"]["structured_conflicts"] if sc["kind"] == "duplicate-name"]
    assert len(dup_scs) == 1
    dup_sc = dup_scs[0]
    assert dup_sc["fixable"] is False
    assert dup_sc["actionable"] is False
    assert len(dup_sc["actions"]) == 0
    assert len(dup_sc["advice"]) == 1

    diff_summary = dup_sc.get("diff_summary")
    assert diff_summary is not None
    assert "extra-script.py" in diff_summary
    assert "version" in diff_summary

    # Apply refuses to touch real divergence
    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 0
    assert standalone_dir.exists()
    assert (standalone_dir / "extra-script.py").is_file()


def test_duplicate_name_open_questions_q006_to_q008_never_autoresolve(tmp_path: pathlib.Path) -> None:
    """Questions Q006-Q008 (gcube-jenkins, gcube-security-audit, frontend-design) are NEVER auto-resolved."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "gcube-ai-toolkit" / "gcube-developer-tools" / "0.2.1" / "skills"

    test_cases = [
        ("gcube-jenkins", "Q006"),
        ("gcube-security-audit", "Q007"),
        ("frontend-design", "Q008"),
    ]

    for name, qid in test_cases:
        p_dir = p_skills / name
        p_dir.mkdir(parents=True, exist_ok=True)
        (p_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test\n---\n# {name}\n")

        s_dir = fake_home / ".claude" / "skills" / name
        s_dir.mkdir(parents=True, exist_ok=True)
        # Even if byte-identical or normalized-equal, open questions must NOT auto-resolve
        (s_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test\n---\n# {name}\n")

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "gcube-developer-tools@gcube-ai-toolkit": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    st = run_env(["status"], fake_home)
    dup_scs = [sc for sc in st["environments"]["claude"]["global"]["structured_conflicts"] if sc["kind"] == "duplicate-name"]
    assert len(dup_scs) == 3

    for dup_sc in dup_scs:
        name = dup_sc["names"][0]
        expected_qid = dict(test_cases)[name]
        assert dup_sc["fixable"] is False
        assert dup_sc["actionable"] is False
        assert len(dup_sc["actions"]) == 0
        assert any(expected_qid in adv for adv in dup_sc["advice"])

    # Apply makes zero changes
    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 0
    for name, _ in test_cases:
        assert (fake_home / ".claude" / "skills" / name).is_dir()


# ---------------------------------------------------------------------------
# Task 13.6: Kilo effective view; install respects plugins and policy (P2-b + P2-c)
# ---------------------------------------------------------------------------


def test_kilo_shadowing_order_across_roots(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_ws = tmp_path / "ws"
    fake_home.mkdir()
    fake_ws.mkdir()

    sname = "my-custom-skill"
    claude_dir = fake_home / ".claude" / "skills" / sname
    config_dir = fake_home / ".config" / "kilo" / "skills" / sname
    kilo_home_dir = fake_home / ".kilo" / "skills" / sname
    kilo_proj_dir = fake_ws / ".kilo" / "skills" / sname

    # Step 1: Only in ~/.claude/skills
    claude_dir.mkdir(parents=True)
    (claude_dir / "SKILL.md").write_text("# Claude copy\n")
    st1 = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    eff1 = st1["kilo_effective"]
    assert sname in eff1
    assert eff1[sname]["winning"] == str(claude_dir)
    assert eff1[sname]["shadowed"] == []

    # Step 2: Add ~/.config/kilo/skills -> shadows ~/.claude/skills
    config_dir.mkdir(parents=True)
    (config_dir / "SKILL.md").write_text("# Config copy\n")
    st2 = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    eff2 = st2["kilo_effective"]
    assert eff2[sname]["winning"] == str(config_dir)
    assert str(claude_dir) in eff2[sname]["shadowed"]

    # Step 3: Add ~/.kilo/skills -> shadows ~/.config/kilo/skills and ~/.claude/skills
    kilo_home_dir.mkdir(parents=True)
    (kilo_home_dir / "SKILL.md").write_text("# Kilo home copy\n")
    st3 = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    eff3 = st3["kilo_effective"]
    assert eff3[sname]["winning"] == str(kilo_home_dir)
    assert str(config_dir) in eff3[sname]["shadowed"]
    assert str(claude_dir) in eff3[sname]["shadowed"]

    # Step 4: Add project .kilo/skills -> shadows all global copies
    kilo_proj_dir.mkdir(parents=True)
    (kilo_proj_dir / "SKILL.md").write_text("# Kilo project copy\n")
    st4 = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    eff4 = st4["kilo_effective"]
    assert eff4[sname]["winning"] == str(kilo_proj_dir)
    assert str(kilo_home_dir) in eff4[sname]["shadowed"]
    assert str(config_dir) in eff4[sname]["shadowed"]
    assert str(claude_dir) in eff4[sname]["shadowed"]


def test_kilo_skill_in_claude_and_kilo_resolved_per_precedence(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    sname = "shared-skill"
    claude_skill = fake_home / ".claude" / "skills" / sname
    kilo_skill = fake_home / ".kilo" / "skills" / sname
    claude_skill.mkdir(parents=True)
    (claude_skill / "SKILL.md").write_text("# Claude version\n")
    kilo_skill.mkdir(parents=True)
    (kilo_skill / "SKILL.md").write_text("# Kilo version\n")

    st = run_env(["status"], fake_home)
    assert "kilo_effective" in st
    eff = st["kilo_effective"]
    assert sname in eff
    # Kilo precedence: ~/.kilo/skills beats ~/.claude/skills
    assert eff[sname]["winning"] == str(kilo_skill)
    assert eff[sname]["shadowed"] == [str(claude_skill)]

    # Kilo environment reflects cross-root duplicate finding
    k_conflicts = st["environments"]["kilo"]["global"]["conflicts"]
    assert any(sname in c and "standalone:~/.claude/skills" in c and "standalone:~/.kilo/skills" in c for c in k_conflicts)

    # With KILO_DISABLE_CLAUDE_CODE_SKILLS=1, ~/.claude is excluded from Kilo's view
    env_dis = os.environ.copy()
    env_dis["KILO_DISABLE_CLAUDE_CODE_SKILLS"] = "1"
    st_dis = run_env_raw(["status", "--json"], fake_home, env=env_dis)
    assert st_dis.returncode == 0
    data_dis = json.loads(st_dis.stdout)
    eff_dis = data_dis["kilo_effective"]
    assert eff_dis[sname]["winning"] == str(kilo_skill)
    assert eff_dis[sname]["shadowed"] == []
    k_conflicts_dis = data_dis["environments"]["kilo"]["global"]["conflicts"]
    assert not any(sname in c for c in k_conflicts_dis)


def test_install_skills_skips_plugin_provided_and_policy_removed_with_reasons(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Set up enabled Claude plugin providing task-pipeline
    plugins_cache = fake_home / ".claude" / "plugins" / "cache"
    p_skills = plugins_cache / "ai-orchestration" / "architect-side" / "0.3.0" / "skills"
    (p_skills / "task-pipeline").mkdir(parents=True)
    (p_skills / "task-pipeline" / "SKILL.md").write_text("# Plugin Task Pipeline\n")

    plugins_reg_file = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    plugins_reg_file.parent.mkdir(parents=True, exist_ok=True)
    plugins_reg_file.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "architect-side@ai-orchestration": [
                {
                    "scope": "user",
                    "installPath": str(p_skills.parent),
                }
            ]
        }
    }))

    # Dry-run install
    dry = run_env(["install-skills", "--dry-run", "--assistants", "all", "--scope", "global"], fake_home)
    assert dry["ok"] is True
    plan = dry["plan"]

    # In Claude: task-pipeline skipped (provided by enabled plugin)
    # and orchestration-workflow skipped (removed by conflict policy 'bound')
    claude_tp = next(
        item for item in plan
        if ".claude" in item["path"] and item["path"].endswith("/task-pipeline")
    )
    assert claude_tp["action"] == "skip"
    assert "provided by enabled plugin 'architect-side@ai-orchestration'" in claude_tp["reason"]

    claude_ow = next(
        item for item in plan
        if ".claude" in item["path"] and item["path"].endswith("/orchestration-workflow")
    )
    assert claude_ow["action"] == "skip"
    assert "removed by conflict policy ('bound')" in claude_ow["reason"]

    # In Codex: orchestration-workflow skipped (removed by conflict policy 'bound')
    codex_ow = next(
        item for item in plan
        if ".codex" in item["path"] and item["path"].endswith("/orchestration-workflow")
    )
    assert codex_ow["action"] == "skip"
    assert "removed by conflict policy ('bound')" in codex_ow["reason"]

    # Apply install without force
    apply_res = run_env(["install-skills", "--assistants", "all", "--scope", "global"], fake_home)
    assert apply_res["ok"] is True
    assert not (fake_home / ".claude" / "skills" / "task-pipeline").exists()
    assert not (fake_home / ".claude" / "skills" / "orchestration-workflow").exists()
    assert not (fake_home / ".codex" / "skills" / "orchestration-workflow").exists()

    # --force overrides both skips
    force_res = run_env(["install-skills", "--assistants", "all", "--scope", "global", "--force"], fake_home)
    assert force_res["ok"] is True
    assert (fake_home / ".claude" / "skills" / "task-pipeline").is_dir()
    assert (fake_home / ".claude" / "skills" / "orchestration-workflow").is_dir()
    assert (fake_home / ".codex" / "skills" / "orchestration-workflow").is_dir()


def test_resolve_then_install_leaves_no_new_finding(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Install both generic and bound for Claude with --force to induce conflict
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration", "--force"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    # Verify conflict exists
    st_before = run_env(["status"], fake_home)
    assert len(st_before["environments"]["claude"]["global"]["structured_conflicts"]) == 4

    # Resolve conflicts -> removes all 4 generic skills per bound policy
    rc = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc["ok"] is True
    assert rc["resolved_count"] == 4
    assert not (fake_home / ".claude" / "skills" / "orchestration-workflow").exists()

    # Re-run install-skills: skips 'orchestration-workflow' due to bound policy
    inst = run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)
    assert inst["ok"] is True
    plan = inst["plan"]
    ow_plan = next(item for item in plan if item["path"].endswith("/orchestration-workflow"))
    assert ow_plan["action"] == "skip"
    assert "removed by conflict policy ('bound')" in ow_plan["reason"]
    assert not (fake_home / ".claude" / "skills" / "orchestration-workflow").exists()

    # Verify status reports no findings for Claude
    st_after = run_env(["status"], fake_home)
    assert st_after["environments"]["claude"]["global"]["conflicts"] == []
    assert st_after["environments"]["claude"]["global"]["structured_conflicts"] == []


# ---------------------------------------------------------------------------
# Task 13.7: Doctor P3 Tests
# ---------------------------------------------------------------------------


def test_p3a_clean_stray_and_redundant_mcp_dry_run_and_apply(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # 1. Setup stray ~/.codex/config.json with MCP servers
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    stray_json = codex_dir / "config.json"
    stray_json.write_text(json.dumps({
        "mcpServers": {
            "server-a": {"command": "cmd-a"},
            "server-b": {"command": "cmd-b"},
        }
    }))

    # Setup ~/.codex/config.toml defining server-a but not server-b
    (codex_dir / "config.toml").write_text("""[mcp_servers.server-a]
command = "cmd-a"
args = []
""")

    # 2. Setup redundant MCP override in Kilo:
    # kilo.json and kilo.jsonc both define playwright with identical command
    kilo_dir = fake_home / ".config" / "kilo"
    kilo_dir.mkdir(parents=True)
    kilo_json = kilo_dir / "kilo.json"
    kilo_jsonc = kilo_dir / "kilo.jsonc"
    kilo_json.write_text(json.dumps({
        "mcp": {
            "playwright": {"command": "npx", "args": ["@modelcontextprotocol/server-playwright"]},
            "other": {"command": "other-cmd"},
        }
    }, indent=2))
    kilo_jsonc.write_text("""{
        "mcp": {
            "playwright": {"command": "npx", "args": ["@modelcontextprotocol/server-playwright"]}
        }
    }""")

    # Check status before clean: 1 stray file, 1 redundant MCP override
    st_before = run_env(["status"], fake_home)
    assert len(st_before["stray"]) == 1
    assert "playwright" in st_before["environments"]["kilo"]["global"]["mcp_servers"]
    assert len(st_before["environments"]["kilo"]["global"]["mcp_servers"]["playwright"]["overrides"]) == 1

    # Check finding_groups:
    # stray finding is fixable=True, actionable=True
    # redundant-mcp finding is fixable=True, actionable=True, severity="info"
    groups = st_before.get("finding_groups", [])
    stray_g = next(g for g in groups if g["kind"] == "stray")
    assert stray_g["fixable"] is True
    assert stray_g["actionable"] is True
    assert len(stray_g["actions"]) == 1
    assert stray_g["actions"][0]["action"] == "trash"
    assert "server-a (in config.toml: True)" in stray_g["advice"][0]
    assert "server-b (in config.toml: False)" in stray_g["advice"][0]

    mcp_g = next(g for g in groups if g["kind"] == "redundant-mcp")
    assert mcp_g["fixable"] is True
    assert mcp_g["severity"] == "info"
    assert mcp_g["actions"][0]["action"] == "edit"

    # 3. Dry-run clean-stray: plan lists 1 trash and 1 edit
    dry = run_env(["clean-stray", "--dry-run"], fake_home)
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert len(dry["plan"]) == 2
    actions = [item["action"] for item in dry["plan"]]
    assert "trash" in actions
    assert "edit" in actions
    assert dry["applied"] == 0
    plan_hash = dry["plan_hash"]

    # 4. Expect plan hash mismatch refused
    bad = run_env_raw(["clean-stray", "--expect-plan-hash", "wronghash123"], fake_home)
    assert bad.returncode != 0
    assert "Plan hash mismatch" in json.loads(bad.stdout)["error"]

    # 5. Apply clean-stray with matching plan hash
    res = run_env(["clean-stray", "--expect-plan-hash", plan_hash], fake_home)
    assert res["ok"] is True
    assert res["applied"] == 2

    # Check disk state: stray file moved to trash, kilo.json edited, other keys preserved
    assert not stray_json.exists()
    trash_items = list((fake_home / ".config" / "ai-orchestration" / "trash").rglob("config.json"))
    assert len(trash_items) == 1

    updated_kilo = json.loads(kilo_json.read_text(encoding="utf-8"))
    assert "playwright" not in updated_kilo.get("mcp", {})
    assert updated_kilo.get("mcp", {}).get("other") == {"command": "other-cmd"}

    # 6. Verify status now reports no stray and no override
    st_after = run_env(["status"], fake_home)
    assert st_after["stray"] == []
    assert st_after["environments"]["kilo"]["global"]["mcp_servers"]["playwright"]["overrides"] == []


def test_p3a_clean_stray_refuses_unparseable_config(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    bad_json = codex_dir / "config.json"
    bad_json.write_text("{ unparseable json content }")

    st = run_env(["status"], fake_home)
    stray_g = next(g for g in st["finding_groups"] if g["kind"] == "stray")
    assert stray_g["fixable"] is False
    assert stray_g["actionable"] is False
    assert "cannot be parsed" in stray_g["advice"][0]

    # clean-stray dry run plans advise action, does not trash
    dry = run_env(["clean-stray", "--dry-run"], fake_home)
    assert len(dry["plan"]) == 1
    assert dry["plan"][0]["action"] == "advise"

    # clean-stray apply leaves unparseable file intact
    run_env(["clean-stray"], fake_home)
    assert bad_json.exists()


def test_p3b_register_mcp_idempotency_and_replace_diff(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # 1. First registration into claude & codex
    reg1 = run_env(["register-mcp", "kilo-mcp", "--assistants", "claude", "codex", "--scope", "global"], fake_home)
    assert reg1["ok"] is True
    assert len(reg1["updated_configs"]) == 2

    # 2. Re-register identical entry: plan shows noop for both, applied is 0
    dry_noop = run_env(["register-mcp", "kilo-mcp", "--assistants", "claude", "codex", "--scope", "global", "--dry-run"], fake_home)
    assert dry_noop["ok"] is True
    assert len(dry_noop["plan"]) == 2
    assert all(item["action"] == "noop" for item in dry_noop["plan"])
    assert all("already registered" in item["reason"] for item in dry_noop["plan"])

    # Apply identical registration: updated_configs is empty (idempotent, no changes written)
    apply_noop = run_env(["register-mcp", "kilo-mcp", "--assistants", "claude", "codex", "--scope", "global"], fake_home)
    assert apply_noop["ok"] is True
    assert apply_noop["updated_configs"] == []

    # 3. Differing command: modify claude config to have old command, then re-register
    cfg_p = pathlib.Path(reg1["updated_configs"][0])
    cdata = json.loads(cfg_p.read_text(encoding="utf-8"))
    cdata["mcpServers"]["kilo-mcp"]["command"] = "old-python"
    cfg_p.write_text(json.dumps(cdata, indent=2) + "\n")

    dry_replace = run_env(["register-mcp", "kilo-mcp", "--assistants", "claude", "--scope", "global", "--dry-run"], fake_home)
    assert dry_replace["ok"] is True
    replace_items = [item for item in dry_replace["plan"] if item["action"] == "replace"]
    assert len(replace_items) == 1
    assert "old_command" in replace_items[0]
    assert "old-python" in replace_items[0]["old_command"]
    assert "new_command" in replace_items[0]
    assert "diff" in replace_items[0]
    assert "->" in replace_items[0]["diff"]


def test_p3b_register_mcp_assistants_all_skips_kilo_for_kilo_mcp(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Running with --assistants all on kilo-mcp omits kilo by default
    reg = run_env(["register-mcp", "kilo-mcp", "--assistants", "all", "--scope", "global"], fake_home)
    assert reg["ok"] is True
    # Only claude and codex configs were updated
    assert len(reg["updated_configs"]) == 2
    st = run_env(["status"], fake_home)
    assert "kilo-mcp" in st["environments"]["claude"]["global"]["registered_mcps"]
    assert "kilo-mcp" in st["environments"]["codex"]["global"]["registered_mcps"]
    assert "kilo-mcp" not in st["environments"]["kilo"]["global"]["registered_mcps"]


def test_p3c_agent_transform_drops_kilo_frontmatter_and_hashes_receipt(tmp_path: pathlib.Path) -> None:
    from orchestration_env import transform_agent_for_assistant, read_agent_receipts

    # Verify transform logic directly
    kilo_agent_text = """---
name: test-agent
description: Test agent description
mode: subagent
permission:
  edit: allow
---
# Test Agent Instructions
Here is the agent prompt.
"""
    claude_transformed = transform_agent_for_assistant(kilo_agent_text, "claude")
    assert "mode:" not in claude_transformed
    assert "permission:" not in claude_transformed
    assert "edit: allow" not in claude_transformed
    assert "name: test-agent" in claude_transformed
    assert "description: Test agent description" in claude_transformed
    assert "# Test Agent Instructions" in claude_transformed

    # For kilo, content is unchanged
    assert transform_agent_for_assistant(kilo_agent_text, "kilo") == kilo_agent_text

    # Verify install-skills for claude transforms agent and writes receipt with transformed hash
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    res = run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)
    assert res["ok"] is True

    claude_agents_dir = fake_home / ".claude" / "agents"
    agent_file = claude_agents_dir / "kilo-mcp-orchestrator-agent.md"
    assert agent_file.is_file()
    agent_text = agent_file.read_text(encoding="utf-8")
    assert "mode:" not in agent_text
    assert "permission:" not in agent_text

    receipts = read_agent_receipts(claude_agents_dir)
    assert "kilo-mcp-orchestrator-agent.md" in receipts
    rdata = receipts["kilo-mcp-orchestrator-agent.md"]
    assert rdata["source_hash"] == hashlib.sha256(agent_text.encode("utf-8")).hexdigest()

    # Status classifies as up-to-date
    st = run_env(["status"], fake_home)
    agent_info = st["environments"]["claude"]["global"]["agents"]["kilo-mcp-orchestrator-agent.md"]
    assert agent_info["state"] == "up-to-date"


def test_p3c_legacy_agent_without_receipt_classifies_up_to_date_instead_of_foreign(tmp_path: pathlib.Path) -> None:
    from orchestration_env import resolve_source_repo, transform_agent_for_assistant
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    rpath = resolve_source_repo("kilo-mcp", None)
    if not rpath:
        pytest.skip("kilo-mcp source repo not found")
    cat_agent = rpath / "plugins" / "architect-side" / "agents" / "kilo-mcp-orchestrator-agent.md"
    if not cat_agent.is_file():
        pytest.skip("kilo-mcp catalog agent not found")

    raw = cat_agent.read_text(encoding="utf-8")
    claude_copy = transform_agent_for_assistant(raw, "claude")

    claude_agents_dir = fake_home / ".claude" / "agents"
    claude_agents_dir.mkdir(parents=True)
    # Write adapted agent directly without receipt (legacy copy)
    (claude_agents_dir / "kilo-mcp-orchestrator-agent.md").write_text(claude_copy, encoding="utf-8")

    st = run_env(["status"], fake_home)
    agent_info = st["environments"]["claude"]["global"]["agents"]["kilo-mcp-orchestrator-agent.md"]
    # Should classify as up-to-date-legacy (or up-to-date), NOT foreign!
    assert agent_info["state"] in ("up-to-date-legacy", "up-to-date")
    assert agent_info["state"] != "foreign"


def test_p3d_generalized_trigger_conflicts_and_plugin_advice(tmp_path: pathlib.Path) -> None:
    from orchestration_env import resolve_source_repo
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    rpath_orch = resolve_source_repo("ai-orchestration", None)
    rpath_kilo = resolve_source_repo("kilo-mcp", None)
    if not rpath_orch or not rpath_kilo:
        pytest.skip("Source repos not found")

    src_generic = rpath_orch / "plugins" / "executor-side" / "skills" / "executor-contract"
    src_bound = rpath_kilo / "plugins" / "executor-side" / "skills" / "kilo-mcp-executor-contract"
    if not (src_generic / "SKILL.md").is_file() or not (src_bound / "SKILL.md").is_file():
        pytest.skip("Skills for pair testing not found")

    claude_skills = fake_home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    shutil.copytree(src_generic, claude_skills / "executor-contract")
    shutil.copytree(src_bound, claude_skills / "kilo-mcp-executor-contract")

    st = run_env(["status"], fake_home)
    scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    tcs = [s for s in scs if s["kind"] == "trigger-conflict"]
    assert len(tcs) == 1
    assert set(tcs[0]["names"]) == {"executor-contract", "kilo-mcp-executor-contract"}
    assert tcs[0]["kind"] == "trigger-conflict"

    # Now simulate a plugin-only generic skill that competes with bound
    # Advice should list all other skills provided by that plugin
    fake_home2 = tmp_path / "home2"
    fake_home2.mkdir()
    plugins_cache = fake_home2 / ".claude" / "plugins" / "cache"
    p_install = plugins_cache / "custom-pack" / "skills"
    p_skills_root = p_install / "skills"
    (p_skills_root / "executor-contract").mkdir(parents=True)
    (p_skills_root / "executor-contract" / "SKILL.md").write_text("# Generic\n")
    (p_skills_root / "other-helper-a").mkdir(parents=True)
    (p_skills_root / "other-helper-a" / "SKILL.md").write_text("# Helper A\n")
    (p_skills_root / "other-helper-b").mkdir(parents=True)
    (p_skills_root / "other-helper-b" / "SKILL.md").write_text("# Helper B\n")

    reg = fake_home2 / ".claude" / "plugins" / "installed_plugins.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "pack@custom": [
                {
                    "scope": "user",
                    "installPath": str(p_install),
                }
            ]
        }
    }))

    # Also install standalone bound skill in fake_home2
    c_skills2 = fake_home2 / ".claude" / "skills"
    c_skills2.mkdir(parents=True)
    shutil.copytree(src_bound, c_skills2 / "kilo-mcp-executor-contract")

    # Status in fake_home2
    st2 = run_env(["status"], fake_home2)
    scs2 = st2["environments"]["claude"]["global"]["structured_conflicts"]
    tcs2 = [s for s in scs2 if s["kind"] == "trigger-conflict"]
    assert len(tcs2) == 1
    # Check that resolve-conflicts dry-run advice lists the other skills in pack@custom
    rc_dry = run_env(["resolve-conflicts", "--dry-run"], fake_home2)
    assert len(rc_dry["advice"]) == 1
    advice = rc_dry["advice"][0]
    assert "pack@custom" in advice
    assert "other-helper-a" in advice
    assert "other-helper-b" in advice


# ---------------------------------------------------------------------------
# Task 16.6 Tests: Version-Free Launcher, Doctor Broker MCP Detection & Plan,
# and Skill Regeneration Idempotence
# ---------------------------------------------------------------------------


def test_16_6_launcher_preview_apply_update_in_place_and_refuse_foreign(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    launcher_path = fake_home / ".local" / "bin" / "ai-orch"

    # 1. Preview (default when --apply is omitted) does not write to disk
    preview = run_env(["install-launcher"], fake_home)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["applied"] is False
    assert preview["path"] == str(launcher_path)
    assert preview["current_state"] == "missing"
    assert preview["plan"][0]["action"] == "create"
    assert not launcher_path.exists()
    plan_hash = preview["plan_hash"]
    assert preview["expect_hash"] == plan_hash

    # 2. Apply with mismatched hash is refused
    bad_apply = run_env_raw(["install-launcher", "--apply", "--expect-hash", "deadbeef"], fake_home)
    assert bad_apply.returncode != 0
    bad_payload = json.loads(bad_apply.stdout)
    assert bad_payload["ok"] is False
    assert "Plan hash mismatch" in bad_payload["error"]
    assert not launcher_path.exists()

    # 3. Apply with matching --expect-hash creates executable launcher
    applied = run_env(["install-launcher", "--apply", "--expect-hash", plan_hash], fake_home)
    assert applied["ok"] is True
    assert applied["dry_run"] is False
    assert applied["applied"] is True
    assert applied["action"] == "create"
    assert launcher_path.is_file()
    assert os.access(launcher_path, os.X_OK)
    content = launcher_path.read_text(encoding="utf-8")
    assert "# ai-orchestration-launcher-v1" in content

    # 4. Subsequent preview on up-to-date launcher is noop
    noop_preview = run_env(["install-launcher"], fake_home)
    assert noop_preview["ok"] is True
    assert noop_preview["current_state"] == "up-to-date"
    assert noop_preview["plan"][0]["action"] == "noop"

    # 5. Existing launcher of ours with older content is updated in place
    launcher_path.write_text("#!/usr/bin/env python3\n# ai-orchestration-launcher-v1\n# older copy\n", encoding="utf-8")
    upd_preview = run_env(["install-launcher"], fake_home)
    assert upd_preview["ok"] is True
    assert upd_preview["current_state"] == "outdated"
    assert upd_preview["plan"][0]["action"] == "update"
    upd_apply = run_env(["install-launcher", "--apply", "--expect-hash", upd_preview["expect_hash"]], fake_home)
    assert upd_apply["ok"] is True
    assert upd_apply["applied"] is True
    assert upd_apply["action"] == "update"
    assert launcher_path.read_text(encoding="utf-8") == content
    assert (launcher_path.parent / "ai-orch.ai-orch.bak").is_file()

    # 6. Refusal to overwrite an unrelated (foreign) file
    foreign_text = "#!/bin/sh\necho 'unrelated user binary'\n"
    launcher_path.write_text(foreign_text, encoding="utf-8")
    foreign_preview = run_env_raw(["install-launcher", "--json"], fake_home)
    assert foreign_preview.returncode != 0
    fp_data = json.loads(foreign_preview.stdout)
    assert fp_data["ok"] is False
    assert fp_data["current_state"] == "foreign"
    assert fp_data["plan"][0]["action"] == "refuse"

    foreign_apply = run_env_raw(["install-launcher", "--apply", "--json"], fake_home)
    assert foreign_apply.returncode != 0
    fa_data = json.loads(foreign_apply.stdout)
    assert fa_data["ok"] is False
    assert launcher_path.read_text(encoding="utf-8") == foreign_text


def test_16_6_launcher_execs_newest_plugin_cache_or_configured_checkout(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()

    # Install launcher into fake_home
    prev = run_env(["install-launcher"], fake_home)
    run_env(["install-launcher", "--apply", "--expect-hash", prev["expect_hash"]], fake_home)
    launcher = fake_home / ".local" / "bin" / "ai-orch"

    # Create two cached plugin versions in fake_home: 0.3.0 and 0.5.0
    for ver in ("0.3.0", "0.5.0"):
        bdir = fake_home / ".claude" / "plugins" / "cache" / "ai-orchestration" / "architect-side" / ver / "bin"
        bdir.mkdir(parents=True)
        bfile = bdir / "ai-orch"
        bfile.write_text(f"import sys; print('CACHE_VER={ver}:' + ','.join(sys.argv[1:]))\n", encoding="utf-8")
        bfile.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(fake_home),
        "AI_ORCH_HOME": str(fake_home),
        "AI_ORCHESTRATION_CONFIG": str(cfg_dir),
    }
    res_cache = subprocess.run([str(launcher), "tasks", "list"], capture_output=True, text=True, env=env, check=True)
    assert res_cache.stdout.strip() == "CACHE_VER=0.5.0:tasks,list"

    # Configure a source checkout in AI_ORCHESTRATION_CONFIG/orchestration.toml -> takes precedence
    checkout_dir = tmp_path / "source-checkout"
    (checkout_dir / "bin").mkdir(parents=True)
    (checkout_dir / ".claude-plugin").mkdir(parents=True)
    (checkout_dir / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"version": "0.6.0"}), encoding="utf-8"
    )
    (checkout_dir / "bin" / "ai-orch").write_text(
        "import sys; print('SOURCE_CHECKOUT:' + ','.join(sys.argv[1:]))\n", encoding="utf-8"
    )
    (cfg_dir / "orchestration.toml").write_text(
        f'[launcher]\nsource_checkout = "{checkout_dir}"\n', encoding="utf-8"
    )
    res_src = subprocess.run([str(launcher), "mcp"], capture_output=True, text=True, env=env, check=True)
    assert res_src.stdout.strip() == "SOURCE_CHECKOUT:mcp"


def test_16_6_doctor_detects_missing_stale_and_correct_registrations_all_clients(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    expected_launcher = str(fake_home / ".local" / "bin" / "ai-orch")

    # 1. Missing registrations across all three clients -> warning finding per client + info finding for missing launcher
    st_missing = run_env(["status"], fake_home)
    bm_missing = st_missing["broker_mcp"]["clients"]
    for asst in ("claude", "kilo", "codex"):
        assert bm_missing[asst]["state"] == "missing"
        assert st_missing["environments"][asst]["global"]["broker_mcp"]["state"] == "missing"
        fg = next(g for g in st_missing["finding_groups"] if g["group_key"] == f"missing-broker-mcp:{asst}")
        assert fg["kind"] == "missing-broker-mcp"
        assert fg["group"] == "Broker MCP registration"
        assert fg["severity"] == "warning"
        assert fg["fixable"] is True
        assert fg["actionable"] is True
        assert asst in fg["message"]
        assert bm_missing[asst]["config_path"] in fg["message"]
        assert f"ai-orch env register-broker --assistants {asst}" in fg["fix_command"]
        assert f"ai-orch env register-broker --assistants {asst}" in fg["message"]
        assert len(fg["actions"]) == 1
        assert fg["actions"][0]["fix_command"] == f"ai-orch env register-broker --assistants {asst}"

    assert st_missing["summary"]["warning"] == 3
    l_fg_missing = next(g for g in st_missing["finding_groups"] if g["group_key"] == "missing-launcher:ai-orch")
    assert l_fg_missing["severity"] == "info"
    assert l_fg_missing["fix_command"] == "ai-orch install-launcher"
    assert "ai-orch install-launcher" in l_fg_missing["message"]
    assert st_missing["summary"]["info"] == 1

    # 2. Stale registrations (versioned plugin-cache paths & format pitfalls) on fixture files -> error finding per client
    versioned_bin = str(
        fake_home / ".claude" / "plugins" / "cache" / "ai-orchestration" / "architect-side" / "0.3.0" / "bin" / "ai-orch"
    )
    # Claude fixture: versioned path + null field
    (fake_home / ".claude.json").write_text(
        json.dumps({
            "mcpServers": {
                "ai-orchestration": {
                    "type": "stdio",
                    "command": versioned_bin,
                    "args": ["mcp"],
                    "env": None,
                }
            }
        }, indent=2),
        encoding="utf-8",
    )
    # Kilo fixture: versioned path
    kilo_dir = fake_home / ".config" / "kilo"
    kilo_dir.mkdir(parents=True)
    (kilo_dir / "kilo.jsonc").write_text(
        "// Kilo JSONC config\n"
        + json.dumps({
            "mcp": {
                "ai-orchestration": {
                    "type": "local",
                    "command": [versioned_bin, "mcp"],
                    "environment": {},
                }
            }
        }, indent=2),
        encoding="utf-8",
    )
    # Codex fixture: versioned path + missing default_tools_approval_mode
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "config.toml").write_text(
        f'[mcp_servers.ai-orchestration]\ncommand = "{versioned_bin}"\nargs = ["mcp"]\n',
        encoding="utf-8",
    )

    st_stale = run_env(["status"], fake_home)
    bm_stale = st_stale["broker_mcp"]["clients"]
    for asst in ("claude", "kilo", "codex"):
        assert bm_stale[asst]["state"] == "stale"
        assert any("versioned path" in r for r in bm_stale[asst]["reasons"])
        fg = next(g for g in st_stale["finding_groups"] if g["group_key"] == f"stale-broker-mcp:{asst}")
        assert fg["kind"] == "stale-broker-mcp"
        assert fg["group"] == "Broker MCP registration"
        assert fg["severity"] == "error"
        assert fg["fixable"] is True
        assert asst in fg["message"]
        assert bm_stale[asst]["config_path"] in fg["message"]
        assert f"ai-orch env register-broker --assistants {asst}" in fg["fix_command"]
        assert f"ai-orch env register-broker --assistants {asst}" in fg["message"]
        assert fg["actions"][0]["action"] == "replace"
        assert fg["actions"][0]["fix_command"] == f"ai-orch env register-broker --assistants {asst}"

    assert st_stale["summary"]["error"] == 3
    assert any("null fields" in r for r in bm_stale["claude"]["reasons"])
    assert any("default_tools_approval_mode" in r for r in bm_stale["codex"]["reasons"])

    # 3. Preview and apply repair plan + install launcher -> zero findings across all clients and launcher
    l_prev = run_env(["install-launcher"], fake_home)
    run_env(["install-launcher", "--apply", "--expect-hash", l_prev["expect_hash"]], fake_home)

    plan_preview = run_env(["register-broker", "--assistants", "all"], fake_home)
    assert plan_preview["ok"] is True
    assert plan_preview["dry_run"] is True
    assert plan_preview["applied"] == 0

    plan_apply = run_env(
        ["register-broker", "--assistants", "all", "--apply", "--expect-hash", plan_preview["expect_hash"]],
        fake_home,
    )
    assert plan_apply["ok"] is True
    assert plan_apply["dry_run"] is False
    assert plan_apply["applied"] == 3

    st_ok = run_env(["status"], fake_home)
    bm_ok = st_ok["broker_mcp"]["clients"]
    for asst in ("claude", "kilo", "codex"):
        assert bm_ok[asst]["state"] == "registered"
        assert bm_ok[asst]["reasons"] == []
        assert bm_ok[asst]["expected_command"] == expected_launcher
    assert st_ok["launcher"]["state"] == "up-to-date"
    assert st_ok["finding_groups"] == []
    assert st_ok["summary"]["total_groups"] == 0
    assert st_ok["summary"]["error"] == 0
    assert st_ok["summary"]["warning"] == 0
    assert st_ok["summary"]["info"] == 0


def test_16_6_launcher_findings_and_acknowledge_mechanism(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    launcher_path = fake_home / ".local" / "bin" / "ai-orch"

    # Register all 3 clients first so we isolate launcher findings
    reg_prev = run_env(["register-broker", "--assistants", "all"], fake_home)
    run_env(["register-broker", "--assistants", "all", "--apply", "--expect-hash", reg_prev["expect_hash"]], fake_home)

    # 1. Missing launcher -> severity info, fix is `ai-orch install-launcher`
    st1 = run_env(["status"], fake_home)
    assert len(st1["finding_groups"]) == 1
    lf1 = st1["finding_groups"][0]
    assert lf1["group_key"] == "missing-launcher:ai-orch"
    assert lf1["kind"] == "missing-launcher"
    assert lf1["severity"] == "info"
    assert lf1["fix_command"] == "ai-orch install-launcher"
    assert str(launcher_path) in lf1["message"]

    # 2. Outdated launcher -> severity warning, fix is `ai-orch install-launcher`
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_text("#!/usr/bin/env python3\n# ai-orchestration-launcher-v1\n# outdated\n", encoding="utf-8")
    launcher_path.chmod(0o755)
    st2 = run_env(["status"], fake_home)
    assert len(st2["finding_groups"]) == 1
    lf2 = st2["finding_groups"][0]
    assert lf2["group_key"] == "outdated-launcher:ai-orch"
    assert lf2["kind"] == "outdated-launcher"
    assert lf2["severity"] == "warning"
    assert lf2["fix_command"] == "ai-orch install-launcher"
    assert st2["summary"]["warning"] == 1

    # 3. Acknowledge outdated launcher via 13.2 ack -> severity drops to info and acknowledged == True
    ack_res = run_env(["ack", "outdated-launcher:ai-orch", "--note", "defer launcher update"], fake_home)
    assert ack_res["ok"] is True
    st_acked = run_env(["status"], fake_home)
    lf_acked = st_acked["finding_groups"][0]
    assert lf_acked["acknowledged"] is True
    assert lf_acked["severity"] == "info"
    assert st_acked["summary"]["acknowledged"] == 1
    assert st_acked["summary"]["warning"] == 0

    # Unack restores warning
    unack_res = run_env(["unack", "outdated-launcher:ai-orch"], fake_home)
    assert unack_res["ok"] is True
    st_unacked = run_env(["status"], fake_home)
    assert st_unacked["finding_groups"][0]["severity"] == "warning"

    # 4. Install up-to-date launcher -> zero findings
    l_prev = run_env(["install-launcher"], fake_home)
    run_env(["install-launcher", "--apply", "--expect-hash", l_prev["expect_hash"]], fake_home)
    st3 = run_env(["status"], fake_home)
    assert st3["finding_groups"] == []
    assert st3["summary"]["total_groups"] == 0


def test_16_6_registration_plan_content_per_client_format(tmp_path: pathlib.Path) -> None:
    from orchestration_env import _has_null_values, parse_jsonc
    import tomllib

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    expected_launcher = str(fake_home / ".local" / "bin" / "ai-orch")

    preview = run_env(["register-broker", "--assistants", "all"], fake_home)
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    by_asst = {item["assistant"]: item for item in preview["plan"]}

    # Claude format: stdio, launcher mcp, strictly zero null values anywhere
    claude_item = by_asst["claude"]
    assert claude_item["server_config"] == {
        "type": "stdio",
        "command": expected_launcher,
        "args": ["mcp"],
    }
    assert not _has_null_values(claude_item["server_config"])
    claude_doc = json.loads(claude_item["content"])
    assert not _has_null_values(claude_doc)
    assert "null" not in claude_item["content"]
    assert claude_doc["mcpServers"]["ai-orchestration"] == claude_item["server_config"]

    # Codex format: [mcp_servers.ai-orchestration] with default_tools_approval_mode = "approve"
    codex_item = by_asst["codex"]
    assert codex_item["server_config"] == {
        "command": expected_launcher,
        "args": ["mcp"],
        "default_tools_approval_mode": "approve",
    }
    codex_doc = tomllib.loads(codex_item["content"])
    assert codex_doc["mcp_servers"]["ai-orchestration"] == {
        "command": expected_launcher,
        "args": ["mcp"],
        "default_tools_approval_mode": "approve",
    }

    # Kilo format: "mcp": {"ai-orchestration": {"type": "local", "command": [launcher, "mcp"], "environment": {}, "enabled": true}}
    kilo_item = by_asst["kilo"]
    assert kilo_item["server_config"] == {
        "type": "local",
        "command": [expected_launcher, "mcp"],
        "environment": {},
        "enabled": True,
    }
    kilo_doc = parse_jsonc(kilo_item["content"])
    assert kilo_doc["mcp"]["ai-orchestration"] == kilo_item["server_config"]


def test_16_6_skills_regeneration_idempotence_and_broker_tools_section() -> None:
    repo_root = SCRIPT.parent.parent
    regen_script = repo_root / "scripts" / "regenerate_generic_skills.py"
    tp_skill = repo_root / "plugins" / "architect-side" / "skills" / "task-pipeline" / "SKILL.md"
    ow_skill = repo_root / "plugins" / "architect-side" / "skills" / "orchestration-workflow" / "SKILL.md"

    # First run and second run must leave zero diff and pass --check
    r1 = subprocess.run([sys.executable, str(regen_script)], capture_output=True, text=True, check=False)
    assert r1.returncode == 0, r1.stderr
    after_first = ow_skill.read_text(encoding="utf-8")

    r2 = subprocess.run([sys.executable, str(regen_script)], capture_output=True, text=True, check=False)
    assert r2.returncode == 0, r2.stderr
    after_second = ow_skill.read_text(encoding="utf-8")
    assert after_first == after_second

    r_check = subprocess.run([sys.executable, str(regen_script), "--check"], capture_output=True, text=True, check=False)
    assert r_check.returncode == 0, r_check.stderr

    implemented_tools = [
        "whoami",
        "workspaces.list",
        "projects.list",
        "tasks.list",
        "tasks.show",
        "tasks.next",
        "tasks.graph",
        "tasks.new",
        "tasks.transition",
        "tasks.set",
        "questions.list",
        "questions.ask",
        "questions.answer",
        "inbox.add_note",
        "orchestrator.status",
    ]
    for skill_file in (tp_skill, ow_skill):
        text = skill_file.read_text(encoding="utf-8")
        assert "## Reaching the task engine" in text
        assert "## Tooling feedback" in text
        assert "project/ID" in text
        assert "expect_hash" in text
        assert "idempotency_key" in text
        for tname in implemented_tools:
            assert f"`{tname}`" in text, f"Missing tool {tname} in {skill_file}"
        # Unimplemented 16.7 / 16.8 tools must not be listed
        assert "`mail.send`" not in text
        assert "`orchestrator.ask`" not in text


def test_doctor_detects_vendored_or_stale_tasks_engine(tmp_path: pathlib.Path) -> None:
    from orchestration_env import inspect_environment, REPO_ROOT

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()

    # 1. Clean workspace -> zero stale-vendored-engine findings
    st_clean = inspect_environment(workspace=ws, home=fake_home)
    assert not any(g["kind"] == "stale-vendored-engine" for g in st_clean["finding_groups"])

    # 2. Add vendored tasks/scripts/tasks_engine.py -> always reported as warning
    vendored = ws / "tasks" / "scripts" / "tasks_engine.py"
    vendored.parent.mkdir(parents=True)
    vendored.write_text("# vendored engine\n", encoding="utf-8")

    st_vendored = inspect_environment(workspace=ws, home=fake_home)
    fg_v = next(g for g in st_vendored["finding_groups"] if g["group_key"] == "stale-vendored-engine:tasks/scripts/tasks_engine.py")
    assert fg_v["kind"] == "stale-vendored-engine"
    assert fg_v["severity"] == "warning"
    assert fg_v["path"] == str(vendored)

    # 3. Add up-to-date .kilo/skills/task-pipeline/scripts/tasks_engine.py (matching canonical)
    canonical = REPO_ROOT / "plugins" / "architect-side" / "skills" / "task-pipeline" / "scripts" / "tasks_engine.py"
    kilo_engine = ws / ".kilo" / "skills" / "task-pipeline" / "scripts" / "tasks_engine.py"
    kilo_engine.parent.mkdir(parents=True)
    shutil.copy2(canonical, kilo_engine)

    st_up_to_date = inspect_environment(workspace=ws, home=fake_home)
    # The up-to-date .kilo engine must NOT be reported as stale!
    assert not any(g["group_key"] == "stale-vendored-engine:.kilo/skills/task-pipeline/scripts/tasks_engine.py" for g in st_up_to_date["finding_groups"])
    # tasks/scripts/tasks_engine.py is still reported
    assert any(g["group_key"] == "stale-vendored-engine:tasks/scripts/tasks_engine.py" for g in st_up_to_date["finding_groups"])

    # 4. Modify .kilo/skills/task-pipeline/scripts/tasks_engine.py -> now outdated/differs -> reported as warning
    kilo_engine.write_text("# outdated engine copy\n", encoding="utf-8")
    st_outdated = inspect_environment(workspace=ws, home=fake_home)
    fg_k = next(g for g in st_outdated["finding_groups"] if g["group_key"] == "stale-vendored-engine:.kilo/skills/task-pipeline/scripts/tasks_engine.py")
    assert fg_k["kind"] == "stale-vendored-engine"
    assert fg_k["severity"] == "warning"
    assert fg_k["path"] == str(kilo_engine)

    # Remove vendored tasks/scripts/tasks_engine.py -> only the .kilo one is reported
    vendored.unlink()
    st_kilo_only = inspect_environment(workspace=ws, home=fake_home)
    engine_findings = [g for g in st_kilo_only["finding_groups"] if g["kind"] == "stale-vendored-engine"]
    assert len(engine_findings) == 1
    assert engine_findings[0]["group_key"] == "stale-vendored-engine:.kilo/skills/task-pipeline/scripts/tasks_engine.py"


# ---------------------------------------------------------------------------
# Task T056: Compare installed and source skill content; warn on stale source clone
# ---------------------------------------------------------------------------

def test_t056_outdated_installed_copy_replaces_without_overwrite(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Create mock repo in ~/.ai-orchestration/repos/claude-mcp
    mock_repo = fake_home / ".ai-orchestration" / "repos" / "claude-mcp"
    src_skill_dir = mock_repo / "plugins" / "architect-side" / "skills" / "t056-test-skill"
    src_skill_dir.mkdir(parents=True)
    (src_skill_dir / "SKILL.md").write_text("# T056 Test Skill v1\n")

    # Install for kilo
    inst1 = run_env(["install-skills", "--repo", "claude-mcp", "--assistants", "kilo"], fake_home)
    assert inst1["ok"] is True
    assert inst1["installed_count"] == 1

    installed_dir = fake_home / ".kilo" / "skills" / "t056-test-skill"
    assert (installed_dir / "SKILL.md").read_text() == "# T056 Test Skill v1\n"
    marker_file = installed_dir / ".ai-orch-source.json"
    assert marker_file.is_file()
    mdata1 = json.loads(marker_file.read_text(encoding="utf-8"))
    old_hash = mdata1["source_hash"]

    # Now update source in mock_repo to v2
    (src_skill_dir / "SKILL.md").write_text("# T056 Test Skill v2 (Updated Upstream)\n")

    # 1. Status reports skill as outdated (not up-to-date)
    st = run_env(["status"], fake_home)
    k_skills = st["environments"]["kilo"]["global"]["skills"]
    assert k_skills["t056-test-skill"]["state"] == "outdated"

    # 2. Dry run install-skills without --overwrite plans REPLACE
    dry = run_env(["install-skills", "--repo", "claude-mcp", "--assistants", "kilo", "--dry-run"], fake_home)
    assert dry["ok"] is True
    plan = dry["plan"]
    plan_item = next(item for item in plan if item["path"] == str(installed_dir))
    assert plan_item["action"] == "replace"
    assert plan_item["current_state"] == "outdated"
    assert "source newer" in plan_item["reason"]

    # 3. Apply install without --overwrite successfully updates skill and updates marker
    inst2 = run_env(["install-skills", "--repo", "claude-mcp", "--assistants", "kilo"], fake_home)
    assert inst2["ok"] is True
    assert inst2["installed_count"] == 1
    assert (installed_dir / "SKILL.md").read_text() == "# T056 Test Skill v2 (Updated Upstream)\n"

    # Marker is updated with new source hash
    mdata2 = json.loads(marker_file.read_text(encoding="utf-8"))
    assert mdata2["source_hash"] != old_hash
    from orchestration_env import hash_directory
    assert mdata2["source_hash"] == hash_directory(src_skill_dir)

    # Status now reports up-to-date
    st_after = run_env(["status"], fake_home)
    assert st_after["environments"]["kilo"]["global"]["skills"]["t056-test-skill"]["state"] == "up-to-date"


def test_t056_locally_edited_installed_copy_requires_overwrite(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    mock_repo = fake_home / ".ai-orchestration" / "repos" / "claude-mcp"
    src_skill_dir = mock_repo / "plugins" / "architect-side" / "skills" / "t056-local-edit-skill"
    src_skill_dir.mkdir(parents=True)
    (src_skill_dir / "SKILL.md").write_text("# Base Skill Content\n")

    inst1 = run_env(["install-skills", "--repo", "claude-mcp", "--assistants", "kilo"], fake_home)
    assert inst1["ok"] is True

    installed_dir = fake_home / ".kilo" / "skills" / "t056-local-edit-skill"
    (installed_dir / "SKILL.md").write_text("# Locally Edited Content By User\n")

    # Update source as well
    (src_skill_dir / "SKILL.md").write_text("# Upstream Change\n")

    # Status detects modified-or-outdated
    st = run_env(["status"], fake_home)
    assert st["environments"]["kilo"]["global"]["skills"]["t056-local-edit-skill"]["state"] == "modified-or-outdated"

    # install-skills without --overwrite skips it
    dry_skip = run_env(["install-skills", "--repo", "claude-mcp", "--assistants", "kilo", "--dry-run"], fake_home)
    assert dry_skip["ok"] is True
    plan_item = next(item for item in dry_skip["plan"] if item["path"] == str(installed_dir))
    assert plan_item["action"] == "skip"
    assert plan_item["current_state"] == "modified-or-outdated"
    assert "installed edited locally" in plan_item["reason"]

    # install-skills with --overwrite replaces it
    dry_ow = run_env(
        ["install-skills", "--repo", "claude-mcp", "--assistants", "kilo", "--dry-run", "--overwrite", "t056-local-edit-skill"],
        fake_home,
    )
    assert dry_ow["ok"] is True
    plan_ow_item = next(item for item in dry_ow["plan"] if item["path"] == str(installed_dir))
    assert plan_ow_item["action"] == "replace"
    assert "--overwrite" in plan_ow_item["reason"]


def test_t056_source_clone_behind_bare_remote_warning(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    # Initial checkout to create commit
    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(bare), str(work)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "test@test.com"], check=True)
    skill_dir = work / "plugins" / "architect-side" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Demo Skill v1\n")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "Commit 1"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "HEAD"], check=True, capture_output=True)

    # Clone into cache dir
    cache_clone = fake_home / ".ai-orchestration" / "repos" / "ai-orchestration"
    cache_clone.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(bare), str(cache_clone)], check=True, capture_output=True)

    # Push new commit to remote from work
    (skill_dir / "SKILL.md").write_text("# Demo Skill v2\n")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "Commit 2"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "HEAD"], check=True, capture_output=True)

    # Now cache_clone is behind remote
    st = run_env(["status"], fake_home)
    repo_info = st["source_repos"]["ai-orchestration"]
    assert repo_info["available"] is True
    assert repo_info["stale"] is True
    assert repo_info["behind_remote"] is True
    assert "behind its remote" in repo_info["warning"]
    assert "fetch-repos" in repo_info["warning"]

    # Finding group created with warning severity
    stale_fg = next(g for g in st["finding_groups"] if g["kind"] == "stale-source-repo")
    assert stale_fg["severity"] == "warning"
    assert stale_fg["names"] == ["ai-orchestration"]
    assert any("fetch-repos" in adv for adv in stale_fg["advice"])

    # install-skills also warns
    inst = run_env(["install-skills", "--repo", "ai-orchestration", "--assistants", "kilo", "--dry-run"], fake_home)
    assert inst["ok"] is True
    assert inst.get("source_repo_stale") is True
    assert "fetch-repos" in inst.get("warning", "")

    # CLI human-readable prints warning to stderr
    res_cli = subprocess.run(
        [sys.executable, str(SCRIPT), "--home", str(fake_home), "install-skills", "--repo", "ai-orchestration", "--assistants", "kilo", "--dry-run"],
        capture_output=True, text=True,
    )
    assert "[warning]" in res_cli.stderr
    assert "fetch-repos" in res_cli.stderr


def test_t056_offline_unreachable_remote_no_failure(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    repo = fake_home / ".ai-orchestration" / "repos" / "ai-orchestration"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], check=True)
    skill_dir = repo / "plugins" / "architect-side" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Demo Skill\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "Initial"], check=True, capture_output=True)

    # Add unreachable remote
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "http://192.0.2.1/unreachable.git"], check=True)

    # Status must not fail or raise exception
    st = run_env(["status"], fake_home)
    assert st["source_repos"]["ai-orchestration"]["available"] is True
    assert st["source_repos"]["ai-orchestration"]["stale"] is False

    # install-skills must not fail
    inst = run_env(["install-skills", "--repo", "ai-orchestration", "--assistants", "kilo", "--dry-run"], fake_home)
    assert inst["ok"] is True
    assert inst.get("source_repo_stale") is not True


def test_t056_configured_local_checkout_ahead_warning(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    # Create cache clone
    cache_clone = fake_home / ".ai-orchestration" / "repos" / "ai-orchestration"
    cache_clone.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(bare), str(cache_clone)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(cache_clone), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(cache_clone), "config", "user.email", "test@test.com"], check=True)
    skill_dir = cache_clone / "plugins" / "architect-side" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Base Skill\n")
    subprocess.run(["git", "-C", str(cache_clone), "add", "."], check=True)
    subprocess.run(["git", "-C", str(cache_clone), "commit", "-m", "Base commit"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(cache_clone), "push", "origin", "HEAD"], check=True, capture_output=True)

    # Create local checkout
    local_dir = tmp_path / "local-ai-orchestration"
    subprocess.run(["git", "clone", str(bare), str(local_dir)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(local_dir), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(local_dir), "config", "user.email", "test@test.com"], check=True)

    # Local checkout adds a commit ahead of clone
    (local_dir / "README.md").write_text("# Local commit ahead\n")
    subprocess.run(["git", "-C", str(local_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(local_dir), "commit", "-m", "Local ahead commit"], check=True, capture_output=True)

    # Configure local checkout in fake_home/.config/ai-orchestration/orchestration.toml
    cfg_dir = fake_home / ".config" / "ai-orchestration"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "orchestration.toml").write_text(f'[repos]\nai-orchestration = "{local_dir}"\n')

    st = run_env(["status"], fake_home)
    repo_info = st["source_repos"]["ai-orchestration"]
    assert repo_info["stale"] is True
    assert repo_info["local_ahead"] is True
    assert "ahead" in repo_info["warning"]
    assert "fetch-repos" in repo_info["warning"]


def test_n063_identical_per_assistant_skill_copies_not_flagged_as_duplicates(tmp_path: pathlib.Path) -> None:
    """N063: Identical/equivalent standalone skill copies in ~/.claude/skills/<s/> and ~/.kilo/skills/<s/>
    (same scope, one per assistant root family) are recognized as intentional per-assistant copies and not flagged.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    sname = "d4science-ansible-operations"
    claude_skill = fake_home / ".claude" / "skills" / sname
    kilo_skill = fake_home / ".kilo" / "skills" / sname
    claude_skill.mkdir(parents=True)
    kilo_skill.mkdir(parents=True)
    skill_md = "---\nname: d4science-ansible-operations\ndescription: Ansible ops\n---\n\n# Body\n"
    (claude_skill / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (kilo_skill / "SKILL.md").write_text(skill_md, encoding="utf-8")

    st = run_env(["status"], fake_home)
    k_conflicts = st["environments"]["kilo"]["global"]["conflicts"]
    assert not any(sname in c for c in k_conflicts)
    assert not any(g["group_key"] == f"duplicate-name:{sname}" for g in st["finding_groups"])


def test_parse_frontmatter_and_compare_without_pyyaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """T088: Stdlib fallback parser in parse_frontmatter_and_body normalizes nested metadata and folded block scalars when PyYAML is absent."""
    import orchestration_env as oe

    monkeypatch.setattr(oe, "yaml", None)

    nested_md = (
        "---\n"
        "name: gcube-component-release\n"
        "description: \"Release gcube components\"\n"
        "metadata:\n"
        "  author: Alfredo Oliviero\n"
        "  version: 1.0.0\n"
        "---\n\n"
        "# Body\n"
    )
    flat_md = (
        "---\n"
        "name: gcube-component-release\n"
        "description: \"Release gcube components\"\n"
        "metadata: \"\"\n"
        "author: Alfredo Oliviero\n"
        "version: 1.0.0\n"
        "---\n\n"
        "# Body\n"
    )
    eq1, changed1, body_diff1 = oe.compare_skill_md(nested_md, flat_md)
    assert eq1 is True
    assert changed1 == []
    assert body_diff1 is False

    folded_md = (
        "---\n"
        "name: demo-folded-skill\n"
        "description: >-\n"
        "  Create distinctive: frontend interfaces\n"
        "  with high design quality.\n"
        "license: Apache-2.0\n"
        "---\n\n"
        "# Body line\n"
    )
    quoted_md = (
        "---\r\n"
        "name: demo-folded-skill\r\n"
        "description: \"Create distinctive: frontend interfaces with high design quality.\"\r\n"
        "license: Apache-2.0   \r\n"
        "---\r\n\r\n"
        "# Body line  \r\n"
    )
    eq2, changed2, body_diff2 = oe.compare_skill_md(folded_md, quoted_md)
    assert eq2 is True
    assert changed2 == []
    assert body_diff2 is False


def test_parse_frontmatter_without_pyyaml_nested_lists_and_literal_vs_folded_negative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """T088 Bounce 1 (B1): Stdlib YAML fallback preserves nested lists/structures beyond one level,
    distinguishes literal ('|', '|-') from folded ('>', '>-') block scalars, and fails closed on
    unsupported YAML constructs so diverging skills never normalize equal or auto-trash.
    """
    import orchestration_env as oe

    monkeypatch.setattr(oe, "yaml", None)

    # 1. Negative test: nested list under metadata: (e.g. tags:) must not be dropped
    skill_tags_a = (
        "---\n"
        "name: gcube-component-release\n"
        "description: Release gcube components\n"
        "metadata:\n"
        "  author: Alfredo Oliviero\n"
        "  tags:\n"
        "    - release\n"
        "    - maven\n"
        "---\n\n"
        "# Body\n"
    )
    skill_tags_b = (
        "---\n"
        "name: gcube-component-release\n"
        "description: Release gcube components\n"
        "metadata:\n"
        "  author: Alfredo Oliviero\n"
        "  tags:\n"
        "    - release\n"
        "    - docker\n"
        "---\n\n"
        "# Body\n"
    )
    skill_no_tags = (
        "---\n"
        "name: gcube-component-release\n"
        "description: Release gcube components\n"
        "metadata:\n"
        "  author: Alfredo Oliviero\n"
        "---\n\n"
        "# Body\n"
    )
    fm_a, _ = oe.parse_frontmatter_and_body(skill_tags_a)
    assert fm_a is not None
    assert fm_a["metadata"]["tags"] == ["release", "maven"]

    eq_tags, changed_tags, _ = oe.compare_skill_md(skill_tags_a, skill_tags_b)
    assert eq_tags is False
    assert "tags" in changed_tags

    eq_missing_tags, changed_missing_tags, _ = oe.compare_skill_md(skill_tags_a, skill_no_tags)
    assert eq_missing_tags is False
    assert "tags" in changed_missing_tags

    # Deeply nested mapping + list beyond two levels must also be preserved
    deep_a = (
        "---\n"
        "name: deep-skill\n"
        "metadata:\n"
        "  routing:\n"
        "    profiles:\n"
        "      - fast\n"
        "      - safe\n"
        "---\n\n"
        "# Body\n"
    )
    deep_b = (
        "---\n"
        "name: deep-skill\n"
        "metadata:\n"
        "  routing:\n"
        "    profiles:\n"
        "      - fast\n"
        "---\n\n"
        "# Body\n"
    )
    eq_deep, changed_deep, _ = oe.compare_skill_md(deep_a, deep_b)
    assert eq_deep is False
    assert "routing" in changed_deep

    # 2. Negative test: literal ('|' / '|-') vs folded ('>' / '>-') scalars must not normalize equal
    literal_skill = (
        "---\n"
        "name: scalar-style-skill\n"
        "description: |-\n"
        "  First line of description\n"
        "  Second line must stay on a new line\n"
        "notes: |\n"
        "  step 1\n"
        "  step 2\n"
        "---\n\n"
        "# Body\n"
    )
    folded_skill = (
        "---\n"
        "name: scalar-style-skill\n"
        "description: >-\n"
        "  First line of description\n"
        "  Second line must stay on a new line\n"
        "notes: >\n"
        "  step 1\n"
        "  step 2\n"
        "---\n\n"
        "# Body\n"
    )
    fm_lit, _ = oe.parse_frontmatter_and_body(literal_skill)
    fm_fold, _ = oe.parse_frontmatter_and_body(folded_skill)
    assert fm_lit is not None and fm_fold is not None
    assert "\n" in fm_lit["description"]
    assert "\n" not in fm_fold["description"]
    assert fm_lit["notes"] == "step 1\nstep 2\n"
    assert fm_fold["notes"] == "step 1 step 2\n"

    eq_style, changed_style, _ = oe.compare_skill_md(literal_skill, folded_skill)
    assert eq_style is False
    assert "description" in changed_style
    assert "notes" in changed_style

    # 3. Fail-closed test: unsupported YAML constructs (flow collections, anchors) return None and never compare equal
    unsupported_a = (
        "---\n"
        "name: flow-skill\n"
        "metadata: {tags: [a, b]}\n"
        "---\n\n"
        "# Body\n"
    )
    unsupported_b = (
        "---\n"
        "name: flow-skill\n"
        "metadata: {tags: [c, d]}\n"
        "---\n\n"
        "# Body\n"
    )
    fm_unsup, _ = oe.parse_frontmatter_and_body(unsupported_a)
    assert fm_unsup is None
    eq_unsup, changed_unsup, _ = oe.compare_skill_md(unsupported_a, unsupported_b)
    assert eq_unsup is False
    assert changed_unsup == ["<unparsed-frontmatter>"]

    # 4. End-to-end directory comparison: different nested tags must not be marked equivalent
    dir_a = tmp_path / "plugin_skill"
    dir_b = tmp_path / "standalone_skill"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "SKILL.md").write_text(skill_tags_a, encoding="utf-8")
    (dir_b / "SKILL.md").write_text(skill_tags_b, encoding="utf-8")
    cmp_dirs = oe.compare_skill_dirs(dir_a, dir_b)
    assert cmp_dirs["equivalent"] is False
    assert "SKILL.md" in cmp_dirs["diff_files"]
    assert "tags" in cmp_dirs["changed_fm_keys"]


# ---------------------------------------------------------------------------
# Task 19.2: Project Doctor (`ai-orch doctor`) & Convention Drift Detection
# ---------------------------------------------------------------------------

AI_ORCH_BIN = SCRIPT.parent.parent / "bin" / "ai-orch"
FIXTURES_DIR = SCRIPT.parent / "fixtures"


def create_2026_10_17_fixture(project_dir: pathlib.Path) -> pathlib.Path:
    """Copy the checked-in '2026-10-17 style' drifted project fixture from scripts/fixtures/project_2026_10_17."""
    proj = pathlib.Path(project_dir).resolve()
    src = FIXTURES_DIR / "project_2026_10_17"
    shutil.copytree(src, proj, dirs_exist_ok=True)
    return proj


def create_updated_project_fixture(
    project_dir: pathlib.Path,
    home: pathlib.Path | None = None,
    global_config: pathlib.Path | None = None,
) -> pathlib.Path:
    """Copy the checked-in updated project fixture from scripts/fixtures/project_updated and initialize environment state."""
    import orchestration_env as oe

    h = (home or oe.get_home_dir()).resolve()
    proj = pathlib.Path(project_dir).resolve()
    src = FIXTURES_DIR / "project_updated"
    shutil.copytree(src, proj, dirs_exist_ok=True)
    tasks_dir = proj / "tasks"
    (tasks_dir / "_inbox" / "to-analyze").mkdir(parents=True, exist_ok=True)
    (tasks_dir / "_inbox" / "analyzed").mkdir(parents=True, exist_ok=True)

    oc = oe._load_orchestration_config()
    te = oe._load_tasks_engine()
    reg = oe._load_orchestration_registry()

    gpath = (
        pathlib.Path(global_config).resolve()
        if global_config is not None
        else (oe.get_config_dir(h) / "orchestration.toml")
    )
    if oc is not None and not gpath.is_file():
        gpath.parent.mkdir(parents=True, exist_ok=True)
        oc.write_file_atomic(gpath, oc.dump_toml(oc.DEFAULT_GLOBAL_CONFIG))

    if reg is not None:
        cdir = oe.get_config_dir(h)
        plan = reg.plan_workspace_register(proj, title=proj.name, config_dir=cdir)
        reg.apply_workspace_register(plan, expect_hash=plan["plan_hash"], config_dir=cdir)

    if oc is not None:
        ppath = oc.find_project_config_path(proj, gpath, for_write=True)
        existing_pdata = oc.load_toml_file(ppath) if ppath.is_file() else {}
        pdata = oc.deep_merge(
            {
                "project": {
                    "name": proj.name,
                    "primary_orchestrator": "claude",
                },
                "routing": {
                    "default_executor": "kilo",
                },
                "verification": {
                    "default_mode": "cross-agent",
                },
            },
            existing_pdata,
        )
        oc.write_file_atomic(ppath, oc.dump_toml(pdata))

        cfg, _ = oc.resolve_config(gpath, proj)
        block = oc.render_agents_md_block(cfg, proj, gpath)
        template_agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
        rendered_agents = oc.inject_or_replace_agents_block(template_agents, block)
        (proj / "AGENTS.md").write_text(rendered_agents, encoding="utf-8")

    if te is not None:
        te.upgrade_tasks_tree(tasks_dir, dry_run=False)

    return proj


def test_19_2_project_doctor_2026_10_17_fixture_reports_all_expected_findings_with_severity(
    tmp_path: pathlib.Path,
) -> None:
    """Fixture with a '2026-10-17 style' project (reconstructed from N078) reports all expected findings with severity and fix commands."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proj_dir = tmp_path / "ricerca_auto_2026_10_17"
    create_2026_10_17_fixture(proj_dir)

    res = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "doctor", "--project", str(proj_dir), "--home", str(fake_home), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(res.stdout)

    assert report["ok"] is False
    assert report["drifted"] is True
    assert report["convention_version"] is None
    assert report["tool_convention_version"] == oe.CONVENTION_VERSION

    findings = report["findings"]
    kinds = {f["kind"] for f in findings}
    expected_kinds = {
        "missing-project-config",
        "unregistered-workspace",
        "index-missing-markers",
        "stale-agents-md",
        "legacy-task-headers",
        "convention-version-drift",
    }
    assert expected_kinds.issubset(kinds)

    for f in findings:
        assert f["severity"] in ("error", "warning")
        assert f["fix_command"] and isinstance(f["fix_command"], str)
        assert f["fix"] == f["fix_command"]
        assert f["message"] and isinstance(f["message"], str)

    # Check specific AGENTS.md duplicated hand-written block detection
    agents_finding = next(f for f in findings if f["group_key"] == "project-drift:stale-agents-md")
    assert agents_finding["duplicated_blocks"] is True
    assert agents_finding["stale_rendered"] is True
    assert any("Required Skills" in h for h in agents_finding["duplicated_sections"])
    assert any("Core Operating Rules" in h for h in agents_finding["duplicated_sections"])

    # Check legacy task headers details
    hdr_finding = next(f for f in findings if f["kind"] == "legacy-task-headers")
    assert hdr_finding["severity"] == "error"
    assert hdr_finding["error_count"] > 0
    assert any("status" in issue or "header field" in issue for issue in hdr_finding["issues"])
    assert any("verification pending:" in issue for issue in hdr_finding["issues"])
    assert any("missing 'approval' header field" in issue for issue in hdr_finding["issues"])


def test_19_2_project_doctor_updated_project_reports_zero_findings(
    tmp_path: pathlib.Path,
) -> None:
    """Updated project reports zero findings and records convention_version in tasks/convention_version."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proj_dir = tmp_path / "ricerca_auto_updated"
    create_updated_project_fixture(proj_dir, home=fake_home)

    # Verify versioned tasks/convention_version file exists on disk
    conv_file = proj_dir / "tasks" / "convention_version"
    assert conv_file.is_file()
    assert conv_file.read_text(encoding="utf-8").strip() == oe.CONVENTION_VERSION

    res = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "doctor", "--project", str(proj_dir), "--home", str(fake_home), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(res.stdout)

    assert report["ok"] is True
    assert report["drifted"] is False
    assert report["convention_version"] == oe.CONVENTION_VERSION
    assert report["tool_convention_version"] == oe.CONVENTION_VERSION
    assert report["findings"] == []
    assert report["summary"]["total"] == 0
    assert report["summary"]["error"] == 0
    assert report["summary"]["warning"] == 0


def test_19_2_project_doctor_json_stability_and_ack_unack(
    tmp_path: pathlib.Path,
) -> None:
    """`ai-orch doctor --json` is deterministic across runs and supports ack/unack on project drift findings."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proj_dir = tmp_path / "proj_json_stable"
    create_2026_10_17_fixture(proj_dir)

    r1 = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "doctor", "--project", str(proj_dir), "--home", str(fake_home), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    r2 = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "doctor", "--project", str(proj_dir), "--home", str(fake_home), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert r1.stdout == r2.stdout
    j1 = json.loads(r1.stdout)
    expected_keys = {
        "ok",
        "drifted",
        "project",
        "project_path",
        "workspace",
        "tasks_dir",
        "convention_version",
        "tool_convention_version",
        "convention_version_info",
        "findings",
        "finding_groups",
        "groups",
        "summary",
        "severity_counts",
        "checks",
    }
    assert expected_keys.issubset(set(j1.keys()))

    # Test ack and unack of a project drift finding via `ai-orch doctor ack` / `unack`
    ack_res = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "doctor",
            "ack",
            "project-drift:missing-project-config",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--note",
            "defer config init",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    ack_payload = json.loads(ack_res.stdout)
    assert ack_payload["ok"] is True
    assert ack_payload["acknowledged"] is True

    r_after_ack = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "doctor", "--project", str(proj_dir), "--home", str(fake_home), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    j_ack = json.loads(r_after_ack.stdout)
    cfg_f = next(f for f in j_ack["findings"] if f["group_key"] == "project-drift:missing-project-config")
    assert cfg_f["acknowledged"] is True
    assert cfg_f["severity"] == "info"
    assert j_ack["summary"]["acknowledged"] == 1

    unack_res = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "doctor",
            "unack",
            "project-drift:missing-project-config",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(unack_res.stdout)["unacknowledged"] is True


def test_19_2_global_skill_drift_detected_with_two_fake_installed_versions(
    tmp_path: pathlib.Path,
) -> None:
    """Global skill drift is detected when two fake installed versions are present across global skill roots."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proj_dir = tmp_path / "proj_clean"
    create_updated_project_fixture(proj_dir, home=fake_home)

    # Install two fake skill versions in global scope (e.g. v0.9.0 in Claude and v1.0.0 in Kilo)
    claude_skill_dir = fake_home / ".claude" / "skills" / "task-pipeline"
    claude_skill_dir.mkdir(parents=True)
    (claude_skill_dir / "SKILL.md").write_text(
        "---\nname: task-pipeline\ndescription: Fake v0.9.0\nversion: 0.9.0\n---\n# Fake 0.9.0\n",
        encoding="utf-8",
    )
    (claude_skill_dir / ".ai-orch-source.json").write_text(
        json.dumps({
            "repo": "ai-orchestration",
            "plugin": "architect-side",
            "name": "task-pipeline",
            "version": "0.9.0",
            "source_hash": "fake_hash_090",
            "mode": "copy",
        }),
        encoding="utf-8",
    )

    kilo_skill_dir = fake_home / ".kilo" / "skills" / "task-pipeline"
    kilo_skill_dir.mkdir(parents=True)
    (kilo_skill_dir / "SKILL.md").write_text(
        "---\nname: task-pipeline\ndescription: Fake v1.0.0\nversion: 1.0.0\n---\n# Fake 1.0.0\n",
        encoding="utf-8",
    )
    (kilo_skill_dir / ".ai-orch-source.json").write_text(
        json.dumps({
            "repo": "ai-orchestration",
            "plugin": "architect-side",
            "name": "task-pipeline",
            "version": "1.0.0",
            "source_hash": "fake_hash_100",
            "mode": "copy",
        }),
        encoding="utf-8",
    )

    res = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "doctor", "--project", str(proj_dir), "--home", str(fake_home), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(res.stdout)

    assert report["ok"] is False
    assert report["drifted"] is True
    assert len(report["findings"]) == 1
    sk_finding = report["findings"][0]
    assert sk_finding["kind"] == "global-skill-drift"
    assert sk_finding["severity"] == "warning"
    assert "task-pipeline" in sk_finding["names"]
    assert set(sk_finding["versions_found"]) == {"0.9.0", "1.0.0"}
    assert "install-skills" in sk_finding["fix_command"]


def test_19_2_one_line_drift_warning_on_ai_orch_commands_and_disable_mechanisms(
    tmp_path: pathlib.Path,
) -> None:
    """Running any ai-orch command in a project with drift emits a single-line warning on stderr (disablable)."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    drifted_proj = tmp_path / "drifted_proj"
    create_2026_10_17_fixture(drifted_proj)

    env_base = os.environ.copy()
    env_base["AI_ORCH_HOME"] = str(fake_home)
    env_base.pop("AI_ORCH_NO_DRIFT_WARNING", None)
    env_base.pop("AI_ORCH_DRIFT_WARNING", None)

    # 1. Running `ai-orch tasks list --json` in the drifted project emits 1-line warning on stderr,
    #    while stdout remains valid JSON.
    res_warn = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "tasks", "list", "--tasks-dir", str(drifted_proj / "tasks"), "--json"],
        cwd=str(drifted_proj),
        env=env_base,
        capture_output=True,
        text=True,
        check=True,
    )
    parsed_stdout = json.loads(res_warn.stdout)
    assert isinstance(parsed_stdout, dict)
    stderr_lines = [ln for ln in res_warn.stderr.splitlines() if ln.strip()]
    assert len(stderr_lines) == 1
    assert "[ai-orch] warning: project 'drifted_proj' has convention drift" in stderr_lines[0]
    assert "ai-orch doctor" in stderr_lines[0]

    # 2. Disable via AI_ORCH_NO_DRIFT_WARNING=1
    env_disabled = dict(env_base)
    env_disabled["AI_ORCH_NO_DRIFT_WARNING"] = "1"
    res_no_warn_env = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "tasks", "list", "--tasks-dir", str(drifted_proj / "tasks"), "--json"],
        cwd=str(drifted_proj),
        env=env_disabled,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[ai-orch] warning:" not in res_no_warn_env.stderr

    # 3. Disable via CLI flag --no-drift-warning
    res_no_warn_flag = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "--no-drift-warning",
            "tasks",
            "list",
            "--tasks-dir",
            str(drifted_proj / "tasks"),
            "--json",
        ],
        cwd=str(drifted_proj),
        env=env_base,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[ai-orch] warning:" not in res_no_warn_flag.stderr

    # 4. Disable via [doctor] drift_warning = false in project config
    (drifted_proj / ".ai-orchestration.local.toml").write_text(
        "[doctor]\ndrift_warning = false\n",
        encoding="utf-8",
    )
    res_no_warn_cfg = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "tasks", "list", "--tasks-dir", str(drifted_proj / "tasks"), "--json"],
        cwd=str(drifted_proj),
        env=env_base,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[ai-orch] warning:" not in res_no_warn_cfg.stderr

    # 5. Updated project emits zero warning even with warnings enabled
    clean_proj = tmp_path / "clean_proj"
    create_updated_project_fixture(clean_proj, home=fake_home)
    res_clean = subprocess.run(
        [sys.executable, str(AI_ORCH_BIN), "tasks", "list", "--tasks-dir", str(clean_proj / "tasks"), "--json"],
        cwd=str(clean_proj),
        env=env_base,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[ai-orch] warning:" not in res_clean.stderr


# ===========================================================================
# Task 19.3: `ai-orch upgrade` di progetto
# ===========================================================================


def test_19_3_project_upgrade_on_2026_10_17_fixture_preview_apply_doctor_validate_and_idempotence(
    tmp_path: pathlib.Path,
) -> None:
    """Task 19.3 Verification:
    On the 19.2 fixture: preview -> apply -> `ai-orch doctor` with zero findings and `tasks validate`
    with zero errors; second apply = no modifications.
    """
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True)
    proj_dir = tmp_path / "ricerca_auto"
    create_2026_10_17_fixture(proj_dir)

    env = os.environ.copy()
    env["AI_ORCH_HOME"] = str(fake_home)

    # Snapshot all files in proj_dir before preview
    before_preview_snapshot = {
        str(p.relative_to(proj_dir)): p.read_bytes()
        for p in sorted(proj_dir.rglob("*"))
        if p.is_file()
    }

    # 1. Preview by default via CLI (`ai-orch upgrade --project ... --json`)
    res_prev = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "upgrade",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    prev_data = json.loads(res_prev.stdout)
    assert prev_data["ok"] is True
    assert prev_data["applied"] is False
    assert prev_data["dry_run"] is True
    assert prev_data["changed"] is True
    plan_hash = prev_data["plan_hash"]
    assert len(plan_hash) == 64
    plan_steps = {op["step"] for op in prev_data["plan"]}
    assert "project-config" in plan_steps
    assert "workspace-register" in plan_steps
    assert "agents-md" in plan_steps
    assert "task-headers" in plan_steps
    assert "tasks-agents-md" in plan_steps
    assert "convention-version" in plan_steps
    assert "index-adopt-sync" in plan_steps

    # Verify preview did not touch any file on disk
    after_preview_snapshot = {
        str(p.relative_to(proj_dir)): p.read_bytes()
        for p in sorted(proj_dir.rglob("*"))
        if p.is_file()
    }
    assert after_preview_snapshot == before_preview_snapshot

    # 2. Apply without --expect-hash is refused
    res_no_hash = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "upgrade",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--apply",
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_no_hash.returncode != 0
    no_hash_data = json.loads(res_no_hash.stdout)
    assert no_hash_data["ok"] is False
    assert no_hash_data["applied"] is False

    # 3. Apply with wrong hash is refused
    res_wrong_hash = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "upgrade",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--apply",
            "--expect-hash",
            "0123456789abcdef" * 4,
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_wrong_hash.returncode != 0
    wrong_hash_data = json.loads(res_wrong_hash.stdout)
    assert wrong_hash_data["ok"] is False
    assert "mismatch" in wrong_hash_data["error"].lower()

    # 4. Apply with matching --expect-hash succeeds
    res_apply = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "upgrade",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--apply",
            "--expect-hash",
            plan_hash,
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    apply_data = json.loads(res_apply.stdout)
    assert apply_data["ok"] is True
    assert apply_data["applied"] is True
    assert apply_data["changed"] is True
    assert (proj_dir / "tasks" / "convention_version").read_text(encoding="utf-8").strip() == oe.CONVENTION_VERSION

    # 5. `ai-orch doctor` after apply -> 0 findings, drifted is False, --check exits 0
    res_doc = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "doctor",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--check",
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    doc_data = json.loads(res_doc.stdout)
    assert doc_data["ok"] is True
    assert doc_data["drifted"] is False
    assert doc_data["findings"] == []
    assert doc_data["summary"]["total"] == 0
    assert doc_data["summary"]["error"] == 0
    assert doc_data["summary"]["warning"] == 0

    # 6. `ai-orch tasks validate` after apply -> 0 errors, 0 warnings
    res_val = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "tasks",
            "validate",
            "--tasks-dir",
            str(proj_dir / "tasks"),
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    val_data = json.loads(res_val.stdout)
    assert val_data["ok"] is True
    assert val_data["errors"] == []
    assert val_data["warnings"] == []

    # 7. Second preview and second apply -> no modifications ("secondo apply = nessuna modifica")
    after_apply1_snapshot = {
        str(p.relative_to(proj_dir)): p.read_bytes()
        for p in sorted(proj_dir.rglob("*"))
        if p.is_file()
    }

    res_prev2 = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "upgrade",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    prev2_data = json.loads(res_prev2.stdout)
    assert prev2_data["ok"] is True
    assert prev2_data["changed"] is False
    assert prev2_data["plan"] == []
    assert prev2_data["upgraded_files"] == []

    # Second apply with new empty plan_hash
    res_apply2 = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "upgrade",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--apply",
            "--expect-hash",
            prev2_data["plan_hash"],
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    apply2_data = json.loads(res_apply2.stdout)
    assert apply2_data["ok"] is True
    assert apply2_data["applied"] is True
    assert apply2_data["changed"] is False
    assert apply2_data["upgraded_files"] == []

    # Second apply repeating original plan_hash is also a clean no-op
    res_apply2_repeat = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "upgrade",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--apply",
            "--expect-hash",
            plan_hash,
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    apply2_repeat_data = json.loads(res_apply2_repeat.stdout)
    assert apply2_repeat_data["ok"] is True
    assert apply2_repeat_data["applied"] is True
    assert apply2_repeat_data["changed"] is False
    assert apply2_repeat_data["upgraded_files"] == []

    after_apply2_snapshot = {
        str(p.relative_to(proj_dir)): p.read_bytes()
        for p in sorted(proj_dir.rglob("*"))
        if p.is_file()
    }
    assert after_apply2_snapshot == after_apply1_snapshot


def test_19_3_agents_md_blocks_outside_markers_preserved_byte_for_byte(
    tmp_path: pathlib.Path,
) -> None:
    """Task 19.3 Verification:
    Duplicated hand-written orchestration sections outside markers are removed, while custom project
    blocks in AGENTS.md outside markers remain byte-for-byte identical.
    """
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True)
    proj_dir = tmp_path / "ricerca_auto"
    create_2026_10_17_fixture(proj_dir)

    expected_intro_bytes = (
        "# ricerca_auto — Project Architecture & Notes\n\n"
        " Project-specific domain rules and scraper notes that must remain intact.\n\n"
    ).encode("utf-8")
    expected_footer_bytes = (
        "\n## Project Database Notes\n\n"
        "PostgreSQL port 5432; keep this footer byte-for-byte.\n"
    ).encode("utf-8")

    prev = oe.upgrade_project(proj_dir, home=fake_home)
    app = oe.upgrade_project(proj_dir, home=fake_home, apply=True, expect_hash=prev["plan_hash"])
    assert app["ok"] is True
    assert app["applied"] is True
    assert len(app["removed_duplicated_sections"]) == 5

    raw_bytes = (proj_dir / "AGENTS.md").read_bytes()
    begin_marker = b"<!-- BEGIN ai-orchestration -->\n"
    end_marker = b"<!-- END ai-orchestration -->\n"
    assert begin_marker in raw_bytes
    assert end_marker in raw_bytes

    b_idx = raw_bytes.index(begin_marker)
    e_idx = raw_bytes.index(end_marker) + len(end_marker)

    actual_intro_bytes = raw_bytes[:b_idx]
    actual_footer_bytes = raw_bytes[e_idx:]

    assert actual_intro_bytes == expected_intro_bytes
    assert actual_footer_bytes == expected_footer_bytes
    assert b"Old hand-written table from 2026-10-17" not in raw_bytes
    assert b"Hand-written Rule 1 before markers were introduced." not in raw_bytes


def test_19_3_project_upgrade_refuses_when_active_executor_worktree_exists(
    tmp_path: pathlib.Path,
) -> None:
    """Task 19.3 Verification:
    With an active executor worktree of the project, `ai-orch upgrade` refuses with a clear reason.
    """
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True)
    proj_dir = tmp_path / "ricerca_auto"
    create_2026_10_17_fixture(proj_dir)

    # Case 1: Real git linked worktree
    subprocess.run(["git", "-C", str(proj_dir), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(proj_dir), "config", "user.email", "test@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(proj_dir), "config", "user.name", "Test User"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(proj_dir), "add", "AGENTS.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(proj_dir), "commit", "-m", "initial"], check=True, capture_output=True)

    wt_dir = tmp_path / "wt-exec-T001"
    subprocess.run(
        ["git", "-C", str(proj_dir), "worktree", "add", str(wt_dir), "-b", "exec/T001"],
        check=True,
        capture_output=True,
    )

    # Both preview and apply refuse via CLI and API
    res_refuse = oe.upgrade_project(proj_dir, home=fake_home)
    assert res_refuse["ok"] is False
    assert res_refuse["applied"] is False
    assert res_refuse["error_code"] == "active-executor-worktrees"
    assert any(pathlib.Path(w["path"]) == wt_dir.resolve() for w in res_refuse["active_worktrees"])
    assert "active executor worktree" in res_refuse["message"].lower()

    res_cli_refuse = subprocess.run(
        [
            sys.executable,
            str(AI_ORCH_BIN),
            "upgrade",
            "--project",
            str(proj_dir),
            "--home",
            str(fake_home),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_cli_refuse.returncode != 0
    cli_refuse_data = json.loads(res_cli_refuse.stdout)
    assert cli_refuse_data["ok"] is False
    assert cli_refuse_data["error_code"] == "active-executor-worktrees"
    assert str(wt_dir.resolve()) in cli_refuse_data["error"]

    # Remove the linked git worktree
    subprocess.run(
        ["git", "-C", str(proj_dir), "worktree", "remove", "--force", str(wt_dir)],
        check=True,
        capture_output=True,
    )

    # Case 2: Sibling .worktrees/<proj>/run-active directory
    sibling_wt = tmp_path / ".worktrees" / proj_dir.name / "run-active"
    sibling_wt.mkdir(parents=True)
    res_refuse_sibling = oe.upgrade_project(proj_dir, home=fake_home)
    assert res_refuse_sibling["ok"] is False
    assert res_refuse_sibling["error_code"] == "active-executor-worktrees"
    assert any(pathlib.Path(w["path"]) == sibling_wt.resolve() for w in res_refuse_sibling["active_worktrees"])
    shutil.rmtree(tmp_path / ".worktrees")

    # Once active worktrees are gone, upgrade succeeds
    prev = oe.upgrade_project(proj_dir, home=fake_home)
    assert prev["ok"] is True
    app = oe.upgrade_project(proj_dir, home=fake_home, apply=True, expect_hash=prev["plan_hash"])
    assert app["ok"] is True
    assert app["applied"] is True
    doc = oe.inspect_project_doctor(proj_dir, home=fake_home)
    assert doc["drifted"] is False
    assert doc["findings"] == []


def test_19_3_project_upgrade_migrates_legacy_project_config(
    tmp_path: pathlib.Path,
) -> None:
    """Task 19.3: Legacy project config at `tasks/orchestration.toml` is merged into canonical config
    and archived so `ai-orch doctor` reports zero findings."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True)
    proj_dir = tmp_path / "ricerca_auto"
    create_2026_10_17_fixture(proj_dir)

    legacy_cfg = proj_dir / "tasks" / "orchestration.toml"
    legacy_cfg.write_text(
        '[project]\nname = "ricerca_auto"\nprimary_orchestrator = "claude"\nextension_fields = ["portal-target"]\n',
        encoding="utf-8",
    )

    prev = oe.upgrade_project(proj_dir, home=fake_home)
    assert prev["ok"] is True
    assert any(op["step"] == "legacy-project-config" for op in prev["plan"])

    app = oe.upgrade_project(proj_dir, home=fake_home, apply=True, expect_hash=prev["plan_hash"])
    assert app["ok"] is True
    assert not legacy_cfg.exists()

    canon_cfg_path = fake_home / ".config" / "ai-orchestration" / "projects" / "ricerca_auto" / "orchestration.toml"
    assert canon_cfg_path.is_file()
    assert "portal-target" in canon_cfg_path.read_text(encoding="utf-8")

    doc = oe.inspect_project_doctor(proj_dir, home=fake_home)
    assert doc["drifted"] is False
    assert doc["findings"] == []


# ===========================================================================
# Task 19.2 Bounce 1 Regression Tests (B1..B6)
# ===========================================================================


def test_19_2_b1_ordinary_user_sections_not_treated_as_duplicated_orchestration_or_deleted_on_upgrade(
    tmp_path: pathlib.Path,
) -> None:
    """B1: Ordinary user-authored `## Required Skills`, `## Core Operating Rules`, and
    `## Orchestration Lifecycle` sections — even when they use orchestration vocabulary like
    `task-pipeline`, `task-spec-authoring`, `focus_files`, and 'one task = one commit' — are
    never flagged by `ai-orch doctor` and never deleted by `ai-orch upgrade`, whereas real
    historical renderings (2026-10-15 927244a and 2026-10-17 0eef7a8) are positively detected and removed."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proj_dir = tmp_path / "user_sections_proj"
    create_updated_project_fixture(proj_dir, home=fake_home)

    user_header = (
        "# Custom Application Guidelines\n\n"
        "## Required Skills\n\n"
        "- Familiarity with Rust, Tokio, and SQLite WAL internals.\n"
        "- Use `task-pipeline` and `task-spec-authoring` when writing team notes, plus `orchestration-workflow`.\n\n"
        "## Core Operating Rules\n\n"
        "### Rule 1: Keep the Main Session Free for Reviews\n\n"
        "All crate modules must compile with `#![forbid(unsafe_code)]`.\n"
        "List `focus_files` in PR descriptions and follow \"one task = one commit\" with a disjoint write scope.\n\n"
        "### Rule 2: Define Execution Tasks Before Delegating\n\n"
        "Run tests in an isolated git worktree before opening a PR.\n\n"
        "## Orchestration Lifecycle\n\n"
        "Worker pods move from `open` → `in progress` → `delivered` → `verified` → `done`.\n"
        "Attach a `Final Report` and run `git worktree remove` after the Post-Merge Integration Gate.\n\n"
    )
    user_footer = (
        "\n## Database Migrations\n\n"
        "Run `sqlx migrate run` before integration tests.\n"
    )

    existing_agents = (proj_dir / "AGENTS.md").read_text(encoding="utf-8")
    begin_idx = existing_agents.index("<!-- BEGIN ai-orchestration -->")
    end_marker = "<!-- END ai-orchestration -->\n"
    end_idx = existing_agents.index(end_marker) + len(end_marker)
    managed_block = existing_agents[begin_idx:end_idx]

    full_agents = user_header + managed_block + user_footer
    (proj_dir / "AGENTS.md").write_text(full_agents, encoding="utf-8")

    # 1. Doctor must report zero findings (not flagged as duplicated-agents-md)
    doc = oe.inspect_project_doctor(proj_dir, home=fake_home)
    assert doc["ok"] is True
    assert doc["drifted"] is False
    assert doc["findings"] == []
    assert doc["checks"]["agents_md"]["duplicated_blocks"] is False
    assert doc["checks"]["agents_md"]["duplicated_sections"] == []

    # 2. Even if managed block is stale and upgrade runs, user sections remain byte-for-byte intact
    stale_managed = (
        "<!-- BEGIN ai-orchestration -->\n"
        "# Agent Orchestration & Development Guidelines\n"
        "Stale managed content.\n"
        "<!-- END ai-orchestration -->\n"
    )
    (proj_dir / "AGENTS.md").write_text(user_header + stale_managed + user_footer, encoding="utf-8")

    prev = oe.upgrade_project(proj_dir, home=fake_home)
    assert prev["removed_duplicated_sections"] == []
    app = oe.upgrade_project(proj_dir, home=fake_home, apply=True, expect_hash=prev["plan_hash"])
    assert app["ok"] is True

    after_bytes = (proj_dir / "AGENTS.md").read_bytes()
    b_pos = after_bytes.index(b"<!-- BEGIN ai-orchestration -->\n")
    e_pos = after_bytes.index(b"<!-- END ai-orchestration -->\n") + len(b"<!-- END ai-orchestration -->\n")
    assert after_bytes[:b_pos] == user_header.encode("utf-8")
    assert after_bytes[e_pos:] == user_footer.encode("utf-8")

    # 3. Positive test with two real historical renderings (2026-10-15 927244a & 2026-10-17 0eef7a8)
    for hist_fname in ("2026-10-15_927244a_default.md", "2026-10-17_0eef7a8_default.md"):
        hist_text = (FIXTURES_DIR / "historical_agents_md" / hist_fname).read_text(encoding="utf-8")
        unmarked_hist = (
            hist_text.replace("<!-- BEGIN ai-orchestration -->\n", "")
            .replace("<!-- END ai-orchestration -->\n", "")
        )
        (proj_dir / "AGENTS.md").write_text(user_header + unmarked_hist + managed_block + user_footer, encoding="utf-8")

        doc_hist = oe.inspect_project_doctor(proj_dir, home=fake_home)
        assert doc_hist["drifted"] is True
        assert doc_hist["checks"]["agents_md"]["duplicated_blocks"] is True
        assert "## 1. Required Skills" in doc_hist["checks"]["agents_md"]["duplicated_sections"]
        assert "## 2. Core Operating Rules" in doc_hist["checks"]["agents_md"]["duplicated_sections"]
        assert "## 3. Orchestration Lifecycle & Cross-Agent Verification Gate" in doc_hist["checks"]["agents_md"]["duplicated_sections"]
        assert "## Required Skills" not in doc_hist["checks"]["agents_md"]["duplicated_sections"]
        assert "## Core Operating Rules" not in doc_hist["checks"]["agents_md"]["duplicated_sections"]

        prev_hist = oe.upgrade_project(proj_dir, home=fake_home)
        assert "## 1. Required Skills" in prev_hist["removed_duplicated_sections"]
        app_hist = oe.upgrade_project(proj_dir, home=fake_home, apply=True, expect_hash=prev_hist["plan_hash"])
        assert app_hist["ok"] is True

        upgraded_bytes = (proj_dir / "AGENTS.md").read_bytes()
        b_idx2 = upgraded_bytes.index(b"<!-- BEGIN ai-orchestration -->\n")
        e_idx2 = upgraded_bytes.index(b"<!-- END ai-orchestration -->\n") + len(b"<!-- END ai-orchestration -->\n")
        assert upgraded_bytes[:b_idx2] == user_header.encode("utf-8")
        assert upgraded_bytes[e_idx2:] == user_footer.encode("utf-8")


def test_19_2_b2_unrelated_third_party_versioned_global_skills_ignored(
    tmp_path: pathlib.Path,
) -> None:
    """B2: Unrelated third-party global skills with a `version` field in frontmatter or VERSION file
    are not treated as managed and do not produce false `global-skill-drift` findings."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proj_dir = tmp_path / "proj_clean"
    create_updated_project_fixture(proj_dir, home=fake_home)

    # Install unrelated versioned skills across Claude and Kilo global roots
    third_party_claude = fake_home / ".claude" / "skills" / "acme-pdf-helper"
    third_party_claude.mkdir(parents=True)
    (third_party_claude / "SKILL.md").write_text(
        "---\nname: acme-pdf-helper\ndescription: Third-party PDF skill\nversion: 3.4.1\n---\n# Acme PDF\n",
        encoding="utf-8",
    )
    (third_party_claude / "VERSION").write_text("3.4.1\n", encoding="utf-8")

    third_party_kilo = fake_home / ".kilo" / "skills" / "custom-rust-linter"
    third_party_kilo.mkdir(parents=True)
    (third_party_kilo / "SKILL.md").write_text(
        "---\nname: custom-rust-linter\ndescription: Custom linter skill\nversion: 0.2.0\n---\n# Rust Linter\n",
        encoding="utf-8",
    )

    # Also install the same third-party skill in both assistants with different versions
    third_party_kilo_pdf = fake_home / ".kilo" / "skills" / "acme-pdf-helper"
    third_party_kilo_pdf.mkdir(parents=True)
    (third_party_kilo_pdf / "SKILL.md").write_text(
        "---\nname: acme-pdf-helper\ndescription: Third-party PDF skill\nversion: 2.9.0\n---\n# Acme PDF older\n",
        encoding="utf-8",
    )

    doc = oe.inspect_project_doctor(proj_dir, home=fake_home)
    assert doc["ok"] is True
    assert doc["drifted"] is False
    assert doc["findings"] == []
    assert doc["checks"]["global_skills"]["drifted"] is False
    assert doc["checks"]["global_skills"]["drifted_names"] == []
    assert doc["checks"]["global_skills"]["versions_found"] == []


def test_19_2_b3_non_header_tasks_validate_errors_reported_separately_from_legacy_task_headers(
    tmp_path: pathlib.Path,
) -> None:
    """B3: Non-header `tasks validate` errors (e.g. missing `## Verification` section or dependency cycle)
    are reported under `tasks-validation-errors`, while `legacy-task-headers` is reserved for genuine
    legacy-header diagnostics."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proj_dir = tmp_path / "proj_val_err"
    create_updated_project_fixture(proj_dir, home=fake_home)

    # Corrupt T001 body by removing required `## Verification` section while keeping valid current headers
    t001_path = proj_dir / "tasks" / "scrapers" / "T001-autoscout-adapter.md"
    t001_text = t001_path.read_text(encoding="utf-8")
    t001_no_ver = t001_text.replace("## Verification\n\n- `pytest tests/test_autoscout.py` passes.\n\n", "")
    t001_path.write_text(t001_no_ver, encoding="utf-8")

    doc = oe.inspect_project_doctor(proj_dir, home=fake_home)
    assert doc["ok"] is False
    assert doc["drifted"] is True
    kinds = {f["kind"] for f in doc["findings"]}
    assert "tasks-validation-errors" in kinds
    assert "legacy-task-headers" not in kinds

    val_f = next(f for f in doc["findings"] if f["kind"] == "tasks-validation-errors")
    assert val_f["severity"] == "error"
    assert any("missing required Markdown section(s): ## Verification" in e for e in val_f["errors"])
    assert doc["checks"]["task_headers"]["ok"] is True
    assert doc["checks"]["tasks_validation"]["ok"] is False


def test_19_2_b4_render_and_import_exceptions_emit_doctor_check_failed_and_never_mark_index_in_sync(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B4: Exceptions during index sync render, AGENTS.md render, tasks/AGENTS.md render,
    task-validation (`validate_tasks_tree`), workspace registry lookup (`resolve_workspace_for_path`),
    or helper module import are never swallowed as OK/in-sync and instead emit `doctor-check-failed`
    findings with `severity='error'`."""
    import orchestration_env as oe

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proj_dir = tmp_path / "proj_check_fail"
    create_updated_project_fixture(proj_dir, home=fake_home)

    te = oe._load_tasks_engine()
    oc = oe._load_orchestration_config()
    reg = oe._load_orchestration_registry()

    def _boom_index(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("simulated index render failure")

    def _boom_agents(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("simulated agents render failure")

    def _boom_tasks_agents(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("simulated tasks agents render failure")

    def _boom_validate(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated tasks validate failure")

    def _boom_registry(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated workspace registry failure")

    # 1. Runtime check exceptions (index-sync, agents-md, tasks-agents-md, tasks-validate, workspace-registry)
    with monkeypatch.context() as mp:
        mp.setattr(te, "render_synced_index", _boom_index)
        mp.setattr(oc, "render_agents_md_block", _boom_agents)
        mp.setattr(te, "render_upgraded_agents_md", _boom_tasks_agents)
        mp.setattr(te, "validate_tasks_tree", _boom_validate)
        mp.setattr(reg, "resolve_workspace_for_path", _boom_registry)
        doc = oe.inspect_project_doctor(proj_dir, home=fake_home)

    assert doc["ok"] is False
    assert doc["drifted"] is True
    assert doc["checks"]["index_markers"]["in_sync"] is False
    assert doc["checks"]["index_markers"]["ok"] is False
    assert doc["checks"]["agents_md"]["ok"] is False
    assert doc["checks"]["task_headers"]["ok"] is False
    assert doc["checks"]["tasks_validation"]["ok"] is False
    assert doc["checks"]["workspace_registry"]["ok"] is False

    failed_findings = [f for f in doc["findings"] if f["kind"] == "doctor-check-failed"]
    failed_checks = {f["check"] for f in failed_findings}
    assert {
        "index-sync",
        "agents-md",
        "tasks-agents-md",
        "tasks-validate",
        "workspace-registry",
    }.issubset(failed_checks)
    for ff in failed_findings:
        assert ff["severity"] == "error"

    # 2. Helper module import failures (`import-tasks-engine`, `import-orchestration-config`, `import-orchestration-registry`)
    def _boom_import_te() -> object:
        raise ImportError("simulated tasks_engine import failure")

    def _boom_import_oc() -> object:
        raise ImportError("simulated orchestration_config import failure")

    def _boom_import_reg() -> object:
        raise ImportError("simulated orchestration_registry import failure")

    with monkeypatch.context() as mp:
        mp.setattr(oe, "_load_tasks_engine", _boom_import_te)
        mp.setattr(oe, "_load_orchestration_config", _boom_import_oc)
        mp.setattr(oe, "_load_orchestration_registry", _boom_import_reg)
        doc_imp = oe.inspect_project_doctor(proj_dir, home=fake_home)

    assert doc_imp["ok"] is False
    assert doc_imp["drifted"] is True
    assert doc_imp["checks"]["index_markers"]["ok"] is False
    assert doc_imp["checks"]["agents_md"]["ok"] is False
    assert doc_imp["checks"]["task_headers"]["ok"] is False
    assert doc_imp["checks"]["tasks_validation"]["ok"] is False
    assert doc_imp["checks"]["workspace_registry"]["ok"] is False

    imp_failed = [f for f in doc_imp["findings"] if f["kind"] == "doctor-check-failed"]
    imp_checks = {f["check"] for f in imp_failed}
    assert {
        "import-tasks-engine",
        "import-orchestration-config",
        "import-orchestration-registry",
    }.issubset(imp_checks)
    for ff in imp_failed:
        assert ff["severity"] == "error"


def test_19_2_b5_drift_warning_command_matrix_and_documented_exclusions(
    tmp_path: pathlib.Path,
) -> None:
    """B5: Verify the 1-line stderr drift warning across the command matrix (`tasks`, `config`, `env`,
    `questions`, `use-cases`, `run`, `events`, `sessions`, `triggers`, `workspace`, `preflight`, `describe`)
    and verify that documented exclusions (`doctor`, `upgrade`, `env doctor`, `--help`) do not emit it."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    drifted_proj = tmp_path / "drifted_matrix_proj"
    create_2026_10_17_fixture(drifted_proj)

    env_base = os.environ.copy()
    env_base["AI_ORCH_HOME"] = str(fake_home)
    env_base.pop("AI_ORCH_NO_DRIFT_WARNING", None)
    env_base.pop("AI_ORCH_DRIFT_WARNING", None)

    warn_commands = [
        ["tasks", "list", "--tasks-dir", str(drifted_proj / "tasks"), "--json"],
        ["config", "show", "--workspace", str(drifted_proj), "--json"],
        ["env", "status", "--home", str(fake_home), "--workspace", str(drifted_proj), "--json"],
        ["questions", "list", "--tasks-dir", str(drifted_proj / "tasks"), "--json"],
        ["use-cases", "list", "--tasks-dir", str(drifted_proj / "tasks"), "--json"],
        ["run", "list", "--workspace", str(drifted_proj), "--json"],
        ["events", "tail", "--workspace", str(drifted_proj), "--json"],
        ["sessions", "list", "--workspace", str(drifted_proj), "--json"],
        ["triggers", "list", "--workspace", str(drifted_proj), "--json"],
        ["workspace", "list", "--json"],
        ["preflight", "--workspace", str(drifted_proj), "--json"],
        ["describe", "--json"],
    ]

    for cmd_args in warn_commands:
        res = subprocess.run(
            [sys.executable, str(AI_ORCH_BIN), *cmd_args],
            cwd=str(drifted_proj),
            env=env_base,
            capture_output=True,
            text=True,
            check=True,
        )
        parsed = json.loads(res.stdout)
        assert isinstance(parsed, (dict, list)), f"stdout not valid JSON for {cmd_args}"
        assert "[ai-orch] warning: project 'drifted_matrix_proj' has convention drift" in res.stderr, (
            f"missing drift warning on stderr for {cmd_args}: {res.stderr!r}"
        )

    excluded_commands = [
        ["doctor", "--project", str(drifted_proj), "--home", str(fake_home), "--json"],
        ["upgrade", "--project", str(drifted_proj), "--home", str(fake_home), "--json"],
        ["env", "doctor", "--project", str(drifted_proj), "--home", str(fake_home), "--json"],
        ["tasks", "--help"],
    ]
    for cmd_args in excluded_commands:
        res = subprocess.run(
            [sys.executable, str(AI_ORCH_BIN), *cmd_args],
            cwd=str(drifted_proj),
            env=env_base,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "[ai-orch] warning:" not in res.stderr, f"unexpected warning for excluded command {cmd_args}"


def test_19_2_b6_no_fixture_builders_in_production_module_and_checked_in_fixtures_used() -> None:
    """B6: Large fixture builders are moved out of `scripts/orchestration_env.py` into the tests
    and backed by checked-in fixture files under `scripts/fixtures/`."""
    import orchestration_env as oe

    assert not hasattr(oe, "create_2026_10_17_fixture")
    assert not hasattr(oe, "create_updated_project_fixture")
    assert (FIXTURES_DIR / "project_2026_10_17" / "AGENTS.md").is_file()
    assert (FIXTURES_DIR / "project_2026_10_17" / "tasks" / "00-INDEX.md").is_file()
    assert (FIXTURES_DIR / "project_2026_10_17" / "tasks" / "scrapers" / "T001-autoscout-adapter.md").is_file()
    assert (FIXTURES_DIR / "project_updated" / "AGENTS.md").is_file()
    assert (FIXTURES_DIR / "project_updated" / "tasks" / "scrapers" / "T001-autoscout-adapter.md").is_file()












