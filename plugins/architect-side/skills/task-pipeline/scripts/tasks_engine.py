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
import json
import pathlib
import re
import shutil
import subprocess
import sys
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
            inline_tasks = [
                {"id": tm.group(1), "title": tm.group(2).strip()}
                for tm in INLINE_TASK_HEADING_RE.finditer(text)
            ]
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
                        }
                    )
            initiatives.append(
                {
                    "id": num,
                    "slug": slug,
                    "folder": entry.name,
                    "title": title,
                    "location": location,
                    "rel_path": plan_path.relative_to(tasks_dir).as_posix(),
                    "has_summary": (entry / "summary.md").is_file(),
                    "tasks": expanded_tasks if expanded_tasks else inline_tasks,
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
    m = re.search(r"^## Tasks by category\b(.*?)(?=^## |\Z)", existing_index, re.MULTILINE | re.DOTALL)
    if not m:
        return cats
    for cm in re.finditer(r"^###\s+([A-Za-z0-9_-]+)\s*$", m.group(1), re.MULTILINE):
        cats.append(cm.group(1))
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
        if re.match(r"^\d{2,}\.\d+$", row_id):
            rows.append(line_s)
    return rows


def render_synced_index(tasks_dir: pathlib.Path, existing_index: str) -> str:
    emergent = discover_emergent_tasks(tasks_dir)
    active_tasks = [t for t in emergent if not t["in_done"] and t["canonical_state"] not in TERMINAL_STATES]
    done_tasks = [t for t in emergent if t["in_done"] or t["canonical_state"] in TERMINAL_STATES]

    active_tasks.sort(key=lambda t: (PRIORITY_SORT_KEY.get(t["priority"], 99), t["id"]))
    done_tasks.sort(key=lambda t: t["id"], reverse=True)

    # 1. Next up section (preserve any initiative rows + emergent next-up=yes rows, sorted by priority or capped)
    init_next_rows = _extract_existing_initiative_next_up_rows(existing_index)
    emergent_next = [t for t in active_tasks if t["next_up"] == "yes"]

    next_up_lines = [
        "## Next up",
        "",
        "| Id | Priority | Task | Executor | Handoff |",
        "| --- | --- | --- | --- | --- |",
    ]
    if init_next_rows:
        # Keep initiative rows and interleave/append emergent next-up rows (avoiding duplicate IDs)
        seen_next_ids: set[str] = set()
        for r in init_next_rows:
            rid = [c.strip() for c in r.strip("|").split("|")][0]
            seen_next_ids.add(rid)
            next_up_lines.append(r)
        for t in emergent_next:
            if t["id"] not in seen_next_ids and len(seen_next_ids) < 5:
                seen_next_ids.add(t["id"])
                next_up_lines.append(
                    f"| {t['id']} | {t['priority']} | [{t['title']}]({t['rel_path']}) | {t['executor']} | `{t['handoff']}` |"
                )
    else:
        for t in emergent_next[:5]:
            next_up_lines.append(
                f"| {t['id']} | {t['priority']} | [{t['title']}]({t['rel_path']}) | {t['executor']} | `{t['handoff']}` |"
            )
    next_up_section = "\n".join(next_up_lines) + "\n"

    # 2. Tasks by category section
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

    ordered_cats = [c for c in existing_cat_order if c in discovered_cats] + [
        c for c in discovered_cats if c not in existing_cat_order
    ]

    cat_lines = ["## Tasks by category", ""]
    for idx_c, cat in enumerate(ordered_cats):
        if idx_c > 0:
            cat_lines.append("")
        blurb = _read_category_blurb(tasks_dir, cat, existing_index)
        cat_lines.extend(
            [
                f"### {cat}",
                "",
                blurb,
                "",
                "| Id | Priority | Task | State | Executor | Depends on |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        cat_tasks = [t for t in active_tasks if (t["category"] or t["folder_category"]) == cat]
        for t in cat_tasks:
            cat_lines.append(
                f"| {t['id']} | {t['priority']} | [{t['title']}]({t['rel_path']}) | "
                f"{t['state']} | {t['executor']} | {t['depends_on_raw']} |"
            )
    cat_section = "\n".join(cat_lines) + "\n"

    # 3. Decisions waiting section
    waiting_tasks = [t for t in active_tasks if t["decider"] and t["decider"] != "-"]
    dec_lines = [
        "## Decisions waiting",
        "",
        "| Task / Initiative | Question (exact) | Decider | Blocks |",
        "| --- | --- | --- | --- |",
    ]
    if waiting_tasks:
        # Find what each waiting task blocks
        blocks_map: dict[str, list[str]] = {t["id"]: [] for t in waiting_tasks}
        for other in active_tasks:
            for dep in other["depends_on"]:
                if dep in blocks_map:
                    blocks_map[dep].append(other["id"])
        for wt in waiting_tasks:
            raw_dec = wt["decider"]
            if ":" in raw_dec:
                who, question = [p.strip() for p in raw_dec.split(":", 1)]
            else:
                who, question = raw_dec, raw_dec
            blocks_str = ", ".join(blocks_map.get(wt["id"], [])) or "-"
            dec_lines.append(f"| {wt['id']} | {question} | {who} | {blocks_str} |")
    else:
        dec_lines.append(
            "| - | None currently blocking — architectural direction locked with owner on 2026-10-15 (see `docs/03`–`05`). | - | - |"
        )
    dec_section = "\n".join(dec_lines) + "\n"

    # 4. Done section
    done_lines = [
        "## Done",
        "",
        "| Id | Task | Result | Closed |",
        "| --- | --- | --- | --- |",
    ]
    today_str = datetime.date.today().isoformat()
    for dt in done_tasks:
        done_lines.append(
            f"| {dt['id']} | [{dt['title']}]({dt['rel_path']}) | {dt['state']} | {today_str} |"
        )
    done_section = "\n".join(done_lines) + "\n"

    if not existing_index.strip():
        return (
            "# Task Index\n\n"
            f"{next_up_section}\n"
            f"{cat_section}\n"
            f"{dec_section}\n"
            f"{done_section}"
        )

    updated = existing_index

    def _replace_section(doc: str, heading: str, replacement: str) -> str:
        pat = re.compile(rf"^## {re.escape(heading)}\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
        if pat.search(doc):
            return pat.sub(replacement.rstrip() + "\n\n", doc)
        return doc.rstrip() + "\n\n" + replacement.rstrip() + "\n"

    updated = _replace_section(updated, "Next up", next_up_section)
    updated = _replace_section(updated, "Tasks by category", cat_section)
    updated = _replace_section(updated, "Decisions waiting", dec_section)
    updated = _replace_section(updated, "Done", done_section)
    return re.sub(r"\n{3,}", "\n\n", updated).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI Subcommands
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    emergent = discover_emergent_tasks(tasks_dir)
    initiatives = discover_initiatives(tasks_dir)
    payload = {
        "ok": True,
        "tasks_dir": str(tasks_dir),
        "emergent_tasks": emergent,
        "initiatives": initiatives,
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
    rendered = render_synced_index(tasks_dir, existing)
    in_sync = existing == rendered

    if args.check:
        if getattr(args, "json", False):
            print(json.dumps({"ok": in_sync, "in_sync": in_sync, "path": str(index_path)}, indent=2))
        elif in_sync:
            print(f"[ok] {index_path} is in sync with task headers")
        else:
            print(f"[FAIL] {index_path} is out of sync with task headers")
        return 0 if in_sync else 1

    if args.apply:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(rendered, encoding="utf-8")
        if getattr(args, "json", False):
            print(json.dumps({"ok": True, "applied": True, "path": str(index_path)}, indent=2))
        else:
            print(f"[ok] updated {index_path}")
        return 0

    if getattr(args, "json", False):
        print(
            json.dumps(
                {"ok": True, "applied": False, "in_sync": in_sync, "path": str(index_path), "rendered": rendered},
                indent=2,
            )
        )
    else:
        sys.stdout.write(rendered)
    return 0


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
    p_sync.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sync.set_defaults(func=cmd_sync_index)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
