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
    assert "| T001 | P0 | [First feature](features/T001-first.md) |" in synced
    assert "| T001 | Which DB engine? | owner | T002 |" in synced
    assert "| T000 | [Initial setup](done/features/T000-init.md) | done |" in synced


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
            if len(cells) == 4 and re.match(r"^T\d+$", cells[0]):
                res[cells[0]] = (cells[2], cells[3])
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
            ids.append(cells[0])
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
            if len(cells) == 4 and re.match(r"^T\d+$", cells[0]):
                rows.append((cells[0], cells[2], cells[3]))
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
        "### 05.12 - Canonical two-digit task\n"
        "### 05.2a - Letter suffix is not an id\n"
        "### 05.3 Missing separator\n"
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

    plan.write_text("### 05.1 - Fine\n### 05.10 — Em dash is accepted\n", encoding="utf-8")
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

    res_add_init = te.child_add(tasks_dir, "07", title="Task 3")
    assert res_add_init["ok"] is True
    assert res_add_init["allocated_id"] == "07.3"

    res_add_inflight = te.child_add(tasks_dir, "07.1", title="Subtask")
    assert res_add_inflight["ok"] is False
    assert "Cannot add child to in-flight leaf '07.1'" in res_add_inflight["error"]

    res_add_open = te.child_add(tasks_dir, "07.2", title="Subtask of 2")
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

    res_exp = te.expand_node(tasks_dir, "07.4")
    assert res_exp["ok"] is True
    folder_path = pathlib.Path(res_exp["folder"])
    assert folder_path.is_dir()
    assert (folder_path / "README.md").is_file()

    exp_plan_text = plan_file.read_text(encoding="utf-8")
    assert "- **Expanded:** [07.4-run-engine-c-worktrees-verify-verdicts/](07.4-run-engine-c-worktrees-verify-verdicts/README.md)" in exp_plan_text

    res_col = te.collapse_node(tasks_dir, "07.4")
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

    res = te.reopen_node(tasks_dir, "07.1", reason="Re-testing verification")
    assert res["ok"] is True
    assert res["new_state"] == "open"

    tree = te.discover_task_tree(tasks_dir)
    assert tree["07.1"].canonical_state == "open"


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
    """A block stops at any `###` heading (a letter-suffixed `### 12.2a - ...` included), so it never
    absorbs the next item's bullets; letter-suffixed ids are not dependency ids and are kept on rewrite."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "12-sample").mkdir(parents=True)
    plan = tasks_dir / "12-sample" / "plan.md"
    plan.write_text(
        "# 12 - Sample\n\n## Tasks\n\n"
        "### 12.1 - A\n\n- **Status:** `open` · **Depends on:** 07.12\n- **Goal:** g\n\n"
        "### 12.2a - Legacy\n\n- **Status:** `done` · **Depends on:** 10.4 (lane end)\n- **Goal:** g\n\n"
        "### 12.3 - B\n\n- **Status:** `open` · **Depends on:** 12.2a, 07.11 (runs lane end), 12.1\n- **Goal:** g\n",
        encoding="utf-8",
    )
    tree = te.discover_task_tree(tasks_dir)
    assert tree["12.1"].depends_on == ["07.12"] and tree["12.1"].canonical_state == "open"
    assert "12.2a" not in tree
    assert tree["12.3"].own_depends_on == ["07.11", "12.1"]
    assert te.update_depends_on_field("12.2a, 07.11 (runs lane end), 12.1", ["07.11", "12.1"]) == (
        "12.2a, 07.11 (runs lane end), 12.1"
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
    res = te.child_add(tasks_dir, r["id"], "child")
    assert res is not None and res["ok"] is False and "not implemented" in res["error"]


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

