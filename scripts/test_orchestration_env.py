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

    # Verify old copy was moved to .ai-orch-trash/
    trash_dir = claude_skills / ".ai-orch-trash"
    assert trash_dir.is_dir()
    trashed_foreign = list(trash_dir.glob("*/orchestration-workflow/SKILL.md"))
    assert len(trashed_foreign) == 1
    assert trashed_foreign[0].read_text() == "# Foreign Orchestration\n"

    # Verify new copy was installed with .ai-orch-source.json
    assert (foreign_dir / "SKILL.md").read_text() != "# Foreign Orchestration\n"
    assert (foreign_dir / ".ai-orch-source.json").is_file()

    # Now overwrite executor-contract as well
    inst3 = run_env(
        ["install-skills", "--assistants", "claude", "--scope", "global", "--overwrite", "executor-contract"],
        fake_home,
    )
    assert inst3["ok"] is True
    trashed_modified = list(trash_dir.glob("*/executor-contract/SKILL.md"))
    assert len(trashed_modified) == 1
    assert trashed_modified[0].read_text() == "# Local Edit of Executor\n"

    # Verify .ai-orch-trash is ignored by inspect_environment
    st2 = run_env(["status"], fake_home)
    assert ".ai-orch-trash" not in st2["environments"]["claude"]["global"]["skills"]


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
    assert res_good["installed_count"] >= 8

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

    # Preserved in .ai-orch-trash/
    trashed_skill = list((fake_home / ".claude" / "skills" / ".ai-orch-trash").glob("*/interactive-role-setup/SKILL.md"))
    assert len(trashed_skill) == 1
    assert trashed_skill[0].read_text() == "# Obsolete Skill\n"

    trashed_agent = list((kilo_agents / ".ai-orch-trash").glob("*/mcp-orchestrator-agent.md"))
    assert len(trashed_agent) == 1
    assert trashed_agent[0].read_text() == "# Obsolete Agent\n"


def test_remove_skill_and_resolve_conflicts_trash_instead_of_delete(tmp_path: pathlib.Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Install generic and bound skills to induce conflict in claude
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    claude_skills = fake_home / ".claude" / "skills"
    assert (claude_skills / "orchestration-workflow").is_dir()
    assert (claude_skills / "kilo-mcp-orchestrator").is_dir()

    # Resolve conflicts -> moves generic 'orchestration-workflow' to .ai-orch-trash/
    rc = run_env(["resolve-conflicts"], fake_home)
    assert rc["ok"] is True
    assert not (claude_skills / "orchestration-workflow").exists()
    assert (claude_skills / "kilo-mcp-orchestrator").is_dir()

    trashed_conflict = list((claude_skills / ".ai-orch-trash").glob("*/orchestration-workflow/SKILL.md"))
    assert len(trashed_conflict) == 1

    # Remove skill -> moves 'kilo-mcp-orchestrator' to .ai-orch-trash/
    rm = run_env(["remove-skill", "kilo-mcp-orchestrator", "--assistant", "claude"], fake_home)
    assert rm["ok"] is True
    assert not (claude_skills / "kilo-mcp-orchestrator").exists()

    trashed_rm = list((claude_skills / ".ai-orch-trash").glob("*/kilo-mcp-orchestrator/SKILL.md"))
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
    run_env(["install-skills", "--assistants", "kilo", "claude", "--repo", "ai-orchestration"], fake_home)
    run_env(["install-skills", "--assistants", "kilo", "claude", "--repo", "kilo-mcp"], fake_home)

    rc = run_env(["resolve-conflicts"], fake_home)
    assert rc["ok"] is True
    assert rc["resolved_count"] == 2

    kilo_res = next(r for r in rc["resolved"] if r["assistant"] == "kilo")
    assert kilo_res["kept"] == "kilo-mcp-orchestrator"
    assert kilo_res["removed"] == "orchestration-workflow"

    claude_res = next(r for r in rc["resolved"] if r["assistant"] == "claude")
    assert claude_res["kept"] == "orchestration-workflow"
    assert claude_res["removed"] == "kilo-mcp-orchestrator"
