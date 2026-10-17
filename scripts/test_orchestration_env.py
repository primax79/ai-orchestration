"""Unit tests for scripts/orchestration_env.py (skill installation, MCP registration, status & drift detection across kilo, claude, and codex)."""
from __future__ import annotations

import hashlib
import json
import os
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
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)
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
    run_env(["install-skills", "--assistants", "claude", "--scope", "global"], fake_home)
    trash_root = fake_home / ".config" / "ai-orchestration" / "trash"
    before = sorted(p for p in trash_root.rglob("*")) if trash_root.exists() else []

    plan = run_env(["install-skills", "--dry-run", "--assistants", "claude", "--scope", "global"], fake_home)
    skill_actions = {e["action"] for e in plan["plan"] if "/skills/" in e["path"]}
    assert skill_actions == {"noop"}, skill_actions

    run_env(["install-skills", "--assistants", "claude", "--scope", "global"], fake_home)
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
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)

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
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)

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

    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home_a)

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
    assert "disable plugin architect-side@ai-orchestration in ~/.claude/settings.json (enabledPlugins) or uninstall it" in plan_b[0]["reason"]
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
            expected_tcs = 1 if scope == "global" else 0
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
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    # 1. Status inspection: conflict carries fixable=True, actions non-empty, scope='global'
    st = run_env(["status"], fake_home)
    scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    assert len(scs) == 1
    sc = scs[0]
    assert sc["kind"] == "trigger-conflict"
    assert sc["scope"] == "global"
    assert sc["fixable"] is True
    assert sc["actionable"] is True
    assert len(sc["actions"]) == 1
    assert sc["actions"][0]["action"] == "trash"
    assert sc["actions"][0]["path"].endswith("orchestration-workflow")
    assert sc["advice"] == []

    # 2. Dry-run resolution: plan contains executable actions, applied=0, resolved_count=1
    rc_dry = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc_dry["ok"] is True
    assert rc_dry["dry_run"] is True
    assert len(rc_dry["actions"]) == 1
    assert rc_dry["actions"][0]["action"] == "trash"
    assert rc_dry["advice"] == []
    assert rc_dry["applied"] == 0
    assert rc_dry["resolved_count"] == 1
    assert rc_dry["resolved"] == []

    # 3. Apply resolution: executing plan performs action, returns applied=1, resolved_count=1
    rc_apply = run_env(["resolve-conflicts", "--apply"], fake_home)
    assert rc_apply["ok"] is True
    assert rc_apply["applied"] == 1
    assert rc_apply["resolved_count"] == 1
    assert len(rc_apply["resolved"]) == 1
    assert rc_apply["resolved"][0]["assistant"] == "claude"
    assert rc_apply["resolved"][0]["removed"] == "orchestration-workflow"
    assert rc_apply["resolved"][0]["kept"] == "kilo-mcp-orchestrator"

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
    assert "disable plugin" in sc["advice"][0]

    # 2. Dry-run resolution: explicitly states actions=[] and advice=[...]
    rc_dry = run_env(["resolve-conflicts", "--dry-run"], fake_home)
    assert rc_dry["ok"] is True
    assert rc_dry["dry_run"] is True
    assert rc_dry["actions"] == []
    assert len(rc_dry["advice"]) == 1
    assert "disable plugin" in rc_dry["advice"][0]
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
    run_env(["install-skills", "--assistants", "claude", "--repo", "ai-orchestration"], fake_home)
    run_env(["install-skills", "--assistants", "claude", "--repo", "kilo-mcp"], fake_home)

    # 1. Status with project workspace:
    # Finding appears in global section (scope="global"), but is NOT repeated in project section
    st = run_env(["status", "--workspace", str(fake_ws)], fake_home)
    global_scs = st["environments"]["claude"]["global"]["structured_conflicts"]
    assert len(global_scs) == 1
    assert global_scs[0]["kind"] == "trigger-conflict"
    assert global_scs[0]["scope"] == "global"

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
    assert len(g_scs2) == 1
    assert g_scs2[0]["kind"] == "trigger-conflict"

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




