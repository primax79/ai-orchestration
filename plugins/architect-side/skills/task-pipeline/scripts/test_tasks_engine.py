#!/usr/bin/env python3
"""Unit tests for tasks_engine.py."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

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
