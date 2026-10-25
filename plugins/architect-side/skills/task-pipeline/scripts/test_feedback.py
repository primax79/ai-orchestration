"""test_feedback.py — Tests for ai-orch feedback and outbox flush (T034).

Covers:
  - Resolution order (env, config, repo, outbox)
  - Inbox note creation with provenance footer and ready status
  - --dry-run writes nothing
  - Outbox fallback and feedback flush (with --dry-run)
  - Broker-held lock falling back to outbox instead of failing
  - tasks upgrade writing the tooling feedback rule in AGENTS.md
  - Author resolution (registry slug -> git toplevel -> cwd)
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from typing import Any

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import orchestration_broker_lock as obl
import tasks_engine as te

BIN_AI_ORCH = REPO_ROOT / "bin" / "ai-orch"


def run_engine(*args: str, cwd: pathlib.Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPTS_DIR / "tasks_engine.py"), *args]
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=run_env,
        check=False,
    )


def run_bin(*args: str, cwd: pathlib.Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(BIN_AI_ORCH), *args]
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=run_env,
        check=False,
    )


# ---------------------------------------------------------------------------
# 1. Resolution Order
# ---------------------------------------------------------------------------

def test_feedback_resolution_order_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_target = tmp_path / "env-tasks"
    env_target.mkdir()
    monkeypatch.setenv("AI_ORCH_FEEDBACK_TASKS_DIR", str(env_target))

    source, path = te.resolve_feedback_target()
    assert source == "env"
    assert path == env_target.resolve()


def test_feedback_resolution_order_config(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_ORCH_FEEDBACK_TASKS_DIR", raising=False)
    config_dir = tmp_path / "global_config"
    config_dir.mkdir()
    cfg_target = tmp_path / "cfg-tasks"
    cfg_target.mkdir()

    cfg_file = config_dir / "orchestration.toml"
    cfg_file.write_text(f'[feedback]\ntasks_dir = "{cfg_target}"\n', encoding="utf-8")
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(config_dir))

    source, path = te.resolve_feedback_target(config_dir=config_dir)
    assert source == "config"
    assert path == cfg_target.resolve()


def test_feedback_resolution_order_repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_ORCH_FEEDBACK_TASKS_DIR", raising=False)
    config_dir = tmp_path / "global_config"
    config_dir.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(config_dir))
    monkeypatch.setenv("AI_ORCH_BIN", str(REPO_ROOT / "bin" / "ai-orch"))

    source, path = te.resolve_feedback_target(config_dir=config_dir)
    assert source == "repo"
    assert path == (REPO_ROOT / "tasks").resolve()


def test_feedback_resolution_order_outbox(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_ORCH_FEEDBACK_TASKS_DIR", raising=False)
    config_dir = tmp_path / "global_config"
    config_dir.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(config_dir))

    # Point AI_ORCH_BIN to a fake binary in a repo without task-pipeline
    fake_repo = tmp_path / "fake-repo"
    fake_bin = fake_repo / "bin" / "ai-orch"
    fake_bin.parent.mkdir(parents=True)
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("AI_ORCH_BIN", str(fake_bin))

    source, path = te.resolve_feedback_target(config_dir=config_dir)
    assert source == "outbox"
    assert path == (config_dir / "feedback-outbox").resolve()

    # When for_flush=True, outbox resolution returns (outbox, None)
    source_fl, path_fl = te.resolve_feedback_target(config_dir=config_dir, for_flush=True)
    assert source_fl == "outbox"
    assert path_fl is None


# ---------------------------------------------------------------------------
# 2. Inbox Note Creation & Provenance Footer
# ---------------------------------------------------------------------------

def test_feedback_creates_inbox_note_with_footer(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    te.upgrade_tasks_tree(tasks_dir)

    monkeypatch.setenv("AI_ORCH_FEEDBACK_TASKS_DIR", str(tasks_dir))

    res = run_bin(
        "feedback",
        "--kind", "bug",
        "--title", "Widget fails to render",
        "--body", "The widget throws ReferenceError on load.\nExpected clean render.",
        "--short", "Broken widget",
        "--author", "custom-developer",
        "--about", "src/widget.ts",
        "--json",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["target_source"] == "env"
    assert payload["id"] == "N001"

    # Inspect created note file
    note_file = tasks_dir / payload["rel_path"]
    assert note_file.is_file()
    content = note_file.read_text(encoding="utf-8")

    # Header checks
    assert "- id: N001" in content
    assert "- title: Widget fails to render" in content
    assert "- kind: bug" in content
    assert "- status: ready" in content
    assert "- author: custom-developer" in content
    assert "- about: src/widget.ts" in content
    assert "- short: Broken widget" in content

    # Body and footer checks
    assert "The widget throws ReferenceError on load." in content
    assert "Expected clean render." in content
    assert "---" in content
    assert "- Author: custom-developer" in content
    assert "- Workspace:" in content
    assert "- ai-orch:" in content
    assert "- Date:" in content

    # Must NOT contain environment variables or raw file dumps
    assert "AI_ORCH_FEEDBACK_TASKS_DIR" not in content
    assert "PATH=" not in content


# ---------------------------------------------------------------------------
# 3. --dry-run Writes Nothing
# ---------------------------------------------------------------------------

def test_feedback_dry_run_writes_nothing(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    te.upgrade_tasks_tree(tasks_dir)

    monkeypatch.setenv("AI_ORCH_FEEDBACK_TASKS_DIR", str(tasks_dir))

    to_analyze = tasks_dir / "_inbox" / "to-analyze"
    files_before = list(to_analyze.iterdir())

    # Text output dry-run
    res_text = run_bin(
        "feedback",
        "--kind", "feature",
        "--title", "Add fuzzy matching",
        "--body", "It would be useful to support fzf-style search.",
        "--dry-run",
    )
    assert res_text.returncode == 0, res_text.stderr
    assert "[dry-run]" in res_text.stdout
    assert "Add fuzzy matching" in res_text.stdout
    assert list(to_analyze.iterdir()) == files_before

    # JSON output dry-run
    res_json = run_bin(
        "feedback",
        "--kind", "feature",
        "--title", "Add fuzzy matching",
        "--body", "It would be useful to support fzf-style search.",
        "--dry-run",
        "--json",
    )
    assert res_json.returncode == 0
    payload = json.loads(res_json.stdout)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["note"]["title"] == "Add fuzzy matching"
    assert list(to_analyze.iterdir()) == files_before


# ---------------------------------------------------------------------------
# 4. Outbox Fallback and Flush
# ---------------------------------------------------------------------------

def test_feedback_outbox_fallback_and_flush(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_ORCH_FEEDBACK_TASKS_DIR", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(config_dir))

    # Point AI_ORCH_BIN to dummy binary to trigger outbox fallback (step 4)
    fake_repo = tmp_path / "foreign-project"
    fake_bin = fake_repo / "bin" / "ai-orch"
    fake_bin.parent.mkdir(parents=True)
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("AI_ORCH_BIN", str(fake_bin))

    outbox_dir = config_dir / "feedback-outbox"

    # 1. Queue feedback into outbox
    res_queue = run_bin(
        "feedback",
        "--kind", "idea",
        "--title", "CLI tab completion",
        "--body", "Shell completion for subcommands would save time.",
        "--json",
    )
    assert res_queue.returncode == 0, res_queue.stdout + res_queue.stderr
    queue_payload = json.loads(res_queue.stdout)
    assert queue_payload["ok"] is True
    assert queue_payload["queued"] is True
    assert queue_payload["target_source"] == "outbox"

    assert outbox_dir.is_dir()
    queued_notes = list(outbox_dir.glob("*/note.md"))
    assert len(queued_notes) == 1
    content = queued_notes[0].read_text(encoding="utf-8")
    assert "- title: CLI tab completion" in content
    assert "- kind: idea" in content
    assert "- status: ready" in content

    # 2. Flush fails when target tasks dir is not configured
    res_flush_err = run_bin("feedback", "flush", "--json")
    assert res_flush_err.returncode != 0
    err_payload = json.loads(res_flush_err.stdout)
    assert err_payload["ok"] is False
    assert err_payload["error"] == "target-not-configured"

    # 3. Configure target tasks directory
    target_tasks = tmp_path / "target-tasks"
    target_tasks.mkdir()
    te.upgrade_tasks_tree(target_tasks)
    monkeypatch.setenv("AI_ORCH_FEEDBACK_TASKS_DIR", str(target_tasks))

    # 4. Flush dry-run: leaves outbox intact and writes nothing to target
    res_flush_dry = run_bin("feedback", "flush", "--dry-run", "--json")
    assert res_flush_dry.returncode == 0
    dry_payload = json.loads(res_flush_dry.stdout)
    assert dry_payload["ok"] is True
    assert dry_payload["dry_run"] is True
    assert dry_payload["would_flush_count"] == 1
    assert len(list(outbox_dir.glob("*/note.md"))) == 1
    assert len(list((target_tasks / "_inbox" / "to-analyze").iterdir())) == 0

    # 5. Real flush moves note from outbox into target tasks tree
    res_flush_real = run_bin("feedback", "flush", "--json")
    assert res_flush_real.returncode == 0
    flush_payload = json.loads(res_flush_real.stdout)
    assert flush_payload["ok"] is True
    assert flush_payload["flushed_count"] == 1

    # Outbox is now empty
    assert len(list(outbox_dir.glob("*/note.md"))) == 0

    # Target tasks tree now has the note
    target_notes = list((target_tasks / "_inbox" / "to-analyze").glob("*/note.md"))
    assert len(target_notes) == 1
    flushed_content = target_notes[0].read_text(encoding="utf-8")
    assert "- title: CLI tab completion" in flushed_content
    assert "- id: N001" in flushed_content
    assert "- status: ready" in flushed_content

    # 6. Flush on empty outbox succeeds with count 0
    res_flush_empty = run_bin("feedback", "flush", "--json")
    assert res_flush_empty.returncode == 0
    empty_payload = json.loads(res_flush_empty.stdout)
    assert empty_payload["ok"] is True
    assert empty_payload["flushed_count"] == 0


# ---------------------------------------------------------------------------
# 5. Broker-Held Lock Falls Back to Outbox
# ---------------------------------------------------------------------------

def test_feedback_broker_lock_fallback_to_outbox(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(config_dir))

    target_tasks = tmp_path / "target-tasks"
    target_tasks.mkdir()
    te.upgrade_tasks_tree(target_tasks)
    monkeypatch.setenv("AI_ORCH_FEEDBACK_TASKS_DIR", str(target_tasks))

    # Acquire broker lock in config_dir
    handle = obl.acquire_broker_lock(config_dir=config_dir)
    assert handle is not None
    status = obl.broker_status(config_dir=config_dir)
    assert status.held is True

    # Submit feedback while broker holds lock
    res = run_bin(
        "feedback",
        "--kind", "bug",
        "--title", "Fails while broker running",
        "--body", "Broker is active.",
        "--json",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["queued"] is True
    assert payload["broker_lock_held"] is True
    assert payload["target_source"] == "outbox"

    # Note was queued in outbox, target tree has no new note
    outbox_dir = config_dir / "feedback-outbox"
    assert len(list(outbox_dir.glob("*/note.md"))) == 1
    assert len(list((target_tasks / "_inbox" / "to-analyze").iterdir())) == 0

    # Flush while broker is held fails safely
    res_flush = run_bin("feedback", "flush", "--json")
    assert res_flush.returncode != 0
    flush_payload = json.loads(res_flush.stdout)
    assert flush_payload["ok"] is False
    assert flush_payload["error"] == "broker-owns-writes"

    # Release broker lock and flush succeeds
    handle.release()
    res_flush_ok = run_bin("feedback", "flush", "--json")
    assert res_flush_ok.returncode == 0
    assert len(list(outbox_dir.glob("*/note.md"))) == 0
    assert len(list((target_tasks / "_inbox" / "to-analyze").glob("*/note.md"))) == 1


# ---------------------------------------------------------------------------
# 6. Tasks Upgrade AGENTS.md Rule
# ---------------------------------------------------------------------------

def test_tasks_upgrade_writes_feedback_rule_in_agents_md(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Plain upgrade previews by default and writes nothing
    res_prev = run_bin("tasks", "upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_prev.returncode == 0, res_prev.stdout + res_prev.stderr
    prev_payload = json.loads(res_prev.stdout)
    assert prev_payload["ok"] is True
    assert prev_payload["applied"] is False
    assert not (tasks_dir / "AGENTS.md").exists()

    # Apply with plan hash writes
    res = run_bin(
        "tasks",
        "upgrade",
        "--tasks-dir",
        str(tasks_dir),
        "--apply",
        "--expect-plan-hash",
        prev_payload["plan_hash"],
        "--json",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["applied"] is True

    agents_file = tasks_dir / "AGENTS.md"
    assert agents_file.is_file()
    text = agents_file.read_text(encoding="utf-8")
    assert "Tooling feedback" in text
    assert "ai-orch feedback" in text
    assert "Do not work around tooling issues silently" in text


# ---------------------------------------------------------------------------
# 7. Validation & Edge Cases
# ---------------------------------------------------------------------------

def test_feedback_validation_and_body_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    te.upgrade_tasks_tree(tasks_dir)
    monkeypatch.setenv("AI_ORCH_FEEDBACK_TASKS_DIR", str(tasks_dir))

    # Missing kind
    res1 = run_bin("feedback", "--title", "T", "--body", "B", "--json")
    assert res1.returncode == 2

    # Invalid kind
    res2 = run_bin("feedback", "--kind", "invalid", "--title", "T", "--body", "B", "--json")
    assert res2.returncode == 2

    # Missing title
    res3 = run_bin("feedback", "--kind", "bug", "--body", "B", "--json")
    assert res3.returncode == 2

    # Missing body and body-file
    res4 = run_bin("feedback", "--kind", "bug", "--title", "T", "--json")
    assert res4.returncode == 2

    # Nonexistent body-file
    res5 = run_bin("feedback", "--kind", "bug", "--title", "T", "--body-file", str(tmp_path / "nope.md"), "--json")
    assert res5.returncode == 2

    # Valid body-file
    bf = tmp_path / "content.md"
    bf.write_text("Detailed body from file.\nMulti-line description.", encoding="utf-8")
    res6 = run_bin("feedback", "--kind", "request", "--title", "From file", "--body-file", str(bf), "--json")
    assert res6.returncode == 0
    p6 = json.loads(res6.stdout)
    assert p6["ok"] is True
    created = (tasks_dir / p6["rel_path"]).read_text(encoding="utf-8")
    assert "Detailed body from file." in created


def test_feedback_author_default_resolution(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    te.upgrade_tasks_tree(tasks_dir)
    monkeypatch.setenv("AI_ORCH_FEEDBACK_TASKS_DIR", str(tasks_dir))

    # Test author fallback to git toplevel basename when outside registered workspace
    res = run_bin(
        "feedback",
        "--kind", "idea",
        "--title", "Author resolution check",
        "--body", "Testing author fallback.",
        "--json",
    )
    assert res.returncode == 0
    p = json.loads(res.stdout)
    created = (tasks_dir / p["rel_path"]).read_text(encoding="utf-8")
    # In this worktree, git toplevel name is task-T034-built-in-feedback
    assert f"- author: {REPO_ROOT.name}" in created
    assert f"- Author: {REPO_ROOT.name}" in created
