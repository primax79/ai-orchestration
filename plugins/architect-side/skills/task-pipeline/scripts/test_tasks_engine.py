#!/usr/bin/env python3
"""Unit tests for tasks_engine.py."""
from __future__ import annotations

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
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ext_lines = []
    if profile is not None:
        ext_lines.append(f"- profile: {profile}")
    if verification_mode is not None:
        ext_lines.append(f"- verification-mode: {verification_mode}")
    if verifier is not None:
        ext_lines.append(f"- verifier: {verifier}")
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

    res = run_cli("upgrade", "--tasks-dir", str(tasks_dir), "--json")
    assert res.returncode == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
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
    _write_sample_task(tasks_dir / "features" / "T001.md", task_id="T001", title="Real task", category="features")

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
| T001 | P1 | [Real task](features/T001.md) | open | kilo | - |
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
    _write_sample_task(task_file, task_id="T001")
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
    assert "- status: verified" in uc_text
    assert "- last-verdict: pass" in uc_text
    assert "### [" in uc_text
    assert "AI Validation by kilo:gemini-4-argon" in uc_text

    # 6. Validate passes with zero errors/warnings now!
    res_val2 = run_cli("validate", "--tasks-dir", str(tasks_dir), "--json")
    assert json.loads(res_val2.stdout)["ok"] is True


def test_use_cases_validate_probe_and_campaign(tmp_path: pathlib.Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "00-INDEX.md").write_text("# Task Index\n", encoding="utf-8")

    # 1. Create passing UC001
    run_cli(
        "use-cases", "create",
        "--id", "UC001",
        "--title", "Passing Scenario",
        "--actor", "Buyer",
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


def test_depends_on_rejects_cross_project_qualified_ref(tmp_path: pathlib.Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "features" / "T001-scraper.md"
    _write_sample_task(task_file, task_id="T001", depends_on="other-proj/T002")

    errors, warnings, _, _ = te.validate_tasks_tree(tasks_dir)
    assert any("cross-project dependencies are v2; use coordinates: from the workspace tree" in e for e in errors)


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
    assert any("cross-project dependencies are v2; use coordinates: from the workspace tree" in e for e in errors)
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

    # T001 is listed as `done, conditional (Q001)` in Conditional
    assert f"done, conditional ({q1_id})" in index_text
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
