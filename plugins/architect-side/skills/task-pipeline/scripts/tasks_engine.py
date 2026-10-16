#!/usr/bin/env python3
"""tasks_engine.py — Deterministic parser, validator, state-transition engine,
and `00-INDEX.md` synchronizer for the `ai-orchestration` `tasks/` tree.

Implements the formal contract defined in:
  - `tasks/specs/task-and-state-model.md`
  - `plugins/architect-side/skills/macroplan-authoring/SKILL.md`

Zero external dependencies (Python 3.11+ stdlib only). Every subcommand
supports `--json` (before or after the subcommand name).
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

CORE_HEADER_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "category",
    "priority",
    "priority-reason",
    "next-up",
    "state",
    "executor",
    "depends-on",
    "decider",
    "sources",
    "paths",
    "handoff",
)

OPTIONAL_EXTENSION_FIELDS: tuple[str, ...] = (
    "profile",
    "verification-mode",
    "verifier",
)

ALL_ALLOWED_HEADER_FIELDS: set[str] = set(CORE_HEADER_FIELDS) | set(OPTIONAL_EXTENSION_FIELDS)

PRIORITIES: set[str] = {"P0", "P1", "P2", "P3"}
PRIORITY_SORT_KEY: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
NEXT_UP_VALUES: set[str] = {"yes", "no"}
PROFILES: set[str] = {"deep-reasoning", "orchestration", "bulk-execution", "exploration"}
VERIFICATION_MODES: set[str] = {"self", "independent-session", "cross-agent", "panel", "owner"}

CANONICAL_STATES: set[str] = {
    "open",
    "in progress",
    "waiting",
    "blocked",
    "delivered",
    "bounced",
    "verified",
    "done",
    "done with a caveat",
    "dropped",
}

TERMINAL_STATES: set[str] = {"done", "done with a caveat", "dropped"}

# Legal state transitions (canonical base state -> allowed target canonical base states)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in progress", "waiting", "blocked", "dropped"},
    "in progress": {"waiting", "blocked", "delivered", "dropped"},
    "waiting": {"in progress", "blocked", "open", "dropped"},
    "blocked": {"in progress", "waiting", "open", "dropped"},
    "delivered": {"verified", "bounced", "done with a caveat", "dropped"},
    "bounced": {"in progress", "waiting", "blocked", "dropped"},
    "verified": {"done", "done with a caveat", "bounced", "dropped"},
    "done": set(),
    "done with a caveat": set(),
    "dropped": set(),
}

REQUIRED_SECTIONS: tuple[str, ...] = ("## Goal", "## Steps", "## Verification")
RESERVED_DIRS: set[str] = {"_inbox", "_reviews", "specs", "done", "merged", "notes", "reviews"}

CANONICAL_TASKS_AGENTS_MD = """# tasks/ convention (task-pipeline + emergent tasks)

Short copy of the `task-pipeline` skill (`plugins/architect-side/skills/task-pipeline/`).

- **Pipeline for large multi-task initiatives:** `_inbox/to-analyze/` → `specs/<slug>.md` → `NN-<slug>/plan.md` (tasks `NN.T` sized one-per-commit, inline or expanded) → `done/NN-<slug>/` (with `summary.md`) → `merged/NN-<slug>/`.
- **Emergent tasks (`<category>/T###-<slug>`): Capture first, then continue.** Work that appears mid-session becomes a task file at once; it does not stay in the session context.
- **Ids:** `T###`, unique across `done/` too; reserve the id by creating the file immediately.
- **Layout:** `tasks/<category>/T###-<slug>.md` for small tasks; `T###-<slug>/{README,CONTEXT,PROGRESS}.md` when there is context. Each category has a `README.md` and `notes/`.
- **Header (closed set, exact order):** `id`, `title`, `category`, `priority` (P0-P3), `priority-reason`, `next-up`, `state`, `executor`, `depends-on`, `decider`, `sources`, `paths`, `handoff`. Optional extensions: `profile`, `verification-mode`, `verifier`.
- **States:** `open`, `in progress`, `waiting`, `blocked`, `delivered`, `bounced`, `verified`, `done` (or `done with a caveat`), `dropped`. `verified` is set by someone other than the executor, or by the executor after the owner's explicit approval (recorded in `PROGRESS.md`).
- **Registry:** `00-INDEX.md` (Initiatives, Specs, Next up <= 5, Tasks by category, Decisions waiting, Done) is the state; keep it current with every change.
- **Done:** `git mv` the finished emergent task to `tasks/done/<category>/`.
- **Several sessions:** only a category's `owner-session` edits its tasks; others add notes or new tasks.
"""

TASK_ID_RE = re.compile(r"^(?:T\d{3,}|\d{2,}\.\d+)$")
EMERGENT_ID_RE = re.compile(r"^T\d{3,}$")
INITIATIVE_DIR_RE = re.compile(r"^(\d{2,})-(.+)$")
HEADER_LINE_RE = re.compile(r"^-\s+([a-z][a-z0-9-]*):\s*(.*)$")
INLINE_TASK_HEADING_RE = re.compile(r"^###\s+(\d{2,}\.\d+)\s+[—–-]\s+(.+?)\s*$", re.MULTILINE)


def normalize_state(raw_state: str) -> str:
    """Map parameterized state strings like 'done with a caveat: self-verified only'
    or 'dropped: reason' to their canonical base state."""
    s = raw_state.strip()
    for base in ("done with a caveat", "waiting", "blocked", "dropped"):
        if s == base or s.startswith(base + ":") or s.startswith(base + " ("):
            return base
    return s


def is_valid_state(raw_state: str) -> bool:
    return normalize_state(raw_state) in CANONICAL_STATES


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_emergent_task_file(
    file_path: pathlib.Path,
    tasks_dir: pathlib.Path,
    in_done: bool = False,
) -> dict[str, Any]:
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    rel_path = file_path.relative_to(tasks_dir).as_posix()
    is_folder = file_path.name == "README.md"
    task_root = file_path.parent if is_folder else file_path

    # Locate H1
    h1_idx: int | None = None
    h1_text = ""
    for i, line in enumerate(lines):
        if line.startswith("# "):
            h1_idx = i
            h1_text = line[2:].strip()
            break

    header_keys: list[str] = []
    headers: dict[str, str] = {}
    header_start: int | None = None
    header_end: int | None = None

    if h1_idx is not None:
        idx = h1_idx + 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        header_start = idx
        while idx < len(lines):
            m = HEADER_LINE_RE.match(lines[idx])
            if not m:
                break
            k, v = m.group(1), m.group(2).strip()
            header_keys.append(k)
            headers[k] = v
            idx += 1
        header_end = idx

    # Check for `verification pending:` line immediately after header
    verification_pending: str | None = None
    if header_end is not None:
        scan_idx = header_end
        while scan_idx < len(lines) and not lines[scan_idx].strip():
            scan_idx += 1
        if scan_idx < len(lines) and lines[scan_idx].strip().lower().startswith("verification pending:"):
            verification_pending = lines[scan_idx].strip().split(":", 1)[1].strip()

    sections_present = [sec for sec in REQUIRED_SECTIONS if re.search(rf"^{re.escape(sec)}\b", text, re.MULTILINE)]

    # Determine expected category from directory layout
    parts = file_path.relative_to(tasks_dir).parts
    if in_done:
        # done/<category>/T###-...
        folder_category = parts[1] if len(parts) >= 3 else ""
    else:
        # <category>/T###-...
        folder_category = parts[0] if len(parts) >= 2 else ""

    raw_depends = headers.get("depends-on", "-")
    depends_list = (
        [d.strip() for d in raw_depends.split(",") if d.strip() and d.strip() != "-"]
        if raw_depends and raw_depends != "-"
        else []
    )

    raw_state = headers.get("state", "")
    return {
        "kind": "emergent",
        "id": headers.get("id", ""),
        "title": headers.get("title", ""),
        "h1": h1_text,
        "category": headers.get("category", ""),
        "folder_category": folder_category,
        "priority": headers.get("priority", ""),
        "priority_reason": headers.get("priority-reason", ""),
        "next_up": headers.get("next-up", ""),
        "state": raw_state,
        "canonical_state": normalize_state(raw_state),
        "executor": headers.get("executor", ""),
        "depends_on": depends_list,
        "depends_on_raw": raw_depends,
        "decider": headers.get("decider", "-"),
        "sources": headers.get("sources", "-"),
        "paths": headers.get("paths", "-"),
        "handoff": headers.get("handoff", ""),
        "profile": headers.get("profile"),
        "verification_mode": headers.get("verification-mode"),
        "verifier": headers.get("verifier"),
        "verification_pending": verification_pending,
        "header_keys": header_keys,
        "headers": headers,
        "sections_present": sections_present,
        "is_folder": is_folder,
        "in_done": in_done,
        "file_path": str(file_path),
        "task_root": str(task_root),
        "rel_path": rel_path,
    }


def discover_emergent_tasks(tasks_dir: pathlib.Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not tasks_dir.is_dir():
        return results

    def _scan_category_dir(cat_dir: pathlib.Path, in_done: bool) -> None:
        if not cat_dir.is_dir():
            return
        for entry in sorted(cat_dir.iterdir()):
            if entry.name.startswith(".") or entry.name in ("README.md", "notes"):
                continue
            if entry.is_file() and entry.suffix == ".md" and re.match(r"^T\d{3,}-", entry.name):
                results.append(parse_emergent_task_file(entry, tasks_dir, in_done=in_done))
            elif entry.is_dir() and re.match(r"^T\d{3,}-", entry.name):
                readme = entry / "README.md"
                if readme.is_file():
                    results.append(parse_emergent_task_file(readme, tasks_dir, in_done=in_done))

    # Active categories
    for child in sorted(tasks_dir.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
            continue
        if child.name in RESERVED_DIRS or INITIATIVE_DIR_RE.match(child.name):
            continue
        _scan_category_dir(child, in_done=False)

    # Done categories
    done_dir = tasks_dir / "done"
    if done_dir.is_dir():
        for child in sorted(done_dir.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
                continue
            if child.name in RESERVED_DIRS or INITIATIVE_DIR_RE.match(child.name):
                continue
            _scan_category_dir(child, in_done=True)

    return results


def discover_initiatives(tasks_dir: pathlib.Path) -> list[dict[str, Any]]:
    initiatives: list[dict[str, Any]] = []
    if not tasks_dir.is_dir():
        return initiatives

    # Try parsing initiative statuses from 00-INDEX.md if present
    index_path = tasks_dir / "00-INDEX.md"
    index_statuses: dict[str, str] = {}
    if index_path.is_file():
        idx_text = index_path.read_text(encoding="utf-8")
        for line in idx_text.splitlines():
            m_idx = re.match(
                r"^\|\s*\d+\s*\|\s*(\d{2,})\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([^|]+)\|",
                line,
            )
            if m_idx:
                inum = m_idx.group(1)
                st_col = m_idx.group(4).lower()
                if "not merged" in st_col or "in progress" in st_col or "progress" in st_col:
                    index_statuses[inum] = "in progress"
                elif "merged" in st_col or "done" in st_col:
                    index_statuses[inum] = "done"
                else:
                    index_statuses[inum] = "open"

    search_roots: list[tuple[pathlib.Path, str]] = [
        (tasks_dir, "active"),
        (tasks_dir / "done", "done"),
        (tasks_dir / "merged", "merged"),
    ]

    for root, location in search_roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            m = INITIATIVE_DIR_RE.match(entry.name)
            if not m:
                continue
            num, slug = m.group(1), m.group(2)
            plan_path = entry / "plan.md"
            if not plan_path.is_file():
                continue
            text = plan_path.read_text(encoding="utf-8")
            h1_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            title = h1_match.group(1).strip() if h1_match else entry.name

            # Determine initiative status
            if location in ("merged", "done") or (entry / "summary.md").is_file():
                init_status = "done"
            elif num in index_statuses:
                init_status = index_statuses[num]
            else:
                status_m = re.search(
                    r"^\s*>\s*\*\*Status:\*\*\s*([^\n·]+)", text, re.MULTILINE | re.IGNORECASE
                )
                if status_m:
                    st_raw = status_m.group(1).lower()
                    if "not merged" in st_raw or "in progress" in st_raw or "progress" in st_raw:
                        init_status = "in progress"
                    elif "done" in st_raw or "merged" in st_raw:
                        init_status = "done"
                    else:
                        init_status = "open"
                else:
                    init_status = "open"

            inline_tasks = [
                {"id": tm.group(1), "title": tm.group(2).strip(), "state": init_status}
                for tm in INLINE_TASK_HEADING_RE.finditer(text)
            ]

            # Also check table tasks in plan.md (e.g. | **T1** | **Title**: desc |)
            table_tasks = []
            for line in text.splitlines():
                tm = re.match(r"^\|\s*\*\*(T\w+|\d+\.\d+)\*\*\s*\|\s*(.+?)\s*\|", line)
                if tm:
                    sub_id, raw_content = tm.groups()
                    title_m = re.match(r"^\*\*([^*]+)\*\*[:\s]*(.*)$", raw_content.strip())
                    sub_title = title_m.group(1).strip() if title_m else raw_content.strip()
                    # Check if log mentions this task as verified
                    sub_state = init_status
                    if init_status == "in progress":
                        if re.search(rf"\b{re.escape(sub_id)}\b.*?\bverified\b", text, re.IGNORECASE):
                            sub_state = "verified"
                        elif re.search(rf"\b{re.escape(sub_id)}\b.*?\bdelivered\b", text, re.IGNORECASE):
                            sub_state = "delivered"
                        elif re.search(rf"\b{re.escape(sub_id)}\b.*?\bqueued\b", text, re.IGNORECASE):
                            sub_state = "open"
                    table_tasks.append(
                        {
                            "id": sub_id,
                            "title": sub_title,
                            "state": sub_state,
                        }
                    )

            # Also check expanded NN.T-*.md files
            expanded_tasks = []
            for sub in sorted(entry.glob(f"{num}.*-*.md")):
                sub_m = re.match(rf"^({re.escape(num)}\.\d+)-(.+)\.md$", sub.name)
                if sub_m:
                    expanded_tasks.append(
                        {
                            "id": sub_m.group(1),
                            "title": sub_m.group(2),
                            "rel_path": sub.relative_to(tasks_dir).as_posix(),
                            "state": init_status,
                        }
                    )

            chosen_tasks = expanded_tasks or inline_tasks or table_tasks

            initiatives.append(
                {
                    "id": num,
                    "slug": slug,
                    "folder": entry.name,
                    "title": title,
                    "status": init_status,
                    "location": location,
                    "rel_path": plan_path.relative_to(tasks_dir).as_posix(),
                    "has_summary": (entry / "summary.md").is_file(),
                    "tasks": chosen_tasks,
                }
            )
    return initiatives


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_tasks_tree(tasks_dir: pathlib.Path) -> tuple[list[str], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[str] = []
    warnings: list[str] = []

    emergent = discover_emergent_tasks(tasks_dir)
    initiatives = discover_initiatives(tasks_dir)

    seen_ids: dict[str, str] = {}
    known_task_ids: set[str] = set()

    for init in initiatives:
        known_task_ids.add(init["id"])
        for t in init.get("tasks", []):
            known_task_ids.add(t["id"])

    for task in emergent:
        tid = task["id"]
        rel = task["rel_path"]
        if not tid:
            errors.append(f"{rel}: missing required 'id' header field.")
        else:
            if not EMERGENT_ID_RE.match(tid):
                errors.append(f"{rel}: invalid emergent task id {tid!r} (expected format T###).")
            if tid in seen_ids:
                errors.append(f"{rel}: duplicate task id {tid!r} (already defined in {seen_ids[tid]}).")
            else:
                seen_ids[tid] = rel
            known_task_ids.add(tid)

        # Check filename starts with ID
        target_name = pathlib.Path(task["task_root"]).name
        if tid and not target_name.startswith(f"{tid}-"):
            errors.append(f"{rel}: file/folder name {target_name!r} does not start with '{tid}-'.")

        # Validate header fields & order
        keys = task["header_keys"]
        missing_core = [k for k in CORE_HEADER_FIELDS if k not in keys]
        if missing_core:
            errors.append(f"{rel}: missing mandatory header field(s): {', '.join(missing_core)}.")

        unknown_keys = [k for k in keys if k not in ALL_ALLOWED_HEADER_FIELDS]
        if unknown_keys:
            errors.append(f"{rel}: unknown header field(s): {', '.join(unknown_keys)}.")

        # Check exact ordering of CORE_HEADER_FIELDS and optional extension fields after handoff
        present_core = [k for k in keys if k in CORE_HEADER_FIELDS]
        expected_core = [k for k in CORE_HEADER_FIELDS if k in present_core]
        if present_core != expected_core:
            errors.append(
                f"{rel}: core header fields out of order: got {present_core}, expected {list(CORE_HEADER_FIELDS)}."
            )

        if "handoff" in keys:
            handoff_pos = keys.index("handoff")
            for ext_k in keys:
                if ext_k in OPTIONAL_EXTENSION_FIELDS and keys.index(ext_k) < handoff_pos:
                    errors.append(f"{rel}: optional field '{ext_k}' must appear after 'handoff'.")

        # Check empty values
        for k in CORE_HEADER_FIELDS:
            if k in task["headers"] and task["headers"][k] == "":
                errors.append(f"{rel}: header field '{k}' cannot be empty (use '-' when empty).")

        # Category match
        if task["category"] and task["folder_category"] and task["category"] != task["folder_category"]:
            errors.append(
                f"{rel}: header category {task['category']!r} does not match folder {task['folder_category']!r}."
            )

        # Priority
        if task["priority"] and task["priority"] not in PRIORITIES:
            errors.append(f"{rel}: invalid priority {task['priority']!r} (expected one of {sorted(PRIORITIES)}).")

        if not task["priority_reason"] or task["priority_reason"] == "-":
            errors.append(f"{rel}: 'priority-reason' must be a non-empty explanation.")

        # next-up
        if task["next_up"] not in NEXT_UP_VALUES:
            errors.append(f"{rel}: invalid next-up {task['next_up']!r} (expected 'yes' or 'no').")

        # State
        if not task["state"] or not is_valid_state(task["state"]):
            errors.append(
                f"{rel}: invalid state {task['state']!r} (expected one of {sorted(CANONICAL_STATES)})."
            )

        # Done placement consistency
        cstate = task["canonical_state"]
        if task["in_done"] and cstate not in TERMINAL_STATES:
            errors.append(f"{rel}: task is under done/ but state is {task['state']!r} (not terminal).")
        if not task["in_done"] and cstate in TERMINAL_STATES:
            warnings.append(f"{rel}: task has terminal state {task['state']!r} but has not been moved to done/.")

        # Optional extension fields
        if task["profile"] and task["profile"] != "-" and task["profile"] not in PROFILES:
            errors.append(f"{rel}: invalid profile {task['profile']!r} (expected one of {sorted(PROFILES)}).")
        if (
            task["verification_mode"]
            and task["verification_mode"] != "-"
            and task["verification_mode"] not in VERIFICATION_MODES
        ):
            errors.append(
                f"{rel}: invalid verification-mode {task['verification_mode']!r} "
                f"(expected one of {sorted(VERIFICATION_MODES)})."
            )

        # Required sections
        missing_sections = [s for s in REQUIRED_SECTIONS if s not in task["sections_present"]]
        if missing_sections:
            errors.append(f"{rel}: missing required Markdown section(s): {', '.join(missing_sections)}.")

    # Validate dependency DAG acyclicity & valid dependency references
    adj: dict[str, list[str]] = {}
    for task in emergent:
        tid = task["id"]
        if not tid:
            continue
        deps_for_tid = adj.setdefault(tid, [])
        for dep in task["depends_on"]:
            if not TASK_ID_RE.match(dep):
                errors.append(f"{task['rel_path']}: invalid depends-on reference {dep!r}.")
            elif dep == tid:
                errors.append(f"{task['rel_path']}: task {tid} cannot depend on itself.")
            elif dep not in deps_for_tid:
                deps_for_tid.append(dep)

    # Cycle detection via DFS coloring (0 = unvisited, 1 = visiting, 2 = visited)
    color: dict[str, int] = {}

    def _dfs(node: str, stack: list[str]) -> None:
        color[node] = 1
        for nb in adj.get(node, []):
            if nb not in adj:
                continue
            if color.get(nb, 0) == 1:
                cycle_path = " -> ".join(stack + [nb])
                errors.append(f"Dependency cycle detected in depends-on graph: {cycle_path}.")
            elif color.get(nb, 0) == 0:
                _dfs(nb, stack + [nb])
        color[node] = 2

    for node in sorted(adj):
        if color.get(node, 0) == 0:
            _dfs(node, [node])

    return errors, warnings, emergent, initiatives


# ---------------------------------------------------------------------------
# State Transitions
# ---------------------------------------------------------------------------

def _is_independent_verifier(executor: str, actor: str | None, verifier: str | None) -> bool:
    """Return True if the verifier/actor satisfies independent verification (`verifier != executor`
    or owner approval or explicit blind-subagent)."""
    exec_norm = executor.strip().lower()
    for candidate in (verifier, actor):
        if not candidate:
            continue
        cand_norm = candidate.strip().lower()
        if cand_norm in ("owner", "user"):
            return True
        if cand_norm.startswith("blind-subagent"):
            return True
        if cand_norm.startswith("panel("):
            return True
        tool_prefix = cand_norm.split(":", 1)[0].strip()
        if tool_prefix and tool_prefix != exec_norm:
            return True
    return False


def _update_task_file_headers_and_state(
    file_path: pathlib.Path,
    new_state: str,
    verifier: str | None = None,
    clear_next_up: bool = False,
) -> None:
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    h1_idx = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
    idx = h1_idx + 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    header_end = idx
    verifier_line_idx: int | None = None
    handoff_line_idx: int | None = None

    while header_end < len(lines):
        m = HEADER_LINE_RE.match(lines[header_end])
        if not m:
            break
        key = m.group(1)
        if key == "state":
            lines[header_end] = f"- state: {new_state}"
        elif key == "next-up" and clear_next_up:
            lines[header_end] = "- next-up: no"
        elif key == "verifier":
            verifier_line_idx = header_end
            if verifier is not None:
                lines[header_end] = f"- verifier: {verifier}"
        elif key == "handoff":
            handoff_line_idx = header_end
        header_end += 1

    if verifier is not None and verifier_line_idx is None and handoff_line_idx is not None:
        lines.insert(header_end, f"- verifier: {verifier}")
        header_end += 1

    # Manage `verification pending:` line right after header
    cstate = normalize_state(new_state)
    scan_idx = header_end
    while scan_idx < len(lines) and not lines[scan_idx].strip():
        scan_idx += 1

    has_vp_line = (
        scan_idx < len(lines)
        and lines[scan_idx].strip().lower().startswith("verification pending:")
    )
    if cstate == "delivered":
        vp_target = verifier or "independent verifier"
        vp_line = f"verification pending: run Verification checks ({vp_target})"
        if has_vp_line:
            lines[scan_idx] = vp_line
        else:
            lines.insert(header_end, "")
            lines.insert(header_end + 1, vp_line)
    elif has_vp_line:
        # Remove `verification pending:` line once no longer in `delivered`
        del lines[scan_idx]
        if scan_idx < len(lines) and not lines[scan_idx].strip() and scan_idx > 0 and not lines[scan_idx - 1].strip():
            del lines[scan_idx]

    file_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _append_progress_log(
    task_info: dict[str, Any],
    old_state: str,
    new_state: str,
    actor: str | None,
    verifier: str | None,
    reason: str | None,
) -> pathlib.Path | None:
    file_path = pathlib.Path(task_info["file_path"])
    progress_path = file_path.parent / "PROGRESS.md" if task_info["is_folder"] else None
    if progress_path is None and not (file_path.parent / "PROGRESS.md").exists():
        # For single-file tasks that bounce or get owner-verified, only write PROGRESS.md if it's a folder task
        return None

    today = datetime.date.today().isoformat()
    who = verifier or actor or "orchestrator"
    detail = f" — {reason}" if reason else ""
    entry_line = f"- {today}, {who}: state `{old_state}` -> `{new_state}`{detail}"

    if progress_path and progress_path.exists():
        content = progress_path.read_text(encoding="utf-8")
        if "## Log" in content:
            parts = content.split("## Log", 1)
            after_heading = parts[1].splitlines()
            heading_suffix = after_heading[0] if after_heading else ""
            rest = "\n".join(after_heading[1:]).lstrip("\n")
            new_content = f"{parts[0]}## Log{heading_suffix}\n\n{entry_line}\n"
            if rest:
                new_content += f"{rest.rstrip()}\n"
            progress_path.write_text(new_content, encoding="utf-8")
        else:
            progress_path.write_text(content.rstrip() + f"\n\n## Log (newest first)\n\n{entry_line}\n", encoding="utf-8")
    elif progress_path:
        progress_path.write_text(
            f"# {task_info['id']} - progress\n\n## Open\n\n## Log (newest first)\n\n{entry_line}\n",
            encoding="utf-8",
        )
    return progress_path


def _move_task_to_done(task_info: dict[str, Any], tasks_dir: pathlib.Path) -> pathlib.Path:
    if task_info["in_done"]:
        return pathlib.Path(task_info["file_path"])

    src_root = pathlib.Path(task_info["task_root"])
    cat = task_info["category"] or task_info["folder_category"]
    dest_dir = tasks_dir / "done" / cat
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir / src_root.name

    # Try git mv first if inside a git worktree and tracked; fall back to shutil.move
    res = subprocess.run(
        ["git", "mv", str(src_root), str(dest_root)],
        cwd=str(tasks_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        shutil.move(str(src_root), str(dest_root))

    return dest_root / "README.md" if task_info["is_folder"] else dest_root


def transition_task(
    tasks_dir: pathlib.Path,
    task_id: str,
    new_state: str,
    actor: str | None = None,
    verifier: str | None = None,
    reason: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_valid_state(new_state):
        return False, {
            "ok": False,
            "task_id": task_id,
            "error": f"Invalid target state {new_state!r}. Allowed states: {sorted(CANONICAL_STATES)}.",
        }

    emergent = discover_emergent_tasks(tasks_dir)
    target = next((t for t in emergent if t["id"] == task_id), None)
    if target is None:
        return False, {
            "ok": False,
            "task_id": task_id,
            "error": f"Task {task_id!r} not found in {tasks_dir}.",
        }

    old_state = target["state"]
    old_canon = target["canonical_state"]
    new_canon = normalize_state(new_state)

    if old_canon in ("open", "in progress") and new_canon in ("done", "done with a caveat", "verified"):
        return False, {
            "ok": False,
            "task_id": task_id,
            "old_state": old_state,
            "new_state": new_state,
            "error": (
                f"Illegal transition '{old_state}' -> '{new_state}': "
                "no direct path from open/in progress to verified or done; task must pass through 'delivered' first."
            ),
        }

    allowed = ALLOWED_TRANSITIONS.get(old_canon, set())
    if new_canon not in allowed:
        return False, {
            "ok": False,
            "task_id": task_id,
            "old_state": old_state,
            "new_state": new_state,
            "error": (
                f"Illegal transition '{old_state}' -> '{new_state}'. "
                f"Allowed from '{old_canon}': {sorted(allowed)}."
            ),
        }

    # Guard on delivered -> verified
    vmode = (target.get("verification_mode") or "cross-agent").strip()
    if vmode == "-":
        vmode = "cross-agent"
    executor = target.get("executor", "self")

    if old_canon == "delivered" and new_canon == "verified":
        if vmode == "self" and not _is_independent_verifier(executor, actor, verifier):
            return False, {
                "ok": False,
                "task_id": task_id,
                "old_state": old_state,
                "new_state": new_state,
                "error": (
                    "Task has verification-mode='self' and no independent verifier or owner approval was supplied; "
                    "transition to 'done with a caveat: self-verified only' instead of 'verified'."
                ),
            }
        if vmode == "owner" and (actor or "").lower() != "owner" and (verifier or "").lower() != "owner":
            return False, {
                "ok": False,
                "task_id": task_id,
                "old_state": old_state,
                "new_state": new_state,
                "error": "Task requires owner verification (--actor owner or --verifier owner).",
            }
        if not _is_independent_verifier(executor, actor, verifier):
            return False, {
                "ok": False,
                "task_id": task_id,
                "old_state": old_state,
                "new_state": new_state,
                "error": (
                    f"Independent verification guard failed: task executor is {executor!r}, "
                    f"so transitioning 'delivered' -> 'verified' requires an independent verifier "
                    f"(--actor != {executor!r}, --verifier <tool>:<profile>, blind-subagent:<profile>, or owner)."
                ),
            }

    if new_canon == "bounced" and not (reason and reason.strip()):
        return False, {
            "ok": False,
            "task_id": task_id,
            "old_state": old_state,
            "new_state": new_state,
            "error": "Transitioning to 'bounced' requires --reason with the failing criterion / B1..Bn findings.",
        }

    # Format state string when self-verified caveat is used
    effective_state = new_state
    if new_canon == "done with a caveat" and ":" not in new_state and reason:
        effective_state = f"done with a caveat: {reason.strip()}"
    elif new_canon == "done with a caveat" and ":" not in new_state and vmode == "self":
        effective_state = "done with a caveat: self-verified only"

    is_terminal = new_canon in TERMINAL_STATES
    file_path = pathlib.Path(target["file_path"])
    _update_task_file_headers_and_state(
        file_path,
        effective_state,
        verifier=verifier,
        clear_next_up=is_terminal,
    )
    _append_progress_log(target, old_state, effective_state, actor, verifier, reason)

    final_path = file_path
    if is_terminal and not target["in_done"]:
        final_path = _move_task_to_done(target, tasks_dir)

    return True, {
        "ok": True,
        "task_id": task_id,
        "old_state": old_state,
        "new_state": effective_state,
        "verifier": verifier or target.get("verifier"),
        "reason": reason,
        "file_path": str(final_path),
        "rel_path": final_path.relative_to(tasks_dir).as_posix(),
    }


# ---------------------------------------------------------------------------
# 00-INDEX.md Synchronizer
# ---------------------------------------------------------------------------

def _file_sha256(path: pathlib.Path) -> str:
    if not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write_text(path: pathlib.Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = pathlib.Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _git_closed_date(tasks_dir: pathlib.Path, rel_path: str) -> str:
    today_str = datetime.date.today().isoformat()
    target_file = tasks_dir / rel_path
    try:
        cmd = ["git", "log", "--diff-filter=A", "--format=%as", "-1", "--", str(target_file)]
        res = subprocess.run(
            cmd,
            cwd=str(tasks_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if res.returncode == 0:
            date_str = res.stdout.strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                return date_str
    except Exception:
        pass
    return today_str


def has_generated_markers(content: str) -> bool:
    return bool(re.search(r"<!--\s*ai-orch:generated\s+[a-zA-Z0-9_\-:]+\s*-->", content))


def _marker_pattern(section: str) -> re.Pattern[str]:
    sec_escaped = re.escape(section)
    if "-" in section or "_" in section:
        alt = section.replace("-", "_") if "-" in section else section.replace("_", "-")
        sec_escaped = rf"(?:{re.escape(section)}|{re.escape(alt)})"
    return re.compile(
        rf"<!--\s*ai-orch:generated\s+{sec_escaped}\s*-->\n?(.*?)\n?<!--\s*/ai-orch:generated\s+{sec_escaped}\s*-->",
        re.DOTALL,
    )


def _find_table_range(lines: list[str]) -> tuple[int | None, int | None]:
    start_idx = None
    end_idx = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("|"):
            if start_idx is None:
                start_idx = idx
            end_idx = idx
        elif start_idx is not None and line.strip() and not line.strip().startswith("|"):
            break
    return start_idx, end_idx


def _extract_existing_table_header(region_text: str | None, expected_col_count: int) -> tuple[str, str] | None:
    if not region_text:
        return None
    lines = region_text.splitlines()
    for i in range(len(lines) - 1):
        line1 = lines[i].strip()
        line2 = lines[i + 1].strip()
        if line1.startswith("|") and line2.startswith("|"):
            cells1 = [c.strip() for c in line1.strip("|").split("|")]
            cells2 = [c.strip() for c in line2.strip("|").split("|")]
            if len(cells1) == expected_col_count and len(cells2) == expected_col_count:
                if all(c == "---" or (c.startswith("---") and set(c) <= {"-", ":", " "}) for c in cells2):
                    return line1, line2
    return None


def _replace_generated_region(doc: str, section: str, new_content: str) -> str:
    pat = _marker_pattern(section)
    m = pat.search(doc)
    if not m:
        return doc
    replacement = f"<!-- ai-orch:generated {section} -->\n{new_content.strip()}\n<!-- /ai-orch:generated {section} -->"
    return doc[:m.start()] + replacement + doc[m.end():]


def adopt_markers(existing_index: str) -> str:
    updated = existing_index

    # 1. Next up
    pat_next = re.compile(r"^##\s+Next up\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m = pat_next.search(updated)
    if m:
        sec = m.group(0)
        if not _marker_pattern("next-up").search(sec):
            lines = sec.splitlines(keepends=True)
            start_idx, end_idx = _find_table_range(lines)
            if start_idx is not None and end_idx is not None:
                tbl = "".join(lines[start_idx:end_idx + 1]).strip()
                replacement = f"<!-- ai-orch:generated next-up -->\n{tbl}\n<!-- /ai-orch:generated next-up -->\n"
                new_sec = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx + 1:])
            else:
                new_sec = sec.rstrip() + "\n\n<!-- ai-orch:generated next-up -->\n<!-- /ai-orch:generated next-up -->\n\n"
            updated = updated[:m.start()] + new_sec + updated[m.end():]

    # 2. Tasks by category
    pat_cat = re.compile(r"^##\s+Tasks by category\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m = pat_cat.search(updated)
    if m:
        sec = m.group(0)
        if not _marker_pattern("tasks-by-category").search(sec):
            lines = sec.splitlines(keepends=True)
            start_idx = None
            end_idx = None
            for idx, line in enumerate(lines):
                if line.strip().startswith("### ") or (start_idx is None and line.strip().startswith("|")):
                    if start_idx is None:
                        start_idx = idx
                if line.strip().startswith("|"):
                    end_idx = idx
            if start_idx is not None and end_idx is not None and end_idx >= start_idx:
                cat_block = "".join(lines[start_idx:end_idx + 1]).strip()
                replacement = f"<!-- ai-orch:generated tasks-by-category -->\n{cat_block}\n<!-- /ai-orch:generated tasks-by-category -->\n"
                new_sec = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx + 1:])
            else:
                new_sec = sec.rstrip() + "\n\n<!-- ai-orch:generated tasks-by-category -->\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
            updated = updated[:m.start()] + new_sec + updated[m.end():]

    # 3. Decisions waiting
    pat_dec = re.compile(r"^##\s+Decisions waiting\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m = pat_dec.search(updated)
    if m:
        sec = m.group(0)
        if not _marker_pattern("decisions").search(sec):
            lines = sec.splitlines(keepends=True)
            start_idx, end_idx = _find_table_range(lines)
            if start_idx is not None and end_idx is not None:
                tbl = "".join(lines[start_idx:end_idx + 1]).strip()
                replacement = f"<!-- ai-orch:generated decisions -->\n{tbl}\n<!-- /ai-orch:generated decisions -->\n"
                new_sec = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx + 1:])
            else:
                new_sec = sec.rstrip() + "\n\n<!-- ai-orch:generated decisions -->\n<!-- /ai-orch:generated decisions -->\n\n"
            updated = updated[:m.start()] + new_sec + updated[m.end():]

    # 4. Done
    pat_done = re.compile(r"^##\s+Done\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m = pat_done.search(updated)
    if m:
        sec = m.group(0)
        if not _marker_pattern("done").search(sec):
            lines = sec.splitlines(keepends=True)
            start_idx, end_idx = _find_table_range(lines)
            if start_idx is not None and end_idx is not None:
                tbl = "".join(lines[start_idx:end_idx + 1]).strip()
                replacement = f"<!-- ai-orch:generated done -->\n{tbl}\n<!-- /ai-orch:generated done -->\n"
                new_sec = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx + 1:])
            else:
                new_sec = sec.rstrip() + "\n\n<!-- ai-orch:generated done -->\n<!-- /ai-orch:generated done -->\n\n"
            updated = updated[:m.start()] + new_sec + updated[m.end():]

    return updated


def _read_category_blurb(tasks_dir: pathlib.Path, category: str, existing_index: str) -> str:
    # Preserve existing category blurb from 00-INDEX.md if present
    pattern = re.compile(
        rf"^###\s+{re.escape(category)}\s*\n\n([^\n|][^\n]*)\n",
        re.MULTILINE,
    )
    m = pattern.search(existing_index)
    if m:
        return m.group(1).strip()

    readme_path = tasks_dir / category / "README.md"
    owner = "unassigned"
    goal_line = f"Tasks in `{category}`."
    if readme_path.is_file():
        rtext = readme_path.read_text(encoding="utf-8")
        om = re.search(r"^owner-session:\s*(.+)$", rtext, re.MULTILINE)
        if om:
            owner = om.group(1).strip()
        gm = re.search(r"^##\s+Goal and scope\s*\n+([^\n]+)", rtext, re.MULTILINE)
        if gm:
            first_sentence = gm.group(1).strip().split(". ")[0].rstrip(".")
            goal_line = f"{first_sentence}."
    return f"{goal_line} Owner session: {owner} ([README]({category}/README.md))."


def _extract_existing_category_order(existing_index: str) -> list[str]:
    cats: list[str] = []
    sec_text = existing_index
    m = re.search(r"^##\s+Tasks by category\b(.*?)(?=^## |\Z)", existing_index, re.MULTILINE | re.DOTALL)
    if m:
        sec_text = m.group(1)
    for cm in re.finditer(r"^###\s+([A-Za-z0-9_-]+)\s*$", sec_text, re.MULTILINE):
        cname = cm.group(1)
        if cname not in cats:
            cats.append(cname)
    return cats


def _extract_existing_initiative_next_up_rows(existing_index: str) -> list[str]:
    """Preserve initiative task rows (e.g. `01.1`, `03.1`) already listed in `## Next up`."""
    rows: list[str] = []
    m = re.search(r"^## Next up\b(.*?)(?=^## |\Z)", existing_index, re.MULTILINE | re.DOTALL)
    if not m:
        return rows
    for line in m.group(1).splitlines():
        line_s = line.strip()
        if not line_s.startswith("|"):
            continue
        cells = [c.strip() for c in line_s.strip("|").split("|")]
        if not cells:
            continue
        row_id = cells[0]
        if re.match(r"^\d{2,}\.\d+$", row_id) or row_id.startswith("INIT-"):
            rows.append(line_s)
    return rows


def render_synced_index(tasks_dir: pathlib.Path, existing_index: str, adopt: bool = False) -> str:
    emergent = discover_emergent_tasks(tasks_dir)
    initiatives = discover_initiatives(tasks_dir)
    active_tasks = [t for t in emergent if not t["in_done"] and t["canonical_state"] not in TERMINAL_STATES]
    done_tasks = [t for t in emergent if t["in_done"] or t["canonical_state"] in TERMINAL_STATES]

    active_tasks.sort(key=lambda t: (PRIORITY_SORT_KEY.get(t["priority"], 99), t["id"]))
    done_tasks.sort(key=lambda t: t["id"], reverse=True)

    resolved_ids: set[str] = set(t["id"] for t in emergent)
    for init in initiatives:
        resolved_ids.add(str(init["id"]))
        resolved_ids.add(f"INIT-{init['id']}")
        for sub_t in init.get("tasks", []):
            resolved_ids.add(sub_t["id"])
            resolved_ids.add(f"{init['id']}.{sub_t['id']}")

    if existing_index.strip():
        if not has_generated_markers(existing_index):
            if adopt:
                existing_index = adopt_markers(existing_index)
            else:
                raise ValueError(
                    "Index has no generated-region markers (<!-- ai-orch:generated <section> -->). "
                    "Run with --adopt to wrap existing tables in markers."
                )

    # 1. Next up section
    m_next = _marker_pattern("next-up").search(existing_index) if existing_index.strip() else None
    existing_next_region = m_next.group(1) if m_next else existing_index

    hdr_next, sep_next = _extract_existing_table_header(existing_next_region, 5) or (
        "| Id | Priority | Task | Executor | Handoff |",
        "| --- | --- | --- | --- | --- |",
    )
    next_up_lines = [hdr_next, sep_next]

    existing_next_rows: list[tuple[str, list[str], str]] = []
    if existing_next_region:
        for line in existing_next_region.splitlines():
            line_s = line.strip()
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Id", "---") or cells[0].startswith("---"):
                continue
            existing_next_rows.append((cells[0], cells, line_s))

    emergent_next_map = {t["id"]: t for t in active_tasks if t["next_up"] == "yes"}
    seen_next_ids: set[str] = set()

    for row_id, cells, raw_line in existing_next_rows:
        if re.match(r"^\d{2,}\.\d+$", row_id) or row_id.startswith("INIT-"):
            seen_next_ids.add(row_id)
            next_up_lines.append(raw_line)
        elif row_id in emergent_next_map:
            t = emergent_next_map[row_id]
            seen_next_ids.add(row_id)
            next_up_lines.append(
                f"| {t['id']} | {t['priority']} | [{t['title']}]({t['rel_path']}) | {t['executor']} | `{t['handoff']}` |"
            )
        elif row_id not in resolved_ids:
            seen_next_ids.add(row_id)
            pri = cells[1] if len(cells) > 1 else "P2"
            task_cell = cells[2] if len(cells) > 2 else "-"
            if not task_cell.endswith("(missing)"):
                task_cell = f"{task_cell} (missing)"
            exc = cells[3] if len(cells) > 3 else "unassigned"
            hnd = cells[4] if len(cells) > 4 else "-"
            next_up_lines.append(f"| {row_id} | {pri} | {task_cell} | {exc} | {hnd} |")

    for t in active_tasks:
        if t["next_up"] == "yes" and t["id"] not in seen_next_ids and len(seen_next_ids) < 5:
            seen_next_ids.add(t["id"])
            next_up_lines.append(
                f"| {t['id']} | {t['priority']} | [{t['title']}]({t['rel_path']}) | {t['executor']} | `{t['handoff']}` |"
            )

    next_up_content = "\n".join(next_up_lines)

    # 2. Tasks by category section
    m_cat = _marker_pattern("tasks-by-category").search(existing_index) if existing_index.strip() else None
    existing_cat_region = m_cat.group(1) if m_cat else existing_index

    existing_cat_order = _extract_existing_category_order(existing_index)
    discovered_cats: list[str] = []
    if tasks_dir.is_dir():
        for child in sorted(tasks_dir.iterdir()):
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and not child.name.startswith("_")
                and child.name not in RESERVED_DIRS
                and not INITIATIVE_DIR_RE.match(child.name)
            ):
                discovered_cats.append(child.name)
    for t in active_tasks:
        cat = t["category"] or t["folder_category"]
        if cat and cat not in discovered_cats:
            discovered_cats.append(cat)

    existing_by_cat: dict[str, list[tuple[str, list[str]]]] = {}
    existing_cat_headers: dict[str, tuple[str, str]] = {}
    if existing_cat_region:
        cat_matches = list(re.finditer(r"^###\s+([A-Za-z0-9_-]+)\s*$", existing_cat_region, re.MULTILINE))
        for i, cm in enumerate(cat_matches):
            cname = cm.group(1)
            start_pos = cm.end()
            end_pos = cat_matches[i + 1].start() if i + 1 < len(cat_matches) else len(existing_cat_region)
            block_text = existing_cat_region[start_pos:end_pos]
            hdr_pair = _extract_existing_table_header(block_text, 6)
            if hdr_pair:
                existing_cat_headers[cname] = hdr_pair
            existing_by_cat[cname] = []
            for line in block_text.splitlines():
                line_s = line.strip()
                if not line_s.startswith("|"):
                    continue
                cells = [c.strip() for c in line_s.strip("|").split("|")]
                if not cells or cells[0] in ("Id", "---") or cells[0].startswith("---"):
                    continue
                existing_by_cat[cname].append((cells[0], cells))

    all_cats = list(dict.fromkeys(discovered_cats))
    ordered_cats = [c for c in existing_cat_order if c in all_cats or c in existing_by_cat] + [
        c for c in all_cats if c not in existing_cat_order
    ]

    cat_lines: list[str] = []
    for idx_c, cat in enumerate(ordered_cats):
        if idx_c > 0:
            cat_lines.append("")
        blurb = _read_category_blurb(tasks_dir, cat, existing_cat_region or existing_index)
        hdr_cat, sep_cat = existing_cat_headers.get(
            cat,
            ("| Id | Priority | Task | State | Executor | Depends on |", "| --- | --- | --- | --- | --- | --- |"),
        )
        cat_lines.extend(
            [
                f"### {cat}",
                "",
                blurb,
                "",
                hdr_cat,
                sep_cat,
            ]
        )
        cat_tasks = {t["id"]: t for t in active_tasks if (t["category"] or t["folder_category"]) == cat}
        seen_cat_ids: set[str] = set()

        for row_id, cells in existing_by_cat.get(cat, []):
            if row_id in cat_tasks:
                t = cat_tasks[row_id]
                seen_cat_ids.add(row_id)
                cat_lines.append(
                    f"| {t['id']} | {t['priority']} | [{t['title']}]({t['rel_path']}) | "
                    f"{t['state']} | {t['executor']} | {t['depends_on_raw']} |"
                )
            elif row_id not in resolved_ids:
                seen_cat_ids.add(row_id)
                pri = cells[1] if len(cells) > 1 else "P2"
                task_cell = cells[2] if len(cells) > 2 else "-"
                if not task_cell.endswith("(missing)"):
                    task_cell = f"{task_cell} (missing)"
                st = cells[3] if len(cells) > 3 else "open"
                exc = cells[4] if len(cells) > 4 else "unassigned"
                dep = cells[5] if len(cells) > 5 else "-"
                cat_lines.append(f"| {row_id} | {pri} | {task_cell} | {st} | {exc} | {dep} |")

        new_cat_tasks = [t for tid, t in cat_tasks.items() if tid not in seen_cat_ids]
        new_cat_tasks.sort(key=lambda t: (PRIORITY_SORT_KEY.get(t["priority"], 99), t["id"]))
        for t in new_cat_tasks:
            seen_cat_ids.add(t["id"])
            cat_lines.append(
                f"| {t['id']} | {t['priority']} | [{t['title']}]({t['rel_path']}) | "
                f"{t['state']} | {t['executor']} | {t['depends_on_raw']} |"
            )

    cat_content = "\n".join(cat_lines)

    # 3. Decisions waiting section
    m_dec = _marker_pattern("decisions").search(existing_index) if existing_index.strip() else None
    existing_dec_region = m_dec.group(1) if m_dec else existing_index

    hdr_dec, sep_dec = _extract_existing_table_header(existing_dec_region, 4) or (
        "| Task / Initiative | Question (exact) | Decider | Blocks |",
        "| --- | --- | --- | --- |",
    )
    dec_lines = [hdr_dec, sep_dec]

    existing_dec_rows: list[tuple[str, list[str]]] = []
    if existing_dec_region:
        for line in existing_dec_region.splitlines():
            line_s = line.strip()
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Task", "Task / Initiative", "---") or cells[0].startswith("---"):
                continue
            if cells[0] != "-":
                existing_dec_rows.append((cells[0], cells))

    # Only tasks in state waiting or blocked with a decider belong in ## Decisions waiting
    qualifying_tasks: dict[str, dict[str, Any]] = {
        t["id"]: t
        for t in active_tasks
        if t["canonical_state"] in ("waiting", "blocked")
        and t["decider"]
        and t["decider"].strip() not in ("", "-")
    }

    blocks_map: dict[str, list[str]] = {tid: [] for tid in qualifying_tasks}
    for other in active_tasks:
        for dep in other["depends_on"]:
            if dep in blocks_map:
                blocks_map[dep].append(other["id"])

    existing_waiting_ids_without_dec = set()
    if existing_cat_region:
        for line in existing_cat_region.splitlines():
            line_s = line.strip()
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if len(cells) >= 4 and re.match(r"^T\d+$", cells[0]):
                tid, st = cells[0], cells[3]
                if normalize_state(st) in ("waiting", "blocked") and tid not in [r[0] for r in existing_dec_rows]:
                    existing_waiting_ids_without_dec.add(tid)

    seen_dec_ids: set[str] = set()

    # 1. Existing rows in original order
    for row_id, cells in existing_dec_rows:
        if row_id in qualifying_tasks:
            seen_dec_ids.add(row_id)
            wt = qualifying_tasks[row_id]
            # PRESERVE question cell (like Done Closed/Result); update only Decider and Blocks
            q_cell = cells[1] if len(cells) > 1 and cells[1] not in ("", "-") else ""
            if not q_cell:
                raw_dec = wt["decider"]
                q_cell = raw_dec.split(":", 1)[1].strip() if ":" in raw_dec else raw_dec
            raw_dec = wt["decider"]
            who = raw_dec.split(":", 1)[0].strip() if ":" in raw_dec else raw_dec
            blocks_str = ", ".join(blocks_map.get(row_id, [])) or "-"
            dec_lines.append(f"| {row_id} | {q_cell} | {who} | {blocks_str} |")
        elif row_id not in resolved_ids:
            seen_dec_ids.add(row_id)
            task_cell = f"{row_id} (missing)" if not row_id.endswith("(missing)") else row_id
            q_cell = cells[1] if len(cells) > 1 else "-"
            dec_cell = cells[2] if len(cells) > 2 else "-"
            blk_cell = cells[3] if len(cells) > 3 else "-"
            dec_lines.append(f"| {task_cell} | {q_cell} | {dec_cell} | {blk_cell} |")

    # 2. Append new qualifying tasks
    new_dec_tasks = [
        t for tid, t in qualifying_tasks.items()
        if tid not in seen_dec_ids and tid not in existing_waiting_ids_without_dec
    ]
    for wt in new_dec_tasks:
        seen_dec_ids.add(wt["id"])
        raw_dec = wt["decider"]
        if ":" in raw_dec:
            who, question = [p.strip() for p in raw_dec.split(":", 1)]
        else:
            who, question = raw_dec, raw_dec
        blocks_str = ", ".join(blocks_map.get(wt["id"], [])) or "-"
        dec_lines.append(f"| {wt['id']} | {question} | {who} | {blocks_str} |")

    if len(dec_lines) == 2:
        dec_lines.append("| - | None. | - | - |")
    dec_content = "\n".join(dec_lines)

    # 4. Done section
    m_done = _marker_pattern("done").search(existing_index) if existing_index.strip() else None
    existing_done_region = m_done.group(1) if m_done else existing_index

    hdr_done, sep_done = _extract_existing_table_header(existing_done_region, 4) or (
        "| Id | Task | Result | Closed |",
        "| --- | --- | --- | --- |",
    )
    done_lines = [hdr_done, sep_done]

    existing_done_rows: list[tuple[str, list[str]]] = []
    if existing_done_region:
        for line in existing_done_region.splitlines():
            line_s = line.strip()
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Id", "---") or cells[0].startswith("---"):
                continue
            if cells[0] != "-":
                existing_done_rows.append((cells[0], cells))

    done_tasks_map = {dt["id"]: dt for dt in done_tasks}
    seen_done_ids: set[str] = set()

    for row_id, cells in existing_done_rows:
        if row_id in done_tasks_map:
            dt = done_tasks_map[row_id]
            seen_done_ids.add(row_id)
            task_cell = f"[{dt['title']}]({dt['rel_path']})"
            res_val = cells[2] if len(cells) > 2 and cells[2] not in ("", "-") else dt["state"]
            closed_val = cells[3] if len(cells) > 3 and cells[3] not in ("", "-") else _git_closed_date(tasks_dir, dt["rel_path"])
            done_lines.append(f"| {row_id} | {task_cell} | {res_val} | {closed_val} |")
        elif row_id not in resolved_ids:
            seen_done_ids.add(row_id)
            task_cell = cells[1] if len(cells) > 1 else "-"
            if not task_cell.endswith("(missing)"):
                task_cell = f"{task_cell} (missing)"
            res_val = cells[2] if len(cells) > 2 else "done"
            closed_val = cells[3] if len(cells) > 3 else datetime.date.today().isoformat()
            done_lines.append(f"| {row_id} | {task_cell} | {res_val} | {closed_val} |")

    new_done_tasks = [dt for dt_id, dt in done_tasks_map.items() if dt_id not in seen_done_ids]
    new_done_tasks.sort(key=lambda t: t["id"], reverse=True)
    for dt in new_done_tasks:
        dt_id = dt["id"]
        seen_done_ids.add(dt_id)
        task_cell = f"[{dt['title']}]({dt['rel_path']})"
        res_val = dt["state"]
        closed_val = _git_closed_date(tasks_dir, dt["rel_path"])
        done_lines.append(f"| {dt_id} | {task_cell} | {res_val} | {closed_val} |")

    done_content = "\n".join(done_lines)

    if not existing_index.strip():
        return (
            "# Task Index\n\n"
            "## Next up\n\n"
            f"<!-- ai-orch:generated next-up -->\n{next_up_content}\n<!-- /ai-orch:generated next-up -->\n\n"
            "## Tasks by category\n\n"
            f"<!-- ai-orch:generated tasks-by-category -->\n{cat_content}\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
            "## Decisions waiting\n\n"
            f"<!-- ai-orch:generated decisions -->\n{dec_content}\n<!-- /ai-orch:generated decisions -->\n\n"
            "## Done\n\n"
            f"<!-- ai-orch:generated done -->\n{done_content}\n<!-- /ai-orch:generated done -->\n"
        )

    updated = existing_index
    updated = _replace_generated_region(updated, "next-up", next_up_content)
    updated = _replace_generated_region(updated, "tasks-by-category", cat_content)
    updated = _replace_generated_region(updated, "decisions", dec_content)
    updated = _replace_generated_region(updated, "done", done_content)
    return updated


# ---------------------------------------------------------------------------
# CLI Subcommands
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    emergent = discover_emergent_tasks(tasks_dir)
    initiatives = discover_initiatives(tasks_dir)

    all_tasks: list[dict[str, Any]] = list(emergent)
    for init in initiatives:
        init_st = init.get("status", "open")
        for sub_t in init.get("tasks", []):
            sub_id = sub_t["id"]
            if not (sub_id.startswith(init["id"]) or sub_id.startswith("T") or sub_id.startswith(f"INIT-{init['id']}")):
                sub_id = f"{init['id']}.{sub_id}"
            all_tasks.append(
                {
                    "kind": "initiative_task",
                    "id": sub_id,
                    "title": sub_t["title"],
                    "category": init.get("slug", init.get("folder", "initiative")),
                    "priority": sub_t.get("priority", "P1"),
                    "priority_reason": sub_t.get("priority_reason", f"Subtask of Initiative #{init['id']}"),
                    "next_up": "yes" if init_st == "in progress" and sub_t.get("state") != "done" else "no",
                    "state": sub_t.get("state", init_st),
                    "executor": sub_t.get("executor", "kilo"),
                    "handoff": sub_t.get("handoff", f"Work on task {sub_id} in {init.get('rel_path')}"),
                    "file_path": str(tasks_dir / init["rel_path"]),
                    "in_done": sub_t.get("state", init_st) == "done",
                }
            )
        if not init.get("tasks"):
            all_tasks.append(
                {
                    "kind": "initiative",
                    "id": f"INIT-{init['id']}",
                    "title": init["title"],
                    "category": init.get("slug", init.get("folder", "initiative")),
                    "priority": "P1",
                    "priority_reason": f"Initiative container #{init['id']}",
                    "next_up": "yes" if init_st == "in progress" else "no",
                    "state": init_st,
                    "executor": "architect",
                    "handoff": f"Review plan for Initiative #{init['id']} in {init.get('rel_path')}",
                    "file_path": str(tasks_dir / init["rel_path"]),
                    "in_done": init_st == "done",
                }
            )

    payload = {
        "ok": True,
        "tasks_dir": str(tasks_dir),
        "emergent_tasks": emergent,
        "initiatives": initiatives,
        "all_tasks": all_tasks,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"Tasks dir  : {tasks_dir}")
        print(f"Initiatives: {len(initiatives)}")
        for init in initiatives:
            print(f"  [{init['id']}] {init['title']} ({init['location']}, {len(init['tasks'])} tasks)")
        print(f"Emergent   : {len(emergent)}")
        for t in emergent:
            loc = "done" if t["in_done"] else t["category"]
            print(f"  [{t['id']}] ({t['priority']}, {t['state']}, exec={t['executor']}, {loc}) {t['title']}")
        print(f"Total tasks: {len(all_tasks)}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    errors, warnings, emergent, initiatives = validate_tasks_tree(tasks_dir)
    ok = len(errors) == 0
    payload = {
        "ok": ok,
        "tasks_dir": str(tasks_dir),
        "emergent_count": len(emergent),
        "initiative_count": len(initiatives),
        "errors": errors,
        "warnings": warnings,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        for w in warnings:
            print(f"[WARN] {w}")
        for e in errors:
            print(f"[FAIL] {e}")
        if ok:
            print(f"[ok] validated {len(emergent)} emergent task(s) and {len(initiatives)} initiative(s) in {tasks_dir}")
    return 0 if ok else 1


def cmd_transition(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, payload = transition_task(
        tasks_dir=tasks_dir,
        task_id=args.task_id,
        new_state=args.new_state,
        actor=args.actor,
        verifier=args.verifier,
        reason=args.reason,
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        if ok:
            print(f"[ok] {args.task_id}: {payload['old_state']!r} -> {payload['new_state']!r} ({payload['rel_path']})")
        else:
            print(f"[FAIL] {payload['error']}", file=sys.stderr)
    return 0 if ok else 1


def cmd_sync_index(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    index_path = tasks_dir / "00-INDEX.md"
    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    current_hash = _file_sha256(index_path)

    adopt = getattr(args, "adopt", False)
    apply_flag = getattr(args, "apply", False)
    check_flag = getattr(args, "check", False)
    expect_hash = getattr(args, "expect_hash", None)

    # 1. Hash verification if expect_hash is given
    if expect_hash is not None:
        if current_hash.lower() != expect_hash.lower():
            err_msg = f"Index hash mismatch: expected {expect_hash}, got {current_hash}"
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"ok": False, "applied": False, "error": err_msg, "hash": current_hash, "path": str(index_path)},
                        indent=2,
                    )
                )
            else:
                print(f"[FAIL] {err_msg}", file=sys.stderr)
            return 1

    has_markers = has_generated_markers(existing) if existing.strip() else True

    # 2. Check adopt + apply requires --expect-hash
    if adopt and apply_flag:
        if expect_hash is None:
            err_msg = "Adopting markers with --apply requires --expect-hash <sha256>."
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"ok": False, "applied": False, "error": err_msg, "hash": current_hash, "path": str(index_path)},
                        indent=2,
                    )
                )
            else:
                print(f"[FAIL] {err_msg}", file=sys.stderr)
            return 1

    # 3. Check plain --apply on an index without markers
    if existing.strip() and not has_markers and not adopt and apply_flag:
        err_msg = (
            f"Index {index_path} has no generated-region markers "
            "(<!-- ai-orch:generated <section> -->). Run with --adopt to preview, then --adopt --apply --expect-hash <hash>."
        )
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"ok": False, "applied": False, "error": err_msg, "hash": current_hash, "path": str(index_path)},
                    indent=2,
                )
            )
        else:
            print(f"[FAIL] {err_msg}", file=sys.stderr)
        return 1

    # 4. Render
    try:
        rendered = render_synced_index(tasks_dir, existing, adopt=adopt)
    except ValueError as e:
        err_msg = str(e)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"ok": False, "applied": False, "error": err_msg, "hash": current_hash, "path": str(index_path)},
                    indent=2,
                )
            )
        else:
            print(f"[FAIL] {err_msg}", file=sys.stderr)
        return 1

    in_sync = existing == rendered

    diff_lines = list(
        difflib.unified_diff(
            existing.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=str(index_path),
            tofile=f"{index_path} (rendered)",
        )
    )
    diff_str = "".join(diff_lines)

    # 5. Adopt alone (without --apply) is PREVIEW only: prints diff and writes nothing
    if adopt and not apply_flag:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "applied": False,
                        "adopted": False,
                        "in_sync": in_sync,
                        "diff": diff_str,
                        "hash": current_hash,
                        "path": str(index_path),
                    },
                    indent=2,
                )
            )
        else:
            if diff_str:
                sys.stdout.write(diff_str)
            else:
                print(f"[ok] {index_path} already has markers and is in sync")
        return 0

    # 6. Check mode (--check without adopt)
    if check_flag:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": in_sync,
                        "in_sync": in_sync,
                        "diff": diff_str,
                        "hash": current_hash,
                        "path": str(index_path),
                    },
                    indent=2,
                )
            )
        else:
            if in_sync:
                print(f"[ok] {index_path} is in sync with task headers")
            else:
                if diff_str:
                    sys.stdout.write(diff_str)
                print(f"[FAIL] {index_path} is out of sync with task headers", file=sys.stderr)
        return 0 if in_sync else 1

    # 7. Apply mode: either normal --apply (on marked index) or --adopt --apply --expect-hash
    if apply_flag:
        _atomic_write_text(index_path, rendered, encoding="utf-8")
        new_hash = _file_sha256(index_path)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "applied": True,
                        "adopted": adopt,
                        "path": str(index_path),
                        "hash": new_hash,
                    },
                    indent=2,
                )
            )
        else:
            action = "adopted and updated" if adopt else "updated"
            print(f"[ok] {action} {index_path}")
        return 0

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "ok": True,
                    "applied": False,
                    "in_sync": in_sync,
                    "diff": diff_str,
                    "hash": current_hash,
                    "path": str(index_path),
                    "rendered": rendered,
                },
                indent=2,
            )
        )
    else:
        sys.stdout.write(rendered)
    return 0


def upgrade_tasks_tree(tasks_dir: pathlib.Path) -> dict[str, Any]:
    """Upgrade a tasks/ directory to the latest task-pipeline v0.3.0 convention:
      1. Updates tasks/AGENTS.md with canonical task-pipeline rules and skill names.
      2. Ensures standard directories exist (_inbox/to-analyze, _inbox/analyzed).
      3. Regenerates/updates 00-INDEX.md with standard tables (Initiatives, Specs, Next up, Tasks by category, Decisions waiting, Done).
      4. Validates the upgraded tree.
    """
    upgraded_files: list[str] = []

    # 1. Update tasks/AGENTS.md
    agents_md = tasks_dir / "AGENTS.md"
    existing_agents = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else ""
    if existing_agents.strip() != CANONICAL_TASKS_AGENTS_MD.strip():
        agents_md.write_text(CANONICAL_TASKS_AGENTS_MD, encoding="utf-8")
        upgraded_files.append(str(agents_md))

    # 2. Ensure standard directories
    (tasks_dir / "_inbox" / "to-analyze").mkdir(parents=True, exist_ok=True)
    (tasks_dir / "_inbox" / "analyzed").mkdir(parents=True, exist_ok=True)

    # 3. Re-sync 00-INDEX.md
    idx_path = tasks_dir / "00-INDEX.md"
    existing_idx = idx_path.read_text(encoding="utf-8") if idx_path.is_file() else ""
    rendered_idx = render_synced_index(tasks_dir, existing_idx, adopt=True)
    if existing_idx.strip() != rendered_idx.strip():
        _atomic_write_text(idx_path, rendered_idx, encoding="utf-8")
        upgraded_files.append(str(idx_path))

    # 4. Validate
    errors, warnings, emergent, initiatives = validate_tasks_tree(tasks_dir)

    return {
        "ok": len(errors) == 0,
        "upgraded_files": upgraded_files,
        "emergent_count": len(emergent),
        "initiative_count": len(initiatives),
        "errors": errors,
        "warnings": warnings,
    }


def cmd_upgrade(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    res = upgrade_tasks_tree(tasks_dir)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res["upgraded_files"]:
            print(f"[ok] Upgraded {len(res['upgraded_files'])} file(s) in {tasks_dir}:")
            for f in res["upgraded_files"]:
                print(f"  - {f}")
        else:
            print(f"[ok] {tasks_dir} is already up-to-date with latest task-pipeline convention.")
        if res["warnings"]:
            for w in res["warnings"]:
                print(f"[WARN] {w}")
        if res["errors"]:
            for e in res["errors"]:
                print(f"[FAIL] {e}")
    return 0 if res["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="Output structured JSON on stdout")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List all emergent tasks and initiatives in tasks/")
    p_list.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_list.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_list.set_defaults(func=cmd_list)

    p_val = sub.add_parser("validate", help="Validate task headers, IDs, sections, and dependency DAG")
    p_val.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_val.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_val.set_defaults(func=cmd_validate)

    p_tr = sub.add_parser("transition", help="Transition a task to a new state enforcing state-machine guards")
    p_tr.add_argument("task_id", help="Task ID (e.g. T001)")
    p_tr.add_argument("new_state", help="New state (e.g. 'in progress', 'delivered', 'verified', 'bounced', 'done')")
    p_tr.add_argument("--actor", default=None, help="Actor performing the transition (e.g. kilo, claude, owner)")
    p_tr.add_argument("--verifier", default=None, help="Independent verifier identifier (e.g. claude:deep-reasoning, blind-subagent:deep-reasoning, owner)")
    p_tr.add_argument("--reason", default=None, help="Bounce findings (B1..Bn), caveat reason, or transition note")
    p_tr.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_tr.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_tr.set_defaults(func=cmd_transition)

    p_sync = sub.add_parser("sync-index", help="Deterministically synchronize tasks/00-INDEX.md tables from task headers")
    p_sync.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sync.add_argument("--apply", action="store_true", help="Write updated 00-INDEX.md in place")
    p_sync.add_argument("--check", action="store_true", help="Exit non-zero if 00-INDEX.md is out of sync")
    p_sync.add_argument("--adopt", action="store_true", help="Preview wrapping existing generated tables in markers (apply with --adopt --apply --expect-hash <hash>)")
    p_sync.add_argument("--expect-hash", default=None, help="Refuse to apply if current index SHA256 does not match this hash")
    p_sync.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sync.set_defaults(func=cmd_sync_index)

    p_upg = sub.add_parser("upgrade", help="Upgrade a tasks/ directory to the latest task-pipeline v0.3.0 convention")
    p_upg.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_upg.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_upg.set_defaults(func=cmd_upgrade)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
