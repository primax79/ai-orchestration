#!/usr/bin/env python3
"""Unit tests for tasks_engine.py."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import tasks_engine as te  # noqa: E402

SCRIPT_PATH = SCRIPT_DIR / "tasks_engine.py"
REPO_ROOT = SCRIPT_DIR.parents[4]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_sample_task(
    path: pathlib.Path,
    task_id: str = "T001",
    title: str = "Implement scraper",
    category: str = "features",
    priority: str = "P1",
    next_up: str = "yes",
    state: str = "open",
    executor: str = "kilo",
    depends_on: str = "-",
    decider: str = "-",
    profile: str | None = "bulk-execution",
    verification_mode: str | None = "cross-agent",
    verifier: str | None = "-",
    short: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ext_lines = []
    if profile is not None:
        ext_lines.append(f"- profile: {profile}")
    if verification_mode is not None:
        ext_lines.append(f"- verification-mode: {verification_mode}")
    if verifier is not None:
        ext_lines.append(f"- verifier: {verifier}")
    if short is not None:
        ext_lines.append(f"- short: {short}")
    ext_block = ("\n" + "\n".join(ext_lines)) if ext_lines else ""

    content = f"""# {task_id} {title}

- id: {task_id}
- title: {title}
- category: {category}
- priority: {priority}
- priority-reason: Needed for feature parity
- next-up: {next_up}
- state: {state}
- executor: {executor}
- depends-on: {depends_on}
- decider: {decider}
- sources: spec.md
- paths: src/scraper.py
- handoff: Read tasks/{category}/{path.name}, do the open steps, run the Verification, update the task and the registry.{ext_block}

## Goal

Build the scraper module.

## Steps

1. Write `src/scraper.py`.

## Verification

- `pytest tests/test_scraper.py` passes.
"""
    path.write_text(content, encoding="utf-8")


def test_upgrade_tasks_tree(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    # Write old-style AGENTS.md
    (tasks_dir / "AGENTS.md").write_text("# old convention\nmacroplan-authoring\n", encoding="utf-8")
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n\n## Initiatives\n\n| 1 | 01 | [Test](01-test/plan.md) | in progress |\n", encoding="utf-8")

    # Preview by default
    res_prev = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_prev.returncode == 0
    prev_payload = json.loads(res_prev.stdout)
    assert prev_payload["ok"] is True
    assert prev_payload["applied"] is False
    assert not (tasks_dir / "_inbox" / "to-analyze").exists()

    # Apply with plan hash
    res = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--apply", "--expect-plan-hash", prev_payload["plan_hash"], "--json")
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["applied"] is True
    assert any("AGENTS.md" in f for f in payload["upgraded_files"])
    assert (tasks_dir / "_inbox" / "to-analyze").is_dir()
    assert (tasks_dir / "_inbox" / "analyzed").is_dir()
    assert "task-pipeline" in (tasks_dir / "AGENTS.md").read_text()


def test_real_repo_tasks_validate_and_list() -> None:
    tasks_dir = REPO_ROOT / "tasks"
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0, res_val.stdout + res_val.stderr
    val_payload = json.loads(res_val.stdout)
    assert val_payload["ok"] is True
    assert val_payload["emergent_count"] >= 9
    assert val_payload["initiative_count"] >= 5

    res_list = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list.returncode == 0
    list_payload = json.loads(res_list.stdout)
    assert list_payload["ok"] is True
    ids = {t["id"] for t in list_payload["emergent_tasks"]}
    assert {"T001", "T003", "T009"}.issubset(ids)


def test_validate_catches_duplicate_id_cycle_and_missing_sections(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(tasks_dir / "features" / "T001-alpha.md", task_id="T001", depends_on="T002")
    _write_sample_task(tasks_dir / "features" / "T002-beta.md", task_id="T002", depends_on="T001")
    # Duplicate T001 in done/
    _write_sample_task(
        tasks_dir / "done" / "features" / "T001-dup.md",
        task_id="T001",
        state="done",
    )
    # Missing ## Verification section on T003
    bad_path = tasks_dir / "features" / "T003-missing-sec.md"
    _write_sample_task(bad_path, task_id="T003")
    bad_path.write_text(
        bad_path.read_text(encoding="utf-8").replace("## Verification", "## Notes"),
        encoding="utf-8",
    )

    res = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    joined_errors = "\n".join(payload["errors"])
    assert "duplicate task id 'T001'" in joined_errors
    assert "Dependency cycle detected" in joined_errors
    assert "missing required Markdown section(s): ## Verification" in joined_errors


def test_transition_guards_and_bounce_and_closure(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    # Create a folder task T001 with PROGRESS.md
    t001_readme = tasks_dir / "features" / "T001-auth" / "README.md"
    _write_sample_task(
        t001_readme,
        task_id="T001",
        title="Auth flow",
        category="features",
        executor="kilo",
        verification_mode="cross-agent",
    )

    # 1. Block direct open -> done
    res_illegal = run_cli("transition", "T001", "done", "--tasks-dir", str(tasks_dir), "--json")
    assert res_illegal.returncode == 1
    assert "must pass through 'delivered' first" in json.loads(res_illegal.stdout)["error"]

    # 2. open -> in progress
    res_ip = run_cli("transition", "T001", "in progress", "--actor", "kilo", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ip.returncode == 0

    # 3. Block direct in progress -> done
    res_illegal2 = run_cli("transition", "T001", "done", "--tasks-dir", str(tasks_dir), "--json")
    assert res_illegal2.returncode == 1

    # 4. in progress -> delivered
    res_del = run_cli("transition", "T001", "delivered", "--actor", "kilo", "--tasks-dir", str(tasks_dir), "--json")
    assert res_del.returncode == 0
    assert "verification pending:" in t001_readme.read_text(encoding="utf-8")

    # 5. Block self-verification on cross-agent mode (actor == executor == kilo)
    res_self_ver = run_cli(
        "transition",
        "T001",
        "verified",
        "--actor",
        "kilo",
        "--tasks-dir",
        str(tasks_dir),
        "--json",
    )
    assert res_self_ver.returncode == 1
    assert "Independent verification guard failed" in json.loads(res_self_ver.stdout)["error"]

    # 6. Bounce requires --reason
    res_bounce_no_reason = run_cli("transition", "T001", "bounced", "--tasks-dir", str(tasks_dir), "--json")
    assert res_bounce_no_reason.returncode == 1

    res_bounce = run_cli(
        "transition",
        "T001",
        "bounced",
        "--actor",
        "claude",
        "--reason",
        "B1: missing token expiry check in src/auth.py:42",
        "--tasks-dir",
        str(tasks_dir),
        "--json",
    )
    assert res_bounce.returncode == 0
    progress_file = t001_readme.parent / "PROGRESS.md"
    assert progress_file.exists()
    assert "B1: missing token expiry check" in progress_file.read_text(encoding="utf-8")

    # 7. bounced -> in progress -> delivered -> verified (by independent verifier claude:deep-reasoning)
    assert run_cli("transition", "T001", "in progress", "--tasks-dir", str(tasks_dir)).returncode == 0
    assert run_cli("transition", "T001", "delivered", "--tasks-dir", str(tasks_dir)).returncode == 0

    res_ver = run_cli(
        "transition",
        "T001",
        "verified",
        "--verifier",
        "claude:deep-reasoning",
        "--reason",
        "All pytest checks green",
        "--tasks-dir",
        str(tasks_dir),
        "--json",
    )
    assert res_ver.returncode == 0
    assert "verification pending:" not in t001_readme.read_text(encoding="utf-8")

    # 8. verified -> done moves folder to tasks/done/features/T001-auth/README.md
    res_done = run_cli("transition", "T001", "done", "--actor", "claude", "--tasks-dir", str(tasks_dir), "--json")
    assert res_done.returncode == 0
    done_payload = json.loads(res_done.stdout)
    assert done_payload["rel_path"] == "done/features/T001-auth/README.md"
    assert (tasks_dir / "done" / "features" / "T001-auth" / "README.md").exists()
    assert not t001_readme.exists()


def test_independent_session_blind_subagent_and_self_mode(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    # T010: Single-Framework Native mode (`independent-session`)
    _write_sample_task(
        tasks_dir / "features" / "T010-native.md",
        task_id="T010",
        executor="kilo",
        verification_mode="independent-session",
    )
    run_cli("transition", "T010", "in progress", "--tasks-dir", str(tasks_dir))
    run_cli("transition", "T010", "delivered", "--tasks-dir", str(tasks_dir))

    # Same session kilo cannot self-verify
    assert (
        run_cli("transition", "T010", "verified", "--actor", "kilo", "--tasks-dir", str(tasks_dir)).returncode == 1
    )
    # Blind subagent can verify in Single-Framework Native mode
    assert (
        run_cli(
            "transition",
            "T010",
            "verified",
            "--verifier",
            "blind-subagent:deep-reasoning",
            "--tasks-dir",
            str(tasks_dir),
        ).returncode
        == 0
    )

    # T011: verification-mode = self cannot enter verified without independent verifier, transitions to done with a caveat
    _write_sample_task(
        tasks_dir / "features" / "T011-self.md",
        task_id="T011",
        executor="kilo",
        verification_mode="self",
    )
    run_cli("transition", "T011", "in progress", "--tasks-dir", str(tasks_dir))
    run_cli("transition", "T011", "delivered", "--tasks-dir", str(tasks_dir))
    assert run_cli("transition", "T011", "verified", "--tasks-dir", str(tasks_dir)).returncode == 1
    res_caveat = run_cli(
        "transition",
        "T011",
        "done with a caveat",
        "--tasks-dir",
        str(tasks_dir),
        "--json",
    )
    assert res_caveat.returncode == 0
    assert json.loads(res_caveat.stdout)["new_state"] == "done with a caveat: self-verified only"


def test_sync_index_preserves_initiatives_and_updates_tables(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "features" / "README.md").write_text(
        "# features\n\nowner-session: s1\n\n## Goal and scope\n\nFeature tasks.\n",
        encoding="utf-8",
    )
    _write_sample_task(
        tasks_dir / "features" / "T001-first.md",
        task_id="T001",
        title="First feature",
        category="features",
        priority="P0",
        next_up="yes",
        state="waiting",
        decider="owner: Which DB engine?",
    )
    _write_sample_task(
        tasks_dir / "features" / "T002-second.md",
        task_id="T002",
        title="Second feature",
        category="features",
        priority="P1",
        next_up="no",
        depends_on="T001",
    )
    _write_sample_task(
        tasks_dir / "done" / "features" / "T000-init.md",
        task_id="T000",
        title="Initial setup",
        category="features",
        priority="P2",
        next_up="no",
        state="done",
    )

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Initiatives

| Priority | # | Initiative | Status | Depends on | Size |
| --- | --- | --- | --- | --- | --- |
| 1 | 01 | [Core](01-core/plan.md) | open | - | M |

## Specs

| Spec | Drives |
| --- | --- |
| [spec](specs/spec.md) | 01 |

## Next up

OLD

## Tasks by category

OLD

## Decisions waiting

OLD

## Done

OLD

## Dependency graph

```text
01 -> 02
```
""",
        encoding="utf-8",
    )

    chk1 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--check", "--json")
    assert chk1.returncode == 1

    # An index without markers must refuse --apply
    app_refused = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert app_refused.returncode == 1
    assert json.loads(app_refused.stdout)["ok"] is False

    # --adopt alone is preview only and writes nothing
    adopt = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--json")
    assert adopt.returncode == 0
    adopt_payload = json.loads(adopt.stdout)
    assert adopt_payload["applied"] is False
    current_h = adopt_payload["hash"]

    # --adopt --apply without --expect-hash is refused
    adopt_no_hash = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--json")
    assert adopt_no_hash.returncode == 1
    assert json.loads(adopt_no_hash.stdout)["ok"] is False

    # --adopt --apply with --expect-hash writes markers and syncs
    adopt_apply = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--expect-hash", current_h, "--json")
    assert adopt_apply.returncode == 0

    chk2 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--check", "--json")
    assert chk2.returncode == 0

    synced = index_path.read_text(encoding="utf-8")
    assert "| 1 | 01 | [Core](01-core/plan.md) | open | - | M |" in synced
    assert "01 -> 02" in synced
    assert "| T001 (First feature) | P0 | [First feature](features/T001-first.md) |" in synced
    assert "| T001 | Which DB engine? | owner | T002 |" in synced
    assert "| T000 (Initial setup) | [Initial setup](done/features/T000-init.md) | done |" in synced


def test_index_regression_fixture_lossless(tmp_path: pathlib.Path) -> None:
    fixture_dir = SCRIPT_DIR / "fixtures" / "index-regression"
    tasks_dir = tmp_path / "tasks"
    shutil.copytree(fixture_dir, tasks_dir)

    orig_index_path = fixture_dir / "00-INDEX.md"
    orig_text = orig_index_path.read_text(encoding="utf-8")
    orig_bytes = (tasks_dir / "00-INDEX.md").read_bytes()

    # Parse original Done rows from ## Done section
    def _extract_done_rows(text: str) -> dict[str, tuple[str, str]]:
        m = re.search(r"^##\s+Done\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if not m:
            return {}
        res: dict[str, tuple[str, str]] = {}
        for line in m.group(0).splitlines():
            line_s = line.strip()
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            m_id = re.match(r"^(T\d+)", cells[0])
            if len(cells) == 4 and m_id:
                res[m_id.group(1)] = (cells[2], cells[3])
        return res

    orig_done_rows = _extract_done_rows(orig_text)
    orig_ids = set(re.findall(r"\b(T\d{3})\b", orig_text))

    # 1. Preview-only adopt writes nothing
    res_adopt_preview = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--json")
    assert res_adopt_preview.returncode == 0
    payload_preview = json.loads(res_adopt_preview.stdout)
    assert payload_preview["ok"] is True
    assert payload_preview["applied"] is False
    assert (tasks_dir / "00-INDEX.md").read_bytes() == orig_bytes
    current_hash = payload_preview["hash"]

    # 2. Adopt + apply without --expect-hash is refused
    res_adopt_no_hash = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--json")
    assert res_adopt_no_hash.returncode == 1
    assert json.loads(res_adopt_no_hash.stdout)["ok"] is False
    assert (tasks_dir / "00-INDEX.md").read_bytes() == orig_bytes

    # 3. Adopt + apply with mismatched hash is refused
    res_adopt_bad_hash = run_cli(
        "sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--expect-hash", "0" * 64, "--json"
    )
    assert res_adopt_bad_hash.returncode == 1
    assert json.loads(res_adopt_bad_hash.stdout)["ok"] is False
    assert (tasks_dir / "00-INDEX.md").read_bytes() == orig_bytes

    # 4. Adopt + apply with the right hash succeeds
    res_adopt_apply = run_cli(
        "sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--expect-hash", current_hash, "--json"
    )
    assert res_adopt_apply.returncode == 0
    payload_applied = json.loads(res_adopt_apply.stdout)
    assert payload_applied["ok"] is True
    assert payload_applied["applied"] is True

    # 5. Subsequent normal apply succeeds
    res_apply = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res_apply.returncode == 0
    assert json.loads(res_apply.stdout)["ok"] is True

    result_index_path = tasks_dir / "00-INDEX.md"
    result_text = result_index_path.read_text(encoding="utf-8")

    # Verification: No row lost
    result_ids = set(re.findall(r"\b(T\d{3})\b", result_text))
    assert orig_ids.issubset(result_ids)

    # Verification: No Done cell lost (compare by id + Closed + Result)
    result_done_rows = _extract_done_rows(result_text)

    for tid, (expected_res, expected_closed) in orig_done_rows.items():
        assert tid in result_done_rows
        assert result_done_rows[tid] == (expected_res, expected_closed)

    # Regression assertion (a): Decisions table equals original Decisions table
    # (only T007, T009 rows, original texts, original header row)
    def _extract_table_lines(text: str, section_heading: str) -> list[str]:
        m = re.search(rf"^##\s+{re.escape(section_heading)}\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if not m:
            return []
        lines: list[str] = []
        for line in m.group(0).splitlines():
            line_s = line.strip()
            if line_s.startswith("|"):
                lines.append(line_s)
        return lines

    orig_dec_table = _extract_table_lines(orig_text, "Decisions waiting")
    result_dec_table = _extract_table_lines(result_text, "Decisions waiting")
    assert result_dec_table == orig_dec_table
    dec_row_ids = [
        c.strip() for line in result_dec_table[2:]
        for c in [line.strip("|").split("|")[0].strip()]
        if c and c != "-"
    ]
    assert dec_row_ids == ["T007", "T009"]

    # Regression assertion (b): sequence of ### headings and row ids in every table equal original
    def _extract_category_headings(text: str) -> list[str]:
        m = re.search(r"^##\s+Tasks by category\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if not m:
            return []
        return [cm.group(1) for cm in re.finditer(r"^###\s+([A-Za-z0-9_-]+)\s*$", m.group(0), re.MULTILINE)]

    orig_cat_headings = _extract_category_headings(orig_text)
    result_cat_headings = _extract_category_headings(result_text)
    assert result_cat_headings == orig_cat_headings

    def _extract_table_row_ids(text: str, heading_pattern: str) -> list[str]:
        m = re.search(rf"^{heading_pattern}\b.*?(?=^#+ |\Z)", text, re.MULTILINE | re.DOTALL)
        if not m:
            return []
        ids: list[str] = []
        for line in m.group(0).splitlines():
            line_s = line.strip()
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Id", "Task", "Task / Initiative", "---", "-") or cells[0].startswith("---"):
                continue
            ids.append(cells[0].split()[0] if cells[0] else "")
        return ids

    # Check row ids in Next up
    assert _extract_table_row_ids(result_text, r"##\s+Next up") == _extract_table_row_ids(orig_text, r"##\s+Next up")
    # Check row ids in each category
    for cat in orig_cat_headings:
        assert _extract_table_row_ids(result_text, rf"###\s+{cat}") == _extract_table_row_ids(orig_text, rf"###\s+{cat}")
    # Check row ids in Decisions waiting
    assert _extract_table_row_ids(result_text, r"##\s+Decisions waiting") == _extract_table_row_ids(orig_text, r"##\s+Decisions waiting")
    # Check row ids in Done
    assert _extract_table_row_ids(result_text, r"##\s+Done") == _extract_table_row_ids(orig_text, r"##\s+Done")

    # Regression assertion (c): Done rows keep order and dates
    def _extract_done_ordered(text: str) -> list[tuple[str, str, str]]:
        m = re.search(r"^##\s+Done\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if not m:
            return []
        rows: list[tuple[str, str, str]] = []
        for line in m.group(0).splitlines():
            line_s = line.strip()
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            m_id = re.match(r"^(T\d+)", cells[0])
            if len(cells) == 4 and m_id:
                rows.append((m_id.group(1), cells[2], cells[3]))
        return rows

    assert _extract_done_ordered(result_text) == _extract_done_ordered(orig_text)

    # Verification: No prose line lost outside regions
    non_region_text = re.sub(
        r"<!--\s*ai-orch:generated\s+[^\n>]+-->.*?<!--\s*/ai-orch:generated\s+[^\n>]+-->\n?",
        "",
        result_text,
        flags=re.DOTALL,
    )
    for expected_prose in [
        "# Task Index",
        "Live registry of work for this workspace.",
        "## Next up",
        "## Tasks by category",
        "## Decisions waiting",
        "Priorities validated 2026-10-08 against the P0-P3 criteria",
        "## Done",
    ]:
        assert expected_prose in non_region_text

    # Verification: Second --apply is a no-op (file bytes unchanged)
    bytes_before = result_index_path.read_bytes()
    res_apply2 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_apply2.returncode == 0
    bytes_after = result_index_path.read_bytes()
    assert bytes_before == bytes_after

    # Verification: --check exits 0
    res_check = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--check", "--json")
    assert res_check.returncode == 0
    payload_check = json.loads(res_check.stdout)
    assert payload_check["in_sync"] is True
    assert payload_check["diff"] == ""


def test_sync_index_expect_hash(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "cat").mkdir(parents=True)
    _write_sample_task(tasks_dir / "cat" / "T001.md", task_id="T001", title="Task 1", category="cat")

    # Initial creation with markers
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Next up

<!-- ai-orch:generated next-up -->
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )
    run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    current_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()

    # Mismatch hash -> refused, file unchanged
    bad_hash = "0" * 64
    res_mismatch = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--expect-hash", bad_hash, "--json")
    assert res_mismatch.returncode == 1
    payload = json.loads(res_mismatch.stdout)
    assert payload["ok"] is False
    assert "hash mismatch" in payload["error"].lower()
    assert hashlib.sha256(index_path.read_bytes()).hexdigest() == current_hash

    # Matching hash -> succeeds
    res_match = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--expect-hash", current_hash, "--json")
    assert res_match.returncode == 0
    assert json.loads(res_match.stdout)["ok"] is True


def test_sync_index_refused_without_markers(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    index_path = tasks_dir / "00-INDEX.md"
    content = "# Task Index\n\n## Next up\n\n| Id | Task |\n\n## Done\n\n| Id | Task |\n"
    index_path.write_text(content, encoding="utf-8")

    res = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert "has no generated-region markers" in payload["error"]
    assert index_path.read_text(encoding="utf-8") == content


def test_sync_index_missing_id_kept_with_suffix(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    _write_sample_task(tasks_dir / "features" / "T001-real.md", task_id="T001", title="Real task", category="features")

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
| T997 | P1 | [Missing next](features/T997.md) | kilo | `do it` |
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
### features

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T001 | P1 | [Real task](features/T001-real.md) | open | kilo | - |
| T998 | P2 | [Deleted task](features/T998.md) | open | kilo | - |
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| - | None. | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
| T999 | [Old deleted task](done/old/T999.md) | done | 2026-07-01 |
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )

    res = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res.returncode == 0

    content = index_path.read_text(encoding="utf-8")
    assert "| T999 | [Old deleted task](done/old/T999.md) (missing) | done | 2026-07-01 |" in content
    assert "| T998 | P2 | [Deleted task](features/T998.md) (missing) | open | kilo | - |" in content
    assert "| T997 | P1 | [Missing next](features/T997.md) (missing) | kilo | `do it` |" in content

    # Second apply should not duplicate "(missing) (missing)"
    res2 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res2.returncode == 0
    content2 = index_path.read_text(encoding="utf-8")
    assert "(missing) (missing)" not in content2


def test_sync_index_empty_decisions_renders_generic_row(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    _write_sample_task(tasks_dir / "features" / "T001.md", task_id="T001", title="Task", decider="-")

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| Task / Initiative | Question (exact) | Decider | Blocks |
| --- | --- | --- | --- |
| - | None currently blocking — architectural direction locked with owner on 2026-10-15 (see `docs/03`–`05`). | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )

    res = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res.returncode == 0

    content = index_path.read_text(encoding="utf-8")
    assert "| - | None. | - | - |" in content
    assert "architectural direction locked with owner" not in content


def test_sync_index_preserves_blank_lines_outside_regions(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    _write_sample_task(tasks_dir / "features" / "T001.md", task_id="T001", title="Task")

    index_path = tasks_dir / "00-INDEX.md"
    five_blanks = "\n\n\n\n\n"
    index_path.write_text(
        f"""# Task Index{five_blanks}## Next up

<!-- ai-orch:generated next-up -->
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
<!-- /ai-orch:generated done -->{five_blanks}## Footer
""",
        encoding="utf-8",
    )

    res = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res.returncode == 0

    content = index_path.read_text(encoding="utf-8")
    assert f"# Task Index{five_blanks}## Next up" in content
    assert f"{five_blanks}## Footer" in content


def test_concurrent_transitions_with_expect_task_hash(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    t001_dir = tasks_dir / "features" / "T001-concurrent"
    _write_sample_task(t001_dir / "README.md", task_id="T001", title="Concurrent task", category="features")
    (t001_dir / "CONTEXT.md").write_text("# Context\nInitial context\n", encoding="utf-8")
    (t001_dir / "PROGRESS.md").write_text("# Progress\nInitial progress\n", encoding="utf-8")

    bundle_hash = te.task_bundle_sha256(t001_dir)

    # Use a lock-holding helper process to synchronize p1 and p2 at the lock boundary
    lock_file = tasks_dir / ".ai-orch.lock"
    helper = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"""
import fcntl, os, sys
fd = os.open({str(lock_file)!r}, os.O_RDWR | os.O_CREAT, 0o666)
fcntl.flock(fd, fcntl.LOCK_EX)
sys.stdout.write("LOCKED\\n")
sys.stdout.flush()
sys.stdin.readline()
fcntl.flock(fd, fcntl.LOCK_UN)
os.close(fd)
""",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert helper.stdout is not None and helper.stdin is not None
    assert helper.stdout.readline() == "LOCKED\n"

    # Spawn two concurrent transition processes with the same expect-task-hash
    p1 = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "transition",
            "T001",
            "in progress",
            "--actor",
            "kilo",
            "--tasks-dir",
            str(tasks_dir),
            "--expect-task-hash",
            bundle_hash,
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    p2 = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "transition",
            "T001",
            "in progress",
            "--actor",
            "kilo",
            "--tasks-dir",
            str(tasks_dir),
            "--expect-task-hash",
            bundle_hash,
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    import time
    time.sleep(0.2)  # Allow both processes to start and queue on flock

    # Release the lock so p1 and p2 race
    helper.stdin.write("RELEASE\n")
    helper.stdin.flush()
    helper.wait(timeout=5)

    out1, err1 = p1.communicate(timeout=10)
    out2, err2 = p2.communicate(timeout=10)

    res1 = (p1.returncode, json.loads(out1))
    res2 = (p2.returncode, json.loads(out2))

    successes = [r for r in (res1, res2) if r[0] == 0]
    failures = [r for r in (res1, res2) if r[0] != 0]

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}: {res1}, {res2}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}: {res1}, {res2}"

    succ_payload = successes[0][1]
    fail_payload = failures[0][1]

    assert succ_payload["ok"] is True
    assert succ_payload["new_state"] == "in progress"

    assert fail_payload["ok"] is False
    assert fail_payload["error"] == "stale-task"
    assert fail_payload["expected"] == bundle_hash
    assert fail_payload["actual"] != bundle_hash


def test_stale_expect_task_hash_refused_bundle_unchanged(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    t001_dir = tasks_dir / "features" / "T001-stale"
    _write_sample_task(t001_dir / "README.md", task_id="T001", title="Stale test task", category="features")
    (t001_dir / "CONTEXT.md").write_text("# Context\nImportant context\n", encoding="utf-8")
    (t001_dir / "PROGRESS.md").write_text("# Progress\nInitial progress log\n", encoding="utf-8")

    bundle_hash = te.task_bundle_sha256(t001_dir)
    original_bytes = {
        p.relative_to(t001_dir).as_posix(): p.read_bytes()
        for p in t001_dir.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    }

    stale_hash = "0" * 64
    res = run_cli(
        "transition",
        "T001",
        "in progress",
        "--actor",
        "kilo",
        "--tasks-dir",
        str(tasks_dir),
        "--expect-task-hash",
        stale_hash,
        "--json",
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "stale-task"
    assert payload["expected"] == stale_hash
    assert payload["actual"] == bundle_hash

    # Compare bytes of every file in the task bundle
    current_bytes = {
        p.relative_to(t001_dir).as_posix(): p.read_bytes()
        for p in t001_dir.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    }
    assert current_bytes == original_bytes


def test_lock_timeout_path(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(tasks_dir / "features" / "T001-lock.md", task_id="T001", category="features")

    lock_file = tasks_dir / ".ai-orch.lock"
    helper = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"""
import fcntl, os, sys
fd = os.open({str(lock_file)!r}, os.O_RDWR | os.O_CREAT, 0o666)
fcntl.flock(fd, fcntl.LOCK_EX)
sys.stdout.write("LOCKED\\n")
sys.stdout.flush()
sys.stdin.readline()
fcntl.flock(fd, fcntl.LOCK_UN)
os.close(fd)
""",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert helper.stdout is not None and helper.stdin is not None
    assert helper.stdout.readline() == "LOCKED\n"

    try:
        import os
        env = dict(os.environ, AI_ORCH_LOCK_TIMEOUT="1")
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "transition",
                "T001",
                "in progress",
                "--actor",
                "kilo",
                "--tasks-dir",
                str(tasks_dir),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert proc.returncode != 0
        payload = json.loads(proc.stdout)
        assert payload["ok"] is False
        assert payload["error"] == "lock-timeout"
    finally:
        helper.stdin.write("QUIT\n")
        helper.stdin.flush()
        helper.wait(timeout=5)


def test_atomic_write_failure_cleanup(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_file = tmp_path / "sample.md"
    target_file.write_text("original content\n", encoding="utf-8")
    original_bytes = target_file.read_bytes()

    def failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        assert pathlib.Path(src).is_file()
        raise OSError("Simulated filesystem error during atomic replace")

    import os
    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="Simulated filesystem error"):
        te._atomic_write_text(target_file, "mutated content that should abort\n")

    # Original file is intact
    assert target_file.read_bytes() == original_bytes
    # No temp files left behind
    temp_files = list(tmp_path.glob(".*.tmp"))
    assert temp_files == []


def test_tasks_list_bundle_sha256_stability_and_context_change(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    folder_dir = tasks_dir / "features" / "T001-folder"
    _write_sample_task(folder_dir / "README.md", task_id="T001", title="Folder task", category="features")
    context_file = folder_dir / "CONTEXT.md"
    context_file.write_text("# Initial Context\nSome context text\n", encoding="utf-8")

    single_file = tasks_dir / "features" / "T002-single.md"
    _write_sample_task(single_file, task_id="T002", title="Single task", category="features")

    # 1. Run list --json
    res1 = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res1.returncode == 0
    data1 = json.loads(res1.stdout)
    assert data1["ok"] is True

    t1_hash_run1 = next(t["bundle_sha256"] for t in data1["emergent_tasks"] if t["id"] == "T001")
    t2_hash_run1 = next(t["bundle_sha256"] for t in data1["emergent_tasks"] if t["id"] == "T002")
    assert re.match(r"^[0-9a-f]{64}$", t1_hash_run1)
    assert re.match(r"^[0-9a-f]{64}$", t2_hash_run1)

    # Also verify all_tasks exposes bundle_sha256
    all_t1 = next(t["bundle_sha256"] for t in data1["all_tasks"] if t["id"] == "T001")
    assert all_t1 == t1_hash_run1

    # 2. Stability across calls
    res2 = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res2.returncode == 0
    data2 = json.loads(res2.stdout)
    t1_hash_run2 = next(t["bundle_sha256"] for t in data2["emergent_tasks"] if t["id"] == "T001")
    t2_hash_run2 = next(t["bundle_sha256"] for t in data2["emergent_tasks"] if t["id"] == "T002")
    assert t1_hash_run2 == t1_hash_run1
    assert t2_hash_run2 == t2_hash_run1

    # 3. Modify CONTEXT.md of folder task
    context_file.write_text("# Updated Context\nDifferent context text\n", encoding="utf-8")

    res3 = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res3.returncode == 0
    data3 = json.loads(res3.stdout)
    t1_hash_run3 = next(t["bundle_sha256"] for t in data3["emergent_tasks"] if t["id"] == "T001")
    t2_hash_run3 = next(t["bundle_sha256"] for t in data3["emergent_tasks"] if t["id"] == "T002")

    assert t1_hash_run3 != t1_hash_run1, "Bundle hash must change when CONTEXT.md changes"
    assert t2_hash_run3 == t2_hash_run1, "Single-file task hash must remain unchanged"


def test_unsupported_platform_refusal_on_mutating_commands(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(tasks_dir / "features" / "T001.md", task_id="T001", category="features")
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n"
        "## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    # Sync index initially so check passes
    run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")

    # Read-only commands work
    res_list = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list.returncode == 0
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    res_check = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--check", "--json")
    assert res_check.returncode == 0

    # Simulate unsupported platform
    monkeypatch.setattr(te, "is_platform_supported", lambda: False)

    # transition fails
    ok_tr, payload_tr = te.transition_task(tasks_dir, "T001", "in progress", actor="kilo")
    assert ok_tr is False
    assert payload_tr["error"] == "unsupported-platform"

    # sync-index --apply fails
    class Args:
        pass
    args_sync = Args()
    args_sync.tasks_dir = str(tasks_dir)
    args_sync.apply = True
    args_sync.check = False
    args_sync.adopt = False
    args_sync.expect_hash = None
    args_sync.json = True
    assert te.cmd_sync_index(args_sync) == 1

    # upgrade fails
    upg_res = te.upgrade_tasks_tree(tasks_dir)
    assert upg_res["ok"] is False
    assert upg_res["error"] == "unsupported-platform"


def test_validate_lock_file_git_ignore_warning(tmp_path: pathlib.Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)

    tasks_dir = repo_dir / "tasks"
    _write_sample_task(tasks_dir / "features" / "T001.md", task_id="T001", category="features")

    # 1. Lock file not ignored -> warning
    errors, warnings, emergent, initiatives = te.validate_tasks_tree(tasks_dir)
    assert len(errors) == 0
    assert any(".ai-orch.lock" in w and "not ignored by git" in w for w in warnings)

    # 2. Add .ai-orch.lock to .gitignore -> warning disappears
    (repo_dir / ".gitignore").write_text(".ai-orch.lock\n", encoding="utf-8")
    errors2, warnings2, emergent2, initiatives2 = te.validate_tasks_tree(tasks_dir)
    assert len(errors2) == 0
    assert not any(".ai-orch.lock" in w for w in warnings2)


# ---------------------------------------------------------------------------
# 08.1 Blocking Questions Tests
# ---------------------------------------------------------------------------

def _write_sample_question(
    path: pathlib.Path,
    qid: str = "Q001",
    title: str = "Sample question",
    question: str = "Should we use option A or B?",
    status: str = "open",
    blocks: str = "T001 (waiting)",
    decider: str = "owner",
    asked_by: str = "owner",
    asked: str = "2026-10-17",
    origin_run: str = "-",
    open_answer: str = "no",
    recommended: str = "A",
    context: str = "Detailed context.",
    options: list[tuple[str, str, str | None]] | None = None,
    choice: str = "-",
    answered_by: str = "-",
    answered: str = "-",
    text: str | None = None,
) -> None:
    if options is None:
        options = [
            ("A", "First option", "Safe choice"),
            ("B", "Second option", "Risky choice"),
        ]
    content = te.format_question_content(
        id=qid,
        title=title,
        question=question,
        status=status,
        blocks=blocks,
        decider=decider,
        asked_by=asked_by,
        asked=asked,
        origin_run=origin_run,
        open_answer=open_answer,
        recommended=recommended,
        context=context,
        options=options,
        choice=choice,
        answered_by=answered_by,
        answered=answered,
        text=text,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_question_validator_rules(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    q_file = tasks_dir / "questions" / "Q001-sample-question.md"

    # Base valid setup
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="waiting",
        decider="Q001",
    )
    _write_sample_question(q_file, qid="Q001", blocks="T001 (waiting)")

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert warnings == []

    # 1. Invalid question id format
    _write_sample_question(q_file, qid="Q01")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("invalid question id 'Q01'" in e for e in errors)

    # 2. Header out of order
    bad_order_content = """# Q001 Sample question

- id: Q001
- status: open
- question: Should we use option A or B?
- blocks: T001 (waiting)
- decider: owner
- asked-by: owner
- asked: 2026-10-17
- origin-run: -
- open-answer: no
- recommended: A

## Context

Context.

## Options

- **A** — First: safe
- **B** — Second: risky

## Answer

- choice: -
- answered-by: -
- answered: -
"""
    q_file.write_text(bad_order_content, encoding="utf-8")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("header fields out of order" in e for e in errors)

    # 3. Question does not end with '?'
    _write_sample_question(q_file, question="Does not end with question mark")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("must end with '?'" in e for e in errors)

    # 4. Question exceeds 160 characters
    long_q = "A" * 161 + "?"
    _write_sample_question(q_file, question=long_q)
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("exceeds 160 characters" in e for e in errors)

    # 5. Duplicate option labels
    _write_sample_question(q_file, options=[("A", "First", "conseq"), ("A", "Duplicate", "conseq")])
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("duplicate option labels" in e for e in errors)

    # 6. open-answer: no with fewer than 2 options
    _write_sample_question(q_file, open_answer="no", options=[("A", "Only one", "conseq")])
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("at least 2 options required when open-answer is 'no'" in e for e in errors)

    # 7. open-answer: yes with 1 option (must be 0 or >= 2)
    _write_sample_question(q_file, open_answer="yes", options=[("A", "Only one", "conseq")], recommended="A")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("options must be empty (pure open question) or have at least 2 options" in e for e in errors)

    # 8. Pure open question (0 options) but recommended != '-'
    _write_sample_question(q_file, open_answer="yes", options=[], recommended="A")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("recommended must be '-' when options are empty" in e for e in errors)

    # 9. >= 2 options with unknown recommended label
    _write_sample_question(q_file, recommended="Z")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("recommended option 'Z' not found in options" in e for e in errors)

    # 10. Option bullet contains (recommended) marker
    bad_bullet_content = te.format_question_content(
        id="Q001",
        title="Sample",
        question="Which one?",
        status="open",
        blocks="T001 (waiting)",
        decider="owner",
        asked_by="owner",
        asked="2026-10-17",
        origin_run="-",
        open_answer="no",
        recommended="A",
        context="Context.",
        options=[("A (recommended)", "First", "safe"), ("B", "Second", "risky")],
    )
    q_file.write_text(bad_bullet_content, encoding="utf-8")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("option bullet contains '(recommended)' marker" in e for e in errors)

    # 11. Answer consistency
    # Open status with choice != '-'
    _write_sample_question(q_file, status="open", choice="A")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("status is 'open' but choice is 'A'" in e for e in errors)

    # Answered status with choice: open but open-answer: no
    _write_sample_question(q_file, status="answered", open_answer="no", choice="open", answered_by="owner", answered="2026-10-17", text="Some text")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("choice is 'open' but open-answer is 'no'" in e for e in errors)

    # Answered status with choice: open but missing text block
    _write_sample_question(q_file, status="answered", open_answer="yes", options=[], recommended="-", choice="open", answered_by="owner", answered="2026-10-17", text=None)
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("choice is 'open' requires a non-empty text block" in e for e in errors)

    # Withdrawn status without reason text
    _write_sample_question(q_file, status="withdrawn", choice="withdrawn", answered_by="owner", answered="2026-10-17", text=None)
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("withdrawn question requires reason in text block" in e for e in errors)

    # 12. Blocks consistency
    # Blocked task does not exist
    _write_sample_question(q_file, blocks="T999 (waiting)")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("blocked task 'T999' not found" in e for e in errors)

    # Blocked task invalid format
    _write_sample_question(q_file, blocks="bad-id (waiting)")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("invalid task ID 'bad-id' in blocks" in e for e in errors)

    # Question is open but task is not waiting
    _write_sample_task(tasks_dir / "features" / "T001-task.md", task_id="T001", category="features", state="in progress", decider="Q001")
    _write_sample_question(q_file, blocks="T001 (in progress)")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("question is 'open' but blocked task 'T001' is in state 'in progress'" in e for e in errors)

    # Question is open but task decider does not reference Q001
    _write_sample_task(tasks_dir / "features" / "T001-task.md", task_id="T001", category="features", state="waiting", decider="-")
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("question is 'open' but task 'T001' decider '-' does not reference Q001" in e for e in errors)

    # 13. Warnings
    # Context not completed warning
    _write_sample_task(tasks_dir / "features" / "T001-task.md", task_id="T001", category="features", state="waiting", decider="Q001")
    _write_sample_question(
        q_file,
        open_answer="yes",
        options=[],
        recommended="-",
        context="Converted from the legacy decider header of T001; context to be completed by the owner.",
        blocks="T001 (waiting)",
    )
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert any("context-not-completed" in w for w in warnings)

    # Legacy decider warning on task
    _write_sample_task(tasks_dir / "features" / "T002-legacy.md", task_id="T002", category="features", state="waiting", decider="owner: Should we do X?")
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("legacy free-text decider 'owner: Should we do X?'" in w for w in warnings)


def test_ask_and_answer_single_file_and_folder_tasks(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"

    # Single-file task
    _write_sample_task(
        tasks_dir / "features" / "T001-single.md",
        task_id="T001",
        category="features",
        state="in progress",
    )
    # Folder task
    folder_task_dir = tasks_dir / "features" / "T002-folder"
    _write_sample_task(
        folder_task_dir / "README.md",
        task_id="T002",
        category="features",
        state="in progress",
    )
    (folder_task_dir / "PROGRESS.md").write_text("# Progress\n\n## Log (newest first)\n\n", encoding="utf-8")

    # 1. Ask on single-file task
    ok_ask1, res_ask1 = te.ask_question(
        tasks_dir,
        question="Which approach for single file?",
        context="Context for T001.",
        options=[("A", "Approach A", "Fast"), ("B", "Approach B", "Thorough")],
        blocks="T001",
    )
    assert ok_ask1 is True
    assert res_ask1["id"] == "Q001"

    t1 = te.parse_emergent_task_file(tasks_dir / "features" / "T001-single.md", tasks_dir)
    assert t1["state"] == "waiting"
    assert t1["decider"] == "Q001"

    q1 = te.parse_question_file(pathlib.Path(res_ask1["file_path"]), tasks_dir)
    assert q1["blocks"] == "T001 (in progress)"

    # 2. Ask on folder task
    ok_ask2, res_ask2 = te.ask_question(
        tasks_dir,
        question="Which approach for folder task?",
        context="Context for T002.",
        options=[("A", "Approach A", "Fast"), ("B", "Approach B", "Thorough")],
        blocks="T002",
    )
    assert ok_ask2 is True
    assert res_ask2["id"] == "Q002"

    t2 = te.parse_emergent_task_file(folder_task_dir / "README.md", tasks_dir)
    assert t2["state"] == "waiting"
    assert t2["decider"] == "Q002"
    prog2 = (folder_task_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "Blocked by question Q002" in prog2

    # Validate tree
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert warnings == []

    # 3. Answer Q001 -> restores single-file task to in progress
    ok_ans1, res_ans1 = te.answer_question(tasks_dir, "Q001", choice="A", text="Use approach A")
    assert ok_ans1 is True
    assert res_ans1["unblocked_tasks"] == ["T001"]

    t1_after = te.parse_emergent_task_file(tasks_dir / "features" / "T001-single.md", tasks_dir)
    assert t1_after["state"] == "in progress"
    assert t1_after["decider"] == "-"

    # 4. Answer Q002 -> restores folder task to in progress
    ok_ans2, res_ans2 = te.answer_question(tasks_dir, "Q002", choice="B")
    assert ok_ans2 is True
    assert res_ans2["unblocked_tasks"] == ["T002"]

    t2_after = te.parse_emergent_task_file(folder_task_dir / "README.md", tasks_dir)
    assert t2_after["state"] == "in progress"
    assert t2_after["decider"] == "-"
    prog2_after = (folder_task_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "Unblocked: question Q002 answered" in prog2_after


def test_two_questions_on_one_task_earliest_prior_state(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="in progress",
    )

    # 1. Ask first question when task is in progress
    ok1, res1 = te.ask_question(
        tasks_dir,
        question="First question on T001?",
        context="Context 1",
        options=[("A", "Opt A", "Conseq A"), ("B", "Opt B", "Conseq B")],
        blocks="T001",
    )
    assert ok1 is True
    assert res1["id"] == "Q001"

    t_mid1 = te.parse_emergent_task_file(tasks_dir / "features" / "T001-task.md", tasks_dir)
    assert t_mid1["state"] == "waiting"
    assert t_mid1["decider"] == "Q001"

    # 2. Ask second question when task is waiting
    ok2, res2 = te.ask_question(
        tasks_dir,
        question="Second question on T001?",
        context="Context 2",
        options=[("A", "Opt A", "Conseq A"), ("B", "Opt B", "Conseq B")],
        blocks="T001",
    )
    assert ok2 is True
    assert res2["id"] == "Q002"

    t_mid2 = te.parse_emergent_task_file(tasks_dir / "features" / "T001-task.md", tasks_dir)
    assert t_mid2["state"] == "waiting"
    assert t_mid2["decider"] == "Q001, Q002"

    q2 = te.parse_question_file(pathlib.Path(res2["file_path"]), tasks_dir)
    assert q2["blocks"] == "T001 (waiting)"

    # Validation clean
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert warnings == []

    # 3. Answer Q001 first: task must remain waiting
    ok_ans1, res_ans1 = te.answer_question(tasks_dir, "Q001", choice="A")
    assert ok_ans1 is True
    assert res_ans1["unblocked_tasks"] == []

    t_after_q1 = te.parse_emergent_task_file(tasks_dir / "features" / "T001-task.md", tasks_dir)
    assert t_after_q1["state"] == "waiting"
    assert "Q002" in t_after_q1["decider"]

    # 4. Answer Q002: now both are resolved -> restores to earliest prior state ('in progress')
    ok_ans2, res_ans2 = te.answer_question(tasks_dir, "Q002", choice="B")
    assert ok_ans2 is True
    assert res_ans2["unblocked_tasks"] == ["T001"]

    t_final = te.parse_emergent_task_file(tasks_dir / "features" / "T001-task.md", tasks_dir)
    assert t_final["state"] == "in progress"
    assert t_final["decider"] == "-"


def test_concurrent_ask_on_same_task(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="in progress",
    )

    results: list[dict[str, Any]] = []
    errors_list: list[Exception] = []

    def worker(q_num: int) -> None:
        try:
            ok, res = te.ask_question(
                tasks_dir,
                question=f"Concurrent question {q_num} on T001?",
                context=f"Context {q_num}",
                options=[("A", "Opt A", "Conseq A"), ("B", "Opt B", "Conseq B")],
                blocks="T001",
            )
            if ok:
                results.append(res)
            else:
                errors_list.append(Exception(res.get("error")))
        except Exception as e:
            errors_list.append(e)

    t1 = threading.Thread(target=worker, args=(1,))
    t2 = threading.Thread(target=worker, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors_list) == 0
    assert len(results) == 2
    ids = {r["id"] for r in results}
    assert len(ids) == 2
    assert "Q001" in ids
    assert "Q002" in ids

    t_task = te.parse_emergent_task_file(tasks_dir / "features" / "T001-task.md", tasks_dir)
    assert t_task["state"] == "waiting"
    assert "Q001" in t_task["decider"]
    assert "Q002" in t_task["decider"]


def test_ask_rollback_on_task_write_failure(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="in progress",
    )
    initial_content = (tasks_dir / "features" / "T001-task.md").read_text(encoding="utf-8")

    # Monkeypatch _update_task_file_headers_and_state to fail
    def failing_update(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Simulated task write failure")

    monkeypatch.setattr(te, "_update_task_file_headers_and_state", failing_update)

    with pytest.raises(RuntimeError, match="Simulated task write failure"):
        te.ask_question(
            tasks_dir,
            question="Will rollback work?",
            context="Rollback context",
            options=[("A", "Yes", "Good"), ("B", "No", "Bad")],
            blocks="T001",
        )

    # 1. Question file must not exist
    q_files = list((tasks_dir / "questions").glob("Q*.md"))
    assert q_files == []

    # 2. Task file must be restored to original content
    restored_content = (tasks_dir / "features" / "T001-task.md").read_text(encoding="utf-8")
    assert restored_content == initial_content


def test_answer_multiline_and_unicode_roundtrip(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="in progress",
    )

    ok, res = te.ask_question(
        tasks_dir,
        question="Can answer contain special formatting?",
        context="Context for unicode & multiline answer.",
        options=[("A", "Option A", "Desc A"), ("B", "Option B", "Desc B")],
        open_answer="yes",
        blocks="T001",
    )
    assert ok is True
    qid = res["id"]

    complex_answer_text = (
        "Heading 1:\n# Section 1\n"
        "Colons: `foo: bar` and `status: active`\n"
        "Pipes: | col1 | col2 |\n"
        "Backticks in text:\n"
        "```python\n"
        "def hello():\n"
        "    return 'world'\n"
        "```\n"
        "Unicode: Hello 🌍! Testing with € and 日本語 text.\n"
    )

    ok_ans, res_ans = te.answer_question(
        tasks_dir,
        qid,
        choice="open",
        text=complex_answer_text,
    )
    assert ok_ans is True

    # Read back and verify exact round-trip
    q_data = te.parse_question_file(pathlib.Path(res["file_path"]), tasks_dir)
    assert q_data["answer"]["choice"] == "open"
    assert q_data["answer"]["text"] == complex_answer_text.strip()

    # Tree validates with 0 errors
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []


def test_withdraw_format_and_unblock(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="in progress",
    )

    ok, res = te.ask_question(
        tasks_dir,
        question="Will this question be withdrawn?",
        context="Context.",
        options=[("A", "Opt A", "Desc A"), ("B", "Opt B", "Desc B")],
        blocks="T001",
    )
    assert ok is True
    qid = res["id"]

    # Withdraw with reason
    reason_text = "Spec changed: question no longer applicable."
    ok_w, res_w = te.withdraw_question(tasks_dir, qid, reason=reason_text)
    assert ok_w is True
    assert res_w["status"] == "withdrawn"
    assert res_w["unblocked_tasks"] == ["T001"]

    q_data = te.parse_question_file(pathlib.Path(res["file_path"]), tasks_dir)
    assert q_data["status"] == "withdrawn"
    assert q_data["answer"]["choice"] == "withdrawn"
    assert q_data["answer"]["text"] == reason_text

    t_task = te.parse_emergent_task_file(tasks_dir / "features" / "T001-task.md", tasks_dir)
    assert t_task["state"] == "in progress"
    assert t_task["decider"] == "-"

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []


def test_from_task_golden_output(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T007-task.md",
        task_id="T007",
        category="features",
        state="waiting",
        decider="owner: Which permission mode should headless Claude runs use by default?",
    )

    res = run_cli("questions", "ask", "--from-task", "T007", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    qid = payload["id"]
    assert qid == "Q001"

    # Verify task decider updated
    t_after = te.parse_emergent_task_file(tasks_dir / "features" / "T007-task.md", tasks_dir)
    assert t_after["state"] == "waiting"
    assert t_after["decider"] == "Q001"

    # Verify pure open question file
    q_file = tasks_dir / payload["rel_path"]
    q_content = q_file.read_text(encoding="utf-8")

    assert "- id: Q001" in q_content
    assert "- question: Which permission mode should headless Claude runs use by default?" in q_content
    assert "- status: open" in q_content
    assert "- blocks: T007 (waiting)" in q_content
    assert "- open-answer: yes" in q_content
    assert "- recommended: -" in q_content
    assert "Converted from the legacy decider header of T007; context to be completed by the owner." in q_content

    # Tree validation: 0 errors, warning is context-not-completed
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert any("context-not-completed" in w for w in warnings)


def test_waiting_invariant_and_force_unblock(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="in progress",
    )

    # Ask question Q001
    ok_ask, res_ask = te.ask_question(
        tasks_dir,
        question="Should we proceed?",
        context="Context.",
        options=[("A", "Yes", "Go"), ("B", "No", "Stop")],
        blocks="T001",
    )
    assert ok_ask is True

    # 1. Normal transition out of waiting is refused
    res_tr1 = run_cli("transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr1.returncode == 1
    p1 = json.loads(res_tr1.stdout)
    assert "Waiting invariant violated" in p1["error"]

    # 2. Transition with --force-unblock but no reason is refused
    res_tr2 = run_cli("transition", "T001", "in progress", "--force-unblock", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr2.returncode == 1
    p2 = json.loads(res_tr2.stdout)
    assert "--force-unblock requires non-empty --reason" in p2["error"]

    # 3. Transition with --force-unblock and --reason succeeds
    res_tr3 = run_cli(
        "transition",
        "T001",
        "in progress",
        "--force-unblock",
        "--reason",
        "Owner decided to bypass question",
        "--tasks-dir",
        str(tasks_dir),
        "--json",
    )
    assert res_tr3.returncode == 0
    p3 = json.loads(res_tr3.stdout)
    assert p3["ok"] is True

    # Task is now in progress with decider: -
    t_after = te.parse_emergent_task_file(tasks_dir / "features" / "T001-task.md", tasks_dir)
    assert t_after["state"] == "in progress"
    assert t_after["decider"] == "-"

    # Question Q001 is withdrawn with reason
    q_after = te.parse_question_file(pathlib.Path(res_ask["file_path"]), tasks_dir)
    assert q_after["status"] == "withdrawn"
    assert q_after["answer"]["choice"] == "withdrawn"
    assert "Owner decided to bypass question" in q_after["answer"]["text"]


def test_decisions_region_sync_index(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "features" / "README.md").write_text("# features\n\nowner-session: s1\n\n## Goal and scope\n\nFeature tasks.\n", encoding="utf-8")

    # T001 is waiting on Q001
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="waiting",
        decider="Q001",
    )
    # T002 is waiting with legacy decider
    _write_sample_task(
        tasks_dir / "features" / "T002-legacy.md",
        task_id="T002",
        category="features",
        state="waiting",
        decider="owner: Legacy decision needed?",
    )

    # Q001 is open
    _write_sample_question(
        tasks_dir / "questions" / "Q001-permission-mode.md",
        qid="Q001",
        question="Which permission mode should we use?",
        blocks="T001 (waiting)",
        recommended="A",
    )

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Next up

<!-- ai-orch:generated next-up -->
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| Key | Question | Blocks | Decider | Recommended |
| --- | --- | --- | --- | --- |
| - | None. | - | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )

    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res_sync.returncode == 0

    idx_text = index_path.read_text(encoding="utf-8")

    # Table header is 5 columns
    assert "| Key | Question | Blocks | Decider | Recommended |" in idx_text

    # Open question Q001 row appears first
    assert "| [Q001](questions/Q001-permission-mode.md) | Which permission mode should we use? | T001 | owner | A |" in idx_text

    # Legacy decider row appears after question rows
    assert "| T002 | Legacy decision needed? | - | owner | - |" in idx_text

    # Position check: Q001 comes before T002 in Decisions waiting
    q001_pos = idx_text.index("[Q001]")
    t002_pos = idx_text.index("| T002 | Legacy decision needed?")
    assert q001_pos < t002_pos

    # Check sync-index --check passes
    res_chk = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--check", "--json")
    assert res_chk.returncode == 0


def test_architect_live_test_case_cli(tmp_path: pathlib.Path) -> None:
    """Architect live test on a disposable tree:
    questions answer Q002 --choice A --text $'Use A.\nBut: keep | pipes and ```backticks``` intact.\n## not a heading'
    1. tasks validate then PASSES (fenced code blocks are opaque, not parsed as sections).
    2. questions show Q002 --json returns the exact original text (round-trip true).
    3. trailing newline semantics: stored text is the given text with a single trailing newline normalized away.
    """
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T000-dummy.md",
        task_id="T000",
        category="features",
        state="waiting",
        decider="Q001",
    )
    _write_sample_question(
        tasks_dir / "questions" / "Q001-dummy.md",
        qid="Q001",
        blocks="T000 (waiting)",
    )

    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="in progress",
    )

    # Ask Q002
    ok_ask, res_ask = te.ask_question(
        tasks_dir,
        question="Which approach should we use?",
        context="Context for Q002.",
        options=[("A", "Approach A", "Fast"), ("B", "Approach B", "Safe")],
        blocks="T001",
    )
    assert ok_ask is True
    assert res_ask["id"] == "Q002"

    raw_architect_input = (
        "Use A.\n"
        "But: keep | pipes and ```backticks``` intact.\n"
        "## not a heading"
    )

    # 1. Answer via CLI
    res_ans = run_cli(
        "questions", "answer", "Q002",
        "--choice", "A",
        "--text", raw_architect_input,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_ans.returncode == 0
    ans_payload = json.loads(res_ans.stdout)
    assert ans_payload["ok"] is True

    # 2. tasks validate passes with 0 errors
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    val_payload = json.loads(res_val.stdout)
    assert val_payload["ok"] is True
    assert val_payload["errors"] == []

    # 3. questions show Q002 --json returns exact original text
    res_show = run_cli(
        "questions", "show", "Q002",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_show.returncode == 0
    show_payload = json.loads(res_show.stdout)
    assert show_payload["ok"] is True
    returned_text = show_payload["question"]["answer"]["text"]
    assert returned_text == raw_architect_input

    # 4. Trailing newline semantics: single trailing newline normalized away
    _write_sample_task(
        tasks_dir / "features" / "T002-task.md",
        task_id="T002",
        category="features",
        state="in progress",
    )
    ok_ask3, res_ask3 = te.ask_question(
        tasks_dir,
        question="Question with trailing newline?",
        context="Context for Q003.",
        options=[("A", "Option A", "Desc A"), ("B", "Option B", "Desc B")],
        blocks="T002",
    )
    assert ok_ask3 is True
    qid3 = res_ask3["id"]

    input_with_trailing_nl = "Answer text with single trailing newline.\n"
    res_ans3 = run_cli(
        "questions", "answer", qid3,
        "--choice", "A",
        "--text", input_with_trailing_nl,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_ans3.returncode == 0

    res_val3 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val3.returncode == 0

    res_show3 = run_cli(
        "questions", "show", qid3,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_show3.returncode == 0
    show_payload3 = json.loads(res_show3.stdout)
    # Stored text is the given text with a single trailing newline normalized away
    assert show_payload3["question"]["answer"]["text"] == te.normalize_fenced_text(input_with_trailing_nl)
    assert show_payload3["question"]["answer"]["text"] == "Answer text with single trailing newline."


def test_task_readme_with_fenced_code_containing_heading_validates(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    folder_task_dir = tasks_dir / "features" / "T001-deploy"
    folder_task_dir.mkdir(parents=True)
    readme_path = folder_task_dir / "README.md"
    readme_content = """# T001 Deploy step

- id: T001
- title: Deploy step
- category: features
- priority: P1
- priority-reason: core feature
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: test

## Goal

Deploy correctly.

## Steps

Run:
```bash
## not a section
echo "deploying"
```

## Verification

Test output.
"""
    readme_path.write_text(readme_content, encoding="utf-8")

    t = te.parse_emergent_task_file(readme_path, tasks_dir)
    assert t["sections_present"] == ["## Goal", "## Steps", "## Verification"]

    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    val_payload = json.loads(res_val.stdout)
    assert val_payload["ok"] is True
    assert val_payload["errors"] == []

    # If ## Verification is missing outside the code block (only inside ```bash), validation must fail
    broken_readme = """# T001 Deploy step

- id: T001
- title: Deploy step
- category: features
- priority: P1
- priority-reason: core feature
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: test

## Goal

Deploy correctly.

## Steps

Run:
```bash
## Verification
echo "fake verification inside code block"
```
"""
    readme_path.write_text(broken_readme, encoding="utf-8")
    t_broken = te.parse_emergent_task_file(readme_path, tasks_dir)
    assert t_broken["sections_present"] == ["## Goal", "## Steps"]

    res_val2 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val2.returncode == 1
    val_payload2 = json.loads(res_val2.stdout)
    assert val_payload2["ok"] is False
    assert any("missing required Markdown section(s): ## Verification" in e for e in val_payload2["errors"])


def test_tilde_fences_parsing_and_validation(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    folder_task_dir = tasks_dir / "features" / "T001-tilde"
    folder_task_dir.mkdir(parents=True)
    readme_path = folder_task_dir / "README.md"
    readme_content = """# T001 Tilde task

- id: T001
- title: Tilde task
- category: features
- priority: P2
- priority-reason: testing
- next-up: no
- state: waiting
- executor: kilo
- depends-on: -
- decider: Q001
- sources: -
- paths: -
- handoff: test

## Goal

Goal with tildes.

## Steps

~~~bash
## not a section
echo 1
~~~

## Verification

Verified.
"""
    readme_path.write_text(readme_content, encoding="utf-8")

    # Write a question with tilde fence in answer
    q_file = tasks_dir / "questions" / "Q001-tilde-question.md"
    q_file.parent.mkdir(parents=True, exist_ok=True)
    q_content = """# Q001 Tilde question

- id: Q001
- question: Should we support tilde fences?
- status: answered
- blocks: T001 (waiting)
- decider: owner
- asked-by: kilo
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: -

## Context

Testing tilde fences.

## Options

- **A** — Yes: support tildes
- **B** — No: only backticks

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17

~~~text
Use A.
Inside tildes: ```nested backticks```
## not a heading
~~~
"""
    q_file.write_text(q_content, encoding="utf-8")

    q_data = te.parse_question_file(q_file, tasks_dir)
    assert q_data["sections_present"] == ["## Context", "## Options", "## Answer"]
    assert q_data["answer"]["choice"] == "A"
    assert q_data["answer"]["text"] == "Use A.\nInside tildes: ```nested backticks```\n## not a heading"

    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    assert json.loads(res_val.stdout)["ok"] is True


def test_nested_shorter_fence_inside_longer_one(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="waiting",
        decider="Q001",
    )

    q_file = tasks_dir / "questions" / "Q001-nested-fence.md"
    q_file.parent.mkdir(parents=True, exist_ok=True)
    q_content = """# Q001 Nested fence

- id: Q001
- question: How to format nested code?
- status: answered
- blocks: T001 (waiting)
- decider: owner
- asked-by: kilo
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: -

## Context

Context text.

## Options

- **A** — Longer outer fence
- **B** — Escaping

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17

````text
Outer 4-backtick fence:
```bash
echo "inner 3-backtick fence"
## not a heading inside inner
```
- not a bullet
## not a heading outside inner but inside outer
````
"""
    q_file.write_text(q_content, encoding="utf-8")

    q_data = te.parse_question_file(q_file, tasks_dir)
    assert q_data["sections_present"] == ["## Context", "## Options", "## Answer"]
    expected_inner_text = (
        "Outer 4-backtick fence:\n"
        "```bash\n"
        "echo \"inner 3-backtick fence\"\n"
        "## not a heading inside inner\n"
        "```\n"
        "- not a bullet\n"
        "## not a heading outside inner but inside outer"
    )
    assert q_data["answer"]["text"] == expected_inner_text

    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    assert json.loads(res_val.stdout)["ok"] is True


def test_unclosed_fence_behavior(tmp_path: pathlib.Path) -> None:
    # 1. Direct scanner test
    text = "Line 1\n```text\nLine 2 inside unclosed\n## not a heading\nLine 3"
    lines, blocks = te.scan_markdown_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].closed is False
    assert blocks[0].content == "Line 2 inside unclosed\n## not a heading\nLine 3"
    assert lines[0].is_fenced is False
    assert all(l.is_fenced for l in lines[1:])

    # 2. In question file: unclosed fence in ## Answer runs to EOF
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="waiting",
        decider="Q001",
    )
    q_file = tasks_dir / "questions" / "Q001-unclosed.md"
    q_file.parent.mkdir(parents=True, exist_ok=True)
    q_content = """# Q001 Unclosed fence

- id: Q001
- question: What happens if unclosed?
- status: answered
- blocks: T001 (waiting)
- decider: owner
- asked-by: kilo
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: -

## Context

Context.

## Options

- **A** — Choice A
- **B** — Choice B

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17

```text
Unclosed fence content
Line 2
## not a heading
"""
    q_file.write_text(q_content, encoding="utf-8")

    q_data = te.parse_question_file(q_file, tasks_dir)
    assert q_data["sections_present"] == ["## Context", "## Options", "## Answer"]
    assert q_data["answer"]["text"] == "Unclosed fence content\nLine 2\n## not a heading"

    # 3. In task file: unclosed fence in ## Steps swallows ## Verification, causing validation to fail
    task_file = tasks_dir / "features" / "T002-unclosed.md"
    task_content = """# T002 Task with unclosed fence

- id: T002
- title: Task with unclosed fence
- category: features
- priority: P2
- priority-reason: test
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: test

## Goal

Goal text.

## Steps

```bash
echo "unclosed code block"
## Verification
echo "fake verification inside unclosed fence"
"""
    task_file.write_text(task_content, encoding="utf-8")
    t2 = te.parse_emergent_task_file(task_file, tasks_dir)
    assert t2["sections_present"] == ["## Goal", "## Steps"]


def test_question_context_and_options_with_fenced_code(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(
        tasks_dir / "features" / "T001-task.md",
        task_id="T001",
        category="features",
        state="waiting",
        decider="Q001",
    )
    q_file = tasks_dir / "questions" / "Q001-ctx-code.md"
    q_file.parent.mkdir(parents=True, exist_ok=True)
    q_content = """# Q001 Code in context and options

- id: Q001
- question: How to handle code in context?
- status: open
- blocks: T001 (waiting)
- decider: owner
- asked-by: kilo
- asked: 2026-10-17
- origin-run: -
- open-answer: no
- recommended: A

## Context

Here is the code block with a heading:
```python
## not a section
def solve():
    return 42
```
End of context.

## Options

- **A** — Option A: `use code` | pipeline
- **B** — Option B: ignore

## Answer

- choice: -
- answered-by: -
- answered: -
"""
    q_file.write_text(q_content, encoding="utf-8")

    q_data = te.parse_question_file(q_file, tasks_dir)
    assert q_data["sections_present"] == ["## Context", "## Options", "## Answer"]
    assert "## not a section" in q_data["context"]
    assert len(q_data["options"]) == 2
    assert q_data["options"][0]["label"] == "A"
    assert q_data["options"][0]["consequence"] == "`use code` | pipeline"

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []


def test_questions_ask_with_no_blocked_task(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")
    res = run_cli(
        "questions", "ask", "--tasks-dir", str(tasks_dir),
        "--question", "Which default should we use?", "--context", "Some context.",
        "--option", "A=One: first", "--option", "B=Two: second",
        "--recommended", "A", "--open-answer", "no", "--blocks", "-", "--json",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    qfile = next((tasks_dir / "questions").glob("Q001-*.md"))
    assert "- blocks: -\n" in qfile.read_text(encoding="utf-8")
    val = run_cli("validate", "--tasks-dir", str(tasks_dir))
    assert val.returncode == 0, val.stdout + val.stderr


def test_questions_ask_against_blocked_task(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # 1. Create a task in blocked state
    task_file = tasks_dir / "features" / "T042-blocked-feature.md"
    _write_sample_task(task_file, task_id="T042", state="blocked")

    # 2. Ask a question blocking T042
    res_ask = run_cli(
        "questions", "ask",
        "--tasks-dir", str(tasks_dir),
        "--question", "How should we resolve this blocker?",
        "--context", "External dependency is missing, need architecture decision.",
        "--open-answer", "yes",
        "--blocks", "T042",
        "--json",
    )
    assert res_ask.returncode == 0
    payload_ask = json.loads(res_ask.stdout)
    assert payload_ask["ok"] is True
    qid = payload_ask["id"]

    # Verify task transitioned from blocked -> waiting
    task_text = task_file.read_text(encoding="utf-8")
    assert "- state: waiting\n" in task_text
    assert f"- decider: {qid}\n" in task_text

    # Verify question file recorded blocks: T042 (blocked)
    q_file = tasks_dir / "questions" / f"{qid}-how-should-we-resolve-this-blocker.md"
    assert f"- blocks: T042 (blocked)\n" in q_file.read_text(encoding="utf-8")

    # 3. Answer question
    res_ans = run_cli(
        "questions", "answer",
        qid,
        "--choice", "open",
        "--text", "Decision made: use internal fallback.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_ans.returncode == 0

    # Verify task unblocked to open
    updated_task = task_file.read_text(encoding="utf-8")
    assert "- state: open\n" in updated_task
    assert "- decider: -\n" in updated_task


# ---------------------------------------------------------------------------
# Inbox Notes & Tasks New From Note Tests
# ---------------------------------------------------------------------------

def _create_test_png(width: int = 2, height: int = 2) -> bytes:
    """Create a minimal valid PNG using Python stdlib (zlib, struct)."""
    import struct
    import zlib

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    ihdr_chunk = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + ihdr_crc

    raw = b"\x00\xff\x00\x00\xff\x00\xff\x00\xff" + b"\x00\x00\x00\xff\xff\xff\xff\xff\xff"
    compressed = zlib.compress(raw)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed))
    idat_chunk = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc

    iend_crc = struct.pack(">I", zlib.crc32(b"IEND"))
    iend_chunk = struct.pack(">I", 0) + b"IEND" + iend_crc
    return sig + ihdr_chunk + idat_chunk + iend_chunk


def test_inbox_add_show_list_roundtrip(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Add note
    res_add = run_cli(
        "inbox", "add",
        "--title", "Login defect on Safari",
        "--kind", "bug",
        "--body", "User cannot log in on Safari 17.\nToken is rejected.",
        "--about", "src/auth/login.py",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0, res_add.stdout + res_add.stderr
    data_add = json.loads(res_add.stdout)
    assert data_add["ok"] is True
    assert data_add["id"] == "N001"
    assert (tasks_dir / "_inbox" / "to-analyze" / data_add["folder"] / "note.md").is_file()

    # 2. Show note
    res_show = run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_show.returncode == 0, res_show.stdout + res_show.stderr
    data_show = json.loads(res_show.stdout)
    assert data_show["ok"] is True
    note = data_show["note"]
    assert note["id"] == "N001"
    assert note["title"] == "Login defect on Safari"
    assert note["kind"] == "bug"
    assert note["status"] == "draft"
    assert note["about"] == "src/auth/login.py"
    assert "User cannot log in on Safari 17." in note["body"]
    assert note["attachments"] == []
    assert note["bundle_sha256"] != ""

    # Show text mode
    res_show_text = run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir))
    assert res_show_text.returncode == 0
    assert "Note: N001 (draft)" in res_show_text.stdout

    # 3. List notes
    res_list = run_cli("inbox", "list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list.returncode == 0
    data_list = json.loads(res_list.stdout)
    assert len(data_list["notes"]) == 1
    assert data_list["notes"][0]["id"] == "N001"

    # Add second note with ready status
    res_add2 = run_cli(
        "inbox", "add",
        "--title", "Idea for caching",
        "--kind", "idea",
        "--status", "ready",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add2.returncode == 0
    data_add2 = json.loads(res_add2.stdout)
    assert data_add2["id"] == "N002"

    # List filtered by status
    res_list_ready = run_cli("inbox", "list", "--status", "ready", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list_ready.returncode == 0
    data_ready = json.loads(res_list_ready.stdout)
    assert len(data_ready["notes"]) == 1
    assert data_ready["notes"][0]["id"] == "N002"


def test_inbox_edit_roundtrip_and_expect_hash(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Add note
    res_add = run_cli(
        "inbox", "add",
        "--title", "Draft Note",
        "--kind", "note",
        "--body", "Initial body text",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0
    initial_hash = json.loads(res_add.stdout)["bundle_sha256"]

    # Refuse edit with stale expect-hash
    res_stale = run_cli(
        "inbox", "edit", "N001",
        "--title", "Updated Title",
        "--expect-hash", "bad0000000000000000000000000000000000000000000000000000000000000",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_stale.returncode != 0
    data_stale = json.loads(res_stale.stdout)
    assert data_stale["ok"] is False
    assert data_stale["error"] == "stale-note"

    # Edit with matching expect-hash
    res_edit = run_cli(
        "inbox", "edit", "N001",
        "--title", "Updated Title",
        "--body", "Updated body text",
        "--status", "ready",
        "--expect-hash", initial_hash,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_edit.returncode == 0
    data_edit = json.loads(res_edit.stdout)
    assert data_edit["ok"] is True
    assert data_edit["status"] == "ready"
    assert data_edit["bundle_sha256"] != initial_hash

    # Verify updated content
    show = json.loads(run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert show["title"] == "Updated Title"
    assert show["body"] == "Updated body text"
    assert show["status"] == "ready"

    # Test processing status blocks edits
    note_file = pathlib.Path(show["file_path"])
    note_content = note_file.read_text(encoding="utf-8").replace("- status: ready", "- status: processing")
    note_file.write_text(note_content, encoding="utf-8")

    res_proc_edit = run_cli(
        "inbox", "edit", "N001",
        "--title", "Cannot Edit While Processing",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_proc_edit.returncode != 0
    data_proc = json.loads(res_proc_edit.stdout)
    assert data_proc["error"] == "locked-processing"


def test_inbox_attach_and_detach_and_limits(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Add note
    res_add = run_cli("inbox", "add", "--title", "Note with images", "--tasks-dir", str(tasks_dir), "--json")
    assert res_add.returncode == 0

    png_bytes = _create_test_png(2, 2)
    valid_png_path = tmp_path / "screenshot.png"
    valid_png_path.write_bytes(png_bytes)

    # 1. Attach valid PNG
    res_att = run_cli("inbox", "attach", "N001", "--file", str(valid_png_path), "--tasks-dir", str(tasks_dir), "--json")
    assert res_att.returncode == 0, res_att.stdout + res_att.stderr
    data_att = json.loads(res_att.stdout)
    assert data_att["ok"] is True
    assert data_att["attachment"] == "01-screenshot.png"
    assert data_att["markdown"] == "![](attachments/01-screenshot.png)"

    # Check show reports attachment
    show1 = json.loads(run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert show1["attachments"] == ["01-screenshot.png"]
    assert show1["attachment_details"] == [{"name": "01-screenshot.png", "class": "image", "size": len(png_bytes)}]

    # 2. Refuse invalid image magic bytes (e.g. text file named fake.png)
    fake_png = tmp_path / "fake.png"
    fake_png.write_text("Not a png at all, just plain text", encoding="utf-8")
    res_fake = run_cli("inbox", "attach", "N001", "--file", str(fake_png), "--tasks-dir", str(tasks_dir), "--json")
    assert res_fake.returncode != 0
    assert json.loads(res_fake.stdout)["error"] == "invalid-image-type"

    # 3. Refuse > 10 MB attachment
    oversized = tmp_path / "huge.png"
    with open(oversized, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.seek(10 * 1024 * 1024 + 50)
        f.write(b"\x00")
    res_huge = run_cli("inbox", "attach", "N001", "--file", str(oversized), "--tasks-dir", str(tasks_dir), "--json")
    assert res_huge.returncode != 0
    assert json.loads(res_huge.stdout)["error"] == "size-limit-exceeded"

    # 4. Attach up to 30 images
    for i in range(2, 31):
        fpath = tmp_path / f"img_{i}.png"
        fpath.write_bytes(png_bytes)
        res_i = run_cli("inbox", "attach", "N001", "--file", str(fpath), "--tasks-dir", str(tasks_dir), "--json")
        assert res_i.returncode == 0

    show30 = json.loads(run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert len(show30["attachments"]) == 30

    # 5. 31st attachment is refused
    fpath31 = tmp_path / "img_31.png"
    fpath31.write_bytes(png_bytes)
    res_31 = run_cli("inbox", "attach", "N001", "--file", str(fpath31), "--tasks-dir", str(tasks_dir), "--json")
    assert res_31.returncode != 0
    assert json.loads(res_31.stdout)["error"] == "attachment-limit-reached"

    # 6. Detach path traversal refused
    res_trav = run_cli("inbox", "detach", "N001", "--name", "../screenshot.png", "--tasks-dir", str(tasks_dir), "--json")
    assert res_trav.returncode != 0

    res_trav2 = run_cli("inbox", "detach", "N001", "--name", "..", "--tasks-dir", str(tasks_dir), "--json")
    assert res_trav2.returncode != 0

    # 7. Detach valid file
    res_det = run_cli("inbox", "detach", "N001", "--name", "01-screenshot.png", "--tasks-dir", str(tasks_dir), "--json")
    assert res_det.returncode == 0
    assert json.loads(res_det.stdout)["ok"] is True

    show_after_det = json.loads(run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert "01-screenshot.png" not in show_after_det["attachments"]
    assert len(show_after_det["attachments"]) == 29


def test_inbox_resolve_discard_reopen_lifecycle(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Add note
    res_add = run_cli(
        "inbox", "add",
        "--title", "Performance bug",
        "--kind", "bug",
        "--body", "Slow query on database",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0

    # 1. Resolve note
    res_res = run_cli(
        "inbox", "resolve", "N001",
        "--produced", "T010, T011",
        "--by", "owner",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_res.returncode == 0, res_res.stdout + res_res.stderr
    data_res = json.loads(res_res.stdout)
    assert data_res["ok"] is True
    assert data_res["status"] == "processed"

    # Note folder has moved to analyzed/
    assert not (tasks_dir / "_inbox" / "to-analyze" / data_res["folder"]).exists()
    assert (tasks_dir / "_inbox" / "analyzed" / data_res["folder"]).exists()

    show_proc = json.loads(run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert show_proc["status"] == "processed"
    assert show_proc["produced"] == "T010, T011"
    assert show_proc["processed_by"] == "owner"

    # Edit on processed note is refused
    res_closed_edit = run_cli("inbox", "edit", "N001", "--title", "New Title", "--tasks-dir", str(tasks_dir), "--json")
    assert res_closed_edit.returncode != 0
    assert json.loads(res_closed_edit.stdout)["error"] == "note-closed"

    # 2. Reopen note
    res_reop = run_cli("inbox", "reopen", "N001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_reop.returncode == 0
    data_reop = json.loads(res_reop.stdout)
    assert data_reop["status"] == "ready"

    # Moved back to to-analyze
    assert (tasks_dir / "_inbox" / "to-analyze" / data_res["folder"]).exists()
    assert not (tasks_dir / "_inbox" / "analyzed" / data_res["folder"]).exists()

    # 3. Discard note
    res_disc = run_cli(
        "inbox", "discard", "N001",
        "--reason", "Duplicate report",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_disc.returncode == 0
    data_disc = json.loads(res_disc.stdout)
    assert data_disc["status"] == "discarded"
    assert (tasks_dir / "_inbox" / "analyzed" / data_res["folder"]).exists()

    show_disc = json.loads(run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert show_disc["status"] == "discarded"
    assert "Duplicate report" in show_disc["body"]

    # Reopen discarded note
    res_reop2 = run_cli("inbox", "reopen", "N001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_reop2.returncode == 0
    assert (tasks_dir / "_inbox" / "to-analyze" / data_res["folder"]).exists()


def test_inbox_concurrent_add_distinct_ids(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    results: list[dict[str, Any]] = []
    errors: list[Exception] = []

    def worker(idx: int) -> None:
        try:
            ok, res = te.inbox_add(
                tasks_dir=tasks_dir,
                title=f"Concurrent note {idx}",
                kind="idea",
                body=f"Body for note {idx}",
            )
            if ok:
                results.append(res)
            else:
                errors.append(Exception(res.get("error")))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(results) == 5
    ids = {r["id"] for r in results}
    assert len(ids) == 5
    assert ids == {"N001", "N002", "N003", "N004", "N005"}


def test_legacy_notes_listed_and_converted_on_edit(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "_inbox" / "to-analyze").mkdir(parents=True)
    (tasks_dir / "_inbox" / "analyzed").mkdir(parents=True)

    legacy_to_analyze = tasks_dir / "_inbox" / "to-analyze" / "2026-07-20-call-luca.md"
    legacy_to_analyze.write_text("# Call with Luca\n\nNeed to support OAuth2.\n", encoding="utf-8")

    legacy_analyzed = tasks_dir / "_inbox" / "analyzed" / "old-call.md"
    legacy_analyzed.write_text("# Old Call\n\nResolved discussion.\n", encoding="utf-8")

    # List notes: both listed with legacy: True, id: "-"
    notes = json.loads(run_cli("inbox", "list", "--tasks-dir", str(tasks_dir), "--json").stdout)["notes"]
    assert len(notes) == 2
    for n in notes:
        assert n["legacy"] is True
        assert n["id"] == "-"

    # Show legacy note by filename
    show_legacy = json.loads(run_cli("inbox", "show", "2026-07-20-call-luca.md", "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert show_legacy["title"] == "Call with Luca"
    assert "Need to support OAuth2." in show_legacy["body"]

    # Edit legacy note: converts it to folder form with an allocated id
    res_edit = run_cli(
        "inbox", "edit", "2026-07-20-call-luca.md",
        "--title", "Call with Luca - Auth",
        "--status", "ready",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_edit.returncode == 0, res_edit.stdout + res_edit.stderr
    data_edit = json.loads(res_edit.stdout)
    assert data_edit["ok"] is True
    allocated_id = data_edit["id"]
    assert allocated_id == "N001"

    # Original plain .md is gone, folder exists
    assert not legacy_to_analyze.exists()
    folder_note = tasks_dir / data_edit["rel_path"]
    assert folder_note.is_file()

    # Show newly converted note
    show_converted = json.loads(run_cli("inbox", "show", "N001", "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert show_converted["legacy"] is False
    assert show_converted["id"] == "N001"
    assert show_converted["title"] == "Call with Luca - Auth"
    assert show_converted["status"] == "ready"


def test_tasks_new_from_note(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Add note
    res_add = run_cli(
        "inbox", "add",
        "--title", "JWT rotation and session refresh",
        "--kind", "request",
        "--body", "Implement JWT token rotation for increased security.\n\nTokens should expire after 15 minutes and refresh automatically.",
        "--about", "src/auth/tokens.py, src/auth/session.py",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0
    note_id = json.loads(res_add.stdout)["id"]

    # 2. Create task from note
    res_new = run_cli(
        "new",
        "--from-note", note_id,
        "--category", "features",
        "--title", "JWT token rotation",
        "--priority", "P1",
        "--priority-reason", "Security compliance requirement",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new.returncode == 0, res_new.stdout + res_new.stderr
    data_new = json.loads(res_new.stdout)
    assert data_new["ok"] is True
    assert data_new["id"] == "T001"
    assert data_new["sources"].startswith("_inbox/to-analyze/")
    assert data_new["paths"] == "src/auth/tokens.py, src/auth/session.py"

    # 3. Verify task content on disk
    task_file = tasks_dir / data_new["rel_path"]
    assert task_file.is_file()
    task_data = te.parse_emergent_task_file(task_file, tasks_dir)
    assert task_data["id"] == "T001"
    assert task_data["title"] == "JWT token rotation"
    assert task_data["category"] == "features"
    assert task_data["priority"] == "P1"
    assert task_data["priority_reason"] == "Security compliance requirement"
    assert task_data["state"] == "open"
    assert task_data["sources"] == data_new["sources"]
    assert task_data["paths"] == "src/auth/tokens.py, src/auth/session.py"

    # Goal extracted from first paragraph of note body
    assert "Implement JWT token rotation for increased security." in task_file.read_text(encoding="utf-8")

    # 4. tasks validate passes
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0, res_val.stdout + res_val.stderr
    val_data = json.loads(res_val.stdout)
    assert val_data["ok"] is True

    # 5. Note is NOT resolved (still in to-analyze, status draft)
    note_after = json.loads(run_cli("inbox", "show", note_id, "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert note_after["status"] == "draft"
    assert note_after["in_analyzed"] is False


def test_ai_orch_inbox_and_tasks_new_integration(tmp_path: pathlib.Path) -> None:
    ai_orch_bin = REPO_ROOT / "bin" / "ai-orch"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Add note via ai-orch inbox add
    res_add = subprocess.run(
        [sys.executable, str(ai_orch_bin), "inbox", "add", "--title", "CLI Note", "--tasks-dir", str(tasks_dir), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_add.returncode == 0, res_add.stdout + res_add.stderr
    note_id = json.loads(res_add.stdout)["id"]

    # tasks new via ai-orch tasks new
    res_new = subprocess.run(
        [
            sys.executable, str(ai_orch_bin), "tasks", "new",
            "--from-note", note_id,
            "--category", "features",
            "--title", "Task from CLI",
            "--tasks-dir", str(tasks_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert res_new.returncode == 0, res_new.stdout + res_new.stderr
    assert json.loads(res_new.stdout)["id"] == "T001"


def test_inbox_moves_rewrite_task_sources_lifecycle(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Add note N001
    res_add = run_cli(
        "inbox", "add",
        "--title", "Auth token rotation",
        "--kind", "idea",
        "--body", "Implement auth token rotation.\n\nMore details here.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0
    note_id = json.loads(res_add.stdout)["id"]

    # 2. Create task T001 from note
    res_new = run_cli(
        "new",
        "--from-note", note_id,
        "--category", "features",
        "--title", "Auth token rotation",
        "--priority", "P1",
        "--priority-reason", "Security compliance requirement",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new.returncode == 0, res_new.stdout + res_new.stderr
    t1_data = json.loads(res_new.stdout)
    assert t1_data["sources"].startswith("_inbox/to-analyze/")
    assert (tasks_dir / t1_data["sources"]).is_file()

    # 3. Resolve note -> task sources points to analyzed/ and tasks validate ok
    res_res = run_cli(
        "inbox", "resolve", note_id,
        "--produced", "T001",
        "--by", "owner",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_res.returncode == 0, res_res.stdout + res_res.stderr
    res_data = json.loads(res_res.stdout)
    assert res_data["ok"] is True
    assert res_data["sources_updated"] == ["T001"]

    task_file = tasks_dir / t1_data["rel_path"]
    parsed_t1 = te.parse_emergent_task_file(task_file, tasks_dir)
    assert parsed_t1["sources"].startswith("_inbox/analyzed/")
    assert parsed_t1["sources"].endswith("/note.md")
    assert (tasks_dir / parsed_t1["sources"]).is_file()

    # tasks validate ok
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0, res_val.stdout + res_val.stderr
    assert json.loads(res_val.stdout)["ok"] is True

    # 4. Reopen note -> moves back to to-analyze/ and task sources updated back
    res_reop = run_cli(
        "inbox", "reopen", note_id,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_reop.returncode == 0, res_reop.stdout + res_reop.stderr
    reop_data = json.loads(res_reop.stdout)
    assert reop_data["ok"] is True
    assert reop_data["sources_updated"] == ["T001"]

    parsed_t1_reop = te.parse_emergent_task_file(task_file, tasks_dir)
    assert parsed_t1_reop["sources"].startswith("_inbox/to-analyze/")
    assert (tasks_dir / parsed_t1_reop["sources"]).is_file()

    res_val2 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val2.returncode == 0, res_val2.stdout + res_val2.stderr
    assert json.loads(res_val2.stdout)["ok"] is True

    # 5. Discard path -> moves to analyzed/ and task sources updated
    res_disc = run_cli(
        "inbox", "discard", note_id,
        "--reason", "Superseded by alternate design",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_disc.returncode == 0, res_disc.stdout + res_disc.stderr
    disc_data = json.loads(res_disc.stdout)
    assert disc_data["ok"] is True
    assert disc_data["sources_updated"] == ["T001"]

    parsed_t1_disc = te.parse_emergent_task_file(task_file, tasks_dir)
    assert parsed_t1_disc["sources"].startswith("_inbox/analyzed/")
    assert (tasks_dir / parsed_t1_disc["sources"]).is_file()

    res_val3 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val3.returncode == 0, res_val3.stdout + res_val3.stderr
    assert json.loads(res_val3.stdout)["ok"] is True


def test_inbox_resolve_updates_task_in_done(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Add note N001
    res_add = run_cli(
        "inbox", "add",
        "--title", "Archived Feature",
        "--body", "Description of archived feature.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0
    note_id = json.loads(res_add.stdout)["id"]

    # 2. Create task T001
    res_new = run_cli(
        "new",
        "--from-note", note_id,
        "--category", "features",
        "--title", "Archived Feature",
        "--priority", "P2",
        "--priority-reason", "Historical task",
        "--step", "Implement archived feature",
        "--verification", "pytest tests/test_archived.py",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new.returncode == 0
    t1_data = json.loads(res_new.stdout)
    assert t1_data["sources"].startswith("_inbox/to-analyze/")

    # 3. Transition T001 to done (open -> in progress -> delivered -> verified -> done)
    run_cli("transition", "T001", "in progress", "--actor", "kilo", "--tasks-dir", str(tasks_dir), "--json")
    run_cli("transition", "T001", "delivered", "--actor", "kilo", "--tasks-dir", str(tasks_dir), "--json")
    run_cli("transition", "T001", "verified", "--actor", "owner", "--verifier", "owner", "--tasks-dir", str(tasks_dir), "--json")
    res_done = run_cli("transition", "T001", "done", "--actor", "owner", "--tasks-dir", str(tasks_dir), "--json")
    assert res_done.returncode == 0
    done_data = json.loads(res_done.stdout)
    assert done_data["rel_path"].startswith("done/")

    done_task_file = tasks_dir / done_data["rel_path"]
    assert done_task_file.is_file()

    # 4. Resolve note N001 -> task in done/ must be updated
    res_res = run_cli(
        "inbox", "resolve", note_id,
        "--produced", "T001",
        "--by", "owner",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_res.returncode == 0, res_res.stdout + res_res.stderr
    res_data = json.loads(res_res.stdout)
    assert "T001" in res_data["sources_updated"]

    parsed_done = te.parse_emergent_task_file(done_task_file, tasks_dir, in_done=True)
    assert parsed_done["sources"].startswith("_inbox/analyzed/")
    assert (tasks_dir / parsed_done["sources"]).is_file()

    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0, res_val.stdout + res_val.stderr
    assert json.loads(res_val.stdout)["ok"] is True


def test_inbox_resolve_rollback_on_failure(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Add note N001
    res_add = run_cli(
        "inbox", "add",
        "--title", "Rollback note",
        "--body", "Testing atomic rollback.\n\nBody paragraph.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0
    note_id = json.loads(res_add.stdout)["id"]
    note_folder_name = json.loads(res_add.stdout)["folder"]

    # 2. Create tasks T001 and T002
    res_t1 = run_cli(
        "new",
        "--from-note", note_id,
        "--category", "features",
        "--title", "Task one",
        "--priority", "P1",
        "--priority-reason", "Reason 1",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_t1.returncode == 0
    t1_rel = json.loads(res_t1.stdout)["rel_path"]

    res_t2 = run_cli(
        "new",
        "--from-note", note_id,
        "--category", "features",
        "--title", "Task two",
        "--priority", "P2",
        "--priority-reason", "Reason 2",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_t2.returncode == 0
    t2_rel = json.loads(res_t2.stdout)["rel_path"]

    t1_file = tasks_dir / t1_rel
    t2_file = tasks_dir / t2_rel
    orig_t1_content = t1_file.read_text(encoding="utf-8")
    orig_t2_content = t2_file.read_text(encoding="utf-8")
    orig_note_file = tasks_dir / "_inbox" / "to-analyze" / note_folder_name / "note.md"
    orig_note_content = orig_note_file.read_text(encoding="utf-8")

    # 3. Monkeypatch _atomic_write_text to fail when writing T002
    orig_atomic_write = te._atomic_write_text

    def failing_write(path: pathlib.Path, content: str, encoding: str = "utf-8") -> None:
        if "T002" in str(path):
            raise OSError("Simulated disk error while writing T002")
        orig_atomic_write(path, content, encoding=encoding)

    monkeypatch.setattr(te, "_atomic_write_text", failing_write)

    # 4. Resolve should fail
    ok, res = te.inbox_resolve(tasks_dir, note_id, produced="T001, T002")
    assert ok is False
    assert "Simulated disk error" in res["error"]

    # 5. Verify complete rollback
    # Note folder must be back in to-analyze/ and NOT in analyzed/
    assert (tasks_dir / "_inbox" / "to-analyze" / note_folder_name / "note.md").is_file()
    assert not (tasks_dir / "_inbox" / "analyzed" / note_folder_name).exists()
    assert orig_note_file.read_text(encoding="utf-8") == orig_note_content

    # T001 must have been rolled back to original content
    assert t1_file.read_text(encoding="utf-8") == orig_t1_content
    assert t2_file.read_text(encoding="utf-8") == orig_t2_content

    parsed_t1 = te.parse_emergent_task_file(t1_file, tasks_dir)
    assert parsed_t1["sources"].startswith("_inbox/to-analyze/")

    # 6. Also test rollback when os.replace fails
    def failing_replace(src, dst):
        raise OSError("Simulated os.replace failure")

    monkeypatch.setattr(os, "replace", failing_replace)
    monkeypatch.undo()  # restore _atomic_write_text
    monkeypatch.setattr(os, "replace", failing_replace)

    ok_replace, res_replace = te.inbox_resolve(tasks_dir, note_id, produced="T001, T002")
    assert ok_replace is False
    assert (tasks_dir / "_inbox" / "to-analyze" / note_folder_name / "note.md").is_file()
    assert not (tasks_dir / "_inbox" / "analyzed" / note_folder_name).exists()
    assert orig_note_file.read_text(encoding="utf-8") == orig_note_content




def test_plan_format_warnings_flag_non_canonical_task_items(tmp_path: pathlib.Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(
        "# Plan\n\n## Tasks\n\n"
        "### 05.1 - Canonical task\n"
        "### 05.1b - Canonical task with letter suffix\n"
        "### 05.12 - Canonical two-digit task\n"
        "### 05.2 Missing separator\n"
        "### 05.3 Also missing separator\n"
        "- **T1 — Bullet task**: text\n"
        "| **T2** | **Table task** | x |\n"
        "#### T3 - Heading with T id\n"
        "```\n- **T9 — inside a fence is ignored**\n```\n",
        encoding="utf-8",
    )
    warnings = te.plan_format_warnings(plan, "05-x/plan.md")
    assert len(warnings) == 1
    w = warnings[0]
    assert "2 `NN.T` heading without ' - ' separator" in w
    assert "1 bullet task `T<n>`" in w
    assert "1 table row task `T<n>`" in w
    assert "1 heading task `T<n>`" in w

    plan.write_text("### 05.1 - Fine\n### 05.1b - Letter suffix is accepted\n### 05.10 — Em dash is accepted\n", encoding="utf-8")
    assert te.plan_format_warnings(plan, "05-x/plan.md") == []


def test_plan_task_state_comes_from_its_status_line(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    init = tasks_dir / "05-sample"
    init.mkdir(parents=True)
    (init / "plan.md").write_text(
        "# 05 - Sample\n\n## Tasks\n\n"
        "### 05.1 - Finished\n\n- **Status:** `done` (2026-10-17) · **Profile:** `bulk-execution`\n\n"
        "### 05.2 - Running\n- **Status:** `in progress` (Kilo)\n\n"
        "### 05.3 - No status line\n\nSome text.\n",
        encoding="utf-8",
    )
    states = {t["id"]: t["state"] for i in te.discover_initiatives(tasks_dir) for t in i.get("tasks", [])}
    assert states["05.1"] == "done"
    assert states["05.2"] == "in progress"
    assert states["05.3"] != "done"


def test_tasks_new_without_note(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    ok, res = te.tasks_new_from_note(tasks_dir, None, "bugfix", "Fix the thing", priority="P1")
    assert not ok and "--goal" in res["error"]
    ok, res = te.tasks_new_from_note(tasks_dir, None, "bugfix", "Fix the thing", goal="Make it work.")
    assert not ok and "--priority-reason" in res["error"]
    ok, res = te.tasks_new_from_note(
        tasks_dir, None, "bugfix", "Fix the thing", priority="P1",
        priority_reason="Blocks the owner", goal="Make it work.", paths="src/x.py",
    )
    assert ok, res
    text = (tasks_dir / res["rel_path"]).read_text(encoding="utf-8")
    assert "- id: T001" in text and "- paths: src/x.py" in text and "Make it work." in text
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []


def test_transition_plan_task_rewrites_its_status_line(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    init = tasks_dir / "05-sample"
    init.mkdir(parents=True)
    plan = init / "plan.md"
    plan.write_text(
        "# 05 - Sample\n\n## Tasks\n\n"
        "### 05.1 - First\n\n- **Status:** `open` · **Profile:** `bulk-execution`\n\n"
        "### 05.2 - Second\n- **Status:** `open`\n",
        encoding="utf-8",
    )
    ok, res = te.transition_task(tasks_dir, "05.1", "in progress", actor="claude", reason="dispatched to kilo")
    assert ok, res
    text = plan.read_text(encoding="utf-8")
    assert "- **Status:** `in progress` (" in text and "dispatched to kilo) · **Profile:** `bulk-execution`" in text
    assert "### 05.2 - Second\n- **Status:** `open`" in text
    ok, res = te.transition_task(tasks_dir, "05.1", "done")
    assert not ok and "Illegal transition" in res["error"]
    ok, res = te.transition_task(tasks_dir, "05.1", "delivered", expect_task_hash="0" * 64)
    assert not ok and res["error"] == "stale-task"
    ok, res = te.transition_task(tasks_dir, "05.9", "in progress")
    assert not ok and "not found" in res["error"]


def test_plan_task_depends_on_from_status_line(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "05-sample").mkdir(parents=True)
    (tasks_dir / "05-sample" / "plan.md").write_text(
        "# 05 - Sample\n\n## Tasks\n\n"
        "### 05.1 - A\n- **Status:** `done` · **Depends on:** - · **Repo:** x\n\n"
        "### 05.2 - B\n- **Status:** `open` · **Depends on:** 05.1, 07.4 (same file), T012 · **Repo:** x\n",
        encoding="utf-8",
    )
    deps = {t["id"]: t["depends_on"] for i in te.discover_initiatives(tasks_dir) for t in i["tasks"]}
    assert deps["05.1"] == "-"
    assert deps["05.2"] == "05.1, 07.4, T012"


# ---------------------------------------------------------------------------
# Task 11.1: First-class Task Hierarchy (N levels) Tests
# ---------------------------------------------------------------------------

def test_depth_1_to_5_parsing_and_depth_warning(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-hierarchy"
    init_dir.mkdir()
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        """# 07 - Hierarchy

- **Goal:** Test depth parsing.

## Tasks

### 07.1 - Level 1 Block

- **Status:** `open`
- **Goal:** Level 1 goal.
- **Expanded:** [07.1-level1/](07.1-level1/README.md)
""",
        encoding="utf-8",
    )

    # Level 1 folder
    l1_dir = init_dir / "07.1-level1"
    l1_dir.mkdir()
    (l1_dir / "README.md").write_text(
        """# 07.1 - Level 1 Block

- **Goal:** Level 1 goal.

## Subtasks

### 07.1.1 - Level 2 Block

- **Status:** `open`
- **Goal:** Level 2 goal.
- **Expanded:** [07.1.1-level2/](07.1.1-level2/README.md)
""",
        encoding="utf-8",
    )

    # Level 2 folder
    l2_dir = l1_dir / "07.1.1-level2"
    l2_dir.mkdir()
    (l2_dir / "README.md").write_text(
        """# 07.1.1 - Level 2 Block

- **Goal:** Level 2 goal.

## Subtasks

### 07.1.1.1 - Level 3 Block

- **Status:** `open`
- **Goal:** Level 3 goal.
- **Expanded:** [07.1.1.1-level3/](07.1.1.1-level3/README.md)
""",
        encoding="utf-8",
    )

    # Level 3 folder
    l3_dir = l2_dir / "07.1.1.1-level3"
    l3_dir.mkdir()
    (l3_dir / "README.md").write_text(
        """# 07.1.1.1 - Level 3 Block

- **Goal:** Level 3 goal.

## Subtasks

### 07.1.1.1.1 - Level 4 Block

- **Status:** `open`
- **Goal:** Level 4 goal.
- **Expanded:** [07.1.1.1.1-level4/](07.1.1.1.1-level4/README.md)
""",
        encoding="utf-8",
    )

    # Level 4 folder
    l4_dir = l3_dir / "07.1.1.1.1-level4"
    l4_dir.mkdir()
    (l4_dir / "README.md").write_text(
        """# 07.1.1.1.1 - Level 4 Block

- **Goal:** Level 4 goal.

## Subtasks

### 07.1.1.1.1.1 - Level 5 Block

- **Status:** `open`
- **Goal:** Level 5 goal.
""",
        encoding="utf-8",
    )

    tree = te.discover_task_tree(tasks_dir)
    assert "07" in tree
    assert tree["07"].depth == 0
    assert tree["07.1"].depth == 1
    assert tree["07.1.1"].depth == 2
    assert tree["07.1.1.1"].depth == 3
    assert tree["07.1.1.1.1"].depth == 4
    assert tree["07.1.1.1.1.1"].depth == 5
    assert tree["07.1.1.1.1.1"].is_leaf is True

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert any("depth 5 > 4" in w for w in warnings)


def test_every_s5_rule_incl_nested_derived_containers_and_empty_container() -> None:
    # 1. No children -> open
    assert te.derive_container_state([]) == "open"

    # 2. Every child dropped -> dropped
    assert te.derive_container_state(["dropped", "dropped"]) == "dropped"

    # 3. Every child done, done with a caveat or dropped -> done, or done with caveat
    assert te.derive_container_state(["done", "done", "dropped"]) == "done"
    assert te.derive_container_state(["done", "done with a caveat: reason", "dropped"]) == "done with a caveat"

    # 4. Any child past open (in progress, delivered, bounced, verified, done) -> in progress
    assert te.derive_container_state(["done", "open"]) == "in progress"
    assert te.derive_container_state(["in progress", "open"]) == "in progress"
    assert te.derive_container_state(["delivered", "open"]) == "in progress"
    assert te.derive_container_state(["bounced", "open"]) == "in progress"
    assert te.derive_container_state(["verified", "open"]) == "in progress"

    # 5. Any child blocked -> blocked
    assert te.derive_container_state(["blocked", "open"]) == "blocked"

    # 6. Any child waiting -> waiting
    assert te.derive_container_state(["waiting", "open"]) == "waiting"

    # 7. Otherwise -> open
    assert te.derive_container_state(["open", "open"]) == "open"


def test_s7_bullet_grammar_verbatim_fixtures_and_roundtrip() -> None:
    fixtures_dir = pathlib.Path(__file__).parent / "fixtures" / "real-plans"
    for plan_file in ("06-plan.md", "07-plan.md", "11-plan.md"):
        path = fixtures_dir / plan_file
        assert path.is_file(), f"Missing fixture {plan_file}"
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line_clean = line.strip()
            if line_clean.startswith("- **") or line_clean.startswith("* **"):
                prefix, segs = te.parse_bullet_line(line)
                reconstructed = te.serialize_bullet_segments(prefix, segs)
                assert reconstructed == line, f"Roundtrip mismatch in {plan_file}:\nOriginal : {line}\nRebuilt  : {reconstructed}"

    # Test update_depends_on_field preserves free text
    assert te.update_depends_on_field("09.1 (same file)", ["09.1", "07.4"]) == "09.1, 07.4 (same file)"
    assert te.update_depends_on_field("07.3, 08.1 — supervisor", ["07.3", "08.1", "06.10"]) == "07.3, 08.1, 06.10 — supervisor"
    assert te.update_depends_on_field("-", ["01.1"]) == "01.1"


def test_block_transition_leaves_rest_of_plan_byte_identical(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "11-subtasks"
    init_dir.mkdir()
    fixtures_dir = pathlib.Path(__file__).parent / "fixtures" / "real-plans"
    plan_content = (fixtures_dir / "11-plan.md").read_text(encoding="utf-8")
    target_plan = init_dir / "plan.md"
    target_plan.write_text(plan_content, encoding="utf-8")

    tree = te.discover_task_tree(tasks_dir)
    assert "11.1" in tree
    initial_hash = tree["11.1"].task_hash

    ok, res = te.transition_task(
        tasks_dir=tasks_dir,
        task_id="11.1",
        new_state="in progress",
        expect_task_hash=initial_hash,
    )
    assert ok is True
    assert res["new_state"] == "in progress"

    new_content = target_plan.read_text(encoding="utf-8")
    assert "- **Status:** `in progress`" in new_content

    # Every byte outside block 11.1 must be identical
    m_old = re.search(r"### 11\.1\b.*?(?=### 11\.2)", plan_content, re.DOTALL)
    m_new = re.search(r"### 11\.1\b.*?(?=### 11\.2)", new_content, re.DOTALL)
    assert m_old is not None and m_new is not None

    before_old = plan_content[:m_old.start()]
    before_new = new_content[:m_new.start()]
    assert before_old == before_new

    after_old = plan_content[m_old.end():]
    after_new = new_content[m_new.end():]
    assert after_old == after_new


def test_container_transition_refused(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "11-subtasks"
    init_dir.mkdir()
    fixtures_dir = pathlib.Path(__file__).parent / "fixtures" / "real-plans"
    (init_dir / "plan.md").write_text((fixtures_dir / "11-plan.md").read_text(encoding="utf-8"), encoding="utf-8")

    # Transitioning root initiative container 11
    ok, res = te.transition_task(tasks_dir, "11", "in progress")
    assert ok is False
    assert res["error"] == "derived state; transition its leaves"


def test_container_dependency_expansion_and_inherited_ancestor_deps_and_cycle_through_ancestor(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir()
    (init_dir / "plan.md").write_text(
        """# 07 - Agent Runs

- **Goal:** Agent runs.

## Tasks

### 07.1 - Task 1

- **Status:** `open`
- **Goal:** Goal 1.

### 07.2 - Task 2

- **Status:** `open`
- **Goal:** Goal 2.
- **Depends on:** 07
""",
        encoding="utf-8",
    )

    tree = te.discover_task_tree(tasks_dir)
    assert "07" in tree
    expanded_leaves = te.expand_dependency_to_leaves(tree, "07")
    assert sorted(expanded_leaves) == ["07.1", "07.2"]

    cycle_errors = te.check_dependency_cycles(tree)
    assert any("depends on its ancestor 07 (cycle)" in ce for ce in cycle_errors)


def test_s8_allocation_with_archived_children(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir()
    (init_dir / "plan.md").write_text(
        """# 07 - Agent Runs

- **Goal:** Test.

## Tasks

### 07.1 - Task 1
- **Status:** `open`
- **Goal:** Goal 1.

### 07.2 - Task 2
- **Status:** `open`
- **Goal:** Goal 2.

## Closed

### 07.3 - Old closed
- **Status:** `done`
- **Goal:** Goal 3.
""",
        encoding="utf-8",
    )

    done_dir = init_dir / "done"
    done_dir.mkdir()
    (done_dir / "07.4-archived").mkdir()

    tree = te.discover_task_tree(tasks_dir)
    next_id = te.allocate_child_id(tree, "07", tasks_dir)
    assert next_id == "07.5"


def test_s10_stale_plan_hash_refused(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir()
    (init_dir / "plan.md").write_text(
        """# 07 - Agent Runs

- **Goal:** Test.

## Tasks

### 07.4 - Inline leaf
- **Status:** `open`
- **Goal:** Goal 4.
""",
        encoding="utf-8",
    )

    res = te.expand_node(tasks_dir, "07.4", expect_plan_hash="0000000000000000000000000000000000000000000000000000000000000000")
    assert res["ok"] is False
    assert "Plan hash mismatch" in res["error"]


def test_s11_inheritance_sources_and_label_union(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir()
    (init_dir / "plan.md").write_text(
        """# 07 - Agent Runs

- **Goal:** Test inheritance.
- **Executor:** kilo · **Priority:** P1 · **Profile:** deep-reasoning · **Repo:** ai-orchestration/ · **Labels:** runs, engine

## Tasks

### 07.1 - Child Block
- **Status:** `open` · **Priority:** P2 · **Labels:** ui
- **Goal:** Child goal.
""",
        encoding="utf-8",
    )

    tree = te.discover_task_tree(tasks_dir)
    child = tree["07.1"]

    assert child.fields["executor"]["value"] == "kilo"
    assert child.fields["executor"]["source"] == "inherited:07"

    assert child.fields["priority"]["value"] == "P2"
    assert child.fields["priority"]["source"] == "own"

    assert child.fields["profile"]["value"] == "deep-reasoning"
    assert child.fields["profile"]["source"] == "inherited:07"

    assert child.fields["repo"]["value"] == "ai-orchestration/"
    assert child.fields["repo"]["source"] == "inherited:07"

    assert sorted(child.labels) == ["engine", "runs", "ui"]
    assert child.label_sources["engine"] == "inherited:07"
    assert child.label_sources["runs"] == "inherited:07"
    assert child.label_sources["ui"] == "own"

    res_rem = te.set_labels(tasks_dir, "07.1", remove_labels=["engine"])
    assert res_rem["ok"] is False
    assert "Cannot remove inherited label 'engine' (inherited from 07)" in res_rem["error"]


def test_s12_add_child_to_running_container_allowed_and_to_inflight_leaf_refused(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir()
    (init_dir / "plan.md").write_text(
        """# 07 - Agent Runs

- **Goal:** Test.

## Tasks

### 07.1 - Running Task
- **Status:** `in progress`
- **Goal:** Goal 1.

### 07.2 - Open Leaf
- **Status:** `open`
- **Goal:** Goal 2.
""",
        encoding="utf-8",
    )

    res_dry = te.child_add(tasks_dir, "07", title="Task 3", dry_run=True)
    assert res_dry["ok"] is True
    res_add_init = te.child_add(tasks_dir, "07", title="Task 3", expect_plan_hash=res_dry["plan_hash"])
    assert res_add_init["ok"] is True
    assert res_add_init["allocated_id"] == "07.3"

    res_add_inflight = te.child_add(tasks_dir, "07.1", title="Subtask")
    assert res_add_inflight["ok"] is False
    assert "Cannot add child to in-flight leaf '07.1'" in res_add_inflight["error"]

    res_dry_open = te.child_add(tasks_dir, "07.2", title="Subtask of 2", dry_run=True)
    assert res_dry_open["ok"] is True
    res_add_open = te.child_add(tasks_dir, "07.2", title="Subtask of 2", expect_plan_hash=res_dry_open["plan_hash"])
    assert res_add_open["ok"] is True
    assert res_add_open["allocated_id"] == "07.2.1"
    assert "folder" in res_add_open


def test_expand_collapse_roundtrip_byte_exact(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir()
    original_plan = """# 07 - Agent Runs

- **Goal:** Test.

## Tasks

### 07.4 - Run engine C: worktrees, verify, verdicts

- **Status:** `done` (2026-10-16) · **Size:** L · **Profile:** `deep-reasoning` · **Depends on:** 07.3 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`
- **Goal:** Spec §5.4, §5.5, §5.6.
- **Verification:**
  - `pytest scripts/test_orchestration_runs.py` passes.
"""
    plan_file = init_dir / "plan.md"
    plan_file.write_text(original_plan, encoding="utf-8")

    res_dry_exp = te.expand_node(tasks_dir, "07.4", dry_run=True)
    assert res_dry_exp["ok"] is True
    res_exp = te.expand_node(tasks_dir, "07.4", expect_plan_hash=res_dry_exp["plan_hash"])
    assert res_exp["ok"] is True
    folder_path = pathlib.Path(res_exp["folder"])
    assert folder_path.is_dir()
    assert (folder_path / "README.md").is_file()

    exp_plan_text = plan_file.read_text(encoding="utf-8")
    assert "- **Expanded:** [07.4-run-engine-c-worktrees-verify-verdicts/](07.4-run-engine-c-worktrees-verify-verdicts/README.md)" in exp_plan_text

    res_dry_col = te.collapse_node(tasks_dir, "07.4", dry_run=True)
    assert res_dry_col["ok"] is True
    res_col = te.collapse_node(tasks_dir, "07.4", expect_plan_hash=res_dry_col["plan_hash"])
    assert res_col["ok"] is True
    assert not folder_path.exists()

    restored_plan_text = plan_file.read_text(encoding="utf-8")
    assert restored_plan_text == original_plan


def test_reopen_from_done_in_open_location(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir()
    (init_dir / "plan.md").write_text(
        """# 07 - Agent Runs

- **Goal:** Test.

## Tasks

### 07.1 - Task 1
- **Status:** `done` (2026-10-16)
- **Goal:** Goal 1.
""",
        encoding="utf-8",
    )

    res_dry = te.reopen_node(tasks_dir, "07.1", reason="Re-testing verification", dry_run=True)
    assert res_dry["ok"] is True
    res = te.reopen_node(tasks_dir, "07.1", reason="Re-testing verification", expect_plan_hash=res_dry["plan_hash"])
    assert res["ok"] is True
    assert res["new_state"] == "open"

    tree = te.discover_task_tree(tasks_dir)
    assert tree["07.1"].canonical_state == "open"
    plan_text = (init_dir / "plan.md").read_text(encoding="utf-8")
    assert "Re-testing verification" in plan_text


def test_question_blocking_leaf_works_blocking_container_refused(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir()
    (init_dir / "plan.md").write_text(
        """# 07 - Agent Runs

- **Goal:** Test.

## Tasks

### 07.4 - Leaf Task
- **Status:** `open`
- **Goal:** Goal 4.
""",
        encoding="utf-8",
    )

    # 1. Blocking container 07 is REFUSED
    ok_cont, res_cont = te.ask_question(
        tasks_dir,
        question="Block container?",
        context="Context.",
        open_answer="yes",
        blocks="07",
    )
    assert ok_cont is False
    assert "Cannot block container '07': questions can only block leaf tasks." in res_cont["error"]

    # 2. Blocking leaf 07.4 SUCCEEDS
    ok_leaf, res_leaf = te.ask_question(
        tasks_dir,
        question="Block leaf?",
        context="Context.",
        open_answer="yes",
        blocks="07.4",
    )
    assert ok_leaf is True
    qid = res_leaf["id"]

    tree = te.discover_task_tree(tasks_dir)
    assert tree["07.4"].state == "waiting"

    ok_ans, _ = te.answer_question(tasks_dir, qid, choice="open", text="Proceed")
    assert ok_ans is True
    tree_after = te.discover_task_tree(tasks_dir)
    assert tree_after["07.4"].canonical_state == "open"




def test_block_ends_at_non_canonical_heading_and_legacy_dep_ids(tmp_path: pathlib.Path) -> None:
    """A block stops at any `###` heading. Single-letter suffixed ids (12.2a) are valid plan task ids;
    multi-letter suffixed ids (12.2ab) are legacy and kept on rewrite."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "12-sample").mkdir(parents=True)
    plan = tasks_dir / "12-sample" / "plan.md"
    plan.write_text(
        "# 12 - Sample\n\n## Tasks\n\n"
        "### 12.1 - A\n\n- **Status:** `open` · **Depends on:** 07.12\n- **Goal:** g\n\n"
        "### 12.2a - Valid single-letter suffix\n\n- **Status:** `done` · **Depends on:** 10.4 (lane end)\n- **Goal:** g\n\n"
        "### 12.3 - B\n\n- **Status:** `open` · **Depends on:** 12.2a, 12.2ab, 07.11 (runs lane end), 12.1\n- **Goal:** g\n",
        encoding="utf-8",
    )
    tree = te.discover_task_tree(tasks_dir)
    assert tree["12.1"].depends_on == ["07.12"] and tree["12.1"].canonical_state == "open"
    assert "12.2a" in tree and tree["12.2a"].canonical_state == "done"
    assert "12.2a" in tree["12.3"].own_depends_on
    assert "12.2ab" not in tree
    assert te.update_depends_on_field("12.2ab, 07.11 (runs lane end), 12.1", ["07.11", "12.1"]) == (
        "12.2ab, 07.11 (runs lane end), 12.1"
    )
    before = plan.read_text(encoding="utf-8")
    ok, res = te.transition_task(tasks_dir, "12.1", "in progress", actor="claude", expect_task_hash=tree["12.1"].task_hash)
    assert ok, res
    after = plan.read_text(encoding="utf-8")
    assert after != before
    assert after.split("### 12.2a")[1] == before.split("### 12.2a")[1]
    assert "- **Status:** `in progress` (" in after.split("### 12.2a")[0]


def test_set_labels_on_block_keeps_label_words_and_child_add_on_file_leaf_refused(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "05-x").mkdir(parents=True)
    plan = tasks_dir / "05-x" / "plan.md"
    plan.write_text("# 05 - X\n\n## Tasks\n\n### 05.1 - A\n\n- **Status:** `open` · **Labels:** runs\n- **Goal:** g\n", encoding="utf-8")
    res = te.set_labels(tasks_dir, "05.1", add_labels=["ui"])
    assert res["ok"] and res["labels"] == ["runs", "ui"]
    assert "- **Status:** `open` · **Labels:** runs, ui\n" in plan.read_text(encoding="utf-8")
    ok, r = te.tasks_new_from_note(tasks_dir, None, "bugfix", "Fix", priority="P1", priority_reason="r", goal="g")
    assert ok
    # Missing expect_plan_hash refused:
    res_missing = te.child_add(tasks_dir, r["id"], "child")
    assert res_missing["ok"] is False and "requires --expect-plan-hash" in res_missing["error"]
    # Dry run works:
    res_dry = te.child_add(tasks_dir, r["id"], "child", dry_run=True)
    assert res_dry["ok"] is True and res_dry["allocated_id"] == f"{r['id']}.1"
    # Apply works and converts file leaf to folder:
    res_app = te.child_add(tasks_dir, r["id"], "child", expect_plan_hash=res_dry["plan_hash"])
    assert res_app["ok"] is True and res_app["allocated_id"] == f"{r['id']}.1"
    tree = te.discover_task_tree(tasks_dir)
    assert tree[r["id"]].is_container is True
    assert f"{r['id']}.1" in tree


def test_attachment_classes_and_validation(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Add note
    res_add = run_cli("inbox", "add", "--title", "Attachments multi-class test", "--tasks-dir", str(tasks_dir), "--json")
    assert res_add.returncode == 0
    note_id = json.loads(res_add.stdout)["id"]

    # 1. Image class accepted (PNG, GIF)
    png_bytes = _create_test_png(2, 2)
    png_path = tmp_path / "screenshot.png"
    png_path.write_bytes(png_bytes)
    res_png = run_cli("inbox", "attach", note_id, "--file", str(png_path), "--tasks-dir", str(tasks_dir), "--json")
    assert res_png.returncode == 0
    data_png = json.loads(res_png.stdout)
    assert data_png["class"] == "image"
    assert data_png["markdown"].startswith("![](attachments/")

    gif_bytes = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    gif_path = tmp_path / "animation.gif"
    gif_path.write_bytes(gif_bytes)
    res_gif = run_cli("inbox", "attach", note_id, "--file", str(gif_path), "--tasks-dir", str(tasks_dir), "--json")
    assert res_gif.returncode == 0
    data_gif = json.loads(res_gif.stdout)
    assert data_gif["class"] == "image"

    # 2. PDF class accepted (content starts with %PDF-)
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(pdf_bytes)
    res_pdf = run_cli("inbox", "attach", note_id, "--file", str(pdf_path), "--tasks-dir", str(tasks_dir), "--json")
    assert res_pdf.returncode == 0
    data_pdf = json.loads(res_pdf.stdout)
    assert data_pdf["class"] == "pdf"
    assert data_pdf["markdown"].startswith("[") and "](attachments/" in data_pdf["markdown"]

    # 3. Text class accepted (UTF-8, no NUL in first 64 KB, allowed extensions)
    log_text = "2026-10-17 12:00:00 [INFO] Server started\n2026-10-17 12:00:01 [WARN] Slow query\n"
    log_path = tmp_path / "server.log"
    log_path.write_text(log_text, encoding="utf-8")
    res_log = run_cli("inbox", "attach", note_id, "--file", str(log_path), "--tasks-dir", str(tasks_dir), "--json")
    assert res_log.returncode == 0
    data_log = json.loads(res_log.stdout)
    assert data_log["class"] == "text"
    assert data_log["markdown"].startswith("[") and "](attachments/" in data_log["markdown"]

    # Check show reports JSON objects {name, class, size}
    show_data = json.loads(run_cli("inbox", "show", note_id, "--tasks-dir", str(tasks_dir), "--json").stdout)["note"]
    assert len(show_data["attachments"]) == 4
    assert all(isinstance(a, str) for a in show_data["attachments"])
    for att in show_data["attachment_details"]:
        assert "name" in att and "class" in att and "size" in att
        assert att["class"] in ("image", "pdf", "text")
        assert att["size"] > 0

    # 4. Refused: a .png that is really text
    fake_png = tmp_path / "fake.png"
    fake_png.write_text("Hello, I am actually plain text disguised as a png.", encoding="utf-8")
    res_fake_png = run_cli("inbox", "attach", note_id, "--file", str(fake_png), "--tasks-dir", str(tasks_dir), "--json")
    assert res_fake_png.returncode != 0
    assert json.loads(res_fake_png.stdout)["error"] == "invalid-image-type"

    # 5. Refused: a .log with a NUL byte in first 64 KB
    bad_log = tmp_path / "corrupt.log"
    bad_log.write_bytes(b"Good text before null\x00bad binary text after null")
    res_bad_log = run_cli("inbox", "attach", note_id, "--file", str(bad_log), "--tasks-dir", str(tasks_dir), "--json")
    assert res_bad_log.returncode != 0
    assert json.loads(res_bad_log.stdout)["error"] == "invalid-text-type"

    # 6. Refused: a fake .pdf (does not start with %PDF-)
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("This is not a real PDF file at all.", encoding="utf-8")
    res_fake_pdf = run_cli("inbox", "attach", note_id, "--file", str(fake_pdf), "--tasks-dir", str(tasks_dir), "--json")
    assert res_fake_pdf.returncode != 0
    assert json.loads(res_fake_pdf.stdout)["error"] == "invalid-pdf-type"

    # 7. Refused: executable / binary / zip
    fake_elf = tmp_path / "program.exe"
    fake_elf.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    res_elf = run_cli("inbox", "attach", note_id, "--file", str(fake_elf), "--tasks-dir", str(tasks_dir), "--json")
    assert res_elf.returncode != 0
    assert json.loads(res_elf.stdout)["error"] == "invalid-attachment-type"

    fake_zip = tmp_path / "bundle.zip"
    fake_zip.write_bytes(b"PK\x03\x04\x14\x00\x00\x00\x08\x00")
    res_zip = run_cli("inbox", "attach", note_id, "--file", str(fake_zip), "--tasks-dir", str(tasks_dir), "--json")
    assert res_zip.returncode != 0
    assert json.loads(res_zip.stdout)["error"] == "invalid-attachment-type"

    # 8. Refused: traversal names in attach and detach
    res_trav1 = run_cli("inbox", "attach", note_id, "--file", str(pdf_path), "--name", "../traversal.pdf", "--tasks-dir", str(tasks_dir), "--json")
    assert res_trav1.returncode != 0
    assert json.loads(res_trav1.stdout)["error"] == "invalid-attachment-name"

    res_trav2 = run_cli("inbox", "attach", note_id, "--file", str(pdf_path), "--name", "sub/folder.pdf", "--tasks-dir", str(tasks_dir), "--json")
    assert res_trav2.returncode != 0
    assert json.loads(res_trav2.stdout)["error"] == "invalid-attachment-name"

    # Direct API test for null byte in name (POSIX subprocess execve rejects null bytes in argv)
    ok_nul, res_nul = te.inbox_attach(tasks_dir, note_id, pdf_path, name="nul\x00byte.pdf")
    assert not ok_nul
    assert res_nul["error"] == "invalid-attachment-name"

    res_trav4 = run_cli("inbox", "detach", note_id, "--name", "../traversal.pdf", "--tasks-dir", str(tasks_dir), "--json")
    assert res_trav4.returncode != 0
    assert json.loads(res_trav4.stdout)["error"] == "invalid-attachment"

    ok_nul_det, res_nul_det = te.inbox_detach(tasks_dir, note_id, name="nul\x00byte.pdf")
    assert not ok_nul_det
    assert res_nul_det["error"] == "invalid-attachment"


def test_feature_kind_support_and_triage(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. inbox add with kind: feature
    res_add = run_cli(
        "inbox", "add",
        "--title", "User dark mode toggle",
        "--kind", "feature",
        "--body", "Add dark mode toggle to the user navigation bar.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0
    note_id = json.loads(res_add.stdout)["id"]

    # 2. inbox show verifies kind: feature
    show_res = json.loads(run_cli("inbox", "show", note_id, "--tasks-dir", str(tasks_dir), "--json").stdout)
    assert show_res["ok"] is True
    assert show_res["note"]["kind"] == "feature"

    # 3. inbox edit updates to feature
    res_edit = run_cli("inbox", "edit", note_id, "--kind", "request", "--tasks-dir", str(tasks_dir), "--json")
    assert res_edit.returncode == 0
    res_edit2 = run_cli("inbox", "edit", note_id, "--kind", "feature", "--tasks-dir", str(tasks_dir), "--json")
    assert res_edit2.returncode == 0

    # 4. tasks new --from-note hints category 'feature'
    res_new = run_cli(
        "new",
        "--from-note", note_id,
        "--title", "Dark mode toggle",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new.returncode == 0, res_new.stdout + res_new.stderr
    data_new = json.loads(res_new.stdout)
    assert data_new["ok"] is True
    assert data_new["rel_path"].startswith("feature/")


def test_task_attachments_lifecycle_file_to_folder_and_bundle_hash(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Create a single-file emergent task
    res_new = run_cli(
        "new",
        "--category", "features",
        "--title", "Single file task with attachments",
        "--goal", "Task goal testing file to folder conversion.",
        "--priority-reason", "Testing attachments",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new.returncode == 0
    task_id = json.loads(res_new.stdout)["id"]

    # Check it is currently a single-file task
    single_file_path = tasks_dir / "features" / f"{task_id}-single-file-task-with-attachments.md"
    assert single_file_path.is_file()
    original_bytes = single_file_path.read_bytes()
    orig_task_dict = te.parse_emergent_task_file(single_file_path, tasks_dir)
    original_bundle_hash = orig_task_dict["bundle_sha256"]
    assert orig_task_dict["attachments"] == []

    # 2. tasks list --json exposes attachments
    list_res = json.loads(run_cli("list", "--tasks-dir", str(tasks_dir), "--json").stdout)
    matching_et = next(t for t in list_res["emergent_tasks"] if t["id"] == task_id)
    assert matching_et["attachments"] == []

    # 3. Attach a PDF file to the single-file task
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    pdf_file = tmp_path / "spec.pdf"
    pdf_file.write_bytes(pdf_bytes)

    res_att = run_cli(
        "attach",
        task_id,
        "--file", str(pdf_file),
        "--expect-task-hash", original_bundle_hash,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_att.returncode == 0, res_att.stdout + res_att.stderr
    att_data = json.loads(res_att.stdout)
    assert att_data["ok"] is True
    assert att_data["attachment"] == "01-spec.pdf"
    assert att_data["class"] == "pdf"
    assert att_data["markdown"] == "[01-spec.pdf](attachments/01-spec.pdf)"

    # Check file -> folder conversion happened:
    # - single-file task is gone
    assert not single_file_path.exists()
    # - folder README.md exists and is BYTE-IDENTICAL to original file
    folder_dir = tasks_dir / "features" / f"{task_id}-single-file-task-with-attachments"
    readme_path = folder_dir / "README.md"
    assert readme_path.is_file()
    assert readme_path.read_bytes() == original_bytes

    # - attachment file exists in attachments/
    att_dest = folder_dir / "attachments" / "01-spec.pdf"
    assert att_dest.is_file()
    assert att_dest.read_bytes() == pdf_bytes

    # - bundle hash changed
    new_bundle_hash = att_data["bundle_sha256"]
    assert new_bundle_hash != original_bundle_hash

    # 4. tasks list --json now exposes the attachment
    list_res2 = json.loads(run_cli("list", "--tasks-dir", str(tasks_dir), "--json").stdout)
    matching_et2 = next(t for t in list_res2["emergent_tasks"] if t["id"] == task_id)
    assert len(matching_et2["attachments"]) == 1
    assert matching_et2["attachments"][0] == "01-spec.pdf"
    assert matching_et2["attachment_details"][0] == {"name": "01-spec.pdf", "class": "pdf", "size": len(pdf_bytes)}

    # 5. Attach text file with optimistic locking check
    log_file = tmp_path / "debug.log"
    log_file.write_text("log data line 1\n", encoding="utf-8")

    # Stale hash rejected
    res_stale = run_cli(
        "attach",
        task_id,
        "--file", str(log_file),
        "--expect-task-hash", "deadbeef" * 8,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_stale.returncode != 0
    assert json.loads(res_stale.stdout)["error"] == "stale-task-hash"

    # Matching hash accepted
    res_att2 = run_cli(
        "attach",
        task_id,
        "--file", str(log_file),
        "--expect-task-hash", new_bundle_hash,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_att2.returncode == 0
    att_data2 = json.loads(res_att2.stdout)
    assert att_data2["attachment"] == "02-debug.log"
    assert att_data2["class"] == "text"
    hash_after_att2 = att_data2["bundle_sha256"]
    assert hash_after_att2 != new_bundle_hash

    # 6. Detach attachment
    # Stale hash rejected
    res_det_stale = run_cli(
        "detach",
        task_id,
        "--name", "01-spec.pdf",
        "--expect-task-hash", "wronghash" * 8,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_det_stale.returncode != 0
    assert json.loads(res_det_stale.stdout)["error"] == "stale-task-hash"

    # Matching hash succeeds
    res_det = run_cli(
        "detach",
        task_id,
        "--name", "01-spec.pdf",
        "--expect-task-hash", hash_after_att2,
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_det.returncode == 0
    det_data = json.loads(res_det.stdout)
    assert det_data["ok"] is True
    assert det_data["detached"] == "01-spec.pdf"
    assert not att_dest.exists()

    # tasks list reflects detachment
    list_res3 = json.loads(run_cli("list", "--tasks-dir", str(tasks_dir), "--json").stdout)
    matching_et3 = next(t for t in list_res3["emergent_tasks"] if t["id"] == task_id)
    assert len(matching_et3["attachments"]) == 1
    assert matching_et3["attachments"][0] == "02-debug.log"

    # 7. Detach remaining file
    res_det2 = run_cli("detach", task_id, "--name", "02-debug.log", "--tasks-dir", str(tasks_dir), "--json")
    assert res_det2.returncode == 0
    list_res4 = json.loads(run_cli("list", "--tasks-dir", str(tasks_dir), "--json").stdout)
    matching_et4 = next(t for t in list_res4["emergent_tasks"] if t["id"] == task_id)
    assert matching_et4["attachments"] == []

    # 8. Detach non-existent file gives error
    res_det_none = run_cli("detach", task_id, "--name", "nonexistent.png", "--tasks-dir", str(tasks_dir), "--json")
    assert res_det_none.returncode != 0


def test_task_attachments_refuses_plan_tasks(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "09-inbox").mkdir(parents=True)
    plan_file = tasks_dir / "09-inbox" / "plan.md"
    plan_file.write_text(
        "# 09 - Inbox\n\n## Tasks\n\n### 09.1 - Plan Task\n\n- **Status:** `open`\n- **Goal:** Plan task goal.\n",
        encoding="utf-8",
    )

    dummy_file = tmp_path / "doc.txt"
    dummy_file.write_text("Hello", encoding="utf-8")

    # attach on plan task refused
    res_att = run_cli("attach", "09.1", "--file", str(dummy_file), "--tasks-dir", str(tasks_dir), "--json")
    assert res_att.returncode != 0
    assert json.loads(res_att.stdout)["error"] == "plan-task-attachments-unsupported"

    # detach on plan task refused
    res_det = run_cli("detach", "09.1", "--name", "01-doc.txt", "--tasks-dir", str(tasks_dir), "--json")
    assert res_det.returncode != 0
    assert json.loads(res_det.stdout)["error"] == "plan-task-attachments-unsupported"


def test_tasks_new_from_note_copies_attachments_and_rewrites_links(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Create an inbox note with an image and a text attachment
    res_add = run_cli(
        "inbox", "add",
        "--title", "Auth bug with reproduction",
        "--kind", "bug",
        "--body", "Authentication fails when session expires.\n\nSee ![](attachments/01-screen.png) and [02-trace.log](attachments/02-trace.log) for stack trace.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_add.returncode == 0
    note_id = json.loads(res_add.stdout)["id"]

    png_bytes = _create_test_png(2, 2)
    img_file = tmp_path / "screen.png"
    img_file.write_bytes(png_bytes)
    res_att1 = run_cli("inbox", "attach", note_id, "--file", str(img_file), "--tasks-dir", str(tasks_dir), "--json")
    assert res_att1.returncode == 0

    log_bytes = "Stack trace: NullPointerException at auth.py:42\n".encode("utf-8")
    log_file = tmp_path / "trace.log"
    log_file.write_bytes(log_bytes)
    res_att2 = run_cli("inbox", "attach", note_id, "--file", str(log_file), "--tasks-dir", str(tasks_dir), "--json")
    assert res_att2.returncode == 0

    # 2. Convert note to task with tasks new --from-note
    # (Notice: --category omitted; kind 'bug' hints 'bugfix')
    res_new = run_cli(
        "new",
        "--from-note", note_id,
        "--title", "Fix session expiry crash",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new.returncode == 0, res_new.stdout + res_new.stderr
    data_new = json.loads(res_new.stdout)
    assert data_new["ok"] is True
    task_id = data_new["id"]

    # Verify task was created in folder form under bugfix/
    rel_path = data_new["rel_path"]
    assert rel_path == f"bugfix/{task_id}-fix-session-expiry-crash/README.md"

    task_folder = tasks_dir / "bugfix" / f"{task_id}-fix-session-expiry-crash"
    readme_path = task_folder / "README.md"
    assert readme_path.is_file()

    # Verify attachments were copied into task's own attachments/ folder
    task_att_dir = task_folder / "attachments"
    assert task_att_dir.is_dir()
    copied_img = task_att_dir / "01-screen.png"
    copied_log = task_att_dir / "02-trace.log"
    assert copied_img.is_file()
    assert copied_img.read_bytes() == png_bytes
    assert copied_log.is_file()
    assert copied_log.read_bytes() == log_bytes

    # Verify task content has rewritten links pointing to task's local attachments
    readme_text = readme_path.read_text(encoding="utf-8")
    assert f"- handoff: Read tasks/{rel_path}," in readme_text

    # Verify tasks list --json exposes the 2 copied attachments on the task
    list_res = json.loads(run_cli("list", "--tasks-dir", str(tasks_dir), "--json").stdout)
    matching_task = next(t for t in list_res["emergent_tasks"] if t["id"] == task_id)
    assert len(matching_task["attachments"]) == 2
    att_names = matching_task["attachments"]
    assert "01-screen.png" in att_names
    assert "02-trace.log" in att_names

    # 3. Resolve the inbox note -> moves note folder to tasks/_inbox/analyzed/
    res_res = run_cli("inbox", "resolve", note_id, "--produced", task_id, "--by", "owner", "--tasks-dir", str(tasks_dir), "--json")
    assert res_res.returncode == 0

    # Task attachments remain fully intact and self-contained after note moves!
    assert copied_img.is_file()
    assert copied_log.is_file()
    assert copied_img.read_bytes() == png_bytes

    # tasks validate passes with 0 errors
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    assert json.loads(res_val.stdout)["ok"] is True


def test_use_cases_crud_and_validation(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Create a task that references UC001 (placed after handoff per header grammar)
    task_file = tasks_dir / "features" / "T001-car-search.md"
    _write_sample_task(task_file, task_id="T001", state="delivered")
    task_text = task_file.read_text(encoding="utf-8")
    task_file.write_text(task_text.replace("- verifier: -", "- verifier: -\n- use-cases: UC001"), encoding="utf-8")

    # Validate warns because UC001 does not exist yet
    res_val1 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert any("references unknown use case 'UC001'" in w for w in json.loads(res_val1.stdout)["warnings"])

    # 2. Create UC001
    res_create = run_cli(
        "use-cases", "create",
        "--id", "UC001",
        "--title", "Search by budget and fuel",
        "--actor", "Buyer",
        "--status", "active",
        "--priority", "P1",
        "--linked-tasks", "T001",
        "--verification-type", "automated-probe",
        "--verification-command", "curl -fsS http://localhost/search",
        "--description", "Allows buyer to filter by price and fuel",
        "--scenario", "1. User submits search form.\n2. Filtered results display.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_create.returncode == 0
    payload_create = json.loads(res_create.stdout)
    assert payload_create["ok"] is True
    assert payload_create["id"] == "UC001"

    # 3. List use cases
    res_list = run_cli("use-cases", "list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list.returncode == 0
    payload_list = json.loads(res_list.stdout)
    assert payload_list["total"] == 1
    assert payload_list["use_cases"][0]["id"] == "UC001"
    assert payload_list["use_cases"][0]["actor"] == "Buyer"
    assert payload_list["use_cases"][0]["linked_tasks"] == ["T001"]
    assert payload_list["use_cases"][0]["approval"] == "approved"
    assert payload_list["use_cases"][0]["stage"] == "untested"
    assert payload_list["use_cases"][0]["status"] == "untested"

    # 4. Show use case
    res_show = run_cli("use-cases", "show", "UC001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_show.returncode == 0
    assert json.loads(res_show.stdout)["use_case"]["title"] == "Search by budget and fuel"

    # 5. Record validation result
    res_rec = run_cli(
        "use-cases", "record-validation", "UC001",
        "--verdict", "pass",
        "--summary", "All 3 acceptance criteria verified against test database",
        "--evidence", "curl exit code 0",
        "--actor", "kilo:gemini-4-argon",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_rec.returncode == 0
    payload_rec = json.loads(res_rec.stdout)
    assert payload_rec["ok"] is True
    assert payload_rec["verdict"] == "pass"
    assert payload_rec["status"] == "verified"

    # Verify updated content has AI Validation Log
    uc_file = tasks_dir / "use-cases" / "UC001-search-by-budget-and-fuel.md"
    uc_text = uc_file.read_text(encoding="utf-8")
    assert "- approval: approved" in uc_text
    assert "- last-verdict: pass" in uc_text
    assert "### [" in uc_text
    assert "AI Validation by kilo:gemini-4-argon" in uc_text

    # 6. Validate passes with zero errors/warnings now!
    res_val2 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert json.loads(res_val2.stdout)["ok"] is True


def test_use_cases_validate_probe_and_campaign(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "01-core").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    (tasks_dir / "01-core" / "plan.md").write_text(
        "# 01 — Core Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Core task\n\n"
        "- **Status:** `done` · **Short:** Core task · **Size:** S · **Depends on:** - · **Use cases:** UC001, UC002\n"
        "- **Goal:** Core task.\n",
        encoding="utf-8",
    )

    # 1. Create passing UC001
    run_cli(
        "use-cases", "create",
        "--id", "UC001",
        "--title", "Passing Scenario",
        "--actor", "Buyer",
        "--approval", "approved",
        "--verification-command", "echo 'PASS_DATA'",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )

    # 2. Create failing UC002
    run_cli(
        "use-cases", "create",
        "--id", "UC002",
        "--title", "Failing Scenario",
        "--actor", "Buyer",
        "--approval", "approved",
        "--verification-command", "exit 1",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )

    # 3. Validate UC001 probe
    res_val1 = run_cli("use-cases", "validate", "UC001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val1.returncode == 0
    p1 = json.loads(res_val1.stdout)
    assert p1["ok"] is True
    assert p1["verdict"] == "pass"
    assert p1["status"] == "verified"

    # 4. Validate UC002 probe (fails)
    res_val2 = run_cli("use-cases", "validate", "UC002", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val2.returncode == 1
    p2 = json.loads(res_val2.stdout)
    assert p2["ok"] is True
    assert p2["verdict"] == "fail"
    assert p2["status"] == "failing"

    # 5. Run full product campaign
    res_camp = run_cli("use-cases", "campaign", "--tasks-dir", str(tasks_dir), "--json")
    assert res_camp.returncode == 1  # 1 failure
    pc = json.loads(res_camp.stdout)
    assert pc["ok"] is True
    assert pc["total"] == 2
    assert pc["passed"] == 1
    assert pc["failed"] == 1
    assert pc["readiness_score"] == 50.0
    assert pathlib.Path(pc["report_file"]).is_file()


# ===========================================================================
# Initiative 10: Timeline, Gantt, and Graph Tests
# ===========================================================================

def test_child_blocks_parsing_every_form_and_inherited_priorities(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    init_dir = tasks_dir / "01-test-init"
    init_dir.mkdir()
    plan_content = """# 01 - Test Initiative

- **Priority:** P1

## Waves

### 01.1 - First task (inherits priority and default size)

- **Status:** `open`
- **Goal:** G1

### 01.2 - Second task (own priority and size inline)

- **Status:** `open` · **Priority:** P0 · **Size:** L
- **Goal:** G2

### 01.3 - Third task (separate bullets, size and free-text deps)

- **Status:** `in progress`
- **Priority:** P3
- **Size:** XS
- **Depends on:** 01.1 (first task) — needs DB schema
- **Goal:** G3
"""
    (init_dir / "plan.md").write_text(plan_content, encoding="utf-8")

    tree = te.discover_task_tree(tasks_dir)
    assert "01.1" in tree
    assert "01.2" in tree
    assert "01.3" in tree

    t1 = tree["01.1"]
    assert t1.priority == "P1"
    assert t1.priority_source == "inherited:01"
    assert t1.size == "M"
    assert t1.size_source == "default"

    t2 = tree["01.2"]
    assert t2.priority == "P0"
    assert t2.priority_source == "own"
    assert t2.size == "L"
    assert t2.size_source == "own"

    t3 = tree["01.3"]
    assert t3.priority == "P3"
    assert t3.priority_source == "own"
    assert t3.size == "XS"
    assert t3.size_source == "own"
    assert t3.depends_on == ["01.1"]
    assert t3.depends_on_free_text.strip() == "(first task) — needs DB schema"


def test_tasks_graph_columns_ready_queue_and_mermaid(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    init_dir = tasks_dir / "01-graph-init"
    init_dir.mkdir()
    plan_content = """# 01 - Graph Initiative

- **Priority:** P2

### 01.1 - Base task (done)

- **Status:** `done`
- **Goal:** Base

### 01.2 - Task depending on done task (ready in col 0)

- **Status:** `open` · **Priority:** P2 · **Depends on:** 01.1
- **Goal:** Ready 1

### 01.3 - Independent task with P0 priority (ready in col 0)

- **Status:** `open` · **Priority:** P0
- **Goal:** Ready 2

### 01.4 - Second step task (in col 1)

- **Status:** `open` · **Priority:** P1 · **Depends on:** 01.2, 01.3
- **Goal:** Col 1 task

### 01.5 - Third step task (in col 2)

- **Status:** `open` · **Priority:** P2 · **Depends on:** 01.4
- **Goal:** Col 2 task
"""
    (init_dir / "plan.md").write_text(plan_content, encoding="utf-8")

    res = run_cli("graph", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True

    columns = data["columns"]
    # 01.1 is done, not in columns
    assert "01.1" not in columns
    assert columns["01.2"] == 0
    assert columns["01.3"] == 0
    assert columns["01.4"] == 1
    assert columns["01.5"] == 2

    # Ready queue: 01.3 (P0) before 01.2 (P2)
    ready = data["ready_queue"]
    assert ready == ["01.3", "01.2"]

    # Mermaid
    res_m = run_cli("graph", "--tasks-dir", str(tasks_dir), "--mermaid")
    assert res_m.returncode == 0
    mermaid = res_m.stdout
    assert "flowchart LR" in mermaid
    assert "subgraph" in mermaid
    assert "node_01_2 --> node_01_4" in mermaid
    assert "node_01_3 --> node_01_4" in mermaid
    assert "node_01_4 --> node_01_5" in mermaid
    assert "classDef p0" in mermaid
    assert "class node_01_3 p0" in mermaid


def test_set_deps_refuses_cycle_and_names_it(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    init_dir = tasks_dir / "01-cycle-init"
    init_dir.mkdir()
    plan_content = """# 01 - Cycle Init

### 01.1 - Task A

- **Status:** `open`
- **Goal:** A

### 01.2 - Task B

- **Status:** `open` · **Depends on:** 01.1
- **Goal:** B

### 01.3 - Task C

- **Status:** `open` · **Depends on:** 01.2
- **Goal:** C
"""
    (init_dir / "plan.md").write_text(plan_content, encoding="utf-8")

    # Creating cycle: make 01.1 depend on 01.3
    res = run_cli("set-deps", "01.1", "01.3", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode != 0
    data = json.loads(res.stdout)
    assert data["ok"] is False
    assert "Cycle detected in dependencies" in data["error"]
    assert "01.1" in data["error"] and "01.2" in data["error"] and "01.3" in data["error"]

    # Self-cycle: make 01.1 depend on 01.1
    res_self = run_cli("set-deps", "01.1", "01.1", "--tasks-dir", str(tasks_dir), "--json")
    assert res_self.returncode != 0
    data_self = json.loads(res_self.stdout)
    assert data_self["ok"] is False
    assert "Cycle detected in dependencies" in data_self["error"]


def test_set_deps_keeps_free_text_and_checks_unknown_id(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    init_dir = tasks_dir / "01-text-init"
    init_dir.mkdir()
    plan_content = """# 01 - Text Init

### 01.1 - Dependency 1

- **Status:** `open`
- **Goal:** D1

### 01.2 - Dependency 2

- **Status:** `open`
- **Goal:** D2

### 01.3 - Target task

- **Status:** `open` · **Depends on:** 01.1 (runs lane) — needs the real CLIs
- **Goal:** T
"""
    plan_file = init_dir / "plan.md"
    plan_file.write_text(plan_content, encoding="utf-8")

    # Unknown ID refused
    res_unk = run_cli("set-deps", "01.3", "01.1, 99.99", "--tasks-dir", str(tasks_dir), "--json")
    assert res_unk.returncode != 0
    data_unk = json.loads(res_unk.stdout)
    assert data_unk["ok"] is False
    assert "Unknown task id '99.99' in dependencies." in data_unk["error"]

    # Update dependencies to 01.1, 01.2, free text kept
    res = run_cli("set-deps", "01.3", "01.1, 01.2", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["depends_on"] == ["01.1", "01.2"]

    new_content = plan_file.read_text(encoding="utf-8")
    assert "01.1, 01.2 (runs lane) — needs the real CLIs" in new_content


def test_set_priority_and_set_size_on_emergent_and_block_tasks(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # 1. Emergent task T001
    cat_dir = tasks_dir / "features"
    cat_dir.mkdir()
    t001_file = cat_dir / "T001-sample-task.md"
    t001_content = """# T001: Sample task

- id: T001
- title: Sample task
- category: features
- priority: P2
- priority-reason: Normal priority
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Work on T001

## Goal
Do something.

## Steps
1. Step.

## Verification
echo ok
"""
    t001_file.write_text(t001_content, encoding="utf-8")

    # Set priority on T001
    res_sp_em = run_cli("set-priority", "T001", "P0", "--reason", "Urgent bug", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sp_em.returncode == 0
    assert json.loads(res_sp_em.stdout)["ok"] is True
    t001_text = t001_file.read_text(encoding="utf-8")
    assert "- priority: P0" in t001_text
    assert "- priority-reason: Urgent bug" in t001_text

    # Set size on T001
    res_ss_em = run_cli("set-size", "T001", "XL", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ss_em.returncode == 0
    assert json.loads(res_ss_em.stdout)["ok"] is True
    t001_text2 = t001_file.read_text(encoding="utf-8")
    assert "- size: XL" in t001_text2

    # 2. Block task in plan.md
    init_dir = tasks_dir / "02-block-init"
    init_dir.mkdir()
    plan_file = init_dir / "plan.md"
    plan_content = """# 02 - Block Init

### 02.1 - First block task

- **Status:** `open`
- **Goal:** G1
"""
    plan_file.write_text(plan_content, encoding="utf-8")

    # Set priority on block task
    res_sp_bl = run_cli("set-priority", "02.1", "P1", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sp_bl.returncode == 0
    assert json.loads(res_sp_bl.stdout)["ok"] is True
    plan_text = plan_file.read_text(encoding="utf-8")
    assert "**Priority:** P1" in plan_text

    # Set size on block task
    res_ss_bl = run_cli("set-size", "02.1", "L", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ss_bl.returncode == 0
    assert json.loads(res_ss_bl.stdout)["ok"] is True
    plan_text2 = plan_file.read_text(encoding="utf-8")
    assert "**Size:** L" in plan_text2


def test_heaviest_chain_and_totals_follow_sizes(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    init_dir = tasks_dir / "03-chains-init"
    init_dir.mkdir()
    # Chain 1: 03.1 (S=2) -> 03.2 (S=2) -> 03.3 (S=2) = total weight 6
    # Chain 2: 03.4 (L=5) -> 03.5 (XL=8) = total weight 13
    plan_content = """# 03 - Chains Init

### 03.1 - C1 Step 1

- **Status:** `open` · **Size:** S
- **Goal:** C1.1

### 03.2 - C1 Step 2

- **Status:** `open` · **Size:** S · **Depends on:** 03.1
- **Goal:** C1.2

### 03.3 - C1 Step 3

- **Status:** `open` · **Size:** S · **Depends on:** 03.2
- **Goal:** C1.3

### 03.4 - C2 Step 1

- **Status:** `open` · **Size:** L
- **Goal:** C2.1

### 03.5 - C2 Step 2

- **Status:** `open` · **Size:** XL · **Depends on:** 03.4
- **Goal:** C2.2
"""
    (init_dir / "plan.md").write_text(plan_content, encoding="utf-8")

    res = run_cli("graph", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0
    data = json.loads(res.stdout)

    assert data["heaviest_chain"] == ["03.4", "03.5"]
    assert data["longest_chain"] == ["03.4", "03.5"]
    assert data["heaviest_chain_weight"] == 13

    totals = data["totals"]
    assert totals["by_size"]["S"] == 3
    assert totals["by_size"]["L"] == 1
    assert totals["by_size"]["XL"] == 1
    assert "3 S" in totals["overall"]
    assert "1 L" in totals["overall"]
    assert "1 XL" in totals["overall"]
    assert totals["total_open"] == 5


def test_stale_hash_is_refused(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    init_dir = tasks_dir / "04-hash-init"
    init_dir.mkdir()
    plan_content = """# 04 - Hash Init

### 04.1 - Task

- **Status:** `open`
- **Goal:** G
"""
    (init_dir / "plan.md").write_text(plan_content, encoding="utf-8")

    wrong_hash = "deadbeef" * 8
    # set-priority with stale hash
    res_sp = run_cli("set-priority", "04.1", "P0", "--expect-task-hash", wrong_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_sp.returncode != 0
    assert "Task hash mismatch" in json.loads(res_sp.stdout)["error"]

    # set-size with stale hash
    res_ss = run_cli("set-size", "04.1", "L", "--expect-task-hash", wrong_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_ss.returncode != 0
    assert "Task hash mismatch" in json.loads(res_ss.stdout)["error"]

    # set-deps with stale hash
    res_sd = run_cli("set-deps", "04.1", "--to", "", "--expect-task-hash", wrong_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_sd.returncode != 0
    assert "Task hash mismatch" in json.loads(res_sd.stdout)["error"]


def test_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    init_dir = tasks_dir / "05-dry-init"
    init_dir.mkdir()
    plan_file = init_dir / "plan.md"
    original_plan = """# 05 - Dry Run Init

### 05.1 - Task A

- **Status:** `open`
- **Goal:** GA

### 05.2 - Task B

- **Status:** `open`
- **Goal:** GB
"""
    plan_file.write_text(original_plan, encoding="utf-8")

    # dry-run set-priority
    res_sp = run_cli("set-priority", "05.1", "P0", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sp.returncode == 0
    sp_data = json.loads(res_sp.stdout)
    assert sp_data["ok"] is True
    assert sp_data["dry_run"] is True
    assert "diff" in sp_data and len(sp_data["diff"]) > 0
    assert plan_file.read_text(encoding="utf-8") == original_plan

    # dry-run set-size
    res_ss = run_cli("set-size", "05.1", "XL", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ss.returncode == 0
    ss_data = json.loads(res_ss.stdout)
    assert ss_data["ok"] is True
    assert ss_data["dry_run"] is True
    assert "diff" in ss_data and len(ss_data["diff"]) > 0
    assert plan_file.read_text(encoding="utf-8") == original_plan

    # dry-run set-deps
    res_sd = run_cli("set-deps", "05.2", "05.1", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sd.returncode == 0
    sd_data = json.loads(res_sd.stdout)
    assert sd_data["ok"] is True
    assert sd_data["dry_run"] is True
    assert "diff" in sd_data and len(sd_data["diff"]) > 0
    assert plan_file.read_text(encoding="utf-8") == original_plan



def test_graph_ready_queue_holds_only_startable_leaves(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "05-sample").mkdir(parents=True)
    (tasks_dir / "05-sample" / "plan.md").write_text(
        "# 05 - Sample\n\n## Tasks\n\n"
        "### 05.1 - Open\n- **Status:** `open`\n\n"
        "### 05.2 - Running\n- **Status:** `in progress`\n\n"
        "### 05.3 - Delivered\n- **Status:** `delivered`\n\n"
        "### 05.4 - Waits on running\n- **Status:** `open` · **Depends on:** 05.2\n",
        encoding="utf-8",
    )
    res = run_cli("graph", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["ready_queue"] == ["05.1"]


def test_microtask_creation_reduced_schema_and_graph(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Create microtask via CLI
    res = run_cli(
        "micro",
        "--title", "Fix navbar alignment",
        "--kind", "bug",
        "--priority", "P1",
        "--label", "ui",
        "--label", "css",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["id"] == "T001"
    assert data["kind"] == "bug"
    assert data["priority"] == "P1"
    assert data["size"] == "XS"
    assert data["labels"] == ["ui", "css"]

    mf = tasks_dir / "micro" / "T001-fix-navbar-alignment.md"
    assert mf.is_file()
    content = mf.read_text(encoding="utf-8")
    assert "- id: T001" in content
    assert "- title: Fix navbar alignment" in content
    assert "- kind: bug" in content
    assert "- priority: P1" in content
    assert "- state: open" in content
    assert "- executor: kilo" in content
    assert "- paths: -" in content
    assert "- depends-on: -" in content
    assert "- labels: ui, css" in content
    assert "## What" in content
    assert "## Goal" not in content

    # 2. Validate tree
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    val_data = json.loads(res_val.stdout)
    assert val_data["ok"] is True
    assert len(val_data["errors"]) == 0

    # 3. Check tasks graph exposes node_type=microtask and size=XS
    res_graph = run_cli("graph", "--tasks-dir", str(tasks_dir), "--json")
    assert res_graph.returncode == 0
    g_data = json.loads(res_graph.stdout)
    node = g_data["nodes_by_id"]["T001"]
    assert node["node_type"] == "microtask"
    assert node["size"] == "XS"
    assert node["size_source"] == "default"
    assert node["kind"] == "bug"
    assert set(node["labels"]) == {"ui", "css"}
    assert g_data["totals"]["by_size"]["XS"] == 1


def test_microtask_concurrent_creation(tmp_path: pathlib.Path) -> None:
    import concurrent.futures

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    def _create(idx: int):
        return run_cli(
            "micro",
            "--title", f"Concurrent task {idx}",
            "--kind", "chore",
            "--tasks-dir", str(tasks_dir),
            "--json",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(_create, i) for i in range(12)]
        results = [f.result() for f in futures]

    for r in results:
        assert r.returncode == 0, r.stderr

    created_ids = [json.loads(r.stdout)["id"] for r in results]
    assert len(set(created_ids)) == 12
    assert sorted(created_ids) == [f"T{i:03d}" for i in range(1, 13)]

    # Validate all 12 pass validation
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    val_data = json.loads(res_val.stdout)
    assert val_data["ok"] is True
    assert len(val_data["errors"]) == 0


def test_microtask_promotion_and_dependency_resolution(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Create microtask
    res_m = run_cli(
        "micro",
        "--title", "Quick spelling fix",
        "--kind", "docs",
        "--priority", "P3",
        "--label", "docs",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_m.returncode == 0
    assert json.loads(res_m.stdout)["id"] == "T001"

    # Create plan task that depends on T001
    (tasks_dir / "01-test").mkdir(parents=True)
    plan = tasks_dir / "01-test" / "plan.md"
    plan.write_text(
        "# 01 - Test\n\n## Tasks\n\n### 01.1 - Child\n- **Status:** `open` · **Depends on:** T001\n- **Goal:** G\n",
        encoding="utf-8",
    )

    # Verify dependency in graph
    res_g1 = run_cli("graph", "--tasks-dir", str(tasks_dir), "--json")
    assert res_g1.returncode == 0
    g1 = json.loads(res_g1.stdout)
    assert g1["nodes_by_id"]["01.1"]["column"] == 1
    assert "T001" in g1["nodes_by_id"]["01.1"]["blocked_by"]

    # Promote T001 to category maintenance
    res_prom = run_cli(
        "promote",
        "T001",
        "--category", "maintenance",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_prom.returncode == 0, res_prom.stderr
    p_data = json.loads(res_prom.stdout)
    assert p_data["ok"] is True
    assert p_data["category"] == "maintenance"

    # Old file gone, new file created
    assert not (tasks_dir / "micro" / "T001-quick-spelling-fix.md").exists()
    prom_file = tasks_dir / "maintenance" / "T001-quick-spelling-fix.md"
    assert prom_file.is_file()

    text = prom_file.read_text(encoding="utf-8")
    assert "- id: T001" in text
    assert "- category: maintenance" in text
    assert "- priority-reason: Promoted from microtask T001" in text
    assert "- handoff: Read tasks/maintenance/T001-quick-spelling-fix.md" in text
    assert "- kind: docs" in text
    assert "- labels: docs" in text
    assert "## Goal" in text
    assert "## Steps" in text
    assert "## Verification" in text

    # Validation succeeds
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    assert len(json.loads(res_val.stdout)["errors"]) == 0

    # Dependencies still resolve to T001 in graph
    res_g2 = run_cli("graph", "--tasks-dir", str(tasks_dir), "--json")
    assert res_g2.returncode == 0
    g2 = json.loads(res_g2.stdout)
    assert g2["nodes_by_id"]["01.1"]["column"] == 1
    assert "T001" in g2["nodes_by_id"]["01.1"]["blocked_by"]
    assert g2["nodes_by_id"]["T001"]["node_type"] == "leaf"


def test_set_kind_and_set_labels_with_dry_run_and_validation(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "02-x").mkdir(parents=True)
    plan = tasks_dir / "02-x" / "plan.md"
    plan.write_text(
        "# 02 - X\n\n## Tasks\n\n### 02.1 - Task\n- **Status:** `open`\n- **Goal:** G\n",
        encoding="utf-8",
    )

    # 1. set-kind on block with --dry-run
    res_sk_dry = run_cli("set-kind", "02.1", "feature", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sk_dry.returncode == 0
    sk_dry = json.loads(res_sk_dry.stdout)
    assert sk_dry["ok"] is True
    assert sk_dry["dry_run"] is True
    assert "diff" in sk_dry and "+- **Status:** `open` · **Kind:** feature" in sk_dry["diff"]
    assert "**Kind:**" not in plan.read_text(encoding="utf-8")

    # 2. set-kind real apply
    res_sk = run_cli("set-kind", "02.1", "feature", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sk.returncode == 0
    assert "- **Status:** `open` · **Kind:** feature\n" in plan.read_text(encoding="utf-8")

    # 3. set-labels on block
    res_sl = run_cli("set-labels", "02.1", "--add", "ui,perf", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sl.returncode == 0
    assert "- **Status:** `open` · **Kind:** feature · **Labels:** ui, perf\n" in plan.read_text(encoding="utf-8")

    # 4. set-labels remove
    res_sl_rem = run_cli("set-labels", "02.1", "--remove", "ui", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sl_rem.returncode == 0
    assert "- **Status:** `open` · **Kind:** feature · **Labels:** perf\n" in plan.read_text(encoding="utf-8")

    # 5. set-kind and set-labels on emergent task
    res_m = run_cli("micro", "--title", "Emergent", "--kind", "chore", "--tasks-dir", str(tasks_dir), "--json")
    assert res_m.returncode == 0
    t_id = json.loads(res_m.stdout)["id"]

    res_sk_m = run_cli("set-kind", t_id, "investigation", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sk_m.returncode == 0
    assert "- kind: investigation" in (tasks_dir / "micro" / f"{t_id}-emergent.md").read_text(encoding="utf-8")

    res_sl_m = run_cli("set-labels", t_id, "--add", "kilo-mcp", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sl_m.returncode == 0
    assert "- labels: kilo-mcp" in (tasks_dir / "micro" / f"{t_id}-emergent.md").read_text(encoding="utf-8")

    # 6. Invalid kind refused
    res_bad_k = run_cli("set-kind", t_id, "unknown_kind", "--tasks-dir", str(tasks_dir), "--json")
    assert res_bad_k.returncode != 0
    assert "Invalid kind" in json.loads(res_bad_k.stdout)["error"]

    # 7. Invalid label refused
    res_bad_l = run_cli("set-labels", t_id, "--add", "INVALID_LABEL!", "--tasks-dir", str(tasks_dir), "--json")
    assert res_bad_l.returncode != 0
    assert "Invalid label" in json.loads(res_bad_l.stdout)["error"]


def test_labels_command_and_list_graph_filtering(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Create task 1: bug, labels=[ui, frontend]
    run_cli("micro", "--title", "Bug 1", "--kind", "bug", "--label", "ui,frontend", "--tasks-dir", str(tasks_dir), "--json")
    # Create task 2: bug, labels=[backend]
    run_cli("micro", "--title", "Bug 2", "--kind", "bug", "--label", "backend", "--tasks-dir", str(tasks_dir), "--json")
    # Create task 3: feature, labels=[ui]
    run_cli("micro", "--title", "Feature 1", "--kind", "feature", "--label", "ui", "--tasks-dir", str(tasks_dir), "--json")
    # Create task 4: chore, no labels
    run_cli("micro", "--title", "Chore 1", "--kind", "chore", "--tasks-dir", str(tasks_dir), "--json")

    # 1. tasks labels command
    res_lbls = run_cli("labels", "--tasks-dir", str(tasks_dir), "--json")
    assert res_lbls.returncode == 0
    lbl_data = json.loads(res_lbls.stdout)
    assert lbl_data["counts"]["ui"] == 2
    assert lbl_data["counts"]["frontend"] == 1
    assert lbl_data["counts"]["backend"] == 1

    # 2. tasks list --kind bug
    res_l_kind = run_cli("list", "--kind", "bug", "--tasks-dir", str(tasks_dir), "--json")
    assert res_l_kind.returncode == 0
    l_kind = json.loads(res_l_kind.stdout)
    assert len(l_kind["all_tasks"]) == 2
    assert {t["title"] for t in l_kind["all_tasks"]} == {"Bug 1", "Bug 2"}

    # 3. tasks list --label ui
    res_l_lbl = run_cli("list", "--label", "ui", "--tasks-dir", str(tasks_dir), "--json")
    assert res_l_lbl.returncode == 0
    l_lbl = json.loads(res_l_lbl.stdout)
    assert len(l_lbl["all_tasks"]) == 2
    assert {t["title"] for t in l_lbl["all_tasks"]} == {"Bug 1", "Feature 1"}

    # 4. tasks list --kind bug --label ui (AND across fields)
    res_l_both = run_cli("list", "--kind", "bug", "--label", "ui", "--tasks-dir", str(tasks_dir), "--json")
    assert res_l_both.returncode == 0
    l_both = json.loads(res_l_both.stdout)
    assert len(l_both["all_tasks"]) == 1
    assert l_both["all_tasks"][0]["title"] == "Bug 1"

    # 5. tasks list --kind bug --kind feature (OR within field)
    res_l_or = run_cli("list", "--kind", "bug", "--kind", "feature", "--tasks-dir", str(tasks_dir), "--json")
    assert res_l_or.returncode == 0
    l_or = json.loads(res_l_or.stdout)
    assert len(l_or["all_tasks"]) == 3

    # 6. tasks graph --kind bug
    res_g_kind = run_cli("graph", "--kind", "bug", "--tasks-dir", str(tasks_dir), "--json")
    assert res_g_kind.returncode == 0
    g_kind = json.loads(res_g_kind.stdout)
    assert len(g_kind["nodes"]) == 2
    assert all(n["kind"] == "bug" for n in g_kind["nodes"])


def test_validator_detects_unknown_kind_and_malformed_label(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "03-test").mkdir(parents=True)
    plan = tasks_dir / "03-test" / "plan.md"
    plan.write_text(
        "# 03 - Test\n\n## Tasks\n\n"
        "### 03.1 - Bad kind\n- **Status:** `open` · **Kind:** bogus_kind\n- **Goal:** G\n\n"
        "### 03.2 - Bad label\n- **Status:** `open` · **Labels:** bad_label_with_UPPERCASE\n- **Goal:** G\n",
        encoding="utf-8",
    )
    (tasks_dir / "micro").mkdir()
    (tasks_dir / "micro" / "T099-bad.md").write_text(
        "# T099 Bad microtask\n\n"
        "- id: T099\n"
        "- title: Bad microtask\n"
        "- kind: not_a_kind\n"
        "- priority: P2\n"
        "- state: open\n"
        "- executor: kilo\n"
        "- paths: -\n"
        "- depends-on: -\n"
        "- labels: this-label-is-far-too-long-exceeding-twenty-four-chars\n\n"
        "## What\n\nSomething\n",
        encoding="utf-8",
    )

    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 1
    val = json.loads(res_val.stdout)
    errors = " ".join(val["errors"])
    assert "invalid kind 'bogus_kind' on node 03.1" in errors
    assert "invalid label 'bad_label_with_UPPERCASE' on node 03.2" in errors
    assert "invalid kind 'not_a_kind'" in errors
    assert "invalid label 'this-label-is-far-too-long-exceeding-twenty-four-chars'" in errors


# ---------------------------------------------------------------------------
# 11.6 Follow-up Tests: CLI structure commands, S10 hashes, reopen, file/folder children,
# scoped set-deps, set-labels on file/folder, depth > 2, initiative status in sync-index
# ---------------------------------------------------------------------------

def test_cli_s10_hashes_child_add_expand_collapse_reopen(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "07-test"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        """# 07 - Test

- **Goal:** S10 hash CLI tests.

## Tasks

### 07.1 - Leaf Task
- **Status:** `open`
- **Goal:** Goal 1.

### 07.2 - Done Task
- **Status:** `done` (2026-10-16)
- **Goal:** Goal 2.
""",
        encoding="utf-8",
    )

    # 1. child add: missing hash refused
    res = run_cli("child", "add", "07", "--title", "Task 3", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode != 0
    assert "requires --expect-plan-hash" in json.loads(res.stdout)["error"]

    # dry-run returns plan_hash
    res_dry = run_cli("child", "add", "07", "--title", "Task 3", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0
    data_dry = json.loads(res_dry.stdout)
    assert data_dry["dry_run"] is True
    plan_hash = data_dry["plan_hash"]
    assert plan_hash and len(plan_hash) == 64

    # stale hash refused
    res_stale = run_cli("child", "add", "07", "--title", "Task 3", "--expect-plan-hash", "00" * 32, "--tasks-dir", str(tasks_dir), "--json")
    assert res_stale.returncode != 0
    assert "Plan hash mismatch" in json.loads(res_stale.stdout)["error"]

    # apply with matching hash succeeds
    res_app = run_cli("child", "add", "07", "--title", "Task 3", "--expect-plan-hash", plan_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_app.returncode == 0
    assert json.loads(res_app.stdout)["allocated_id"] == "07.3"

    # 2. expand: missing hash refused
    res_exp_bad = run_cli("expand", "07.3", "--tasks-dir", str(tasks_dir), "--json")
    assert res_exp_bad.returncode != 0
    assert "requires --expect-plan-hash" in json.loads(res_exp_bad.stdout)["error"]

    res_exp_dry = run_cli("expand", "07.3", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_exp_dry.returncode == 0
    exp_hash = json.loads(res_exp_dry.stdout)["plan_hash"]

    res_exp_stale = run_cli("expand", "07.3", "--expect-plan-hash", "00" * 32, "--tasks-dir", str(tasks_dir), "--json")
    assert res_exp_stale.returncode != 0
    assert "Plan hash mismatch" in json.loads(res_exp_stale.stdout)["error"]

    res_exp_ok = run_cli("expand", "07.3", "--expect-plan-hash", exp_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_exp_ok.returncode == 0
    assert (init_dir / "07.3-task-3" / "README.md").is_file()

    # 3. collapse: missing hash refused
    res_col_bad = run_cli("collapse", "07.3", "--tasks-dir", str(tasks_dir), "--json")
    assert res_col_bad.returncode != 0
    assert "requires --expect-plan-hash" in json.loads(res_col_bad.stdout)["error"]

    res_col_dry = run_cli("collapse", "07.3", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_col_dry.returncode == 0
    col_hash = json.loads(res_col_dry.stdout)["plan_hash"]

    res_col_stale = run_cli("collapse", "07.3", "--expect-plan-hash", "00" * 32, "--tasks-dir", str(tasks_dir), "--json")
    assert res_col_stale.returncode != 0
    assert "Plan hash mismatch" in json.loads(res_col_stale.stdout)["error"]

    res_col_ok = run_cli("collapse", "07.3", "--expect-plan-hash", col_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_col_ok.returncode == 0
    assert not (init_dir / "07.3-task-3").exists()

    # 4. reopen: missing hash refused
    res_reop_bad = run_cli("reopen", "07.2", "--reason", "verification failed", "--tasks-dir", str(tasks_dir), "--json")
    assert res_reop_bad.returncode != 0
    assert "requires --expect-plan-hash" in json.loads(res_reop_bad.stdout)["error"]

    res_reop_dry = run_cli("reopen", "07.2", "--reason", "verification failed", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_reop_dry.returncode == 0
    reop_hash = json.loads(res_reop_dry.stdout)["plan_hash"]

    res_reop_stale = run_cli("reopen", "07.2", "--reason", "verification failed", "--expect-plan-hash", "00" * 32, "--tasks-dir", str(tasks_dir), "--json")
    assert res_reop_stale.returncode != 0
    assert "Plan hash mismatch" in json.loads(res_reop_stale.stdout)["error"]

    res_reop_ok = run_cli("reopen", "07.2", "--reason", "verification failed", "--expect-plan-hash", reop_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_reop_ok.returncode == 0
    assert json.loads(res_reop_ok.stdout)["new_state"] == "open"
    plan_text = plan_file.read_text(encoding="utf-8")
    assert "verification failed" in plan_text


def test_cli_reopen_writes_reason_and_restores_ancestors(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    feat_dir = tasks_dir / "features"
    t_folder = feat_dir / "T014-payment-gateway"
    t_folder.mkdir(parents=True)
    readme = t_folder / "README.md"
    readme.write_text(
        """# T014 Payment Gateway

- id: T014
- title: Payment Gateway
- category: features
- priority: P1
- priority-reason: core flow
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read instructions.

## Goal

Payment gateway feature.

## Subtasks

### T014.1 - Stripe connector

- **Status:** `done` (2026-10-15) · **Kind:** feature
- **Goal:** Implement Stripe connector.
""",
        encoding="utf-8",
    )

    tree = te.discover_task_tree(tasks_dir)
    assert tree["T014"].state == "done"
    assert tree["T014.1"].canonical_state == "done"

    # Dry-run reopen on T014.1
    res_dry = run_cli("reopen", "T014.1", "--reason", "Stripe API v3 breaking changes", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0
    data_dry = json.loads(res_dry.stdout)
    plan_hash = data_dry["plan_hash"]

    # Apply reopen
    res_app = run_cli("reopen", "T014.1", "--reason", "Stripe API v3 breaking changes", "--expect-plan-hash", plan_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_app.returncode == 0

    new_readme = readme.read_text(encoding="utf-8")
    assert "Stripe API v3 breaking changes" in new_readme
    assert "- state: open" in new_readme

    tree_after = te.discover_task_tree(tasks_dir)
    assert tree_after["T014.1"].canonical_state == "open"
    assert tree_after["T014"].canonical_state == "open"


def test_cli_child_add_on_emergent_task_converts_file_to_folder(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    feat_dir = tasks_dir / "features"
    feat_dir.mkdir(parents=True)
    task_file = feat_dir / "T020-auth.md"
    task_file.write_text(
        """# T020 Authentication

- id: T020
- title: Authentication
- category: features
- priority: P1
- priority-reason: auth core
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read instructions.

## Goal

Authentication module.

## Steps

- [ ] Implement auth.

## Verification

- [ ] Test auth.
""",
        encoding="utf-8",
    )

    # 1. child add on single-file leaf converts to folder
    res_dry = run_cli("child", "add", "T020", "--title", "Add JWT support", "--kind", "feature", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0
    d_dry = json.loads(res_dry.stdout)
    assert d_dry["allocated_id"] == "T020.1"
    plan = d_dry["plan"]
    assert any(p["action"] == "delete" and "T020-auth.md" in p["path"] for p in plan)
    assert any(p["action"] == "create" and "T020-" in p["path"] and "README.md" in p["path"] for p in plan)

    res_app = run_cli("child", "add", "T020", "--title", "Add JWT support", "--kind", "feature", "--expect-plan-hash", d_dry["plan_hash"], "--tasks-dir", str(tasks_dir), "--json")
    assert res_app.returncode == 0
    assert not task_file.exists()
    folder = feat_dir / "T020-authentication"
    readme = folder / "README.md"
    assert readme.is_file()
    readme_text = readme.read_text(encoding="utf-8")
    assert "## Subtasks" in readme_text
    assert "### T020.1 - Add JWT support" in readme_text

    # 2. Add second child under the container
    res_dry2 = run_cli("child", "add", "T020", "--title", "Add OAuth2 support", "--kind", "feature", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry2.returncode == 0
    d_dry2 = json.loads(res_dry2.stdout)
    assert d_dry2["allocated_id"] == "T020.2"

    res_app2 = run_cli("child", "add", "T020", "--title", "Add OAuth2 support", "--kind", "feature", "--expect-plan-hash", d_dry2["plan_hash"], "--tasks-dir", str(tasks_dir), "--json")
    assert res_app2.returncode == 0
    readme_text2 = readme.read_text(encoding="utf-8")
    assert "### T020.2 - Add OAuth2 support" in readme_text2

    # Validation passes 100%
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0


def test_cli_tasks_new_from_note_with_parent(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    inbox_dir = tasks_dir / "_inbox" / "to-analyze" / "N001-fix-bug"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "note.md").write_text(
        """# N001 Fix Gateway Bug

- id: N001
- date: 2026-10-17
- source: sentry
- author: team
- status: ready
- kind: bug
- title: Fix Gateway Bug
- about: src/gateway.py

Payment gateway times out under burst load.
""",
        encoding="utf-8",
    )

    init_dir = tasks_dir / "08-payments"
    init_dir.mkdir(parents=True)
    (init_dir / "plan.md").write_text(
        """# 08 - Payments

- **Goal:** Payment service.

## Tasks

### 08.1 - Setup DB
- **Status:** `open`
- **Goal:** Setup payment DB.
""",
        encoding="utf-8",
    )

    # Create task new under parent 08
    res_new = run_cli("new", "--from-note", "N001", "--parent", "08", "--title", "Fix gateway timeout", "--tasks-dir", str(tasks_dir), "--json")
    assert res_new.returncode == 0
    d_new = json.loads(res_new.stdout)
    assert d_new["id"] == "08.2"
    assert d_new["parent"] == "08"

    plan_text = (init_dir / "plan.md").read_text(encoding="utf-8")
    assert "### 08.2 - Fix gateway timeout" in plan_text
    assert "**Kind:** bug" in plan_text

    # Validation passes
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0


def test_cli_set_deps_emergent_file_preserves_surrounding_and_free_text(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    feat_dir = tasks_dir / "features"
    feat_dir.mkdir(parents=True)
    for tid in ("T001", "T002", "T003"):
        (feat_dir / f"{tid}-dummy.md").write_text(
            f"# {tid} Dummy\n\n- id: {tid}\n- title: Dummy\n- category: features\n- priority: P2\n- priority-reason: test\n- next-up: no\n- state: open\n- executor: kilo\n- depends-on: -\n- decider: -\n- sources: -\n- paths: -\n- handoff: -\n\n## Goal\nDummy\n",
            encoding="utf-8",
        )
    task_file = feat_dir / "T040-pipeline.md"
    original_content = """# T040 Pipeline

- id: T040
- title: Pipeline
- category: features
- priority: P2
- priority-reason: core flow
- next-up: no
- state: open
- executor: kilo
- depends-on: T001, T002 (staging only)
- decider: -
- sources: -
- paths: -
- handoff: Read instructions.

## Goal

Special characters & exact line preservation test.

## Notes

Some critical details that must not change!
"""
    task_file.write_text(original_content, encoding="utf-8")

    # Add T003
    res_add = run_cli("set-deps", "T040", "--add", "T003", "--tasks-dir", str(tasks_dir), "--json")
    assert res_add.returncode == 0
    content_after_add = task_file.read_text(encoding="utf-8")
    assert "- depends-on: T001, T002, T003 (staging only)" in content_after_add
    # Check that everything before and after - depends-on: is untouched
    assert content_after_add.split("- depends-on:")[0] == original_content.split("- depends-on:")[0]
    assert content_after_add.split("\n- decider:")[1] == original_content.split("\n- decider:")[1]

    # Remove T001
    res_rem = run_cli("set-deps", "T040", "--remove", "T001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_rem.returncode == 0
    content_after_rem = task_file.read_text(encoding="utf-8")
    assert "- depends-on: T002, T003 (staging only)" in content_after_rem
    assert content_after_rem.split("- depends-on:")[0] == original_content.split("- depends-on:")[0]
    assert content_after_rem.split("\n- decider:")[1] == original_content.split("\n- decider:")[1]


def test_cli_set_labels_file_and_folder_nodes(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    feat_dir = tasks_dir / "features"
    feat_dir.mkdir(parents=True)
    t_file = feat_dir / "T050-foo.md"
    t_file.write_text(
        """# T050 Foo

- id: T050
- title: Foo
- category: features
- priority: P2
- priority-reason: test
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read instructions.

## Goal

Foo.
""",
        encoding="utf-8",
    )

    t_folder = feat_dir / "T051-bar"
    t_folder.mkdir()
    readme = t_folder / "README.md"
    readme.write_text(
        """# T051 Bar

- id: T051
- title: Bar
- category: features
- priority: P2
- priority-reason: test
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read instructions.

## Goal

Bar.
""",
        encoding="utf-8",
    )

    # 1. set-labels on single file
    res1 = run_cli("set-labels", "T050", "--add", "ui,frontend", "--tasks-dir", str(tasks_dir), "--json")
    assert res1.returncode == 0
    assert "- labels: ui, frontend" in t_file.read_text(encoding="utf-8")

    # 2. set-labels on folder node
    res2 = run_cli("set-labels", "T051", "--add", "backend", "--tasks-dir", str(tasks_dir), "--json")
    assert res2.returncode == 0
    assert "- labels: backend" in readme.read_text(encoding="utf-8")

    # 3. remove label on single file
    res3 = run_cli("set-labels", "T050", "--remove", "frontend", "--tasks-dir", str(tasks_dir), "--json")
    assert res3.returncode == 0
    assert "- labels: ui" in t_file.read_text(encoding="utf-8")

    # 4. set-labels to exact list
    res4 = run_cli("set-labels", "T050", "--to", "auth,security", "--tasks-dir", str(tasks_dir), "--json")
    assert res4.returncode == 0
    assert "- labels: auth, security" in t_file.read_text(encoding="utf-8")


def test_cli_expand_collapse_depth_greater_than_two(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "09-deep"
    init_dir.mkdir(parents=True)
    (init_dir / "plan.md").write_text(
        """# 09 - Deep

- **Goal:** Deep nesting test.

## Tasks

### 09.1 - Level 1 Task
- **Status:** `open`
- **Goal:** Level 1.
""",
        encoding="utf-8",
    )

    # 1. Expand 09.1 (depth 1 -> 2)
    res_dry1 = run_cli("expand", "09.1", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry1.returncode == 0
    res_exp1 = run_cli("expand", "09.1", "--expect-plan-hash", json.loads(res_dry1.stdout)["plan_hash"], "--tasks-dir", str(tasks_dir), "--json")
    assert res_exp1.returncode == 0
    l1_folder = init_dir / "09.1-level-1-task"
    assert (l1_folder / "README.md").is_file()

    # 2. Add child 09.1.1 to 09.1
    res_dry_add = run_cli("child", "add", "09.1", "--title", "Level 2 Task", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry_add.returncode == 0
    assert json.loads(res_dry_add.stdout)["allocated_id"] == "09.1.1"
    res_add1 = run_cli("child", "add", "09.1", "--title", "Level 2 Task", "--expect-plan-hash", json.loads(res_dry_add.stdout)["plan_hash"], "--tasks-dir", str(tasks_dir), "--json")
    assert res_add1.returncode == 0

    # 3. Expand 09.1.1 (depth 2 -> 3)
    res_dry2 = run_cli("expand", "09.1.1", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry2.returncode == 0
    res_exp2 = run_cli("expand", "09.1.1", "--expect-plan-hash", json.loads(res_dry2.stdout)["plan_hash"], "--tasks-dir", str(tasks_dir), "--json")
    assert res_exp2.returncode == 0
    l2_folder = l1_folder / "09.1.1-level-2-task"
    assert (l2_folder / "README.md").is_file()

    # 4. Collapse 09.1.1 back to block in 09.1/README.md
    res_dry_col = run_cli("collapse", "09.1.1", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry_col.returncode == 0
    res_col = run_cli("collapse", "09.1.1", "--expect-plan-hash", json.loads(res_dry_col.stdout)["plan_hash"], "--tasks-dir", str(tasks_dir), "--json")
    assert res_col.returncode == 0
    assert not l2_folder.exists()
    assert "### 09.1.1 - Level 2 Task" in (l1_folder / "README.md").read_text(encoding="utf-8")


def test_cli_sync_index_initiative_status_cells(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "10-sample"
    init_dir.mkdir(parents=True)
    (init_dir / "plan.md").write_text(
        """# 10 - Sample

- **Goal:** Sample initiative.

## Tasks

### 10.1 - Done Task
- **Status:** `done` (2026-10-15)
- **Goal:** G1.

### 10.2 - Running Task
- **Status:** `in progress` (2026-10-16; kilo)
- **Goal:** G2.

### 10.3 - Open Task
- **Status:** `open`
- **Goal:** G3.
""",
        encoding="utf-8",
    )

    index_file = tasks_dir / "00-INDEX.md"
    index_file.write_text(
        """# Tasks Registry

## Initiatives

<!-- ai-orch:generated initiatives -->
| Priority | ID | Initiative | Status | Owner | Scope |
| --- | --- | --- | --- | --- | --- |
| P1 | 10 | [Sample](10-sample/plan.md) | open | owner | Sample |
<!-- ai-orch:generated initiatives -->

## Active Tasks
<!-- ai-orch:generated active-tasks -->
<!-- ai-orch:generated active-tasks -->

## Closed Tasks
<!-- ai-orch:generated closed-tasks -->
<!-- ai-orch:generated closed-tasks -->
""",
        encoding="utf-8",
    )

    res_sync = run_cli("sync-index", "--apply", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sync.returncode == 0

    idx_text = index_file.read_text(encoding="utf-8")
    assert "in progress (done: 10.1; running: 10.2)" in idx_text


def test_cli_questions_ask_blocks_child_ids(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "11-orch"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        """# 11 - Orchestration

- **Goal:** Test.

## Tasks

### 11.1 - Container Task
- **Status:** `open`
- **Goal:** C1.
""",
        encoding="utf-8",
    )

    # Expand 11.1 to folder and add child 11.1.1
    res_dry_exp = te.expand_node(tasks_dir, "11.1", dry_run=True)
    te.expand_node(tasks_dir, "11.1", expect_plan_hash=res_dry_exp["plan_hash"])

    res_dry_add = te.child_add(tasks_dir, "11.1", "Child leaf", dry_run=True)
    te.child_add(tasks_dir, "11.1", "Child leaf", expect_plan_hash=res_dry_add["plan_hash"])

    # Create emergent task T060 with child T060.1
    feat_dir = tasks_dir / "features"
    feat_dir.mkdir(parents=True)
    (feat_dir / "T060-worker.md").write_text(
        """# T060 Worker

- id: T060
- title: Worker
- category: features
- priority: P2
- priority-reason: test
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read instructions.

## Goal

Worker.

## Steps

- [ ] Steps.

## Verification

- [ ] Verification.
""",
        encoding="utf-8",
    )
    res_dry_cadd = te.child_add(tasks_dir, "T060", "Worker subtask", dry_run=True)
    te.child_add(tasks_dir, "T060", "Worker subtask", expect_plan_hash=res_dry_cadd["plan_hash"])

    # Ask question blocking child IDs 11.1.1 and T060.1
    res_ask = run_cli("questions", "ask", "--question", "Confirm API specs?", "--context", "Need confirmation on endpoints.", "--blocks", "11.1.1, T060.1", "--open-answer", "yes", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ask.returncode == 0
    d_ask = json.loads(res_ask.stdout)
    qid = d_ask["id"]

    tree = te.discover_task_tree(tasks_dir)
    assert tree["11.1.1"].state == "waiting"
    assert tree["T060.1"].state == "waiting"

    # Filter questions list by blocked child ID
    res_list = run_cli("questions", "list", "--blocks", "11.1.1", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list.returncode == 0
    d_list = json.loads(res_list.stdout)
    assert any(q["id"] == qid for q in d_list["questions"])

    # Validate passes with 0 errors
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0

    # Answer question -> unblocks back to open
    res_ans = run_cli("questions", "answer", qid, "--choice", "open", "--text", "Confirmed", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ans.returncode == 0

    tree_after = te.discover_task_tree(tasks_dir)
    assert tree_after["11.1.1"].canonical_state == "open"
    assert tree_after["T060.1"].canonical_state == "open"

    res_val_after = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val_after.returncode == 0


# ===========================================================================
# Task 12.12 Events & Questions Apply Tests
# ===========================================================================

def _read_ws_events(workspace: pathlib.Path) -> list[dict[str, Any]]:
    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import orchestration_events
    return orchestration_events.read_events(workspace)


def test_events_task_creation(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 1. tasks new from note
    res_note = run_cli("inbox", "add", "--title", "Feature note", "--tasks-dir", str(tasks_dir), "--json")
    assert res_note.returncode == 0
    note_id = json.loads(res_note.stdout)["id"]

    res_new = run_cli("new", "--title", "Feature task", "--from-note", note_id, "--category", "features", "--tasks-dir", str(tasks_dir), "--json")
    assert res_new.returncode == 0
    t_id = json.loads(res_new.stdout)["id"]

    events = _read_ws_events(tmp_path)
    ev_new = [e for e in events if e["type"] == "task.created" and e["subject"] == t_id]
    assert len(ev_new) == 1
    assert ev_new[0]["source"] == "tasks_engine"
    assert ev_new[0]["data"]["category"] == "features"
    assert ev_new[0]["data"]["state"] == "open"

    # 2. microtask
    res_micro = run_cli("micro", "--title", "Quick chore", "--kind", "chore", "--priority", "P3", "--tasks-dir", str(tasks_dir), "--json")
    assert res_micro.returncode == 0
    m_id = json.loads(res_micro.stdout)["id"]

    events = _read_ws_events(tmp_path)
    ev_micro = [e for e in events if e["type"] == "task.created" and e["subject"] == m_id]
    assert len(ev_micro) == 1
    assert ev_micro[0]["data"]["kind"] == "chore"
    assert ev_micro[0]["data"]["priority"] == "P3"

    # 3. child add
    res_dry = run_cli("child", "add", t_id, "--title", "Subtask 1", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0
    plan_hash = json.loads(res_dry.stdout)["plan_hash"]
    res_child = run_cli("child", "add", t_id, "--title", "Subtask 1", "--expect-plan-hash", plan_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_child.returncode == 0
    child_id = json.loads(res_child.stdout)["allocated_id"]

    events = _read_ws_events(tmp_path)
    ev_child = [e for e in events if e["type"] == "task.created" and e["subject"] == child_id]
    assert len(ev_child) == 1
    assert ev_child[0]["data"]["parent"] == t_id

    # 4. promote
    res_promo = run_cli("promote", m_id, "--category", "features", "--tasks-dir", str(tasks_dir), "--json")
    assert res_promo.returncode == 0
    events = _read_ws_events(tmp_path)
    ev_promo = [e for e in events if e["type"] == "task.created" and e["subject"] == m_id and e["data"].get("category") == "features"]
    assert len(ev_promo) == 1


def test_events_task_transitions_and_reopen(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 1. Initiative task transition
    init_dir = tasks_dir / "01-init"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text("# 01 Plan\n\n### 01.1 - Setup\n\n- **Status:** `open`\n- **Goal:** Setup\n", encoding="utf-8")

    res_tr1 = run_cli("transition", "01.1", "in progress", "--actor", "executor-1", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr1.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_init = [e for e in events if e["type"] == "task.transitioned" and e["subject"] == "01.1"]
    assert len(ev_init) == 1
    assert ev_init[0]["data"]["from"] == "open"
    assert ev_init[0]["data"]["to"] == "in progress"
    assert ev_init[0]["data"]["actor"] == "executor-1"
    assert ev_init[0]["actor"] == "executor-1"
    assert ev_init[0]["source"] == "tasks_engine"

    # 2. Emergent task transitions
    task_file = tasks_dir / "features" / "T001-test.md"
    _write_sample_task(task_file, task_id="T001", state="open")

    res_tr2 = run_cli("transition", "T001", "in progress", "--actor", "dev", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr2.returncode == 0
    res_tr3 = run_cli("transition", "T001", "delivered", "--actor", "dev", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr3.returncode == 0
    res_tr4 = run_cli("transition", "T001", "verified", "--verifier", "independent-session", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr4.returncode == 0
    res_tr5 = run_cli("transition", "T001", "done", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr5.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_t001 = [e for e in events if e["type"] == "task.transitioned" and e["subject"] == "T001"]
    assert len(ev_t001) == 4
    assert [e["data"]["to"] for e in ev_t001] == ["in progress", "delivered", "verified", "done"]

    # 3. Transition 01.1 to done, then reopen it
    assert run_cli("transition", "01.1", "delivered", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    assert run_cli("transition", "01.1", "verified", "--verifier", "independent-session", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    assert run_cli("transition", "01.1", "done", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    res_reopen_dry = run_cli("reopen", "01.1", "--reason", "Fix bug", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_reopen_dry.returncode == 0
    plan_hash = json.loads(res_reopen_dry.stdout)["plan_hash"]

    res_reopen = run_cli("reopen", "01.1", "--reason", "Fix bug", "--expect-plan-hash", plan_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_reopen.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_reopen = [e for e in events if e["type"] == "task.transitioned" and e["subject"] == "01.1"]
    last_ev = ev_reopen[-1]
    assert last_ev["data"]["from"] == "done"
    assert last_ev["data"]["to"] == "open"
    assert last_ev["data"]["reason"] == "Fix bug"


def test_events_structure_and_field_changes(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    init_dir = tasks_dir / "01-init"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text("# 01 Plan\n\n### 01.1 - Parent\n\n- **Status:** `open`\n- **Goal:** Parent goal\n", encoding="utf-8")

    # 1. expand inline block 01.1 to folder
    res_exp_dry = run_cli("expand", "01.1", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_exp_dry.returncode == 0
    p_hash = json.loads(res_exp_dry.stdout)["plan_hash"]
    res_exp = run_cli("expand", "01.1", "--expect-plan-hash", p_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_exp.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_exp = [e for e in events if e["type"] == "task.expanded" and e["subject"] == "01.1"]
    assert len(ev_exp) == 1

    # 2. collapse 01.1 folder back to block
    res_col_dry = run_cli("collapse", "01.1", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_col_dry.returncode == 0
    c_hash = json.loads(res_col_dry.stdout)["plan_hash"]
    res_col = run_cli("collapse", "01.1", "--expect-plan-hash", c_hash, "--tasks-dir", str(tasks_dir), "--json")
    assert res_col.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_col = [e for e in events if e["type"] == "task.collapsed" and e["subject"] == "01.1"]
    assert len(ev_col) == 1

    # 3. set-priority, size, deps, kind, labels on emergent task T001
    task_file = tasks_dir / "features" / "T001-structure.md"
    _write_sample_task(task_file, task_id="T001", state="open")
    task_file2 = tasks_dir / "features" / "T002-dep.md"
    _write_sample_task(task_file2, task_id="T002", state="open")

    assert run_cli("set-priority", "T001", "P0", "--reason", "Urgent", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    assert run_cli("set-size", "T001", "M", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    assert run_cli("set-deps", "T001", "--add", "T002", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    assert run_cli("set-kind", "T001", "bug", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    assert run_cli("set-labels", "T001", "--add", "backend", "--tasks-dir", str(tasks_dir), "--json").returncode == 0

    events = _read_ws_events(tmp_path)
    ev_updates = [e for e in events if e["type"] == "task.updated" and e["subject"] == "T001"]
    fields_updated = [e["data"]["field"] for e in ev_updates]
    assert "priority" in fields_updated
    assert "size" in fields_updated
    assert "depends_on" in fields_updated
    assert "kind" in fields_updated
    assert "labels" in fields_updated


def test_events_attachments(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "features" / "T001-att.md"
    _write_sample_task(task_file, task_id="T001", state="open")

    sample_doc = tmp_path / "spec.pdf"
    sample_doc.write_bytes(b"%PDF-1.4 sample content")

    res_att = run_cli("attach", "T001", "--file", str(sample_doc), "--tasks-dir", str(tasks_dir), "--json")
    assert res_att.returncode == 0
    att_name = json.loads(res_att.stdout)["attachment"]

    events = _read_ws_events(tmp_path)
    ev_att = [e for e in events if e["type"] == "task.attached" and e["subject"] == "T001"]
    assert len(ev_att) == 1
    assert ev_att[0]["data"]["name"] == att_name

    res_det = run_cli("detach", "T001", "--name", att_name, "--tasks-dir", str(tasks_dir), "--json")
    assert res_det.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_det = [e for e in events if e["type"] == "task.detached" and e["subject"] == "T001"]
    assert len(ev_det) == 1
    assert ev_det[0]["data"]["name"] == att_name


def test_events_questions_and_apply(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "features" / "T001-q.md"
    _write_sample_task(task_file, task_id="T001", state="open")

    # 1. Ask question Q001
    res_ask = run_cli(
        "questions", "ask",
        "--question", "Use SQLite or PostgreSQL?",
        "--context", "Storage decision",
        "--option", "A=SQLite: Simpler",
        "--option", "B=PostgreSQL: Scalable",
        "--blocks", "T001",
        "--asked-by", "architect",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_ask.returncode == 0
    qid = json.loads(res_ask.stdout)["id"]

    events = _read_ws_events(tmp_path)
    ev_ask = [e for e in events if e["type"] == "question.asked" and e["subject"] == qid]
    assert len(ev_ask) == 1
    assert ev_ask[0]["actor"] == "architect"
    assert ev_ask[0]["data"]["question"] == "Use SQLite or PostgreSQL?"

    # 2. Answer question Q001
    res_ans = run_cli(
        "questions", "answer", qid,
        "--choice", "A",
        "--text", "Go with SQLite for simplicity",
        "--by", "lead-dev",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_ans.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_ans = [e for e in events if e["type"] == "question.answered" and e["subject"] == qid]
    assert len(ev_ans) == 1
    assert ev_ans[0]["actor"] == "lead-dev"
    assert ev_ans[0]["data"]["choice"] == "A"

    # 3. Apply question Q001
    res_app = run_cli(
        "questions", "apply", qid,
        "--by", "lead-dev",
        "--ref", "commit-abcdef",
        "--note", "Adopted SQLite in sqlite_db.py",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_app.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_app = [e for e in events if e["type"] == "question.applied" and e["subject"] == qid]
    assert len(ev_app) == 1
    assert ev_app[0]["actor"] == "lead-dev"
    assert ev_app[0]["data"]["ref"] == "commit-abcdef"
    assert ev_app[0]["data"]["note"] == "Adopted SQLite in sqlite_db.py"

    # 4. Ask Q002 and withdraw it
    res_ask2 = run_cli(
        "questions", "ask",
        "--question", "Enable redis cache?",
        "--context", "Caching layer",
        "--blocks", "-",
        "--open-answer", "yes",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_ask2.returncode == 0
    qid2 = json.loads(res_ask2.stdout)["id"]

    res_with = run_cli(
        "questions", "withdraw", qid2,
        "--reason", "Not needed at this scale",
        "--by", "architect",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_with.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_with = [e for e in events if e["type"] == "question.withdrawn" and e["subject"] == qid2]
    assert len(ev_with) == 1
    assert ev_with[0]["actor"] == "architect"
    assert ev_with[0]["data"]["reason"] == "Not needed at this scale"


def test_events_inbox_lifecycle(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 1. Draft note
    res_add1 = run_cli("inbox", "add", "--title", "Draft Idea", "--status", "draft", "--tasks-dir", str(tasks_dir), "--json")
    assert res_add1.returncode == 0
    n1 = json.loads(res_add1.stdout)["id"]

    events = _read_ws_events(tmp_path)
    ev_n1 = [e for e in events if e["type"] == "note.created" and e["subject"] == n1]
    assert len(ev_n1) == 1

    # 2. Ready note
    res_add2 = run_cli("inbox", "add", "--title", "Ready Idea", "--status", "ready", "--tasks-dir", str(tasks_dir), "--json")
    assert res_add2.returncode == 0
    n2 = json.loads(res_add2.stdout)["id"]

    events = _read_ws_events(tmp_path)
    ev_n2 = [e for e in events if e["type"] == "note.ready" and e["subject"] == n2]
    assert len(ev_n2) == 1

    # 3. Edit draft note to ready
    res_edit = run_cli("inbox", "edit", n1, "--status", "ready", "--tasks-dir", str(tasks_dir), "--json")
    assert res_edit.returncode == 0

    events = _read_ws_events(tmp_path)
    ev_n1_ready = [e for e in events if e["type"] == "note.ready" and e["subject"] == n1]
    assert len(ev_n1_ready) == 1

    # 4. Attach & detach
    doc_file = tmp_path / "note_att.txt"
    doc_file.write_text("Sample text", encoding="utf-8")
    res_att = run_cli("inbox", "attach", n1, "--file", str(doc_file), "--tasks-dir", str(tasks_dir), "--json")
    assert res_att.returncode == 0
    att_name = json.loads(res_att.stdout)["attachment"]

    events = _read_ws_events(tmp_path)
    assert any(e["type"] == "note.attached" and e["subject"] == n1 for e in events)

    res_det = run_cli("inbox", "detach", n1, "--name", att_name, "--tasks-dir", str(tasks_dir), "--json")
    assert res_det.returncode == 0
    events = _read_ws_events(tmp_path)
    assert any(e["type"] == "note.detached" and e["subject"] == n1 for e in events)

    # 5. Resolve note N001
    res_res = run_cli("inbox", "resolve", n1, "--produced", "T001", "--by", "triage-agent", "--tasks-dir", str(tasks_dir), "--json")
    assert res_res.returncode == 0
    events = _read_ws_events(tmp_path)
    ev_res = [e for e in events if e["type"] == "note.processed" and e["subject"] == n1]
    assert len(ev_res) == 1
    assert ev_res[0]["actor"] == "triage-agent"
    assert ev_res[0]["data"]["status"] == "processed"

    # 6. Discard note N002
    res_disc = run_cli("inbox", "discard", n2, "--reason", "Not relevant", "--tasks-dir", str(tasks_dir), "--json")
    assert res_disc.returncode == 0
    events = _read_ws_events(tmp_path)
    ev_disc = [e for e in events if e["type"] == "note.processed" and e["subject"] == n2]
    assert len(ev_disc) == 1
    assert ev_disc[0]["data"]["status"] == "discarded"

    # 7. Reopen note N002
    res_reopen = run_cli("inbox", "reopen", n2, "--tasks-dir", str(tasks_dir), "--json")
    assert res_reopen.returncode == 0
    events = _read_ws_events(tmp_path)
    ev_reopen = [e for e in events if e["type"] == "note.ready" and e["subject"] == n2]
    assert len(ev_reopen) == 2


def test_events_no_event_on_dry_run_or_refusal(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    init_dir = tasks_dir / "01-init"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text("# 01 Plan\n\n### 01.1 - Setup\n\n- **Status:** `done`\n- **Goal:** Setup\n", encoding="utf-8")

    task_file = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(task_file, task_id="T001", state="open")

    events_before = _read_ws_events(tmp_path)
    assert len(events_before) == 0

    # Dry-run reopen on done task
    res1 = run_cli("reopen", "01.1", "--reason", "Test dry run", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res1.returncode == 0
    assert len(_read_ws_events(tmp_path)) == 0

    # Illegal transition refusal (open -> done directly)
    res2 = run_cli("transition", "T001", "done", "--tasks-dir", str(tasks_dir), "--json")
    assert res2.returncode != 0
    assert len(_read_ws_events(tmp_path)) == 0

    # Dry-run child add
    res3 = run_cli("child", "add", "T001", "--title", "Sub 1", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res3.returncode == 0
    assert len(_read_ws_events(tmp_path)) == 0

    # Child add with invalid plan hash refusal
    res4 = run_cli("child", "add", "T001", "--title", "Sub 1", "--expect-plan-hash", "badhash", "--tasks-dir", str(tasks_dir), "--json")
    assert res4.returncode != 0
    assert len(_read_ws_events(tmp_path)) == 0

    # Questions apply on non-existent question
    res5 = run_cli("questions", "apply", "Q999", "--tasks-dir", str(tasks_dir), "--json")
    assert res5.returncode != 0
    assert len(_read_ws_events(tmp_path)) == 0


def test_events_seq_ordering_matches_writes(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 1. Add note
    res1 = run_cli("inbox", "add", "--title", "Order test note", "--tasks-dir", str(tasks_dir), "--json")
    assert res1.returncode == 0
    n_id = json.loads(res1.stdout)["id"]

    # 2. Edit note to ready
    res2 = run_cli("inbox", "edit", n_id, "--status", "ready", "--tasks-dir", str(tasks_dir), "--json")
    assert res2.returncode == 0

    # 3. Create task from note
    res3 = run_cli("new", "--title", "Order test task", "--from-note", n_id, "--category", "features", "--tasks-dir", str(tasks_dir), "--json")
    assert res3.returncode == 0
    t_id = json.loads(res3.stdout)["id"]

    # 4. Set priority
    res4 = run_cli("set-priority", t_id, "P1", "--tasks-dir", str(tasks_dir), "--json")
    assert res4.returncode == 0

    # 5. Transition task
    res5 = run_cli("transition", t_id, "in progress", "--tasks-dir", str(tasks_dir), "--json")
    assert res5.returncode == 0

    # 6. Ask question
    res6 = run_cli("questions", "ask", "--question", "Approval needed?", "--context", "Gate", "--blocks", t_id, "--open-answer", "yes", "--tasks-dir", str(tasks_dir), "--json")
    assert res6.returncode == 0
    q_id = json.loads(res6.stdout)["id"]

    # 7. Answer question
    res7 = run_cli("questions", "answer", q_id, "--choice", "open", "--text", "Approved", "--tasks-dir", str(tasks_dir), "--json")
    assert res7.returncode == 0

    # 8. Apply question
    res8 = run_cli("questions", "apply", q_id, "--ref", t_id, "--tasks-dir", str(tasks_dir), "--json")
    assert res8.returncode == 0

    events = _read_ws_events(tmp_path)
    assert len(events) >= 8

    # Sequence numbers must be strictly monotonically increasing matching write order
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))

    # Check key types present in order
    types = [e["type"] for e in events]
    assert types[0] == "note.created"
    assert types[1] == "note.ready"
    assert types[2] == "task.created"
    assert types[3] == "task.updated"
    assert types[4] == "task.transitioned"
    assert "question.asked" in types
    assert "question.answered" in types
    assert types[-1] == "question.applied"


def test_events_graceful_fallback_when_module_unavailable(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # Monkeypatch _get_orchestration_events to return None
    monkeypatch.setattr(te, "_get_orchestration_events", lambda: None)

    # Microtask creation succeeds without error
    ok_m, res_m = te.tasks_micro(tasks_dir, "Fallback microtask")
    assert ok_m is True

    # Transition succeeds without error
    ok_tr, res_tr = te.transition_task(tasks_dir, res_m["id"], "in progress")
    assert ok_tr is True

    # Questions ask/answer/apply succeed without error
    ok_ask, res_ask = te.ask_question(tasks_dir, question="Fallback Q?", context="Ctx", blocks="-", open_answer="yes")
    assert ok_ask is True
    ok_ans, res_ans = te.answer_question(tasks_dir, res_ask["id"], choice="open", text="ok")
    assert ok_ans is True
    ok_app, res_app = te.apply_question(tasks_dir, res_ask["id"], ref="ref-1")
    assert ok_app is True


def test_questions_apply_and_ledger_validation(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # Create task
    task_file = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(task_file, task_id="T001", state="open")

    # Ask question Q001 blocking T001
    ok_ask, res_ask = te.ask_question(
        tasks_dir,
        question="Use JWT or session cookies?",
        context="Auth mechanism",
        blocks="T001",
        open_answer="yes",
    )
    assert ok_ask is True
    qid = res_ask["id"]

    # 1. Apply before answered is refused
    ok_app1, res_app1 = te.apply_question(tasks_dir, qid)
    assert ok_app1 is False
    assert "expected 'answered'" in res_app1["error"]

    # 2. Answer question
    ok_ans, _ = te.answer_question(tasks_dir, qid, choice="open", text="Use JWT with rotation")
    assert ok_ans is True

    # 3. Dry-run apply succeeds without writing ledger
    ok_dry, res_dry = te.apply_question(tasks_dir, qid, dry_run=True, note="Dry run test")
    assert ok_dry is True
    assert res_dry["dry_run"] is True
    assert not (tasks_dir / "questions" / "applied.jsonl").exists()

    # 4. Real apply writes ledger and emits event
    ok_real, res_real = te.apply_question(
        tasks_dir,
        qid,
        by="security-lead",
        ref="commit-123456",
        note="Implemented JWT rotation",
    )
    assert ok_real is True
    assert res_real["status"] == "applied"
    assert res_real["record"]["question"] == qid
    assert res_real["record"]["by"] == "security-lead"
    assert res_real["record"]["ref"] == "commit-123456"

    # Ledger file verification
    ledger_file = tasks_dir / "questions" / "applied.jsonl"
    assert ledger_file.is_file()
    records = te.read_applied_ledger(tasks_dir)
    assert len(records) == 1
    assert records[0]["question"] == qid
    assert records[0]["by"] == "security-lead"

    # 5. Re-apply without force is refused
    ok_dup, res_dup = te.apply_question(tasks_dir, qid)
    assert ok_dup is False
    assert "already recorded as applied" in res_dup["error"]

    # 6. Re-apply with force succeeds
    ok_force, res_force = te.apply_question(tasks_dir, qid, by="security-lead", force=True, note="Second application")
    assert ok_force is True
    records2 = te.read_applied_ledger(tasks_dir)
    assert len(records2) == 2

    # 7. Discover questions reports applied status (latest record)
    questions = te.discover_questions(tasks_dir)
    target_q = next(q for q in questions if q["id"] == qid)
    assert target_q["applied"] is True
    assert target_q["applied_record"]["note"] == "Second application"

    # 8. Show question reports applied
    ok_show, res_show = te.show_question(tasks_dir, qid)
    assert ok_show is True
    assert res_show["question"]["applied"] is True

    # 9. CLI test
    res_cli_show = run_cli("questions", "show", qid, "--tasks-dir", str(tasks_dir))
    assert res_cli_show.returncode == 0
    assert "Applied by : security-lead" in res_cli_show.stdout

    # 10. Question file markdown format remains completely valid (only Context, Options, Answer)
    q_file = tasks_dir / "questions" / f"{qid}-use-jwt-or-session-cookies.md"
    assert q_file.is_file()
    content = q_file.read_text(encoding="utf-8")
    sections = [line for line in content.splitlines() if line.startswith("## ")]
    assert sections == ["## Context", "## Options", "## Answer"]

    # Validation passes with 0 errors
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    val_data = json.loads(res_val.stdout)
    assert val_data["errors"] == []


# ---------------------------------------------------------------------------
# Task 11.4: Closed-Apart Placement at Every Level (Ship, Archive, Closed Sections, Reopen)
# ---------------------------------------------------------------------------


def test_11_4_leaf_block_closing_moves_to_closed_and_reopen_moves_back(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-sample"
    init_dir.mkdir()
    plan = init_dir / "plan.md"
    plan.write_text(
        """# 07 - Sample

- **Goal:** Sample goal.

## Tasks

### 07.1 - First task
- **Status:** `delivered`
- **Goal:** Goal 1.

### 07.2 - Second task
- **Status:** `open`
- **Goal:** Goal 2.
""",
        encoding="utf-8",
    )

    # Transition 07.1 to verified, then to done
    ok, res = te.transition_task(tasks_dir, "07.1", "verified", actor="owner")
    assert ok is True
    ok, res = te.transition_task(tasks_dir, "07.1", "done", actor="owner")
    assert ok is True

    text = plan.read_text(encoding="utf-8")
    assert "## Closed" in text
    m_tasks = re.search(r"^##\s+Tasks", text, re.MULTILINE)
    m_closed = re.search(r"^##\s+Closed", text, re.MULTILINE)
    m_071 = re.search(r"^###\s+07\.1", text, re.MULTILINE)
    m_072 = re.search(r"^###\s+07\.2", text, re.MULTILINE)
    assert m_tasks is not None and m_closed is not None and m_071 is not None and m_072 is not None
    assert m_tasks.start() < m_072.start() < m_closed.start() < m_071.start()

    tree = te.discover_task_tree(tasks_dir)
    assert tree["07.1"].canonical_state == "done"
    assert tree["07.1"].in_closed_section is True
    assert tree["07.2"].canonical_state == "open"
    assert tree["07.2"].in_closed_section is False

    assert te.check_markdown_links(tasks_dir) == []

    # Reopening 07.1 moves it back to open section before 07.2, and removes empty ## Closed
    res_dry = te.reopen_node(tasks_dir, "07.1", reason="Need recheck", dry_run=True)
    assert res_dry["ok"] is True
    assert res_dry["dry_run"] is True
    plan_hash = res_dry["plan_hash"]

    # Refuse wrong hash
    res_fail = te.reopen_node(tasks_dir, "07.1", reason="Need recheck", expect_plan_hash="bad" + plan_hash[3:])
    assert res_fail["ok"] is False
    assert "Plan hash mismatch" in res_fail["error"]

    res_apply = te.reopen_node(tasks_dir, "07.1", reason="Need recheck", expect_plan_hash=plan_hash)
    assert res_apply["ok"] is True

    text2 = plan.read_text(encoding="utf-8")
    assert "## Closed" not in text2
    m_071_new = re.search(r"^###\s+07\.1", text2, re.MULTILINE)
    m_072_new = re.search(r"^###\s+07\.2", text2, re.MULTILINE)
    assert m_071_new is not None and m_072_new is not None
    assert m_071_new.start() < m_072_new.start()
    assert "- **Status:** `open`" in text2
    assert "Need recheck" in text2

    tree2 = te.discover_task_tree(tasks_dir)
    assert tree2["07.1"].canonical_state == "open"
    assert tree2["07.1"].in_closed_section is False


def test_11_4_folder_child_closing_moves_to_done_under_parent(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "07-hierarchy"
    init_dir.mkdir()
    plan = init_dir / "plan.md"
    plan.write_text(
        """# 07 - Hierarchy

- **Goal:** Hierarchy goal.

## Tasks

### 07.1 - Folder Container
- **Expanded:** [07.1-sub/](07.1-sub/README.md)
""",
        encoding="utf-8",
    )

    sub_dir = init_dir / "07.1-sub"
    sub_dir.mkdir()
    sub_readme = sub_dir / "README.md"
    sub_readme.write_text(
        """# 07.1 - Folder Container

- **Goal:** Sub goal.

## Subtasks

### 07.1.1 - Leaf one
- **Status:** `delivered`
- **Goal:** L1.

### 07.1.2 - Leaf two
- **Status:** `delivered`
- **Goal:** L2.
""",
        encoding="utf-8",
    )

    # Close 07.1.1
    te.transition_task(tasks_dir, "07.1.1", "verified", actor="owner")
    te.transition_task(tasks_dir, "07.1.1", "done", actor="owner")

    tree = te.discover_task_tree(tasks_dir)
    assert tree["07.1"].in_done is False
    assert (init_dir / "07.1-sub").is_dir()

    # Close 07.1.2 -> now all children are done! Container closes on derivation
    te.transition_task(tasks_dir, "07.1.2", "verified", actor="owner")
    ok, res = te.transition_task(tasks_dir, "07.1.2", "done", actor="owner")
    assert ok is True

    # Folder child should have moved to done/07.1-sub
    assert not (init_dir / "07.1-sub").exists()
    done_sub = init_dir / "done" / "07.1-sub"
    assert done_sub.is_dir()
    assert (done_sub / "README.md").is_file()

    # In parent plan.md, expanded bullet points to done/ and block is in ## Closed
    plan_t = plan.read_text(encoding="utf-8")
    assert "[done/07.1-sub/](done/07.1-sub/README.md)" in plan_t
    m_cl = re.search(r"^##\s+Closed", plan_t, re.MULTILINE)
    m_blk = re.search(r"^###\s+07\.1", plan_t, re.MULTILINE)
    assert m_cl is not None and m_blk is not None
    assert m_cl.start() < m_blk.start()

    tree_done = te.discover_task_tree(tasks_dir)
    assert tree_done["07.1"].in_done is True
    assert tree_done["07.1.1"].in_done is True
    assert tree_done["07.1.2"].in_done is True

    assert te.check_markdown_links(tasks_dir) == []

    # Now reopen 07.1.1 -> folder should restore back to 07.1-sub, and block out of ## Closed
    res_dry = te.reopen_node(tasks_dir, "07.1.1", reason="Need fix in leaf 1", dry_run=True)
    assert res_dry["ok"] is True
    res_apply = te.reopen_node(tasks_dir, "07.1.1", reason="Need fix in leaf 1", expect_plan_hash=res_dry["plan_hash"])
    assert res_apply["ok"] is True

    assert (init_dir / "07.1-sub").is_dir()
    assert not (init_dir / "done" / "07.1-sub").exists()
    plan_t2 = plan.read_text(encoding="utf-8")
    assert "[07.1-sub/](07.1-sub/README.md)" in plan_t2
    assert "done/07.1-sub" not in plan_t2

    tree_rest = te.discover_task_tree(tasks_dir)
    assert tree_rest["07.1"].in_done is False
    assert tree_rest["07.1.1"].canonical_state == "open"
    assert te.check_markdown_links(tasks_dir) == []


def test_11_4_ship_initiative_creates_summary_rewrites_links_and_reopen_restores(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "11-subtasks"
    init_dir.mkdir()
    plan = init_dir / "plan.md"
    plan.write_text(
        """# 11 - Subtasks

> **Derived from spec:** [`../specs/subtasks.md`](../specs/subtasks.md)
> **Status:** `done`

- **Goal:** Complete subtasks.

## Tasks

### 11.1 - Leaf task
- **Status:** `done` (2026-10-18)
- **Goal:** G1.
""",
        encoding="utf-8",
    )

    specs_dir = tasks_dir / "specs"
    specs_dir.mkdir()
    spec = specs_dir / "subtasks.md"
    spec.write_text(
        """# Subtasks Spec

Drives: initiative [11](../11-subtasks/plan.md)
""",
        encoding="utf-8",
    )

    index = tasks_dir / "00-INDEX.md"
    index.write_text(
        """# Index

| Priority | # | Initiative | Status | Depends on | Size |
| --- | --- | --- | --- | --- | --- |
| 1 | 11 | [Subtasks](11-subtasks/plan.md) | done | - | M |
""",
        encoding="utf-8",
    )

    # 1. Preview with dry-run
    res_dry = te.ship_initiative(tasks_dir, "11", dry_run=True)
    assert res_dry["ok"] is True
    assert res_dry["dry_run"] is True
    assert (init_dir / "plan.md").is_file()
    plan_hash = res_dry["plan_hash"]

    # 2. Refuse without plan hash
    res_no_hash = te.ship_initiative(tasks_dir, "11")
    assert res_no_hash["ok"] is False
    assert "Applying ship requires --expect-plan-hash" in res_no_hash["error"]

    # 3. Apply ship with plan hash
    res_ship = te.ship_initiative(tasks_dir, "11", expect_plan_hash=plan_hash)
    assert res_ship["ok"] is True
    assert not init_dir.exists()
    done_init = tasks_dir / "done" / "11-subtasks"
    assert done_init.is_dir()
    assert (done_init / "plan.md").is_file()
    assert (done_init / "summary.md").is_file()

    # summary.md skeleton content
    sum_t = (done_init / "summary.md").read_text(encoding="utf-8")
    assert "# Summary: 11 - Subtasks" in sum_t
    assert "## Outcome" in sum_t
    assert "## Deviations" in sum_t
    assert "## Follow-ups" in sum_t

    # In spec: link rewritten to ../done/11-subtasks/plan.md
    spec_t = spec.read_text(encoding="utf-8")
    assert "[11](../done/11-subtasks/plan.md)" in spec_t

    # In 00-INDEX.md: link rewritten to done/11-subtasks/plan.md
    index_t = index.read_text(encoding="utf-8")
    assert "[Subtasks](done/11-subtasks/plan.md)" in index_t

    # In plan.md: link to ../specs/ adjusted to ../../specs/
    plan_done_t = (done_init / "plan.md").read_text(encoding="utf-8")
    assert "[`../specs/subtasks.md`](../../specs/subtasks.md)" in plan_done_t

    # All relative links resolve
    broken = te.check_markdown_links(tasks_dir)
    assert broken == []

    # 4. Reopen leaf 11.1 -> restores initiative back to tasks/11-subtasks
    res_reop_dry = te.reopen_node(tasks_dir, "11.1", reason="Found regression", dry_run=True)
    assert res_reop_dry["ok"] is True
    res_reop = te.reopen_node(tasks_dir, "11.1", reason="Found regression", expect_plan_hash=res_reop_dry["plan_hash"])
    assert res_reop["ok"] is True

    assert init_dir.is_dir()
    assert not done_init.exists()

    sum_rest = (init_dir / "summary.md").read_text(encoding="utf-8")
    assert "- **Reopened:**" in sum_rest and "Found regression" in sum_rest

    spec_rest = spec.read_text(encoding="utf-8")
    assert "[11](../11-subtasks/plan.md)" in spec_rest

    index_rest = index.read_text(encoding="utf-8")
    assert "[Subtasks](11-subtasks/plan.md)" in index_rest

    plan_rest = (init_dir / "plan.md").read_text(encoding="utf-8")
    assert "[`../specs/subtasks.md`](../specs/subtasks.md)" in plan_rest

    assert te.check_markdown_links(tasks_dir) == []


def test_11_4_questions_never_move(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    q_dir = tasks_dir / "questions"
    q_dir.mkdir()

    # Ask question Q001
    ok_ask, res_ask = te.ask_question(
        tasks_dir,
        question="Sample question?",
        context="Context for Q001.",
        options=[("A", "Yes", "Proceed"), ("B", "No", "Abort")],
        blocks="-",
    )
    assert ok_ask is True
    qid = res_ask["id"]

    # Answer question
    ok_ans, res_ans = te.answer_question(tasks_dir, qid, choice="A", text="Chose A")
    assert ok_ans is True
    q_file = pathlib.Path(res_ask["file_path"])
    assert q_file.is_file()
    assert not (q_dir / "closed").exists()

    # Running archive does not move questions
    res_arch = te.archive_misplaced(tasks_dir, dry_run=True)
    assert res_arch["ok"] is True
    for op in res_arch["plan"]:
        assert "questions" not in op["path"]

    assert q_file.is_file()
    assert not (q_dir / "closed").exists()


def test_11_4_tasks_archive_dry_run_and_apply(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "08-misplaced"
    init_dir.mkdir()
    plan = init_dir / "plan.md"
    plan.write_text(
        """# 08 - Misplaced

- **Goal:** Test archive.

## Tasks

### 08.1 - Done block in open section
- **Status:** `done` (2026-10-17)
- **Goal:** G1.

### 08.2 - Open block
- **Status:** `open`
- **Goal:** G2.
""",
        encoding="utf-8",
    )

    # Emergent task done in open category
    feat_dir = tasks_dir / "features"
    feat_dir.mkdir()
    em_file = feat_dir / "T001-feature.md"
    _write_sample_task(em_file, task_id="T001")
    te.transition_task(tasks_dir, "T001", "in progress")
    te.transition_task(tasks_dir, "T001", "delivered")
    te.transition_task(tasks_dir, "T001", "verified", actor="owner")
    em_text = em_file.read_text(encoding="utf-8")
    em_text = re.sub(r"^- state:\s*.*$", "- state: done", em_text, flags=re.MULTILINE)
    em_file.write_text(em_text, encoding="utf-8")

    # Dry-run archive
    res_dry = te.archive_misplaced(tasks_dir, dry_run=True)
    assert res_dry["ok"] is True
    assert res_dry["dry_run"] is True
    assert res_dry["archived_count"] == 2
    assert "08.1" in res_dry["misplaced_blocks"]
    assert "T001" in res_dry["misplaced_emergent"]

    assert em_file.is_file()
    assert "## Closed" not in plan.read_text(encoding="utf-8")

    # Apply archive
    res_apply = te.archive_misplaced(tasks_dir, expect_plan_hash=res_dry["plan_hash"])
    assert res_apply["ok"] is True
    assert res_apply["archived_count"] == 2

    # Verify 08.1 moved to ## Closed in plan.md
    plan_t = plan.read_text(encoding="utf-8")
    assert "## Closed" in plan_t
    m_cl = re.search(r"^##\s+Closed", plan_t, re.MULTILINE)
    m_081 = re.search(r"^###\s+08\.1", plan_t, re.MULTILINE)
    m_082 = re.search(r"^###\s+08\.2", plan_t, re.MULTILINE)
    assert m_082.start() < m_cl.start() < m_081.start()

    # Verify T001 moved to tasks/done/features/
    assert not em_file.exists()
    assert (tasks_dir / "done" / "features" / "T001-feature.md").is_file()

    # Second archive reports nothing to do
    res_dry2 = te.archive_misplaced(tasks_dir, dry_run=True)
    assert res_dry2["ok"] is True
    assert res_dry2["archived_count"] == 0
    assert res_dry2["plan"] == []


def test_11_4_validation_closed_apart_rules(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "09-validation"
    init_dir.mkdir()
    plan = init_dir / "plan.md"
    plan.write_text(
        """# 09 - Validation

- **Goal:** Test validation.

## Tasks

### 09.1 - Open block
- **Status:** `open`
- **Goal:** G1.

## Closed

### 09.2 - Open in closed section
- **Status:** `open`
- **Goal:** G2.
""",
        encoding="utf-8",
    )

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("in ## Closed but state is 'open'" in e for e in errors)


def test_11_4_cli_ship_and_archive(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    init_dir = tasks_dir / "12-cli"
    init_dir.mkdir()
    plan = init_dir / "plan.md"
    plan.write_text(
        """# 12 - CLI Ship

- **Goal:** Test CLI ship.

## Tasks

### 12.1 - Task 1
- **Status:** `done` (2026-10-18)
- **Goal:** G1.
""",
        encoding="utf-8",
    )

    # Dry-run CLI ship
    res_dry = run_cli("ship", "12", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0
    data_dry = json.loads(res_dry.stdout)
    assert data_dry["ok"] is True
    plan_hash = data_dry["plan_hash"]

    # Apply CLI ship
    res_ship = run_cli("ship", "12", "--expect-plan-hash", plan_hash, "--tasks-dir", str(tasks_dir))
    assert res_ship.returncode == 0
    assert "[ok] shipped initiative 12 -> done/12-cli" in res_ship.stdout

    # CLI archive
    res_arch = run_cli("archive", "--dry-run", "--tasks-dir", str(tasks_dir))
    assert res_arch.returncode == 0
    assert "[ok] Nothing to archive." in res_arch.stdout


# ==============================================================================
# T025: Short Title Tests (derivation, parsing, validation, creation, set-short)
# ==============================================================================


def test_derive_short_title() -> None:
    # 1. Dropping leading stop words ("the", "a", "an")
    assert te.derive_short_title("The unified task and state model") == "unified task state model"
    assert te.derive_short_title("A quick bug fix") == "quick bug fix"
    assert te.derive_short_title("An operational review") == "operational review"

    # 2. Stripping leading IDs
    assert te.derive_short_title("T025 Short title field for tasks and questions") == "Short title field tasks"
    assert te.derive_short_title("T007 - Shared release manager") == "Shared release manager"
    assert te.derive_short_title("12.16 UI proposal confirm") == "UI proposal confirm"
    assert te.derive_short_title("Q004 Permission policy for headless runs") == "Permission policy headless runs"
    assert te.derive_short_title("UC001 User authentication flow") == "User authentication flow"
    assert te.derive_short_title("N003 Brainstorming session notes") == "Brainstorming session notes"

    # 3. Stripping backticks
    assert te.derive_short_title("T007 - `shared release manager`") == "shared release manager"

    # 4. Parentheticals
    assert te.derive_short_title("12.16 (UI proposal confirm)") == "UI proposal confirm"
    assert te.derive_short_title("Deploy service (production v1.2)") == "Deploy service"

    # 5. Length <= 40 chars, no trailing punctuation
    res = te.derive_short_title("Fix bug: part one.")
    assert not res.endswith(".")
    assert len(res) <= 40
    assert 1 <= len(res.split()) <= 5

    # 6. Fallback on empty or symbol-only
    assert te.derive_short_title("") == "untitled"
    assert te.derive_short_title("---") == "untitled"


def test_validate_short_title() -> None:
    # Valid
    assert te.validate_short_title("short title") == []
    assert te.validate_short_title("one two three four five") == []
    assert te.validate_short_title("word") == []

    # Empty / dash
    assert len(te.validate_short_title("")) > 0
    assert len(te.validate_short_title("-")) > 0
    assert len(te.validate_short_title("   ")) > 0

    # Word count > 5
    issues = te.validate_short_title("one two three four five six")
    assert any("expected 1-5 words" in i for i in issues)

    # Length > 40 chars
    long_val = "word " * 9  # 45 chars
    issues = te.validate_short_title(long_val.strip())
    assert any("exceeds 40 characters" in i for i in issues)

    # Trailing punctuation
    for punct in [".", ",", ";", ":", "!", "?", "-", "—", "–"]:
        issues = te.validate_short_title(f"short title{punct}")
        assert any("has trailing punctuation" in i for i in issues)


def test_parse_short_title_all_kinds(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "micro").mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "_inbox" / "to-analyze" / "20261018-note").mkdir(parents=True)

    # 1. Full emergent task WITH short
    t1_path = tasks_dir / "features" / "T001-with-short.md"
    t1_path.write_text(
        "# T001 Feature One\n\n"
        "- id: T001\n- title: Feature One\n- category: features\n- priority: P1\n"
        "- priority-reason: core\n- next-up: no\n- state: open\n- executor: kilo\n"
        "- depends-on: -\n- decider: -\n- sources: -\n- paths: -\n- handoff: -\n"
        "- short: feature one label\n\n## Goal\n\nGoal.\n\n## Steps\n\nSteps.\n\n## Verification\n\nVerify.\n",
        encoding="utf-8",
    )
    parsed_t1 = te.parse_emergent_task_file(t1_path, tasks_dir)
    assert parsed_t1["short"] == "feature one label"
    assert parsed_t1["short_title"] == "feature one label"
    assert parsed_t1["short_title_source"] == "field"

    # 2. Full emergent task WITHOUT short (derived)
    t2_path = tasks_dir / "features" / "T002-without-short.md"
    t2_path.write_text(
        "# T002 Feature Two\n\n"
        "- id: T002\n- title: Feature Two\n- category: features\n- priority: P1\n"
        "- priority-reason: core\n- next-up: no\n- state: open\n- executor: kilo\n"
        "- depends-on: -\n- decider: -\n- sources: -\n- paths: -\n- handoff: -\n\n"
        "## Goal\n\nGoal.\n\n## Steps\n\nSteps.\n\n## Verification\n\nVerify.\n",
        encoding="utf-8",
    )
    parsed_t2 = te.parse_emergent_task_file(t2_path, tasks_dir)
    assert parsed_t2["short"] is None
    assert parsed_t2["short_title"] == "Feature Two"
    assert parsed_t2["short_title_source"] == "derived"

    # 3. Microtask WITH short
    m1_path = tasks_dir / "micro" / "T003-micro-short.md"
    m1_path.write_text(
        "# T003 Quick chore\n\n"
        "- id: T003\n- title: Quick chore\n- kind: chore\n- priority: P2\n"
        "- state: open\n- executor: kilo\n- paths: -\n- depends-on: -\n"
        "- short: quick chore\n\n## What\n\nDo chore.\n",
        encoding="utf-8",
    )
    parsed_m1 = te.parse_emergent_task_file(m1_path, tasks_dir)
    assert parsed_m1["short"] == "quick chore"
    assert parsed_m1["short_title"] == "quick chore"
    assert parsed_m1["short_title_source"] == "field"

    # 4. Question WITH short
    q1_path = tasks_dir / "questions" / "Q001-test-q.md"
    q1_path.write_text(
        "# Q001 Permission choice\n\n"
        "- id: Q001\n- question: Which mode?\n- status: open\n- blocks: -\n"
        "- decider: owner\n- asked-by: owner\n- asked: 2026-10-18\n- origin-run: -\n"
        "- open-answer: no\n- recommended: A\n- short: permission choice\n\n"
        "## Context\n\nCtx.\n\n## Options\n\n- **A** — Opt A\n",
        encoding="utf-8",
    )
    parsed_q1 = te.parse_question_file(q1_path, tasks_dir)
    assert parsed_q1["short"] == "permission choice"
    assert parsed_q1["short_title"] == "permission choice"
    assert parsed_q1["short_title_source"] == "field"

    # 5. Question WITHOUT short (derived)
    q2_path = tasks_dir / "questions" / "Q002-test-q2.md"
    q2_path.write_text(
        "# Q002 Database Selection Choice\n\n"
        "- id: Q002\n- question: Which database engine should we adopt?\n- status: open\n- blocks: -\n"
        "- decider: owner\n- asked-by: owner\n- asked: 2026-10-18\n- origin-run: -\n"
        "- open-answer: no\n- recommended: A\n\n"
        "## Context\n\nCtx.\n\n## Options\n\n- **A** — Opt A\n",
        encoding="utf-8",
    )
    parsed_q2 = te.parse_question_file(q2_path, tasks_dir)
    assert parsed_q2["short"] is None
    assert parsed_q2["short_title_source"] == "derived"
    assert parsed_q2["short_title"] == "Database Selection Choice"

    # 6. Plan task with **Short:** bullet
    init_dir = tasks_dir / "01-init"
    init_dir.mkdir(parents=True)
    plan_path = init_dir / "plan.md"
    plan_path.write_text(
        "# 01 - Init\n\n- **Goal:** G.\n\n## Tasks\n\n"
        "### 01.1 - Task with short\n"
        "- **Status:** `open` · **Short:** task with short · **Kind:** feature\n"
        "- **Goal:** G1.\n\n"
        "### 01.2 - Task without short\n"
        "- **Status:** `open` · **Kind:** chore\n"
        "- **Goal:** G2.\n",
        encoding="utf-8",
    )
    tree = te.discover_task_tree(tasks_dir)
    assert tree["01.1"].short == "task with short"
    assert tree["01.1"].short_title == "task with short"
    assert tree["01.1"].short_title_source == "field"

    assert tree["01.2"].short is None
    assert tree["01.2"].short_title == "Task without short"
    assert tree["01.2"].short_title_source == "derived"


def test_validate_malformed_short_values(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)

    # Emergent task with trailing punctuation in short
    t1_path = tasks_dir / "features" / "T001-invalid.md"
    t1_path.write_text(
        "# T001 Feature One\n\n"
        "- id: T001\n- title: Feature One\n- category: features\n- priority: P1\n"
        "- priority-reason: core\n- next-up: no\n- state: open\n- executor: kilo\n"
        "- depends-on: -\n- decider: -\n- sources: -\n- paths: -\n- handoff: -\n"
        "- short: trailing period.\n\n## Goal\n\nGoal.\n\n## Steps\n\nSteps.\n\n## Verification\n\nVerify.\n",
        encoding="utf-8",
    )
    # Question with 6 words in short
    q1_path = tasks_dir / "questions" / "Q001-invalid.md"
    q1_path.write_text(
        "# Q001 Permission choice\n\n"
        "- id: Q001\n- question: Which mode?\n- status: open\n- blocks: -\n"
        "- decider: owner\n- asked-by: owner\n- asked: 2026-10-18\n- origin-run: -\n"
        "- open-answer: yes\n- recommended: -\n- short: one two three four five six\n\n"
        "## Context\n\nCtx.\n\n## Options\n\n- **A** — Opt A\n- **B** — Opt B\n\n## Answer\n\n-\n",
        encoding="utf-8",
    )

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert len(errors) == 0  # Constraints on short are non-fatal warnings
    assert any("short title 'trailing period.' violates conventions" in w for w in warnings)
    assert any("question short title 'one two three four five six' violates conventions" in w for w in warnings)


def test_creation_commands_short_flag(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. tasks new with --short
    res_new1 = run_cli(
        "new",
        "--title", "First Task",
        "--category", "features",
        "--goal", "Goal 1",
        "--priority-reason", "Reason 1",
        "--short", "first custom title",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new1.returncode == 0
    t1_file = tasks_dir / json.loads(res_new1.stdout)["rel_path"]
    t1_content = t1_file.read_text(encoding="utf-8")
    assert "- short: first custom title" in t1_content

    # 2. tasks new without --short (derived)
    res_new2 = run_cli(
        "new",
        "--title", "The Second Feature Task",
        "--category", "features",
        "--goal", "Goal 2",
        "--priority-reason", "Reason 2",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new2.returncode == 0
    t2_file = tasks_dir / json.loads(res_new2.stdout)["rel_path"]
    t2_content = t2_file.read_text(encoding="utf-8")
    # Derived from "The Second Feature Task" -> "Second Feature Task"
    assert "- short: Second Feature Task" in t2_content

    # 3. tasks micro with --short
    res_m1 = run_cli(
        "micro",
        "--title", "Chore Task",
        "--short", "chore custom title",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_m1.returncode == 0
    m1_file = tasks_dir / json.loads(res_m1.stdout)["rel_path"]
    m1_content = m1_file.read_text(encoding="utf-8")
    assert "- short: chore custom title" in m1_content

    # 4. tasks micro without --short (derived)
    res_m2 = run_cli(
        "micro",
        "--title", "A Clean Chores Work",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_m2.returncode == 0
    m2_file = tasks_dir / json.loads(res_m2.stdout)["rel_path"]
    m2_content = m2_file.read_text(encoding="utf-8")
    assert "- short: Clean Chores Work" in m2_content

    # 5. questions ask with --short
    res_q1 = run_cli(
        "questions", "ask",
        "--question", "Which option?",
        "--context", "Context text",
        "--blocks", "T001",
        "--open-answer", "yes",
        "--short", "which option question",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_q1.returncode == 0
    q1_file = tasks_dir / json.loads(res_q1.stdout)["rel_path"]
    q1_content = q1_file.read_text(encoding="utf-8")
    assert "- short: which option question" in q1_content

    # 6. questions ask without --short (derived)
    res_q2 = run_cli(
        "questions", "ask",
        "--question", "What permission mode is needed?",
        "--context", "Context text",
        "--blocks", "T002",
        "--open-answer", "yes",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_q2.returncode == 0
    q2_file = tasks_dir / json.loads(res_q2.stdout)["rel_path"]
    q2_content = q2_file.read_text(encoding="utf-8")
    assert "- short: permission mode needed" in q2_content


def test_set_short_command(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)

    t1_path = tasks_dir / "features" / "T001-sample.md"
    t1_path.write_text(
        "# T001 Feature One\n\n"
        "- id: T001\n- title: Feature One\n- category: features\n- priority: P1\n"
        "- priority-reason: core\n- next-up: no\n- state: open\n- executor: kilo\n"
        "- depends-on: -\n- decider: -\n- sources: -\n- paths: -\n- handoff: -\n\n"
        "## Goal\n\nGoal.\n\n## Steps\n\nSteps.\n\n## Verification\n\nVerify.\n",
        encoding="utf-8",
    )

    # 1. Dry run
    res_dry = run_cli("set-short", "T001", "custom short title", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0
    payload_dry = json.loads(res_dry.stdout)
    assert payload_dry["ok"] is True
    assert payload_dry["dry_run"] is True
    assert "+- short: custom short title" in payload_dry["diff"]
    # File not modified yet
    assert "- short:" not in t1_path.read_text(encoding="utf-8")
    # The dry-run hash is the precondition for the apply (preview -> apply flow of the UI bridges)
    res_flow = run_cli(
        "set-short", "T001", "custom short title", "--expect-plan-hash", payload_dry["plan_hash"],
        "--dry-run", "--tasks-dir", str(tasks_dir), "--json",
    )
    assert json.loads(res_flow.stdout)["ok"] is True
    assert payload_dry["task_hash"] != payload_dry["new_task_hash"]

    # 2. Validation failure on malformed input
    res_bad = run_cli("set-short", "T001", "has trailing period.", "--tasks-dir", str(tasks_dir), "--json")
    assert res_bad.returncode == 1
    assert "trailing punctuation" in json.loads(res_bad.stdout)["error"]

    # 3. Apply change
    res_apply = run_cli("set-short", "T001", "custom short title", "--tasks-dir", str(tasks_dir), "--json")
    assert res_apply.returncode == 0
    payload_apply = json.loads(res_apply.stdout)
    assert payload_apply["ok"] is True
    assert "- short: custom short title" in t1_path.read_text(encoding="utf-8")
    current_hash = payload_apply["task_hash"]

    # 4. Hash mismatch refusal
    res_mismatch = run_cli(
        "set-short", "T001", "updated short", "--expect-task-hash", "0" * 64, "--tasks-dir", str(tasks_dir), "--json"
    )
    assert res_mismatch.returncode == 1
    assert "Task hash mismatch" in json.loads(res_mismatch.stdout)["error"]

    # 5. Matching hash succeeds
    res_match = run_cli(
        "set-short", "T001", "updated short", "--expect-task-hash", current_hash, "--tasks-dir", str(tasks_dir), "--json"
    )
    assert res_match.returncode == 0
    assert "- short: updated short" in t1_path.read_text(encoding="utf-8")


def test_json_outputs_carry_short_title(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)

    # Create task with short
    run_cli(
        "new",
        "--title", "User Auth Implementation",
        "--category", "features",
        "--goal", "Implement authentication",
        "--priority-reason", "Security",
        "--short", "user auth impl",
        "--tasks-dir", str(tasks_dir),
    )
    # Create question
    run_cli(
        "questions", "ask",
        "--question", "Which OAuth provider?",
        "--context", "Google vs GitHub",
        "--blocks", "T001",
        "--open-answer", "yes",
        "--short", "oauth provider selection",
        "--tasks-dir", str(tasks_dir),
    )

    # Create unblocked task for ready queue
    run_cli(
        "new",
        "--title", "Unblocked Ready Task",
        "--category", "features",
        "--goal", "Ready to work",
        "--priority-reason", "Active",
        "--short", "unblocked ready task",
        "--tasks-dir", str(tasks_dir),
    )

    # 1. tasks list --json
    res_list = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list.returncode == 0
    list_data = json.loads(res_list.stdout)
    node = list_data["all_tasks"][0]
    assert node["short_title"] == "user auth impl"
    assert node["short_title_source"] == "field"

    # 2. tasks graph --json
    res_graph = run_cli("graph", "--tasks-dir", str(tasks_dir), "--json")
    assert res_graph.returncode == 0
    graph_data = json.loads(res_graph.stdout)
    g_node = graph_data["nodes_by_id"]["T001"]
    assert g_node["short_title"] == "user auth impl"
    assert g_node["short_title_source"] == "field"

    # 3. questions list --json
    res_ql = run_cli("questions", "list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ql.returncode == 0
    ql_data = json.loads(res_ql.stdout)
    q_item = ql_data["questions"][0]
    assert q_item["short_title"] == "oauth provider selection"
    assert q_item["short_title_source"] == "field"

    # 4. tasks next --json
    res_next = run_cli("next", "--tasks-dir", str(tasks_dir), "--json")
    assert res_next.returncode == 0
    next_data = json.loads(res_next.stdout)
    assert len(next_data["tasks"]) > 0
    assert next_data["tasks"][0]["short_title"] == "unblocked ready task"
    assert next_data["tasks"][0]["short_title_source"] == "field"


def test_sync_index_short_title_table_output(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)

    run_cli(
        "new",
        "--title", "Database Index Migration",
        "--category", "features",
        "--goal", "Migrate DB index",
        "--priority-reason", "Performance",
        "--short", "db index migration",
        "--tasks-dir", str(tasks_dir),
    )

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        "# Index\n\n"
        "## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )

    res_sync = run_cli("sync-index", "--apply", "--tasks-dir", str(tasks_dir), "--json")
    assert res_sync.returncode == 0
    content = index_path.read_text(encoding="utf-8")
    assert "| T001 (db index migration) |" in content






def test_set_short_keeps_optional_field_order(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    t_path.write_text(
        "# T001 Feature One\n\n"
        "- id: T001\n- title: Feature One\n- category: features\n- priority: P1\n"
        "- priority-reason: core\n- next-up: no\n- state: open\n- executor: kilo\n"
        "- depends-on: -\n- decider: -\n- sources: -\n- paths: -\n- handoff: -\n- verifier: claude\n\n"
        "## Goal\n\nGoal.\n\n## Steps\n\nSteps.\n\n## Verification\n\nVerify.\n",
        encoding="utf-8",
    )
    dry = json.loads(run_cli("set-short", "T001", "feature one", "--dry-run", "--tasks-dir", str(tasks_dir), "--json").stdout)
    res = run_cli("set-short", "T001", "feature one", "--expect-task-hash", dry["task_hash"], "--tasks-dir", str(tasks_dir), "--json")
    assert json.loads(res.stdout)["ok"] is True
    text = t_path.read_text(encoding="utf-8")
    assert text.index("- verifier: claude") < text.index("- short: feature one")
    assert run_cli("validate", "--tasks-dir", str(tasks_dir)).returncode == 0


def test_set_short_on_initiative_is_read_back(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "07-agent-runs"
    init_dir.mkdir(parents=True)
    (init_dir / "plan.md").write_text(
        "# 07 - Agent runs from the control plane\n\n"
        "## Tasks\n\n### 07.1 - First task\n\n- **Status:** `open`\n- **Goal:** Do it.\n",
        encoding="utf-8",
    )
    dry = json.loads(run_cli("set-short", "07", "Agent runs", "--dry-run", "--tasks-dir", str(tasks_dir), "--json").stdout)
    assert json.loads(run_cli("set-short", "07", "Agent runs", "--expect-task-hash", dry["task_hash"],
                              "--tasks-dir", str(tasks_dir), "--json").stdout)["ok"] is True
    assert "- **Short:** Agent runs" in (init_dir / "plan.md").read_text(encoding="utf-8")
    listing = json.loads(run_cli("list", "--tasks-dir", str(tasks_dir), "--json").stdout)
    blob = json.dumps(listing)
    assert '"short_title": "Agent runs"' in blob and '"short_title_source": "field"' in blob


def test_concurrent_writers_transition_no_lost_update(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    tree = te.discover_task_tree(tasks_dir)
    initial_hash = tree["T001"].task_hash

    import concurrent.futures

    def _tr_writer(state: str) -> subprocess.CompletedProcess[str]:
        return run_cli(
            "transition",
            "T001",
            state,
            "--actor",
            "kilo",
            "--expect-task-hash",
            initial_hash,
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        )

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    with te.task_write_lock(tasks_dir):
        f1 = ex.submit(_tr_writer, "in progress")
        f2 = ex.submit(_tr_writer, "in progress")
        time.sleep(0.3)

    r1 = f1.result(timeout=10)
    r2 = f2.result(timeout=10)
    ex.shutdown(wait=True)

    results = [r1, r2]
    successes = [r for r in results if r.returncode == 0]
    failures = [r for r in results if r.returncode != 0]

    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {[r.stdout for r in results]}"
    assert len(failures) == 1, f"Expected 1 failure, got {len(failures)}: {[r.stdout for r in results]}"
    fail_payload = json.loads(failures[0].stdout)
    assert fail_payload.get("error") == "stale-task"


def test_concurrent_writers_set_short_no_lost_update(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    tree = te.discover_task_tree(tasks_dir)
    initial_hash = tree["T001"].task_hash

    import concurrent.futures

    def _short_writer(title: str) -> subprocess.CompletedProcess[str]:
        return run_cli(
            "set-short",
            "T001",
            title,
            "--expect-task-hash",
            initial_hash,
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        )

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    with te.task_write_lock(tasks_dir):
        f1 = ex.submit(_short_writer, "title alpha")
        f2 = ex.submit(_short_writer, "title beta")
        time.sleep(0.3)

    r1 = f1.result(timeout=10)
    r2 = f2.result(timeout=10)
    ex.shutdown(wait=True)

    results = [r1, r2]
    successes = [r for r in results if r.returncode == 0]
    failures = [r for r in results if r.returncode != 0]

    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {[r.stdout for r in results]}"
    assert len(failures) == 1, f"Expected 1 failure, got {len(failures)}: {[r.stdout for r in results]}"
    fail_payload = json.loads(failures[0].stdout)
    assert "Task hash mismatch" in fail_payload.get("error", "")


def test_concurrent_writers_apply_on_top_without_expect_hash(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    import concurrent.futures

    def _set_short(title: str) -> subprocess.CompletedProcess[str]:
        return run_cli(
            "set-short",
            "T001",
            title,
            "--tasks-dir",
            str(tasks_dir),
            "--json",
        )

    # Both write without --expect-task-hash; one applies on top of the other under lock
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    with te.task_write_lock(tasks_dir):
        f1 = ex.submit(_set_short, "title one")
        f2 = ex.submit(_set_short, "title two")
        time.sleep(0.3)

    r1 = f1.result(timeout=10)
    r2 = f2.result(timeout=10)
    ex.shutdown(wait=True)

    assert r1.returncode == 0
    assert r2.returncode == 0
    final_tree = te.discover_task_tree(tasks_dir)
    assert final_tree["T001"].short_title in ("title one", "title two")
    assert te.validate_tasks_tree(tasks_dir)[0] == []


def test_idempotency_key_lifecycle_and_pruning(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    # 1. Invalid key format rejected
    r_bad = run_cli("transition", "T001", "in progress", "--actor", "kilo", "--idempotency-key", "short", "--tasks-dir", str(tasks_dir), "--json")
    assert r_bad.returncode == 2
    assert "invalid-idempotency-key" in r_bad.stdout

    r_bad_chars = run_cli("transition", "T001", "in progress", "--actor", "kilo", "--idempotency-key", "invalid key with spaces!!", "--tasks-dir", str(tasks_dir), "--json")
    assert r_bad_chars.returncode == 2
    assert "invalid-idempotency-key" in r_bad_chars.stdout

    # 2. First call with valid key succeeds and writes to idempotency store
    idemp_key = "key_sample_12345"
    r1 = run_cli("transition", "T001", "in progress", "--actor", "kilo", "--idempotency-key", idemp_key, "--tasks-dir", str(tasks_dir), "--json")
    assert r1.returncode == 0
    p1 = json.loads(r1.stdout)
    assert p1["ok"] is True
    assert p1["new_state"] == "in progress"

    # Check that disk record exists
    proj_root = te._resolve_workspace_from_tasks_dir(tasks_dir)
    key_h = hashlib.sha256(idemp_key.encode("utf-8")).hexdigest()
    rec_file = proj_root / ".ai-orchestration" / "idempotency" / f"{key_h}.json"
    assert rec_file.is_file()
    rec_data = json.loads(rec_file.read_text(encoding="utf-8"))
    assert rec_data["key"] == idemp_key
    assert rec_data["exit_code"] == 0
    assert rec_data["result"]["new_state"] == "in progress"

    # 3. Repeated call with same key and same arguments returns stored result without writing
    old_mtime = t_path.stat().st_mtime
    time.sleep(0.1)
    r2 = run_cli("transition", "T001", "in progress", "--actor", "kilo", "--idempotency-key", idemp_key, "--tasks-dir", str(tasks_dir), "--json")
    assert r2.returncode == 0
    p2 = json.loads(r2.stdout)
    assert p2 == p1
    assert t_path.stat().st_mtime == old_mtime

    # 4. Same key with different arguments -> idempotency-key-reused
    r_diff = run_cli("transition", "T001", "delivered", "--actor", "kilo", "--idempotency-key", idemp_key, "--tasks-dir", str(tasks_dir), "--json")
    assert r_diff.returncode == 2
    p_diff = json.loads(r_diff.stdout)
    assert p_diff.get("error") == "idempotency-key-reused"

    # 5. Pruning of records older than 7 days on write
    old_key = "old_stale_key_9999"
    old_h = hashlib.sha256(old_key.encode("utf-8")).hexdigest()
    old_file = proj_root / ".ai-orchestration" / "idempotency" / f"{old_h}.json"
    old_file.write_text(json.dumps({"key": old_key, "exit_code": 0}), encoding="utf-8")
    eight_days_ago = time.time() - (8 * 86400)
    os.utime(str(old_file), (eight_days_ago, eight_days_ago))

    fresh_key = "fresh_key_77777777"
    r_fresh = run_cli("set-short", "T001", "short title", "--idempotency-key", fresh_key, "--tasks-dir", str(tasks_dir), "--json")
    assert r_fresh.returncode == 0
    assert not old_file.exists()
    assert (proj_root / ".ai-orchestration" / "idempotency" / f"{hashlib.sha256(fresh_key.encode('utf-8')).hexdigest()}.json").exists()


def _broker_holding_worker(cfg_dir: str, ready_evt: Any, stop_evt: Any) -> None:
    repo_root = te._find_repo_root()
    if repo_root:
        sys.path.insert(0, str(repo_root / "scripts"))
    import orchestration_broker_lock as obl

    os.environ["AI_ORCHESTRATION_CONFIG"] = cfg_dir
    handle = obl.acquire_broker_lock(cfg_dir)
    assert handle is not None
    obl.write_broker_manifest(cfg_dir, pid=os.getpid(), port=9999, started_at="2026-10-18T12:00:00Z")
    ready_evt.set()
    stop_evt.wait(timeout=10)
    handle.release()


def test_broker_singleton_guard_blocks_mutating_commands(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_dir = tmp_path / "broker_cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(cfg_dir))
    monkeypatch.delenv("AI_ORCH_BROKER_CHILD", raising=False)

    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    import multiprocessing
    ready_evt = multiprocessing.Event()
    stop_evt = multiprocessing.Event()
    proc = multiprocessing.Process(
        target=_broker_holding_worker,
        args=(str(cfg_dir), ready_evt, stop_evt),
    )
    proc.start()

    try:
        assert ready_evt.wait(timeout=5)

        # 1. Mutating command fails with exit 75 and broker-owns-writes
        env = os.environ.copy()
        env["AI_ORCHESTRATION_CONFIG"] = str(cfg_dir)
        env.pop("AI_ORCH_BROKER_CHILD", None)

        res_mut = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_mut.returncode == 75
        p_mut = json.loads(res_mut.stdout)
        assert p_mut["ok"] is False
        assert p_mut["error"] == "broker-owns-writes"
        assert f"running as pid {proc.pid}" in p_mut["message"]

        # Also test via set-short
        res_mut2 = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "set-short", "T001", "my short", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_mut2.returncode == 75
        p_mut2 = json.loads(res_mut2.stdout)
        assert p_mut2["error"] == "broker-owns-writes"

        # 2. Read command is UNAFFECTED and succeeds
        res_read = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "list", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_read.returncode == 0
        p_read = json.loads(res_read.stdout)
        assert p_read["ok"] is True

        res_val = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "validate", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_val.returncode == 0

        # 3. Mutating command with AI_ORCH_BROKER_CHILD=1 succeeds
        env_child = env.copy()
        env_child["AI_ORCH_BROKER_CHILD"] = "1"
        res_child = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "set-short", "T001", "my short", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env_child,
        )
        assert res_child.returncode == 0
        p_child = json.loads(res_child.stdout)
        assert p_child["ok"] is True

    finally:
        stop_evt.set()
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()

    # 4. Once broker stops, mutating command succeeds normally
    res_after = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res_after.returncode == 0
    p_after = json.loads(res_after.stdout)
    assert p_after["ok"] is True


def test_stale_broker_manifest_allows_mutating_cli(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_dir = tmp_path / "broker_cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(cfg_dir))
    monkeypatch.delenv("AI_ORCH_BROKER_CHILD", raising=False)

    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    repo_root = te._find_repo_root()
    if repo_root:
        sys.path.insert(0, str(repo_root / "scripts"))
    import orchestration_broker_lock as obl

    handle = obl.acquire_broker_lock(cfg_dir)
    assert handle is not None

    # Spawn short-lived process to obtain a dead PID
    sub = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = sub.pid
    sub.wait()

    obl.write_broker_manifest(cfg_dir, pid=dead_pid, port=8888, started_at="2026-10-18T12:00:00Z")

    env = os.environ.copy()
    env["AI_ORCHESTRATION_CONFIG"] = str(cfg_dir)
    env.pop("AI_ORCH_BROKER_CHILD", None)

    # Status check confirms held is False
    st = obl.broker_status(cfg_dir)
    assert st.held is False
    assert st.pid_alive is False
    assert st.live_pid is None

    # Mutating command must succeed (exit 0) and not cite dead pid
    res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0
    p = json.loads(res.stdout)
    assert p["ok"] is True
    assert p["new_state"] == "in progress"
    assert str(dead_pid) not in res.stdout
    assert str(dead_pid) not in res.stderr

    handle.release()


def test_live_broker_forwards_cli_writes(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import http.server
    import threading

    cfg_dir = tmp_path / "broker_cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(cfg_dir))
    monkeypatch.delenv("AI_ORCH_BROKER_CHILD", raising=False)

    token_file = cfg_dir / "ui-token"
    token_file.write_text("tok-secret-1234\n", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    received = []

    class MockBrokerHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/cli":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                received.append({"path": "/cli", "token": self.headers.get("x-ai-orch-token"), "body": json.loads(body)})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                resp = {
                    "returncode": 0,
                    "stdout": json.dumps({"ok": True, "from_broker": True, "action": "forwarded"}),
                    "stderr": "",
                }
                self.wfile.write(json.dumps(resp).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), MockBrokerHandler)
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()

    repo_root = te._find_repo_root()
    if repo_root:
        sys.path.insert(0, str(repo_root / "scripts"))
    import orchestration_broker_lock as obl

    handle = obl.acquire_broker_lock(cfg_dir)
    assert handle is not None

    obl.write_broker_manifest(
        cfg_dir,
        pid=os.getpid(),
        port=port,
        started_at="2026-10-18T12:00:00Z",
        token_file=str(token_file),
    )

    try:
        env = os.environ.copy()
        env["AI_ORCHESTRATION_CONFIG"] = str(cfg_dir)
        env.pop("AI_ORCH_BROKER_CHILD", None)

        # 1. transition command forwards to broker
        res_trans = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_trans.returncode == 0
        p_trans = json.loads(res_trans.stdout)
        assert p_trans["from_broker"] is True

        # 2. set-short command forwards to broker
        res_short = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "set-short", "T001", "my short", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_short.returncode == 0
        p_short = json.loads(res_short.stdout)
        assert p_short["from_broker"] is True

        # 3. new command forwards to broker
        res_new = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "new", "--title", "Emergent item", "--short", "emergent", "--category", "features", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_new.returncode == 0
        p_new = json.loads(res_new.stdout)
        assert p_new["from_broker"] is True

        # Verify all received calls had the UI token
        assert len(received) == 3
        for call in received:
            assert call["token"] == "tok-secret-1234"

    finally:
        server.shutdown()
        server.server_close()
        handle.release()


def test_live_broker_fallback_to_child_channel_when_cli_404(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import http.server
    import threading

    cfg_dir = tmp_path / "broker_cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(cfg_dir))
    monkeypatch.delenv("AI_ORCH_BROKER_CHILD", raising=False)

    token_file = cfg_dir / "ui-token"
    token_file.write_text("tok-fallback-5678\n", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    class HealthOnlyBrokerHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            # No /cli endpoint (e.g. MCP streamable-HTTP only)
            self.send_response(404)
            self.end_headers()

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), HealthOnlyBrokerHandler)
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()

    repo_root = te._find_repo_root()
    if repo_root:
        sys.path.insert(0, str(repo_root / "scripts"))
    import orchestration_broker_lock as obl

    handle = obl.acquire_broker_lock(cfg_dir)
    assert handle is not None

    obl.write_broker_manifest(
        cfg_dir,
        pid=os.getpid(),
        port=port,
        started_at="2026-10-18T12:00:00Z",
        token_file=str(token_file),
    )

    try:
        env = os.environ.copy()
        env["AI_ORCHESTRATION_CONFIG"] = str(cfg_dir)
        env.pop("AI_ORCH_BROKER_CHILD", None)

        # Mutating transition executes locally via child channel and succeeds
        res = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res.returncode == 0
        p = json.loads(res.stdout)
        assert p["ok"] is True
        assert p["new_state"] == "in progress"
    finally:
        server.shutdown()
        server.server_close()
        handle.release()


def test_ai_orch_mcp_help() -> None:
    repo_root = te._find_repo_root()
    bin_ai_orch = repo_root / "bin" / "ai-orch"
    res = subprocess.run(
        [sys.executable, str(bin_ai_orch), "mcp", "--help"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "--local" in res.stdout
    assert "in-process" in res.stdout or "stdio" in res.stdout


# ---------------------------------------------------------------------------
# Tests for Qualified References, Coordinates, Placement Warnings, and Tasks Move (16.4)
# ---------------------------------------------------------------------------


def test_parse_and_format_qualified_ref():
    # 1. Successful parses
    r1 = te.parse_qualified_ref("ai-coding-tools:ai-orchestration/T025")
    assert r1 == {"workspace": "ai-coding-tools", "project": "ai-orchestration", "id": "T025"}
    assert te.format_qualified_ref(r1) == "ai-coding-tools:ai-orchestration/T025"

    r2 = te.parse_qualified_ref("ai-orchestration/12.16")
    assert r2 == {"project": "ai-orchestration", "id": "12.16"}
    assert te.format_qualified_ref(r2) == "ai-orchestration/12.16"

    r3 = te.parse_qualified_ref("_workspace/T014")
    assert r3 == {"project": "_workspace", "id": "T014"}
    assert te.format_qualified_ref(r3) == "_workspace/T014"

    r4 = te.parse_qualified_ref("T025")
    assert r4 == {"id": "T025"}
    assert te.format_qualified_ref(r4) == "T025"

    r5 = te.parse_qualified_ref("my-ws:T025")
    assert r5 == {"workspace": "my-ws", "id": "T025"}
    assert te.format_qualified_ref(r5) == "my-ws:T025"

    # Format with kwargs
    assert te.format_qualified_ref(id="T001", project="proj-a") == "proj-a/T001"
    assert te.format_qualified_ref(id="T001", project="proj-a", workspace="ws") == "ws:proj-a/T001"

    # 2. Malformed cases
    with pytest.raises(ValueError, match="invalid id"):
        te.parse_qualified_ref("bad slug")

    with pytest.raises(ValueError, match="invalid project slug"):
        te.parse_qualified_ref("bad_slug/T025")

    with pytest.raises(ValueError, match="invalid project slug"):
        te.parse_qualified_ref("a/T025")

    with pytest.raises(ValueError, match="invalid workspace slug"):
        te.parse_qualified_ref("bad_ws:ai-orchestration/T025")

    with pytest.raises(ValueError, match="missing id"):
        te.parse_qualified_ref("ai-orchestration/")

    with pytest.raises(ValueError, match="missing id"):
        te.parse_qualified_ref("ai-coding-tools:ai-orchestration/")

    with pytest.raises(ValueError, match="Empty qualified reference"):
        te.parse_qualified_ref("")

    with pytest.raises(ValueError, match="invalid id"):
        te.parse_qualified_ref("ai-orchestration/T025 extra")

    with pytest.raises(ValueError, match="multiple '/'"):
        te.parse_qualified_ref("ai-orchestration/T025/junk")

    with pytest.raises(ValueError, match="invalid id"):
        te.parse_qualified_ref("T025 junk")


def test_depends_on_accepts_cross_project_qualified_ref(tmp_path: pathlib.Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "features" / "T001-scraper.md"
    _write_sample_task(task_file, task_id="T001", depends_on="other-proj/T002")

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []


def test_coordinates_header_parsing_and_resolution(tmp_path: pathlib.Path):
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir(parents=True)
    ws_tasks = ws_dir / "tasks"
    ws_tasks.mkdir(parents=True)

    proj_a = ws_dir / "projects" / "proj-a"
    proj_a_tasks = proj_a / "tasks"
    proj_a_tasks.mkdir(parents=True)

    # Create target task in proj-a
    _write_sample_task(proj_a_tasks / "core" / "T001-core.md", task_id="T001", title="Core auth logic")

    # In ws_tasks, create an emergent task coordinating proj-a/T001 and unresolved proj-b/T002
    t_ws = ws_tasks / "orchestration" / "T010-coord.md"
    _write_sample_task(t_ws, task_id="T010", title="Coordinate auth rollout", category="orchestration")
    content = t_ws.read_text(encoding="utf-8")
    content = content.replace("- verifier: -", "- verifier: -\n- coordinates: proj-a/T001, proj-b/T002")
    t_ws.write_text(content, encoding="utf-8")

    emergent = te.discover_emergent_tasks(ws_tasks)
    t10 = next(t for t in emergent if t["id"] == "T010")
    assert len(t10["coordinates"]) == 2
    c1 = next(c for c in t10["coordinates"] if c["project"] == "proj-a")
    assert c1["id"] == "T001"
    assert c1.get("state") == "open"
    assert "short_title" in c1

    c2 = next(c for c in t10["coordinates"] if c["project"] == "proj-b")
    assert c2["id"] == "T002"
    assert "state" not in c2
    assert "short_title" not in c2


def test_validate_coordinates_and_placement_warnings(tmp_path: pathlib.Path):
    ws_dir = tmp_path / "my-workspace"
    ws_dir.mkdir(parents=True)
    ws_tasks = ws_dir / "tasks"
    ws_tasks.mkdir(parents=True)

    cfg = ws_dir / "orchestration.toml"
    cfg.write_text(
        '[workspace]\n'
        'projects = [\n'
        '  { slug = "proj-a", path = "projects/proj-a" },\n'
        '  { slug = "proj-b", path = "projects/proj-b" }\n'
        ']\n',
        encoding="utf-8",
    )

    proj_a_tasks = ws_dir / "projects" / "proj-a" / "tasks"
    proj_a_tasks.mkdir(parents=True)
    _write_sample_task(proj_a_tasks / "feat" / "T001-task.md", task_id="T001", title="Task A")

    # 1. Placement warning: task in _workspace with no coordinates whose paths all lie inside proj-a
    t1 = ws_tasks / "features" / "T001-single.md"
    _write_sample_task(t1, task_id="T001", title="Task single project paths")
    c1 = t1.read_text(encoding="utf-8").replace("- paths: src/scraper.py", "- paths: projects/proj-a/src/file.py, projects/proj-a/README.md")
    t1.write_text(c1, encoding="utf-8")

    # 2. Placement warning: task whose coordinates name a single project
    t2 = ws_tasks / "features" / "T002-single-coord.md"
    _write_sample_task(t2, task_id="T002", title="Task single coord")
    c2 = t2.read_text(encoding="utf-8").replace("- verifier: -", "- verifier: -\n- coordinates: proj-a/T001")
    t2.write_text(c2, encoding="utf-8")

    errors, warnings, _, _ = te.validate_tasks_tree(ws_tasks)
    assert any("T001-single.md: belongs in project proj-a; use tasks move" in w for w in warnings)
    assert any("T002-single-coord.md: belongs in project proj-a; use tasks move" in w for w in warnings)


def test_tasks_move_dry_run_and_apply(tmp_path: pathlib.Path):
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir(parents=True)
    ws_tasks = ws_dir / "tasks"
    ws_tasks.mkdir(parents=True)

    proj_a_dir = ws_dir / "proj-a"
    proj_a_tasks = proj_a_dir / "tasks"
    proj_a_tasks.mkdir(parents=True)

    (ws_tasks / "00-INDEX.md").write_text("# Workspace Index\n", encoding="utf-8")
    (proj_a_tasks / "00-INDEX.md").write_text("# Project A Index\n", encoding="utf-8")

    _write_sample_task(proj_a_tasks / "features" / "T001-existing.md", task_id="T001", title="Existing")

    src_task = ws_tasks / "refactor" / "T014-clean-db.md"
    _write_sample_task(src_task, task_id="T014", title="Clean DB schema", category="refactor")

    # 1. Dry run
    res_dry = te.move_task(
        tasks_dir=ws_tasks,
        task_id="T014",
        to_project="proj-a",
        to_tasks_dir=proj_a_tasks,
        dry_run=True,
    )
    assert res_dry["ok"] is True
    assert res_dry["dry_run"] is True
    assert res_dry["new_task_id"] == "T002"
    assert "diff_source" in res_dry and "diff_target" in res_dry
    assert "+- state: moved" in res_dry["diff_source"]
    assert "+- moved-to: proj-a/T002" in res_dry["diff_source"]
    assert "+- id: T002" in res_dry["diff_target"]
    assert not (proj_a_tasks / "refactor" / "T002-clean-db.md").exists()

    # 2. CAS hash failure test
    res_cas_fail = te.move_task(
        tasks_dir=ws_tasks,
        task_id="T014",
        to_tasks_dir=proj_a_tasks,
        expect_task_hash="badhash123",
    )
    assert res_cas_fail["ok"] is False
    assert "Task hash mismatch" in res_cas_fail["error"]

    # 3. Apply move
    res_apply = te.move_task(
        tasks_dir=ws_tasks,
        task_id="T014",
        to_project="proj-a",
        to_tasks_dir=proj_a_tasks,
        dry_run=False,
    )
    assert res_apply["ok"] is True
    assert res_apply["new_task_id"] == "T002"

    target_file = proj_a_tasks / "refactor" / "T002-clean-db.md"
    assert target_file.exists()
    assert "- id: T002" in target_file.read_text(encoding="utf-8")

    pointer_text = src_task.read_text(encoding="utf-8")
    assert "- state: moved" in pointer_text
    assert "- moved-to: proj-a/T002" in pointer_text

    ws_idx = (ws_tasks / "00-INDEX.md").read_text(encoding="utf-8")
    assert "T014" in ws_idx
    assert "moved" in ws_idx

    proj_idx = (proj_a_tasks / "00-INDEX.md").read_text(encoding="utf-8")
    assert "T002" in proj_idx

    err_ws, warn_ws, _, _ = te.validate_tasks_tree(ws_tasks)
    assert err_ws == []

    err_target, warn_target, _, _ = te.validate_tasks_tree(proj_a_tasks)
    assert err_target == []


def test_tasks_move_folder_task_and_cli(tmp_path: pathlib.Path):
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir(parents=True)
    ws_tasks = ws_dir / "tasks"
    ws_tasks.mkdir(parents=True)

    proj_b_tasks = ws_dir / "proj-b" / "tasks"
    proj_b_tasks.mkdir(parents=True)

    # Create folder task in source
    folder_task = ws_tasks / "architecture" / "T020-auth-rework"
    folder_task.mkdir(parents=True)
    _write_sample_task(folder_task / "README.md", task_id="T020", title="Auth rework", category="architecture")
    # Add an attachment
    att_dir = folder_task / "attachments"
    att_dir.mkdir(parents=True)
    (att_dir / "spec.txt").write_text("architecture spec", encoding="utf-8")

    # Run CLI with --dry-run
    res_dry = run_cli(
        "move", "T020",
        "--to-project", "proj-b",
        "--to-tasks-dir", str(proj_b_tasks),
        "--tasks-dir", str(ws_tasks),
        "--dry-run",
        "--json",
    )
    assert res_dry.returncode == 0
    data_dry = json.loads(res_dry.stdout)
    assert data_dry["ok"] is True
    assert data_dry["dry_run"] is True
    assert data_dry["new_task_id"] == "T001"
    assert not (proj_b_tasks / "architecture" / "T001-auth-rework").exists()

    # Run CLI real move with --idempotency-key
    res_real = run_cli(
        "move", "T020",
        "--to-project", "proj-b",
        "--to-tasks-dir", str(proj_b_tasks),
        "--tasks-dir", str(ws_tasks),
        "--idempotency-key", "key-move-12345",
        "--json",
    )
    assert res_real.returncode == 0
    data_real = json.loads(res_real.stdout)
    assert data_real["ok"] is True
    assert data_real["new_task_id"] == "T001"

    # Target folder exists with attachment
    target_folder = proj_b_tasks / "architecture" / "T001-auth-rework"
    assert target_folder.is_dir()
    assert (target_folder / "README.md").exists()
    assert "- id: T001" in (target_folder / "README.md").read_text(encoding="utf-8")
    assert (target_folder / "attachments" / "spec.txt").read_text(encoding="utf-8") == "architecture spec"

    # Source pointer README exists, attachments moved out
    source_readme = folder_task / "README.md"
    assert source_readme.exists()
    assert "- state: moved" in source_readme.read_text(encoding="utf-8")
    assert "- moved-to: proj-b/T001" in source_readme.read_text(encoding="utf-8")
    assert not (folder_task / "attachments").exists()

    # Validate source and target
    err_ws, warn_ws, _, _ = te.validate_tasks_tree(ws_tasks)
    assert err_ws == []
    err_t, warn_t, _, _ = te.validate_tasks_tree(proj_b_tasks)
    assert err_t == []


def test_plan_task_coordinates_and_depends_on_validation(tmp_path: pathlib.Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    init_dir = tasks_dir / "01-core"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 01 Core\n\n"
        "## Tasks\n\n"
        "### 01.1 - Task A\n"
        "- **Status:** open\n"
        "- **Goal:** Subtask A\n"
        "- **Coordinates:** proj-a/T001\n"
        "- **Depends on:** other-proj/12.2\n",
        encoding="utf-8",
    )

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert any("cannot resolve project 'proj-a' for coordinates reference 'proj-a/T001'" in w for w in warnings)


def test_validate_coordinates_warnings_for_missing_task(tmp_path: pathlib.Path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(parents=True)
    ws_tasks = ws_dir / "tasks"
    ws_tasks.mkdir(parents=True)

    cfg = ws_dir / "orchestration.toml"
    cfg.write_text(
        '[workspace]\nprojects = [\n  { slug = "proj-a", path = "proj-a" }\n]\n',
        encoding="utf-8",
    )

    proj_a_tasks = ws_dir / "proj-a" / "tasks"
    proj_a_tasks.mkdir(parents=True)
    # Project exists, but task T999 does not exist
    t1 = ws_tasks / "features" / "T001-coord.md"
    _write_sample_task(t1, task_id="T001", title="Task with missing target")
    c1 = t1.read_text(encoding="utf-8").replace("- verifier: -", "- verifier: -\n- coordinates: proj-a/T999")
    t1.write_text(c1, encoding="utf-8")

    errors, warnings, _, _ = te.validate_tasks_tree(ws_tasks)
    assert any("target task 'T999' in project 'proj-a' does not exist" in w for w in warnings)


def test_tasks_move_rebases_paths_to_the_project_root(tmp_path: pathlib.Path) -> None:
    """16.4: a task moved from the workspace tree into a project keeps paths relative to its new root."""
    ws = tmp_path / "ws"
    (ws / "tasks").mkdir(parents=True)
    (ws / "proj" / "tasks").mkdir(parents=True)
    (ws / "tasks" / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")
    (ws / "proj" / "tasks" / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")
    res = run_cli("new", "--tasks-dir", str(ws / "tasks"), "--category", "features", "--title", "Misplaced",
                  "--short", "Misplaced", "--goal", "g", "--priority-reason", "r", "--paths", "proj/src, docs/x.md",
                  "--json")
    assert json.loads(res.stdout)["ok"] is True
    mv = run_cli("move", "T001", "--to-tasks-dir", str(ws / "proj" / "tasks"), "--tasks-dir", str(ws / "tasks"),
                 "--json")
    assert json.loads(mv.stdout)["ok"] is True, mv.stdout
    moved = next((ws / "proj" / "tasks" / "features").glob("T001-*.md")).read_text(encoding="utf-8")
    assert "- paths: src, docs/x.md" in moved
    pointer = next((ws / "tasks" / "features").glob("T001-*.md")).read_text(encoding="utf-8")
    assert "- moved-to:" in pointer


def test_t029_plan_task_ids_with_letter_suffix(tmp_path: pathlib.Path) -> None:
    """T029: plan tasks with letter suffixes (NN.T<letter>, e.g. 06.1b) are parsed consistently,
    ordered 06.1 < 06.1b < 06.2 in list/tree/initiatives/graph, can be transitioned and depended on;
    malformed headings in a plan's task section emit a validate error."""
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "06-control-plane"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 06 - Control Plane\n\n"
        "## Tasks\n\n"
        "### 06.1 - First task\n\n"
        "- **Status:** `open`\n"
        "- **Goal:** First goal.\n\n"
        "### 06.1b - Middle task with letter suffix\n\n"
        "- **Status:** `open`\n"
        "- **Goal:** Middle goal.\n\n"
        "### 06.2 - Second task\n\n"
        "- **Status:** `open` · **Depends on:** 06.1b\n"
        "- **Goal:** Second goal.\n",
        encoding="utf-8",
    )
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    tree = te.discover_task_tree(tasks_dir)
    assert "06.1" in tree
    assert "06.1b" in tree
    assert "06.2" in tree

    # Children ordering: 06.1 < 06.1b < 06.2
    assert tree["06"].children == ["06.1", "06.1b", "06.2"]

    # Depends-on accepts 06.1b
    assert tree["06.2"].depends_on == ["06.1b"]

    # Initiative counts and task list
    inits = te.discover_initiatives(tasks_dir, tree)
    assert len(inits) == 1
    init = inits[0]
    assert [t["id"] for t in init["tasks"]] == ["06.1", "06.1b", "06.2"]
    assert init["leaves_total"] == 3

    # Graph includes all three
    graph = te.compute_tasks_graph(tasks_dir)
    graph_ids = [n["id"] for n in graph["nodes"]]
    assert "06.1" in graph_ids
    assert "06.1b" in graph_ids
    assert "06.2" in graph_ids

    # Transition 06.1b to in progress
    ok, res = te.transition_task(tasks_dir, "06.1b", "in progress", actor="kilo")
    assert ok is True, res
    tree_after = te.discover_task_tree(tasks_dir)
    assert tree_after["06.1b"].canonical_state == "in progress"
    assert tree_after["06"].children == ["06.1", "06.1b", "06.2"]

    # Transition 06.1b through delivered and verified to done (moves to ## Closed)
    ok_del, res_del = te.transition_task(tasks_dir, "06.1b", "delivered", actor="kilo")
    assert ok_del is True, res_del
    ok_ver, res_ver = te.transition_task(tasks_dir, "06.1b", "verified", actor="verifier")
    assert ok_ver is True, res_ver
    ok_done, res_done = te.transition_task(tasks_dir, "06.1b", "done", actor="kilo")
    assert ok_done is True, res_done
    tree_done = te.discover_task_tree(tasks_dir)
    assert tree_done["06.1b"].canonical_state == "done"

    # Validate passes on clean plan
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == [], errors

    # Malformed heading in task section emits a validate error
    plan_text = plan_file.read_text(encoding="utf-8")
    malformed_plan = plan_text + "\n### malformed heading\n\n- **Status:** `open`\n- **Goal:** Bad.\n"
    plan_file.write_text(malformed_plan, encoding="utf-8")
    errs_malformed, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("heading '### malformed heading' in task section does not parse as a task" in e for e in errs_malformed)


def test_t030_conditions_header_validation_and_status(tmp_path: pathlib.Path) -> None:
    """T030: conditions: header validation (must reference known Q### questions),
    conditional boolean and status resolution."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "server-and-bindings").mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # Ask two questions (blocks="-" means blocking no task)
    ok_q1, q1 = te.ask_question(
        tasks_dir=tasks_dir,
        question="Question 1?",
        context="Context 1",
        options=[("A", "Option A", None), ("B", "Option B", None)],
        blocks="-",
    )
    assert ok_q1 is True, q1
    ok_q2, q2 = te.ask_question(
        tasks_dir=tasks_dir,
        question="Question 2?",
        context="Context 2",
        options=[("yes", "Yes", None), ("no", "No", None)],
        blocks="-",
    )
    assert ok_q2 is True, q2

    # Create task with conditions header in canonical order
    task_file = tasks_dir / "server-and-bindings" / "T001-conditional-task.md"
    task_file.write_text(
        f"# T001 Conditional Task\n\n"
        f"- id: T001\n"
        f"- title: Conditional Task\n"
        f"- category: server-and-bindings\n"
        f"- priority: P2\n"
        f"- priority-reason: test\n"
        f"- next-up: no\n"
        f"- state: open\n"
        f"- executor: kilo\n"
        f"- depends-on: -\n"
        f"- decider: -\n"
        f"- sources: -\n"
        f"- paths: -\n"
        f"- handoff: -\n"
        f"- conditions: {q1['id']}, {q2['id']}\n"
        f"- short: Conditional\n\n"
        f"## Goal\nWork\n\n"
        f"## Steps\n1. Do\n\n"
        f"## Verification\nPass\n",
        encoding="utf-8",
    )

    # Valid tree passes validation
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == [], errors

    # Check parsed state: open -> conditional: False
    t_parsed = te.parse_emergent_task_file(task_file, tasks_dir)
    assert t_parsed["conditional"] is False
    assert len(t_parsed["conditions"]) == 2
    assert t_parsed["conditions"][0]["status"] == "open"

    # Set state to done -> conditional: True
    task_file.write_text(task_file.read_text(encoding="utf-8").replace("- state: open", "- state: done"), encoding="utf-8")
    t_parsed_done = te.parse_emergent_task_file(task_file, tasks_dir)
    assert t_parsed_done["conditional"] is True

    # Error on unknown question in conditions
    bad_task = task_file.read_text(encoding="utf-8").replace(f"- conditions: {q1['id']}, {q2['id']}", "- conditions: Q999")
    task_file.write_text(bad_task, encoding="utf-8")
    errs_unknown, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("condition question 'Q999' not found in questions/" in e for e in errs_unknown)

    # Error on malformed question id
    malformed_task = task_file.read_text(encoding="utf-8").replace("- conditions: Q999", "- conditions: NOT_A_QUESTION")
    task_file.write_text(malformed_task, encoding="utf-8")
    errs_bad_id, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("invalid question id 'NOT_A_QUESTION' in conditions" in e for e in errs_bad_id)


def test_t030_sync_index_conditional_section_and_questions_answer(tmp_path: pathlib.Path) -> None:
    """T030: sync-index renders a Conditional section above Done; when conditions answered,
    task leaves Conditional section and appears in Done; questions answer --changes-result creates follow-up task."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "server-and-bindings").mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)

    # Ask Q001
    ok_q, q1 = te.ask_question(
        tasks_dir=tasks_dir,
        question="Keep feature X?",
        context="Context",
        options=[("keep", "Keep", None), ("drop", "Drop", None)],
        blocks="-",
    )
    assert ok_q is True, q1
    q1_id = q1["id"]

    # Create T001 (done, with condition Q001)
    t1_file = tasks_dir / "server-and-bindings" / "T001-conditional-done.md"
    t1_file.write_text(
        f"# T001 Feature X Implementation\n\n"
        f"- id: T001\n"
        f"- title: Feature X Implementation\n"
        f"- category: server-and-bindings\n"
        f"- priority: P2\n"
        f"- priority-reason: test\n"
        f"- next-up: no\n"
        f"- state: done\n"
        f"- executor: kilo\n"
        f"- depends-on: -\n"
        f"- decider: -\n"
        f"- sources: -\n"
        f"- paths: -\n"
        f"- handoff: -\n"
        f"- conditions: {q1_id}\n"
        f"- short: Feature X\n\n"
        f"## Goal\nImplemented.\n\n"
        f"## Steps\n1. Do\n\n"
        f"## Verification\nPass.\n",
        encoding="utf-8",
    )

    # Initial index sync
    run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    index_text = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")

    # ## Conditional must appear ABOVE ## Done
    assert "## Conditional" in index_text
    assert "## Done" in index_text
    cond_pos = index_text.index("## Conditional")
    done_pos = index_text.index("## Done")
    assert cond_pos < done_pos

    # T001 is listed as `done, conditional (Q001 (0 d, owner))` in Conditional
    assert f"done, conditional ({q1_id} (0 d, owner))" in index_text
    # T001 is NOT listed in ## Done
    done_section = index_text[done_pos:]
    assert "T001" not in done_section

    # Now answer Q001 with --changes-result
    ok_ans, ans_res = te.answer_question(
        tasks_dir=tasks_dir,
        question_id=q1_id,
        choice="drop",
        text="Decision is to drop feature X",
        changes_result=True,
    )
    assert ok_ans is True
    assert ans_res["conditions_resolved"] == ["T001"]
    assert "follow_up_tasks" in ans_res
    assert len(ans_res["follow_up_tasks"]) == 1
    fu_id = ans_res["follow_up_tasks"][0]

    # Verify follow-up task was created and linked via sources:
    fu_task = te.discover_emergent_tasks(tasks_dir)
    fu_match = next((t for t in fu_task if t["id"] == fu_id), None)
    assert fu_match is not None
    assert f"T001, {q1_id}" in fu_match["headers"]["sources"]

    # Sync index again
    run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    index_text_after = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")

    # Since all conditions of T001 are now answered, T001 leaves Conditional and is in Done.
    # No more conditional tasks -> ## Conditional and its marker are GONE!
    assert "## Conditional" not in index_text_after
    assert "<!-- ai-orch:generated conditional -->" not in index_text_after
    done_sec_after = index_text_after[index_text_after.index("## Done"):]
    assert "T001" in done_sec_after


def test_t029_parse_qualified_ref_letter_suffix() -> None:
    """T029: parse_qualified_ref accepts plan task ids with lowercase letter suffixes."""
    ref1 = te.parse_qualified_ref("06.1b")
    assert ref1["id"] == "06.1b"
    ref2 = te.parse_qualified_ref("my-proj/06.1b")
    assert ref2["project"] == "my-proj"
    assert ref2["id"] == "06.1b"
    ref3 = te.parse_qualified_ref("ws:my-proj/06.10a")
    assert ref3["workspace"] == "ws"
    assert ref3["project"] == "my-proj"
    assert ref3["id"] == "06.10a"


def test_t030_plan_task_conditions_and_json_output(tmp_path: pathlib.Path) -> None:
    """T030: plan-task conditions status line (**Conditions:** Q###), validation, JSON output,
    and questions answer --changes-result on plan tasks."""
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "06-control-plane"
    init_dir.mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # Ask Q001
    ok_q, q1 = te.ask_question(
        tasks_dir=tasks_dir,
        question="Plan condition question?",
        context="Context",
        options=[("opt1", "Option 1", None), ("opt2", "Option 2", None)],
        blocks="-",
    )
    assert ok_q is True
    q1_id = q1["id"]

    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 06 - Control Plane\n\n"
        "## Tasks\n\n"
        f"### 06.1 - First task\n\n"
        f"- **Status:** `done` · **Conditions:** {q1_id}\n"
        f"- **Goal:** Test plan conditions.\n",
        encoding="utf-8",
    )

    # Valid tree passes validation
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == [], errors

    tree = te.discover_task_tree(tasks_dir)
    node = tree["06.1"]
    assert node.conditional is True
    assert len(node.conditions) == 1
    assert node.conditions[0]["id"] == q1_id
    assert node.conditions[0]["status"] == "open"

    # Check to_dict() carries conditions and conditional
    d = node.to_dict()
    assert d["conditional"] is True
    assert d["conditions"] == node.conditions

    # Check cmd_list json output carries conditions and conditional
    res_list = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    list_payload = json.loads(res_list.stdout)
    assert list_payload["ok"] is True
    node_in_list = list_payload["tree"]["06.1"]
    assert node_in_list["conditional"] is True
    assert len(node_in_list["conditions"]) == 1

    # Answering Q001 with --changes-result resolves condition for 06.1 and creates follow-up task
    ok_ans, ans_res = te.answer_question(
        tasks_dir=tasks_dir,
        question_id=q1_id,
        choice="opt1",
        changes_result=True,
    )
    assert ok_ans is True
    assert "06.1" in ans_res["conditions_resolved"]
    assert len(ans_res["follow_up_tasks"]) == 1


def test_t030_canonical_optional_headers_order(tmp_path: pathlib.Path) -> None:
    """T030: conditions: header must follow canonical optional-field order (after moved-to, before short)."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "server-and-bindings").mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    ok_q, q1 = te.ask_question(
        tasks_dir=tasks_dir,
        question="Header order?",
        context="Context",
        options=[("a", "A", None), ("b", "B", None)],
        blocks="-",
    )
    assert ok_q is True
    q1_id = q1["id"]

    # Out-of-order: conditions before size (size is an optional field before conditions)
    bad_task = tasks_dir / "server-and-bindings" / "T001-bad-order.md"
    bad_task.write_text(
        f"# T001 Bad Order\n\n"
        f"- id: T001\n"
        f"- title: Bad Order\n"
        f"- category: server-and-bindings\n"
        f"- priority: P2\n"
        f"- priority-reason: test\n"
        f"- next-up: no\n"
        f"- state: open\n"
        f"- executor: kilo\n"
        f"- depends-on: -\n"
        f"- decider: -\n"
        f"- sources: -\n"
        f"- paths: -\n"
        f"- handoff: -\n"
        f"- conditions: {q1_id}\n"
        f"- size: M\n\n"
        f"## Goal\nG\n\n## Steps\n1. S\n\n## Verification\nV\n",
        encoding="utf-8",
    )
    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("optional header fields out of order" in e for e in errors)


def test_t031_conditional_done_followups(tmp_path: pathlib.Path) -> None:
    """T031: Condition age in days, decider in index; stale conditions line (>7d); JSON outputs."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "server-and-bindings").mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n\n## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n", encoding="utf-8")

    today = datetime.date.today()
    date_9d = (today - datetime.timedelta(days=9)).isoformat()
    date_2d = (today - datetime.timedelta(days=2)).isoformat()

    # Create Q003 (asked 9 days ago, decider owner)
    q3_file = tasks_dir / "questions" / "Q003-old-condition.md"
    q3_file.write_text(
        "# Q003 Old Condition\n\n"
        "- id: Q003\n"
        "- question: Old condition question?\n"
        "- status: open\n"
        "- blocks: -\n"
        "- decider: owner\n"
        "- asked-by: owner\n"
        f"- asked: {date_9d}\n"
        "- origin-run: -\n"
        "- open-answer: yes\n"
        "- recommended: -\n"
        "- short: Old condition\n\n"
        "## Context\nOld context.\n\n"
        "## Options\n- **A** — Opt A: consequence\n- **B** — Opt B: consequence\n\n"
        "## Answer\n- choice: -\n- text: -\n- answered-by: -\n- answered: -\n",
        encoding="utf-8",
    )

    # Create Q004 (asked 2 days ago, decider team)
    q4_file = tasks_dir / "questions" / "Q004-new-condition.md"
    q4_file.write_text(
        "# Q004 New Condition\n\n"
        "- id: Q004\n"
        "- question: New condition question?\n"
        "- status: open\n"
        "- blocks: -\n"
        "- decider: team\n"
        "- asked-by: owner\n"
        f"- asked: {date_2d}\n"
        "- origin-run: -\n"
        "- open-answer: yes\n"
        "- recommended: -\n"
        "- short: New condition\n\n"
        "## Context\nNew context.\n\n"
        "## Options\n- **A** — Opt A: consequence\n- **B** — Opt B: consequence\n\n"
        "## Answer\n- choice: -\n- text: -\n- answered-by: -\n- answered: -\n",
        encoding="utf-8",
    )

    # Create T012 (done, condition Q003)
    t12_file = tasks_dir / "server-and-bindings" / "T012-first-task.md"
    t12_file.write_text(
        "# T012 First Task\n\n"
        "- id: T012\n"
        "- title: First Task\n"
        "- category: server-and-bindings\n"
        "- priority: P2\n"
        "- priority-reason: test\n"
        "- next-up: no\n"
        "- state: done\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: -\n"
        "- conditions: Q003\n"
        "- short: First\n\n"
        "## Goal\nG1\n\n## Steps\n1. S1\n\n## Verification\nV1\n",
        encoding="utf-8",
    )

    # Create T015 (done, condition Q004)
    t15_file = tasks_dir / "server-and-bindings" / "T015-second-task.md"
    t15_file.write_text(
        "# T015 Second Task\n\n"
        "- id: T015\n"
        "- title: Second Task\n"
        "- category: server-and-bindings\n"
        "- priority: P2\n"
        "- priority-reason: test\n"
        "- next-up: no\n"
        "- state: done\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: -\n"
        "- conditions: Q004\n"
        "- short: Second\n\n"
        "## Goal\nG2\n\n## Steps\n1. S2\n\n## Verification\nV2\n",
        encoding="utf-8",
    )

    # Sync index
    run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    index_text = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")

    # Check table rows: age in whole days and decider
    assert "done, conditional (Q003 (9 d, owner))" in index_text
    assert "done, conditional (Q004 (2 d, team))" in index_text

    # Check stale line: Q003 (>7d) listed, Q004 (2d) NOT listed
    assert "Stale conditions (> 7 days): Q003 (9 d, owner) on T012" in index_text
    assert "on T015" not in index_text

    # Check JSON output
    res_list = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    payload = json.loads(res_list.stdout)
    assert payload["ok"] is True
    t12_json = payload["tree"]["T012"]
    assert t12_json["conditional"] is True
    assert t12_json["conditions"] == [
        {
            "id": "Q003",
            "status": "open",
            "short_title": "Old condition",
            "age_days": 9,
            "decider": "owner",
        }
    ]
    t15_json = payload["tree"]["T015"]
    assert t15_json["conditional"] is True
    assert t15_json["conditions"] == [
        {
            "id": "Q004",
            "status": "open",
            "short_title": "New condition",
            "age_days": 2,
            "decider": "team",
        }
    ]

    # When no conditions are stale (> 7 days), stale conditions line is omitted
    date_5d = (today - datetime.timedelta(days=5)).isoformat()
    q3_file.write_text(q3_file.read_text(encoding="utf-8").replace(f"- asked: {date_9d}", f"- asked: {date_5d}"), encoding="utf-8")
    run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    index_text_fresh = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "done, conditional (Q003 (5 d, owner))" in index_text_fresh
    assert "Stale conditions" not in index_text_fresh


def test_t031_header_field_order_error(tmp_path: pathlib.Path) -> None:
    """T031: Header field order error lists canonical sequence and identifies where misplaced field belongs."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "server-and-bindings").mkdir(parents=True)
    (tasks_dir / "questions").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    ok_q, q1 = te.ask_question(
        tasks_dir=tasks_dir,
        question="Header order check?",
        context="Context",
        options=[("a", "A", None), ("b", "B", None)],
        blocks="-",
    )
    assert ok_q is True
    q1_id = q1["id"]

    # Place conditions directly after handoff, but before verifier (canonical: verifier before conditions)
    bad_task = tasks_dir / "server-and-bindings" / "T020-bad-field-order.md"
    bad_task.write_text(
        f"# T020 Bad Field Order\n\n"
        f"- id: T020\n"
        f"- title: Bad Field Order\n"
        f"- category: server-and-bindings\n"
        f"- priority: P2\n"
        f"- priority-reason: test\n"
        f"- next-up: no\n"
        f"- state: open\n"
        f"- executor: kilo\n"
        f"- depends-on: -\n"
        f"- decider: -\n"
        f"- sources: -\n"
        f"- paths: -\n"
        f"- handoff: -\n"
        f"- conditions: {q1_id}\n"
        f"- verifier: owner\n\n"
        f"## Goal\nG\n\n## Steps\n1. S\n\n## Verification\nV\n",
        encoding="utf-8",
    )

    errors, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert len(errors) > 0
    err = next(e for e in errors if "optional header fields out of order" in e)
    # Checks expected order
    assert "got ['conditions', 'verifier'], expected ['verifier', 'conditions']" in err
    # Checks canonical sequence is listed
    assert f"Canonical sequence: {list(te.OPTIONAL_EXTENSION_FIELDS)}" in err
    # Checks where misplaced fields belong
    assert "field 'conditions' belongs after 'moved-to' and before 'waiting-on'" in err
    assert "field 'verifier' belongs after 'verification-mode' and before 'verify-by'" in err

    # Now fix the order: verifier before conditions
    good_task = bad_task.read_text(encoding="utf-8").replace(
        f"- conditions: {q1_id}\n- verifier: owner\n",
        f"- verifier: owner\n- conditions: {q1_id}\n",
    )
    bad_task.write_text(good_task, encoding="utf-8")
    errors_fixed, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors_fixed == [], errors_fixed


def test_ship_keeps_an_existing_summary(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "15-validation"
    init_dir.mkdir(parents=True)
    (init_dir / "plan.md").write_text(
        "# 15 - Validation\n\n> **Status:** `done`\n\n- **Goal:** G.\n\n## Tasks\n\n"
        "### 15.1 - Leaf task\n- **Status:** `done` (2026-10-17)\n- **Goal:** G1.\n",
        encoding="utf-8",
    )
    (tasks_dir / "specs").mkdir()
    (tasks_dir / "specs" / "validation.md").write_text("# Spec\n", encoding="utf-8")
    (init_dir / "summary.md").write_text(
        "# Summary: 15 - Validation\n\n- **Spec:** [`spec`](../specs/validation.md)\n\n## Outcome\n\nHand-written outcome.\n",
        encoding="utf-8",
    )

    dry = te.ship_initiative(tasks_dir, "15", dry_run=True)
    assert dry["ok"] is True
    res = te.ship_initiative(tasks_dir, "15", expect_plan_hash=dry["plan_hash"])
    assert res["ok"] is True

    summary = (tasks_dir / "done" / "15-validation" / "summary.md").read_text(encoding="utf-8")
    assert "Hand-written outcome." in summary
    assert "<outcome description" not in summary
    assert "](../../specs/validation.md)" in summary


def test_standalone_execution_no_orchestration_events_warning(tmp_path: pathlib.Path) -> None:
    # 1. Copy tasks_engine.py to an isolated folder in tmp_path (outside ai-orchestration)
    isolated_dir = tmp_path / "standalone_skill" / "scripts"
    isolated_dir.mkdir(parents=True)
    engine_copy = isolated_dir / "tasks_engine.py"
    shutil.copy2(SCRIPT_PATH, engine_copy)

    # 2. Set up a project directory with tasks/ inside tmp_path
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tasks_dir = project_dir / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n## Initiatives\n\n## Specs\n\n## Next up\n\n## Tasks by category\n\n## Decisions waiting\n\n## Done\n",
        encoding="utf-8",
    )

    def run_isolated(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(engine_copy), *args],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            check=False,
        )

    # 3. Test upgrade
    res_upg_prev = run_isolated("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_upg_prev.returncode == 0, f"upgrade preview failed: {res_upg_prev.stdout} {res_upg_prev.stderr}"
    assert "[warning] could not import orchestration_events" not in res_upg_prev.stderr
    upg_prev_data = json.loads(res_upg_prev.stdout)
    assert upg_prev_data["ok"] is True
    assert upg_prev_data["applied"] is False

    res_upg = run_isolated(
        "upgrade",
        "--tasks-dir",
        str(tasks_dir),
        "--apply",
        "--expect-plan-hash",
        upg_prev_data["plan_hash"],
        "--json",
    )
    assert res_upg.returncode == 0, f"upgrade apply failed: {res_upg.stdout} {res_upg.stderr}"
    assert "[warning] could not import orchestration_events" not in res_upg.stderr
    assert json.loads(res_upg.stdout)["applied"] is True

    # 4. Test new
    res_new = run_isolated(
        "new",
        "--tasks-dir", str(tasks_dir),
        "--category", "features",
        "--title", "Standalone task",
        "--priority", "P1",
        "--priority-reason", "Essential",
        "--goal", "Test standalone operation.",
        "--step", "Standalone step",
        "--verification", "python -c 'assert True'",
        "--json",
    )
    assert res_new.returncode == 0, f"new failed: {res_new.stdout} {res_new.stderr}"
    assert "[warning] could not import orchestration_events" not in res_new.stderr
    new_data = json.loads(res_new.stdout)
    task_id = new_data["id"]

    # 5. Test transition
    res_trans = run_isolated(
        "transition",
        "--tasks-dir", str(tasks_dir),
        task_id,
        "in progress",
        "--reason", "Starting work",
        "--json",
    )
    assert res_trans.returncode == 0, f"transition failed: {res_trans.stdout} {res_trans.stderr}"
    assert "[warning] could not import orchestration_events" not in res_trans.stderr

    # 6. Test validate
    res_val = run_isolated("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0, f"validate failed: {res_val.stdout} {res_val.stderr}"
    assert "[warning] could not import orchestration_events" not in res_val.stderr

    # 7. Test sync-index --apply
    res_sync = run_isolated("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res_sync.returncode == 0, f"sync-index failed: {res_sync.stdout} {res_sync.stderr}"
    assert "[warning] could not import orchestration_events" not in res_sync.stderr


def test_upgrade_creates_and_updates_tasks_gitignore(tmp_path: pathlib.Path) -> None:
    # 1. Fresh tasks dir without .gitignore
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n## Initiatives\n\n## Specs\n\n## Next up\n\n## Tasks by category\n\n## Decisions waiting\n\n## Done\n",
        encoding="utf-8",
    )

    # Dry-run first
    res_dry = te.upgrade_tasks_tree(tasks_dir, dry_run=True)
    assert res_dry["ok"] is True
    assert str(tasks_dir / ".gitignore") in res_dry["created"]
    assert str(tasks_dir / ".gitignore") in res_dry["upgraded_files"]
    assert not (tasks_dir / ".gitignore").exists()

    # Actual upgrade: creates tasks/.gitignore
    res = te.upgrade_tasks_tree(tasks_dir)
    assert res["ok"] is True
    assert str(tasks_dir / ".gitignore") in res["created"]
    assert str(tasks_dir / ".gitignore") in res["upgraded_files"]
    gi_path = tasks_dir / ".gitignore"
    assert gi_path.is_file()
    assert ".ai-orch.lock" in [line.strip() for line in gi_path.read_text(encoding="utf-8").splitlines()]

    # 2. Existing tasks/.gitignore with custom lines
    custom_tasks = tmp_path / "tasks_custom"
    custom_tasks.mkdir()
    (custom_tasks / "00-INDEX.md").write_text(
        "# Task Index\n\n## Initiatives\n\n## Specs\n\n## Next up\n\n## Tasks by category\n\n## Decisions waiting\n\n## Done\n",
        encoding="utf-8",
    )
    custom_gi = custom_tasks / ".gitignore"
    custom_gi.write_text("*.tmp\ncustom-entry\n", encoding="utf-8")

    # Dry run on existing
    res_dry2 = te.upgrade_tasks_tree(custom_tasks, dry_run=True)
    assert res_dry2["ok"] is True
    assert str(custom_gi) in res_dry2["updated"]
    assert str(custom_gi) in res_dry2["upgraded_files"]
    assert ".ai-orch.lock" not in custom_gi.read_text(encoding="utf-8")

    # Actual upgrade: preserves custom lines and appends .ai-orch.lock
    res2 = te.upgrade_tasks_tree(custom_tasks)
    assert res2["ok"] is True
    assert str(custom_gi) in res2["updated"]
    assert str(custom_gi) in res2["upgraded_files"]
    content = custom_gi.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]
    assert "*.tmp" in lines
    assert "custom-entry" in lines
    assert ".ai-orch.lock" in lines

    # Re-running upgrade when .ai-orch.lock already present -> not in created or updated
    res3 = te.upgrade_tasks_tree(custom_tasks)
    assert res3["ok"] is True
    assert str(custom_gi) not in res3["created"]
    assert str(custom_gi) not in res3["updated"]


# ===========================================================================
# T035 One-Shot Close, Derived State Refusal, Bulk Set-Short, Transition --to
# ===========================================================================


def test_one_shot_close_emergent_and_plan_task(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 1. 00-INDEX.md
    index_file = tasks_dir / "00-INDEX.md"
    index_file.write_text(
        "# Tasks\n\n"
        "## Initiatives\n\n"
        "<!-- ai-orch:generated initiatives -->\n"
        "| Priority | ID | Title | Status | Next up | Leaves Done | Short |\n"
        "|---|---|---|---|---|---|---|\n"
        "| P1 | 01 | Setup Initiative | open | yes | 0/1 | Setup |\n"
        "<!-- /ai-orch:generated initiatives -->\n\n"
        "## Tasks by category\n\n"
        "### features\n\n"
        "<!-- ai-orch:generated category:features -->\n"
        "| Priority | ID | Title | State | Next up | Executor | Decider |\n"
        "|---|---|---|---|---|---|---|\n"
        "| P1 | T001 | Test Emergent | in progress | yes | kilo | - |\n"
        "<!-- /ai-orch:generated category:features -->\n\n"
        "## Done\n\n"
        "<!-- ai-orch:generated done -->\n"
        "| Priority | ID | Title | Closed | Short |\n"
        "|---|---|---|---|---|\n"
        "<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )

    # 2. Emergent folder task
    folder_task_dir = tasks_dir / "features" / "T001-emergent"
    folder_task_dir.mkdir(parents=True)
    _write_sample_task(
        folder_task_dir / "README.md",
        task_id="T001",
        title="Test Emergent",
        category="features",
        state="in progress",
        executor="kilo",
    )
    (folder_task_dir / "PROGRESS.md").write_text("# Progress\n\n## Log (newest first)\n\n", encoding="utf-8")

    # 3. Plan task under 01-setup
    init_dir = tasks_dir / "01-setup"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 01 Setup Initiative\n\n"
        "- **Goal:** Setup goal.\n\n"
        "## Tasks\n\n"
        "### 01.1 - Setup Plan Task\n\n"
        "- **Status:** `in progress`\n"
        "- **Executor:** kilo\n"
        "- **Goal:** Do setup\n\n"
        "## Closed\n",
        encoding="utf-8",
    )

    # Refusal when verifier == executor without owner approval
    res_bad_ver = run_cli("close", "T001", "--verifier", "kilo", "--tasks-dir", str(tasks_dir), "--json")
    assert res_bad_ver.returncode == 1
    assert "Closing task requires an independent verifier" in res_bad_ver.stderr or "Closing task requires an independent verifier" in res_bad_ver.stdout

    # Close emergent task T001 with --verifier reviewer
    res_close_t001 = run_cli("close", "T001", "--verifier", "reviewer", "--tasks-dir", str(tasks_dir), "--json")
    assert res_close_t001.returncode == 0
    t001_data = json.loads(res_close_t001.stdout)
    assert t001_data["ok"] is True
    assert t001_data["old_state"] == "in progress"
    assert t001_data["new_state"] == "done"
    assert len(t001_data["transitions"]) == 3
    assert [t["to"] for t in t001_data["transitions"]] == ["delivered", "verified", "done"]

    # Verify emergent task moved to done/
    assert not (folder_task_dir / "README.md").exists()
    done_readme = tasks_dir / "done" / "features" / "T001-emergent" / "README.md"
    done_progress = tasks_dir / "done" / "features" / "T001-emergent" / "PROGRESS.md"
    assert done_readme.is_file()
    assert done_progress.is_file()

    # Verify all intermediate transitions recorded in PROGRESS.md
    prog_content = done_progress.read_text(encoding="utf-8")
    assert "state `in progress` -> `delivered`" in prog_content
    assert "state `delivered` -> `verified`" in prog_content
    assert "state `verified` -> `done`" in prog_content

    # Close plan task 01.1 with --verifier reviewer
    res_close_plan = run_cli("close", "01.1", "--verifier", "reviewer", "--tasks-dir", str(tasks_dir), "--json")
    assert res_close_plan.returncode == 0
    plan_data = json.loads(res_close_plan.stdout)
    assert plan_data["ok"] is True
    assert plan_data["old_state"] == "in progress"
    assert plan_data["new_state"] == "done"
    assert len(plan_data["transitions"]) == 3

    # Verify inline plan task is now in ## Closed
    plan_text = plan_file.read_text(encoding="utf-8")
    closed_part = plan_text.split("## Closed", 1)[1]
    assert "### 01.1 - Setup Plan Task" in closed_part
    assert "- **Status:** `done`" in closed_part

    # Verify 00-INDEX.md is updated
    index_text = index_file.read_text(encoding="utf-8")
    assert "T001" in index_text
    done_sec = index_text.split("## Done", 1)[1]
    assert "T001" in done_sec


def test_one_shot_close_caveat_and_owner_approved(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    task_file = tasks_dir / "features" / "T002-caveat.md"
    _write_sample_task(
        task_file,
        task_id="T002",
        title="Caveat test",
        category="features",
        state="in progress",
        executor="kilo",
    )

    # Close with --caveat and --owner-approved
    res = run_cli(
        "close",
        "T002",
        "--caveat",
        "manual testing only",
        "--owner-approved",
        "--tasks-dir",
        str(tasks_dir),
        "--json",
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["new_state"] == "done with a caveat: manual testing only"
    assert (tasks_dir / "done" / "features" / "T002-caveat.md").is_file()


def test_initiative_derived_state_transition_refusal(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    init_dir = tasks_dir / "01-core"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 01 Core Initiative\n\n"
        "- **Goal:** Core initiative goal.\n\n"
        "## Tasks\n\n"
        "### 01.1 - Task Alpha\n\n"
        "- **Status:** `open`\n"
        "- **Short:** Alpha\n"
        "- **Goal:** Alpha\n\n"
        "### 01.2 - Task Beta\n\n"
        "- **Status:** `in progress`\n"
        "- **Short:** Beta\n"
        "- **Goal:** Beta\n\n"
        "## Closed\n",
        encoding="utf-8",
    )

    # 1. Plain CLI transition on initiative 01
    res = run_cli("transition", "01", "in progress", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 1
    assert "Initiative '01' state is derived from its child tasks" in res.stderr
    assert "01.1 (Alpha): open" in res.stderr
    assert "01.2 (Beta): in progress" in res.stderr
    assert 'ai-orch tasks ship 01 --summary "..."' in res.stderr

    # 2. JSON mode
    res_json = run_cli("transition", "01", "--to", "delivered", "--tasks-dir", str(tasks_dir), "--json")
    assert res_json.returncode == 1
    data = json.loads(res_json.stdout)
    assert data["ok"] is False
    assert data["error"] == "derived state; transition its leaves"
    assert "Initiative '01' state is derived from its child tasks" in data["message"]
    assert len(data["open_children"]) == 2
    assert data["open_children"][0]["id"] == "01.1"
    assert data["open_children"][1]["id"] == "01.2"


def test_bulk_set_short_from_sources(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 00-INDEX.md
    index_file = tasks_dir / "00-INDEX.md"
    index_file.write_text(
        "# Tasks\n\n"
        "## Initiatives\n\n"
        "<!-- ai-orch:generated initiatives -->\n"
        "| Priority | ID | Title | Status | Next up | Leaves Done | Short |\n"
        "|---|---|---|---|---|---|---|\n"
        "| P1 | 01 | Setup Initiative | open | yes | 0/1 | Old |\n"
        "<!-- /ai-orch:generated initiatives -->\n\n"
        "## Tasks by category\n\n"
        "### features\n\n"
        "<!-- ai-orch:generated category:features -->\n"
        "| Priority | ID | Title | State | Next up | Executor | Decider |\n"
        "|---|---|---|---|---|---|---|\n"
        "| P1 | T001 | Test Emergent | open | yes | kilo | - |\n"
        "<!-- /ai-orch:generated category:features -->\n\n"
        "## Done\n\n"
        "<!-- ai-orch:generated done -->\n"
        "| Priority | ID | Title | Closed | Short |\n"
        "|---|---|---|---|---|\n"
        "<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )

    # Emergent task
    t001_file = tasks_dir / "features" / "T001-scraper.md"
    _write_sample_task(t001_file, task_id="T001", title="Scraper Task", category="features")

    # Plan task
    init_dir = tasks_dir / "01-setup"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 01 Setup Initiative\n\n"
        "- **Goal:** Setup goal.\n\n"
        "## Tasks\n\n"
        "### 01.1 - Setup Task\n\n"
        "- **Status:** `open`\n"
        "- **Goal:** Setup\n\n"
        "## Closed\n",
        encoding="utf-8",
    )

    # 1. Bulk set-short with inline JSON string
    inline_json = json.dumps({"T001": "Short Scraper", "01.1": "Short Setup"})
    res_inline = run_cli("set-short", "--from", inline_json, "--tasks-dir", str(tasks_dir), "--json")
    assert res_inline.returncode == 0
    data_inline = json.loads(res_inline.stdout)
    assert data_inline["ok"] is True
    assert len(data_inline["updated"]) == 2
    assert {u["id"]: u["short_title"] for u in data_inline["updated"]} == {
        "T001": "Short Scraper",
        "01.1": "Short Setup",
    }

    # Verify task contents
    assert "- short: Short Scraper" in t001_file.read_text(encoding="utf-8")
    assert "**Short:** Short Setup" in plan_file.read_text(encoding="utf-8")

    # 2. Bulk set-short from lines file (key=value / id: short)
    pairs_file = tmp_path / "shorts.txt"
    pairs_file.write_text("T001: Fast Scraper\n01.1=Fast Setup\n", encoding="utf-8")

    res_file = run_cli("set-short", "--from", str(pairs_file), "--tasks-dir", str(tasks_dir), "--json")
    assert res_file.returncode == 0
    data_file = json.loads(res_file.stdout)
    assert data_file["ok"] is True
    assert {u["id"]: u["short_title"] for u in data_file["updated"]} == {
        "T001": "Fast Scraper",
        "01.1": "Fast Setup",
    }
    assert "- short: Fast Scraper" in t001_file.read_text(encoding="utf-8")
    assert "**Short:** Fast Setup" in plan_file.read_text(encoding="utf-8")


def test_transition_to_flag_and_positional(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    task_file = tasks_dir / "features" / "T001-flag.md"
    _write_sample_task(task_file, task_id="T001", state="open")

    # 1. --to flag
    res_flag = run_cli("transition", "T001", "--to", "in progress", "--tasks-dir", str(tasks_dir), "--json")
    assert res_flag.returncode == 0
    data_flag = json.loads(res_flag.stdout)
    assert data_flag["ok"] is True
    assert data_flag["new_state"] == "in progress"

    # 2. Positional
    res_pos = run_cli("transition", "T001", "delivered", "--tasks-dir", str(tasks_dir), "--json")
    assert res_pos.returncode == 0
    data_pos = json.loads(res_pos.stdout)
    assert data_pos["ok"] is True
    assert data_pos["new_state"] == "delivered"

    # 3. Missing target state -> exit 2
    res_missing = run_cli("transition", "T001", "--tasks-dir", str(tasks_dir))
    assert res_missing.returncode == 2
    assert "Missing target state" in res_missing.stderr

    # 4. Conflicting target states -> exit 2
    res_conflict = run_cli("transition", "T001", "verified", "--to", "bounced", "--tasks-dir", str(tasks_dir))
    assert res_conflict.returncode == 2
    assert "Conflicting target states" in res_conflict.stderr


def test_t041_unapplied_answers_surfaced_and_applied_lifecycle(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(task_file, task_id="T001", state="in progress")

    # 1. Ask question Q001 blocking T001
    ok_ask, res_ask = te.ask_question(
        tasks_dir,
        question="Which authentication scheme should we use?",
        context="We need to choose between JWT and Session tokens.",
        options=[("A", "JWT", "Stateless"), ("B", "Session", "Stateful")],
        blocks="T001",
        short="Auth scheme",
    )
    assert ok_ask is True
    qid = res_ask["id"]

    # T001 is waiting on Q001
    tree = te.discover_task_tree(tasks_dir)
    assert tree["T001"].state == "waiting"

    # 2. Answer question
    ok_ans, res_ans = te.answer_question(tasks_dir, qid, choice="A", text="Chose JWT")
    assert ok_ans is True

    # Question file now has applied: no
    q_file = pathlib.Path(res_ask["file_path"])
    assert q_file.is_file()
    assert "- applied: no" in q_file.read_text(encoding="utf-8")

    # Move question to questions/answered/ to test discovery in subfolder
    ans_dir = tasks_dir / "questions" / "answered"
    ans_dir.mkdir(parents=True, exist_ok=True)
    ans_file = ans_dir / q_file.name
    shutil.move(str(q_file), str(ans_file))
    assert ans_file.is_file()
    assert not q_file.exists()

    # 3. questions list --status unapplied surfaces Q001
    ok_list, res_list = te.list_questions(tasks_dir, status="unapplied")
    assert ok_list is True
    assert len(res_list["questions"]) == 1
    assert res_list["questions"][0]["id"] == qid
    assert res_list["questions"][0]["applied"] is False

    # Default questions list includes unapplied_answers
    ok_list_all, res_list_all = te.list_questions(tasks_dir, status="all")
    assert ok_list_all is True
    assert len(res_list_all["unapplied_answers"]) == 1
    assert res_list_all["unapplied_answers"][0]["id"] == qid

    # CLI questions list output includes notice
    res_cli_list = run_cli("questions", "list", "--tasks-dir", str(tasks_dir))
    assert res_cli_list.returncode == 0
    assert "[NOTICE]" in res_cli_list.stdout
    assert "waiting to be applied" in res_cli_list.stdout
    assert qid in res_cli_list.stdout

    # validate_tasks_tree emits warning for unapplied answered question
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert any("has not been applied (run 'ai-orch questions apply Q001" in w for w in warnings)

    # 4. Apply question
    res_apply = run_cli("questions", "apply", qid, "--note", "Implemented in PR #42", "--tasks-dir", str(tasks_dir), "--json")
    assert res_apply.returncode == 0
    data_apply = json.loads(res_apply.stdout)
    assert data_apply["ok"] is True
    assert data_apply["status"] == "applied"

    # Header in file is now applied: yes
    assert "- applied: yes" in ans_file.read_text(encoding="utf-8")

    # questions list --status unapplied is now empty
    ok_list_post, res_list_post = te.list_questions(tasks_dir, status="unapplied")
    assert ok_list_post is True
    assert len(res_list_post["questions"]) == 0

    # validate_tasks_tree has no warning for Q001
    errors_post, warnings_post, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors_post == []
    assert not any(qid in w for w in warnings_post)


def test_t041_questions_move_to_tracker(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "features" / "T010-feature.md"
    _write_sample_task(task_file, task_id="T010", state="in progress")

    # Ask question Q001 blocking T010
    ok_ask, res_ask = te.ask_question(
        tasks_dir,
        question="Should we support external OAuth providers?",
        context="OAuth integration requires coordination with central identity.",
        options=[("A", "Yes", "Add OAuth"), ("B", "No", "Local auth only")],
        blocks="T010",
        short="OAuth support",
    )
    assert ok_ask is True
    qid = res_ask["id"]

    # Verify T010 is waiting
    tree = te.discover_task_tree(tasks_dir)
    assert tree["T010"].state == "waiting"

    # Move question to external tracker via CLI
    tracker_url = "https://tracker.example/issue/42"
    res_move = run_cli(
        "questions",
        "move",
        qid,
        "--to",
        tracker_url,
        "--reason",
        "Handed off to enterprise security team",
        "--tasks-dir",
        str(tasks_dir),
        "--json",
    )
    assert res_move.returncode == 0
    data_move = json.loads(res_move.stdout)
    assert data_move["ok"] is True
    assert data_move["status"] == "moved"
    assert data_move["moved_to"] == tracker_url
    assert "T010" in data_move["unblocked_tasks"]

    # Question file moved to questions/answered/
    moved_path = pathlib.Path(data_move["file_path"])
    assert moved_path.is_file()
    assert "questions/answered" in moved_path.as_posix()
    assert not pathlib.Path(res_ask["file_path"]).exists()

    moved_text = moved_path.read_text(encoding="utf-8")
    assert "- status: moved" in moved_text
    assert f"- moved-to: {tracker_url}" in moved_text
    assert "- reason: Handed off to enterprise security team" in moved_text
    assert "- choice: moved" in moved_text

    # Blocked task T010 unblocked back to in progress
    tree_post = te.discover_task_tree(tasks_dir)
    assert tree_post["T010"].state == "in progress"
    assert tree_post["T010"].fields.get("decider", {}).get("value") in ("-", "", None)

    # validate_tasks_tree passes with 0 errors
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []

    # questions list --status moved returns Q001
    ok_list, res_list = te.list_questions(tasks_dir, status="moved")
    assert ok_list is True
    assert len(res_list["questions"]) == 1
    assert res_list["questions"][0]["id"] == qid
    assert res_list["questions"][0]["status"] == "moved"


def test_t041_non_blocking_questions_with_notes(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 1. Ask question with --blocks - and --notes via function
    ok_ask1, res_ask1 = te.ask_question(
        tasks_dir,
        question="Which database engine should be used for analytics?",
        context="Evaluating ClickHouse vs DuckDB for time-series aggregation.",
        options=[("A", "ClickHouse", "Distributed cluster"), ("B", "DuckDB", "Embedded in-process")],
        blocks="-",
        notes="Benchmarks show DuckDB is 3x faster on single node, but ClickHouse scales horizontally.",
    )
    assert ok_ask1 is True
    q1_file = pathlib.Path(res_ask1["file_path"])
    assert q1_file.is_file()
    q1_text = q1_file.read_text(encoding="utf-8")
    assert "- blocks: -" in q1_text
    assert "## Notes" in q1_text
    assert "Benchmarks show DuckDB is 3x faster" in q1_text

    # 2. Ask question with omitted --blocks and --notes via CLI
    res_ask2 = run_cli(
        "questions",
        "ask",
        "--question",
        "Should we enable compression for event logs?",
        "--context",
        "Disk usage is growing at 50GB/day.",
        "--option",
        "A=Zstd: Best ratio",
        "--option",
        "B=Lz4: Fastest speed",
        "--notes",
        "Zstd level 3 offers a good compromise between CPU and compression ratio.",
        "--tasks-dir",
        str(tasks_dir),
        "--json",
    )
    assert res_ask2.returncode == 0
    data_ask2 = json.loads(res_ask2.stdout)
    assert data_ask2["ok"] is True
    q2_id = data_ask2["id"]
    q2_file = pathlib.Path(data_ask2["file_path"])
    assert q2_file.is_file()
    q2_text = q2_file.read_text(encoding="utf-8")
    assert "- blocks: -" in q2_text
    assert "## Notes" in q2_text
    assert "Zstd level 3 offers a good compromise" in q2_text

    # 3. validate_tasks_tree validates both non-blocking questions cleanly with 0 errors
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []

    # 4. show_question parses notes and blocks
    ok_show, res_show = te.show_question(tasks_dir, q2_id)
    assert ok_show is True
    assert res_show["question"]["blocks"] == "-"
    assert "Zstd level 3" in res_show["question"]["notes"]


def test_tasks_new_with_step_and_verification(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Create task with repeatable --step and --verification
    res = run_cli(
        "new",
        "--category", "features",
        "--title", "Auth service redesign",
        "--priority", "P1",
        "--priority-reason", "Refactoring",
        "--goal", "Redesign the auth service module.",
        "--step", "First step",
        "--step", "Second step",
        "--step", "- [x] Third already done step",
        "--verification", "pytest -q tests/test_auth.py",
        "--verification", "- check_auth_endpoint",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    data = json.loads(res.stdout)
    assert data["ok"] is True
    t_id = data["id"]
    t_file = tasks_dir / data["rel_path"]
    content = t_file.read_text(encoding="utf-8")

    assert "- [ ] First step" in content
    assert "- [ ] Second step" in content
    assert "- [x] Third already done step" in content
    assert "- pytest -q tests/test_auth.py" in content
    assert "- check_auth_endpoint" in content
    assert "- [ ] Step 1" not in content
    assert "- Command or check that proves completion" not in content

    # validate passes with zero errors and zero warnings
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    val_data = json.loads(res_val.stdout)
    assert val_data["errors"] == []
    assert val_data["warnings"] == []

    # 2. Default task without --step or --verification creates default placeholders
    res_default = run_cli(
        "new",
        "--category", "bugfix",
        "--title", "Fix null pointer",
        "--priority", "P2",
        "--priority-reason", "Sentry alert",
        "--goal", "Fix null pointer in parser.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_default.returncode == 0
    t2_file = tasks_dir / json.loads(res_default.stdout)["rel_path"]
    t2_content = t2_file.read_text(encoding="utf-8")
    assert "- [ ] Step 1" in t2_content
    assert "- Command or check that proves completion" in t2_content

    # In open state, validate generates warnings but zero errors
    res_val2 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val2.returncode == 0
    val_data2 = json.loads(res_val2.stdout)
    assert len(val_data2["errors"]) == 0
    assert any("placeholder in ## Steps" in w for w in val_data2["warnings"])
    assert any("placeholder in ## Verification" in w for w in val_data2["warnings"])


def test_tasks_step_checklist_commands(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Create task with default placeholder
    res_new = run_cli(
        "new",
        "--category", "features",
        "--title", "Step checklist management",
        "--priority", "P2",
        "--priority-reason", "Feature request N017",
        "--goal", "Add step checklist subcommands.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new.returncode == 0
    task_id = json.loads(res_new.stdout)["id"]

    # 1. step list shows the initial Step 1 placeholder
    res_list1 = run_cli("step", "list", task_id, "--tasks-dir", str(tasks_dir), "--json")
    assert res_list1.returncode == 0
    data_list1 = json.loads(res_list1.stdout)
    assert data_list1["ok"] is True
    assert data_list1["count"] == 1
    assert data_list1["steps"] == [{"index": 1, "checked": False, "text": "Step 1"}]

    # 2. step add replaces the solitary placeholder
    res_add1 = run_cli("step", "add", task_id, "Implement core logic", "--tasks-dir", str(tasks_dir), "--json")
    assert res_add1.returncode == 0
    data_add1 = json.loads(res_add1.stdout)
    assert data_add1["ok"] is True
    assert data_add1["step"] == {"index": 1, "checked": False, "text": "Implement core logic"}
    assert len(data_add1["steps"]) == 1
    assert data_add1["steps"][0]["text"] == "Implement core logic"

    # 3. step add appends subsequent steps
    res_add2 = run_cli("step", "add", task_id, "Write unit tests", "--tasks-dir", str(tasks_dir), "--json")
    assert res_add2.returncode == 0
    data_add2 = json.loads(res_add2.stdout)
    assert data_add2["ok"] is True
    assert data_add2["step"] == {"index": 2, "checked": False, "text": "Write unit tests"}
    assert len(data_add2["steps"]) == 2

    # Verify via step list human-readable output
    res_list_human = run_cli("step", "list", task_id, "--tasks-dir", str(tasks_dir))
    assert res_list_human.returncode == 0
    assert "1. [ ] Implement core logic" in res_list_human.stdout
    assert "2. [ ] Write unit tests" in res_list_human.stdout

    # 4. step check by index
    res_chk1 = run_cli("step", "check", task_id, "1", "--tasks-dir", str(tasks_dir), "--json")
    assert res_chk1.returncode == 0
    data_chk1 = json.loads(res_chk1.stdout)
    assert data_chk1["ok"] is True
    assert data_chk1["step"]["checked"] is True
    assert data_chk1["steps"][0]["checked"] is True
    assert data_chk1["steps"][1]["checked"] is False

    # 5. step check by case-insensitive substring
    res_chk2 = run_cli("step", "check", task_id, "unit tests", "--tasks-dir", str(tasks_dir), "--json")
    assert res_chk2.returncode == 0
    data_chk2 = json.loads(res_chk2.stdout)
    assert data_chk2["ok"] is True
    assert data_chk2["step"]["checked"] is True
    assert data_chk2["steps"][1]["checked"] is True

    # 6. step uncheck by index
    res_unchk1 = run_cli("step", "uncheck", task_id, "1", "--tasks-dir", str(tasks_dir), "--json")
    assert res_unchk1.returncode == 0
    data_unchk1 = json.loads(res_unchk1.stdout)
    assert data_unchk1["ok"] is True
    assert data_unchk1["step"]["checked"] is False
    assert data_unchk1["steps"][0]["checked"] is False
    assert data_unchk1["steps"][1]["checked"] is True

    # 7. step uncheck by substring
    res_unchk2 = run_cli("step", "uncheck", task_id, "write", "--tasks-dir", str(tasks_dir), "--json")
    assert res_unchk2.returncode == 0
    data_unchk2 = json.loads(res_unchk2.stdout)
    assert data_unchk2["ok"] is True
    assert data_unchk2["step"]["checked"] is False
    assert data_unchk2["steps"][1]["checked"] is False

    # 8. Error cases: index out of bounds
    res_oob = run_cli("step", "check", task_id, "99", "--tasks-dir", str(tasks_dir), "--json")
    assert res_oob.returncode != 0
    assert "out of range" in json.loads(res_oob.stdout)["error"]

    # 9. Error cases: substring not found
    res_notfound = run_cli("step", "check", task_id, "nonexistent-step", "--tasks-dir", str(tasks_dir), "--json")
    assert res_notfound.returncode != 0
    assert "No step matching" in json.loads(res_notfound.stdout)["error"]

    # 10. Error cases: ambiguous substring
    run_cli("step", "add", task_id, "Write integration tests", "--tasks-dir", str(tasks_dir))
    res_ambig = run_cli("step", "check", task_id, "tests", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ambig.returncode != 0
    assert "Multiple steps match" in json.loads(res_ambig.stdout)["error"]

    # 11. Hash checking
    current_hash = data_unchk2["task_hash"]
    res_hash_ok = run_cli("step", "add", task_id, "Step with correct hash", "--expect-task-hash", current_hash, "--tasks-dir", str(tasks_dir), "--json")
    # Since we added "Write integration tests" in between, current_hash is stale
    assert res_hash_ok.returncode != 0
    assert "stale-task-hash" in json.loads(res_hash_ok.stdout)["error"]

    # 12. is_mutating_command registration check
    parser = te.build_parser()
    args_list = parser.parse_args(["step", "list", task_id])
    assert te.is_mutating_command(args_list) is False
    args_add = parser.parse_args(["step", "add", task_id, "New step"])
    assert te.is_mutating_command(args_add) is True
    args_check = parser.parse_args(["step", "check", task_id, "1"])
    assert te.is_mutating_command(args_check) is True
    args_uncheck = parser.parse_args(["step", "uncheck", task_id, "1"])
    assert te.is_mutating_command(args_uncheck) is True


def test_tasks_validate_flagging_placeholders(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Create a task with placeholders
    res_new = run_cli(
        "new",
        "--category", "features",
        "--title", "Placeholder validation test",
        "--priority", "P2",
        "--priority-reason", "Testing validate",
        "--goal", "Test that validate flags placeholders.",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_new.returncode == 0
    task_id = json.loads(res_new.stdout)["id"]
    t_file = tasks_dir / json.loads(res_new.stdout)["rel_path"]

    # In open state: warnings only, zero errors
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert any("placeholder in ## Steps" in w for w in warnings)
    assert any("placeholder in ## Verification" in w for w in warnings)

    # 2. Transition to in progress: placeholders now trigger errors!
    res_tr = run_cli("transition", task_id, "in progress", "--actor", "kilo", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr.returncode == 0

    errors_ip, warnings_ip, _, _ = te.validate_tasks_tree(tasks_dir)
    assert len(errors_ip) >= 2
    assert any("in state 'in progress' contains unedited placeholder in ## Steps" in e for e in errors_ip)
    assert any("in state 'in progress' contains unedited placeholder in ## Verification" in e for e in errors_ip)

    # 3. Test other placeholders like TODO: Step 1 and TODO: Command or check
    t_content = t_file.read_text(encoding="utf-8")
    t_content_todo = t_content.replace("- [ ] Step 1", "- [ ] TODO: Step 1").replace(
        "- Command or check that proves completion", "- [ ] TODO: Command or check"
    )
    t_file.write_text(t_content_todo, encoding="utf-8")

    errors_todo, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("contains unedited placeholder in ## Steps" in e for e in errors_todo)
    assert any("contains unedited placeholder in ## Verification" in e for e in errors_todo)

    # 4. Once edited with real steps and verifications, validate passes cleanly
    t_content_clean = t_content.replace("- [ ] Step 1", "- [ ] Implement the feature cleanly").replace(
        "- Command or check that proves completion", "- pytest tests/test_feature.py"
    )
    t_file.write_text(t_content_clean, encoding="utf-8")

    errors_clean, warnings_clean, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors_clean == []
    assert not any("placeholder" in w for w in warnings_clean)


# ===========================================================================
# T037 Task Index Without Merge Conflicts Across Parallel Worktrees
# ===========================================================================


def test_sync_index_heals_git_conflict_markers_and_merge_index(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    _write_sample_task(
        tasks_dir / "features" / "T001-feature-a.md",
        task_id="T001",
        title="Feature A",
        category="features",
        priority="P1",
        next_up="yes",
    )
    _write_sample_task(
        tasks_dir / "features" / "T002-feature-b.md",
        task_id="T002",
        title="Feature B",
        category="features",
        priority="P1",
        next_up="yes",
    )

    index_path = tasks_dir / "00-INDEX.md"
    conflicted_content = """<<<<<<< HEAD
# Task Index — Our Project
Preamble from HEAD.
=======
# Task Index — Their Project
Preamble from branch.
>>>>>>> branch-b

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
<<<<<<< HEAD
| T001 | P1 | [Feature A](features/T001-feature-a.md) | kilo | `do A` |
=======
| T002 | P1 | [Feature B](features/T002-feature-b.md) | kilo | `do B` |
>>>>>>> branch-b
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
### features

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
<<<<<<< HEAD
| T001 | P1 | [Feature A](features/T001-feature-a.md) | open | kilo | - |
=======
| T002 | P1 | [Feature B](features/T002-feature-b.md) | open | kilo | - |
>>>>>>> branch-b
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| - | None. | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
<!-- /ai-orch:generated done -->
"""
    index_path.write_text(conflicted_content, encoding="utf-8")

    # validate_tasks_tree reports clear conflict marker error
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("00-INDEX.md contains unresolved git conflict markers" in e for e in errors)
    assert any("ai-orch tasks sync-index --apply" in e for e in errors)

    # 1. sync-index --apply cleanly heals the conflicted index
    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res_sync.returncode == 0
    payload = json.loads(res_sync.stdout)
    assert payload["ok"] is True
    assert payload["applied"] is True

    healed_text = index_path.read_text(encoding="utf-8")
    assert "<<<<<<<" not in healed_text
    assert "=======" not in healed_text
    assert ">>>>>>>" not in healed_text
    assert "Preamble from HEAD." in healed_text
    assert "Preamble from branch." not in healed_text

    # Both tasks are present in Next up and Tasks by category
    assert "| T001 (Feature A) | P1 | [Feature A](features/T001-feature-a.md) |" in healed_text
    assert "| T002 (Feature B) | P1 | [Feature B](features/T002-feature-b.md) |" in healed_text

    # Validate passes cleanly with zero errors
    errors_after, _, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors_after == []

    # 2. Re-introduce conflict markers and test merge-index command (standalone mode)
    index_path.write_text(conflicted_content, encoding="utf-8")
    res_merge_standalone = run_cli("merge-index", "--tasks-dir", str(tasks_dir), "--json")
    assert res_merge_standalone.returncode == 0
    merge_payload = json.loads(res_merge_standalone.stdout)
    assert merge_payload["ok"] is True
    assert merge_payload["merged"] is True

    healed_merge_text = index_path.read_text(encoding="utf-8")
    assert "<<<<<<<" not in healed_merge_text
    assert "| T001 (Feature A) | P1 | [Feature A](features/T001-feature-a.md) |" in healed_merge_text
    assert "| T002 (Feature B) | P1 | [Feature B](features/T002-feature-b.md) |" in healed_merge_text

    # 3. Test merge-index as git custom merge driver: %O %A %B
    temp_base = tmp_path / "base_INDEX.md"
    temp_ours = tmp_path / "ours_INDEX.md"
    temp_theirs = tmp_path / "theirs_INDEX.md"
    temp_base.write_text("# Base Index\n", encoding="utf-8")
    temp_theirs.write_text("# Theirs Index\n", encoding="utf-8")
    temp_ours.write_text(conflicted_content, encoding="utf-8")

    res_driver = run_cli("merge-index", str(temp_base), str(temp_ours), str(temp_theirs), "--tasks-dir", str(tasks_dir))
    assert res_driver.returncode == 0
    ours_merged = temp_ours.read_text(encoding="utf-8")
    assert "<<<<<<<" not in ours_merged
    assert "| T001 (Feature A) | P1 | [Feature A](features/T001-feature-a.md) |" in ours_merged
    assert "| T002 (Feature B) | P1 | [Feature B](features/T002-feature-b.md) |" in ours_merged


def test_merge_index_parallel_branches_union_and_deterministic_order(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "engine").mkdir(parents=True)
    (tasks_dir / "done" / "engine").mkdir(parents=True)

    # Branch A added T035 (closed) and T037 (open, P1)
    _write_sample_task(
        tasks_dir / "done" / "engine" / "T035-one-shot.md",
        task_id="T035",
        title="One-shot close",
        category="engine",
        priority="P1",
        state="done",
    )
    _write_sample_task(
        tasks_dir / "engine" / "T037-conflict-free.md",
        task_id="T037",
        title="Conflict free index",
        category="engine",
        priority="P1",
        next_up="yes",
    )

    # Branch B added T034 (closed) and T038 (open, P2)
    _write_sample_task(
        tasks_dir / "done" / "engine" / "T034-feedback.md",
        task_id="T034",
        title="Tooling feedback",
        category="engine",
        priority="P2",
        state="done",
    )
    _write_sample_task(
        tasks_dir / "engine" / "T038-stable-entry.md",
        task_id="T038",
        title="Stable entry point",
        category="engine",
        priority="P2",
        next_up="yes",
    )

    # Simulated git merge conflict in 00-INDEX.md with duplicate rows from partial merge
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
<<<<<<< HEAD
| T037 | P1 | [Conflict free index](engine/T037-conflict-free.md) | kilo | `do it` |
=======
| T038 | P2 | [Stable entry point](engine/T038-stable-entry.md) | kilo | `do it` |
>>>>>>> branch-b
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
### engine

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T037 | P1 | [Conflict free index](engine/T037-conflict-free.md) | open | kilo | - |
| T037 | P1 | [Conflict free index](engine/T037-conflict-free.md) | open | kilo | - |
<<<<<<< HEAD
| T037 | P1 | [Conflict free index](engine/T037-conflict-free.md) | open | kilo | - |
=======
| T038 | P2 | [Stable entry point](engine/T038-stable-entry.md) | open | kilo | - |
>>>>>>> branch-b
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| - | None. | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
<<<<<<< HEAD
| T035 | [One-shot close](done/engine/T035-one-shot.md) | done | 2026-10-21 |
=======
| T034 | [Tooling feedback](done/engine/T034-feedback.md) | done | 2026-10-21 |
>>>>>>> branch-b
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )

    # Run tasks merge-index
    res_merge = run_cli("merge-index", "--tasks-dir", str(tasks_dir), "--json")
    assert res_merge.returncode == 0

    healed_content = index_path.read_text(encoding="utf-8")
    assert "<<<<<<<" not in healed_content
    assert "=======" not in healed_content
    assert ">>>>>>>" not in healed_content

    # No duplicate T037 rows
    assert healed_content.count("| T037 (Conflict free index) |") == 2  # Once in Next up, once in Tasks by category

    # Deterministic order in Next up: T037 (P1) before T038 (P2)
    pos_t37_next = healed_content.find("| T037 (Conflict free index) | P1 | [Conflict free index]")
    pos_t38_next = healed_content.find("| T038 (Stable entry point) | P2 | [Stable entry point]")
    assert pos_t37_next < pos_t38_next

    # Deterministic order in category table: T037 before T038
    pos_t37_cat = healed_content.find("| T037 (Conflict free index) | P1 | [Conflict free index](engine/T037-conflict-free.md) | open |")
    pos_t38_cat = healed_content.find("| T038 (Stable entry point) | P2 | [Stable entry point](engine/T038-stable-entry.md) | open |")
    assert pos_t37_cat < pos_t38_cat

    # Both Done tasks present
    assert "| T035 (One-shot close) | [One-shot close](done/engine/T035-one-shot.md) |" in healed_content
    assert "| T034 (Tooling feedback) | [Tooling feedback](done/engine/T034-feedback.md) |" in healed_content

    # Validates cleanly
    errs, warns, emergent, _ = te.validate_tasks_tree(tasks_dir)
    assert errs == []
    assert len(emergent) == 4


def test_upgrade_creates_and_updates_tasks_gitattributes(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n## Initiatives\n\n## Specs\n\n## Next up\n\n## Tasks by category\n\n## Decisions waiting\n\n## Done\n",
        encoding="utf-8",
    )

    # 1. Dry run on fresh tasks dir without .gitattributes
    res_dry = te.upgrade_tasks_tree(tasks_dir, dry_run=True)
    assert res_dry["ok"] is True
    ga_path = tasks_dir / ".gitattributes"
    assert str(ga_path) in res_dry["created"]
    assert str(ga_path) in res_dry["upgraded_files"]
    assert not ga_path.exists()

    # 2. Real run creates tasks/.gitattributes with rule
    res_real = te.upgrade_tasks_tree(tasks_dir)
    assert res_real["ok"] is True
    assert str(ga_path) in res_real["created"]
    assert str(ga_path) in res_real["upgraded_files"]
    assert ga_path.is_file()
    assert "00-INDEX.md merge=ai-orch-index" in [line.strip() for line in ga_path.read_text(encoding="utf-8").splitlines()]

    # 3. Existing .gitattributes with custom lines
    custom_tasks = tmp_path / "tasks_custom"
    custom_tasks.mkdir()
    (custom_tasks / "00-INDEX.md").write_text(
        "# Task Index\n\n## Initiatives\n\n## Specs\n\n## Next up\n\n## Tasks by category\n\n## Decisions waiting\n\n## Done\n",
        encoding="utf-8",
    )
    custom_ga = custom_tasks / ".gitattributes"
    custom_ga.write_text("*.pdf binary\n*.png binary\n", encoding="utf-8")

    # Dry run shows updated
    res_dry2 = te.upgrade_tasks_tree(custom_tasks, dry_run=True)
    assert res_dry2["ok"] is True
    assert str(custom_ga) in res_dry2["updated"]
    assert str(custom_ga) in res_dry2["upgraded_files"]
    assert "00-INDEX.md merge=ai-orch-index" not in custom_ga.read_text(encoding="utf-8")

    # Real run preserves custom lines and appends rule
    res_real2 = te.upgrade_tasks_tree(custom_tasks)
    assert res_real2["ok"] is True
    assert str(custom_ga) in res_real2["updated"]
    assert str(custom_ga) in res_real2["upgraded_files"]
    lines = [line.strip() for line in custom_ga.read_text(encoding="utf-8").splitlines()]
    assert "*.pdf binary" in lines
    assert "*.png binary" in lines
    assert "00-INDEX.md merge=ai-orch-index" in lines

    # 4. Re-run upgrade when rule is already present -> not in created or updated
    res_rerun = te.upgrade_tasks_tree(custom_tasks)
    assert res_rerun["ok"] is True
    assert str(custom_ga) not in res_rerun["created"]
    assert str(custom_ga) not in res_rerun["updated"]


def test_t042_waiting_on_emergent_task_transition_and_index(tmp_path: pathlib.Path) -> None:
    """T042: tasks transition T001 waiting --waiting-on sets header, updates 00-INDEX.md, and clears on transition out."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    t1_path = tasks_dir / "features" / "T001-deploy-pipeline.md"
    t1_path.write_text(
        "# T001 Deploy pipeline\n\n"
        "- id: T001\n"
        "- title: Deploy pipeline\n"
        "- category: features\n"
        "- priority: P2\n"
        "- priority-reason: core feature\n"
        "- next-up: no\n"
        "- state: in progress\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read this file\n\n"
        "## Goal\nDeploy pipeline.\n\n"
        "## Steps\n- [ ] Deploy step.\n\n"
        "## Verification\n- [ ] Verification step.\n",
        encoding="utf-8",
    )

    # 1. Transition to waiting with --waiting-on
    res = run_cli("transition", "T001", "waiting", "--waiting-on", "external:jenkins-build-42", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"transition failed: {res.stdout}\n{res.stderr}"

    content = t1_path.read_text(encoding="utf-8")
    assert "- state: waiting" in content
    assert "- waiting-on: external:jenkins-build-42" in content

    # 2. Sync index renders `waiting (external:jenkins-build-42)` in 00-INDEX.md
    res = run_cli("sync-index", "--apply", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"sync-index failed: {res.stdout}\n{res.stderr}"
    idx_content = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "waiting (external:jenkins-build-42)" in idx_content

    # 3. tasks list --json includes waiting_on
    res = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0, f"list failed: {res.stdout}\n{res.stderr}"
    payload = json.loads(res.stdout)
    assert payload["tree"]["T001"]["waiting_on"] == "external:jenkins-build-42"

    # 4. tasks show --json includes waiting_on
    res = run_cli("show", "T001", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0, f"show failed: {res.stdout}\n{res.stderr}"
    show_payload = json.loads(res.stdout)
    assert show_payload["task"]["waiting_on"] == "external:jenkins-build-42"

    # 5. Transition back to in progress clears waiting-on
    res = run_cli("transition", "T001", "in progress", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"transition to in progress failed: {res.stdout}\n{res.stderr}"

    content2 = t1_path.read_text(encoding="utf-8")
    assert "- state: in progress" in content2
    assert "waiting-on" not in content2

    # 6. Index after sync no longer has waiting-on
    res = run_cli("sync-index", "--apply", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"sync-index failed: {res.stdout}\n{res.stderr}"
    idx_content2 = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "waiting (external:jenkins-build-42)" not in idx_content2
    assert "in progress" in idx_content2


def test_t042_waiting_on_inline_plan_task_transition(tmp_path: pathlib.Path) -> None:
    """T042: tasks transition 01.1 'waiting on owner:release-signoff' on inline plan task normalizes to waiting and sets waiting_on."""
    tasks_dir = tmp_path / "tasks"
    init_dir = tasks_dir / "01-core-pipeline"
    init_dir.mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n\n## Initiatives\n\n| Priority | # | Initiative | Status | Depends on | Size |\n| --- | --- | --- | --- | --- | --- |\n", encoding="utf-8")

    plan_path = init_dir / "plan.md"
    plan_path.write_text(
        "# 01 Core Pipeline\n\n"
        "## Tasks\n\n"
        "### 01.1 - Release signoff\n\n"
        "- **Status:** `open`\n"
        "- **Goal:** Obtain owner signoff for release.\n"
        "- **Verification:** Owner confirmation.\n",
        encoding="utf-8",
    )

    # Transition with "waiting on owner:release-signoff"
    res = run_cli("transition", "01.1", "waiting on owner:release-signoff", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"transition failed: {res.stdout}\n{res.stderr}"

    tree = te.discover_task_tree(tasks_dir)
    assert tree["01.1"].canonical_state == "waiting"
    assert tree["01.1"].waiting_on == "owner:release-signoff"

    plan_text = plan_path.read_text(encoding="utf-8")
    assert "`waiting`" in plan_text
    assert "**Waiting-on:** owner:release-signoff" in plan_text

    # Update with set-waiting-on
    res = run_cli("set-waiting-on", "01.1", "session:worker-1", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"set-waiting-on failed: {res.stdout}\n{res.stderr}"

    tree = te.discover_task_tree(tasks_dir)
    assert tree["01.1"].waiting_on == "session:worker-1"

    # Transition back to in progress clears waiting-on
    res = run_cli("transition", "01.1", "in progress", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"transition back failed: {res.stdout}\n{res.stderr}"

    tree = te.discover_task_tree(tasks_dir)
    assert tree["01.1"].canonical_state == "in progress"
    assert tree["01.1"].waiting_on is None

    plan_text2 = plan_path.read_text(encoding="utf-8")
    assert "**Waiting-on:**" not in plan_text2


def test_t042_validate_warns_on_unqualified_waiting_task(tmp_path: pathlib.Path) -> None:
    """T042: tasks validate warns when waiting task has no waiting-on, decider, or conditions, and zero warnings once set."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    t1_path = tasks_dir / "features" / "T001-unqualified-waiting.md"
    t1_path.write_text(
        "# T001 Unqualified Waiting\n\n"
        "- id: T001\n"
        "- title: Unqualified Waiting\n"
        "- category: features\n"
        "- priority: P2\n"
        "- priority-reason: testing validation\n"
        "- next-up: no\n"
        "- state: waiting\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read this file\n\n"
        "## Goal\nTest waiting task warning.\n\n"
        "## Steps\n- [ ] Deploy the application.\n\n"
        "## Verification\n- [ ] Confirm curl localhost:8080 works.\n",
        encoding="utf-8",
    )

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert any("in waiting state has no waiting-on, decider, or conditions" in w for w in warnings)

    # Set waiting-on
    res = run_cli("set-waiting-on", "T001", "owner:release-signoff", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"set-waiting-on failed: {res.stdout}\n{res.stderr}"

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []
    assert warnings == []


def test_t042_questions_ask_blocks_sets_waiting_on(tmp_path: pathlib.Path) -> None:
    """T042: questions ask --blocks T001 sets waiting-on to question:Q### alongside decider."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    t1_path = tasks_dir / "features" / "T001-gated-task.md"
    t1_path.write_text(
        "# T001 Gated Task\n\n"
        "- id: T001\n"
        "- title: Gated Task\n"
        "- category: features\n"
        "- priority: P2\n"
        "- priority-reason: core feature\n"
        "- next-up: no\n"
        "- state: in progress\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read this file\n\n"
        "## Goal\nGated task.\n\n"
        "## Steps\n- [ ] Step 1.\n\n"
        "## Verification\n- [ ] Verify 1.\n",
        encoding="utf-8",
    )

    ok, q = te.ask_question(
        tasks_dir=tasks_dir,
        question="Should we gate T001?",
        context="Context for question",
        options=[("a", "Option A", None), ("b", "Option B", None)],
        blocks="T001",
    )
    assert ok is True
    qid = q["id"]

    emergent = te.discover_emergent_tasks(tasks_dir)
    t1 = next(t for t in emergent if t["id"] == "T001")
    assert t1["canonical_state"] == "waiting"
    assert t1["decider"] == qid
    assert t1["waiting_on"] == f"question:{qid}"

    content = t1_path.read_text(encoding="utf-8")
    assert f"- waiting-on: question:{qid}" in content


def test_tasks_next_id_empty_and_populated(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    bin_ai_orch = REPO_ROOT / "bin" / "ai-orch"

    # 1. Empty tasks tree: next_id defaults to T001, highest_id is None
    tasks_dir.mkdir(parents=True)
    res_empty = run_cli("next-id", "--tasks-dir", str(tasks_dir), "--json")
    assert res_empty.returncode == 0
    empty_data = json.loads(res_empty.stdout)
    assert empty_data["ok"] is True
    assert empty_data["highest_id"] is None
    assert empty_data["next_id"] == "T001"

    # 2. Add an active emergent task T010, microtask T025, and done task T048
    (tasks_dir / "features").mkdir(parents=True)
    _write_sample_task(tasks_dir / "features" / "T010-feature.md", task_id="T010")

    (tasks_dir / "micro").mkdir(parents=True)
    (tasks_dir / "micro" / "T025-small-fix.md").write_text("# T025 Small Fix\n\n- id: T025\n", encoding="utf-8")

    (tasks_dir / "done" / "maintenance").mkdir(parents=True)
    _write_sample_task(tasks_dir / "done" / "maintenance" / "T048-done-task.md", task_id="T048")

    # Run tasks_engine.py next-id
    res_pop = run_cli("next-id", "--tasks-dir", str(tasks_dir), "--json")
    assert res_pop.returncode == 0
    pop_data = json.loads(res_pop.stdout)
    assert pop_data["ok"] is True
    assert pop_data["highest_id"] == "T048"
    assert pop_data["next_id"] == "T049"

    # Run via bin/ai-orch tasks next-id
    res_bin = subprocess.run(
        [sys.executable, str(bin_ai_orch), "tasks", "next-id", "--tasks-dir", str(tasks_dir), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_bin.returncode == 0
    bin_data = json.loads(res_bin.stdout)
    assert bin_data["ok"] is True
    assert bin_data["highest_id"] == "T048"
    assert bin_data["next_id"] == "T049"

    # Human-readable output without --json
    res_human = run_cli("next-id", "--tasks-dir", str(tasks_dir))
    assert res_human.returncode == 0
    assert "T049" in res_human.stdout
    assert "T048" in res_human.stdout


def test_upgrade_detects_legacy_plans(tmp_path: pathlib.Path) -> None:
    repo_dir = tmp_path / "repo"
    tasks_dir = repo_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "AGENTS.md").write_text("# Old\n", encoding="utf-8")
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n\n<!-- ai-orch:generated:initiatives -->\n<!-- ai-orch:generated:initiatives:end -->\n", encoding="utf-8")

    # Sibling plans/ directory
    plans_dir = repo_dir / "plans"
    plans_dir.mkdir(parents=True)
    init1_dir = plans_dir / "01-bootstrap"
    init1_dir.mkdir(parents=True)
    (init1_dir / "plan.md").write_text("# 01 Bootstrap\n\n- **Status:** `open`\n", encoding="utf-8")
    (plans_dir / "02-database.md").write_text("# 02 Database\n", encoding="utf-8")
    (plans_dir / "legacy-spec.md").write_text("# Legacy Spec\n", encoding="utf-8")

    bin_ai_orch = REPO_ROOT / "bin" / "ai-orch"

    # 1. Preview mode (dry-run) via bin/ai-orch tasks upgrade
    res_dry = subprocess.run(
        [sys.executable, str(bin_ai_orch), "tasks", "upgrade", "--tasks-dir", str(tasks_dir), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_dry.returncode == 0
    dry_data = json.loads(res_dry.stdout)
    assert dry_data["ok"] is True
    assert "legacy_plans" in dry_data
    lp_dry = dry_data["legacy_plans"]
    assert len(lp_dry) == 3
    sources_dry = [item["source"] for item in lp_dry]
    assert any("01-bootstrap" in s for s in sources_dry)
    assert any("02-database.md" in s for s in sources_dry)
    assert any("legacy-spec.md" in s for s in sources_dry)

    # 2. Mutating upgrade (migrating non-conflicting NN-*/)
    res_upg = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--apply", "--expect-plan-hash", dry_data["plan_hash"], "--json")
    assert res_upg.returncode == 0
    upg_data = json.loads(res_upg.stdout)
    assert upg_data["ok"] is True
    assert upg_data["applied"] is True
    assert "legacy_plans" in upg_data
    assert (tasks_dir / "01-bootstrap" / "plan.md").is_file()

    # 3. Upgrade with --migrate-plans migrates specs as well
    res_mig_prev = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--migrate-plans", "--json")
    assert res_mig_prev.returncode == 0
    mig_prev_data = json.loads(res_mig_prev.stdout)
    assert mig_prev_data["ok"] is True
    assert mig_prev_data["applied"] is False

    res_mig = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--migrate-plans", "--apply", "--expect-plan-hash", mig_prev_data["plan_hash"], "--json")
    assert res_mig.returncode == 0
    mig_data = json.loads(res_mig.stdout)
    assert mig_data["ok"] is True
    assert mig_data["applied"] is True
    assert (tasks_dir / "specs" / "legacy-spec.md").is_file()


def test_workspace_wide_next_across_projects(tmp_path: pathlib.Path) -> None:
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()

    # 1. Root tasks/ (_workspace)
    root_tasks = ws_root / "tasks"
    root_tasks.mkdir()
    (root_tasks / "00-INDEX.md").write_text("# Workspace Index\n\n## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n", encoding="utf-8")
    _write_sample_task(
        root_tasks / "features" / "T001-ws-coordination.md",
        task_id="T001",
        title="Workspace coordination task",
        category="features",
        priority="P2",
        next_up="no",
        state="open",
    )

    # 2. Subproject proj-a/tasks/
    proj_a = ws_root / "proj-a"
    proj_a_tasks = proj_a / "tasks"
    proj_a_tasks.mkdir(parents=True)
    (proj_a_tasks / "00-INDEX.md").write_text("# Proj A Index\n\n## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n", encoding="utf-8")
    _write_sample_task(
        proj_a_tasks / "features" / "T010-auth-critical.md",
        task_id="T010",
        title="Auth critical fix",
        category="features",
        priority="P0",
        next_up="no",
        state="open",
    )

    # 3. Subproject proj-b/tasks/
    proj_b = ws_root / "proj-b"
    proj_b_tasks = proj_b / "tasks"
    proj_b_tasks.mkdir(parents=True)
    (proj_b_tasks / "00-INDEX.md").write_text("# Proj B Index\n\n## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n", encoding="utf-8")
    _write_sample_task(
        proj_b_tasks / "features" / "T020-data-migration.md",
        task_id="T020",
        title="Data migration",
        category="features",
        priority="P1",
        next_up="yes",
        state="open",
    )
    _write_sample_task(
        proj_b_tasks / "features" / "T021-already-done.md",
        task_id="T021",
        title="Already done task",
        category="features",
        priority="P1",
        next_up="no",
        state="done",
    )

    bin_ai_orch = REPO_ROOT / "bin" / "ai-orch"

    # Call via bin/ai-orch tasks next --workspace <ws_root> --json
    res = subprocess.run(
        [sys.executable, str(bin_ai_orch), "tasks", "next", "--workspace", str(ws_root), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert "tasks" in data
    tasks = data["tasks"]
    assert len(tasks) == 3

    # Sorted by priority (P0..P3), next_up == "yes" first, then qualified_id:
    # 1. proj-a/T010: P0, next_up=no
    assert tasks[0]["id"] == "T010"
    assert tasks[0]["project"] == "proj-a"
    assert tasks[0]["qualified_id"] == "proj-a/T010"
    assert tasks[0]["scope"] == "project"
    assert tasks[0]["priority"] == "P0"

    # 2. proj-b/T020: P1, next_up=yes
    assert tasks[1]["id"] == "T020"
    assert tasks[1]["project"] == "proj-b"
    assert tasks[1]["qualified_id"] == "proj-b/T020"
    assert tasks[1]["scope"] == "project"
    assert tasks[1]["priority"] == "P1"
    assert tasks[1]["next_up"] == "yes"

    # 3. _workspace/T001: P2, next_up=no
    assert tasks[2]["id"] == "T001"
    assert tasks[2]["project"] == "_workspace"
    assert tasks[2]["qualified_id"] == "_workspace/T001"
    assert tasks[2]["scope"] == "workspace"
    assert tasks[2]["priority"] == "P2"

    assert data["ready_queue"] == ["proj-a/T010", "proj-b/T020", "_workspace/T001"]

    # Also test bin/ai-orch workspace next --root <ws_root> --json
    res_ws_cmd = subprocess.run(
        [sys.executable, str(bin_ai_orch), "workspace", "next", "--root", str(ws_root), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_ws_cmd.returncode == 0
    ws_data = json.loads(res_ws_cmd.stdout)
    assert ws_data["ok"] is True
    assert [t["qualified_id"] for t in ws_data["tasks"]] == ["proj-a/T010", "proj-b/T020", "_workspace/T001"]

    # Also test --all-projects with cwd=ws_root
    res_all = subprocess.run(
        [sys.executable, str(bin_ai_orch), "tasks", "next", "--all-projects", "--json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(ws_root),
    )
    assert res_all.returncode == 0
    all_data = json.loads(res_all.stdout)
    assert len(all_data["tasks"]) == 3

    # Human-readable output check
    res_human = subprocess.run(
        [sys.executable, str(bin_ai_orch), "tasks", "next", "--workspace", str(ws_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_human.returncode == 0
    assert "proj-a/T010" in res_human.stdout
    assert "proj-b/T020" in res_human.stdout
    assert "_workspace/T001" in res_human.stdout


def test_workspace_wide_list_across_projects(tmp_path: pathlib.Path) -> None:
    ws_root = tmp_path / "workspace_list"
    ws_root.mkdir()

    # 1. Root tasks/ (_workspace)
    root_tasks = ws_root / "tasks"
    root_tasks.mkdir()
    (root_tasks / "00-INDEX.md").write_text("# Workspace Index\n\n## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n", encoding="utf-8")
    _write_sample_task(
        root_tasks / "features" / "T001-ws-coordination.md",
        task_id="T001",
        title="Workspace coordination task",
        category="features",
        priority="P2",
        next_up="no",
        state="open",
    )

    # 2. Subproject proj-a/tasks/
    proj_a = ws_root / "proj-a"
    proj_a_tasks = proj_a / "tasks"
    proj_a_tasks.mkdir(parents=True)
    (proj_a_tasks / "00-INDEX.md").write_text("# Proj A Index\n\n## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n", encoding="utf-8")
    _write_sample_task(
        proj_a_tasks / "features" / "T010-auth-critical.md",
        task_id="T010",
        title="Auth critical fix",
        category="features",
        priority="P0",
        next_up="no",
        state="open",
    )

    # 3. Subproject proj-b/tasks/
    proj_b = ws_root / "proj-b"
    proj_b_tasks = proj_b / "tasks"
    proj_b_tasks.mkdir(parents=True)
    (proj_b_tasks / "00-INDEX.md").write_text("# Proj B Index\n\n## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n", encoding="utf-8")
    _write_sample_task(
        proj_b_tasks / "features" / "T020-data-migration.md",
        task_id="T020",
        title="Data migration",
        category="features",
        priority="P1",
        next_up="yes",
        state="open",
    )
    _write_sample_task(
        proj_b_tasks / "features" / "T021-already-done.md",
        task_id="T021",
        title="Already done task",
        category="features",
        priority="P1",
        next_up="no",
        state="done",
    )

    bin_ai_orch = REPO_ROOT / "bin" / "ai-orch"

    # Call via bin/ai-orch tasks list --workspace <ws_root> --state open --json
    res = subprocess.run(
        [sys.executable, str(bin_ai_orch), "tasks", "list", "--workspace", str(ws_root), "--state", "open", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert "all_tasks" in data
    assert "tasks" in data
    tasks = data["tasks"]
    # Only open tasks (T010, T020, T001) should be returned; T021 is done!
    assert len(tasks) == 3
    qids = [t["qualified_id"] for t in tasks]
    assert "proj-a/T010" in qids
    assert "proj-b/T020" in qids
    assert "_workspace/T001" in qids
    assert not any("T021" in q for q in qids)

    # Check project and scope fields
    for t in tasks:
        assert "project" in t
        assert "qualified_id" in t
        assert "scope" in t
        if t["project"] == "_workspace":
            assert t["scope"] == "workspace"
        else:
            assert t["scope"] == "project"

    # Also test without --state open to see all tasks including done
    res_all = subprocess.run(
        [sys.executable, str(bin_ai_orch), "tasks", "list", "--workspace", str(ws_root), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_all.returncode == 0
    data_all = json.loads(res_all.stdout)
    assert len(data_all["tasks"]) == 4

    # Also test --active-only
    res_act = subprocess.run(
        [sys.executable, str(bin_ai_orch), "tasks", "list", "--workspace", str(ws_root), "--active-only", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_act.returncode == 0
    data_act = json.loads(res_act.stdout)
    assert len(data_act["tasks"]) == 3


def test_cross_workspace_and_cross_project_depends_on_setting_and_validate(tmp_path: pathlib.Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 1. Create task via tasks_new_from_note with cross-workspace and cross-project depends-on
    ok, res = te.tasks_new_from_note(
        tasks_dir=tasks_dir,
        from_note=None,
        category="features",
        title="Dependent task",
        depends_on="workspace:other-ws/T001, sibling-proj/T002",
        goal="Coordinate with other workspace and sibling project",
        priority_reason="Core cross-workspace feature",
    )
    assert ok is True
    t_id = res["id"]

    # Verify tasks validate passes with 0 errors
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []

    # 2. Test updating dependencies via set_deps
    res_set = te.set_deps(
        tasks_dir=tasks_dir,
        node_id=t_id,
        to_ids=["workspace:other-ws/T001", "sibling-proj/T002"],
    )
    assert res_set["ok"] is True
    assert "workspace:other-ws/T001" in res_set["depends_on"]
    assert "sibling-proj/T002" in res_set["depends_on"]

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []


def test_cross_workspace_external_dep_live_resolution_and_next_readiness(tmp_path: pathlib.Path):
    # Setup workspace topologies:
    # tmp_path/
    #   main-ws/
    #     tasks/
    #     sibling-proj/
    #       tasks/
    #   other-ws/
    #     tasks/
    main_ws = tmp_path / "main-ws"
    main_tasks = main_ws / "tasks"
    main_tasks.mkdir(parents=True)

    sibling_proj = main_ws / "sibling-proj"
    sibling_tasks = sibling_proj / "tasks"
    sibling_tasks.mkdir(parents=True)

    other_ws = tmp_path / "other-ws"
    other_tasks = other_ws / "tasks"
    other_tasks.mkdir(parents=True)

    # Create target task in other-ws: T001
    _write_sample_task(
        other_tasks / "features" / "T001-other.md",
        task_id="T001",
        title="External other task",
        category="features",
        state="open",
        short="Other task",
    )

    # Create target task in sibling-proj: T002
    _write_sample_task(
        sibling_tasks / "core" / "T002-sibling.md",
        task_id="T002",
        title="Sibling core task",
        category="core",
        state="open",
        short="Sibling task",
    )

    # Create dependent task in main-ws: T010
    _write_sample_task(
        main_tasks / "features" / "T010-dependent.md",
        task_id="T010",
        title="Main dependent task",
        category="features",
        state="open",
        depends_on="workspace:other-ws/T001, sibling-proj/T002",
    )

    # 1. Test resolve_external_task_ref for workspace:other-ws/T001
    res_other = te.resolve_external_task_ref("workspace:other-ws/T001", main_tasks)
    assert res_other["resolved"] is True
    assert res_other["ref"] == "workspace:other-ws/T001"
    assert res_other["state"] == "open"
    assert res_other["canonical_state"] == "open"
    assert res_other["is_done"] is False
    assert res_other["short_title"] == "Other task"

    # 2. Test resolve_external_task_ref for sibling-proj/T002
    res_sib = te.resolve_external_task_ref("sibling-proj/T002", main_tasks)
    assert res_sib["resolved"] is True
    assert res_sib["ref"] == "sibling-proj/T002"
    assert res_sib["state"] == "open"
    assert res_sib["canonical_state"] == "open"
    assert res_sib["is_done"] is False
    assert res_sib["short_title"] == "Sibling task"

    # 3. Test non-existent external workspace
    res_missing = te.resolve_external_task_ref("workspace:nonexistent-ws/T999", main_tasks)
    assert res_missing["resolved"] is False
    assert res_missing["is_done"] is False

    # 4. Check tasks show --json outputs external_dependencies
    args_show = argparse.Namespace(tasks_dir=str(main_tasks), task_id="T010", json=True)
    code = te.cmd_show(args_show)
    assert code == 0
    show_task = args_show._last_result["task"]
    assert "external_dependencies" in show_task
    ext_deps = show_task["external_dependencies"]
    assert len(ext_deps) == 2
    refs = [d["ref"] for d in ext_deps]
    assert "workspace:other-ws/T001" in refs
    assert "sibling-proj/T002" in refs

    # 5. Check tasks next readiness: both targets are open, so T010 must NOT be in ready_queue
    graph = te.compute_tasks_graph(main_tasks)
    assert "T010" not in graph["ready_queue"]

    # Transition other-ws/T001 to 'delivered'
    t001_file = other_tasks / "features" / "T001-other.md"
    content_001 = t001_file.read_text(encoding="utf-8")
    content_001 = re.sub(r"-\s+state:\s*open", "- state: delivered", content_001)
    t001_file.write_text(content_001, encoding="utf-8")

    # T010 should still be blocked because sibling-proj/T002 is still open
    graph2 = te.compute_tasks_graph(main_tasks)
    assert "T010" not in graph2["ready_queue"]

    # Transition sibling-proj/T002 to 'verified'
    t002_file = sibling_tasks / "core" / "T002-sibling.md"
    content_002 = t002_file.read_text(encoding="utf-8")
    content_002 = re.sub(r"-\s+state:\s*open", "- state: verified", content_002)
    t002_file.write_text(content_002, encoding="utf-8")

    # Now both targets are in delivered/verified -> T010 must be in ready_queue!
    graph3 = te.compute_tasks_graph(main_tasks)
    assert "T010" in graph3["ready_queue"]

    # Transition other-ws/T001 to 'done' -> T010 remains in ready_queue, is_done becomes True
    content_001 = re.sub(r"-\s+state:\s*delivered", "- state: done", content_001)
    t001_file.write_text(content_001, encoding="utf-8")

    res_other_done = te.resolve_external_task_ref("workspace:other-ws/T001", main_tasks)
    assert res_other_done["resolved"] is True
    assert res_other_done["canonical_state"] == "done"
    assert res_other_done["is_done"] is True

    graph4 = te.compute_tasks_graph(main_tasks)
    assert "T010" in graph4["ready_queue"]


def test_cross_workspace_executor_validate_and_show(tmp_path: pathlib.Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # Create task with executor: workspace:ai-coding-tools
    ok, res = te.tasks_new_from_note(
        tasks_dir=tasks_dir,
        from_note=None,
        category="features",
        title="Workspace delegated task",
        executor="workspace:ai-coding-tools",
        goal="Run in ai-coding-tools workspace",
        priority_reason="Delegated to external workspace",
    )
    assert ok is True
    tid = res["id"]

    # tasks validate passes with 0 errors
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []

    # tasks show --json outputs external_executor
    args_show = argparse.Namespace(tasks_dir=str(tasks_dir), task_id=tid, json=True)
    code = te.cmd_show(args_show)
    assert code == 0
    task_data = args_show._last_result["task"]
    assert task_data["executor"] == "workspace:ai-coding-tools"
    assert "external_executor" in task_data
    assert task_data["external_executor"] == {
        "kind": "workspace",
        "workspace": "ai-coding-tools",
    }

    # Test set-executor with session:<name>
    res_set = te.set_executor(tasks_dir, tid, "session:lead-session")
    assert res_set["ok"] is True
    assert res_set["executor"] == "session:lead-session"

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []

    args_show2 = argparse.Namespace(tasks_dir=str(tasks_dir), task_id=tid, json=True)
    assert te.cmd_show(args_show2) == 0
    task_data2 = args_show2._last_result["task"]
    assert task_data2["executor"] == "session:lead-session"
    assert task_data2["external_executor"] == {
        "kind": "session",
        "session": "lead-session",
    }


def test_t044_verify_by_transition_and_set(tmp_path: pathlib.Path) -> None:
    """T044: setting verify-by via tasks transition delivered --verify-by and tasks set-verify-by."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    t1_path = tasks_dir / "features" / "T001-deploy-pipeline.md"
    t1_path.write_text(
        "# T001 Deploy pipeline\n\n"
        "- id: T001\n"
        "- title: Deploy pipeline\n"
        "- category: features\n"
        "- priority: P2\n"
        "- priority-reason: core feature\n"
        "- next-up: no\n"
        "- state: in progress\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read this file\n\n"
        "## Goal\nDeploy pipeline.\n\n"
        "## Steps\n- [ ] Deploy step.\n\n"
        "## Verification\n- [ ] Verification step.\n",
        encoding="utf-8",
    )

    # 1. Transition to delivered with --verify-by
    res = run_cli("transition", "T001", "delivered", "--verify-by", "gcube_atlas", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"transition failed: {res.stdout}\n{res.stderr}"

    content = t1_path.read_text(encoding="utf-8")
    assert "- state: delivered" in content
    assert "- verify-by: gcube_atlas" in content
    assert "verification pending: run Verification checks (verify-by: gcube_atlas)" in content

    # 2. Sync index renders `delivered (verify-by: gcube_atlas)` in 00-INDEX.md
    res = run_cli("sync-index", "--apply", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"sync-index failed: {res.stdout}\n{res.stderr}"
    idx_content = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "delivered (verify-by: gcube_atlas)" in idx_content

    # 3. Update verify-by via set-verify-by with custom check
    res = run_cli("set-verify-by", "T001", "d4science-python-library", "--check", "run pytest -k lib", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"set-verify-by failed: {res.stdout}\n{res.stderr}"

    content2 = t1_path.read_text(encoding="utf-8")
    assert "- verify-by: d4science-python-library" in content2
    assert "verification pending: run pytest -k lib (verify-by: d4science-python-library)" in content2

    res = run_cli("sync-index", "--apply", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0
    idx_content2 = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "delivered (verify-by: d4science-python-library)" in idx_content2

    # 4. Update via request-verification alias
    res = run_cli("request-verification", "T001", "--by", "gcube_atlas", "--tasks-dir", str(tasks_dir))
    assert res.returncode == 0, f"request-verification failed: {res.stdout}\n{res.stderr}"
    content3 = t1_path.read_text(encoding="utf-8")
    assert "- verify-by: gcube_atlas" in content3

    # Validate passes with 0 errors
    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert errors == []


def test_t044_verification_queue_across_workspaces(tmp_path: pathlib.Path) -> None:
    """T044: verification-queue discovering delivered tasks across workspaces and clearing on verification."""
    ws1 = tmp_path / "ws1"
    ws1_tasks = ws1 / "tasks"
    (ws1_tasks / "features").mkdir(parents=True)
    (ws1_tasks / "00-INDEX.md").write_text(
        "# Task Index\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    (ws1_tasks / "features" / "T001-sample.md").write_text(
        "# T001 Sample task\n\n"
        "- id: T001\n"
        "- title: Sample task\n"
        "- category: features\n"
        "- priority: P1\n"
        "- priority-reason: high priority\n"
        "- next-up: no\n"
        "- state: delivered\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read this\n"
        "- verify-by: gcube_atlas\n\n"
        "verification pending: run Verification checks (verify-by: gcube_atlas)\n\n"
        "## Goal\nSample.\n\n"
        "## Steps\n- [ ] Step.\n\n"
        "## Verification\n- [ ] Check.\n",
        encoding="utf-8",
    )

    ws2 = tmp_path / "ws2"
    ws2_tasks = ws2 / "tasks"
    (ws2_tasks / "features").mkdir(parents=True)
    (ws2_tasks / "00-INDEX.md").write_text(
        "# Task Index\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    (ws2_tasks / "features" / "T002-other.md").write_text(
        "# T002 Other task\n\n"
        "- id: T002\n"
        "- title: Other task\n"
        "- category: features\n"
        "- priority: P2\n"
        "- priority-reason: normal priority\n"
        "- next-up: no\n"
        "- state: delivered\n"
        "- executor: claude\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read this\n"
        "- verify-by: other_workspace\n\n"
        "verification pending: run checks (verify-by: other_workspace)\n\n"
        "## Goal\nOther.\n\n"
        "## Steps\n- [ ] Step.\n\n"
        "## Verification\n- [ ] Check.\n",
        encoding="utf-8",
    )

    # 1. Run verification-queue from ws2 looking for gcube_atlas (discovers sibling ws1)
    res = run_cli("verification-queue", "--for", "gcube_atlas", "--tasks-dir", str(ws2_tasks), "--json")
    assert res.returncode == 0, f"verification-queue failed: {res.stdout}\n{res.stderr}"
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["for"] == "gcube_atlas"
    assert payload["count"] == 1
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["id"] == "T001"
    assert item["workspace"] == "ws1"
    assert item["state"] == "delivered"
    assert item["verify_by"] == "gcube_atlas"

    # Also test with workspace:gcube_atlas target filter
    res_ws = run_cli("verification-queue", "--for", "workspace:gcube_atlas", "--tasks-dir", str(ws2_tasks), "--json")
    assert res_ws.returncode == 0
    payload_ws = json.loads(res_ws.stdout)
    assert payload_ws["count"] == 1
    assert payload_ws["items"][0]["id"] == "T001"

    # Also test via bin/ai-orch CLI
    res_bin = subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "ai-orch"), "tasks", "verification-queue", "--for", "gcube_atlas", "--tasks-dir", str(ws2_tasks), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_bin.returncode == 0, f"ai-orch failed: {res_bin.stderr}"
    payload_bin = json.loads(res_bin.stdout)
    assert payload_bin["count"] == 1
    assert payload_bin["items"][0]["id"] == "T001"

    # 2. Transition T001 to verified
    res_tr = run_cli("transition", "T001", "verified", "--verifier", "gcube_atlas", "--reason", "OK: verified in atlas", "--tasks-dir", str(ws1_tasks))
    assert res_tr.returncode == 0, f"transition to verified failed: {res_tr.stdout}\n{res_tr.stderr}"

    t1_content = (ws1_tasks / "features" / "T001-sample.md").read_text(encoding="utf-8")
    assert "- state: verified" in t1_content
    assert "verification pending:" not in t1_content

    # 3. verification-queue --for gcube_atlas is now empty (count == 0)
    res_empty = run_cli("verification-queue", "--for", "gcube_atlas", "--tasks-dir", str(ws2_tasks), "--json")
    assert res_empty.returncode == 0
    payload_empty = json.loads(res_empty.stdout)
    assert payload_empty["ok"] is True
    assert payload_empty["count"] == 0
    assert payload_empty["items"] == []


# ---------------------------------------------------------------------------
# Paused task behaviour tests: next-up exclusion, container hierarchy, and transitions
# ---------------------------------------------------------------------------

def test_paused_emergent_task_with_next_up_excluded_from_next_up(tmp_path: pathlib.Path) -> None:
    """1. A paused emergent task with next-up yes is not in next-up."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    _write_sample_task(
        tasks_dir / "features" / "T001-paused.md",
        task_id="T001",
        title="Paused Task",
        category="features",
        state="paused",
        next_up="yes",
    )

    # Deterministic index sync
    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync.returncode == 0, f"sync-index failed: {res_sync.stderr}"
    index_content = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")

    # T001 must not appear in the generated Next up table
    next_up_match = re.search(
        r"<!-- ai-orch:generated next-up -->(.*?)<!-- /ai-orch:generated next-up -->",
        index_content,
        re.DOTALL,
    )
    assert next_up_match is not None
    assert "T001" not in next_up_match.group(1)

    # tasks next CLI also excludes paused tasks from ready queue
    res_next = run_cli("next", "--tasks-dir", str(tasks_dir), "--json")
    assert res_next.returncode == 0
    data_next = json.loads(res_next.stdout)
    assert "T001" not in data_next.get("ready_queue", [])


def test_plan_task_under_paused_parent_excluded_from_open_leaves_columns_and_counts(tmp_path: pathlib.Path) -> None:
    """2. A plan task under a paused parent is excluded from open leaves, both in columns and in counts."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # Initiative 01 is explicitly paused at initiative level
    init01_dir = tasks_dir / "01-paused-init"
    init01_dir.mkdir(parents=True)
    (init01_dir / "plan.md").write_text(
        "# 01 - Paused Initiative\n\n"
        "- **Status:** `paused`\n\n"
        "## Tasks\n\n"
        "### 01.1 - Leaf task under paused initiative\n\n"
        "- **Status:** `open` · **Priority:** P1\n"
        "- **Goal:** Sub-goal\n",
        encoding="utf-8",
    )

    # Initiative 02 is active, but contains an expanded container task 02.1 that is paused, plus active sibling 02.2
    init02_dir = tasks_dir / "02-active-init"
    init02_dir.mkdir(parents=True)
    (init02_dir / "plan.md").write_text(
        "# 02 - Active Initiative\n\n"
        "## Tasks\n\n"
        "### 02.1 - Paused container task\n\n"
        "- **Status:** `paused`\n"
        "- **Expanded:** [02.1-container/](02.1-container/README.md)\n\n"
        "### 02.2 - Active sibling task\n\n"
        "- **Status:** `open` · **Priority:** P1\n"
        "- **Goal:** Active goal\n",
        encoding="utf-8",
    )

    c_dir = init02_dir / "02.1-container"
    c_dir.mkdir(parents=True)
    (c_dir / "README.md").write_text(
        "# 02.1 - Paused container task\n\n"
        "- **Status:** `paused`\n\n"
        "## Subtasks\n\n"
        "### 02.1.1 - Leaf under paused container\n\n"
        "- **Status:** `open`\n"
        "- **Goal:** Nested goal\n",
        encoding="utf-8",
    )

    res = run_cli("graph", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0, f"graph failed: {res.stderr}"
    data = json.loads(res.stdout)
    assert data["ok"] is True

    columns = data["columns"]
    totals = data["totals"]

    # Leaf tasks under paused ancestors (01.1 under 01, and 02.1.1 under 02.1) are excluded from columns
    assert "01.1" not in columns
    assert "02.1.1" not in columns
    # Active unpaused sibling 02.2 is included
    assert "02.2" in columns

    # Total open leaves and group counts exclude paused leaves
    assert totals["total_open"] == 1
    assert totals["by_group"]["01"]["total_open"] == 0
    assert totals["by_group"]["02"]["total_open"] == 1

    # Ready queue also excludes tasks under paused parents
    assert data["ready_queue"] == ["02.2"]


def test_delivered_to_paused_and_paused_to_in_progress_transitions(tmp_path: pathlib.Path) -> None:
    """3. delivered -> paused is allowed, and paused -> in progress still works."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-delivered.md"
    _write_sample_task(
        t_path,
        task_id="T001",
        title="Delivered Task",
        category="features",
        state="delivered",
    )

    # 1. delivered -> paused transition
    res_pause = run_cli(
        "transition", "T001", "paused",
        "--actor", "owner",
        "--reason", "putting delivery on hold",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_pause.returncode == 0, f"transition delivered->paused failed: {res_pause.stderr}"
    payload_pause = json.loads(res_pause.stdout)
    assert payload_pause["ok"] is True
    assert payload_pause["new_state"] == "paused"
    assert "- state: paused" in t_path.read_text(encoding="utf-8")

    # 2. paused -> in progress transition
    res_resume = run_cli(
        "transition", "T001", "in progress",
        "--actor", "kilo",
        "--reason", "resuming implementation",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_resume.returncode == 0, f"transition paused->in progress failed: {res_resume.stderr}"
    payload_resume = json.loads(res_resume.stdout)
    assert payload_resume["ok"] is True
    assert payload_resume["new_state"] == "in progress"
    assert "- state: in progress" in t_path.read_text(encoding="utf-8")


def test_unpaused_sibling_stays_in_next_up_alongside_paused_task(tmp_path: pathlib.Path) -> None:
    """4. An unpaused sibling stays in next-up alongside a paused task."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    _write_sample_task(
        tasks_dir / "features" / "T001-paused.md",
        task_id="T001",
        title="Paused sibling",
        category="features",
        state="paused",
        next_up="yes",
        priority="P1",
    )
    _write_sample_task(
        tasks_dir / "features" / "T002-active.md",
        task_id="T002",
        title="Active sibling",
        category="features",
        state="open",
        next_up="yes",
        priority="P1",
    )

    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync.returncode == 0, f"sync-index failed: {res_sync.stderr}"
    index_content = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")

    # In Next up section, T002 must be present and T001 must not be present
    m = re.search(
        r"<!-- ai-orch:generated next-up -->(.*?)<!-- /ai-orch:generated next-up -->",
        index_content,
        re.DOTALL,
    )
    assert m is not None
    next_up_table = m.group(1)
    assert "T002" in next_up_table
    assert "T001" not in next_up_table

    # In tasks next CLI, T002 is in ready_queue and T001 is not
    res_next = run_cli("next", "--tasks-dir", str(tasks_dir), "--json")
    assert res_next.returncode == 0
    data_next = json.loads(res_next.stdout)
    assert "T002" in data_next["ready_queue"]
    assert "T001" not in data_next["ready_queue"]


def test_reopen_single_file_emergent_task_in_done(tmp_path: pathlib.Path) -> None:
    """T051: Reopening a single-file emergent task in done/ moves file back to category, sets open, updates index, exits 0."""
    tasks_dir = tmp_path / "tasks"
    done_features = tasks_dir / "done" / "features"
    done_features.mkdir(parents=True)
    task_file = done_features / "T001-implement-scraper.md"
    _write_sample_task(
        task_file,
        task_id="T001",
        title="Implement scraper",
        category="features",
        state="done",
    )
    index_file = tasks_dir / "00-INDEX.md"
    index_file.write_text(
        "# Task Index\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync.returncode == 0, f"sync-index failed: {res_sync.stderr}"
    assert "done/features/T001-implement-scraper.md" in index_file.read_text(encoding="utf-8")

    # 1. Dry run returns plan hash
    res_dry = run_cli("reopen", "T001", "--reason", "Found regression", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0, f"reopen dry-run failed: {res_dry.stderr}"
    data_dry = json.loads(res_dry.stdout)
    assert data_dry["ok"] is True
    plan_hash = data_dry["plan_hash"]

    # 2. Apply reopen
    res_reopen = run_cli("reopen", "T001", "--reason", "Found regression", "--expect-plan-hash", plan_hash, "--tasks-dir", str(tasks_dir))
    assert res_reopen.returncode == 0, f"reopen failed: {res_reopen.stderr}"

    # 3. Assertions
    assert not task_file.exists()
    restored_file = tasks_dir / "features" / "T001-implement-scraper.md"
    assert restored_file.is_file()
    assert "- state: open" in restored_file.read_text(encoding="utf-8")

    index_after = index_file.read_text(encoding="utf-8")
    assert "(features/T001-implement-scraper.md)" in index_after
    assert "(done/features/T001-implement-scraper.md)" not in index_after

    res_check = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--check")
    assert res_check.returncode == 0, f"sync-index --check failed: {res_check.stderr}\n{res_check.stdout}"


def test_reopen_folder_emergent_task_in_done(tmp_path: pathlib.Path) -> None:
    """T051: Reopening a folder emergent task in done/ moves folder back to category, sets open, updates index, exits 0."""
    tasks_dir = tmp_path / "tasks"
    done_feat = tasks_dir / "done" / "features" / "T002-payment-gateway"
    done_feat.mkdir(parents=True)
    readme_file = done_feat / "README.md"
    _write_sample_task(
        readme_file,
        task_id="T002",
        title="Payment Gateway",
        category="features",
        state="done",
    )
    context_file = done_feat / "CONTEXT.md"
    context_file.write_text("# Context\n\nStripe details.\n", encoding="utf-8")

    index_file = tasks_dir / "00-INDEX.md"
    index_file.write_text(
        "# Task Index\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync.returncode == 0, f"sync-index failed: {res_sync.stderr}"
    assert "done/features/T002-payment-gateway/README.md" in index_file.read_text(encoding="utf-8")

    # 1. Dry run returns plan hash
    res_dry = run_cli("reopen", "T002", "--reason", "Refactoring API", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0, f"reopen dry-run failed: {res_dry.stderr}"
    data_dry = json.loads(res_dry.stdout)
    assert data_dry["ok"] is True
    plan_hash = data_dry["plan_hash"]

    # 2. Apply reopen
    res_reopen = run_cli("reopen", "T002", "--reason", "Refactoring API", "--expect-plan-hash", plan_hash, "--tasks-dir", str(tasks_dir))
    assert res_reopen.returncode == 0, f"reopen failed: {res_reopen.stderr}"

    # 3. Assertions
    assert not done_feat.exists()
    restored_folder = tasks_dir / "features" / "T002-payment-gateway"
    assert restored_folder.is_dir()
    restored_readme = restored_folder / "README.md"
    assert restored_readme.is_file()
    assert "- state: open" in restored_readme.read_text(encoding="utf-8")
    assert (restored_folder / "CONTEXT.md").is_file()

    index_after = index_file.read_text(encoding="utf-8")
    assert "(features/T002-payment-gateway/README.md)" in index_after
    assert "(done/features/T002-payment-gateway/README.md)" not in index_after

    res_check = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--check")
    assert res_check.returncode == 0, f"sync-index --check failed: {res_check.stderr}\n{res_check.stdout}"


def test_reopen_emergent_task_dry_run_prints_plan_hash_and_writes_nothing(tmp_path: pathlib.Path) -> None:
    """T051: Dry run prints a plan hash and writes nothing."""
    tasks_dir = tmp_path / "tasks"
    done_features = tasks_dir / "done" / "features"
    done_features.mkdir(parents=True)
    task_file = done_features / "T003-notification-service.md"
    _write_sample_task(
        task_file,
        task_id="T003",
        title="Notification Service",
        category="features",
        state="done",
    )
    task_content_before = task_file.read_text(encoding="utf-8")

    index_file = tasks_dir / "00-INDEX.md"
    index_file.write_text(
        "# Task Index\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )
    run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    index_content_before = index_file.read_text(encoding="utf-8")

    # 1. Dry run with --json prints plan hash in json
    res_dry_json = run_cli("reopen", "T003", "--reason", "Recheck", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry_json.returncode == 0
    data_json = json.loads(res_dry_json.stdout)
    assert data_json["ok"] is True
    assert data_json["dry_run"] is True
    plan_hash = data_json["plan_hash"]
    assert plan_hash and len(plan_hash) == 64

    # 2. Dry run without --json prints plan hash in text output
    res_dry_text = run_cli("reopen", "T003", "--reason", "Recheck", "--dry-run", "--tasks-dir", str(tasks_dir))
    assert res_dry_text.returncode == 0
    assert plan_hash in res_dry_text.stdout

    # 3. Verify nothing written
    assert task_file.is_file()
    assert not (tasks_dir / "features" / "T003-notification-service.md").exists()
    assert task_file.read_text(encoding="utf-8") == task_content_before
    assert index_file.read_text(encoding="utf-8") == index_content_before


# ===========================================================================
# T050 Non-Destructive Upgrade and Sync-Index; Per-Project Extension Fields
# ===========================================================================


def test_t050_agents_md_project_rules_survive_upgrade_and_idempotent(tmp_path: pathlib.Path) -> None:
    """T050: An existing tasks/AGENTS.md with project rules survives upgrade byte-for-byte outside markers, and re-running upgrade is idempotent."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    custom_rules = (
        "# tasks/ - convention for this project\n\n"
        "## Priority criteria\n\n"
        "- P0: security exposure\n"
        "- P1: prod migration\n\n"
        "## Project-specific rules\n\n"
        "- **Categories**: `audit-auth`, `porting-lr74`.\n"
        "- **Redmine**: written in Italian.\n"
    )
    agents_path = tasks_dir / "AGENTS.md"
    agents_path.write_text(custom_rules, encoding="utf-8")
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # 1. Dry-run preview prints plan and writes nothing
    res_dry = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--dry-run", "--json")
    assert res_dry.returncode == 0
    dry_payload = json.loads(res_dry.stdout)
    assert dry_payload["ok"] is True
    assert dry_payload["plan_hash"]
    assert agents_path.read_text(encoding="utf-8") == custom_rules

    # 2. Apply with --expect-hash
    res_upg = run_cli(
        "upgrade",
        "--tasks-dir",
        str(tasks_dir),
        "--apply",
        "--expect-hash",
        dry_payload["plan_hash"],
        "--json",
    )
    assert res_upg.returncode == 0
    upg_payload = json.loads(res_upg.stdout)
    assert upg_payload["ok"] is True

    upgraded_text = agents_path.read_text(encoding="utf-8")
    assert upgraded_text.startswith(custom_rules)
    assert "<!-- ai-orch:managed begin -->" in upgraded_text
    assert "<!-- ai-orch:managed end -->" in upgraded_text
    assert "task-pipeline" in upgraded_text

    # 3. Re-running upgrade is idempotent (no files updated, bytes identical)
    res_upg2 = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_upg2.returncode == 0
    upg2_payload = json.loads(res_upg2.stdout)
    assert upg2_payload["ok"] is True
    assert upg2_payload["upgraded_files"] == []
    assert agents_path.read_text(encoding="utf-8") == upgraded_text

    # 4. Modifying inside markers and re-running refreshes only the managed block
    tampered = upgraded_text.replace("task-pipeline", "stale-skill-name")
    agents_path.write_text(tampered, encoding="utf-8")
    res_prev3 = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_prev3.returncode == 0
    prev3_data = json.loads(res_prev3.stdout)
    assert prev3_data["ok"] is True
    assert prev3_data["applied"] is False
    res_upg3 = run_cli(
        "upgrade",
        "--tasks-dir",
        str(tasks_dir),
        "--apply",
        "--expect-plan-hash",
        prev3_data["plan_hash"],
        "--json",
    )
    assert res_upg3.returncode == 0
    assert agents_path.read_text(encoding="utf-8") == upgraded_text


def test_t050_sync_index_preserves_owner_column_next_up_order_and_id_format(tmp_path: pathlib.Path) -> None:
    """T050: Extra columns (e.g. Owner), Next up order (without --reorder), and bare Id format survive sync-index."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "audit-auth").mkdir(parents=True)

    _write_sample_task(
        tasks_dir / "audit-auth" / "T119-first.md",
        task_id="T119",
        title="Task 119",
        category="audit-auth",
        priority="P0",
        next_up="yes",
        state="in progress",
    )
    _write_sample_task(
        tasks_dir / "audit-auth" / "T037-second.md",
        task_id="T037",
        title="Task 037",
        category="audit-auth",
        priority="P0",
        next_up="yes",
        state="open",
    )
    _write_sample_task(
        tasks_dir / "audit-auth" / "T120-new.md",
        task_id="T120",
        title="Task 120",
        category="audit-auth",
        priority="P1",
        next_up="no",
        state="open",
    )

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
| T119 | P0 | [Task 119](audit-auth/T119-first.md) | kilo | `Read tasks/audit-auth/T119-first.md and execute.` |
| T037 | P0 | [Task 037](audit-auth/T037-second.md) | kilo | `Read tasks/audit-auth/T037-second.md and execute.` |
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
### audit-auth

Auth audit. Owner session: unassigned ([README](audit-auth/README.md)).

| Id | Priority | Task | State | Executor | Depends on | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| T119 | P0 | [Task 119](audit-auth/T119-first.md) | open | kilo | - | Alfredo |
| T037 | P0 | [Task 037](audit-auth/T037-second.md) | open | kilo | - | Alfredo + NetFarm |
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| - | None. | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )

    # 1. Sync without --reorder
    res = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res.returncode == 0
    synced = index_path.read_text(encoding="utf-8")

    # Owner column header and values preserved; new row T120 gets empty Owner cell
    assert "| Id | Priority | Task | State | Executor | Depends on | Owner |" in synced
    assert "| T119 | P0 | [Task 119](audit-auth/T119-first.md) | in progress | kilo | - | Alfredo |" in synced
    assert "| T037 | P0 | [Task 037](audit-auth/T037-second.md) | open | kilo | - | Alfredo + NetFarm |" in synced
    assert "| T120 | P1 | [Task 120](audit-auth/T120-new.md) | open | kilo | - |  |" in synced

    # Next up order preserved: T119 appears before T037 even though T037 < T119 naturally
    next_sec = synced.split("## Tasks by category")[0]
    assert next_sec.index("| T119 |") < next_sec.index("| T037 |")

    # 2. Sync with --reorder sorts T037 before T119
    res_reord = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--reorder", "--apply", "--json")
    assert res_reord.returncode == 0
    synced_reord = index_path.read_text(encoding="utf-8")
    next_sec_reord = synced_reord.split("## Tasks by category")[0]
    assert next_sec_reord.index("| T037 |") < next_sec_reord.index("| T119 |")


def test_t050_companion_file_is_not_a_task_row(tmp_path: pathlib.Path) -> None:
    """T050: Companion files matching T###-*.md without task headers (e.g. T101-answers.md) are ignored."""
    tasks_dir = tmp_path / "tasks"
    cat_dir = tasks_dir / "audit-auth"
    cat_dir.mkdir(parents=True)

    _write_sample_task(
        cat_dir / "T101-decisions.md",
        task_id="T101",
        title="Decisions from triage",
        category="audit-auth",
        priority="P1",
        state="open",
    )
    # Companion file without task header lines
    (cat_dir / "T101-answers.md").write_text(
        "# T101 – Risposte alle decisioni del triage\n\nCompila direttamente qui:\n\n## 1. Infrastruttura\n- [ ] sì\n",
        encoding="utf-8",
    )

    emergent = te.discover_emergent_tasks(tasks_dir)
    assert [t["id"] for t in emergent] == ["T101"]

    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0, res_val.stdout
    assert json.loads(res_val.stdout)["ok"] is True

    rendered = te.render_synced_index(tasks_dir, "", adopt=True)
    assert "T101-answers.md" not in rendered
    assert "T101-decisions.md" in rendered


def test_t050_extension_fields_per_project_and_upgrade_exit_code(tmp_path: pathlib.Path) -> None:
    """T050: 'area' is accepted when declared in orchestration.toml or tasks/AGENTS.md and rejected when not; upgrade exits 0."""
    repo_dir = tmp_path / "project"
    tasks_dir = repo_dir / "tasks"
    cat_dir = tasks_dir / "audit-auth"
    cat_dir.mkdir(parents=True)

    task_file = cat_dir / "T001-auth.md"
    task_file.write_text(
        "# T001 Auth check\n\n"
        "- id: T001\n"
        "- title: Auth check\n"
        "- category: audit-auth\n"
        "- priority: P1\n"
        "- priority-reason: Needed for audit\n"
        "- next-up: no\n"
        "- state: open\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read tasks/audit-auth/T001-auth.md and execute.\n"
        "- area: security audit\n\n"
        "## Goal\n\nCheck auth.\n\n"
        "## Steps\n\n- [ ] Run check.\n\n"
        "## Verification\n\n- Check passes.\n",
        encoding="utf-8",
    )

    # 1. Without declaration: validate rejects 'area'
    res_undeclared = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_undeclared.returncode == 1
    err_undeclared = "\n".join(json.loads(res_undeclared.stdout)["errors"])
    assert "unknown header field(s): area" in err_undeclared

    # 2. Even when validate has errors, upgrade exits 0 and surfaces them as warnings
    res_upg = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_upg.returncode == 0
    upg_data = json.loads(res_upg.stdout)
    assert upg_data["ok"] is True

    # 3. Declare [tasks] extension_fields = ["area"] in orchestration.toml -> validate accepts 'area'
    (repo_dir / "orchestration.toml").write_text(
        '[tasks]\nextension_fields = ["area"]\n',
        encoding="utf-8",
    )
    res_declared = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_declared.returncode == 0, res_declared.stdout
    assert json.loads(res_declared.stdout)["ok"] is True

    # Undeclared field ' bogus ' is still rejected
    task_file.write_text(
        task_file.read_text(encoding="utf-8").replace("- area: security audit\n", "- area: security audit\n- bogus: nope\n"),
        encoding="utf-8",
    )
    res_bogus = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_bogus.returncode == 1
    assert "unknown header field(s): bogus" in "\n".join(json.loads(res_bogus.stdout)["errors"])

    # Restore valid task and test declaration via tasks/AGENTS.md fenced block (without orchestration.toml)
    (repo_dir / "orchestration.toml").unlink()
    task_file.write_text(
        task_file.read_text(encoding="utf-8").replace("- bogus: nope\n", ""),
        encoding="utf-8",
    )
    (tasks_dir / "AGENTS.md").write_text(
        "# Project tasks rules\n\n```toml\n[tasks]\nextension_fields = [\"area\"]\n```\n",
        encoding="utf-8",
    )
    res_agents_decl = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_agents_decl.returncode == 0, res_agents_decl.stdout
    assert json.loads(res_agents_decl.stdout)["ok"] is True


def test_t050_extension_fields_prose_declarations(tmp_path: pathlib.Path) -> None:
    """T050 bounce fix 1: Prose declarations of extra header fields in tasks/AGENTS.md are recognised."""
    tasks_dir = tmp_path / "tasks"
    cat_dir = tasks_dir / "audit-auth"
    cat_dir.mkdir(parents=True)

    # Managed block documents prose form
    assert "Extra header fields:" in te.MANAGED_TASKS_AGENTS_BLOCK

    prose_cases = [
        ("**Extra header fields: `area`** (free-text topic label), placed right after `handoff`.", ("area",)),
        ("Extra header fields: `area`", ("area",)),
        ("- Extra header fields: `area`, `subdomain` and `component`", ("area", "subdomain", "component")),
        ("* **Extra header fields**: `area` and `topic` (free-text)", ("area", "topic")),
    ]
    for prose_line, expected in prose_cases:
        (tasks_dir / "AGENTS.md").write_text(f"# Project rules\n\n{prose_line}\n", encoding="utf-8")
        assert te.get_project_extension_fields(tasks_dir) == expected

    # Validate passes with porting_liferay's exact prose line
    (tasks_dir / "AGENTS.md").write_text(
        "# Rules\n\n**Extra header fields: `area`** (free-text topic label), placed right after `handoff`.\n",
        encoding="utf-8",
    )
    (cat_dir / "T038-audit.md").write_text(
        "# T038 Audit low-severity code backlog\n\n"
        "- id: T038\n"
        "- title: Audit low-severity code backlog\n"
        "- category: audit-auth\n"
        "- priority: P2\n"
        "- priority-reason: Low-severity backlog\n"
        "- next-up: no\n"
        "- state: open\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: Alfredo\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read tasks/audit-auth/T038-audit.md and execute.\n"
        "- area: security audit\n\n"
        "## Goal\n\nFix items.\n\n"
        "## Steps\n\n- [ ] Fix.\n\n"
        "## Verification\n\n- Compile passes.\n",
        encoding="utf-8",
    )
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0, res_val.stdout
    assert json.loads(res_val.stdout)["ok"] is True


def test_t050_no_decisions_row_for_decider_only_blocked_task(tmp_path: pathlib.Path) -> None:
    """T050 bounce fix 2: A blocked/waiting task with `decider: Alfredo` and no question gets no Decisions row."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "audit-auth").mkdir(parents=True)

    # T038: blocked, decider: Alfredo, no question anywhere -> must NOT get a Decisions row
    _write_sample_task(
        tasks_dir / "audit-auth" / "T038-audit-low-severity-batch.md",
        task_id="T038",
        title="Audit low-severity code backlog (Kilo batch)",
        category="audit-auth",
        priority="P2",
        state="blocked",
        depends_on="T001",
        decider="Alfredo",
    )
    # T039: waiting, explicit question in decider (`Alfredo: Should we enable strict mode?`) -> gets a row
    _write_sample_task(
        tasks_dir / "audit-auth" / "T039-strict-mode.md",
        task_id="T039",
        title="Strict mode check",
        category="audit-auth",
        priority="P1",
        state="waiting",
        decider="Alfredo: Should we enable strict mode?",
    )
    # T040: blocked, decider: Alfredo, explicit Question in body -> gets a row
    t040_path = tasks_dir / "audit-auth" / "T040-body-question.md"
    _write_sample_task(
        t040_path,
        task_id="T040",
        title="Body question task",
        category="audit-auth",
        priority="P2",
        state="blocked",
        decider="Alfredo",
    )
    t040_path.write_text(
        t040_path.read_text(encoding="utf-8") + "\n## Question\n\nWhich certificate chain should we trust?\n",
        encoding="utf-8",
    )

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        "# Task Index\n\n"
        "## Next up\n\n"
        "| Id | Priority | Task | Executor | Handoff |\n"
        "| --- | --- | --- | --- | --- |\n\n"
        "## Tasks by category\n\n"
        "### audit-auth\n\n"
        "Auth.\n\n"
        "| Id | Priority | Task | State | Executor | Depends on |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| T038 | P2 | [Audit low-severity code backlog (Kilo batch)](audit-auth/T038-audit-low-severity-batch.md) | open | kilo | - |\n\n"
        "## Decisions waiting\n\n"
        "| Task | Priority | Question (exact) | Decider | Blocks |\n"
        "| --- | --- | --- | --- | --- |\n\n"
        "## Done\n\n"
        "| Id | Task | Result | Closed |\n"
        "| --- | --- | --- | --- |\n",
        encoding="utf-8",
    )

    rendered = te.render_synced_index(tasks_dir, index_path.read_text(encoding="utf-8"), adopt=True)
    dec_sec = rendered.split("## Decisions waiting")[1].split("## Done")[0]
    assert "T038" not in dec_sec
    assert "| Alfredo | Alfredo |" not in dec_sec
    assert "| T039 | P1 | Should we enable strict mode? | Alfredo | - |" in dec_sec
    assert "| T040 | P2 | Which certificate chain should we trust? | Alfredo | - |" in dec_sec


def test_t050_short_title_in_category_rows(tmp_path: pathlib.Path) -> None:
    """T050 KO3: Keep each table's Id-cell format; in bare-ID tables put `short` (or hand-curated label) into Task link text; in `T### (short)` tables keep Id `T### (short)` and full title in Task link text."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "social-sg4").mkdir(parents=True)

    # T154 has explicit `- short: client/model compatibility check`
    t154_path = tasks_dir / "social-sg4" / "T154-compatibility.md"
    _write_sample_task(
        t154_path,
        task_id="T154",
        title="Compatibility of social-service-client 3.1.0 and social-service-model 2.0.2 with the social WS",
        category="social-sg4",
        priority="P0",
        next_up="yes",
        state="delivered",
        short="client/model compatibility check",
    )

    # T155 has no `- short:` header in file, but hand-curated short label in existing category table
    _write_sample_task(
        tasks_dir / "social-sg4" / "T155-roadmap.md",
        task_id="T155",
        title="Roadmap step 1: dockerized environment with social-service-sg4 and Liferay",
        category="social-sg4",
        priority="P0",
        next_up="no",
        state="in progress",
    )

    # T037 has no `- short:` header and uses full title in bare-ID index -> stays bare `T037` with full title
    _write_sample_task(
        tasks_dir / "social-sg4" / "T037-plain.md",
        task_id="T037",
        title="Audit follow-ups and decisions",
        category="social-sg4",
        priority="P1",
        next_up="no",
        state="open",
    )

    existing_index = (
        "# Task Index\n\n"
        "## Next up\n\n"
        "<!-- ai-orch:generated next-up -->\n"
        "| Id | Priority | Task | Executor | Handoff |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| T154 | P0 | [Compatibility of social-service-client 3.1.0 and social-service-model 2.0.2 with the social WS](social-sg4/T154-compatibility.md) | kilo | `Read tasks/social-sg4/T154-compatibility.md and execute.` |\n"
        "<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n"
        "<!-- ai-orch:generated tasks-by-category -->\n"
        "### social-sg4\n\n"
        "Social SG4.\n\n"
        "| Id | Priority | Task | State | Executor | Depends on |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| T154 | P0 | [Compatibility of social-service-client 3.1.0 and social-service-model 2.0.2 with the social WS](social-sg4/T154-compatibility.md) | delivered | kilo | - |\n"
        "| T155 | P0 | [step 1 docker env](social-sg4/T155-roadmap.md) | in progress | kilo | - |\n"
        "| T037 | P1 | [Audit follow-ups and decisions](social-sg4/T037-plain.md) | open | kilo | - |\n"
        "<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n"
        "<!-- ai-orch:generated decisions -->\n"
        "| - | None. | - | - |\n"
        "<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n"
        "<!-- ai-orch:generated done -->\n"
        "| Id | Task | Result | Closed |\n"
        "| --- | --- | --- | --- |\n"
        "<!-- /ai-orch:generated done -->\n"
    )
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(existing_index, encoding="utf-8")

    def _extract_id_cells(text: str) -> list[str]:
        out: list[str] = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and re.match(r"^T\d{3,}", cells[0]):
                out.append(cells[0])
        return out

    before_ids = _extract_id_cells(existing_index)
    assert before_ids == ["T154", "T154", "T155", "T037"]

    # 1. sync-index --apply on bare-ID index
    res_sync1 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync1.returncode == 0, res_sync1.stderr
    synced = index_path.read_text(encoding="utf-8")
    after_ids = _extract_id_cells(synced)
    # All Id cells unchanged (bare T###)
    assert after_ids == before_ids

    next_sec = synced.split("## Tasks by category")[0]
    cat_sec = synced.split("## Tasks by category")[1].split("## Decisions waiting")[0]

    # T154 has bare Id and `short` as Task link text in both Next up and category table
    assert "| T154 | P0 | [client/model compatibility check](social-sg4/T154-compatibility.md) |" in next_sec
    assert "| T154 | P0 | [client/model compatibility check](social-sg4/T154-compatibility.md) | delivered | kilo | - |" in cat_sec
    assert re.search(r"^\| T154 \|", cat_sec, flags=re.MULTILINE)
    assert "T154 (" not in synced

    # T155 preserves its hand-curated short label in link text and keeps bare Id
    assert "| T155 | P0 | [step 1 docker env](social-sg4/T155-roadmap.md) | in progress | kilo | - |" in cat_sec
    # T037 stays bare `T037` with full title
    assert "| T037 | P1 | [Audit follow-ups and decisions](social-sg4/T037-plain.md) | open | kilo | - |" in cat_sec

    # 2. Idempotence: running sync-index --apply a second time reports "already in sync"
    res_sync2 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync2.returncode == 0
    assert "[ok] already in sync, nothing written" in res_sync2.stdout
    assert index_path.read_text(encoding="utf-8") == synced

    # 3. upgrade --apply path preserves bare-ID format and puts `short` into link text
    index_path.write_text(existing_index, encoding="utf-8")
    res_upg_prev = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_upg_prev.returncode == 0
    upg_plan_hash = json.loads(res_upg_prev.stdout)["plan_hash"]
    res_upg_app = run_cli(
        "upgrade",
        "--tasks-dir",
        str(tasks_dir),
        "--apply",
        "--expect-plan-hash",
        upg_plan_hash,
        "--json",
    )
    assert res_upg_app.returncode == 0
    upgraded_index = index_path.read_text(encoding="utf-8")
    assert _extract_id_cells(upgraded_index) == before_ids
    assert "| T154 | P0 | [client/model compatibility check](social-sg4/T154-compatibility.md) | delivered | kilo | - |" in upgraded_index

    # 4. `T### (short)` index keeps `T### (short)` in Id cell and full title in Task link text
    short_id_index = (
        "# Task Index\n\n"
        "## Next up\n\n"
        "<!-- ai-orch:generated next-up -->\n"
        "| Id | Priority | Task | Executor | Handoff |\n"
        "| --- | --- | --- | --- | --- |\n"
        "<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n"
        "<!-- ai-orch:generated tasks-by-category -->\n"
        "### social-sg4\n\n"
        "Social SG4.\n\n"
        "| Id | Priority | Task | State | Executor | Depends on |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| T154 (client/model compatibility check) | P0 | [Compatibility of social-service-client 3.1.0 and social-service-model 2.0.2 with the social WS](social-sg4/T154-compatibility.md) | delivered | kilo | - |\n"
        "| T155 (Roadmap step 1) | P0 | [step 1 docker env](social-sg4/T155-roadmap.md) | in progress | kilo | - |\n"
        "| T037 (Audit follow-ups and decisions) | P1 | [Audit follow-ups and decisions](social-sg4/T037-plain.md) | open | kilo | - |\n"
        "<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n"
        "<!-- ai-orch:generated decisions -->\n"
        "| - | None. | - | - |\n"
        "<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n"
        "<!-- ai-orch:generated done -->\n"
        "| Id | Task | Result | Closed |\n"
        "| --- | --- | --- | --- |\n"
        "<!-- /ai-orch:generated done -->\n"
    )
    rendered_short_idx = te.render_synced_index(tasks_dir, short_id_index, adopt=False)
    assert (
        "| T154 (client/model compatibility check) | P0 | "
        "[Compatibility of social-service-client 3.1.0 and social-service-model 2.0.2 with the social WS](social-sg4/T154-compatibility.md) |"
    ) in rendered_short_idx
    assert (
        "| T155 (Roadmap step 1) | P0 | "
        "[Roadmap step 1: dockerized environment with social-service-sg4 and Liferay](social-sg4/T155-roadmap.md) |"
    ) in rendered_short_idx
    # Next up was empty in short_id_index: new row T154 follows the other tables in the same index (`T### (short)`)
    short_next_sec = rendered_short_idx.split("## Tasks by category")[0]
    assert (
        "| T154 (client/model compatibility check) | P0 | "
        "[Compatibility of social-service-client 3.1.0 and social-service-model 2.0.2 with the social WS](social-sg4/T154-compatibility.md) |"
    ) in short_next_sec

    # 5. Empty/new table in a bare-ID index follows the bare-ID format of the other tables in the same index
    (tasks_dir / "new-cat").mkdir(parents=True)
    _write_sample_task(
        tasks_dir / "new-cat" / "T200-new-cat-task.md",
        task_id="T200",
        title="Full title of the new category task",
        category="new-cat",
        priority="P1",
        next_up="no",
        state="open",
        short="new cat short",
    )
    rendered_with_new_cat = te.render_synced_index(tasks_dir, synced, adopt=False)
    assert "| T200 | P1 | [new cat short](new-cat/T200-new-cat-task.md) | open | kilo | - |" in rendered_with_new_cat


def test_t050_per_section_summary_in_upgrade_and_sync_index_preview(tmp_path: pathlib.Path) -> None:
    """T050 bounce fix 4a: upgrade and sync-index previews summarise rows added/removed/changed per table and Next up membership changes."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "audit-auth").mkdir(parents=True)
    (tasks_dir / "done" / "audit-auth").mkdir(parents=True)

    _write_sample_task(
        tasks_dir / "audit-auth" / "T001-keep.md",
        task_id="T001",
        title="Keep task",
        category="audit-auth",
        priority="P0",
        next_up="yes",
        state="in progress",
    )
    _write_sample_task(
        tasks_dir / "audit-auth" / "T002-new.md",
        task_id="T002",
        title="New task",
        category="audit-auth",
        priority="P1",
        next_up="yes",
        state="open",
    )
    _write_sample_task(
        tasks_dir / "done" / "audit-auth" / "T003-finished.md",
        task_id="T003",
        title="Finished task",
        category="audit-auth",
        priority="P2",
        next_up="no",
        state="done",
    )

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        "# Task Index\n\n"
        "## Next up\n\n"
        "| Id | Priority | Task | Executor | Handoff |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| T001 | P0 | [Keep task](audit-auth/T001-keep.md) | kilo | `Read tasks/audit-auth/T001-keep.md and execute.` |\n"
        "| T003 | P2 | [Finished task](audit-auth/T003-finished.md) | kilo | `Read tasks/audit-auth/T003-finished.md and execute.` |\n\n"
        "## Tasks by category\n\n"
        "### audit-auth\n\n"
        "Auth.\n\n"
        "| Id | Priority | Task | State | Executor | Depends on |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| T001 | P0 | [Keep task](audit-auth/T001-keep.md) | open | kilo | - |\n"
        "| T003 | P2 | [Finished task](audit-auth/T003-finished.md) | open | kilo | - |\n\n"
        "## Decisions waiting\n\n"
        "| - | None. | - | - |\n\n"
        "## Done\n\n"
        "| Id | Task | Result | Closed |\n"
        "| --- | --- | --- | --- |\n",
        encoding="utf-8",
    )

    # 1. Check upgrade preview output
    res_upg = run_cli("upgrade", "--tasks-dir", str(tasks_dir))
    assert res_upg.returncode == 0
    assert "Next up: +1 -1 ~1 row(s) (membership: +T002, -T003)" in res_upg.stdout
    assert "Tasks by category: +1 -1 ~1 row(s) (audit-auth: +1 -1 ~1)" in res_upg.stdout
    assert "Decisions waiting: +0 -0 ~0 row(s)" in res_upg.stdout
    assert "Done: +1 -0 ~0 row(s)" in res_upg.stdout

    # 2. Check sync-index --adopt preview output
    res_adopt = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt")
    assert res_adopt.returncode == 0
    assert "[preview] Section summary:" in res_adopt.stdout
    assert "Next up: +1 -1 ~1 row(s) (membership: +T002, -T003)" in res_adopt.stdout
    assert "Tasks by category: +1 -1 ~1 row(s) (audit-auth: +1 -1 ~1)" in res_adopt.stdout
    assert "Done: +1 -0 ~0 row(s)" in res_adopt.stdout


def test_t050_sync_index_no_change_message(tmp_path: pathlib.Path) -> None:
    """T050 bounce fix 4b: sync-index prints '[ok] already in sync, nothing written' when nothing changed."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "audit-auth").mkdir(parents=True)
    _write_sample_task(
        tasks_dir / "audit-auth" / "T001-first.md",
        task_id="T001",
        title="Task 001",
        category="audit-auth",
        priority="P1",
        state="open",
    )

    # First sync-index --apply writes the initial index
    res1 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res1.returncode == 0
    assert "[ok] updated" in res1.stdout

    # Second sync-index --apply when nothing changed prints "[ok] already in sync, nothing written"
    res2 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res2.returncode == 0
    assert "[ok] already in sync, nothing written" in res2.stdout
    assert "[ok] updated" not in res2.stdout


def test_t054_upgrade_previews_by_default_and_applies_only_with_plan_hash(tmp_path: pathlib.Path) -> None:
    """T054: `tasks upgrade` previews by default and applies only with --apply and matching plan hash."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "AGENTS.md").write_text("# Project convention\n", encoding="utf-8")
    (tasks_dir / "00-INDEX.md").write_text("# Index\n", encoding="utf-8")

    # 1. Plain upgrade writes nothing and prints plan, hash, and apply instruction
    res_plain = run_cli("upgrade", "--tasks-dir", str(tasks_dir))
    assert res_plain.returncode == 0
    assert "[preview] Upgrade plan" in res_plain.stdout
    assert "Plan hash:" in res_plain.stdout
    assert f"To apply: ai-orch tasks upgrade --tasks-dir {tasks_dir} --apply --expect-plan-hash" in res_plain.stdout
    # Disk remains untouched
    assert not (tasks_dir / ".gitignore").exists()
    assert not (tasks_dir / ".gitattributes").exists()
    assert not (tasks_dir / "_inbox").exists()
    assert (tasks_dir / "AGENTS.md").read_text(encoding="utf-8") == "# Project convention\n"

    # 2. Plain upgrade with --json returns {ok: True, applied: False, plan_hash: ..., plan: [...]}
    res_json = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_json.returncode == 0
    payload = json.loads(res_json.stdout)
    assert payload["ok"] is True
    assert payload["applied"] is False
    assert "plan_hash" in payload and payload["plan_hash"]
    assert "plan" in payload and len(payload["plan"]) > 0
    plan_hash = payload["plan_hash"]
    # Verify plan items carry summary / diff summary
    for item in payload["plan"]:
        assert "action" in item
        assert "path" in item
        assert "before_hash" in item
        assert "summary" in item

    # 3. --dry-run and --preview keep working as explicit aliases of default
    res_dry = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--dry-run", "--json")
    assert res_dry.returncode == 0
    dry_data = json.loads(res_dry.stdout)
    assert dry_data["ok"] is True
    assert dry_data["applied"] is False
    assert dry_data["plan_hash"] == plan_hash

    res_prev = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--preview", "--json")
    assert res_prev.returncode == 0
    prev_data = json.loads(res_prev.stdout)
    assert prev_data["ok"] is True
    assert prev_data["applied"] is False
    assert prev_data["plan_hash"] == plan_hash

    # Disk still untouched
    assert not (tasks_dir / ".gitignore").exists()

    # 4. --apply without hash is refused with instruction to preview first
    res_no_hash = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_no_hash.returncode == 1
    assert "Applying upgrade requires --expect-plan-hash <hash>" in res_no_hash.stderr
    assert not (tasks_dir / ".gitignore").exists()

    res_no_hash_json = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res_no_hash_json.returncode == 1
    no_hash_data = json.loads(res_no_hash_json.stdout)
    assert no_hash_data["ok"] is False
    assert no_hash_data["applied"] is False
    assert "requires --expect-plan-hash" in no_hash_data["error"]
    assert no_hash_data["plan_hash"] == plan_hash

    # 5. --apply with a stale/wrong hash is refused
    stale_hash = "0123456789abcdef" * 4
    res_stale = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--apply", "--expect-plan-hash", stale_hash)
    assert res_stale.returncode == 1
    assert "Upgrade plan hash mismatch" in res_stale.stderr
    assert not (tasks_dir / ".gitignore").exists()

    res_stale_json = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--apply", "--expect-plan-hash", stale_hash, "--json")
    assert res_stale_json.returncode == 1
    stale_data = json.loads(res_stale_json.stdout)
    assert stale_data["ok"] is False
    assert stale_data["applied"] is False
    assert "mismatch" in stale_data["error"]

    # 6. Apply with matching hash writes to disk
    res_apply = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--apply", "--expect-plan-hash", plan_hash, "--json")
    assert res_apply.returncode == 0
    apply_data = json.loads(res_apply.stdout)
    assert apply_data["ok"] is True
    assert apply_data["applied"] is True
    assert (tasks_dir / ".gitignore").is_file()
    assert (tasks_dir / ".gitattributes").is_file()
    assert (tasks_dir / "_inbox" / "to-analyze").is_dir()
    assert "task-pipeline" in (tasks_dir / "AGENTS.md").read_text(encoding="utf-8")

    # 7. Re-running upgrade now reports already up-to-date
    res_up_to_date = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_up_to_date.returncode == 0
    utd_data = json.loads(res_up_to_date.stdout)
    assert utd_data["ok"] is True
    assert utd_data["applied"] is False
    assert utd_data["upgraded_files"] == []


# ===========================================================================
# T035 (Reopened): transition walk to done, bulk close, state spellings, log per step
# ===========================================================================


def test_t035_transition_walks_to_done_from_in_progress_and_delivered(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    t1 = tasks_dir / "features" / "T001-from-ip.md"
    _write_sample_task(t1, task_id="T001", title="From In Progress", category="features", state="in progress", executor="kilo")

    t2 = tasks_dir / "features" / "T002-from-del.md"
    _write_sample_task(t2, task_id="T002", title="From Delivered", category="features", state="delivered", executor="kilo")

    # Dry-run prints the planned path without modifying disk
    res_dry = run_cli(
        "transition", "T001", "done",
        "--verifier", "reviewer", "--reason", "all checks green",
        "--dry-run", "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_dry.returncode == 0
    dry_data = json.loads(res_dry.stdout)
    assert dry_data["ok"] is True
    assert dry_data["dry_run"] is True
    assert dry_data["path"] == ["in progress", "delivered", "verified", "done"]
    assert t1.is_file()

    # Walk from 'in progress' to 'done'
    res_t1 = run_cli(
        "transition", "T001", "done",
        "--verifier", "reviewer", "--reason", "all checks green",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_t1.returncode == 0
    d1 = json.loads(res_t1.stdout)
    assert d1["ok"] is True
    assert d1["old_state"] == "in progress"
    assert d1["new_state"] == "done"
    assert [t["to"] for t in d1["transitions"]] == ["delivered", "verified", "done"]
    assert (tasks_dir / "done" / "features" / "T001-from-ip.md").is_file()

    # Walk from 'delivered' to 'done'
    res_t2 = run_cli(
        "transition", "T002", "done",
        "--verifier", "owner", "--reason", "owner checked",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_t2.returncode == 0
    d2 = json.loads(res_t2.stdout)
    assert d2["ok"] is True
    assert d2["old_state"] == "delivered"
    assert d2["new_state"] == "done"
    assert [t["to"] for t in d2["transitions"]] == ["verified", "done"]
    assert (tasks_dir / "done" / "features" / "T002-from-del.md").is_file()


def test_t035_transition_walk_guard_refuses_missing_or_executor_verifier(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    t1 = tasks_dir / "features" / "T001-guard.md"
    _write_sample_task(t1, task_id="T001", title="Guard Test", category="features", state="in progress", executor="kilo")

    # 1. Missing verifier -> refused
    res_no_ver = run_cli("transition", "T001", "done", "--reason", "try close", "--tasks-dir", str(tasks_dir), "--json")
    assert res_no_ver.returncode == 1
    assert not json.loads(res_no_ver.stdout)["ok"]
    assert t1.is_file()

    # 2. Executor as verifier -> refused
    res_exec_ver = run_cli(
        "transition", "T001", "done",
        "--verifier", "kilo", "--reason", "self check",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_exec_ver.returncode == 1
    err_data = json.loads(res_exec_ver.stdout)
    assert err_data["ok"] is False
    assert "independent verifier" in err_data["error"]
    assert t1.is_file()

    # 3. With --owner-approved -> allowed
    res_owner = run_cli(
        "transition", "T001", "done",
        "--owner-approved", "--reason", "approved by owner",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_owner.returncode == 0
    assert json.loads(res_owner.stdout)["ok"] is True
    assert (tasks_dir / "done" / "features" / "T001-guard.md").is_file()


def test_t035_bulk_close_verified_with_plan_hash(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    t1 = tasks_dir / "features" / "T001-ver1.md"
    _write_sample_task(t1, task_id="T001", title="Verified One", category="features", state="verified", executor="kilo", verifier="owner")

    t2 = tasks_dir / "features" / "T002-ver2.md"
    _write_sample_task(t2, task_id="T002", title="Verified Two", category="features", state="verified", executor="kilo", verifier="reviewer")

    t3 = tasks_dir / "features" / "T003-open.md"
    _write_sample_task(t3, task_id="T003", title="Still Open", category="features", state="in progress", executor="kilo")

    # 1. Dry-run returns plan and plan_hash without closing
    res_dry = run_cli("close", "--verified", "--dry-run", "--tasks-dir", str(tasks_dir), "--json")
    assert res_dry.returncode == 0
    dry_data = json.loads(res_dry.stdout)
    assert dry_data["ok"] is True
    assert dry_data["dry_run"] is True
    assert dry_data["closed_count"] == 2
    assert dry_data["tasks"] == ["T001", "T002"]
    plan_hash = dry_data["plan_hash"]
    assert plan_hash
    assert t1.is_file() and t2.is_file()

    # 2. Without --expect-plan-hash (and without --dry-run) -> refused with plan_hash
    res_no_hash = run_cli("close", "--verified", "--tasks-dir", str(tasks_dir), "--json")
    assert res_no_hash.returncode == 1
    no_hash_data = json.loads(res_no_hash.stdout)
    assert no_hash_data["ok"] is False
    assert no_hash_data["plan_hash"] == plan_hash
    assert t1.is_file() and t2.is_file()

    # 3. With matching --expect-plan-hash -> closes both verified tasks, leaves T003 untouched
    res_apply = run_cli(
        "close", "--verified",
        "--expect-plan-hash", plan_hash,
        "--reason", "batch cleanup",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_apply.returncode == 0
    apply_data = json.loads(res_apply.stdout)
    assert apply_data["ok"] is True
    assert apply_data["closed_count"] == 2
    assert apply_data["tasks"] == ["T001", "T002"]
    assert (tasks_dir / "done" / "features" / "T001-ver1.md").is_file()
    assert (tasks_dir / "done" / "features" / "T002-ver2.md").is_file()
    assert t3.is_file()


def test_t035_hyphenated_and_variant_state_spellings_accepted_and_warned(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    t1 = tasks_dir / "features" / "T001-hyphen.md"
    _write_sample_task(t1, task_id="T001", title="Hyphenated State", category="features", state="in-progress", executor="kilo")

    t2 = tasks_dir / "features" / "T002-under.md"
    _write_sample_task(t2, task_id="T002", title="Underscore State", category="features", state="In_Progress", executor="kilo")

    # Normalisation unit checks
    assert te.normalize_state("in-progress") == "in progress"
    assert te.normalize_state("In Progress") == "in progress"
    assert te.normalize_state("in_progress") == "in progress"
    assert te.normalize_state("done-with-a-caveat: note") == "done with a caveat"

    # 1. list shows canonical_state 'in progress' and leaves files untouched
    orig_t1_bytes = t1.read_text(encoding="utf-8")
    res_list = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list.returncode == 0
    list_data = json.loads(res_list.stdout)
    by_id = {t["id"]: t for t in list_data["emergent_tasks"]}
    assert by_id["T001"]["canonical_state"] == "in progress"
    assert by_id["T002"]["canonical_state"] == "in progress"
    assert t1.read_text(encoding="utf-8") == orig_t1_bytes

    # 2. validate succeeds with a warning naming the canonical spelling 'in progress'
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0
    val_data = json.loads(res_val.stdout)
    assert val_data["ok"] is True
    assert any("in-progress" in w and "'in progress'" in w for w in val_data["warnings"])
    assert t1.read_text(encoding="utf-8") == orig_t1_bytes

    # 3. transition and close accept the hyphenated / variant tasks
    res_tr = run_cli("transition", "T001", "delivered", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tr.returncode == 0
    assert json.loads(res_tr.stdout)["new_state"] == "delivered"

    res_close = run_cli("close", "T002", "--verifier", "owner", "--reason", "ok", "--tasks-dir", str(tasks_dir), "--json")
    assert res_close.returncode == 0
    assert json.loads(res_close.stdout)["new_state"] == "done"


def test_t035_log_records_every_intermediate_step_for_single_and_folder_tasks(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # 1. Single-file task without pre-existing ## Log section, closed without --reason
    single_file = tasks_dir / "features" / "T001-single-log.md"
    _write_sample_task(single_file, task_id="T001", title="Single Log", category="features", state="in progress", executor="kilo")

    res_close = run_cli("close", "T001", "--verifier", "owner", "--tasks-dir", str(tasks_dir), "--json")
    assert res_close.returncode == 0
    done_single = tasks_dir / "done" / "features" / "T001-single-log.md"
    single_content = done_single.read_text(encoding="utf-8")
    assert "## Log" in single_content
    assert "state `in progress` -> `delivered`" in single_content
    assert "state `delivered` -> `verified`" in single_content
    assert "state `verified` -> `done`" in single_content

    # 2. Folder task walked via `transition <id> done` from 'open'
    folder_dir = tasks_dir / "features" / "T002-folder-log"
    _write_sample_task(folder_dir / "README.md", task_id="T002", title="Folder Log", category="features", state="open", executor="kilo")

    res_tr = run_cli(
        "transition", "T002", "done",
        "--verifier", "reviewer", "--reason", "walked from open",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_tr.returncode == 0
    done_progress = tasks_dir / "done" / "features" / "T002-folder-log" / "PROGRESS.md"
    assert done_progress.is_file()
    prog_text = done_progress.read_text(encoding="utf-8")
    assert "kilo: state `open` -> `in progress`" in prog_text
    assert "kilo: state `in progress` -> `delivered`" in prog_text
    assert "reviewer: state `delivered` -> `verified` — walked from open" in prog_text
    assert "reviewer: state `verified` -> `done` — walked from open" in prog_text


# ===========================================================================
# T037 (Reopened): git merge driver registration, 3-way row merge, validate
# warning, and sync-index dry-run footer
# ===========================================================================


def _git_run(repo_dir: pathlib.Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "Test User")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Test User")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    env["AI_ORCH_SOURCE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


def test_t037_real_git_merge_two_branches_adding_tasks_keeps_both_rows(tmp_path: pathlib.Path) -> None:
    """Real git init repo, two branches adding different tasks and both updating 00-INDEX.md,
    upgrade has configured the driver, git merge succeeds with zero conflict markers and both rows present."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git_run(repo_dir, "init", "-b", "main")

    tasks_dir = repo_dir / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    _write_sample_task(
        tasks_dir / "features" / "T001-base.md",
        task_id="T001",
        title="Base feature",
        short="Base feature",
        category="features",
        priority="P1",
        next_up="yes",
        state="open",
    )

    # Preview and apply upgrade to scaffold .gitattributes, 00-INDEX.md, and git config merge driver
    prev = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert prev.returncode == 0
    prev_data = json.loads(prev.stdout)
    app = run_cli(
        "upgrade",
        "--tasks-dir",
        str(tasks_dir),
        "--apply",
        "--expect-plan-hash",
        prev_data["plan_hash"],
        "--json",
    )
    assert app.returncode == 0, app.stdout + app.stderr
    assert json.loads(app.stdout)["ok"] is True

    _git_run(repo_dir, "add", ".")
    _git_run(repo_dir, "commit", "-m", "initial base")

    # Branch B adds T003 and updates 00-INDEX.md
    _git_run(repo_dir, "checkout", "-b", "branch-b")
    _write_sample_task(
        tasks_dir / "features" / "T003-branch-b.md",
        task_id="T003",
        title="Branch B feature",
        short="Branch B feature",
        category="features",
        priority="P1",
        next_up="yes",
        state="open",
    )
    res_sync_b = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync_b.returncode == 0
    _git_run(repo_dir, "add", ".")
    _git_run(repo_dir, "commit", "-m", "branch-b adds T003")

    # Main branch adds T002 and updates 00-INDEX.md
    _git_run(repo_dir, "checkout", "main")
    _write_sample_task(
        tasks_dir / "features" / "T002-branch-a.md",
        task_id="T002",
        title="Branch A feature",
        short="Branch A feature",
        category="features",
        priority="P1",
        next_up="yes",
        state="open",
    )
    res_sync_a = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync_a.returncode == 0
    _git_run(repo_dir, "add", ".")
    _git_run(repo_dir, "commit", "-m", "main adds T002")

    # Merge branch-b into main -> custom merge driver resolves 00-INDEX.md automatically
    res_merge = _git_run(repo_dir, "merge", "--no-edit", "branch-b", check=False)
    assert res_merge.returncode == 0, res_merge.stdout + res_merge.stderr

    merged_index = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "<<<<<<<" not in merged_index
    assert "=======" not in merged_index
    assert ">>>>>>>" not in merged_index

    # Both branches' new rows (plus base row) are present in Next up and Tasks by category
    nu_sec = te._extract_index_section_text(merged_index, "Next up", "next-up")
    cat_sec = te._extract_index_section_text(merged_index, "Tasks by category", "tasks-by-category")
    for sec in (nu_sec, cat_sec):
        assert "T001" in sec
        assert "T002" in sec
        assert "T003" in sec
        order, rmap = te._parse_index_table_rows(sec, "task")
        assert len(order) == 3
        assert set(order) == {"T001", "T002", "T003"}
        # Zero duplicate rows
        raw_table_rows = [
            ln for ln in sec.splitlines()
            if ln.strip().startswith("|") and not ln.strip().startswith("| Id") and "---" not in ln
        ]
        assert len(raw_table_rows) == 3


def test_t037_one_branch_edits_row_state_while_other_adds_row(tmp_path: pathlib.Path) -> None:
    """One branch edits a row's state while the other adds a row -> both changes kept (tested in both merge directions)."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git_run(repo_dir, "init", "-b", "main")

    tasks_dir = repo_dir / "tasks"
    t1_path = tasks_dir / "features" / "T001-existing.md"
    _write_sample_task(
        t1_path,
        task_id="T001",
        title="Existing feature",
        short="Existing feature",
        category="features",
        priority="P1",
        next_up="yes",
        state="open",
    )

    prev = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    plan_hash = json.loads(prev.stdout)["plan_hash"]
    run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--apply", "--expect-plan-hash", plan_hash, "--json")
    _git_run(repo_dir, "add", ".")
    _git_run(repo_dir, "commit", "-m", "base with T001 open")

    # Branch state-edit transitions T001 to 'in progress' and syncs index
    _git_run(repo_dir, "checkout", "-b", "state-edit")
    t1_path.write_text(
        t1_path.read_text(encoding="utf-8").replace("- state: open", "- state: in progress"),
        encoding="utf-8",
    )
    assert run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply").returncode == 0
    _git_run(repo_dir, "add", ".")
    _git_run(repo_dir, "commit", "-m", "transition T001 to in progress")

    # Main adds T002 while T001 is still 'open' on main
    _git_run(repo_dir, "checkout", "main")
    _write_sample_task(
        tasks_dir / "features" / "T002-added.md",
        task_id="T002",
        title="Added feature",
        short="Added feature",
        category="features",
        priority="P2",
        next_up="yes",
        state="open",
    )
    assert run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply").returncode == 0
    _git_run(repo_dir, "add", ".")
    _git_run(repo_dir, "commit", "-m", "add T002 on main")

    # Merge state-edit (theirs) into main (ours) where main's working tree still had T001 as open
    res_merge = _git_run(repo_dir, "merge", "--no-edit", "state-edit", check=False)
    assert res_merge.returncode == 0, res_merge.stdout + res_merge.stderr

    merged_index = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "<<<<<<<" not in merged_index
    cat_sec = te._extract_index_section_text(merged_index, "Tasks by category", "tasks-by-category")
    _, rmap = te._parse_index_table_rows(cat_sec, "category")
    assert set(rmap.keys()) == {"T001", "T002"}
    assert "| in progress |" in rmap["T001"]
    assert "| open |" in rmap["T002"]


def test_t037_conflict_outside_generated_regions_surfaces_conflict_markers(tmp_path: pathlib.Path) -> None:
    """Conflicting edits outside generated regions leave conflict markers and return non-zero while generated tables merge cleanly."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    _write_sample_task(tasks_dir / "features" / "T001-a.md", task_id="T001", title="Task A", short="Task A", category="features")
    _write_sample_task(tasks_dir / "features" / "T002-b.md", task_id="T002", title="Task B", short="Task B", category="features")

    base_idx = (
        "# Task Index\n\n"
        "Owner note: original shared line.\n\n"
        "## Next up\n\n"
        "<!-- ai-orch:generated next-up -->\n"
        "| Id | Priority | Task | Executor | Handoff |\n"
        "| --- | --- | --- | --- | --- |\n"
        "<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n"
        "<!-- ai-orch:generated tasks-by-category -->\n"
        "### features\n\n"
        "Features.\n\n"
        "| Id | Priority | Task | State | Executor | Depends on |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n"
        "<!-- ai-orch:generated decisions -->\n"
        "| Task / Initiative | Question (exact) | Decider | Blocks |\n"
        "| --- | --- | --- | --- |\n"
        "| - | None. | - | - |\n"
        "<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n"
        "<!-- ai-orch:generated done -->\n"
        "| Id | Task | Result | Closed |\n"
        "| --- | --- | --- | --- |\n"
        "<!-- /ai-orch:generated done -->\n"
    )
    ours_idx = base_idx.replace(
        "Owner note: original shared line.",
        "Owner note: edited on HEAD branch.",
    ).replace(
        "| Id | Priority | Task | State | Executor | Depends on |\n| --- | --- | --- | --- | --- | --- |",
        "| Id | Priority | Task | State | Executor | Depends on |\n| --- | --- | --- | --- | --- | --- |\n"
        "| T001 | P1 | [Task A](features/T001-a.md) | open | kilo | - |",
    )
    theirs_idx = base_idx.replace(
        "Owner note: original shared line.",
        "Owner note: edited on incoming branch.",
    ).replace(
        "| Id | Priority | Task | State | Executor | Depends on |\n| --- | --- | --- | --- | --- | --- |",
        "| Id | Priority | Task | State | Executor | Depends on |\n| --- | --- | --- | --- | --- | --- |\n"
        "| T002 | P1 | [Task B](features/T002-b.md) | open | kilo | - |",
    )

    f_base = tmp_path / "base.md"
    f_ours = tmp_path / "ours.md"
    f_theirs = tmp_path / "theirs.md"
    f_base.write_text(base_idx, encoding="utf-8")
    f_ours.write_text(ours_idx, encoding="utf-8")
    f_theirs.write_text(theirs_idx, encoding="utf-8")

    res = run_cli("merge-index", str(f_base), str(f_ours), str(f_theirs), "--tasks-dir", str(tasks_dir))
    assert res.returncode == 1
    merged_text = f_ours.read_text(encoding="utf-8")
    # Conflict markers surfaced around the conflicting outside prose
    assert "<<<<<<<" in merged_text
    assert "Owner note: edited on HEAD branch." in merged_text
    assert "Owner note: edited on incoming branch." in merged_text
    # Generated table still cleanly merged both rows without conflict markers inside
    cat_sec = te._extract_index_section_text(merged_text, "Tasks by category", "tasks-by-category")
    assert "<<<<<<<" not in cat_sec
    assert "T001" in cat_sec
    assert "T002" in cat_sec


def test_t037_upgrade_registers_git_merge_driver_and_validate_warns_when_missing(tmp_path: pathlib.Path) -> None:
    """upgrade sets merge.ai-orch-index.driver and merge.ai-orch-index.name in local git config, shows it in plan,
    is idempotent, and validate warns when .gitattributes has merge=ai-orch-index and git config lacks the driver."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git_run(repo_dir, "init", "-b", "main")

    tasks_dir = repo_dir / "tasks"
    _write_sample_task(tasks_dir / "features" / "T001.md", task_id="T001", category="features")

    # 1. Preview upgrade -> plan includes git config merge.ai-orch-index
    res_prev = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_prev.returncode == 0
    prev_data = json.loads(res_prev.stdout)
    plan_paths = {item["path"] for item in prev_data["plan"]}
    assert "git config merge.ai-orch-index" in plan_paths
    assert ".gitattributes" in plan_paths

    # Preview did not write to git config yet
    drv_before, name_before = te._get_git_merge_driver_config(tasks_dir)
    assert drv_before == ""
    assert name_before == ""

    # 2. Apply upgrade -> git config has driver and name
    res_app = run_cli(
        "upgrade",
        "--tasks-dir",
        str(tasks_dir),
        "--apply",
        "--expect-plan-hash",
        prev_data["plan_hash"],
        "--json",
    )
    assert res_app.returncode == 0
    drv_after, name_after = te._get_git_merge_driver_config(tasks_dir)
    assert drv_after.endswith("tasks merge-index %O %A %B")
    assert name_after == "ai-orch conflict-free 00-INDEX.md merge driver"

    # 3. Re-running upgrade is idempotent (plan is empty)
    res_idem = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res_idem.returncode == 0
    idem_data = json.loads(res_idem.stdout)
    assert idem_data["plan"] == []
    assert idem_data["upgraded_files"] == []

    # 4. Validate has no merge-driver warning when driver is configured
    res_val1 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val1.returncode == 0
    val1_data = json.loads(res_val1.stdout)
    assert not any("merge.ai-orch-index.driver" in w for w in val1_data["warnings"])

    # 5. Unset merge.ai-orch-index.driver -> validate warns with one-line fix
    _git_run(repo_dir, "config", "--unset", "merge.ai-orch-index.driver")
    res_val2 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val2.returncode == 0
    val2_data = json.loads(res_val2.stdout)
    drv_warnings = [w for w in val2_data["warnings"] if "merge.ai-orch-index.driver" in w]
    assert len(drv_warnings) == 1
    assert "merge=ai-orch-index" in drv_warnings[0]
    assert 'git config merge.ai-orch-index.driver "' in drv_warnings[0]
    assert "tasks merge-index %O %A %B" in drv_warnings[0]


def test_t037_sync_index_without_apply_prints_dry_run_footer(tmp_path: pathlib.Path) -> None:
    """sync-index without --apply ends with a one-line footer: '[preview] nothing written; re-run with --apply to write these changes'."""
    tasks_dir = tmp_path / "tasks"
    _write_sample_task(tasks_dir / "features" / "T001.md", task_id="T001", category="features")

    # 1. Plain sync-index (no --apply)
    res_plain = run_cli("sync-index", "--tasks-dir", str(tasks_dir))
    assert res_plain.returncode == 0
    lines = res_plain.stdout.strip().splitlines()
    assert lines[-1] == "[preview] nothing written; re-run with --apply to write these changes"
    assert not (tasks_dir / "00-INDEX.md").exists()

    # 2. sync-index --preview (no --apply)
    res_prev = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--preview")
    assert res_prev.returncode == 0
    prev_lines = res_prev.stdout.strip().splitlines()
    assert prev_lines[-1] == "[preview] nothing written; re-run with --apply to write these changes"


# ===========================================================================
# Initiative T055: Campaign Reports & Sync-Index Categories Hygiene
# ===========================================================================

def test_t055_campaign_reports_under_reviews_and_no_reports_category(tmp_path: pathlib.Path) -> None:
    """Running validation campaign creates report under tasks/_reviews/ and sync-index shows no 'reports' category."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # Create a simple use case
    res_create = run_cli(
        "use-cases", "create",
        "--id", "UC001",
        "--title", "Basic Scenario",
        "--actor", "Tester",
        "--verification-command", "echo 'OK'",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_create.returncode == 0

    # Run full product campaign
    res_camp = run_cli("use-cases", "campaign", "--tasks-dir", str(tasks_dir), "--json")
    assert res_camp.returncode == 0
    camp_data = json.loads(res_camp.stdout)
    assert camp_data["ok"] is True
    report_file = pathlib.Path(camp_data["report_file"])
    assert report_file.is_file()
    assert report_file.parent.name == "_reviews"
    assert report_file.parent == (tasks_dir / "_reviews")

    # Adopt and apply sync-index
    res_adopt = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--json")
    adopt_data = json.loads(res_adopt.stdout)
    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--expect-hash", adopt_data["hash"])
    assert res_sync.returncode == 0

    idx_text = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "### reports" not in idx_text
    assert "reports" not in te._extract_existing_category_order(idx_text)


def test_t055_preexisting_reports_folder_not_a_category(tmp_path: pathlib.Path) -> None:
    """A pre-existing tasks/reports/x.md is not treated as a category in 00-INDEX.md."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "reports").mkdir()
    (tasks_dir / "reports" / "x.md").write_text("# Old Report\nSome report text\n", encoding="utf-8")
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    res_adopt = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--json")
    adopt_data = json.loads(res_adopt.stdout)
    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--expect-hash", adopt_data["hash"])
    assert res_sync.returncode == 0

    idx_text = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")
    assert "### reports" not in idx_text
    assert "reports" not in te._extract_existing_category_order(idx_text)


def test_t055_category_removed_when_task_moved_to_done_or_folder_deleted(tmp_path: pathlib.Path) -> None:
    """A category folder with one task, then task moved to done/ or folder deleted: sync-index removes that category table; other categories untouched."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "feat-a").mkdir(parents=True)
    (tasks_dir / "feat-b").mkdir(parents=True)

    _write_sample_task(
        tasks_dir / "feat-a" / "T101-feat-a.md",
        task_id="T101",
        title="Feature A",
        category="feat-a",
        state="open",
    )
    _write_sample_task(
        tasks_dir / "feat-b" / "T102-feat-b.md",
        task_id="T102",
        title="Feature B",
        category="feat-b",
        state="open",
    )

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text("# Task Index\n", encoding="utf-8")

    # Initial adopt & sync
    res_adopt = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--json")
    adopt_data = json.loads(res_adopt.stdout)
    run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--expect-hash", adopt_data["hash"])

    idx_1 = index_path.read_text(encoding="utf-8")
    assert "### feat-a" in idx_1
    assert "### feat-b" in idx_1
    assert "T101" in idx_1
    assert "T102" in idx_1

    # Part 1: Move T101 to done/feat-a/
    done_cat_a = tasks_dir / "done" / "feat-a"
    done_cat_a.mkdir(parents=True, exist_ok=True)
    _write_sample_task(
        done_cat_a / "T101-feat-a.md",
        task_id="T101",
        title="Feature A",
        category="feat-a",
        state="done",
    )
    (tasks_dir / "feat-a" / "T101-feat-a.md").unlink()

    # Re-sync
    res_sync1 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync1.returncode == 0

    idx_2 = index_path.read_text(encoding="utf-8")
    assert "### feat-a" not in idx_2
    assert "### feat-b" in idx_2
    assert "T102" in idx_2
    assert "T101" in idx_2  # now in Done table
    assert "feat-a" not in te._extract_existing_category_order(idx_2)
    assert te._extract_existing_category_order(idx_2) == ["feat-b"]

    # Part 2: Delete feat-b folder
    shutil.rmtree(tasks_dir / "feat-b")

    # Re-sync
    res_sync2 = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync2.returncode == 0

    idx_3 = index_path.read_text(encoding="utf-8")
    assert "### feat-b" not in idx_3
    assert "### feat-a" not in idx_3
    assert te._extract_existing_category_order(idx_3) == []


def test_t055_sync_index_idempotent(tmp_path: pathlib.Path) -> None:
    """Running sync-index twice is idempotent ('already in sync')."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "engine").mkdir(parents=True)
    _write_sample_task(
        tasks_dir / "engine" / "T055-sample.md",
        task_id="T055",
        title="Campaign reports hygiene",
        category="engine",
        state="open",
    )
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text("# Task Index\n", encoding="utf-8")

    # First run (adopt + apply)
    res_adopt = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--json")
    adopt_data = json.loads(res_adopt.stdout)
    res_first = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--adopt", "--apply", "--expect-hash", adopt_data["hash"])
    assert res_first.returncode == 0

    content_first = index_path.read_text(encoding="utf-8")

    # Second run
    res_second = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_second.returncode == 0
    assert "already in sync, nothing written" in res_second.stdout

    content_second = index_path.read_text(encoding="utf-8")
    assert content_first == content_second

    # Also with --json
    res_json = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res_json.returncode == 0
    payload_json = json.loads(res_json.stdout)
    assert payload_json["ok"] is True
    assert payload_json["in_sync"] is True
    assert payload_json["changed"] is False


# ===========================================================================
# Initiative T060: sync-index adds rows for missing initiatives & preview msg
# ===========================================================================


def test_t060_sync_index_adds_missing_initiative_rows_and_preserves_existing(tmp_path: pathlib.Path) -> None:
    """T060: Three initiatives on disk (01-a, 02-b, 03-c with plan.md and task blocks), index lists only 01:
    - Preview without --apply prints '[preview] nothing written; re-run with --apply to write these changes' and writes nothing.
    - sync-index --apply adds 02 and 03 rows with derived status in initiative-number order; 01 row (including custom link text) unchanged byte for byte.
    - Re-run reports 'already in sync' (both with and without --apply).
    """
    tasks_dir = tmp_path / "tasks"
    for folder, num, title, blocks in [
        (
            "01-a",
            "01",
            "Alpha Initiative",
            "### 01.1 - First Alpha\n- **Status:** `done`\n- **Goal:** G1.\n",
        ),
        (
            "02-b",
            "02",
            "Beta Initiative",
            "### 02.1 - Beta Done\n- **Status:** `done`\n- **Goal:** G2a.\n\n"
            "### 02.2 - Beta Open\n- **Status:** `open`\n- **Goal:** G2b.\n",
        ),
        (
            "03-c",
            "03",
            "Gamma Initiative",
            "### 03.1 - Gamma Running\n- **Status:** `in progress`\n- **Goal:** G3a.\n\n"
            "### 03.2 - Gamma Open\n- **Status:** `open`\n- **Goal:** G3b.\n",
        ),
    ]:
        init_dir = tasks_dir / folder
        init_dir.mkdir(parents=True)
        (init_dir / "plan.md").write_text(
            f"# {num} - {title}\n\n## Tasks\n\n{blocks}",
            encoding="utf-8",
        )

    row_01_exact = "| 1 | 01 | [Custom Alpha Link](01-a/plan.md) | done | - | M |"
    initial_index = (
        "# Task Index\n\n"
        "## Initiatives\n\n"
        "<!-- ai-orch:generated initiatives -->\n"
        "| Priority | # | Initiative | Status | Depends on | Size |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{row_01_exact}\n"
        "<!-- /ai-orch:generated initiatives -->\n\n"
        "## Next up\n\n"
        "<!-- ai-orch:generated next-up -->\n"
        "| Id | Priority | Task | Executor | Handoff |\n"
        "| --- | --- | --- | --- | --- |\n"
        "<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n"
        "<!-- ai-orch:generated tasks-by-category -->\n"
        "<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n"
        "<!-- ai-orch:generated decisions -->\n"
        "| Key | Question | Blocks | Decider | Recommended |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| - | None. | - | - | - |\n"
        "<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n"
        "<!-- ai-orch:generated done -->\n"
        "| Id | Task | Result | Closed |\n"
        "| --- | --- | --- | --- |\n"
        "<!-- /ai-orch:generated done -->\n"
    )
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(initial_index, encoding="utf-8")

    # 1. Preview without --apply prints summary + new preview line, writes nothing
    res_preview = run_cli("sync-index", "--tasks-dir", str(tasks_dir))
    assert res_preview.returncode == 0
    preview_lines = res_preview.stdout.strip().splitlines()
    assert "[preview] Section summary:" in res_preview.stdout
    assert "Initiatives: +2 -0 ~0 row(s)" in res_preview.stdout
    assert preview_lines[-1] == "[preview] nothing written; re-run with --apply to write these changes"
    assert index_path.read_text(encoding="utf-8") == initial_index

    # 2. sync-index --apply adds 02 and 03 with derived status; 01 row unchanged byte-for-byte
    res_apply = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_apply.returncode == 0
    updated_index = index_path.read_text(encoding="utf-8")
    assert row_01_exact in updated_index
    row_02_expected = "| 2 | 02 | [Beta Initiative](02-b/plan.md) | in progress (done: 02.1; next: 02.2) | - | M |"
    row_03_expected = "| 3 | 03 | [Gamma Initiative](03-c/plan.md) | in progress (running: 03.1) | - | M |"
    assert row_02_expected in updated_index
    assert row_03_expected in updated_index
    assert updated_index.index(row_01_exact) < updated_index.index(row_02_expected) < updated_index.index(row_03_expected)

    # 3. Re-run with --apply: "already in sync"
    res_rerun = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_rerun.returncode == 0
    assert "already in sync" in res_rerun.stdout
    assert index_path.read_text(encoding="utf-8") == updated_index

    # 4. Re-run without --apply when nothing would change: keeps "already in sync"
    res_rerun_preview = run_cli("sync-index", "--tasks-dir", str(tasks_dir))
    assert res_rerun_preview.returncode == 0
    assert "already in sync" in res_rerun_preview.stdout
    assert "[preview] nothing written" not in res_rerun_preview.stdout


def test_t060_sync_index_preserves_p_style_priority_and_inserts_in_number_order(tmp_path: pathlib.Path) -> None:
    """T060: When existing Initiatives table uses P1/P- priorities and lists 01 and 03 with custom link text,
    missing 02 and 04 are inserted in initiative-number order (01, 02, 03, 04) with P1 priority and derived status.
    """
    tasks_dir = tmp_path / "tasks"
    for folder, num, title, st in [
        ("done/01-first", "01", "First Full Title", "done"),
        ("02-second", "02", "Second Full Title", "open"),
        ("03-third", "03", "Third Full Title", "open"),
        ("04-fourth", "04", "Fourth Full Title", "in progress"),
    ]:
        init_dir = tasks_dir / folder
        init_dir.mkdir(parents=True)
        (init_dir / "plan.md").write_text(
            f"# {num} - {title}\n\n## Tasks\n\n### {num}.1 - Subtask\n- **Status:** `{st}`\n- **Goal:** G.\n",
            encoding="utf-8",
        )

    row_01 = "| P- | 01 | [Custom First](done/01-first/plan.md) | done | - | M |"
    row_03 = "| P1 | 03 | [Custom Third](03-third/plan.md) | open | - | M |"
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        "# Task Index\n\n"
        "## Initiatives\n\n"
        "<!-- ai-orch:generated initiatives -->\n"
        "| Priority | # | Initiative | Status | Depends on | Size |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{row_01}\n"
        f"{row_03}\n"
        "<!-- /ai-orch:generated initiatives -->\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )

    res = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res.returncode == 0
    synced = index_path.read_text(encoding="utf-8")
    row_02 = "| P1 | 02 | [Second Full Title](02-second/plan.md) | open | - | M |"
    row_04 = "| P1 | 04 | [Fourth Full Title](04-fourth/plan.md) | in progress (running: 04.1) | - | M |"
    assert row_01 in synced
    assert row_02 in synced
    assert row_03 in synced
    assert row_04 in synced
    assert synced.index(row_01) < synced.index(row_02) < synced.index(row_03) < synced.index(row_04)


def test_t060_n062_unmarked_initiatives_and_specs_tables_do_not_duplicate_specs_heading(tmp_path: pathlib.Path) -> None:
    """N062: When ## Initiatives and ## Specs tables lack <!-- ai-orch:generated ... --> markers,
    sync-index --apply does not glue ## Specs to the last Initiatives row and does not duplicate ## Specs.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "01-alpha").mkdir(parents=True)
    (tasks_dir / "01-alpha" / "plan.md").write_text(
        "# 01 - Alpha\n\n## Tasks\n\n### 01.1 - Sub\n- **Status:** `done`\n- **Goal:** G.\n",
        encoding="utf-8",
    )
    (tasks_dir / "specs").mkdir(parents=True)
    (tasks_dir / "specs" / "spec-one.md").write_text("# Spec One\n", encoding="utf-8")

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        "# Task Index\n\n"
        "## Initiatives\n\n"
        "| Priority | # | Initiative | Status | Depends on | Size |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 1 | 01 | [Alpha](01-alpha/plan.md) | done | - | L |\n\n"
        "## Specs\n\n"
        "| Spec | Drives |\n"
        "| --- | --- |\n"
        "| [spec-one](specs/spec-one.md) | 01 |\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )

    res = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res.returncode == 0
    synced = index_path.read_text(encoding="utf-8")
    assert synced.count("## Specs") == 1
    assert "| L |\n\n## Specs" in synced










def test_use_cases_create_assigns_next_free_id(tmp_path: pathlib.Path) -> None:
    """An empty --id gets the next free UC###, counting ids under done/ too; explicit ids still work."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    res1 = run_cli("use-cases", "create", "--title", "First flow", "--tasks-dir", str(tasks_dir), "--json")
    assert res1.returncode == 0, res1.stdout + res1.stderr
    assert json.loads(res1.stdout)["id"] == "UC001"

    res_explicit = run_cli("use-cases", "create", "--id", "UC007", "--title", "Explicit", "--tasks-dir", str(tasks_dir), "--json")
    assert json.loads(res_explicit.stdout)["id"] == "UC007"

    done_dir = tasks_dir / "done" / "use-cases"
    done_dir.mkdir(parents=True)
    (done_dir / "UC012-old-flow.md").write_text("# UC012 - Old flow\n", encoding="utf-8")

    res2 = run_cli("use-cases", "create", "--id", "", "--title", "Second flow", "--tasks-dir", str(tasks_dir))
    assert res2.returncode == 0, res2.stdout + res2.stderr
    assert "Created use case UC013" in res2.stdout
    assert len(list((tasks_dir / "use-cases").glob("UC013-*.md"))) == 1
    assert "First flow" in next((tasks_dir / "use-cases").glob("UC001-*.md")).read_text(encoding="utf-8")

    bad = run_cli("use-cases", "create", "--id", "X1", "--title", "Bad", "--tasks-dir", str(tasks_dir), "--json")
    assert bad.returncode != 0


def test_t057_t061_t062_t063_t052_and_n064(tmp_path: pathlib.Path) -> None:
    """Verify T057 (walk step actors), T061 (ask --from-task explicit args),
    T062 (refuse placeholder delivery), T063 (reopen --to delivered --verify-by),
    T052 (questions move refuses answered without --force), and N064 (Italian use-case headings & --criteria).
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text(
        "# Task Index\n\n"
        "## Next up\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )

    # T062: task with template placeholders in Steps and Verification is refused on transition to delivered
    t_ph = tasks_dir / "features" / "T001-placeholder-task.md"
    t_ph.write_text(
        "# T001 Placeholder task\n\n"
        "- id: T001\n"
        "- title: Placeholder task\n"
        "- category: features\n"
        "- priority: P2\n"
        "- priority-reason: test\n"
        "- next-up: no\n"
        "- state: in progress\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read tasks/features/T001-placeholder-task.md\n\n"
        "## Goal\n\nTest goal.\n\n"
        "## Steps\n\n- [ ] Implement task steps.\n\n"
        "## Verification\n\n- [ ] Verify task implementation.\n",
        encoding="utf-8",
    )
    res_ph = run_cli("transition", "T001", "delivered", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ph.returncode != 0
    ph_data = json.loads(res_ph.stdout)
    assert "## Steps" in ph_data["error"]
    assert "## Verification" in ph_data["error"]

    # Replace placeholders with concrete steps & verification and verify T057 walk step actor attribution
    t_ph.write_text(
        t_ph.read_text(encoding="utf-8")
        .replace("- [ ] Implement task steps.", "- [x] Implemented feature X.")
        .replace("- [ ] Verify task implementation.", "- [x] pytest passed.")
        .replace("- state: in progress", "- state: open"),
        encoding="utf-8",
    )
    res_walk = run_cli(
        "close", "T001",
        "--verifier", "claude:deep-reasoning",
        "--reason", "Independent check passed",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_walk.returncode == 0, res_walk.stdout + res_walk.stderr
    done_t1 = tasks_dir / "done" / "features" / "T001-placeholder-task.md"
    assert done_t1.is_file()
    t1_text = done_t1.read_text(encoding="utf-8")
    assert "kilo: state `open` -> `in progress`" in t1_text
    assert "kilo: state `in progress` -> `delivered`" in t1_text
    assert "claude:deep-reasoning: state `delivered` -> `verified` — Independent check passed" in t1_text
    assert "claude:deep-reasoning: state `verified` -> `done` — Independent check passed" in t1_text

    # T063: reopen T001 directly to delivered with --verify-by
    res_reop = run_cli(
        "reopen", "T001",
        "--to", "delivered",
        "--verify-by", "gcube_atlas",
        "--reason", "Closed by architect; requester validates",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_reop.returncode == 0, res_reop.stdout + res_reop.stderr
    active_t1 = tasks_dir / "features" / "T001-placeholder-task.md"
    assert active_t1.is_file()
    assert not done_t1.exists()
    reop_text = active_t1.read_text(encoding="utf-8")
    assert "- state: delivered\n" in reop_text
    assert "- verify-by: gcube_atlas\n" in reop_text
    assert "- verifier:" not in reop_text
    assert "state `done` -> `delivered` — Closed by architect; requester validates" in reop_text

    # T061: questions ask --from-task keeps explicit --question, --option, --recommended, --asked-by, --decider
    active_t1.write_text(reop_text.replace("- state: delivered\n", "- state: open\n"), encoding="utf-8")
    res_q = run_cli(
        "questions", "ask",
        "--from-task", "T001",
        "--question", "Which backend should T001 use?",
        "--context", "Explicit context for T001.",
        "--option", "A: SQLite",
        "--option", "B: Postgres",
        "--recommended", "A",
        "--asked-by", "claude",
        "--decider", "owner",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_q.returncode == 0, res_q.stdout + res_q.stderr
    q_data = json.loads(res_q.stdout)
    qid = q_data["id"]
    q_show = json.loads(run_cli("questions", "show", qid, "--tasks-dir", str(tasks_dir), "--json").stdout)["question"]
    assert q_show["question"] == "Which backend should T001 use?"
    assert q_show["recommended"] == "A"
    assert q_show["asked_by"] == "claude"
    assert q_show["decider"] == "owner"
    assert [o["label"] for o in q_show["options"]] == ["A", "B"]

    # T052: answer Q001, then verify questions move refuses without --force and succeeds with --force
    res_ans = run_cli("questions", "answer", qid, "--choice", "A", "--by", "owner", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ans.returncode == 0
    res_mv_refuse = run_cli("questions", "move", qid, "--to", "https://example.org/1", "--tasks-dir", str(tasks_dir), "--json")
    assert res_mv_refuse.returncode != 0
    assert "already 'answered'" in json.loads(res_mv_refuse.stdout)["error"]
    res_mv_force = run_cli("questions", "move", qid, "--to", "https://example.org/1", "--force", "--tasks-dir", str(tasks_dir), "--json")
    assert res_mv_force.returncode == 0

    # N064 / T066: Italian use-case creation with --lang it and --criteria, plus clean Italian short-title derivation
    res_uc = run_cli(
        "use-cases", "create",
        "--title", "Tenere una cartella del progetto sincronizzata",
        "--lang", "it",
        "--criteria", "La cartella viene indicizzata; I file eliminati spariscono",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_uc.returncode == 0, res_uc.stdout + res_uc.stderr
    uc_id = json.loads(res_uc.stdout)["id"]
    uc_show = json.loads(run_cli("use-cases", "show", uc_id, "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc_show["short_title"] == "Tenere cartella progetto sincronizzata"
    assert "La cartella viene indicizzata" in uc_show["acceptance_criteria"]
    assert "I file eliminati spariscono" in uc_show["acceptance_criteria"]
    assert "## Description & Business Value" in uc_show["content"]
    assert "## Acceptance Criteria" in uc_show["content"]
    assert "Descrivere il valore per l'utente e il contesto." in uc_show["content"]


def test_t066_project_languages_and_english_headings_keywords(tmp_path: pathlib.Path) -> None:
    """T066:
    - languages declared it/it: tasks new and questions ask emit English headings; AGENTS.md managed block states the languages and the keyword rule; validate clean.
    - nothing declared: output of tasks new / questions ask byte-identical to current main.
    - use-cases create --lang it: English headings, Italian placeholder prose; an existing file with Italian headings still parses (show/record-validation) and validate warns to normalize.
    - old T065 key: still read, deprecation warning.
    - tasks config / show-config reports effective languages and their source.
    """
    # 1. Nothing declared: default en, output of tasks new / questions ask byte-identical
    tasks_default = tmp_path / "default_proj" / "tasks"
    tasks_default.mkdir(parents=True)
    cfg_def = json.loads(run_cli("config", "--tasks-dir", str(tasks_default), "--json").stdout)
    assert cfg_def["ok"] is True
    assert cfg_def["languages"] == {"tasks": "en", "questions": "en", "use_cases": "en"}
    assert cfg_def["declared"] is False
    assert cfg_def["language_sources"] == {"tasks": "default", "questions": "default", "use_cases": "default (from tasks)"}

    res_tn_def = run_cli(
        "new",
        "--category", "engine",
        "--title", "Default task",
        "--priority", "P2",
        "--priority-reason", "Testing default output",
        "--goal", "Verify byte-identical output.",
        "--step", "Do step one",
        "--verification", "pytest -q",
        "--tasks-dir", str(tasks_default),
        "--json",
    )
    assert res_tn_def.returncode == 0, res_tn_def.stdout + res_tn_def.stderr
    t_def_path = pathlib.Path(json.loads(res_tn_def.stdout)["file_path"])
    t_def_bytes = t_def_path.read_bytes()
    expected_task_text = (
        "# T001 Default task\n\n"
        "- id: T001\n"
        "- title: Default task\n"
        "- category: engine\n"
        "- priority: P2\n"
        "- priority-reason: Testing default output\n"
        "- next-up: no\n"
        "- state: open\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: -\n"
        "- handoff: Read tasks/engine/T001-default-task.md, do the open steps, run the Verification, update the task and the registry.\n"
        "- short: Default task\n\n"
        "## Goal\n\n"
        "Verify byte-identical output.\n\n"
        "## Steps\n\n"
        "- [ ] Do step one\n\n"
        "## Verification\n\n"
        "- pytest -q\n"
    )
    assert t_def_bytes == expected_task_text.encode("utf-8")

    res_qa_def = run_cli(
        "questions", "ask",
        "--question", "Should we keep English headings?",
        "--context", "Checking byte-identical question output.",
        "--option", "A=Yes: keep fixed English headings",
        "--option", "B=No: translate headings",
        "--recommended", "A",
        "--tasks-dir", str(tasks_default),
        "--json",
    )
    assert res_qa_def.returncode == 0, res_qa_def.stdout + res_qa_def.stderr
    q_def_path = pathlib.Path(json.loads(res_qa_def.stdout)["file_path"])
    q_def_text = q_def_path.read_text(encoding="utf-8")
    assert "\n## Context\n\nChecking byte-identical question output.\n\n## Options\n\n- **A** — Yes: keep fixed English headings\n- **B** — No: translate headings\n\n## Answer\n\n- choice: -\n- answered-by: -\n- answered: -\n" in q_def_text

    # Managed block without language declaration still states fixed English keywords rule
    upg_def = te.render_upgraded_agents_md("", tasks_dir=tasks_default)
    assert "Section headings" in upg_def and "fixed English keywords: never translate them." in upg_def
    assert "Effective project content languages:" not in upg_def

    # 2. Languages declared it/it in tasks/AGENTS.md fenced toml
    tasks_it = tmp_path / "it_proj" / "tasks"
    tasks_it.mkdir(parents=True)
    agents_it = tasks_it / "AGENTS.md"
    agents_it.write_text(
        "# Project tasks rules\n\n"
        "```toml\n"
        "[tasks]\n"
        'language = "it"\n\n'
        "[questions]\n"
        'language = "it"\n'
        "```\n",
        encoding="utf-8",
    )

    cfg_it = json.loads(run_cli("show-config", "--tasks-dir", str(tasks_it), "--json").stdout)
    assert cfg_it["ok"] is True
    assert cfg_it["declared"] is True
    assert cfg_it["languages"] == {"tasks": "it", "questions": "it", "use_cases": "it"}
    assert cfg_it["language_sources"]["tasks"] == "tasks/AGENTS.md [tasks].language"
    assert cfg_it["language_sources"]["questions"] == "tasks/AGENTS.md [questions].language"
    assert "tasks/AGENTS.md [tasks].language" in cfg_it["language_sources"]["use_cases"]

    # Upgrade writes managed block stating the languages and the keyword rule
    upgraded_it = te.render_upgraded_agents_md(agents_it.read_text(encoding="utf-8"), tasks_dir=tasks_it)
    agents_it.write_text(upgraded_it, encoding="utf-8")
    assert "Content language: tasks `it`, questions `it`, use cases `it`. Section headings and header field names are fixed English keywords: never translate them." in upgraded_it

    # tasks new and questions ask emit English headings even when languages are it/it
    res_tn_it = run_cli(
        "new",
        "--category", "engine",
        "--title", "Compito in italiano",
        "--priority", "P2",
        "--priority-reason", "Richiesta del proprietario",
        "--goal", "Verificare che le intestazioni restino in inglese.",
        "--step", "Primo passo",
        "--verification", "pytest -q",
        "--tasks-dir", str(tasks_it),
        "--json",
    )
    assert res_tn_it.returncode == 0, res_tn_it.stdout + res_tn_it.stderr
    t_it_text = pathlib.Path(json.loads(res_tn_it.stdout)["file_path"]).read_text(encoding="utf-8")
    assert "## Goal\n" in t_it_text
    assert "## Steps\n" in t_it_text
    assert "## Verification\n" in t_it_text

    res_qa_it = run_cli(
        "questions", "ask",
        "--question", "Quale opzione scegliamo?",
        "--context", "Contesto della domanda in italiano.",
        "--option", "A=Prima opzione: conseguenza A",
        "--option", "B=Seconda opzione: conseguenza B",
        "--recommended", "A",
        "--tasks-dir", str(tasks_it),
        "--json",
    )
    assert res_qa_it.returncode == 0, res_qa_it.stdout + res_qa_it.stderr
    q_it_text = pathlib.Path(json.loads(res_qa_it.stdout)["file_path"]).read_text(encoding="utf-8")
    assert "## Context\n" in q_it_text
    assert "## Options\n" in q_it_text
    assert "## Answer\n" in q_it_text

    val_it = json.loads(run_cli("validate", "--tasks-dir", str(tasks_it), "--json").stdout)
    assert val_it["ok"] is True
    assert val_it["errors"] == []
    assert val_it["warnings"] == []

    # 3. use-cases create --lang it: English headings, Italian placeholder prose;
    # existing file with Italian headings still parses (show/record-validation) and validate warns to normalize
    res_uc_it = run_cli(
        "use-cases", "create",
        "--title", " Ricerca semantica nei documenti ",
        "--lang", "it",
        "--tasks-dir", str(tasks_it),
        "--json",
    )
    assert res_uc_it.returncode == 0, res_uc_it.stdout + res_uc_it.stderr
    uc1_path = pathlib.Path(json.loads(res_uc_it.stdout)["file_path"])
    uc1_text = uc1_path.read_text(encoding="utf-8")
    assert "## Description & Business Value\nDescrivere il valore per l'utente e il contesto." in uc1_text
    assert "## Preconditions\n- Sistema avviato e inizializzato." in uc1_text
    assert "## Scenario / Interaction Steps\n1. L'utente avvia l'azione.\n2. Il sistema risponde." in uc1_text
    assert "## Automated Verification Command\n" in uc1_text
    assert "## Acceptance Criteria\n- [ ] Il flusso principale funziona come previsto." in uc1_text
    assert "## AI Validation Log\n" in uc1_text

    # Write an existing use case with Italian headings (legacy T065 file)
    uc2_path = tasks_it / "use-cases" / "UC002-caso-legacy.md"
    uc2_path.write_text(
        "# UC002 - Caso legacy con intestazioni italiane\n\n"
        "- id: UC002\n"
        "- title: Caso legacy con intestazioni italiane\n"
        "- actor: Utente\n"
        "- status: active\n"
        "- priority: P1\n"
        "- linked-tasks: -\n"
        "- verification-type: e2e\n"
        "- last-tested: -\n"
        "- last-verdict: -\n"
        "- short: Caso legacy italiano\n\n"
        "## Descrizione\n"
        "Valore del caso d'uso.\n\n"
        "## Precondizioni\n"
        "- Utente autenticato.\n\n"
        "## Scenario\n"
        "1. L'utente apre la pagina.\n\n"
        "## Comando di verifica\n"
        "```bash\n"
        "echo ok\n"
        "```\n\n"
        "## Criteri di accettazione\n"
        "- [ ] Funziona.\n\n"
        "## Registro delle verifiche\n",
        encoding="utf-8",
    )
    uc2_show = json.loads(run_cli("use-cases", "show", "UC002", "--tasks-dir", str(tasks_it), "--json").stdout)["use_case"]
    assert uc2_show["description"] == "Valore del caso d'uso."
    assert uc2_show["preconditions"] == "- Utente autenticato."
    assert uc2_show["scenario"] == "1. L'utente apre la pagina."
    assert uc2_show["verification_command"] == "echo ok"
    assert uc2_show["acceptance_criteria"] == "- [ ] Funziona."

    res_rec = run_cli(
        "use-cases", "record-validation", "UC002",
        "--verdict", "pass",
        "--summary", "Verificato con successo",
        "--tasks-dir", str(tasks_it),
        "--json",
    )
    assert res_rec.returncode == 0, res_rec.stdout + res_rec.stderr
    uc2_after = json.loads(run_cli("use-cases", "show", "UC002", "--tasks-dir", str(tasks_it), "--json").stdout)["use_case"]
    assert uc2_after["last_verdict"] == "pass"
    assert uc2_after["written_status"] == "verified"
    assert uc2_after["stage"] == "draft"
    assert uc2_after["status"] == "draft"
    assert "Verificato con successo" in uc2_after["validation_log"]

    val_uc_warn = json.loads(run_cli("validate", "--tasks-dir", str(tasks_it), "--json").stdout)
    assert val_uc_warn["ok"] is True
    assert any("non-standard heading 'Descrizione' (use 'Description & Business Value')" in w for w in val_uc_warn["warnings"])
    assert any("non-standard heading 'Precondizioni' (use 'Preconditions')" in w for w in val_uc_warn["warnings"])
    assert any("non-standard heading 'Comando di verifica' (use 'Automated Verification Command')" in w for w in val_uc_warn["warnings"])
    assert any("non-standard heading 'Criteri di accettazione' (use 'Acceptance Criteria')" in w for w in val_uc_warn["warnings"])
    assert any("non-standard heading 'Registro delle verifiche' (use 'AI Validation Log')" in w for w in val_uc_warn["warnings"])

    # 4. Old T065 key in .ai-orchestration.local.toml: still read, deprecation warning in validate
    legacy_proj = tmp_path / "legacy_proj"
    tasks_leg = legacy_proj / "tasks"
    tasks_leg.mkdir(parents=True)
    (legacy_proj / ".ai-orchestration.local.toml").write_text(
        'use_case_language = "it"\n',
        encoding="utf-8",
    )
    cfg_leg = json.loads(run_cli("config", "--tasks-dir", str(tasks_leg), "--json").stdout)
    assert cfg_leg["languages"]["use_cases"] == "it"
    assert any("deprecated language key 'use_case_language'" in w for w in cfg_leg["warnings"])

    res_uc_leg = run_cli(
        "use-cases", "create",
        "--title", "Caso con chiave legacy",
        "--tasks-dir", str(tasks_leg),
        "--json",
    )
    assert res_uc_leg.returncode == 0
    uc_leg_text = pathlib.Path(json.loads(res_uc_leg.stdout)["file_path"]).read_text(encoding="utf-8")
    assert "## Description & Business Value\nDescrivere il valore per l'utente e il contesto." in uc_leg_text

    val_leg = json.loads(run_cli("validate", "--tasks-dir", str(tasks_leg), "--json").stdout)
    assert val_leg["ok"] is True
    assert any("deprecated language key 'use_case_language'" in w for w in val_leg["warnings"])

    # 5. Malformed language code warns and falls back to en
    bad_proj = tmp_path / "bad_proj" / "tasks"
    bad_proj.mkdir(parents=True)
    (bad_proj / "AGENTS.md").write_text(
        "# Rules\n\n```toml\n[tasks]\nlanguage = \"\"\n[questions]\nlanguage = \"123_bad!\"\n```\n",
        encoding="utf-8",
    )
    val_bad = json.loads(run_cli("validate", "--tasks-dir", str(bad_proj), "--json").stdout)
    assert val_bad["ok"] is True
    assert any("empty or non-string language value" in w for w in val_bad["warnings"])
    assert any("malformed language code" in w for w in val_bad["warnings"])
    cfg_bad = json.loads(run_cli("config", "--tasks-dir", str(bad_proj), "--json").stdout)
    assert cfg_bad["languages"] == {"tasks": "en", "questions": "en", "use_cases": "en"}


# ===========================================================================
# T067: Initiative task Status note evidence preservation and walk single event
# ===========================================================================


def test_t067_initiative_task_status_note_evidence_and_closure(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    init_dir = tasks_dir / "26-evidence"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 26 Evidence Initiative\n\n"
        "- **Goal:** Test evidence preservation.\n\n"
        "## Tasks\n\n"
        "### 26.1 - Task with evidence\n"
        "- **Status:** `delivered` (merged 765f5d7 2026-09-07) · **Short:** Evidence test\n"
        "- **Goal:** Ensure merge sha is kept.\n\n"
        "### 26.2 - Task without note\n"
        "- **Status:** `delivered` · **Short:** Clean test\n"
        "- **Goal:** Ensure closure event without prior note.\n\n"
        "### 26.3 - Verification task\n"
        "- **Status:** `delivered` (merged abc123 2026-10-08) · **Short:** Target verification\n"
        "- **Goal:** Verification criteria check.\n\n"
        "## Closed\n",
        encoding="utf-8",
    )

    today = datetime.date.today().isoformat()

    # 1. Block with existing note keeps the sha and appends the closure event
    res1 = run_cli("transition", "26.1", "done", "--verifier", "X", "--tasks-dir", str(tasks_dir), "--json")
    assert res1.returncode == 0
    d1 = json.loads(res1.stdout)
    assert d1["ok"] is True
    assert d1["new_state"] == "done"

    plan_text = plan_file.read_text(encoding="utf-8")
    closed_part = plan_text.split("## Closed", 1)[1]
    assert "### 26.1 - Task with evidence" in closed_part
    assert f"- **Status:** `done` (merged 765f5d7 2026-09-07; done {today}, verifier X) · **Short:** Evidence test" in closed_part
    assert "765f5d7" in closed_part

    # 2. Block without a note gets just the closure event (current behaviour)
    res2 = run_cli("transition", "26.2", "done", "--verifier", "reviewer", "--tasks-dir", str(tasks_dir), "--json")
    assert res2.returncode == 0
    d2 = json.loads(res2.stdout)
    assert d2["ok"] is True
    assert d2["new_state"] == "done"

    plan_text = plan_file.read_text(encoding="utf-8")
    closed_part = plan_text.split("## Closed", 1)[1]
    assert "### 26.2 - Task without note" in closed_part
    assert f"- **Status:** `done` (done {today}, verifier reviewer) · **Short:** Clean test" in closed_part

    # 3. Verification criteria check: (merged abc123 2026-10-08) brought to done keeps abc123
    res3 = run_cli("transition", "26.3", "done", "--verifier", "auditor", "--tasks-dir", str(tasks_dir), "--json")
    assert res3.returncode == 0
    plan_text = plan_file.read_text(encoding="utf-8")
    closed_part = plan_text.split("## Closed", 1)[1]
    assert "abc123" in closed_part
    assert f"- **Status:** `done` (merged abc123 2026-10-08; done {today}, verifier auditor) · **Short:** Target verification" in closed_part


def test_t067_initiative_task_walk_produces_single_event(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    init_dir = tasks_dir / "27-walk"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 27 Walk Initiative\n\n"
        "- **Goal:** Test single event walk.\n\n"
        "## Tasks\n\n"
        "### 27.1 - Walk from in progress with note\n"
        "- **Status:** `in progress` (started 2026-09-01) · **Short:** Walk test\n"
        "- **Goal:** Verify single appended event from in progress.\n\n"
        "### 27.2 - Walk from open with note\n"
        "- **Status:** `open` (queued 2026-08-15) · **Short:** Open walk test\n"
        "- **Goal:** Verify single appended event from open.\n\n"
        "## Closed\n",
        encoding="utf-8",
    )

    today = datetime.date.today().isoformat()

    # Walk 27.1 from in progress to done in one command
    res1 = run_cli("transition", "27.1", "done", "--verifier", "reviewer", "--tasks-dir", str(tasks_dir), "--json")
    assert res1.returncode == 0
    d1 = json.loads(res1.stdout)
    assert d1["ok"] is True
    assert len(d1["transitions"]) == 3  # delivered -> verified -> done (from in progress)

    plan_text = plan_file.read_text(encoding="utf-8")
    closed_part = plan_text.split("## Closed", 1)[1]
    assert "### 27.1 - Walk from in progress with note" in closed_part
    # Single event appended for the final state, not intermediate delivered/verified events
    assert f"- **Status:** `done` (started 2026-09-01; done {today}, verifier reviewer) · **Short:** Walk test" in closed_part
    assert "delivered" not in closed_part.split("### 27.1")[1].split("\n")[1]
    assert "verified" not in closed_part.split("### 27.1")[1].split("\n")[1].split("done")[0]

    # Walk 27.2 from open to done in one command
    res2 = run_cli("transition", "27.2", "done", "--verifier", "reviewer", "--tasks-dir", str(tasks_dir), "--json")
    assert res2.returncode == 0
    d2 = json.loads(res2.stdout)
    assert d2["ok"] is True

    plan_text = plan_file.read_text(encoding="utf-8")
    closed_part = plan_text.split("## Closed", 1)[1]
    assert f"- **Status:** `done` (queued 2026-08-15; done {today}, verifier reviewer) · **Short:** Open walk test" in closed_part


def test_t067_initiative_task_reopen_keeps_history_note(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    init_dir = tasks_dir / "28-reopen"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"
    plan_file.write_text(
        "# 28 Reopen Initiative\n\n"
        "- **Goal:** Test reopen history.\n\n"
        "## Tasks\n\n"
        "## Closed\n\n"
        "### 28.1 - Closed task with history\n"
        "- **Status:** `done` (merged 765f5d7 2026-09-07; done 2026-10-27, verifier X) · **Short:** Reopen test\n"
        "- **Goal:** Keep history on reopen.\n",
        encoding="utf-8",
    )

    today = datetime.date.today().isoformat()

    # Reopen 28.1
    res_dry = te.reopen_node(tasks_dir, "28.1", reason="Need regression check", dry_run=True)
    assert res_dry["ok"] is True
    plan_hash = res_dry["plan_hash"]

    res_app = te.reopen_node(tasks_dir, "28.1", reason="Need regression check", expect_plan_hash=plan_hash)
    assert res_app["ok"] is True

    plan_text = plan_file.read_text(encoding="utf-8")
    assert "## Closed" not in plan_text  # empty Closed section is removed
    assert "### 28.1 - Closed task with history" in plan_text
    expected_status = f"- **Status:** `open` (merged 765f5d7 2026-09-07; done 2026-10-27, verifier X; reopened {today}, Need regression check) · **Short:** Reopen test"
    assert expected_status in plan_text
    assert "765f5d7" in plan_text
    assert "verifier X" in plan_text
    assert "Need regression check" in plan_text


def test_t067_initiative_task_note_truncation_over_200_chars(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    init_dir = tasks_dir / "29-trunc"
    init_dir.mkdir(parents=True)
    plan_file = init_dir / "plan.md"

    # Note with multiple intermediate events exceeding 200 characters
    long_mid_1 = "event1 " + ("x" * 80)
    long_mid_2 = "event2 " + ("y" * 80)
    plan_file.write_text(
        f"# 29 Trunc Initiative\n\n"
        f"## Tasks\n\n"
        f"### 29.1 - Long note task\n"
        f"- **Status:** `delivered` (merged 765f5d7 2026-09-07; {long_mid_1}; {long_mid_2}) · **Short:** Trunc test\n"
        f"- **Goal:** Truncate middle events when exceeding 200 chars.\n\n"
        f"## Closed\n",
        encoding="utf-8",
    )

    today = datetime.date.today().isoformat()

    res = run_cli("transition", "29.1", "done", "--verifier", "X", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0
    d = json.loads(res.stdout)
    assert d["ok"] is True

    plan_text = plan_file.read_text(encoding="utf-8")
    closed_part = plan_text.split("## Closed", 1)[1]
    status_line = next(line for line in closed_part.splitlines() if line.startswith("- **Status:**"))

    # The note must be on a single line
    assert "\n" not in status_line
    # The first note and the latest event must be kept
    assert "merged 765f5d7 2026-09-07" in status_line
    assert f"done {today}, verifier X" in status_line
    # The middle events must be dropped
    assert long_mid_1 not in status_line
    assert long_mid_2 not in status_line
    assert f"- **Status:** `done` (merged 765f5d7 2026-09-07; done {today}, verifier X) · **Short:** Trunc test" == status_line


def test_t068_clean_initiative_title() -> None:
    assert (
        te.clean_initiative_title(
            "# 01 — Consolidare le skill di orchestrazione e dei task in ai-orchestration — Piano di implementazione",
            num="01",
        )
        == "Consolidare le skill di orchestrazione e dei task in ai-orchestration"
    )
    assert (
        te.clean_initiative_title(
            "# 01 — Consolidate Orchestration & Task Skills into ai-orchestration — Implementation plan",
            num="01",
        )
        == "Consolidate Orchestration & Task Skills into ai-orchestration"
    )
    assert (
        te.clean_initiative_title("# 02 - Titolo semplice con trattino", num="02")
        == "Titolo semplice con trattino"
    )
    assert te.clean_initiative_title("# 03 — Titolo — Summary", num="03") == "Titolo"
    assert te.clean_initiative_title("# 04 — Titolo — Riepilogo", num="04") == "Titolo"
    assert te.clean_initiative_title("# Riepilogo: 05 - Titolo", num="05") == "Titolo"
    assert te.clean_initiative_title("06 - Senza cancelletto", num="06") == "Senza cancelletto"


def test_t068_sync_index_initiative_labels_renamed_and_curated(tmp_path: pathlib.Path) -> None:
    """T068: Renamed plan updates label via plain sync; hand-written label different from all titles is kept; task rows untouched."""
    # Setup git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    # Initiative 01: starts with English title, later translated to Italian
    init01_dir = tasks_dir / "01-scaffold"
    init01_dir.mkdir(parents=True)
    p01 = init01_dir / "plan.md"
    p01.write_text("# 01 - Old Scaffold Title — Implementation plan\n\n## Tasks\n", encoding="utf-8")

    # Initiative 02: starts with Auth title
    init02_dir = tasks_dir / "02-auth"
    init02_dir.mkdir(parents=True)
    p02 = init02_dir / "plan.md"
    p02.write_text("# 02 - Auth Feature\n\n## Tasks\n", encoding="utf-8")

    # Emergent task T099
    cat_dir = tasks_dir / "engine"
    cat_dir.mkdir(parents=True)
    _write_sample_task(
        cat_dir / "T099-test.md",
        task_id="T099",
        title="Full Emergent Task Title For T099",
        category="engine",
        priority="P1",
        next_up="no",
        state="open",
    )

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(tmp_path), check=True, capture_output=True)

    # Translate plan 01 title to Italian
    p01.write_text("# 01 - Nuovo Titolo Scaffold — Piano di implementazione\n\n## Tasks\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Translate plan 01"], cwd=str(tmp_path), check=True, capture_output=True)

    # Create 00-INDEX.md with:
    # - 01 having the old title label (from git history)
    # - 02 having a hand-curated label (differs from current and all past titles)
    # - T099 having a hand-curated short task label
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Initiatives

<!-- ai-orch:generated initiatives -->
| Priority | # | Initiative | Status | Depends on | Size |
| --- | --- | --- | --- | --- | --- |
| 1 | 01 | [Old Scaffold Title](01-scaffold/plan.md) | open | - | M |
| 2 | 02 | [Curated Auth Label](02-auth/plan.md) | open | - | M |
<!-- /ai-orch:generated initiatives -->

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
### engine

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T099 | P1 | [curated task label](engine/T099-test.md) | open | kilo | - |
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| - | None. | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )

    # 1. Plain sync-index:
    # - 01 label updates to "Nuovo Titolo Scaffold" (because "Old Scaffold Title" was in git history)
    # - 02 label stays "Curated Auth Label" (hand-curated: differs from current and all previous titles)
    # - T099 label stays "curated task label" (emergent task untouched)
    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync.returncode == 0, res_sync.stderr
    synced = index_path.read_text(encoding="utf-8")

    assert "| 1 | 01 | [Nuovo Titolo Scaffold](01-scaffold/plan.md) | open | - | M |" in synced
    assert "| 2 | 02 | [Curated Auth Label](02-auth/plan.md) | open | - | M |" in synced
    assert "| T099 | P1 | [curated task label](engine/T099-test.md) | open | kilo | - |" in synced

    # 2. sync-index --refresh-labels:
    # - preview shows change for 02: Curated Auth Label -> Auth Feature
    res_prev = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--refresh-labels")
    assert res_prev.returncode == 0
    assert "[Curated Auth Label]" in res_prev.stdout
    assert "[Auth Feature]" in res_prev.stdout
    assert "--refresh-labels --apply" in res_prev.stderr

    # - apply overrides 02 to "Auth Feature", keeps T099 untouched
    res_apply = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--refresh-labels", "--apply")
    assert res_apply.returncode == 0, res_apply.stderr
    refreshed = index_path.read_text(encoding="utf-8")

    assert "| 1 | 01 | [Nuovo Titolo Scaffold](01-scaffold/plan.md) | open | - | M |" in refreshed
    assert "| 2 | 02 | [Auth Feature](02-auth/plan.md) | open | - | M |" in refreshed
    assert "| T099 | P1 | [curated task label](engine/T099-test.md) | open | kilo | - |" in refreshed


def test_t068_sync_index_initiative_labels_non_git_repo(tmp_path: pathlib.Path) -> None:
    """T068: In a non-git directory, a label is curated only if it is not a prefix/substring-equal of the title."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    init01_dir = tasks_dir / "01-full"
    init01_dir.mkdir(parents=True)
    p01 = init01_dir / "plan.md"
    p01.write_text("# 01 - Full Initiative Title — Implementation plan\n\n## Tasks\n", encoding="utf-8")

    init02_dir = tasks_dir / "02-another"
    init02_dir.mkdir(parents=True)
    p02 = init02_dir / "plan.md"
    p02.write_text("# 02 - Another Initiative Title\n\n## Tasks\n", encoding="utf-8")

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Initiatives

<!-- ai-orch:generated initiatives -->
| Priority | # | Initiative | Status | Depends on | Size |
| --- | --- | --- | --- | --- | --- |
| 1 | 01 | [Full Initiative](01-full/plan.md) | open | - | M |
| 2 | 02 | [Hand-crafted](02-another/plan.md) | open | - | M |
<!-- /ai-orch:generated initiatives -->

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| - | None. | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )

    # 1. Plain sync-index:
    # 01 label is prefix of "Full Initiative Title" -> not curated -> follows current title
    # 02 label is NOT prefix/substring -> curated -> kept as "Hand-crafted"
    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync.returncode == 0, res_sync.stderr
    synced = index_path.read_text(encoding="utf-8")
    assert "| 1 | 01 | [Full Initiative Title](01-full/plan.md) | open | - | M |" in synced
    assert "| 2 | 02 | [Hand-crafted](02-another/plan.md) | open | - | M |" in synced

    # 2. With --refresh-labels: forces 02 to current title
    res_ref = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--refresh-labels", "--apply")
    assert res_ref.returncode == 0, res_ref.stderr
    refreshed = index_path.read_text(encoding="utf-8")
    assert "| 2 | 02 | [Another Initiative Title](02-another/plan.md) | open | - | M |" in refreshed


def test_t068_sync_index_initiative_in_done_table(tmp_path: pathlib.Path) -> None:
    """T068: Initiative rows in Done table follow current title or keep hand-curated label."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    done_init01 = tasks_dir / "done" / "01-consolidation"
    done_init01.mkdir(parents=True)
    p01 = done_init01 / "plan.md"
    p01.write_text("# 01 - Old English Consolidation — Implementation plan\n\n## Tasks\n", encoding="utf-8")

    done_init02 = tasks_dir / "done" / "02-migration"
    done_init02.mkdir(parents=True)
    p02 = done_init02 / "plan.md"
    p02.write_text("# 02 - Migration Service\n\n## Tasks\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=str(tmp_path), check=True, capture_output=True)

    # Rename 01
    p01.write_text("# 01 - Consolidamento delle skill in italiano — Piano di implementazione\n\n## Tasks\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Rename 01"], cwd=str(tmp_path), check=True, capture_output=True)

    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        """# Task Index

## Initiatives

<!-- ai-orch:generated initiatives -->
<!-- /ai-orch:generated initiatives -->

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| - | None. | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
| 01 | [Old English Consolidation](done/01-consolidation/plan.md) | done | 2026-10-15 |
| 02 | [Curated Migration](done/02-migration/plan.md) | done | 2026-10-16 |
<!-- /ai-orch:generated done -->
""",
        encoding="utf-8",
    )

    res_sync = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply")
    assert res_sync.returncode == 0, res_sync.stderr
    synced = index_path.read_text(encoding="utf-8")

    assert "| 01 | [Consolidamento delle skill in italiano](done/01-consolidation/plan.md) | done | 2026-10-15 |" in synced
    assert "| 02 | [Curated Migration](done/02-migration/plan.md) | done | 2026-10-16 |" in synced

    # --refresh-labels overrides curated label on 02
    res_ref = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--refresh-labels", "--apply")
    assert res_ref.returncode == 0, res_ref.stderr
    refreshed = index_path.read_text(encoding="utf-8")
    assert "| 02 | [Migration Service](done/02-migration/plan.md) | done | 2026-10-16 |" in refreshed


def test_17_1_use_case_link_projection_validate_and_show(tmp_path: pathlib.Path) -> None:
    """Task 17.1: read task<->use case links from emergent headers and initiative blocks,
    compute derived projection (many-to-many, dropped tasks flagged, cross-workspace raw strings),
    emit validate warnings (written!=derived, unknown UC, deprecated UC) with 0 errors,
    and render links in `tasks show` and `use-cases show` (text and --json).
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "done" / "features").mkdir(parents=True)
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "01-search").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # Use cases:
    # - UC001: active, written linked-tasks = ["T001"] (will differ from derived ["01.1", "T001", "T002"])
    # - UC002: deprecated, written linked-tasks = ["01.2"] (matches derived ["01.2"])
    # - UC004: verified, written linked-tasks = ["01.2", "T001"] (matches derived ["01.2", "T001"])
    run_cli(
        "use-cases", "create",
        "--id", "UC001",
        "--title", "Search by budget",
        "--actor", "Buyer",
        "--status", "active",
        "--linked-tasks", "T001",
        "--tasks-dir", str(tasks_dir),
    )
    (tasks_dir / "use-cases" / "UC002-legacy-filter.md").write_text(
        "# UC002 - Legacy filter\n\n"
        "- id: UC002\n"
        "- title: Legacy filter\n"
        "- actor: Buyer\n"
        "- status: deprecated\n"
        "- priority: P2\n"
        "- linked-tasks: 01.2\n"
        "- verification-type: automated-probe\n"
        "- last-tested: -\n"
        "- last-verdict: -\n\n"
        "## Description & Business Value\nDeprecated flow.\n\n"
        "## Preconditions\n- None.\n\n"
        "## Scenario / Interaction Steps\n1. Legacy step.\n\n"
        "## Automated Verification Command\n```bash\necho ok\n```\n\n"
        "## Acceptance Criteria\n- [ ] Legacy.\n\n"
        "## AI Validation Log\n",
        encoding="utf-8",
    )
    run_cli(
        "use-cases", "create",
        "--id", "UC004",
        "--title", "Export search results",
        "--actor", "Buyer",
        "--status", "verified",
        "--linked-tasks", "01.2, T001",
        "--tasks-dir", str(tasks_dir),
    )

    # Initiative 01 with two task blocks:
    # - 01.1 links UC001 (segment after Depends on)
    # - 01.2 links UC004, UC002, and unknown UC999 (segment placed before Depends on)
    (tasks_dir / "01-search" / "plan.md").write_text(
        "# 01 — Search Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Index budget field\n\n"
        "- **Status:** `in progress` · **Short:** Index budget · **Size:** M · **Depends on:** - · **Use cases:** UC001\n"
        "- **Goal:** Index budget field.\n\n"
        "### 01.2 - Export and legacy filter\n\n"
        "- **Status:** `open` · **Use cases:** UC004, UC002, UC999 · **Short:** Export filter · **Size:** S · **Depends on:** 01.1\n"
        "- **Goal:** Export results.\n",
        encoding="utf-8",
    )

    # Emergent tasks:
    # - T001 links UC001, UC004, and cross-workspace workspace: sibling-ws/UC010 (one task -> multiple UCs)
    t1_file = tasks_dir / "features" / "T001-search-ui.md"
    _write_sample_task(t1_file, task_id="T001", state="delivered")
    t1_file.write_text(
        t1_file.read_text(encoding="utf-8").replace(
            "- verifier: -",
            "- verifier: -\n- use-cases: UC001, UC004, workspace:sibling-ws/UC010",
        ),
        encoding="utf-8",
    )

    # - T002 is dropped and links UC001 (so UC001 has 3 linked tasks: 01.1, T001, T002)
    t2_file = tasks_dir / "done" / "features" / "T002-old-budget-ui.md"
    _write_sample_task(t2_file, task_id="T002", state="dropped")
    t2_file.write_text(
        t2_file.read_text(encoding="utf-8").replace(
            "- verifier: -",
            "- verifier: -\n- use-cases: UC001",
        ),
        encoding="utf-8",
    )

    # - T003 has empty `use-cases: -`
    t3_file = tasks_dir / "features" / "T003-chore-cleanup.md"
    _write_sample_task(t3_file, task_id="T003", state="open")
    t3_file.write_text(
        t3_file.read_text(encoding="utf-8").replace(
            "- verifier: -",
            "- verifier: -\n- use-cases: -",
        ),
        encoding="utf-8",
    )

    # 1. Verify compute_use_case_links (many-to-many, sorted, dropped included & flagged, reverse map, cross-workspace raw)
    links = te.compute_use_case_links(tasks_dir)
    assert links["UC001"] == ["01.1", "T001", "T002"]
    assert links["UC002"] == ["01.2"]
    assert links["UC004"] == ["01.2", "T001"]
    assert links["UC999"] == ["01.2"]
    assert links["workspace:sibling-ws/UC010"] == ["T001"]

    # Reverse map {task_id: [uc ids]}
    assert links.reverse["01.1"] == ["UC001"]
    assert links.reverse["01.2"] == ["UC004", "UC002", "UC999"]
    assert links.reverse["T001"] == ["UC001", "UC004", "workspace:sibling-ws/UC010"]
    assert links.reverse["T002"] == ["UC001"]
    assert "T003" not in links.reverse
    assert te.compute_task_use_case_links(tasks_dir) == links.by_task

    # Dropped tasks included in list and flagged
    assert "T002" in links.dropped_tasks
    assert "T001" not in links.dropped_tasks
    assert links.is_dropped("T002") is True
    assert links.is_dropped("01.1") is False
    uc1_details = {d["id"]: d for d in links.details["UC001"]}
    assert uc1_details["01.1"]["dropped"] is False
    assert uc1_details["T001"]["dropped"] is False
    assert uc1_details["T002"]["dropped"] is True
    assert uc1_details["T002"]["canonical_state"] == "dropped"

    # 2. Verify validate warnings (no errors)
    res_val = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val.returncode == 0, res_val.stdout + res_val.stderr
    val_payload = json.loads(res_val.stdout)
    assert val_payload["ok"] is True
    assert val_payload["errors"] == []
    warns = val_payload["warnings"]

    # Warning for UC001 written != derived (shows both)
    assert any(
        "UC001" in w and "written linked-tasks" in w and "T001" in w and "01.1, T001, T002" in w
        for w in warns
    ), f"Missing written!=derived warning for UC001 in: {warns}"
    # UC004 written matches derived -> no written!=derived warning for UC004
    assert not any("UC004" in w and "written linked-tasks" in w for w in warns)
    # Warning for unknown use case UC999
    assert any("01.2" in w and "references unknown use case 'UC999'" in w for w in warns)
    # Cross-workspace ref does NOT trigger unknown use case warning
    assert not any("workspace:sibling-ws/UC010" in w for w in warns)
    # Warning for deprecated use case UC002
    assert any("01.2" in w and "deprecated use case 'UC002'" in w for w in warns)

    # 3. Verify `tasks show <id>` (text and --json)
    res_tshow_json = run_cli("show", "T001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_tshow_json.returncode == 0
    tshow_data = json.loads(res_tshow_json.stdout)["task"]
    assert tshow_data["use_cases"] == ["UC001", "UC004", "workspace:sibling-ws/UC010"]
    uc_det_by_id = {u["id"]: u for u in tshow_data["use_cases_details"]}
    assert uc_det_by_id["UC001"]["stage"] == "in development"
    assert uc_det_by_id["UC001"]["status"] == "in development"
    assert uc_det_by_id["UC001"]["approval"] == "approved"
    assert uc_det_by_id["UC004"]["stage"] == "in development"
    assert uc_det_by_id["UC004"]["status"] == "in development"
    assert uc_det_by_id["UC004"]["approval"] == "approved"
    assert uc_det_by_id["workspace:sibling-ws/UC010"]["status"] == "external"
    assert uc_det_by_id["workspace:sibling-ws/UC010"]["external"] is True

    res_tshow_txt = run_cli("show", "T001", "--tasks-dir", str(tasks_dir))
    assert res_tshow_txt.returncode == 0
    assert "Use cases:" in res_tshow_txt.stdout
    assert "UC001 - Search by budget (stage: in development, status: in development, approval: approved)" in res_tshow_txt.stdout
    assert "UC004 - Export search results (stage: in development, status: in development, approval: approved)" in res_tshow_txt.stdout

    # 4. Verify `use-cases show <UC>` (text and --json)
    res_ucshow_json = run_cli("use-cases", "show", "UC001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_ucshow_json.returncode == 0
    uc1_show = json.loads(res_ucshow_json.stdout)["use_case"]
    assert uc1_show["linked_tasks"] == ["01.1", "T001", "T002"]
    assert uc1_show["derived_linked_tasks"] == ["01.1", "T001", "T002"]
    assert uc1_show["written_linked_tasks"] == ["T001"]
    assert uc1_show["linked_tasks_differ"] is True
    assert uc1_show["written_linked_tasks_note"] == "written, will be replaced by derived in 17.2"
    assert [d["state"] for d in uc1_show["linked_tasks_details"]] == ["in progress", "delivered", "dropped"]

    res_ucshow_txt = run_cli("use-cases", "show", "UC001", "--tasks-dir", str(tasks_dir))
    assert res_ucshow_txt.returncode == 0
    assert "Linked   : 01.1 (in progress), T001 (delivered), T002 (dropped)" in res_ucshow_txt.stdout
    assert "Written  : T001 (written, will be replaced by derived in 17.2)" in res_ucshow_txt.stdout

    # When written == derived (UC004), no "written, will be replaced by derived in 17.2" line is shown
    res_uc4_txt = run_cli("use-cases", "show", "UC004", "--tasks-dir", str(tasks_dir))
    assert res_uc4_txt.returncode == 0
    assert "Linked   : 01.2 (open), T001 (delivered)" in res_uc4_txt.stdout
    assert "written, will be replaced by derived in 17.2" not in res_uc4_txt.stdout



# ===========================================================================
# Initiative T069: Campaign Skips Draft Use Cases; Untested Is Not Failing
# ===========================================================================

def test_t069_campaign_skips_drafts_and_untested_is_not_failing(tmp_path: pathlib.Path) -> None:
    """T069 + 17.6: Campaign runs only ready use cases; non-ready/draft use cases are listed under Not ready without changing status or last-verdict; exit 127 / missing test file / timeout recorded as untested without setting status failing, and untested is excluded from the readiness denominator."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "01-core").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    (tasks_dir / "01-core" / "plan.md").write_text(
        "# 01 — Core Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Delivered task for ready use cases\n\n"
        "- **Status:** `done` · **Short:** Delivered task · **Size:** S · **Depends on:** - · **Use cases:** UC001, UC002, UC005\n"
        "- **Goal:** Delivered task.\n",
        encoding="utf-8",
    )

    # 1. Ready use case: passing
    res1 = run_cli(
        "use-cases", "create",
        "--id", "UC001",
        "--title", "Active Passing Flow",
        "--actor", "Tester",
        "--status", "active",
        "--verification-command", "echo 'PASS_OK'",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res1.returncode == 0

    # 2. Ready use case: failing probe
    res2 = run_cli(
        "use-cases", "create",
        "--id", "UC002",
        "--title", "Active Failing Flow",
        "--actor", "Tester",
        "--status", "active",
        "--verification-command", "exit 1",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res2.returncode == 0

    # 3. Draft use case 1 (no linked tasks): probe exits 1 (deliberately unimplemented), should NOT run
    res3 = run_cli(
        "use-cases", "create",
        "--id", "UC003",
        "--title", "Draft Unimplemented Flow",
        "--actor", "Tester",
        "--status", "draft",
        "--verification-command", "exit 1",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res3.returncode == 0

    # 4. Draft use case 2 (no linked tasks): probe echo, should NOT run
    res4 = run_cli(
        "use-cases", "create",
        "--id", "UC004",
        "--title", "Draft Future Feature",
        "--actor", "Tester",
        "--status", "draft",
        "--verification-command", "echo 'SHOULD_NOT_EXECUTE'",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res4.returncode == 0

    # 5. Ready use case: probe command does not exist (exit 127)
    res5 = run_cli(
        "use-cases", "create",
        "--id", "UC005",
        "--title", "Active Probe Nonexistent Command",
        "--actor", "Tester",
        "--status", "active",
        "--verification-command", "nonexistent-cmd-xyz-12345",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res5.returncode == 0

    # Run the validation campaign
    res_camp = run_cli("use-cases", "campaign", "--tasks-dir", str(tasks_dir), "--json")
    # Return code 1 because UC002 failed
    assert res_camp.returncode == 1
    camp = json.loads(res_camp.stdout)
    assert camp["ok"] is True
    assert camp["total"] == 3  # 3 ready tested
    assert camp["evaluated"] == 2  # 3 - 1 untested
    assert camp["passed"] == 1  # UC001
    assert camp["failed"] == 1  # UC002
    assert camp["untested"] == 1  # UC005
    assert camp["not_ready_count"] == 2  # UC003, UC004
    assert camp["out_of_scope"] == 2  # UC003, UC004
    assert camp["readiness_score"] == 50.0  # 1/2 evaluated (untested excluded from denominator)
    assert camp["readiness_score_in_scope"] == 33.3  # 1/3 in-scope

    # Inspect statuses and last-verdict of each use case
    uc1 = json.loads(run_cli("use-cases", "show", "UC001", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc1["stage"] == "verified"
    assert uc1["status"] == "verified"
    assert uc1["approval"] == "approved"
    assert uc1["last_verdict"] == "pass"

    uc2 = json.loads(run_cli("use-cases", "show", "UC002", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc2["stage"] == "failing"
    assert uc2["status"] == "failing"
    assert uc2["approval"] == "approved"
    assert uc2["last_verdict"] == "fail"

    uc5 = json.loads(run_cli("use-cases", "show", "UC005", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc5["stage"] == "untested"
    assert uc5["status"] == "untested"  # NOT failing!
    assert uc5["approval"] == "approved"
    assert uc5["last_verdict"] == "untested"

    uc3 = json.loads(run_cli("use-cases", "show", "UC003", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc3["stage"] == "draft"
    assert uc3["status"] == "draft"  # untouched
    assert uc3["approval"] == "proposed"
    assert uc3["last_verdict"] in (None, "-")  # untouched

    uc4 = json.loads(run_cli("use-cases", "show", "UC004", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc4["stage"] == "draft"
    assert uc4["status"] == "draft"  # untouched
    assert uc4["approval"] == "proposed"
    assert uc4["last_verdict"] in (None, "-")  # untouched

    # Check report content
    report_file = pathlib.Path(camp["report_file"])
    assert report_file.is_file()
    report_text = report_file.read_text(encoding="utf-8")

    assert "- **Total Tested:** 3" in report_text
    assert "- **Passed:** 1" in report_text
    assert "- **Failed:** 1" in report_text
    assert "- **Untested:** 1" in report_text
    assert "- **Not ready:** 2" in report_text
    assert "## Not ready" in report_text
    assert "UC003" in report_text
    assert "UC004" in report_text
    assert "| **UC001** |" in report_text
    assert "| `PASS` |" in report_text
    assert "| **UC002** |" in report_text
    assert "| `FAIL` |" in report_text
    assert "| **UC005** |" in report_text
    assert "| `UNTESTED` |" in report_text


def test_t069_probe_missing_test_file_and_timeout_recorded_as_untested(tmp_path: pathlib.Path) -> None:
    """T069: Missing test file and timeout probes are recorded as untested and do not mark use cases as failing."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "01-core").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    (tasks_dir / "01-core" / "plan.md").write_text(
        "# 01 — Core Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Delivered task\n\n"
        "- **Status:** `done` · **Short:** Delivered task · **Size:** S · **Depends on:** - · **Use cases:** UC010, UC011\n"
        "- **Goal:** Delivered task.\n",
        encoding="utf-8",
    )

    # 1. Missing test file probe
    run_cli(
        "use-cases", "create",
        "--id", "UC010",
        "--title", "Missing Test File Flow",
        "--actor", "Tester",
        "--status", "active",
        "--verification-command", "pytest tests/nonexistent_test_abc.py",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    res_val = run_cli("use-cases", "validate", "UC010", "--tasks-dir", str(tasks_dir), "--json")
    val_data = json.loads(res_val.stdout)
    assert val_data["verdict"] == "untested"
    assert val_data["stage"] == "untested"

    uc10 = json.loads(run_cli("use-cases", "show", "UC010", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc10["stage"] == "untested"
    assert uc10["status"] == "untested"
    assert uc10["approval"] == "approved"
    assert uc10["last_verdict"] == "untested"

    # 2. Timeout probe
    run_cli(
        "use-cases", "create",
        "--id", "UC011",
        "--title", "Timing Out Flow",
        "--actor", "Tester",
        "--status", "active",
        "--verification-command", "python3 -c 'import time; time.sleep(5)'",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    # Validate with 1s timeout
    ok, res_to = te.validate_use_case_probe(tasks_dir, "UC011", timeout_seconds=1)
    assert ok is True
    assert res_to["verdict"] == "untested"
    assert res_to["stage"] == "untested"

    uc11 = json.loads(run_cli("use-cases", "show", "UC011", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc11["stage"] == "untested"
    assert uc11["status"] == "untested"
    assert uc11["approval"] == "approved"
    assert uc11["last_verdict"] == "untested"


# ===========================================================================
# Task 17.2: link/unlink commands and derived rewrite of linked-tasks in sync-index
# ===========================================================================

def test_17_2_tasks_link_and_unlink_emergent_and_initiative_header_and_segment_order(tmp_path: pathlib.Path) -> None:
    """Task 17.2 (items 1, 3, 4):
    - `tasks link <id> UC001[,UC004]` and `tasks unlink <id> UC001`: preview by default, `--apply --expect-plan-hash`.
    - Emergent tasks: write/update `use-cases:` header respecting extension order (after `run-id`, before `short`).
    - Initiative tasks: write/update `**Use cases:**` segment right after `**Depends on:**` in the block's status line
      (and block rewriter preserves that position when adding/updating `Depends on` or other segments).
    - Unknown UC ids refused; deprecated UC warned.
    - Affected use cases' `linked-tasks:` rewritten in the same transaction on apply, preserving validation logs.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "01-search").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    run_cli(
        "use-cases", "create",
        "--id", "UC001",
        "--title", "Search by budget",
        "--actor", "Buyer",
        "--status", "active",
        "--tasks-dir", str(tasks_dir),
    )
    run_cli(
        "use-cases", "create",
        "--id", "UC004",
        "--title", "Export search results",
        "--actor", "Buyer",
        "--status", "active",
        "--tasks-dir", str(tasks_dir),
    )
    (tasks_dir / "use-cases" / "UC002-deprecated.md").write_text(
        "# UC002 - Deprecated flow\n\n"
        "- id: UC002\n"
        "- title: Deprecated flow\n"
        "- actor: Buyer\n"
        "- status: deprecated\n"
        "- priority: P2\n"
        "- linked-tasks: -\n"
        "- verification-type: automated-probe\n"
        "- last-tested: -\n"
        "- last-verdict: -\n\n"
        "## Description & Business Value\nDeprecated.\n\n"
        "## Preconditions\n- None.\n\n"
        "## Scenario / Interaction Steps\n1. Step.\n\n"
        "## Automated Verification Command\n```bash\necho ok\n```\n\n"
        "## Acceptance Criteria\n- [ ] Ok.\n\n"
        "## AI Validation Log\n",
        encoding="utf-8",
    )

    # Record a validation log entry on UC001 so we can verify it is preserved byte-for-byte
    run_cli(
        "use-cases", "record-validation", "UC001",
        "--verdict", "pass",
        "--summary", "Initial validation pass",
        "--evidence", "All assertions green",
        "--tasks-dir", str(tasks_dir),
    )
    uc1_path = next((tasks_dir / "use-cases").glob("UC001-*.md"))
    uc1_log_before = uc1_path.read_text(encoding="utf-8").split("## AI Validation Log", 1)[1]
    assert "Initial validation pass" in uc1_log_before

    # Emergent task T001 with both `run-id` and `short` headers so `use-cases` must land between them
    t1_file = tasks_dir / "features" / "T001-search-ui.md"
    t1_file.write_text(
        "# T001 Search UI\n\n"
        "- id: T001\n"
        "- title: Search UI\n"
        "- category: features\n"
        "- priority: P1\n"
        "- priority-reason: core\n"
        "- next-up: yes\n"
        "- state: open\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: src/ui.py\n"
        "- handoff: Implement UI.\n"
        "- size: M\n"
        "- kind: feature\n"
        "- run-id: run-123\n"
        "- short: Search UI\n\n"
        "## Goal\n\nBuild search UI.\n\n"
        "## Steps\n\n- [ ] Build UI component.\n\n"
        "## Verification\n\n- pytest tests/test_ui.py\n",
        encoding="utf-8",
    )

    # Initiative 01 with 01.1 (has Depends on, Labels after it) and 01.2 (no Depends on yet)
    plan_file = tasks_dir / "01-search" / "plan.md"
    plan_file.write_text(
        "# 01 — Search Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Index budget field\n\n"
        "- **Status:** `open` · **Short:** Index budget · **Size:** M · **Depends on:** - · **Labels:** backend\n"
        "- **Goal:** Index budget field.\n\n"
        "### 01.2 - Export results\n\n"
        "- **Status:** `open` · **Short:** Export results · **Size:** S\n"
        "- **Goal:** Export results.\n",
        encoding="utf-8",
    )

    # 1. Unknown UC id is refused
    res_unk = run_cli("link", "T001", "UC999", "--tasks-dir", str(tasks_dir), "--json")
    assert res_unk.returncode != 0
    assert "Unknown use case 'UC999'" in json.loads(res_unk.stdout)["error"]

    # 2. Preview by default on emergent task T001 (writes nothing)
    t1_bytes_before = t1_file.read_bytes()
    res_prev = run_cli("link", "T001", "UC001,UC004", "--tasks-dir", str(tasks_dir), "--json")
    assert res_prev.returncode == 0
    prev_data = json.loads(res_prev.stdout)
    assert prev_data["ok"] is True
    assert prev_data["applied"] is False
    assert prev_data["dry_run"] is True
    assert prev_data["use_cases"] == ["UC001", "UC004"]
    assert t1_file.read_bytes() == t1_bytes_before

    # Apply without --expect-plan-hash is refused
    res_no_hash = run_cli("link", "T001", "UC001,UC004", "--apply", "--tasks-dir", str(tasks_dir), "--json")
    assert res_no_hash.returncode != 0
    assert "requires --expect-plan-hash" in json.loads(res_no_hash.stdout)["error"]

    # Apply with --expect-plan-hash writes T001 and updates UC001 and UC004 in the same transaction
    res_app = run_cli(
        "link", "T001", "UC001,UC004",
        "--apply", "--expect-plan-hash", prev_data["plan_hash"],
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_app.returncode == 0, res_app.stdout + res_app.stderr
    app_data = json.loads(res_app.stdout)
    assert app_data["ok"] is True
    assert app_data["applied"] is True

    t1_text = t1_file.read_text(encoding="utf-8")
    assert "- use-cases: UC001, UC004" in t1_text
    # Check header order: after run-id, before short
    assert t1_text.index("- run-id: run-123") < t1_text.index("- use-cases: UC001, UC004") < t1_text.index("- short: Search UI")

    # Verify UC001 and UC004 linked-tasks were rewritten in the same transaction and UC001 log preserved byte-for-byte
    uc1_after = uc1_path.read_text(encoding="utf-8")
    assert "- linked-tasks: T001\n" in uc1_after
    assert uc1_after.split("## AI Validation Log", 1)[1] == uc1_log_before
    uc4_path = next((tasks_dir / "use-cases").glob("UC004-*.md"))
    assert "- linked-tasks: T001\n" in uc4_path.read_text(encoding="utf-8")

    # 3. Link initiative task 01.1 to UC001 and deprecated UC002 (warns on deprecated, places **Use cases:** right after **Depends on:**)
    res_prev_init = run_cli("link", "01.1", "UC001,UC002", "--tasks-dir", str(tasks_dir), "--json")
    assert res_prev_init.returncode == 0
    prev_init_data = json.loads(res_prev_init.stdout)
    assert any("deprecated" in w.lower() and "UC002" in w for w in prev_init_data["warnings"])

    res_app_init = run_cli(
        "link", "01.1", "UC001,UC002",
        "--apply", "--expect-plan-hash", prev_init_data["plan_hash"],
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_app_init.returncode == 0
    plan_text = plan_file.read_text(encoding="utf-8")
    assert "**Depends on:** - · **Use cases:** UC001, UC002 · **Labels:** backend" in plan_text

    # Verify UC001 now lists sorted ["01.1", "T001"]
    assert "- linked-tasks: 01.1, T001\n" in uc1_path.read_text(encoding="utf-8")

    # Verify block rewriter keeps **Use cases:** right after **Depends on:** even when Depends on is added later (on 01.2)
    prev_12 = json.loads(run_cli("link", "01.2", "UC004", "--tasks-dir", str(tasks_dir), "--json").stdout)
    run_cli("link", "01.2", "UC004", "--apply", "--expect-plan-hash", prev_12["plan_hash"], "--tasks-dir", str(tasks_dir))
    # Now set-deps on 01.2 (which had no **Depends on:** segment before)
    run_cli("set-deps", "01.2", "01.1", "--tasks-dir", str(tasks_dir))
    plan_text_after_deps = plan_file.read_text(encoding="utf-8")
    assert "**Depends on:** 01.1 · **Use cases:** UC004" in plan_text_after_deps

    # 4. Unlink UC004 from T001 and UC002 from 01.1
    prev_un = json.loads(run_cli("unlink", "T001", "UC004", "--tasks-dir", str(tasks_dir), "--json").stdout)
    res_un = run_cli(
        "unlink", "T001", "UC004",
        "--apply", "--expect-plan-hash", prev_un["plan_hash"],
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_un.returncode == 0
    assert "- use-cases: UC001\n" in t1_file.read_text(encoding="utf-8")
    # UC004 now only has 01.2
    assert "- linked-tasks: 01.2\n" in uc4_path.read_text(encoding="utf-8")

    # Validate tree is completely clean (0 errors)
    val_res = json.loads(run_cli("validate", "--tasks-dir", str(tasks_dir), "--json").stdout)
    assert val_res["ok"] is True
    assert val_res["errors"] == []


def test_17_2_sync_index_derived_rewrite_events_rollback_and_invalid_tree_refusal(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 17.2 (items 2, 4, 5):
    - `sync-index` includes targeted rewrite of each use case's `linked-tasks:` in its plan (never losing validation log).
    - Pre-adoption guard: skips rewriting `linked-tasks` to empty when written links are not yet adopted on tasks,
      printing 'run use-cases adopt-links first'.
    - Emits one `use_case.links_changed` event per changed use case.
    - Rolls back all touched files if an error occurs mid-transaction.
    - Refuses to run if `validate` has errors.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "use-cases").mkdir(parents=True)
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        "# Task Index\n\n"
        "## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )

    _write_sample_task(tasks_dir / "features" / "T001-feat.md", task_id="T001", title="Feat 1", category="features")
    _write_sample_task(tasks_dir / "features" / "T002-feat.md", task_id="T002", title="Feat 2", category="features")
    # T001 and T002 both link UC001 on the task side
    for tf in (tasks_dir / "features" / "T001-feat.md", tasks_dir / "features" / "T002-feat.md"):
        tf.write_text(
            tf.read_text(encoding="utf-8").replace("- handoff:", "- handoff:") + "",
            encoding="utf-8",
        )
        tf.write_text(
            te._rewrite_emergent_use_cases_in_text(tf.read_text(encoding="utf-8"), ["UC001"]),
            encoding="utf-8",
        )

    # UC001 has stale written linked-tasks: T001 (derived is T001, T002) and a custom AI Validation Log
    uc1_file = tasks_dir / "use-cases" / "UC001-search.md"
    uc1_log = (
        "## AI Validation Log\n\n"
        "### [2026-10-27 10:00 UTC] AI Validation by verifier-1\n"
        "- **Verdict:** `PASS`\n"
        "- **Summary:** Exact bytes preserved.\n"
        "- **Evidence:**\n  line 1\n  line 2\n"
    )
    uc1_file.write_text(
        "# UC001 - Search\n\n"
        "- id: UC001\n"
        "- title: Search\n"
        "- actor: User\n"
        "- status: active\n"
        "- priority: P1\n"
        "- linked-tasks: T001\n"
        "- verification-type: automated-probe\n"
        "- last-tested: 2026-10-27\n"
        "- last-verdict: pass\n\n"
        "## Description & Business Value\nSearch.\n\n"
        "## Preconditions\n- None.\n\n"
        "## Scenario / Interaction Steps\n1. Run search.\n\n"
        "## Automated Verification Command\n```bash\necho ok\n```\n\n"
        "## Acceptance Criteria\n- [ ] Works.\n\n"
        + uc1_log,
        encoding="utf-8",
    )

    # UC002 has written linked-tasks: T001, but NO task links to UC002 (unadopted! Must be guarded, not wiped to empty)
    uc2_file = tasks_dir / "use-cases" / "UC002-unadopted.md"
    uc2_file.write_text(
        "# UC002 - Unadopted\n\n"
        "- id: UC002\n"
        "- title: Unadopted\n"
        "- actor: User\n"
        "- status: draft\n"
        "- priority: P2\n"
        "- linked-tasks: T001\n"
        "- verification-type: automated-probe\n"
        "- last-tested: -\n"
        "- last-verdict: -\n\n"
        "## Description & Business Value\nUnadopted.\n\n"
        "## Preconditions\n- None.\n\n"
        "## Scenario / Interaction Steps\n1. Step.\n\n"
        "## Automated Verification Command\n```bash\necho ok\n```\n\n"
        "## Acceptance Criteria\n- [ ] Ok.\n\n"
        "## AI Validation Log\n",
        encoding="utf-8",
    )

    # 1. Preview sync-index: shows per-file change for UC001, skips UC002 with "run use-cases adopt-links first"
    res_prev = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--preview")
    assert res_prev.returncode == 0
    assert "run use-cases adopt-links first" in res_prev.stdout
    assert "UC002" in res_prev.stdout
    assert "use-cases/UC001-search.md (linked-tasks: [T001] -> [T001, T002])" in res_prev.stdout

    res_prev_json = json.loads(run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--preview", "--json").stdout)
    assert res_prev_json["ok"] is True
    assert res_prev_json["applied"] is False
    assert len(res_prev_json["use_case_rewrites"]) == 1
    assert res_prev_json["use_case_rewrites"][0]["id"] == "UC001"
    assert len(res_prev_json["skipped_unadopted_use_cases"]) == 1
    assert res_prev_json["skipped_unadopted_use_cases"][0]["id"] == "UC002"
    plan_hash = res_prev_json["plan_hash"]

    # 2. Test rollback on injected failure during apply
    orig_idx_bytes = index_path.read_bytes()
    orig_uc1_bytes = uc1_file.read_bytes()
    real_atomic_write = te._atomic_write_text
    call_count = {"n": 0}

    def _failing_write(path: pathlib.Path, content: str, encoding: str = "utf-8") -> None:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("Simulated disk failure on second file")
        real_atomic_write(path, content, encoding=encoding)

    monkeypatch.setattr(te, "_atomic_write_text", _failing_write)
    args_apply = te.build_parser().parse_args([
        "sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--expect-plan-hash", plan_hash
    ])
    with pytest.raises(OSError, match="Simulated disk failure"):
        te.cmd_sync_index(args_apply)
    monkeypatch.setattr(te, "_atomic_write_text", real_atomic_write)

    # Both 00-INDEX.md and UC001 must be rolled back byte-for-byte
    assert index_path.read_bytes() == orig_idx_bytes
    assert uc1_file.read_bytes() == orig_uc1_bytes

    # 3. Apply sync-index succeeds, preserves validation log byte-for-byte, and emits `use_case.links_changed`
    res_app = run_cli(
        "sync-index", "--tasks-dir", str(tasks_dir),
        "--apply", "--expect-plan-hash", plan_hash, "--json",
    )
    assert res_app.returncode == 0, res_app.stdout + res_app.stderr
    app_payload = json.loads(res_app.stdout)
    assert app_payload["ok"] is True
    assert app_payload["applied"] is True
    assert "- linked-tasks: T001, T002\n" in uc1_file.read_text(encoding="utf-8")
    assert uc1_file.read_text(encoding="utf-8").endswith(uc1_log)
    # UC002 untouched because of pre-adoption guard
    assert "- linked-tasks: T001\n" in uc2_file.read_text(encoding="utf-8")

    events = _read_ws_events(tmp_path)
    uc_events = [e for e in events if e["type"] == "use_case.links_changed"]
    assert len(uc_events) == 1
    assert uc_events[0]["subject"] == "UC001"
    assert uc_events[0]["data"]["old_linked_tasks"] == ["T001"]
    assert uc_events[0]["data"]["new_linked_tasks"] == ["T001", "T002"]

    # 4. Refuse to run if validate has errors
    bad_task = tasks_dir / "features" / "T003-broken.md"
    bad_task.write_text("# T003 Broken\n\n- id: T003\n- state: invalid-state\n", encoding="utf-8")
    res_invalid = run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--apply", "--json")
    assert res_invalid.returncode == 1
    inv_payload = json.loads(res_invalid.stdout)
    assert inv_payload["ok"] is False
    assert "invalid tasks tree" in inv_payload["error"]


# ===========================================================================
# Task 17.3: Migration `use-cases adopt-links`
# ===========================================================================

def test_17_3_adopt_links_emergent_initiative_union_snapshot_rollback_idempotent_and_sync_index(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 17.3 (items 1, 2, 3, 4):
    - `use-cases adopt-links` previews by default and writes with `--apply --expect-plan-hash`.
    - Supports both emergent tasks (`- use-cases:` header in canonical extension order) and initiative tasks
      (`**Use cases:**` segment right after `**Depends on:**`), including multiple blocks in the same `plan.md`.
    - Union with existing task `use-cases` (never removes existing links).
    - Writes snapshot of every file that will change under `tasks/_reviews/adopt-links-<timestamp>/`
      with file copies and `manifest.json` containing SHA256 hashes before applying.
    - Atomic apply with rollback on injected write failure.
    - Idempotent second run (nothing to do).
    - After apply, `sync-index` pre-adoption guard no longer skips those use cases, and the derived
      `linked-tasks` equals the old written lists for every adopted use case.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "01-core").mkdir(parents=True)
    index_path = tasks_dir / "00-INDEX.md"
    index_path.write_text(
        "# Task Index\n\n"
        "## Initiatives\n<!-- ai-orch:generated initiatives -->\n<!-- /ai-orch:generated initiatives -->\n\n"
        "## Next up\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
        "## Tasks by category\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
        "## Decisions waiting\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
        "## Done\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n",
        encoding="utf-8",
    )

    # Emergent task T001 already has `use-cases: UC099` (to test union, never removing) + `run-id` and `short`
    t1_file = tasks_dir / "features" / "T001-auth.md"
    t1_file.write_text(
        "# T001 Auth Flow\n\n"
        "- id: T001\n"
        "- title: Auth Flow\n"
        "- category: features\n"
        "- priority: P1\n"
        "- priority-reason: security\n"
        "- next-up: yes\n"
        "- state: open\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: src/auth.py\n"
        "- handoff: Implement auth.\n"
        "- run-id: run-abc\n"
        "- use-cases: UC099\n"
        "- short: Auth Flow\n\n"
        "## Goal\n\nImplement auth.\n\n"
        "## Steps\n\n- [ ] Add auth.\n\n"
        "## Verification\n\n- pytest\n",
        encoding="utf-8",
    )

    # Emergent task T002 has no `use-cases` header yet (has `run-id` and `short` to verify insertion order)
    t2_file = tasks_dir / "features" / "T002-token.md"
    t2_file.write_text(
        "# T002 Token Refresh\n\n"
        "- id: T002\n"
        "- title: Token Refresh\n"
        "- category: features\n"
        "- priority: P1\n"
        "- priority-reason: auth\n"
        "- next-up: no\n"
        "- state: open\n"
        "- executor: kilo\n"
        "- depends-on: -\n"
        "- decider: -\n"
        "- sources: -\n"
        "- paths: src/token.py\n"
        "- handoff: Refresh token.\n"
        "- run-id: run-xyz\n"
        "- short: Token Refresh\n\n"
        "## Goal\n\nRefresh token.\n\n"
        "## Steps\n\n- [ ] Refresh.\n\n"
        "## Verification\n\n- pytest\n",
        encoding="utf-8",
    )

    # Initiative 01 with two blocks (01.1 has existing Use cases: UC088; 01.2 has no Use cases yet)
    plan_file = tasks_dir / "01-core" / "plan.md"
    plan_file.write_text(
        "# 01 — Core Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Setup storage\n\n"
        "- **Status:** `done` · **Short:** Setup storage · **Size:** M · **Depends on:** - · **Use cases:** UC088 · **Labels:** storage\n"
        "- **Goal:** Setup storage.\n\n"
        "### 01.2 - Query index\n\n"
        "- **Status:** `done` · **Short:** Query index · **Size:** S · **Depends on:** 01.1 · **Labels:** search\n"
        "- **Goal:** Query index.\n",
        encoding="utf-8",
    )

    def _write_uc(uc_id: str, title: str, linked_tasks_str: str) -> pathlib.Path:
        p = tasks_dir / "use-cases" / f"{uc_id}-{title.lower().replace(' ', '-')}.md"
        p.write_text(
            f"# {uc_id} - {title}\n\n"
            f"- id: {uc_id}\n"
            f"- title: {title}\n"
            f"- actor: User\n"
            f"- status: active\n"
            f"- priority: P1\n"
            f"- linked-tasks: {linked_tasks_str}\n"
            f"- verification-type: automated-probe\n"
            f"- last-tested: -\n"
            f"- last-verdict: -\n\n"
            f"## Description & Business Value\n{title}.\n\n"
            f"## Preconditions\n- None.\n\n"
            f"## Scenario / Interaction Steps\n1. Step.\n\n"
            f"## Automated Verification Command\n```bash\necho ok\n```\n\n"
            f"## Acceptance Criteria\n- [ ] Ok.\n\n"
            f"## AI Validation Log\n",
            encoding="utf-8",
        )
        return p

    # UC001 links 01.1, T001; UC002 links 01.1, 01.2, T002; UC088 links 01.1; UC099 links T001
    _write_uc("UC001", "Login", "01.1, T001")
    _write_uc("UC002", "Session", "01.1, 01.2, T002")
    _write_uc("UC088", "Storage prelinked", "01.1")
    _write_uc("UC099", "Auth prelinked", "T001")

    # Record written lists before adoption
    ucs_before = {
        u["id"]: list(u["written_linked_tasks"])
        for u in te.discover_use_cases(tasks_dir)
    }

    # Before adopt-links, sync-index guard skips UC001 and UC002 (whose derived links are currently empty)
    sync_before = json.loads(run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--preview", "--json").stdout)
    skipped_before_ids = [s["id"] for s in sync_before["skipped_unadopted_use_cases"]]
    assert skipped_before_ids == ["UC001", "UC002"]

    # 1. Preview adopt-links (default, no --apply): writes nothing
    t1_orig = t1_file.read_bytes()
    t2_orig = t2_file.read_bytes()
    plan_orig = plan_file.read_bytes()

    res_prev = run_cli("use-cases", "adopt-links", "--tasks-dir", str(tasks_dir), "--json")
    assert res_prev.returncode == 0, res_prev.stdout + res_prev.stderr
    prev_data = json.loads(res_prev.stdout)
    assert prev_data["ok"] is True
    assert prev_data["applied"] is False
    assert prev_data["dry_run"] is True
    assert prev_data["tasks_changed_count"] == 4
    assert prev_data["files_changed_count"] == 3
    assert prev_data["unknown_ids"] == []
    assert t1_file.read_bytes() == t1_orig
    assert t2_file.read_bytes() == t2_orig
    assert plan_file.read_bytes() == plan_orig
    plan_hash = prev_data["plan_hash"]

    # Apply without --expect-plan-hash is refused
    res_no_hash = run_cli("use-cases", "adopt-links", "--apply", "--tasks-dir", str(tasks_dir), "--json")
    assert res_no_hash.returncode != 0
    assert "requires --expect-plan-hash" in json.loads(res_no_hash.stdout)["error"]

    # 2. Test rollback on injected failure during apply
    real_atomic_write = te._atomic_write_text
    write_counter = {"n": 0}

    def _fail_on_last_task_write(path: pathlib.Path, content: str, encoding: str = "utf-8") -> None:
        # Allow snapshot manifest/report writes under _reviews, fail on the 2nd task file write
        if "_reviews" not in path.parts:
            write_counter["n"] += 1
            if write_counter["n"] == 2:
                raise OSError("Simulated write failure mid-adopt-links")
        real_atomic_write(path, content, encoding=encoding)

    monkeypatch.setattr(te, "_atomic_write_text", _fail_on_last_task_write)
    args_fail = te.build_parser().parse_args([
        "use-cases", "adopt-links", "--tasks-dir", str(tasks_dir),
        "--apply", "--expect-plan-hash", plan_hash,
    ])
    with pytest.raises(OSError, match="Simulated write failure mid-adopt-links"):
        te.cmd_use_cases_adopt_links(args_fail)
    monkeypatch.setattr(te, "_atomic_write_text", real_atomic_write)

    # Verify all task files rolled back byte-for-byte
    assert t1_file.read_bytes() == t1_orig
    assert t2_file.read_bytes() == t2_orig
    assert plan_file.read_bytes() == plan_orig

    # 3. Apply adopt-links succeeds
    res_app = run_cli(
        "use-cases", "adopt-links",
        "--tasks-dir", str(tasks_dir),
        "--apply", "--expect-plan-hash", plan_hash,
        "--json",
    )
    assert res_app.returncode == 0, res_app.stdout + res_app.stderr
    app_data = json.loads(res_app.stdout)
    assert app_data["ok"] is True
    assert app_data["applied"] is True
    assert app_data["changed"] is True

    # Verify snapshot directory and manifest with sha256 hashes of pre-apply files
    snap_dir = pathlib.Path(app_data["snapshot_dir"])
    assert snap_dir.is_dir()
    assert snap_dir.parent == tasks_dir / "_reviews"
    assert snap_dir.name.startswith("adopt-links-")
    manifest_file = pathlib.Path(app_data["manifest_path"])
    assert manifest_file.is_file()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["plan_hash"] == plan_hash
    assert manifest["files_count"] == 3
    snap_by_rel = {f["path"]: f for f in manifest["files"]}
    assert snap_by_rel["features/T001-auth.md"]["sha256"] == hashlib.sha256(t1_orig).hexdigest()
    assert (snap_dir / "features/T001-auth.md").read_bytes() == t1_orig
    assert snap_by_rel["features/T002-token.md"]["sha256"] == hashlib.sha256(t2_orig).hexdigest()
    assert (snap_dir / "features/T002-token.md").read_bytes() == t2_orig
    assert snap_by_rel["01-core/plan.md"]["sha256"] == hashlib.sha256(plan_orig).hexdigest()
    assert (snap_dir / "01-core/plan.md").read_bytes() == plan_orig

    # Verify union and canonical header/segment ordering on tasks
    t1_after = t1_file.read_text(encoding="utf-8")
    assert "- use-cases: UC001, UC099\n" in t1_after
    assert t1_after.index("- run-id: run-abc") < t1_after.index("- use-cases: UC001, UC099") < t1_after.index("- short: Auth Flow")

    t2_after = t2_file.read_text(encoding="utf-8")
    assert "- use-cases: UC002\n" in t2_after
    assert t2_after.index("- run-id: run-xyz") < t2_after.index("- use-cases: UC002") < t2_after.index("- short: Token Refresh")

    plan_after = plan_file.read_text(encoding="utf-8")
    assert "**Depends on:** - · **Use cases:** UC001, UC002, UC088 · **Labels:** storage" in plan_after
    assert "**Depends on:** 01.1 · **Use cases:** UC002 · **Labels:** search" in plan_after

    # 4. Idempotent second run (nothing to do)
    res_second_prev = json.loads(
        run_cli("use-cases", "adopt-links", "--tasks-dir", str(tasks_dir), "--json").stdout
    )
    assert res_second_prev["ok"] is True
    assert res_second_prev["tasks_changed_count"] == 0
    assert res_second_prev["files_changed_count"] == 0
    assert res_second_prev["plan"] == []

    res_second_app = json.loads(
        run_cli(
            "use-cases", "adopt-links", "--tasks-dir", str(tasks_dir),
            "--apply", "--expect-plan-hash", res_second_prev["plan_hash"], "--json",
        ).stdout
    )
    assert res_second_app["ok"] is True
    assert res_second_app["applied"] is True
    assert res_second_app["changed"] is False

    # 5. After apply, sync-index guard no longer skips any use case and before/after linked-tasks lists are identical
    sync_prev_after = json.loads(run_cli("sync-index", "--tasks-dir", str(tasks_dir), "--preview", "--json").stdout)
    assert sync_prev_after["skipped_unadopted_use_cases"] == []
    res_sync_app = run_cli(
        "sync-index", "--tasks-dir", str(tasks_dir),
        "--apply", "--expect-plan-hash", sync_prev_after["plan_hash"], "--json",
    )
    assert res_sync_app.returncode == 0, res_sync_app.stdout + res_sync_app.stderr

    ucs_after = {
        u["id"]: list(u["written_linked_tasks"])
        for u in te.discover_use_cases(tasks_dir)
    }
    derived_proj = te.compute_use_case_links(tasks_dir)
    for ucid, before_list in ucs_before.items():
        assert ucs_after[ucid] == before_list
        assert derived_proj[ucid] == before_list


def test_17_3_adopt_links_unknown_noncanonical_cross_workspace_refusal_and_skip_unknown(
    tmp_path: pathlib.Path,
) -> None:
    """Task 17.3 (items 1, 4):
    - Fail-closed when `linked-tasks` contains an unknown task ID (`T999`), non-canonical ID (`bad_id` or
      initiative container ID `01`), or cross-workspace reference (`workspace:other/T001`): preview and apply
      return non-zero and list every offending reference.
    - `--skip-unknown` allows preview and apply to proceed, adopting valid links and writing unresolved IDs
      into the snapshot report and manifest.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "01-init").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    _write_sample_task(tasks_dir / "features" / "T001-valid.md", task_id="T001", title="Valid task", category="features")
    (tasks_dir / "01-init" / "plan.md").write_text(
        "# 01 — Init\n\n## Tasks\n\n### 01.1 - Valid child\n\n- **Status:** `open` · **Short:** Valid child · **Size:** S\n- **Goal:** Goal.\n",
        encoding="utf-8",
    )

    (tasks_dir / "use-cases" / "UC001-mixed.md").write_text(
        "# UC001 - Mixed links\n\n"
        "- id: UC001\n"
        "- title: Mixed links\n"
        "- actor: User\n"
        "- status: active\n"
        "- priority: P1\n"
        "- linked-tasks: T001, T999, workspace:other/T002, not-a-task-id, 01\n"
        "- verification-type: automated-probe\n"
        "- last-tested: -\n"
        "- last-verdict: -\n\n"
        "## Description & Business Value\nMixed.\n\n"
        "## Preconditions\n- None.\n\n"
        "## Scenario / Interaction Steps\n1. Step.\n\n"
        "## Automated Verification Command\n```bash\necho ok\n```\n\n"
        "## Acceptance Criteria\n- [ ] Ok.\n\n"
        "## AI Validation Log\n",
        encoding="utf-8",
    )

    # 1. Fail-closed without --skip-unknown (both preview and apply fail and list all 4 bad refs)
    res_fail = run_cli("use-cases", "adopt-links", "--tasks-dir", str(tasks_dir), "--json")
    assert res_fail.returncode == 1
    fail_data = json.loads(res_fail.stdout)
    assert fail_data["ok"] is False
    assert fail_data["applied"] is False
    bad_ids = [u["task_id"] for u in fail_data["unknown_ids"]]
    assert bad_ids == ["T999", "workspace:other/T002", "not-a-task-id", "01"]

    res_fail_app = run_cli(
        "use-cases", "adopt-links", "--tasks-dir", str(tasks_dir),
        "--apply", "--expect-plan-hash", fail_data["plan_hash"], "--json",
    )
    assert res_fail_app.returncode == 1
    assert "- use-cases:" not in (tasks_dir / "features" / "T001-valid.md").read_text(encoding="utf-8")

    # 2. With --skip-unknown, preview succeeds and apply adopts T001 while recording the 4 unresolved refs in the report
    res_skip_prev = run_cli(
        "use-cases", "adopt-links", "--tasks-dir", str(tasks_dir), "--skip-unknown", "--json",
    )
    assert res_skip_prev.returncode == 0
    skip_prev_data = json.loads(res_skip_prev.stdout)
    assert skip_prev_data["ok"] is True
    assert skip_prev_data["links_adopted"] == 1
    assert len(skip_prev_data["unresolved"]) == 4

    res_skip_app = run_cli(
        "use-cases", "adopt-links", "--tasks-dir", str(tasks_dir),
        "--skip-unknown", "--apply", "--expect-plan-hash", skip_prev_data["plan_hash"], "--json",
    )
    assert res_skip_app.returncode == 0, res_skip_app.stdout + res_skip_app.stderr
    skip_app_data = json.loads(res_skip_app.stdout)
    assert skip_app_data["ok"] is True
    assert skip_app_data["applied"] is True
    assert "- use-cases: UC001\n" in (tasks_dir / "features" / "T001-valid.md").read_text(encoding="utf-8")

    snap_dir = pathlib.Path(skip_app_data["snapshot_dir"])
    report_text = (snap_dir / "report.md").read_text(encoding="utf-8")
    for bad_ref in ("T999", "workspace:other/T002", "not-a-task-id", "01"):
        assert bad_ref in report_text
    manifest = json.loads((snap_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [u["task_id"] for u in manifest["unresolved_ids"]] == ["T999", "workspace:other/T002", "not-a-task-id", "01"]


def test_orchestrator_missing_hint_on_mutating_commands(tmp_path: pathlib.Path) -> None:
    """T071: task-modifying commands print a one-line hint when orchestrator role is missing."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    t_path = tasks_dir / "features" / "T001-sample.md"
    _write_sample_task(t_path, task_id="T001", state="open")

    # 1. Role missing -> hint appears on mutating command
    res = run_cli("transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "[hint]" in res.stderr
    assert "Orchestrator role is missing in this workspace" in res.stderr
    assert "sessions register --role orchestrator" in res.stderr

    # Non-mutating command (e.g. list) does not print hint
    res_list = run_cli("list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list.returncode == 0
    assert "[hint]" not in res_list.stderr

    # 2. Registered orchestrator -> no hint
    orch_dir = tmp_path / ".ai-orchestration"
    orch_dir.mkdir(parents=True, exist_ok=True)
    orch_file = orch_dir / "orchestrator.json"
    orch_doc = {
        "role_id": "orchestrator",
        "generation": 1,
        "status": "active",
        "current": {
            "role_id": "orchestrator",
            "generation": 1,
            "session_id": "test-session-123",
            "status": "active",
        },
    }
    orch_file.write_text(json.dumps(orch_doc, indent=2), encoding="utf-8")

    res2 = run_cli("transition", "T001", "delivered", "--tasks-dir", str(tasks_dir), "--json")
    assert res2.returncode == 0, res2.stdout + res2.stderr
    assert "[hint]" not in res2.stderr
    assert "sessions register --role orchestrator" not in res2.stderr

    # 3. Without --json: mutating command when role missing prints hint to stderr
    orch_file.unlink()
    res3 = run_cli("transition", "T001", "verified", "--verifier", "owner", "--reason", "OK", "--tasks-dir", str(tasks_dir))
    assert res3.returncode == 0, res3.stdout + res3.stderr
    assert "[hint]" in res3.stderr
    assert "sessions register --role orchestrator" in res3.stderr




def test_orchestrator_missing_hint_uses_enclosing_workspace(tmp_path: pathlib.Path) -> None:
    """T071: a project tree with its own .ai-orchestration/ (runs, events) uses the enclosing workspace's role."""
    project = tmp_path / "project"
    tasks_dir = project / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (project / ".ai-orchestration" / "runs").mkdir(parents=True)
    _write_sample_task(tasks_dir / "features" / "T001-sample.md", task_id="T001", state="open")
    orch_dir = tmp_path / ".ai-orchestration"
    orch_dir.mkdir()
    (orch_dir / "orchestrator.json").write_text(
        json.dumps({"current": {"session_id": "ws-session", "status": "active"}}), encoding="utf-8"
    )

    res = run_cli("transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "[hint]" not in res.stderr


# ===========================================================================
# Task 17.5: Use case lifecycle — approval field, migrate-lifecycle, derived stage
# ===========================================================================

def test_17_5_use_case_stage_derivation_all_stages_dropped_and_revalidation(tmp_path: pathlib.Path) -> None:
    """Task 17.5 (deliverables 1, 3, 4, 6):
    - `use-cases create` writes `approval: proposed` right where `status` was.
    - Pure derived `stage` for every stage:
      * `draft`: no linked tasks, OR all linked tasks dropped (links kept and shown as dropped);
      * `planned`: linked tasks exist, none started (open, waiting, blocked, paused);
      * `in development`: at least one linked task in progress, bounced, delivered, verified, or done,
        but not all non-dropped tasks delivered/verified/done;
      * `ready` -> mapped from `last-verdict` when all non-dropped tasks are delivered/verified/done
        (dropped tasks ignored):
        - `verified` (last-verdict: pass)
        - `failing` (last-verdict: fail)
        - `partial` (last-verdict: partial)
        - `untested` (last-verdict: untested or `-`/missing)
        - `ready (revalidation pending)` when `revalidation: pending`.
    - Shown everywhere (`use-cases list`, `use-cases show`, `00-INDEX.md` use-case rows):
      a use case that is not ready is never shown as raw `failing`; JSON keeps `status` = `stage`.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "done" / "features").mkdir(parents=True)
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "01-core").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # 1. Verify `use-cases create` writes `- approval: proposed` right after `- actor:` (no `- status:`)
    res_c1 = run_cli(
        "use-cases", "create",
        "--id", "UC001",
        "--title", "No Linked Tasks Draft",
        "--actor", "End-User",
        "--tasks-dir", str(tasks_dir),
        "--json",
    )
    assert res_c1.returncode == 0
    uc1_path = next((tasks_dir / "use-cases").glob("UC001-*.md"))
    uc1_text = uc1_path.read_text(encoding="utf-8")
    assert "- actor: End-User\n- approval: proposed\n- priority: P1\n" in uc1_text
    assert "- status:" not in uc1_text

    def _write_uc(
        uc_id: str,
        title: str,
        approval: str = "approved",
        last_verdict: str = "-",
        revalidation: str | None = None,
    ) -> pathlib.Path:
        reval_line = f"- revalidation: {revalidation}\n" if revalidation else ""
        p = tasks_dir / "use-cases" / f"{uc_id}-{title.lower().replace(' ', '-')}.md"
        p.write_text(
            f"# {uc_id} - {title}\n\n"
            f"- id: {uc_id}\n"
            f"- title: {title}\n"
            f"- actor: Operator\n"
            f"- approval: {approval}\n"
            f"- priority: P1\n"
            f"- linked-tasks: -\n"
            f"- verification-type: automated-probe\n"
            f"- last-tested: 2026-10-28\n"
            f"- last-verdict: {last_verdict}\n"
            f"{reval_line}"
            f"- short: {title}\n\n"
            "## Description & Business Value\nDesc.\n\n"
            "## Preconditions\n- None.\n\n"
            "## Scenario / Interaction Steps\n1. Step.\n\n"
            "## Automated Verification Command\n```bash\necho ok\n```\n\n"
            "## Acceptance Criteria\n- [ ] Criterion.\n\n"
            "## AI Validation Log\n",
            encoding="utf-8",
        )
        return p

    # UC002: all linked tasks dropped -> stage = draft (links kept, shown as dropped)
    _write_uc("UC002", "All Dropped Draft", approval="approved", last_verdict="fail")
    # UC003: linked tasks in open, waiting, blocked, paused (+ 1 dropped) -> stage = planned (even with last-verdict: fail!)
    _write_uc("UC003", "Planned Tasks Not Started", approval="proposed", last_verdict="fail")
    # UC004: one open + one in progress -> stage = in development (even with last-verdict: fail!)
    _write_uc("UC004", "In Development In Progress", approval="approved", last_verdict="fail")
    # UC005: one waiting + one bounced -> stage = in development
    _write_uc("UC005", "In Development Bounced", approval="approved", last_verdict="pass")
    # UC006: one open + one delivered -> stage = in development
    _write_uc("UC006", "In Development Partial Delivered", approval="approved", last_verdict="pass")
    # UC007: all non-dropped tasks delivered/verified/done (+ 1 dropped) + last-verdict: pass -> stage = verified
    _write_uc("UC007", "Ready Verified Flow", approval="approved", last_verdict="pass")
    # UC008: all non-dropped tasks delivered/verified/done + last-verdict: fail -> stage = failing
    _write_uc("UC008", "Ready Failing Flow", approval="approved", last_verdict="fail")
    # UC009: all non-dropped tasks delivered + last-verdict: partial -> stage = partial
    _write_uc("UC009", "Ready Partial Flow", approval="approved", last_verdict="partial")
    # UC010: all non-dropped tasks done + last-verdict: untested -> stage = untested
    _write_uc("UC010", "Ready Untested Explicit", approval="approved", last_verdict="untested")
    # UC011: all non-dropped tasks verified + last-verdict: - -> stage = untested
    _write_uc("UC011", "Ready Untested Missing Verdict", approval="deprecated", last_verdict="-")
    # UC012: all non-dropped tasks done + last-verdict: pass + revalidation: pending -> stage = ready (revalidation pending)
    _write_uc("UC012", "Ready Revalidation Pending", approval="approved", last_verdict="pass", revalidation="pending")

    # Create initiative 01 with tasks in every state linked to UC002..UC012
    (tasks_dir / "01-core" / "plan.md").write_text(
        "# 01 — Core Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Dropped task A\n\n"
        "- **Status:** `dropped` · **Short:** Dropped A · **Size:** S · **Depends on:** - · **Use cases:** UC002, UC003, UC007\n"
        "- **Goal:** Dropped A.\n\n"
        "### 01.2 - Dropped task B\n\n"
        "- **Status:** `dropped` · **Short:** Dropped B · **Size:** S · **Depends on:** - · **Use cases:** UC002\n"
        "- **Goal:** Dropped B.\n\n"
        "### 01.3 - Open task\n\n"
        "- **Status:** `open` · **Short:** Open task · **Size:** S · **Depends on:** - · **Use cases:** UC003, UC004, UC006\n"
        "- **Goal:** Open.\n\n"
        "### 01.4 - Waiting task\n\n"
        "- **Status:** `waiting` · **Short:** Waiting task · **Size:** S · **Depends on:** - · **Use cases:** UC003, UC005\n"
        "- **Goal:** Waiting.\n\n"
        "### 01.5 - Blocked task\n\n"
        "- **Status:** `blocked` · **Short:** Blocked task · **Size:** S · **Depends on:** - · **Use cases:** UC003\n"
        "- **Goal:** Blocked.\n\n"
        "### 01.6 - Paused task\n\n"
        "- **Status:** `paused` · **Short:** Paused task · **Size:** S · **Depends on:** - · **Use cases:** UC003\n"
        "- **Goal:** Paused.\n\n"
        "### 01.7 - In progress task\n\n"
        "- **Status:** `in progress` · **Short:** In progress · **Size:** S · **Depends on:** - · **Use cases:** UC004\n"
        "- **Goal:** In progress.\n\n"
        "### 01.8 - Bounced task\n\n"
        "- **Status:** `bounced` · **Short:** Bounced · **Size:** S · **Depends on:** - · **Use cases:** UC005\n"
        "- **Goal:** Bounced.\n\n"
        "### 01.9 - Delivered task\n\n"
        "- **Status:** `delivered` · **Short:** Delivered · **Size:** S · **Depends on:** - · **Use cases:** UC006, UC007, UC008, UC009\n"
        "- **Goal:** Delivered.\n\n"
        "### 01.10 - Verified task\n\n"
        "- **Status:** `verified` · **Short:** Verified · **Size:** S · **Depends on:** - · **Use cases:** UC007, UC008, UC011\n"
        "- **Goal:** Verified.\n\n"
        "### 01.11 - Done task\n\n"
        "- **Status:** `done` · **Short:** Done · **Size:** S · **Depends on:** - · **Use cases:** UC007, UC008, UC010, UC012\n"
        "- **Goal:** Done.\n\n"
        "### 01.12 - Done with caveat task\n\n"
        "- **Status:** `done with a caveat: minor note` · **Short:** Done caveat · **Size:** S · **Depends on:** - · **Use cases:** UC007\n"
        "- **Goal:** Done with caveat.\n",
        encoding="utf-8",
    )

    expected_stages = {
        "UC001": ("draft", "proposed"),
        "UC002": ("draft", "approved"),
        "UC003": ("planned", "proposed"),
        "UC004": ("in development", "approved"),
        "UC005": ("in development", "approved"),
        "UC006": ("in development", "approved"),
        "UC007": ("verified", "approved"),
        "UC008": ("failing", "approved"),
        "UC009": ("partial", "approved"),
        "UC010": ("untested", "approved"),
        "UC011": ("untested", "deprecated"),
        "UC012": ("ready (revalidation pending)", "approved"),
    }

    # Check `use-cases list` JSON and text
    res_list_json = run_cli("use-cases", "list", "--tasks-dir", str(tasks_dir), "--json")
    assert res_list_json.returncode == 0
    list_payload = json.loads(res_list_json.stdout)
    by_id = {u["id"]: u for u in list_payload["use_cases"]}
    for ucid, (exp_stage, exp_app) in expected_stages.items():
        assert by_id[ucid]["stage"] == exp_stage, f"{ucid}: expected stage {exp_stage}, got {by_id[ucid]['stage']}"
        assert by_id[ucid]["status"] == exp_stage, f"{ucid}: JSON status must equal stage {exp_stage}"
        assert by_id[ucid]["approval"] == exp_app

    res_list_txt = run_cli("use-cases", "list", "--tasks-dir", str(tasks_dir)).stdout
    for ucid, (exp_stage, exp_app) in expected_stages.items():
        assert f"[{ucid}] (stage: {exp_stage}, approval: {exp_app})" in res_list_txt
    # UC002, UC003, UC004 have last-verdict=fail but are not ready -> never shown as stage: failing
    for not_ready_id in ("UC002", "UC003", "UC004"):
        line_for_uc = next(ln for ln in res_list_txt.splitlines() if f"[{not_ready_id}]" in ln)
        assert "stage: failing" not in line_for_uc

    # Check `use-cases show` on UC002 (all dropped -> draft, links kept and shown as dropped)
    res_show_uc2_json = json.loads(run_cli("use-cases", "show", "UC002", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert res_show_uc2_json["stage"] == "draft"
    assert res_show_uc2_json["status"] == "draft"
    assert res_show_uc2_json["approval"] == "approved"
    assert res_show_uc2_json["linked_tasks"] == ["01.1", "01.2"]
    assert all(d["dropped"] is True for d in res_show_uc2_json["linked_tasks_details"])

    res_show_uc2_txt = run_cli("use-cases", "show", "UC002", "--tasks-dir", str(tasks_dir)).stdout
    assert "Approval : approved" in res_show_uc2_txt
    assert "Stage    : draft" in res_show_uc2_txt
    assert "Linked   : 01.1 (dropped), 01.2 (dropped)" in res_show_uc2_txt

    # Check `use-cases show` on UC012 (revalidation pending)
    res_show_uc12_json = json.loads(run_cli("use-cases", "show", "UC012", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert res_show_uc12_json["stage"] == "ready (revalidation pending)"
    assert res_show_uc12_json["status"] == "ready (revalidation pending)"

    # Check 00-INDEX.md use-case rows via render_synced_index
    rendered_idx = te.render_synced_index(tasks_dir, "# Task Index\n", adopt=True)
    assert "<!-- ai-orch:generated use-cases -->" in rendered_idx
    # Approved use cases show stage only; non-approved (proposed/deprecated) show `stage (approval)`
    assert "| UC001 (No Linked Tasks Draft) | P1 | [No Linked Tasks Draft](use-cases/UC001-no-linked-tasks-draft.md) | draft (proposed) |" in rendered_idx
    assert "| UC002 (All Dropped Draft) | P1 | [All Dropped Draft](use-cases/UC002-all-dropped-draft.md) | draft |" in rendered_idx
    assert "| UC003 (Planned Tasks Not Started) | P1 | [Planned Tasks Not Started](use-cases/UC003-planned-tasks-not-started.md) | planned (proposed) |" in rendered_idx
    assert "| UC004 (In Development In Progress) | P1 | [In Development In Progress](use-cases/UC004-in-development-in-progress.md) | in development |" in rendered_idx
    assert "| UC007 (Ready Verified Flow) | P1 | [Ready Verified Flow](use-cases/UC007-ready-verified-flow.md) | verified |" in rendered_idx
    assert "| UC008 (Ready Failing Flow) | P1 | [Ready Failing Flow](use-cases/UC008-ready-failing-flow.md) | failing |" in rendered_idx
    assert "| UC009 (Ready Partial Flow) | P1 | [Ready Partial Flow](use-cases/UC009-ready-partial-flow.md) | partial |" in rendered_idx
    assert "| UC010 (Ready Untested Explicit) | P1 | [Ready Untested Explicit](use-cases/UC010-ready-untested-explicit.md) | untested |" in rendered_idx
    assert "| UC011 (Ready Untested Missing Verdict) | P1 | [Ready Untested Missing Verdict](use-cases/UC011-ready-untested-missing-verdict.md) | untested (deprecated) |" in rendered_idx
    assert "| UC012 (Ready Revalidation Pending) | P1 | [Ready Revalidation Pending](use-cases/UC012-ready-revalidation-pending.md) | ready (revalidation pending) |" in rendered_idx


def test_17_5_migrate_lifecycle_mapping_verdict_fill_log_preserved_idempotent_rollback_and_validate(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 17.5 (deliverables 2, 5, 6):
    - `use-cases migrate-lifecycle`: preview by default, `--apply --expect-plan-hash <h>`.
    - Mapping: `draft -> proposed`; `active`, `verified`, `failing`, `partial -> approved`; `deprecated -> deprecated`.
    - Verdict backfill/fix: `verified -> pass`, `failing -> fail`, `partial -> partial` when `last-verdict` is missing
      or disagrees, and reported in preview/apply output.
    - `## AI Validation Log` and every other body line are kept byte-for-byte.
    - Snapshot written under `tasks/_reviews/migrate-lifecycle-<timestamp>/` before applying.
    - Unknown `status` values stop the apply (fail-closed) and are listed.
    - Atomic apply with rollback on injected write failure.
    - Idempotent second run.
    - `validate`: unmigrated use case (without `approval`) is a warning, not an error.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    log_payload = (
        "\n### [2026-10-25 17:00 UTC] AI Validation by campaign-runner\n"
        "- **Verdict:** `FAIL`\n"
        "- **Summary:** Probe failed with exit code 1\n"
        "- **Evidence:**\n"
        "```\n$ pytest -q\n1 failed\n```\n"
        "- **Gaps Found:**\n"
        "  - Assertion mismatch in line 42\n"
    )

    def _write_legacy_uc(uc_id: str, status_val: str, last_verdict_val: str = "-", extra_log: str = "") -> pathlib.Path:
        p = tasks_dir / "use-cases" / f"{uc_id}-legacy.md"
        p.write_text(
            f"# {uc_id} - Legacy {status_val}\n\n"
            f"- id: {uc_id}\n"
            f"- title: Legacy {status_val}\n"
            f"- actor: User\n"
            f"- status: {status_val}\n"
            f"- priority: P1\n"
            f"- linked-tasks: -\n"
            f"- verification-type: automated-probe\n"
            f"- last-tested: 2026-10-25\n"
            f"- last-verdict: {last_verdict_val}\n"
            f"- short: Legacy {uc_id}\n\n"
            "## Description & Business Value\nExact body text line 1.\nExact body text line 2.\n\n"
            "## Preconditions\n- Precondition A.\n\n"
            "## Scenario / Interaction Steps\n1. Step one.\n2. Step two.\n\n"
            "## Automated Verification Command\n```bash\npytest -q\n```\n\n"
            "## Acceptance Criteria\n- [x] Criterion 1.\n- [ ] Criterion 2.\n\n"
            f"## AI Validation Log{extra_log}",
            encoding="utf-8",
        )
        return p

    p_uc1 = _write_legacy_uc("UC001", "draft", "-")
    p_uc2 = _write_legacy_uc("UC002", "active", "-")
    p_uc3 = _write_legacy_uc("UC003", "verified", "-", extra_log=log_payload)  # missing last-verdict -> fill pass
    p_uc4 = _write_legacy_uc("UC004", "failing", "pass", extra_log=log_payload)  # disagreeing last-verdict -> fix fail
    p_uc5 = _write_legacy_uc("UC005", "partial", "-")  # missing last-verdict -> fill partial
    p_uc6 = _write_legacy_uc("UC006", "deprecated", "-")

    # 1. Validate on unmigrated tree: missing `approval` is a warning, NOT an error (exit 0)
    res_val_before = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val_before.returncode == 0
    val_before = json.loads(res_val_before.stdout)
    assert val_before["ok"] is True
    assert val_before["errors"] == []
    assert sum(1 for w in val_before["warnings"] if "missing 'approval' header field" in w) == 6

    # 2. Inject an unknown status UC007 -> migrate-lifecycle refuses (fail-closed) and lists UC007
    p_uc7 = _write_legacy_uc("UC007", "bogus-status", "-")
    res_bad = run_cli("use-cases", "migrate-lifecycle", "--tasks-dir", str(tasks_dir), "--json")
    assert res_bad.returncode == 1
    bad_data = json.loads(res_bad.stdout)
    assert bad_data["ok"] is False
    assert bad_data["applied"] is False
    assert [u["use_case_id"] for u in bad_data["unknown_statuses"]] == ["UC007"]
    assert bad_data["unknown_statuses"][0]["status"] == "bogus-status"
    p_uc7.unlink()

    # 3. Preview by default writes nothing and reports mappings + verdict backfills
    orig_bytes = {p.name: p.read_bytes() for p in (p_uc1, p_uc2, p_uc3, p_uc4, p_uc5, p_uc6)}
    res_prev = run_cli("use-cases", "migrate-lifecycle", "--tasks-dir", str(tasks_dir), "--json")
    assert res_prev.returncode == 0
    prev_data = json.loads(res_prev.stdout)
    assert prev_data["ok"] is True
    assert prev_data["applied"] is False
    assert prev_data["dry_run"] is True
    assert prev_data["files_changed_count"] == 6
    assert prev_data["counts_by_old_status"] == {
        "draft": 1,
        "active": 1,
        "verified": 1,
        "failing": 1,
        "partial": 1,
        "deprecated": 1,
    }
    assert prev_data["counts_by_new_approval"] == {
        "proposed": 1,
        "approved": 4,
        "deprecated": 1,
    }
    assert [v["use_case_id"] for v in prev_data["verdict_updates"]] == ["UC003", "UC004", "UC005"]
    for p in (p_uc1, p_uc2, p_uc3, p_uc4, p_uc5, p_uc6):
        assert p.read_bytes() == orig_bytes[p.name]

    # 4. Inject failure midway through atomic write -> verify rollback restores all files and removes no data
    real_atomic_write = te._atomic_write_text
    write_calls: list[pathlib.Path] = []

    def _failing_write(path: pathlib.Path, content: str, encoding: str = "utf-8") -> None:
        # Allow snapshot/manifest writes under _reviews, fail on the 3rd use-case file write
        if "use-cases" in path.parts:
            write_calls.append(path)
            if len(write_calls) == 3:
                raise OSError("Simulated disk failure during migrate-lifecycle")
        real_atomic_write(path, content, encoding=encoding)

    monkeypatch.setattr(te, "_atomic_write_text", _failing_write)
    with pytest.raises(OSError, match="Simulated disk failure"):
        te.migrate_use_case_lifecycle(tasks_dir, dry_run=False, expect_plan_hash=prev_data["plan_hash"])
    monkeypatch.setattr(te, "_atomic_write_text", real_atomic_write)

    for p in (p_uc1, p_uc2, p_uc3, p_uc4, p_uc5, p_uc6):
        assert p.read_bytes() == orig_bytes[p.name]

    # 5. Apply migration with --apply --expect-plan-hash
    res_app = run_cli(
        "use-cases", "migrate-lifecycle", "--tasks-dir", str(tasks_dir),
        "--apply", "--expect-plan-hash", prev_data["plan_hash"], "--json",
    )
    assert res_app.returncode == 0, res_app.stdout + res_app.stderr
    app_data = json.loads(res_app.stdout)
    assert app_data["ok"] is True
    assert app_data["applied"] is True
    assert app_data["changed"] is True

    # Verify snapshot under tasks/_reviews/migrate-lifecycle-<ts>/
    snap_dir = pathlib.Path(app_data["snapshot_dir"])
    assert snap_dir.is_dir()
    assert snap_dir.parent == tasks_dir / "_reviews"
    assert snap_dir.name.startswith("migrate-lifecycle-")
    manifest = json.loads(pathlib.Path(app_data["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["files_count"] == 6
    for p in (p_uc1, p_uc2, p_uc3, p_uc4, p_uc5, p_uc6):
        assert (snap_dir / "use-cases" / p.name).read_bytes() == orig_bytes[p.name]

    # Verify header positions, approval values, last-verdict backfills, and byte-for-byte body/log preservation
    expected_after = {
        p_uc1: ("proposed", "-"),
        p_uc2: ("approved", "-"),
        p_uc3: ("approved", "pass"),
        p_uc4: ("approved", "fail"),
        p_uc5: ("approved", "partial"),
        p_uc6: ("deprecated", "-"),
    }
    for p, (exp_app, exp_verdict) in expected_after.items():
        after_text = p.read_text(encoding="utf-8")
        orig_text = orig_bytes[p.name].decode("utf-8")
        assert f"- actor: User\n- approval: {exp_app}\n- priority: P1\n" in after_text
        assert "- status:" not in after_text
        assert f"- last-verdict: {exp_verdict}\n" in after_text
        # Everything from `## Description & Business Value` onwards (including `## AI Validation Log`) is identical byte-for-byte
        orig_body = orig_text.split("## Description & Business Value", 1)[1]
        after_body = after_text.split("## Description & Business Value", 1)[1]
        assert after_body == orig_body

    # 6. Validate after migration: 0 errors, 0 missing-approval warnings
    res_val_after = json.loads(run_cli("validate", "--tasks-dir", str(tasks_dir), "--json").stdout)
    assert res_val_after["ok"] is True
    assert res_val_after["errors"] == []
    assert not any("missing 'approval' header field" in w for w in res_val_after["warnings"])

    # 7. Idempotent second run
    res_prev2 = json.loads(run_cli("use-cases", "migrate-lifecycle", "--tasks-dir", str(tasks_dir), "--json").stdout)
    assert res_prev2["ok"] is True
    assert res_prev2["files_changed_count"] == 0
    assert res_prev2["plan"] == []

    res_app2 = json.loads(
        run_cli(
            "use-cases", "migrate-lifecycle", "--tasks-dir", str(tasks_dir),
            "--apply", "--expect-plan-hash", res_prev2["plan_hash"], "--json",
        ).stdout
    )
    assert res_app2["ok"] is True
    assert res_app2["applied"] is True
    assert res_app2["changed"] is False


# ===========================================================================
# Task 17.6: Validation Only on Ready Use Cases, Campaign Readiness & git-code-rag Shape
# ===========================================================================

def test_17_6_validate_refusal_exit_2_force_override_and_event(tmp_path: pathlib.Path) -> None:
    """Task 17.6 (deliverable 1):
    - `use-cases validate <UC>` refuses with exit code 2 and message 'not ready (N/M tasks done)'
      when stage is `draft`, `planned`, or `in development` (and when all linked tasks are dropped -> `draft` `0/0`).
    - `--force` overrides the refusal, executes the probe, records the validation as forced in `## AI Validation Log`,
      and emits a `use_case.validated` event with `forced: true`.
    - When all non-dropped linked tasks are delivered/verified/done, `use-cases validate` runs without `--force`
      and emits `use_case.validated` with `forced: false`.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "01-core").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # UC001: draft (no linked tasks -> 0/0)
    # UC002: planned (0/2 tasks done)
    # UC003: in development (1/2 tasks done, 1 dropped ignored)
    # UC004: ready (2/2 tasks done, 1 dropped ignored)
    for ucid, title in (
        ("UC001", "Draft No Tasks"),
        ("UC002", "Planned Zero Done"),
        ("UC003", "In Dev One Of Two Done"),
        ("UC004", "Ready Two Of Two Done"),
    ):
        run_cli(
            "use-cases", "create",
            "--id", ucid,
            "--title", title,
            "--actor", "Operator",
            "--approval", "approved",
            "--verification-command", f"echo 'PROBE_{ucid}'",
            "--tasks-dir", str(tasks_dir),
            "--json",
        )

    (tasks_dir / "01-core" / "plan.md").write_text(
        "# 01 — Core Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Open task A\n\n"
        "- **Status:** `open` · **Short:** Open A · **Size:** S · **Depends on:** - · **Use cases:** UC002\n"
        "- **Goal:** Open A.\n\n"
        "### 01.2 - Waiting task B\n\n"
        "- **Status:** `waiting` · **Short:** Waiting B · **Size:** S · **Depends on:** - · **Use cases:** UC002\n"
        "- **Goal:** Waiting B.\n\n"
        "### 01.3 - In progress task C\n\n"
        "- **Status:** `in progress` · **Short:** In progress C · **Size:** S · **Depends on:** - · **Use cases:** UC003\n"
        "- **Goal:** In progress C.\n\n"
        "### 01.4 - Delivered task D\n\n"
        "- **Status:** `delivered` · **Short:** Delivered D · **Size:** S · **Depends on:** - · **Use cases:** UC003, UC004\n"
        "- **Goal:** Delivered D.\n\n"
        "### 01.5 - Done task E\n\n"
        "- **Status:** `done` · **Short:** Done E · **Size:** S · **Depends on:** - · **Use cases:** UC004\n"
        "- **Goal:** Done E.\n\n"
        "### 01.6 - Dropped task F\n\n"
        "- **Status:** `dropped` · **Short:** Dropped F · **Size:** S · **Depends on:** - · **Use cases:** UC003, UC004\n"
        "- **Goal:** Dropped F.\n",
        encoding="utf-8",
    )

    # 1. Refusal on UC001 (draft, 0/0 tasks done) -> exit 2, both JSON and text
    res_uc1_json = run_cli("use-cases", "validate", "UC001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_uc1_json.returncode == 2
    d_uc1 = json.loads(res_uc1_json.stdout)
    assert d_uc1["ok"] is False
    assert d_uc1["reason"] == "not_ready"
    assert d_uc1["stage"] == "draft"
    assert d_uc1["tasks_done"] == 0
    assert d_uc1["tasks_total"] == 0
    assert "not ready (0/0 tasks done" in d_uc1["error"]

    res_uc1_txt = run_cli("use-cases", "validate", "UC001", "--tasks-dir", str(tasks_dir))
    assert res_uc1_txt.returncode == 2
    assert "not ready (0/0 tasks done" in res_uc1_txt.stderr

    # 2. Refusal on UC002 (planned, 0/2 tasks done) -> exit 2
    res_uc2_json = run_cli("use-cases", "validate", "UC002", "--tasks-dir", str(tasks_dir), "--json")
    assert res_uc2_json.returncode == 2
    d_uc2 = json.loads(res_uc2_json.stdout)
    assert d_uc2["ok"] is False
    assert d_uc2["stage"] == "planned"
    assert d_uc2["tasks_done"] == 0
    assert d_uc2["tasks_total"] == 2
    assert "not ready (0/2 tasks done" in d_uc2["error"]

    # 3. Refusal on UC003 (in development, 1/2 tasks done; dropped task 01.6 ignored) -> exit 2
    res_uc3_json = run_cli("use-cases", "validate", "UC003", "--tasks-dir", str(tasks_dir), "--json")
    assert res_uc3_json.returncode == 2
    d_uc3 = json.loads(res_uc3_json.stdout)
    assert d_uc3["ok"] is False
    assert d_uc3["stage"] == "in development"
    assert d_uc3["tasks_done"] == 1
    assert d_uc3["tasks_total"] == 2
    assert "not ready (1/2 tasks done" in d_uc3["error"]

    # Verify UC003 file was NOT touched by refused validation
    uc3_path = next((tasks_dir / "use-cases").glob("UC003-*.md"))
    assert "AI Validation by" not in uc3_path.read_text(encoding="utf-8")

    # 4. Force override on UC003 (--force) -> exit 0, recorded as forced in log and event
    res_uc3_force = run_cli("use-cases", "validate", "UC003", "--force", "--tasks-dir", str(tasks_dir), "--json")
    assert res_uc3_force.returncode == 0
    d_uc3_force = json.loads(res_uc3_force.stdout)
    assert d_uc3_force["ok"] is True
    assert d_uc3_force["forced"] is True
    assert d_uc3_force["verdict"] == "pass"
    assert "(forced)" in d_uc3_force["summary"]

    uc3_text_after = uc3_path.read_text(encoding="utf-8")
    assert "(forced)" in uc3_text_after
    assert "- **Forced:** `true`" in uc3_text_after

    # 5. Ready UC004 (2/2 non-dropped tasks done) -> runs without --force, exit 0, forced=False
    res_uc4 = run_cli("use-cases", "validate", "UC004", "--tasks-dir", str(tasks_dir), "--json")
    assert res_uc4.returncode == 0
    d_uc4 = json.loads(res_uc4.stdout)
    assert d_uc4["ok"] is True
    assert d_uc4["forced"] is False
    assert d_uc4["verdict"] == "pass"
    assert d_uc4["stage"] == "verified"
    assert d_uc4["tasks_done"] == 2
    assert d_uc4["tasks_total"] == 2

    # Check emitted `use_case.validated` events
    import orchestration_events
    evs = orchestration_events.read_events(tmp_path, types=["use_case.validated"])
    assert len(evs) >= 2
    ev_uc3 = next(e for e in evs if e["subject"] == "UC003")
    assert ev_uc3["payload"]["forced"] is True
    assert ev_uc3["payload"]["verdict"] == "pass"
    ev_uc4 = next(e for e in evs if e["subject"] == "UC004")
    assert ev_uc4["payload"]["forced"] is False
    assert ev_uc4["payload"]["verdict"] == "pass"


def test_17_6_campaign_2_ready_2_draft_1_in_dev_and_readiness_denominator(tmp_path: pathlib.Path) -> None:
    """Task 17.6 (Spec §7 item 4 + readiness denominator):
    - Campaign on 2 ready + 2 draft + 1 in-development use cases: only the 2 ready are probed;
      others listed under 'Not ready' with N/M and stage, untouched on disk.
    - Readiness score excludes `untested` from the denominator (and reports both evaluated and in-scope).
       specifically tests the 24 passed, 1 failed, 7 untested shape -> 24/25 = 96.0% evaluated (and 24/32 = 75.0% in-scope).
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "01-core").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    marker_draft = tmp_path / "draft_ran.marker"
    marker_indev = tmp_path / "indev_ran.marker"

    # 2 ready (UC001 pass, UC002 fail)
    run_cli(
        "use-cases", "create", "--id", "UC001", "--title", "Ready Passing",
        "--approval", "approved", "--verification-command", "echo 'READY_1'",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    run_cli(
        "use-cases", "create", "--id", "UC002", "--title", "Ready Failing",
        "--approval", "approved", "--verification-command", "exit 1",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    # 2 draft (no linked tasks) — commands touch marker files if ever executed
    run_cli(
        "use-cases", "create", "--id", "UC003", "--title", "Draft One",
        "--approval", "proposed", "--verification-command", f"touch {marker_draft} && exit 1",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    run_cli(
        "use-cases", "create", "--id", "UC004", "--title", "Draft Two",
        "--approval", "approved", "--verification-command", f"touch {marker_draft} && exit 1",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    # 1 in-development (1 of 2 linked tasks delivered)
    run_cli(
        "use-cases", "create", "--id", "UC005", "--title", "In Dev Flow",
        "--approval", "approved", "--verification-command", f"touch {marker_indev} && exit 1",
        "--tasks-dir", str(tasks_dir), "--json",
    )

    (tasks_dir / "01-core" / "plan.md").write_text(
        "# 01 — Core Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Delivered task\n\n"
        "- **Status:** `delivered` · **Short:** Delivered · **Size:** S · **Depends on:** - · **Use cases:** UC001, UC002, UC005\n"
        "- **Goal:** Delivered.\n\n"
        "### 01.2 - Open task\n\n"
        "- **Status:** `open` · **Short:** Open · **Size:** S · **Depends on:** - · **Use cases:** UC005\n"
        "- **Goal:** Open.\n",
        encoding="utf-8",
    )

    uc3_before = next((tasks_dir / "use-cases").glob("UC003-*.md")).read_bytes()
    uc4_before = next((tasks_dir / "use-cases").glob("UC004-*.md")).read_bytes()
    uc5_before = next((tasks_dir / "use-cases").glob("UC005-*.md")).read_bytes()

    res_camp = run_cli("use-cases", "campaign", "--tasks-dir", str(tasks_dir), "--json")
    assert res_camp.returncode == 1  # UC002 failed
    camp = json.loads(res_camp.stdout)
    assert camp["ok"] is True
    assert camp["total"] == 2
    assert [r["id"] for r in camp["results"]] == ["UC001", "UC002"]
    assert camp["passed"] == 1
    assert camp["failed"] == 1
    assert camp["untested"] == 0
    assert camp["not_ready_count"] == 3
    assert [u["id"] for u in camp["not_ready"]] == ["UC003", "UC004", "UC005"]
    assert camp["not_ready"][0]["progress"] == "0/0"
    assert camp["not_ready"][0]["stage"] == "draft"
    assert camp["not_ready"][1]["progress"] == "0/0"
    assert camp["not_ready"][1]["stage"] == "draft"
    assert camp["not_ready"][2]["progress"] == "1/2"
    assert camp["not_ready"][2]["stage"] == "in development"

    # Non-ready probes never executed and their files are byte-for-byte untouched
    assert not marker_draft.exists()
    assert not marker_indev.exists()
    assert next((tasks_dir / "use-cases").glob("UC003-*.md")).read_bytes() == uc3_before
    assert next((tasks_dir / "use-cases").glob("UC004-*.md")).read_bytes() == uc4_before
    assert next((tasks_dir / "use-cases").glob("UC005-*.md")).read_bytes() == uc5_before

    report_text = pathlib.Path(camp["report_file"]).read_text(encoding="utf-8")
    assert "## Not ready" in report_text
    assert "- **UC003**: Draft One (Not ready (0/0), stage: `draft`)" in report_text
    assert "- **UC004**: Draft Two (Not ready (0/0), stage: `draft`)" in report_text
    assert "- **UC005**: In Dev Flow (Not ready (1/2), stage: `in development`)" in report_text


def test_17_6_git_code_rag_shape_fixture(tmp_path: pathlib.Path) -> None:
    """Task 17.6 (corrected deliverable 6):
    Reproduces the git-code-rag shape in a self-contained fixture:
    - 4 use cases (UC001..UC004) with all linked tasks done and verdict pass;
    - 1 use case (UC005) with `last-verdict: fail` (or legacy `status: failing`) and NO linked tasks:
      must have derived stage `draft`, must NOT be probed, and must be listed under `Not ready (0/0)`;
    - 3 use cases (UC006..UC008) with linked tasks open (`0/1`, `0/2`, `0/3` tasks done):
      must be listed under `Not ready (0/N)` and must NOT be probed;
    - Assert the campaign probes ONLY the 4 ready use cases.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "01-rag").mkdir(parents=True)
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    forbidden_marker = tmp_path / "forbidden_probe_ran.marker"

    def _write_uc(uc_id: str, title: str, approval: str, last_verdict: str, cmd: str) -> pathlib.Path:
        p = tasks_dir / "use-cases" / f"{uc_id}-{title.lower().replace(' ', '-')}.md"
        p.write_text(
            f"# {uc_id} - {title}\n\n"
            f"- id: {uc_id}\n"
            f"- title: {title}\n"
            f"- actor: Developer\n"
            f"- approval: {approval}\n"
            f"- priority: P1\n"
            f"- linked-tasks: -\n"
            f"- verification-type: automated-probe\n"
            f"- last-tested: 2026-10-27\n"
            f"- last-verdict: {last_verdict}\n"
            f"- short: {title}\n\n"
            "## Description & Business Value\nDesc.\n\n"
            "## Preconditions\n- None.\n\n"
            "## Scenario / Interaction Steps\n1. Step.\n\n"
            f"## Automated Verification Command\n```bash\n{cmd}\n```\n\n"
            "## Acceptance Criteria\n- [x] Criterion.\n\n"
            "## AI Validation Log\n",
            encoding="utf-8",
        )
        return p

    # 4 use cases with all linked tasks done and verdict pass
    for i in range(1, 5):
        _write_uc(f"UC00{i}", f"Ready Passing Flow {i}", "approved", "pass", f"echo 'PASS_UC00{i}'")

    # 1 failing with no linked tasks (reproducing git-code-rag UC031 which was marked failing with no tasks)
    p_uc5 = _write_uc(
        "UC005",
        "Unimplemented Post V0 Failing",
        "approved",
        "fail",
        f"touch {forbidden_marker} && exit 1",
    )

    # 3 use cases with linked tasks open (Not ready, 0/N)
    p_uc6 = _write_uc("UC006", "Planned One Open Task", "approved", "-", f"touch {forbidden_marker} && exit 1")
    p_uc7 = _write_uc("UC007", "Planned Two Open Tasks", "proposed", "-", f"touch {forbidden_marker} && exit 1")
    p_uc8 = _write_uc("UC008", "Planned Three Open Tasks", "approved", "-", f"touch {forbidden_marker} && exit 1")

    (tasks_dir / "01-rag" / "plan.md").write_text(
        "# 01 — RAG Initiative\n\n"
        "## Tasks\n\n"
        "### 01.1 - Done task 1\n\n"
        "- **Status:** `done` · **Short:** Done 1 · **Size:** S · **Depends on:** - · **Use cases:** UC001, UC002\n"
        "- **Goal:** Done 1.\n\n"
        "### 01.2 - Done task 2\n\n"
        "- **Status:** `done` · **Short:** Done 2 · **Size:** S · **Depends on:** - · **Use cases:** UC002, UC003, UC004\n"
        "- **Goal:** Done 2.\n\n"
        "### 01.3 - Open task A\n\n"
        "- **Status:** `open` · **Short:** Open A · **Size:** S · **Depends on:** - · **Use cases:** UC006, UC007, UC008\n"
        "- **Goal:** Open A.\n\n"
        "### 01.4 - Open task B\n\n"
        "- **Status:** `open` · **Short:** Open B · **Size:** S · **Depends on:** - · **Use cases:** UC007, UC008\n"
        "- **Goal:** Open B.\n\n"
        "### 01.5 - Open task C\n\n"
        "- **Status:** `open` · **Short:** Open C · **Size:** S · **Depends on:** - · **Use cases:** UC008\n"
        "- **Goal:** Open C.\n",
        encoding="utf-8",
    )

    # Verify UC005 stage is `draft` (never shown as `failing`)
    uc5_show = json.loads(run_cli("use-cases", "show", "UC005", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc5_show["stage"] == "draft"
    assert uc5_show["status"] == "draft"
    assert uc5_show["last_verdict"] == "fail"

    not_ready_bytes_before = {p.name: p.read_bytes() for p in (p_uc5, p_uc6, p_uc7, p_uc8)}

    # Run campaign
    res_camp = run_cli("use-cases", "campaign", "--tasks-dir", str(tasks_dir), "--json")
    assert res_camp.returncode == 0, res_camp.stdout + res_camp.stderr
    camp = json.loads(res_camp.stdout)
    assert camp["ok"] is True

    # Only the 4 ready use cases are probed
    assert camp["total"] == 4
    assert camp["evaluated"] == 4
    assert camp["passed"] == 4
    assert camp["failed"] == 0
    assert camp["untested"] == 0
    assert camp["readiness_score"] == 100.0
    assert [r["id"] for r in camp["results"]] == ["UC001", "UC002", "UC003", "UC004"]

    # The 1 draft-with-fail-verdict + 3 open-task use cases are under Not ready
    assert camp["not_ready_count"] == 4
    not_ready_by_id = {u["id"]: u for u in camp["not_ready"]}
    assert set(not_ready_by_id.keys()) == {"UC005", "UC006", "UC007", "UC008"}
    assert not_ready_by_id["UC005"]["stage"] == "draft"
    assert not_ready_by_id["UC005"]["progress"] == "0/0"
    assert not_ready_by_id["UC006"]["stage"] == "planned"
    assert not_ready_by_id["UC006"]["progress"] == "0/1"
    assert not_ready_by_id["UC007"]["stage"] == "planned"
    assert not_ready_by_id["UC007"]["progress"] == "0/2"
    assert not_ready_by_id["UC008"]["stage"] == "planned"
    assert not_ready_by_id["UC008"]["progress"] == "0/3"

    # None of UC005..UC008 were probed or modified on disk
    assert not forbidden_marker.exists()
    for p in (p_uc5, p_uc6, p_uc7, p_uc8):
        assert p.read_bytes() == not_ready_bytes_before[p.name]

    # Verify markdown report lists them under ## Not ready with 0/N and stage
    report_text = pathlib.Path(camp["report_file"]).read_text(encoding="utf-8")
    assert "- **Readiness Score:** `100.0%` (4/4 evaluated, 4/4 in-scope Use Cases Verified)" in report_text
    assert "## Not ready" in report_text
    assert "- **UC005**: Unimplemented Post V0 Failing (Not ready (0/0), stage: `draft`)" in report_text
    assert "- **UC006**: Planned One Open Task (Not ready (0/1), stage: `planned`)" in report_text
    assert "- **UC007**: Planned Two Open Tasks (Not ready (0/2), stage: `planned`)" in report_text
    assert "- **UC008**: Planned Three Open Tasks (Not ready (0/3), stage: `planned`)" in report_text


def _write_17_7_use_case(
    tasks_dir: pathlib.Path,
    uc_id: str,
    *,
    title: str,
    approval: str = "approved",
    linked_tasks: str = "-",
    last_tested: str = "2026-10-20",
    last_verdict: str = "-",
    verification_command: str = "python3 -c 'print(\"ok\")'",
) -> pathlib.Path:
    uc_dir = tasks_dir / "use-cases"
    uc_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "uc"
    p = uc_dir / f"{uc_id}-{slug}.md"
    p.write_text(
        f"# {uc_id} — {title}\n\n"
        f"- id: {uc_id}\n"
        f"- title: {title}\n"
        f"- actor: Operator\n"
        f"- approval: {approval}\n"
        f"- priority: P1\n"
        f"- linked-tasks: {linked_tasks}\n"
        f"- verification-type: automated-probe\n"
        f"- last-tested: {last_tested}\n"
        f"- last-verdict: {last_verdict}\n"
        f"- short: {title[:30]}\n\n"
        f"## Description\n\n{title} description.\n\n"
        f"## Preconditions\n\n- Ready.\n\n"
        f"## Main Scenario\n\n1. Run probe.\n\n"
        f"## Acceptance Criteria\n\n- [ ] Passes.\n\n"
        f"## Automated Verification Command\n\n```bash\n{verification_command}\n```\n\n"
        f"## AI Validation Log\n\n_No validations recorded yet._\n",
        encoding="utf-8",
    )
    return p


def _write_17_7_task(
    path: pathlib.Path,
    *,
    task_id: str,
    title: str,
    category: str = "features",
    state: str = "open",
    executor: str = "kilo",
    use_cases: str = "-",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {task_id} {title}\n\n"
        f"- id: {task_id}\n"
        f"- title: {title}\n"
        f"- category: {category}\n"
        f"- priority: P1\n"
        f"- priority-reason: Needed for 17.7\n"
        f"- next-up: yes\n"
        f"- state: {state}\n"
        f"- executor: {executor}\n"
        f"- depends-on: -\n"
        f"- decider: -\n"
        f"- sources: spec.md\n"
        f"- paths: src/app.py\n"
        f"- handoff: Read task, execute steps, verify.\n"
        f"- profile: bulk-execution\n"
        f"- verification-mode: cross-agent\n"
        f"- verifier: -\n"
        f"- use-cases: {use_cases}\n\n"
        f"## Goal\n\nImplement {title}.\n\n"
        f"## Steps\n\n1. Write `src/app.py`.\n\n"
        f"## Verification\n\n- `pytest` passes.\n",
        encoding="utf-8",
    )


def test_17_7_reopen_bounce_redeliver_sets_revalidation_pending_and_validate_clears(
    tmp_path: pathlib.Path,
) -> None:
    """Task 17.7 Deliverables 1 & 2:
    - reopen/bounce/redeliver of a task linked to a verified use case sets `revalidation: pending`
      (targeted header edit, files byte-identical except the header line), emits `use_case.revalidation_requested`,
      and lists in `use-cases queue` (text and --json) with triggering task and date, oldest first.
    - `use-cases validate` (pass or fail) and `use-cases campaign` clear `revalidation: pending`.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "features").mkdir(parents=True)
    (tasks_dir / "01-core").mkdir(parents=True)

    # Create 3 use cases: UC001 (linked to T001), UC002 (linked to T002), UC003 (linked to 01.1)
    p_uc1 = _write_17_7_use_case(
        tasks_dir,
        "UC001",
        title="Verified UC One",
        approval="approved",
        linked_tasks="T001",
        last_verdict="pass",
        verification_command="python3 -c 'print(\"uc1 pass\")'",
    )
    p_uc2 = _write_17_7_use_case(
        tasks_dir,
        "UC002",
        title="Verified UC Two",
        approval="approved",
        linked_tasks="T002",
        last_verdict="pass",
        verification_command="python3 -c 'import sys; sys.exit(1)'",
    )
    p_uc3 = _write_17_7_use_case(
        tasks_dir,
        "UC003",
        title="Verified UC Three",
        approval="approved",
        linked_tasks="01.1",
        last_verdict="pass",
        verification_command="python3 -c 'print(\"uc3 pass\")'",
    )

    # Create emergent task T001 (in done, state=done) linked to UC001
    t1_done = tasks_dir / "done" / "features" / "T001-auth-flow.md"
    _write_17_7_task(
        t1_done,
        task_id="T001",
        title="Auth Flow",
        category="features",
        state="done",
        executor="kilo",
        use_cases="UC001",
    )

    # Create emergent task T002 (state=delivered) linked to UC002
    t2_active = tasks_dir / "features" / "T002-token-refresh.md"
    _write_17_7_task(
        t2_active,
        task_id="T002",
        title="Token Refresh",
        category="features",
        state="delivered",
        executor="kilo",
        use_cases="UC002",
    )

    # Create initiative task 01.1 (state=delivered) linked to UC003
    plan_p = tasks_dir / "01-core" / "plan.md"
    plan_p.write_text(
        "# 01 — Core Initiative\n\n"
        "- **Status:** `in progress`\n\n"
        "## Tasks\n\n"
        "### 01.1 - Core Redeliver Task\n\n"
        "- **Status:** `delivered` · **Short:** Core Redeliver · **Size:** S · **Depends on:** - · **Use cases:** UC003\n"
        "- **Goal:** Core task.\n",
        encoding="utf-8",
    )

    # Confirm all 3 use cases start in stage `verified` and queue is empty
    for ucid in ("UC001", "UC002", "UC003"):
        u_show = json.loads(run_cli("use-cases", "show", ucid, "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
        assert u_show["stage"] == "verified"
        assert u_show["revalidation"] is None

    res_q0 = run_cli("use-cases", "queue", "--tasks-dir", str(tasks_dir), "--json")
    assert res_q0.returncode == 0
    assert json.loads(res_q0.stdout)["count"] == 0
    res_q0_txt = run_cli("use-cases", "queue", "--tasks-dir", str(tasks_dir))
    assert "No use cases pending revalidation" in res_q0_txt.stdout

    uc1_before = p_uc1.read_text(encoding="utf-8")
    uc2_before = p_uc2.read_text(encoding="utf-8")
    uc3_before = p_uc3.read_text(encoding="utf-8")

    # 1. Bounce T002 (`delivered -> bounced`) -> UC002 gets `revalidation: pending` (oldest in queue!)
    res_bounce = run_cli(
        "transition", "T002", "bounced",
        "--reason", "Regression in token refresh",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_bounce.returncode == 0, res_bounce.stdout + res_bounce.stderr
    uc2_after = p_uc2.read_text(encoding="utf-8")
    assert "- revalidation: pending\n" in uc2_after
    # File is byte-identical except the `- revalidation: pending` header line
    assert uc2_after.replace("- revalidation: pending\n", "") == uc2_before

    # 2. Reopen T001 (`done -> open`) -> UC001 gets `revalidation: pending` (second in queue)
    res_reopen = run_cli(
        "reopen", "T001",
        "--reason", "Reopen auth flow",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_reopen.returncode == 0, res_reopen.stdout + res_reopen.stderr
    uc1_after = p_uc1.read_text(encoding="utf-8")
    assert "- revalidation: pending\n" in uc1_after
    assert uc1_after.replace("- revalidation: pending\n", "") == uc1_before

    # 3. Redeliver 01.1 (`delivered -> in progress -> delivered`) -> UC003 gets `revalidation: pending` (third in queue)
    assert run_cli("transition", "01.1", "in progress", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    res_redeliver = run_cli("transition", "01.1", "delivered", "--tasks-dir", str(tasks_dir), "--json")
    assert res_redeliver.returncode == 0, res_redeliver.stdout + res_redeliver.stderr
    uc3_after = p_uc3.read_text(encoding="utf-8")
    assert "- revalidation: pending\n" in uc3_after
    assert uc3_after.replace("- revalidation: pending\n", "") == uc3_before

    uc3_show = json.loads(run_cli("use-cases", "show", "UC003", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc3_show["stage"] == "ready (revalidation pending)"
    assert uc3_show["revalidation"] == "pending"

    # Check emitted `use_case.revalidation_requested` events
    ws_events = _read_ws_events(tmp_path)
    reval_evs = [e for e in ws_events if e["type"] == "use_case.revalidation_requested"]
    assert len(reval_evs) == 3
    assert [e["data"]["use_case_id"] for e in reval_evs] == ["UC002", "UC001", "UC003"]
    assert [e["data"]["task_id"] for e in reval_evs] == ["T002", "T001", "01.1"]
    assert "bounced" in reval_evs[0]["data"]["transition"]
    assert "open" in reval_evs[1]["data"]["transition"]
    assert "delivered" in reval_evs[2]["data"]["transition"]

    # Check `ai-orch tasks use-cases queue` (--json and text) lists them oldest first: UC002, UC001, UC003
    res_q = run_cli("use-cases", "queue", "--tasks-dir", str(tasks_dir), "--json")
    assert res_q.returncode == 0
    q_data = json.loads(res_q.stdout)
    assert q_data["ok"] is True
    assert q_data["count"] == 3
    assert [item["id"] for item in q_data["queue"]] == ["UC002", "UC001", "UC003"]
    assert [item["triggering_task"] for item in q_data["queue"]] == ["T002", "T001", "01.1"]
    today_iso = datetime.date.today().isoformat()
    assert all(item["date"] == today_iso for item in q_data["queue"])

    res_q_txt = run_cli("use-cases", "queue", "--tasks-dir", str(tasks_dir))
    assert res_q_txt.returncode == 0
    assert "Use Case Revalidation Queue (3):" in res_q_txt.stdout
    assert "UC002" in res_q_txt.stdout and "T002" in res_q_txt.stdout
    assert res_q_txt.stdout.index("UC002") < res_q_txt.stdout.index("UC001") < res_q_txt.stdout.index("UC003")

    # 4. Validate UC003 (passes) -> clears `revalidation: pending` and returns to `verified`
    res_v3 = run_cli("use-cases", "validate", "UC003", "--tasks-dir", str(tasks_dir), "--json")
    assert res_v3.returncode == 0, res_v3.stdout + res_v3.stderr
    assert "revalidation:" not in p_uc3.read_text(encoding="utf-8")
    uc3_show2 = json.loads(run_cli("use-cases", "show", "UC003", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc3_show2["stage"] == "verified"
    assert uc3_show2["revalidation"] is None

    # 5. Deliver T002 again and validate UC002 (probe exits 1 -> fails) -> fail ALSO clears `revalidation: pending`!
    assert run_cli("transition", "T002", "in progress", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    assert run_cli("transition", "T002", "delivered", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    res_v2 = run_cli("use-cases", "validate", "UC002", "--tasks-dir", str(tasks_dir), "--json")
    assert res_v2.returncode == 1
    v2_data = json.loads(res_v2.stdout)
    assert v2_data["verdict"] == "fail"
    assert "revalidation:" not in p_uc2.read_text(encoding="utf-8")
    uc2_show2 = json.loads(run_cli("use-cases", "show", "UC002", "--tasks-dir", str(tasks_dir), "--json").stdout)["use_case"]
    assert uc2_show2["stage"] == "failing"
    assert uc2_show2["revalidation"] is None

    # 6. Deliver T001 and run `use-cases campaign` -> clears UC001's `revalidation: pending` as well!
    assert run_cli("transition", "T001", "in progress", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    assert run_cli("transition", "T001", "delivered", "--tasks-dir", str(tasks_dir), "--json").returncode == 0
    run_cli("use-cases", "campaign", "--tasks-dir", str(tasks_dir), "--json")
    assert "revalidation:" not in p_uc1.read_text(encoding="utf-8")
    res_q_end = json.loads(run_cli("use-cases", "queue", "--tasks-dir", str(tasks_dir), "--json").stdout)
    assert res_q_end["count"] == 0


def test_17_7_safe_closing_guard_refuses_failing_approved_allows_after_probe_and_owner_approved(
    tmp_path: pathlib.Path,
) -> None:
    """Task 17.7 Deliverable 3:
    - Transition to `verified` or `done` refused with exit 2 when a linked `approved` use case has
      `last-verdict: fail`, emitting `task.transition_refused` with reason `use_case_failing` and `use_case_ids`.
    - Proposed and deprecated use cases never block even when `last-verdict: fail`.
    - Allowed after a later probe run strictly after the task's last `delivered` transition.
    - `--owner-approved` overrides the guard, recorded in the task log and in `task.transitioned` with `owner_approved: true`.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "features").mkdir(parents=True)

    # UC001: approved, failing -> blocks T001
    p_uc1 = _write_17_7_use_case(
        tasks_dir,
        "UC001",
        title="Approved Failing UC",
        approval="approved",
        linked_tasks="T001",
        last_verdict="fail",
        verification_command="python3 -c 'print(\"fixed\")'",
    )
    # UC002: proposed, failing -> never blocks T002
    _write_17_7_use_case(
        tasks_dir,
        "UC002",
        title="Proposed Failing UC",
        approval="proposed",
        linked_tasks="T002",
        last_verdict="fail",
    )
    # UC003: deprecated, failing -> never blocks T002
    _write_17_7_use_case(
        tasks_dir,
        "UC003",
        title="Deprecated Failing UC",
        approval="deprecated",
        linked_tasks="T002",
        last_verdict="fail",
    )
    # UC004: approved, failing -> blocks T003 until --owner-approved override
    _write_17_7_use_case(
        tasks_dir,
        "UC004",
        title="Approved Failing Override UC",
        approval="approved",
        linked_tasks="T003",
        last_verdict="fail",
    )

    t1 = tasks_dir / "features" / "T001-remediate.md"
    _write_17_7_task(t1, task_id="T001", title="Remediate UC1", state="in progress", executor="kilo", use_cases="UC001")
    t2 = tasks_dir / "features" / "T002-proposed.md"
    _write_17_7_task(t2, task_id="T002", title="Proposed UC Task", state="in progress", executor="kilo", use_cases="UC002, UC003")
    t3 = tasks_dir / "features" / "T003-override.md"
    _write_17_7_task(t3, task_id="T003", title="Override UC Task", state="in progress", executor="kilo", use_cases="UC004")

    # Deliver all 3 tasks
    for tid in ("T001", "T002", "T003"):
        assert run_cli("transition", tid, "delivered", "--tasks-dir", str(tasks_dir), "--json").returncode == 0

    # 1. Proposed & deprecated failing use cases do NOT block T002 from verified or done
    res_t2_ver = run_cli("transition", "T002", "verified", "--verifier", "claude", "--tasks-dir", str(tasks_dir), "--json")
    assert res_t2_ver.returncode == 0, res_t2_ver.stdout + res_t2_ver.stderr
    res_t2_done = run_cli("transition", "T002", "done", "--tasks-dir", str(tasks_dir), "--json")
    assert res_t2_done.returncode == 0, res_t2_done.stdout + res_t2_done.stderr

    # 2. Approved failing UC001 refuses T001 going to `verified` or `done` with exit code 2
    res_t1_ver_refused = run_cli("transition", "T001", "verified", "--verifier", "claude", "--tasks-dir", str(tasks_dir), "--json")
    assert res_t1_ver_refused.returncode == 2
    ref_data = json.loads(res_t1_ver_refused.stdout)
    assert ref_data["ok"] is False
    assert ref_data["reason"] == "use_case_failing"
    assert ref_data["use_case_ids"] == ["UC001"]
    assert "UC001" in ref_data["error"]
    assert "--owner-approved" in ref_data["error"]

    res_t1_done_refused = run_cli("transition", "T001", "done", "--verifier", "claude", "--tasks-dir", str(tasks_dir), "--json")
    assert res_t1_done_refused.returncode == 2

    # Check `task.transition_refused` event was emitted with reason `use_case_failing` and `use_case_ids`
    ws_events = _read_ws_events(tmp_path)
    ref_evs = [e for e in ws_events if e["type"] == "task.transition_refused" and e["subject"] == "T001"]
    assert len(ref_evs) >= 1
    assert ref_evs[0]["data"]["reason"] == "use_case_failing"
    assert ref_evs[0]["data"]["use_case_ids"] == ["UC001"]

    # 3. After a later probe run (`use-cases validate UC001`) strictly after T001's `delivered` transition, T001 is allowed!
    res_val1 = run_cli("use-cases", "validate", "UC001", "--tasks-dir", str(tasks_dir), "--json")
    assert res_val1.returncode == 0, res_val1.stdout + res_val1.stderr
    res_t1_ver_ok = run_cli("transition", "T001", "verified", "--verifier", "claude", "--tasks-dir", str(tasks_dir), "--json")
    assert res_t1_ver_ok.returncode == 0, res_t1_ver_ok.stdout + res_t1_ver_ok.stderr
    res_t1_done_ok = run_cli("transition", "T001", "done", "--tasks-dir", str(tasks_dir), "--json")
    assert res_t1_done_ok.returncode == 0, res_t1_done_ok.stdout + res_t1_done_ok.stderr

    # 4. `--owner-approved` overrides the guard on T003 (while UC004 is still failing), recorded in task log & event
    res_t3_refused = run_cli("transition", "T003", "verified", "--verifier", "claude", "--tasks-dir", str(tasks_dir), "--json")
    assert res_t3_refused.returncode == 2

    res_t3_override = run_cli(
        "transition", "T003", "done",
        "--owner-approved",
        "--reason", "Accepted known issue for hotfix",
        "--tasks-dir", str(tasks_dir), "--json",
    )
    assert res_t3_override.returncode == 0, res_t3_override.stdout + res_t3_override.stderr
    t3_done_path = tasks_dir / "done" / "features" / "T003-override.md"
    assert t3_done_path.is_file()
    t3_log_text = t3_done_path.read_text(encoding="utf-8")
    assert "owner-approved" in t3_log_text

    ws_events2 = _read_ws_events(tmp_path)
    t3_trans_evs = [
        e for e in ws_events2
        if e["type"] == "task.transitioned" and e["subject"] == "T003" and e["data"].get("to") in ("verified", "done")
    ]
    assert len(t3_trans_evs) >= 1
    assert any(e["data"].get("owner_approved") is True for e in t3_trans_evs)


def test_17_7_revalidation_pending_atomicity_rollback_on_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 17.7 Deliverable 4:
    Failure injected after the task write (when writing the use case file) rolls back BOTH
    the task file and the use case file byte-for-byte.
    """
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "use-cases").mkdir(parents=True)
    (tasks_dir / "features").mkdir(parents=True)

    p_uc1 = _write_17_7_use_case(
        tasks_dir,
        "UC001",
        title="Atomic Verified UC",
        approval="approved",
        linked_tasks="T001",
        last_verdict="pass",
    )
    t1 = tasks_dir / "features" / "T001-atomic.md"
    _write_17_7_task(t1, task_id="T001", title="Atomic Task", state="delivered", executor="kilo", use_cases="UC001")

    t1_bytes_before = t1.read_bytes()
    uc1_bytes_before = p_uc1.read_bytes()

    real_atomic_write = te._atomic_write_text
    call_count = {"n": 0}

    def _failing_on_second_write(path: pathlib.Path, content: str, encoding: str = "utf-8") -> None:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("Simulated disk failure after task write")
        real_atomic_write(path, content, encoding=encoding)

    monkeypatch.setattr(te, "_atomic_write_text", _failing_on_second_write)

    with pytest.raises(OSError, match="Simulated disk failure after task write"):
        te.transition_task(
            tasks_dir=tasks_dir,
            task_id="T001",
            new_state="bounced",
            reason="Failed check",
        )

    assert call_count["n"] >= 2
    assert t1.read_bytes() == t1_bytes_before
    assert p_uc1.read_bytes() == uc1_bytes_before

    # Also test atomicity on `reopen_node` from `done/`
    t2_done = tasks_dir / "done" / "features" / "T002-reopen-atomic.md"
    _write_17_7_task(t2_done, task_id="T002", title="Reopen Atomic Task", state="done", executor="kilo", use_cases="UC002")
    p_uc2 = _write_17_7_use_case(
        tasks_dir,
        "UC002",
        title="Atomic Reopen UC",
        approval="approved",
        linked_tasks="T002",
        last_verdict="pass",
    )
    t2_bytes_before = t2_done.read_bytes()
    uc2_bytes_before = p_uc2.read_bytes()
    call_count["n"] = 0

    with pytest.raises(OSError, match="Simulated disk failure after task write"):
        te.reopen_node(
            tasks_dir=tasks_dir,
            node_id="T002",
            reason="Reopen atomic test",
            apply_direct=True,
        )

    assert t2_done.is_file()
    assert not (tasks_dir / "features" / "T002-reopen-atomic.md").exists()
    assert t2_done.read_bytes() == t2_bytes_before
    assert p_uc2.read_bytes() == uc2_bytes_before







