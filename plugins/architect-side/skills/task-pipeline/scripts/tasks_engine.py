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
import contextlib
import datetime
import difflib
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

try:
    import orchestration_registry
except ImportError:
    _repo_root = pathlib.Path(__file__).resolve().parents[5]
    _scripts_dir = _repo_root / "scripts"
    if _scripts_dir.is_dir() and str(_scripts_dir) not in sys.path:
        sys.path.insert(0, str(_scripts_dir))
    try:
        import orchestration_registry
    except ImportError:
        orchestration_registry = None  # type: ignore

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
    "verify-by",
    "verify_by",
    "size",
    "kind",
    "labels",
    "branch",
    "worktree",
    "run-id",
    "use-cases",
    "use_cases",
    "coordinates",
    "moved-to",
    "conditions",
    "waiting-on",
    "waiting_on",
    "short",
)
OPTIONAL_HEADER_FIELDS: tuple[str, ...] = OPTIONAL_EXTENSION_FIELDS

VALID_KINDS: set[str] = {"feature", "bug", "fix", "chore", "docs", "investigation"}
LABEL_RE: re.Pattern = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")

MICRO_HEADER_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "kind",
    "priority",
    "state",
    "executor",
    "paths",
    "depends-on",
    "size",
    "labels",
    "conditions",
    "waiting-on",
    "waiting_on",
    "short",
)

MICRO_MANDATORY_HEADER_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "kind",
    "priority",
    "state",
    "executor",
    "paths",
    "depends-on",
)

VALID_SIZES: set[str] = {"XS", "S", "M", "L", "XL"}
SIZE_WEIGHTS: dict[str, int] = {"XS": 1, "S": 2, "M": 3, "L": 5, "XL": 8}

ALL_ALLOWED_HEADER_FIELDS: set[str] = set(CORE_HEADER_FIELDS) | set(OPTIONAL_EXTENSION_FIELDS)

PRIORITIES: set[str] = {"P0", "P1", "P2", "P3"}
PRIORITY_SORT_KEY: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
NEXT_UP_VALUES: set[str] = {"yes", "no"}
PROFILES: set[str] = {"deep-reasoning", "orchestration", "bulk-execution", "exploration"}
VERIFICATION_MODES: set[str] = {"self", "independent-session", "cross-agent", "panel", "owner"}

USE_CASE_ID_RE: re.Pattern = re.compile(r"^UC\d{3,}$")
USE_CASE_STATUSES: set[str] = {"draft", "active", "verified", "failing", "partial"}
USE_CASE_VERIFICATION_TYPES: set[str] = {"automated-probe", "e2e", "code-audit", "api-probe"}
USE_CASE_MANDATORY_HEADER_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "actor",
    "status",
    "priority",
    "linked-tasks",
    "verification-type",
    "last-tested",
    "last-verdict",
)
USE_CASE_OPTIONAL_HEADER_FIELDS: tuple[str, ...] = (
    "short",
)
USE_CASE_HEADER_FIELDS: tuple[str, ...] = USE_CASE_MANDATORY_HEADER_FIELDS + USE_CASE_OPTIONAL_HEADER_FIELDS

CANONICAL_STATES: set[str] = {
    "open",
    "in progress",
    "paused",
    "waiting",
    "blocked",
    "delivered",
    "bounced",
    "verified",
    "done",
    "done with a caveat",
    "dropped",
    "moved",
}

TERMINAL_STATES: set[str] = {"done", "done with a caveat", "dropped", "moved"}

# Legal state transitions (canonical base state -> allowed target canonical base states)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in progress", "waiting", "blocked", "paused", "dropped"},
    "in progress": {"waiting", "blocked", "paused", "delivered", "dropped"},
    "paused": {"in progress", "open", "waiting", "blocked", "dropped"},
    "waiting": {"in progress", "blocked", "paused", "open", "dropped"},
    "blocked": {"in progress", "waiting", "paused", "open", "dropped"},
    "delivered": {"verified", "bounced", "paused", "done with a caveat", "dropped"},
    "bounced": {"in progress", "waiting", "blocked", "paused", "dropped"},
    "verified": {"done", "done with a caveat", "bounced", "dropped"},
    "done": set(),
    "done with a caveat": set(),
    "dropped": set(),
    "moved": set(),
}

REQUIRED_SECTIONS: tuple[str, ...] = ("## Goal", "## Steps", "## Verification")
RESERVED_DIRS: set[str] = {"_inbox", "_reviews", "specs", "done", "merged", "notes", "reviews", "questions", "use-cases"}

STEP_ITEM_RE = re.compile(r"^(\s*[-*]|\s*\d+\.)\s+\[([ xX])\]\s*(.*)$")
STEP_PLACEHOLDER_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(?:\[[ xX]\]\s+)?(?:TODO:\s*)?Step\s+1\.?\s*$", re.IGNORECASE)
VERIFICATION_PLACEHOLDER_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(?:\[[ xX]\]\s+)?(?:TODO:\s*)?Command or check(?:\s+that proves completion)?\.?\s*$", re.IGNORECASE)

QUESTION_MANDATORY_HEADER_FIELDS: tuple[str, ...] = (
    "id",
    "question",
    "status",
    "blocks",
    "decider",
    "asked-by",
    "asked",
    "origin-run",
    "open-answer",
    "recommended",
)
QUESTION_OPTIONAL_HEADER_FIELDS: tuple[str, ...] = (
    "applied",
    "moved-to",
    "reason",
    "short",
)
QUESTION_HEADER_FIELDS: tuple[str, ...] = QUESTION_MANDATORY_HEADER_FIELDS + QUESTION_OPTIONAL_HEADER_FIELDS

QUESTION_STATUSES: set[str] = {"open", "answered", "withdrawn", "moved"}
QUESTION_ID_RE = re.compile(r"^Q\d{3,}$")
QUESTION_FILE_RE = re.compile(r"^(Q\d{3,})-([a-z0-9-]+)\.md$")
OPTION_LINE_RE = re.compile(r"^-\s+\*\*([A-Za-z0-9]+)\*\*\s+[—–-]\s+(.+?)(?::\s*(.*))?$")

NOTE_MANDATORY_HEADER_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "kind",
    "status",
    "created",
    "author",
    "about",
    "produced",
    "processed-by",
)
NOTE_OPTIONAL_HEADER_FIELDS: tuple[str, ...] = (
    "short",
)
NOTE_HEADER_FIELDS: tuple[str, ...] = NOTE_MANDATORY_HEADER_FIELDS + NOTE_OPTIONAL_HEADER_FIELDS
NOTE_KINDS: set[str] = {"note", "bug", "feature", "idea", "request", "question"}
NOTE_STATUSES: set[str] = {"draft", "ready", "processing", "processed", "discarded"}
NOTE_ID_RE = re.compile(r"^N\d{3,}$")
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS_PER_NOTE = 30
MAX_ATTACHMENTS_PER_TASK = 30
IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
TEXT_EXTENSIONS: set[str] = {
    ".txt", ".log", ".md", ".json", ".yaml", ".yml", ".toml",
    ".csv", ".xml", ".diff", ".patch", ".html", ".js", ".ts",
    ".tsx", ".py", ".java", ".sh", ".sql", ".ini", ".cfg",
    ".conf", ".properties",
}

CANONICAL_TASKS_AGENTS_MD = """# tasks/ convention (task-pipeline + emergent tasks)

Short copy of the `task-pipeline` skill (`plugins/architect-side/skills/task-pipeline/`). Self-contained so this repository's `tasks/` tree works with or without the VS Code extension, the broker MCP server, or the `ai-orch` CLI installed.

- **Three progressive ways to use `tasks/` (no hard dependency on extension or MCP):**
  1. **Plain Markdown + Git (zero install — no extension, no MCP, no CLI required):** Every file under `tasks/` (`00-INDEX.md`, `CONTEXT.md`, `AGENTS.md`, `NN-<slug>/plan.md`, `<category>/T###-<slug>.md`, `questions/Q###-<slug>.md`, `_inbox/`) is plain Markdown. Create, edit, transition, and close (`git mv` to `tasks/done/<category>/`) files directly following the format rules below, and update the corresponding row inside the `<!-- ai-orch:generated ... -->` markers in `00-INDEX.md`.
  2. **Standalone CLI (no extension or MCP required):** Run `~/.local/bin/ai-orch tasks …` (or the stdlib-only `python3 .claude/skills/task-pipeline/scripts/tasks_engine.py …` / `python3 <path-to>/tasks_engine.py …`) to create, transition, validate (`tasks validate`), and sync (`tasks sync-index --apply`).
  3. **Broker MCP / Web UI / VS Code Extension (when installed):** Use the `ai-orchestration` MCP tools (`tasks.*`, `questions.*`, `inbox.add_note`) or the UI dashboard.
- **Cross-framework skill loading (any AI assistant / framework):** Claude Code loads `.claude/skills/` and Kilo Code loads `.kilo/skills/`. Any other AI coding framework or assistant (Codex, Gemini CLI, Copilot, Cursor, etc.) that reads `AGENTS.md` without native `.claude/skills/` discovery MUST read the project-versioned orchestration skills directly from `.claude/skills/<skill>/SKILL.md` (specifically `.claude/skills/task-pipeline/SKILL.md`, `.claude/skills/orchestration-workflow/SKILL.md`, `.claude/skills/task-spec-authoring/SKILL.md`, `.claude/skills/executor-contract/SKILL.md`) and use `python3 .claude/skills/task-pipeline/scripts/tasks_engine.py` when `ai-orch` is not on `PATH`.
- **Pipeline for large multi-task initiatives:** `_inbox/to-analyze/` → `specs/<slug>.md` → `NN-<slug>/plan.md` (tasks `### NN.T - <title>` followed by `- **Status:** \\`<state>\\` · ...`, sized one-per-commit, inline or expanded) → `done/NN-<slug>/` (with `summary.md`) → `merged/NN-<slug>/`.
- **Emergent tasks (`<category>/T###-<slug>`): Capture first, then continue.** Work that appears mid-session becomes a task file at once; it does not stay in the session context.
- **Ids & citations:** `T###`, unique across `done/` too; reserve the id by creating the file immediately. Always cite tasks and questions as `ID (short title)` (or `project/ID (short title)` across projects).
- **Layout:** `tasks/<category>/T###-<slug>.md` for small tasks; `T###-<slug>/{README,CONTEXT,PROGRESS}.md` when there is context. Each category has a `README.md` and `notes/`.
- **Header (closed set, exact order, `- key: value` lines under `# T### <title>`, empty value is `-`):** `id`, `title`, `category`, `priority` (P0-P3), `priority-reason`, `next-up` (`yes`|`no`), `state`, `executor`, `depends-on`, `decider`, `sources`, `paths`, `handoff`. Optional extensions (after `handoff`): `profile`, `verification-mode`, `verifier`, `verify-by`, `size`, `kind`, `labels`, `branch`, `worktree`, `run-id`, `use-cases`, `short`, `conditions`. Required body sections: `## Goal`, `## Steps`, `## Verification`.
- **Microtasks (`tasks/micro/T###-<slug>.md`):** reduced header in exact order (`id`, `title`, `kind`, `priority`, `state`, `executor`, `paths`, `depends-on`, `size`, `labels`, optional `short`); size defaults to `XS`; body section `## What` only.
- **States:** `open`, `in progress`, `paused`, `waiting`, `blocked`, `delivered`, `bounced`, `verified`, `done` (or `done with a caveat`), `dropped`. No direct `open`/`in progress` → `done` (always pass through `delivered`). `verified` is set by someone other than the executor, or by the executor after the owner's explicit approval (recorded in `PROGRESS.md`).
- **Registry:** `00-INDEX.md` (Initiatives, Specs, Next up <= 5, Tasks by category, Decisions waiting, Done) is the state; keep it current with every change.
- **Done:** `git mv` the finished emergent task to `tasks/done/<category>/`.
- **Several sessions:** only a category's `owner-session` edits its tasks; others add notes or new tasks.
- **Tooling feedback:** when `ai-orch` is installed, report friction, defects, or improvements at once with `ai-orch feedback --kind bug|feature|idea|request --title "..." --body "..."` (without `ai-orch`, drop a Markdown note in `tasks/_inbox/to-analyze/`). Do not work around tooling issues silently; maintainers triage notes into tasks.
"""

TASK_ID_RE = re.compile(r"^(?:T\d{3,}(?:\.\d+)*|\d{2,}(?:\.\d+[a-z]?)*)$")
TASK_NODE_ID_RE = re.compile(r"^(?:T\d{3,}(?:\.\d+)*|\d{2,}(?:\.\d+[a-z]?)*)$")
CHILD_ID_RE = re.compile(r"^(?:T\d{3,}(?:\.\d+)+|\d{2,}(?:\.\d+[a-z]?)+)$")
ROOT_INITIATIVE_ID_RE = re.compile(r"^\d{2,}$")
EMERGENT_ID_RE = re.compile(r"^T\d{3,}$")
INITIATIVE_DIR_RE = re.compile(r"^(\d{2,})-(.+)$")
HEADER_LINE_RE = re.compile(r"^-\s+([a-z][a-z0-9-]*):\s*(.*)$")
INLINE_TASK_HEADING_RE = re.compile(r"^###\s+((?:T\d{3,}|\d{2,})(?:\.\d+[a-z]?)+)\s+[—–-]\s+(.+?)\s*$", re.MULTILINE)
INLINE_ANY_HEADING_RE = re.compile(r"^###\s+((?:T\d{3,}|\d{2,})(?:\.\d+[a-z]?)*)\s+[—–-]\s+(.+?)\s*$", re.MULTILINE)
EXPANDED_BULLET_RE = re.compile(r"^\s*[-*]\s+\*\*Expanded:\*\*\s*\[([^\]]+)\]\(([^)]+)\)", re.IGNORECASE)
# Node ids in `Depends on` / `blocks` (spec subtasks S7, §3 "any node id"): `NN`, `NN.T[.n...]`,
# `T###[.n...]`, including plan task ids with one lowercase letter suffix `NN.T<letter>` (e.g. `06.1b`, `12.2a`).
DEP_ID_RE = re.compile(r"\b((?:T\d{3,}|\d{2,})(?:\.\d+[a-z]?)*)(?![\w.]|\.\w)")
DEP_ID_PATTERN = r"(?:T\d{3,}|\d{2,})(?:\.\d+[a-z]?)*"
DEP_ITEM_RE = re.compile(
    r"\s*`?("
    r"workspace:[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)?/" + DEP_ID_PATTERN +
    r"|[a-zA-Z0-9_-]+/" + DEP_ID_PATTERN +
    r"|\b" + DEP_ID_PATTERN + r"(?![\w.]|\.\w)"
    r")`?(\s*\([^()]*\))?"
)
NODE_TYPES: set[str] = {"initiative", "container", "leaf", "microtask"}
INHERITED_FIELDS: tuple[str, ...] = ("executor", "priority", "profile", "repo", "paths")


def normalize_waiting_on(qualifier: str | None) -> str | None:
    if not qualifier or not isinstance(qualifier, str):
        return None
    val = qualifier.strip().strip("`").strip()
    if not val or val == "-":
        return None
    if re.match(r"^Q\d{3,}$", val):
        return f"question:{val}"
    return val


def extract_waiting_on(raw_state: str | None) -> str | None:
    """Extract waiting_on qualifier from state strings like 'waiting on <qualifier>',
    'waiting: <qualifier>', or 'waiting (<qualifier>)'."""
    if not raw_state or not isinstance(raw_state, str):
        return None
    s = raw_state.strip()
    m_tick = re.match(r"^`([^`]+)`(?:\s*\(.*\))?\s*$", s)
    if m_tick:
        s = m_tick.group(1).strip()
    s = s.strip("`").strip()
    m_on = re.match(r"^waiting\s+on(?::|\s+)(.+)$", s, re.IGNORECASE)
    if m_on:
        return normalize_waiting_on(m_on.group(1))
    m_colon = re.match(r"^waiting:\s*(.+)$", s, re.IGNORECASE)
    if m_colon:
        return normalize_waiting_on(m_colon.group(1))
    m_paren = re.match(r"^waiting\s*\((.+)\)$", s, re.IGNORECASE)
    if m_paren:
        inner = m_paren.group(1).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", inner):
            return None
        return normalize_waiting_on(inner)
    return None


def extract_verify_by(raw_state: str | None) -> str | None:
    """Extract verify_by target from state strings like 'delivered (verify-by: <target>)'."""
    if not raw_state or not isinstance(raw_state, str):
        return None
    m = re.search(r"\(verify-by:\s*([^)]+)\)", raw_state, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        return val if val and val != "-" else None
    return None


def normalize_state(raw_state: str) -> str:
    """Map parameterized state strings like 'done with a caveat: self-verified only',
    'dropped: reason', '`done` (2026-10-16)', or '`in progress`' to their canonical base state."""
    s = raw_state.strip()
    m_tick = re.match(r"^`([^`]+)`(?:\s*\(.*\))?\s*$", s)
    if m_tick:
        # '`in progress` (Kilo)', '`done` (2026-10-17; claude)': the state is the code span.
        s = m_tick.group(1)
    s = s.strip("`").strip()
    m_date = re.match(r"^(.+?)\s*\(\d{4}-\d{2}-\d{2}\)$", s)
    if m_date:
        s = m_date.group(1).strip().strip("`").strip()
    s_lower = s.lower()
    if (
        s_lower == "waiting"
        or s_lower.startswith("waiting:")
        or s_lower.startswith("waiting (")
        or s_lower.startswith("waiting on ")
        or s_lower.startswith("waiting on:")
    ):
        return "waiting"
    for base in (
        "done with a caveat",
        "waiting",
        "blocked",
        "dropped",
        "in progress",
        "delivered",
        "bounced",
        "verified",
        "done",
        "open",
        "moved",
    ):
        if s == base or s.startswith(base + ":") or s.startswith(base + " ("):
            return base
    return s


def is_valid_state(raw_state: str) -> bool:
    return normalize_state(raw_state) in CANONICAL_STATES


# ---------------------------------------------------------------------------
# Qualified References & Project Resolution (Spec §1)
# ---------------------------------------------------------------------------

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
QUALIFIED_REF_ID_RE = re.compile(
    r"^(?:T\d{3,}(?:\.\d+)*|\d{2,}(?:\.(?:T)?\d+[a-z]?)*|Q\d{3,}|UC\d{3,}|N\d{3,})$"
)


def is_external_task_ref(ref: str | None) -> bool:
    if not ref or not isinstance(ref, str):
        return False
    r = ref.strip().strip("`").strip()
    return r.startswith("workspace:") or ("/" in r and not r.startswith("./") and not r.startswith("../"))


def parse_external_task_ref(ref: str) -> dict[str, str] | None:
    """Parse cross-workspace or cross-project reference:
    - workspace:<ws-slug>/<task-id>
    - workspace:<ws-slug>/<project-slug>/<task-id>
    - <project-slug>/<task-id>
    """
    if not is_external_task_ref(ref):
        return None
    r = ref.strip().strip("`").strip()
    workspace = None
    project = None

    if r.startswith("workspace:"):
        rest = r[len("workspace:"):].strip()
        parts = rest.split("/")
        if len(parts) == 2:
            workspace, task_id = parts[0], parts[1]
        elif len(parts) == 3:
            workspace, project, task_id = parts[0], parts[1], parts[2]
        else:
            return None
    elif ":" in r:
        ws_part, rest = r.split(":", 1)
        workspace = ws_part
        parts = rest.split("/")
        if len(parts) == 1:
            task_id = parts[0]
        elif len(parts) == 2:
            project, task_id = parts[0], parts[1]
        else:
            return None
    else:
        parts = r.split("/")
        if len(parts) == 2:
            project, task_id = parts[0], parts[1]
        elif len(parts) == 3:
            workspace, project, task_id = parts[0], parts[1], parts[2]
        else:
            return None

    slug_pat = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    if workspace is not None and not slug_pat.match(workspace):
        return None
    if project is not None and not slug_pat.match(project):
        return None
    if not task_id or not (re.match(r"^(?:T\d{3,}|\d{2,})(?:\.\d+[a-z]?)*$", task_id) or TASK_ID_RE.match(task_id)):
        return None

    res: dict[str, str] = {"id": task_id}
    if workspace:
        res["workspace"] = workspace
    if project:
        res["project"] = project
    return res


def parse_qualified_ref(text: str) -> dict[str, str]:
    """Parse a qualified task reference of the form [workspace ':'] [project '/'] ID.

    Slugs must match '^[a-z0-9][a-z0-9-]{1,47}$' (except project may be '_workspace').
    ID matches standard id grammar (T###, NN, NN.T…, Q###, UC###, N###).
    Returns a dict with 'id' and optionally 'workspace' and/or 'project'.
    Raises ValueError on malformed input.
    """
    if not isinstance(text, str):
        raise ValueError(f"Qualified reference must be a string, got {type(text).__name__}")
    if not text:
        raise ValueError("Empty qualified reference")

    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError(f"Malformed qualified ref: multiple ':' in {text!r}")
        ws_part, rest = parts
        if not SLUG_RE.match(ws_part):
            raise ValueError(f"Malformed qualified ref: invalid workspace slug {ws_part!r}")
        workspace = ws_part
    else:
        workspace = None
        rest = text

    if "/" in rest:
        parts = rest.split("/")
        if len(parts) != 2:
            raise ValueError(f"Malformed qualified ref: multiple '/' in {text!r}")
        proj_part, id_part = parts
        if proj_part != "_workspace" and not SLUG_RE.match(proj_part):
            raise ValueError(f"Malformed qualified ref: invalid project slug {proj_part!r}")
        project = proj_part
    else:
        project = None
        id_part = rest

    if not id_part:
        raise ValueError(f"Malformed qualified ref: missing id in {text!r}")
    if not QUALIFIED_REF_ID_RE.match(id_part):
        raise ValueError(f"Malformed qualified ref: invalid id {id_part!r} in {text!r}")

    res: dict[str, str] = {"id": id_part}
    if workspace is not None:
        res["workspace"] = workspace
    if project is not None:
        res["project"] = project
    return res


def format_qualified_ref(
    ref: dict[str, Any] | str | None = None,
    *,
    id: str | None = None,
    project: str | None = None,
    workspace: str | None = None,
) -> str:
    """Format a qualified reference into [workspace ':'] [project '/'] ID."""
    if isinstance(ref, dict):
        id = ref.get("id") or id
        project = ref.get("project") or project
        workspace = ref.get("workspace") or workspace
    elif isinstance(ref, str):
        parsed = parse_qualified_ref(ref)
        id = parsed.get("id")
        project = parsed.get("project")
        workspace = parsed.get("workspace")

    if not id:
        raise ValueError("Missing 'id' for format_qualified_ref")

    prefix = ""
    if workspace:
        prefix += f"{workspace}:"
    if project:
        prefix += f"{project}/"
    return f"{prefix}{id}"


def resolve_project_tasks_dir(project_slug: str, context_tasks_dir: pathlib.Path) -> pathlib.Path | None:
    """Locate the tasks/ directory for a given project slug relative to workspace configuration."""
    context_tasks_dir = pathlib.Path(context_tasks_dir).resolve()

    # Special case: _workspace itself
    if project_slug == "_workspace":
        return context_tasks_dir

    # 1. Try orchestration_registry SQLite DB if available
    if orchestration_registry is not None:
        try:
            ws, _ = orchestration_registry.resolve_workspace_for_path(context_tasks_dir.parent)
            if ws is not None:
                ws_path = pathlib.Path(ws["canonical_path"]).resolve()
                proj_res = orchestration_registry.list_projects(ws["slug"])
                for item in proj_res.get("items", []):
                    if item.get("slug") == project_slug:
                        cand = (ws_path / item.get("path", "") / "tasks").resolve()
                        if cand.is_dir() or cand.parent.is_dir():
                            return cand
        except Exception:
            pass

    # 2. Try looking for orchestration.toml or .ai-orchestration.local.toml in workspace root or parents
    curr: pathlib.Path | None = context_tasks_dir.parent
    while curr and curr != curr.parent:
        for cfg_name in (".ai-orchestration.local.toml", "orchestration.toml"):
            cfg_file = curr / cfg_name
            if cfg_file.is_file():
                try:
                    import tomllib
                    cfg_data = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
                    projects = cfg_data.get("workspace", {}).get("projects", [])
                    for p in projects:
                        if p.get("slug") == project_slug or p.get("id") == project_slug:
                            cand = (curr / p.get("path", "") / "tasks").resolve()
                            return cand
                except Exception:
                    pass
        curr = curr.parent

    # 3. Check direct folder structure:
    # If context_tasks_dir is in a workspace, e.g. <ws_root>/tasks:
    # Check <ws_root>/<project_slug>/tasks or <ws_root>/projects/<project_slug>/tasks
    ws_cand = context_tasks_dir.parent
    for sub in (ws_cand / project_slug / "tasks", ws_cand / "projects" / project_slug / "tasks"):
        if sub.is_dir() or sub.parent.is_dir():
            return sub.resolve()

    return None


def is_workspace_task_tree(tasks_dir: pathlib.Path) -> tuple[bool, list[dict[str, Any]]]:
    """Check if tasks_dir is the workspace's own tree (_workspace) and return its projects."""
    tasks_dir = pathlib.Path(tasks_dir).resolve()

    # 1. Check orchestration_registry
    if orchestration_registry is not None:
        try:
            ws, proj = orchestration_registry.resolve_workspace_for_path(tasks_dir.parent)
            if ws is not None:
                if proj is None or proj.get("slug") == "_workspace":
                    proj_res = orchestration_registry.list_projects(ws["slug"])
                    return True, proj_res.get("items", [])
        except Exception:
            pass

    # 2. Check orchestration.toml / .ai-orchestration.local.toml
    curr: pathlib.Path | None = tasks_dir.parent
    while curr and curr != curr.parent:
        for cfg_name in (".ai-orchestration.local.toml", "orchestration.toml"):
            cfg_file = curr / cfg_name
            if cfg_file.is_file():
                try:
                    import tomllib
                    cfg_data = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
                    ws_section = cfg_data.get("workspace")
                    if ws_section:
                        if tasks_dir == (curr / "tasks").resolve():
                            projects = ws_section.get("projects", [])
                            return True, projects
                except Exception:
                    pass
        curr = curr.parent

    # 3. Check name
    if tasks_dir.name == "_workspace" or tasks_dir.parent.name == "_workspace":
        return True, []

    return False, []


def resolve_coordinates(
    coords_refs: list[str],
    context_tasks_dir: pathlib.Path,
    project_tree_cache: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Resolve coordinates references read-only against target project trees.
    Resolved items include {project, id, state?, short_title?}. Unresolved: {project, id}.
    """
    if project_tree_cache is None:
        project_tree_cache = {}

    results: list[dict[str, Any]] = []
    for ref_str in coords_refs:
        try:
            parsed = parse_qualified_ref(ref_str)
        except Exception:
            continue
        proj = parsed.get("project")
        tid = parsed.get("id")
        if not proj or not tid:
            continue
        entry: dict[str, Any] = {"project": proj, "id": tid}

        proj_tasks = resolve_project_tasks_dir(proj, context_tasks_dir)
        if proj_tasks is not None and proj_tasks.is_dir():
            cache_key = str(proj_tasks)
            if cache_key not in project_tree_cache:
                try:
                    p_tree = discover_task_tree(proj_tasks)
                    p_emergent = discover_emergent_tasks(proj_tasks)
                    project_tree_cache[cache_key] = (p_tree, p_emergent)
                except Exception:
                    project_tree_cache[cache_key] = ({}, [])
            p_tree, p_emergent = project_tree_cache[cache_key]

            # Look up task in tree
            target_node = p_tree.get(tid)
            if target_node:
                entry["state"] = target_node.state
                if target_node.short_title:
                    entry["short_title"] = target_node.short_title
            else:
                target_em = next((t for t in p_emergent if t.get("id") == tid), None)
                if target_em:
                    entry["state"] = target_em.get("state")
                    if target_em.get("short_title"):
                        entry["short_title"] = target_em["short_title"]

        results.append(entry)
    return results


def resolve_external_task_ref(ref: str, current_tasks_dir: pathlib.Path | str) -> dict[str, Any]:
    """Resolve cross-workspace or cross-project reference read-only against target task trees.

    Resolves:
      - <project-slug>/<task-id>: looks up <workspace_root>/<project-slug>/tasks/ (or via orchestration_registry)
      - workspace:<ws-slug>/<task-id> or workspace:<ws-slug>/<project-slug>/<task-id>: looks up workspace path in
        orchestration_registry (or sibling directory <current_workspace_parent>/<ws-slug> / ~/works/<ws-slug>)
        and inspects its tasks/ tree to read live state, canonical_state, title, and short_title.
    Returns:
      {"ref": ref, "resolved": True/False, "state": ..., "canonical_state": ..., "is_done": ..., "title": ..., "short_title": ...}
      (gracefully returning "resolved": False without crashing when the external workspace is not registered or not present on disk).
    """
    ref_clean = ref.strip().strip("`").strip() if isinstance(ref, str) else ""
    unresolved: dict[str, Any] = {
        "ref": ref_clean,
        "resolved": False,
        "state": None,
        "canonical_state": None,
        "is_done": False,
        "title": None,
        "short_title": None,
    }
    if not ref_clean:
        return unresolved

    try:
        parsed = parse_external_task_ref(ref_clean)
        if not parsed:
            return unresolved

        current_tasks_dir = pathlib.Path(current_tasks_dir).resolve()
        task_id = parsed["id"]
        ws_slug = parsed.get("workspace")
        proj_slug = parsed.get("project")

        target_tasks_dir: pathlib.Path | None = None

        if ws_slug is not None:
            # 1. Try orchestration_registry
            ws_root: pathlib.Path | None = None
            if orchestration_registry is not None and hasattr(orchestration_registry, "find_workspace_for_arg"):
                try:
                    ws_info = orchestration_registry.find_workspace_for_arg(ws_slug)
                    if ws_info and "canonical_path" in ws_info:
                        p = pathlib.Path(ws_info["canonical_path"]).resolve()
                        if p.is_dir():
                            ws_root = p
                except Exception:
                    pass

            # 2. Try sibling directory or common parent
            if ws_root is None:
                curr_root = current_tasks_dir.parent if current_tasks_dir.name == "tasks" else current_tasks_dir
                for parent_dir in (curr_root.parent, curr_root.parent.parent):
                    cand = (parent_dir / ws_slug).resolve()
                    if cand.is_dir():
                        ws_root = cand
                        break

            # 3. Try ~/works/<ws-slug>
            if ws_root is None:
                cand = (pathlib.Path.home() / "works" / ws_slug).resolve()
                if cand.is_dir():
                    ws_root = cand

            # 4. Try cwd sibling
            if ws_root is None:
                cand = (pathlib.Path.cwd().parent / ws_slug).resolve()
                if cand.is_dir():
                    ws_root = cand

            if ws_root is None or not ws_root.is_dir():
                return unresolved

            if proj_slug is not None:
                for sub in (ws_root / proj_slug / "tasks", ws_root / "projects" / proj_slug / "tasks"):
                    if sub.is_dir():
                        target_tasks_dir = sub.resolve()
                        break
                if target_tasks_dir is None and (ws_root / "tasks").is_dir():
                    target_tasks_dir = (ws_root / "tasks").resolve()
            else:
                if (ws_root / "tasks").is_dir():
                    target_tasks_dir = (ws_root / "tasks").resolve()
                elif (ws_root / "tasks").parent.is_dir():
                    target_tasks_dir = (ws_root / "tasks").resolve()

        else:
            # Cross-project reference within current workspace (<project-slug>/<task-id>)
            if proj_slug is not None:
                target_tasks_dir = resolve_project_tasks_dir(proj_slug, current_tasks_dir)
                if target_tasks_dir is None:
                    curr_root = current_tasks_dir.parent if current_tasks_dir.name == "tasks" else current_tasks_dir
                    for cand in (
                        curr_root / proj_slug / "tasks",
                        curr_root / "projects" / proj_slug / "tasks",
                        curr_root.parent / proj_slug / "tasks",
                        curr_root.parent / "projects" / proj_slug / "tasks",
                    ):
                        if cand.is_dir():
                            target_tasks_dir = cand.resolve()
                            break

        if target_tasks_dir is None or not target_tasks_dir.is_dir():
            return unresolved

        p_tree = discover_task_tree(target_tasks_dir)
        target_node = p_tree.get(task_id)
        if target_node is not None:
            cstate = target_node.canonical_state
            is_done = bool(target_node.in_done or cstate in ("done", "done with a caveat"))
            st = target_node.short_title or derive_short_title(target_node.title)
            return {
                "ref": ref_clean,
                "resolved": True,
                "state": target_node.state,
                "canonical_state": cstate,
                "is_done": is_done,
                "title": target_node.title,
                "short_title": st,
            }

        p_emergent = discover_emergent_tasks(target_tasks_dir)
        target_em = next((t for t in p_emergent if t.get("id") == task_id), None)
        if target_em is not None:
            cstate = target_em.get("canonical_state") or normalize_state(target_em.get("state", "open"))
            is_done = bool(target_em.get("in_done", False) or cstate in ("done", "done with a caveat"))
            st = target_em.get("short_title") or derive_short_title(target_em.get("title", ""))
            return {
                "ref": ref_clean,
                "resolved": True,
                "state": target_em.get("state", "open"),
                "canonical_state": cstate,
                "is_done": is_done,
                "title": target_em.get("title", ""),
                "short_title": st,
            }

        return unresolved

    except Exception:
        return unresolved


# ---------------------------------------------------------------------------
# Platform, Locking & File Serialization
# ---------------------------------------------------------------------------

class LockTimeoutError(Exception):
    pass


class UnsupportedPlatformError(Exception):
    pass


def is_platform_supported() -> bool:
    if os.name == "nt" or fcntl is None:
        return False
    return True


_LOCK_STATE = threading.local()


@contextlib.contextmanager
def task_write_lock(tasks_dir: pathlib.Path, timeout: float | None = None) -> Iterator[pathlib.Path]:
    """Acquire an exclusive flock on <tasks_dir>/.ai-orch.lock.
    Re-entrant for the current thread. Waits up to timeout seconds (default 10s
    or AI_ORCH_LOCK_TIMEOUT env var), raising LockTimeoutError on timeout."""
    if not is_platform_supported():
        raise UnsupportedPlatformError("Mutating commands are unsupported on Windows (requires fcntl for flock).")

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    lock_path = tasks_dir / ".ai-orch.lock"

    held = getattr(_LOCK_STATE, "held_locks", None)
    if held is None:
        held = {}
        _LOCK_STATE.held_locks = held

    lock_key = str(lock_path)
    if lock_key in held and held[lock_key] > 0:
        held[lock_key] += 1
        try:
            yield lock_path
        finally:
            held[lock_key] -= 1
            if held[lock_key] == 0:
                del held[lock_key]
        return

    if timeout is None:
        try:
            timeout = float(os.environ.get("AI_ORCH_LOCK_TIMEOUT", "10.0"))
        except ValueError:
            timeout = 10.0

    tasks_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o666)

    deadline = time.monotonic() + max(0.0, timeout)
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    break
                sleep_interval = min(0.05, max(0.005, deadline - time.monotonic()))
                if sleep_interval > 0:
                    time.sleep(sleep_interval)

        if not acquired:
            raise LockTimeoutError(f"Failed to acquire task-write lock on {lock_path} within {timeout}s.")

        held[lock_key] = 1
        yield lock_path
    finally:
        if acquired:
            if lock_key in held:
                held[lock_key] -= 1
                if held[lock_key] == 0:
                    del held[lock_key]
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Events Emission (Spec 12, E1)
# ---------------------------------------------------------------------------

def _find_repo_root() -> pathlib.Path | None:
    cur = pathlib.Path(__file__).resolve().parent
    for parent in [cur, *cur.parents]:
        if (parent / "scripts" / "orchestration_events.py").is_file():
            return parent
        if (parent / ".git").exists():
            return parent
    return None


def _get_orchestration_events() -> Any | None:
    try:
        import orchestration_events
        return orchestration_events
    except ImportError:
        pass

    try:
        repo_root = _find_repo_root()
        if repo_root is not None:
            scripts_dir = repo_root / "scripts"
            if scripts_dir.is_dir() and str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
        import orchestration_events
        return orchestration_events
    except Exception:
        return None


def _get_broker_status() -> Any:
    try:
        import orchestration_broker_lock
        return orchestration_broker_lock.broker_status()
    except ImportError:
        pass

    try:
        repo_root = _find_repo_root()
        if repo_root is not None:
            scripts_dir = repo_root / "scripts"
            if scripts_dir.is_dir() and str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
        import orchestration_broker_lock
        return orchestration_broker_lock.broker_status()
    except Exception:
        return None


def _is_pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False


def _read_ui_token(b_status: Any = None) -> tuple[str, bool]:
    token_file_path = getattr(b_status, "token_file", None) if b_status is not None else None
    if token_file_path:
        tf = pathlib.Path(token_file_path)
        if tf.is_file():
            try:
                val = tf.read_text(encoding="utf-8").strip()
                return val, True
            except OSError:
                pass

    gtf = _resolve_global_config_dir() / "ui-token"
    if gtf.is_file():
        try:
            val = gtf.read_text(encoding="utf-8").strip()
            return val, True
        except OSError:
            pass

    return "", False


def _check_broker_health(port: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                return isinstance(data, dict) and data.get("status") == "ok"
    except Exception:
        pass
    return False


def _try_forward_to_live_broker(b_status: Any, is_json: bool) -> int | None:
    port = getattr(b_status, "port", None)
    if not port:
        return None
    port = int(port)

    live_pid = getattr(b_status, "live_pid", None)
    if live_pid is None:
        raw_pid = getattr(b_status, "pid", None)
        if raw_pid is not None and _is_pid_alive(raw_pid):
            live_pid = raw_pid

    pid_str = str(live_pid) if live_pid is not None else "unknown"
    token, has_token_file = _read_ui_token(b_status)

    # Fast TCP connect probe with 0.5s timeout
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect(("127.0.0.1", port))
        sock.close()
    except (ConnectionRefusedError, socket.timeout, OSError):
        err_msg = f"route through the broker (MCP) \u2014 it is running as pid {pid_str}"
        payload = {
            "ok": False,
            "error": "broker-owns-writes",
            "message": err_msg,
        }
        if is_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[FAIL] broker-owns-writes: {err_msg}", file=sys.stderr)
        return 75

    # 2. Try POST http://127.0.0.1:<port>/cli
    cli_url = f"http://127.0.0.1:{port}/cli"
    fwd_argv = list(sys.argv[1:])
    if fwd_argv and fwd_argv[0] not in ("tasks", "questions", "use-cases", "inbox", "feedback"):
        fwd_argv = ["tasks", *fwd_argv]
    req_body = json.dumps({"argv": fwd_argv, "cwd": os.getcwd()}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
    }
    if token:
        headers["x-ai-orch-token"] = token

    req = urllib.request.Request(cli_url, data=req_body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                resp_bytes = resp.read()
                resp_data = json.loads(resp_bytes.decode("utf-8"))
                if isinstance(resp_data, dict) and "returncode" in resp_data:
                    out_s = resp_data.get("stdout", "")
                    if out_s:
                        if out_s.endswith("\n"):
                            sys.stdout.write(out_s)
                        else:
                            print(out_s, file=sys.stdout)
                        sys.stdout.flush()
                    err_s = resp_data.get("stderr", "")
                    if err_s:
                        if err_s.endswith("\n"):
                            sys.stderr.write(err_s)
                        else:
                            print(err_s, file=sys.stderr)
                        sys.stderr.flush()
                    return int(resp_data["returncode"])
    except urllib.error.HTTPError as e:
        if e.code in (404, 405):
            if has_token_file or _check_broker_health(port):
                os.environ["AI_ORCH_BROKER_CHILD"] = "1"
                return None
        if has_token_file and _check_broker_health(port):
            os.environ["AI_ORCH_BROKER_CHILD"] = "1"
            return None

        err_msg = f"route through the broker (MCP) \u2014 it is running as pid {pid_str}"
        payload = {
            "ok": False,
            "error": "broker-owns-writes",
            "message": err_msg,
        }
        if is_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[FAIL] broker-owns-writes: {err_msg}", file=sys.stderr)
        return 75
    except (urllib.error.URLError, OSError):
        err_msg = f"route through the broker (MCP) \u2014 it is running as pid {pid_str}"
        payload = {
            "ok": False,
            "error": "broker-owns-writes",
            "message": err_msg,
        }
        if is_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[FAIL] broker-owns-writes: {err_msg}", file=sys.stderr)
        return 75

    if has_token_file and _check_broker_health(port):
        os.environ["AI_ORCH_BROKER_CHILD"] = "1"
        return None

    err_msg = f"route through the broker (MCP) \u2014 it is running as pid {pid_str}"
    payload = {
        "ok": False,
        "error": "broker-owns-writes",
        "message": err_msg,
    }
    if is_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"[FAIL] broker-owns-writes: {err_msg}", file=sys.stderr)
    return 75


def _resolve_workspace_from_tasks_dir(tasks_dir: pathlib.Path) -> pathlib.Path:
    td = pathlib.Path(tasks_dir).resolve()
    for cur in [td, *td.parents]:
        if (cur / ".ai-orchestration").is_dir() or (cur / ".git").exists():
            return cur
    if td.name == "tasks":
        return td.parent
    return td


def _emit_event(
    tasks_dir: pathlib.Path,
    event_type: str,
    payload: Any,
    *,
    subject: str | None = None,
    actor: str | None = None,
    origin_session: str | None = None,
) -> dict[str, Any] | None:
    orch_events = _get_orchestration_events()
    if orch_events is None:
        return None

    workspace = _resolve_workspace_from_tasks_dir(tasks_dir)
    try:
        return orch_events.emit(
            workspace,
            event_type,
            payload,
            source="tasks_engine",
            subject=subject,
            actor=actor or "tasks_engine",
            origin_session=origin_session,
        )
    except Exception as e:
        print(
            f"[warning] failed to emit {event_type} event: {e}",
            file=sys.stderr,
        )
        return None


def _file_sha256(path: pathlib.Path) -> str:
    if not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _folder_bundle_sha256(folder_path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    if not folder_path.is_dir():
        return hasher.hexdigest()

    files: list[tuple[str, pathlib.Path]] = []
    for root, dirs, filenames in os.walk(folder_path):
        dirs[:] = sorted([d for d in dirs if not d.startswith(".")])
        root_path = pathlib.Path(root)
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            file_path = root_path / fn
            if file_path.is_file():
                rel_path = file_path.relative_to(folder_path).as_posix()
                files.append((rel_path, file_path))

    files.sort(key=lambda item: item[0])
    for rel_path, file_path in files:
        hasher.update(rel_path.encode("utf-8") + b"\x00" + file_path.read_bytes())

    return hasher.hexdigest()


def task_bundle_sha256(task: dict[str, Any] | pathlib.Path | str) -> str:
    """Compute sha256 over a canonical serialization of the task's files:
    for a folder task every regular file in the folder (sorted relative path + NUL + bytes),
    for a single-file task just that file."""
    if isinstance(task, dict):
        is_folder = bool(task.get("is_folder", False))
        if is_folder:
            folder_path = pathlib.Path(task.get("task_root") or task.get("file_path", ""))
            if folder_path.is_file():
                folder_path = folder_path.parent
            return _folder_bundle_sha256(folder_path)
        else:
            file_path = pathlib.Path(task.get("file_path") or task.get("task_root", ""))
            return _file_sha256(file_path)

    p = pathlib.Path(task)
    if p.is_dir():
        return _folder_bundle_sha256(p)
    if p.is_file() and p.name == "README.md" and re.match(r"^T\d{3,}-", p.parent.name):
        return _folder_bundle_sha256(p.parent)
    return _file_sha256(p)


def _atomic_write_text(path: pathlib.Path, content: str, encoding: str = "utf-8") -> None:
    """Write content to path atomically via temporary file and os.replace,
    preserving existing file mode."""
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

        if path.exists():
            try:
                mode = path.stat().st_mode & 0o777
                os.chmod(tmp_path, mode)
            except OSError:
                pass
        else:
            try:
                umask = os.umask(0)
                os.umask(umask)
                os.chmod(tmp_path, 0o666 & ~umask)
            except OSError:
                pass

        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# CommonMark Fence-Aware Markdown Scanner
# ---------------------------------------------------------------------------

@dataclass
class ScannedLine:
    line_number: int  # 1-indexed
    text: str         # exact line content without trailing newline
    is_fenced: bool   # True if inside code block OR on opening/closing fence line
    fence_char: str = ""   # '`' or '~' or ""
    is_fence_open: bool = False
    is_fence_close: bool = False


@dataclass
class FencedCodeBlock:
    fence_char: str       # '`' or '~'
    fence_len: int        # >= 3
    info: str             # info string (e.g. "text", "bash")
    content: str          # interior lines joined with \n
    lines: list[str]      # interior lines
    start_line: int       # 1-indexed line number of opening fence
    end_line: int | None  # 1-indexed line number of closing fence (None if unclosed at EOF)
    closed: bool          # True if closed by closing fence, False if unclosed at EOF


@dataclass
class MarkdownSection:
    heading: str          # e.g. "## Context", or "" for preamble
    title: str            # e.g. "Context", or ""
    level: int            # heading level (e.g. 2, or 0 for preamble)
    lines: list[ScannedLine] # all lines belonging to this section
    body: str             # text of section body (excluding the heading line itself)
    code_blocks: list[FencedCodeBlock]


_OPEN_FENCE_TICK_RE = re.compile(r"^[ ]{0,3}(`{3,})([^`]*)$")
_OPEN_FENCE_TILDE_RE = re.compile(r"^[ ]{0,3}(~{3,})([^~]*)$")


def scan_markdown_blocks(text: str) -> tuple[list[ScannedLine], list[FencedCodeBlock]]:
    """Scan markdown text into ScannedLines and FencedCodeBlocks according to CommonMark rules:
    - Opening fence: 0-3 leading spaces, N >= 3 backticks or tildes, optional info string.
      Info string for backtick fence cannot contain backticks; for tilde fence cannot contain tildes.
    - While inside a fence, code fences do not nest.
    - Closing fence: 0-3 leading spaces, >= N of the SAME fence char, followed only by whitespace.
    - Unclosed fence runs to EOF.
    All lines inside code fences (and the fence boundaries themselves) have is_fenced=True.
    """
    raw_lines = text.splitlines()
    scanned_lines: list[ScannedLine] = []
    code_blocks: list[FencedCodeBlock] = []

    in_fence = False
    fence_char = ""
    fence_len = 0
    current_block_info = ""
    current_block_start = 0
    current_block_lines: list[str] = []

    for i, line in enumerate(raw_lines):
        line_num = i + 1
        if not in_fence:
            m_tick = _OPEN_FENCE_TICK_RE.match(line)
            m_tilde = _OPEN_FENCE_TILDE_RE.match(line)
            if m_tick:
                in_fence = True
                fence_char = "`"
                fence_len = len(m_tick.group(1))
                current_block_info = m_tick.group(2).strip()
                current_block_start = line_num
                current_block_lines = []
                scanned_lines.append(
                    ScannedLine(
                        line_number=line_num,
                        text=line,
                        is_fenced=True,
                        fence_char="`",
                        is_fence_open=True,
                    )
                )
            elif m_tilde:
                in_fence = True
                fence_char = "~"
                fence_len = len(m_tilde.group(1))
                current_block_info = m_tilde.group(2).strip()
                current_block_start = line_num
                current_block_lines = []
                scanned_lines.append(
                    ScannedLine(
                        line_number=line_num,
                        text=line,
                        is_fenced=True,
                        fence_char="~",
                        is_fence_open=True,
                    )
                )
            else:
                scanned_lines.append(
                    ScannedLine(
                        line_number=line_num,
                        text=line,
                        is_fenced=False,
                    )
                )
        else:
            is_close = False
            close_pat = rf"^[ ]{{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$"
            if re.match(close_pat, line):
                is_close = True

            if is_close:
                in_fence = False
                scanned_lines.append(
                    ScannedLine(
                        line_number=line_num,
                        text=line,
                        is_fenced=True,
                        fence_char=fence_char,
                        is_fence_close=True,
                    )
                )
                code_blocks.append(
                    FencedCodeBlock(
                        fence_char=fence_char,
                        fence_len=fence_len,
                        info=current_block_info,
                        content="\n".join(current_block_lines),
                        lines=list(current_block_lines),
                        start_line=current_block_start,
                        end_line=line_num,
                        closed=True,
                    )
                )
                fence_char = ""
                fence_len = 0
                current_block_info = ""
                current_block_lines = []
            else:
                scanned_lines.append(
                    ScannedLine(
                        line_number=line_num,
                        text=line,
                        is_fenced=True,
                        fence_char=fence_char,
                    )
                )
                current_block_lines.append(line)

    if in_fence:
        code_blocks.append(
            FencedCodeBlock(
                fence_char=fence_char,
                fence_len=fence_len,
                info=current_block_info,
                content="\n".join(current_block_lines),
                lines=list(current_block_lines),
                start_line=current_block_start,
                end_line=None,
                closed=False,
            )
        )

    return scanned_lines, code_blocks


def parse_markdown_sections(text: str, heading_prefix: str = "## ") -> list[MarkdownSection]:
    """Split markdown text into sections demarcated by headings matching heading_prefix outside code fences."""
    scanned_lines, code_blocks = scan_markdown_blocks(text)
    sections: list[MarkdownSection] = []

    current_heading = ""
    current_title = ""
    current_lines: list[ScannedLine] = []

    hashes = len(heading_prefix.strip())
    prefix_clean = heading_prefix.strip()
    heading_re = re.compile(rf"^{re.escape(prefix_clean)}\s+(.+?)\s*$")

    def _flush_section() -> None:
        if not current_lines and not current_heading:
            return
        if current_heading:
            body_lines = [sl.text for sl in current_lines[1:]]
        else:
            body_lines = [sl.text for sl in current_lines]
        body_text = "\n".join(body_lines)
        if current_lines:
            s_start = current_lines[0].line_number
            s_end = current_lines[-1].line_number
            sec_blocks = [cb for cb in code_blocks if s_start <= cb.start_line <= s_end]
        else:
            sec_blocks = []
        sections.append(
            MarkdownSection(
                heading=current_heading,
                title=current_title,
                level=hashes if current_heading else 0,
                lines=list(current_lines),
                body=body_text,
                code_blocks=sec_blocks,
            )
        )

    for sline in scanned_lines:
        m = heading_re.match(sline.text) if heading_re else None
        if not sline.is_fenced and m:
            _flush_section()
            prefix_hashes = "#" * hashes
            current_heading = f"{prefix_hashes} {m.group(1).strip()}"
            current_title = m.group(1).strip()
            current_lines = [sline]
        else:
            current_lines.append(sline)

    _flush_section()
    return sections


def find_markdown_section(text: str, title: str, heading_prefix: str = "## ") -> MarkdownSection | None:
    for sec in parse_markdown_sections(text, heading_prefix=heading_prefix):
        if sec.title == title or sec.title.startswith(title):
            return sec
    return None


# ---------------------------------------------------------------------------
# Task Tree Model, S7 Bullet Grammar, S5 State & S11 Inheritance
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-")


SHORT_TITLE_STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "for", "of", "in", "on", "at", "to", "by",
    "with", "from", "as", "is", "are", "was", "were", "it", "its", "via",
    "which", "what", "should", "would", "could", "does", "do",
    "before", "after", "that", "this", "into", "when", "where", "be", "but",
    "not", "than", "then", "so", "if", "all", "each", "every",
}
SHORT_TITLE_LEADING_STOP_WORDS: set[str] = {
    "a", "an", "the", "which", "what", "how", "who", "should", "would",
}


def validate_short_title(val: str) -> list[str]:
    """Validate a short title field value per T025:
    - 1–5 words
    - <= 40 chars
    - no trailing punctuation (.,:;!?—–-)
    Returns a list of violation descriptions (empty if valid).
    """
    if not val or val.strip() == "" or val.strip() == "-":
        return ["short title cannot be empty"]
    val_clean = val.strip()
    issues: list[str] = []
    if len(val_clean) > 40:
        issues.append(f"exceeds 40 characters ({len(val_clean)} chars)")
    words = val_clean.split()
    if not (1 <= len(words) <= 5):
        issues.append(f"expected 1-5 words, got {len(words)}")
    if re.search(r"[.,:;!?—–\-]$", val_clean):
        issues.append("has trailing punctuation")
    return issues


def derive_short_title(title: str) -> str:
    """Deterministically derive a 3-4 word short title from a title string.
    Rules per T025:
    - drop leading stop words ('the', 'a', 'an', etc.)
    - strip ids (T###, Q###, UC###, N###, NN.T), backticks, parentheticals
    - keep first 3–4 significant words (at most 5 words, <= 40 chars, no trailing punctuation)
    """
    if not title:
        return "untitled"
    # 1. Strip backticks
    text = title.replace("`", "")
    # 2. Strip leading ID pattern: T###, Q###, UC###, N###, NN.T, NN
    text = re.sub(
        r"^(?:T\d{3,}(?:\.\d+)*|Q\d{3,}|UC\d{3,}|N\d{3,}|\d{2,}(?:\.\d+[a-z]?)*)\s*[:—–-]?\s*",
        "",
        text.strip(),
    )
    # 3. Strip any embedded markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # 4. Handle parentheticals: if stripping leaves >= 2 words, strip them; else unpack them
    no_parens = re.sub(r"\([^)]*\)", "", text)
    no_parens = re.sub(r"\[[^\]]*\]", "", no_parens).strip()
    words_no_parens = [w for w in re.split(r"\s+", no_parens) if w]
    if len(words_no_parens) >= 2:
        text = no_parens
    else:
        inner = re.findall(r"\(([^)]+)\)", text) + re.findall(r"\[([^\]]+)\]", text)
        if inner:
            text = " ".join(inner).strip()
        else:
            text = no_parens or text
    # 5. Clean individual words of outer punctuation
    raw_words = text.split()
    cleaned_words = []
    for w in raw_words:
        cw = re.sub(r"^[^\w]+|[^\w]+$", "", w)
        if cw:
            cleaned_words.append(cw)
    # 6. Drop leading stop words
    while cleaned_words and cleaned_words[0].lower() in SHORT_TITLE_LEADING_STOP_WORDS:
        cleaned_words.pop(0)
    if not cleaned_words:
        return "untitled"
    # 6b. Drop a short code prefix such as "P1-a:" or "P3-a..d:" (kept only if nothing else remains)
    m = re.match(r"^\s*[A-Z]\d+[-\w.]*:\s+(.*)$", text)
    if m:
        rest = [re.sub(r"^[^\w]+|[^\w]+$", "", w) for w in m.group(1).split()]
        rest = [w for w in rest if w]
        if len(rest) >= 2:
            cleaned_words = rest
    # 7. Extract significant words (drop stop words and case-insensitive repeats)
    sig_words = []
    seen_words: set[str] = set()
    for w in cleaned_words:
        lw = w.lower()
        if lw in SHORT_TITLE_STOP_WORDS or lw in seen_words:
            continue
        seen_words.add(lw)
        sig_words.append(w)
    if len(sig_words) < 2:
        sig_words = cleaned_words
    if len(" ".join(sig_words[:4])) > 40:
        shorter_sig = [w for w in sig_words if len(w) <= 24]
        if len(shorter_sig) >= 2:
            sig_words = shorter_sig
    # 8. Target 3-4 words (at most 5 words, at least 1 word), keeping length <= 40 chars
    words_to_use = sig_words[:4]
    candidate = " ".join(words_to_use)
    while len(candidate) > 40 and len(words_to_use) > 1:
        words_to_use.pop()
        candidate = " ".join(words_to_use)
    if len(candidate) > 40:
        candidate = candidate[:40].rstrip()
    candidate = re.sub(r"[.,:;!?—–\-]+$", "", candidate).strip()
    return candidate or "untitled"


@dataclass
class BulletSegment:
    raw_key: str | None
    key: str
    raw_value: str
    clean_value: str


def parse_bullet_line(line: str) -> tuple[str, list[BulletSegment]]:
    """Parse a markdown list bullet into its prefix and segments separated by ' · '.
    S7: A field bullet is '-' followed by one or more segments separated by ' · '.
    A segment is '**Key:** value'. A literal ' · ' inside a value is written '\\·'.
    """
    m = re.match(r"^(\s*[-*]\s+)(.*)$", line)
    if not m:
        return "", []
    prefix, body = m.group(1), m.group(2)
    # Split by ' · ' where · is not escaped by backslash
    raw_segments = re.split(r"(?<!\\)\s+·\s+", body)
    segments: list[BulletSegment] = []
    for raw_seg in raw_segments:
        m_seg = re.match(r"^\*\*([^*:]+)(?:\*\*:|:\*\*)\s*(.*)$", raw_seg)
        if m_seg:
            raw_k = m_seg.group(1).strip()
            norm_k = raw_k.lower().replace(" ", "_")
            raw_v = m_seg.group(2)
            clean_v = raw_v.replace(r"\·", " · ").strip()
            if clean_v.startswith("`") and clean_v.endswith("`") and len(clean_v) >= 2:
                clean_v = clean_v[1:-1]
            segments.append(
                BulletSegment(
                    raw_key=raw_k,
                    key=norm_k,
                    raw_value=raw_v,
                    clean_value=clean_v,
                )
            )
        else:
            clean_seg = raw_seg.replace(r"\·", " · ").strip()
            segments.append(
                BulletSegment(
                    raw_key=None,
                    key="",
                    raw_value=raw_seg,
                    clean_value=clean_seg,
                )
            )
    return prefix, segments


def serialize_bullet_segments(prefix: str, segments: list[BulletSegment]) -> str:
    """Serialize segments back to bullet line preserving exact format."""
    pieces = []
    for seg in segments:
        if seg.raw_key is not None:
            if seg.raw_value:
                pieces.append(f"**{seg.raw_key}:** {seg.raw_value}")
            else:
                pieces.append(f"**{seg.raw_key}:**")
        else:
            pieces.append(seg.raw_value)
    return prefix + " · ".join(pieces)


def _parse_depends_on_items(raw_val: str) -> tuple[list[tuple[str, str]], str]:
    """Split a `Depends on` value into `(id, annotation)` items and trailing free text (spec S7).

    The list is ids separated by `,`; an id may carry a parenthesised note before the next comma
    (`07.4 (same file), T012`). Whatever follows the last id (`(same file)`, ` — supervisor`,
    `, frontend lane after 10.5`) is the free text.
    """
    if not raw_val or raw_val.strip() == "-":
        return [], ""
    val = raw_val.strip()
    items: list[tuple[str, str]] = []
    pos = 0
    item_re = DEP_ITEM_RE
    # Multi-letter suffixed legacy ids (`12.2ab`) are kept verbatim in the list but are not ids.
    legacy_re = re.compile(r"\s*`?(\d{2,}(?:\.\d+)+[a-z]{2,})`?(\s*\([^()]*\))?(?![\w.])")
    sep_re = re.compile(r"\s*,")
    last_end = 0
    while True:
        m = item_re.match(val, pos)
        if m:
            items.append((m.group(1), m.group(2) or ""))
        else:
            m = legacy_re.match(val, pos)
            if not m:
                break
            items.append(("\0" + m.group(1), m.group(2) or ""))
        last_end = m.end()
        sep = sep_re.match(val, last_end)
        if not sep:
            break
        pos = sep.end()
    if not items:
        return [], val
    # The note of the last id is free text (it is kept at the end on rewrite).
    last_id, last_note = items[-1]
    free_text = val[last_end - len(last_note):].rstrip() if last_note else val[last_end:].rstrip()
    items[-1] = (last_id, "")
    return items, free_text


def parse_depends_on_field(raw_val: str) -> tuple[list[str], str]:
    items, free_text = _parse_depends_on_items(raw_val)
    return list(dict.fromkeys(i for i, _ in items if not i.startswith("\0"))), free_text


def update_depends_on_field(raw_val: str, new_ids: list[str]) -> str:
    """Rewrite the id list only; per-id notes, legacy (letter-suffixed) items and the trailing
    free text are kept byte-for-byte."""
    items, free_text = _parse_depends_on_items(raw_val)
    notes = {i: n for i, n in items if n}
    legacy = [f"{i[1:]}{n}" for i, n in items if i.startswith("\0")]
    parts = legacy + [f"{i}{notes.get(i, '')}" for i in new_ids]
    ids_str = ", ".join(parts) if parts else "-"
    if free_text:
        if not free_text.startswith((" ", ",")) and ids_str != "-":
            return f"{ids_str} {free_text}"
        return f"{ids_str}{free_text}"
    return ids_str


def format_id_ranges(ids: list[str]) -> str:
    """Format a list of dotted/task IDs into contiguous ranges using en-dash (–),
    e.g. ['06.1'..'06.8', '06.10'] -> '06.1–06.8, 06.10'."""
    if not ids:
        return ""
    prefix_items: dict[str, list[int]] = {}
    other_items: list[str] = []
    for tid in ids:
        m = re.match(r"^(.+)\.(\d+)$", tid)
        if m:
            pfx, num = m.group(1), int(m.group(2))
            prefix_items.setdefault(pfx, []).append(num)
        else:
            other_items.append(tid)

    parts: list[str] = []
    for pfx, nums in prefix_items.items():
        nums = sorted(set(nums))
        ranges: list[tuple[int, int]] = []
        start = nums[0]
        end = nums[0]
        for n in nums[1:]:
            if n == end + 1:
                end = n
            else:
                ranges.append((start, end))
                start = end = n
        ranges.append((start, end))
        for s, e in ranges:
            if s == e:
                parts.append(f"{pfx}.{s}")
            else:
                parts.append(f"{pfx}.{s}–{pfx}.{e}")
    parts.extend(other_items)
    return ", ".join(parts)


def derive_container_state(child_states: list[str]) -> str:
    """Evaluate S5 total function over child states:
    1. no children -> open (with validator warning "empty container")
    2. every child is dropped -> dropped
    3. every child is done, done with a caveat or dropped -> done, or done with a caveat when at least one child is
    4. any child is past open (in progress, delivered, bounced, verified, done, done with a caveat) -> in progress
    5. any child is blocked -> blocked
    6. any child is waiting -> waiting
    7. otherwise -> open
    """
    if not child_states:
        return "open"
    canon_states = [normalize_state(st) for st in child_states]
    if all(st == "dropped" for st in canon_states):
        return "dropped"
    if all(st in ("done", "done with a caveat", "dropped") for st in canon_states):
        if any(st == "done with a caveat" for st in canon_states):
            return "done with a caveat"
        return "done"
    if any(st in ("in progress", "delivered", "bounced", "verified", "done", "done with a caveat") for st in canon_states):
        return "in progress"
    if any(st == "blocked" for st in canon_states):
        return "blocked"
    if any(st == "waiting" for st in canon_states):
        return "waiting"
    return "open"


def _natural_sort_key(s: str) -> list[tuple[int, int | str]]:
    parts = re.split(r"(\d+)", s)
    return [(0, int(p)) if p.isdigit() else (1, p) for p in parts if p]


def _normalize_id_list(raw_ids: list[str] | str | None) -> list[str]:
    if raw_ids is None:
        return []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    result: list[str] = []
    for item in raw_ids:
        for part in re.split(r"[\s,]+", item.strip()):
            p = part.strip()
            if p and p != "-":
                result.append(p)
    return result


def parse_conditions_field(raw_val: Any) -> list[str]:
    """Parse comma-separated question IDs from conditions header/field, e.g. 'Q003, Q007' -> ['Q003', 'Q007']."""
    if not raw_val or str(raw_val).strip() in ("", "-"):
        return []
    return [p.strip() for p in str(raw_val).split(",") if p.strip() and p.strip() != "-"]


def resolve_task_conditions(
    tasks_dir: pathlib.Path,
    cond_ids: list[str],
    task_state: str,
    questions_map: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Resolve condition question IDs to [{id, status, short_title, age_days, decider}] and compute conditional boolean.

    A task in state done (or verified/delivered) whose conditions include at least one question
    NOT yet answered is 'conditional'.
    """
    if not cond_ids:
        return [], False
    if questions_map is None:
        all_q = discover_questions(tasks_dir)
        questions_map = {q["id"]: q for q in all_q}

    today = datetime.date.today()
    conditions_list: list[dict[str, Any]] = []
    for qid in cond_ids:
        q = questions_map.get(qid)
        if q:
            asked_str = q.get("asked", "")
            age_days = 0
            if asked_str:
                try:
                    asked_date = datetime.date.fromisoformat(str(asked_str).strip()[:10])
                    age_days = max(0, (today - asked_date).days)
                except Exception:
                    age_days = 0
            decider_val = q.get("decider", "").strip() or "owner"
            conditions_list.append({
                "id": qid,
                "status": q.get("status", "unknown"),
                "short_title": q.get("short_title", qid),
                "age_days": age_days,
                "decider": decider_val,
            })
        else:
            conditions_list.append({
                "id": qid,
                "status": "unknown",
                "short_title": qid,
                "age_days": 0,
                "decider": "-",
            })

    canon = normalize_state(task_state)
    is_conditional = (
        canon in ("done", "done with a caveat", "verified", "delivered")
        and any(c["status"] != "answered" for c in conditions_list)
    )
    return conditions_list, is_conditional


@dataclass
class TaskNode:
    id: str
    title: str
    parent: str | None
    depth: int
    node_type: str  # "initiative" | "container" | "leaf" | "microtask"
    is_leaf: bool
    is_container: bool
    children: list[str]
    own_fields: dict[str, Any]
    fields: dict[str, dict[str, Any]]
    labels: list[str]
    label_sources: dict[str, str]
    depends_on: list[str]
    expanded_depends_on: list[str]
    own_depends_on: list[str]
    depends_on_free_text: str
    state: str
    canonical_state: str
    derived_state: str | None
    leaves_done: int
    leaves_total: int
    file_path: str
    rel_path: str
    is_folder: bool
    in_done: bool
    in_closed_section: bool
    task_hash: str
    block_text: str | None = None
    expanded_rel_path: str | None = None
    priority: str = "P2"
    priority_source: str = "default"
    priority_reason: str = ""
    size: str = "M"
    size_source: str = "default"
    kind: str | None = None
    executor: str = "kilo"
    handoff: str = ""
    category: str = ""
    slug: str = ""
    short: str | None = None
    short_title: str = ""
    short_title_source: str = "derived"
    coordinates: list[dict[str, Any]] = field(default_factory=list)
    conditions: list[dict[str, Any]] = field(default_factory=list)
    conditional: bool = False
    own_conditions: list[str] = field(default_factory=list)
    waiting_on: str | None = None
    verify_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        res = {
            "kind": self.kind or ("initiative_task" if "." in self.id and not self.id.startswith("T") else ("emergent" if self.id.startswith("T") else "initiative")),
            "id": self.id,
            "title": self.title,
            "short": self.short,
            "short_title": self.short_title,
            "short_title_source": self.short_title_source,
            "coordinates": list(self.coordinates),
            "conditions": list(self.conditions),
            "conditional": self.conditional,
            "waiting_on": self.waiting_on,
            "verify_by": self.verify_by,
            "verify-by": self.verify_by,
            "parent": self.parent,
            "depth": self.depth,
            "node_type": self.node_type,
            "is_leaf": self.is_leaf,
            "is_container": self.is_container,
            "children": list(self.children),
            "fields": self.fields,
            "labels": list(self.labels),
            "label_sources": dict(self.label_sources),
            "depends_on": list(self.depends_on),
            "expanded_depends_on": list(self.expanded_depends_on),
            "state": self.state,
            "canonical_state": self.canonical_state,
            "derived_state": self.derived_state,
            "leaves_done": self.leaves_done,
            "leaves_total": self.leaves_total,
            "file_path": self.file_path,
            "rel_path": self.rel_path,
            "is_folder": self.is_folder,
            "in_done": self.in_done,
            "in_closed_section": self.in_closed_section,
            "bundle_sha256": self.task_hash,
            "task_hash": self.task_hash,
            "priority": self.priority,
            "priority_source": self.priority_source,
            "priority_reason": self.priority_reason,
            "size": self.size,
            "size_source": self.size_source,
            "executor": self.executor,
            "handoff": self.handoff,
            "category": self.category,
            "slug": self.slug,
        }
        if self.executor.startswith("workspace:"):
            res["external_executor"] = {
                "kind": "workspace",
                "workspace": self.executor[len("workspace:"):].strip().split("/")[0],
            }
        elif self.executor.startswith("session:"):
            res["external_executor"] = {
                "kind": "session",
                "session": self.executor[len("session:"):].strip(),
            }
        return res


def rewrite_block_in_file(
    file_path: pathlib.Path,
    task_id: str,
    new_status: str | None = None,
    new_deps: list[str] | None = None,
    new_labels: list[str] | None = None,
    new_priority: str | None = None,
    new_size: str | None = None,
    new_kind: str | None = None,
    new_executor: str | None = None,
    new_decider: str | None = None,
    new_short: str | None = None,
    expect_task_hash: str | None = None,
    status_note: str | None = None,
    dry_run: bool = False,
    return_diff: bool = False,
    new_conditions: str | None = None,
    new_waiting_on: str | None = None,
    clear_waiting_on: bool = False,
    new_verify_by: str | None = None,
    clear_verify_by: bool = False,
) -> tuple[str, str] | tuple[str, str, str]:
    """Rewrite one `### id - title` block in place; every other byte of the file is preserved.

    A new status replaces the Status value (code span kept) and its parenthesised note, which
    becomes `status_note` when given: `- **Status:** `in progress` (2026-10-17; claude; reason)`.
    """
    if new_waiting_on is not None:
        new_waiting_on = normalize_waiting_on(new_waiting_on)
    if new_status is not None:
        c_st = normalize_state(new_status)
        if c_st == "waiting":
            extracted = extract_waiting_on(new_status)
            if new_waiting_on is None and extracted:
                new_waiting_on = extracted
        elif new_waiting_on is None:
            clear_waiting_on = True

    text = file_path.read_text(encoding="utf-8")
    heading_re = re.compile(
        rf"^###\s+{re.escape(task_id)}\s+[—–-]\s+.*$",
        re.MULTILINE,
    )
    m = heading_re.search(text)
    if not m:
        raise ValueError(f"Block for task '{task_id}' not found in {file_path}")

    start_pos = m.start()
    scanned_lines, _ = scan_markdown_blocks(text)
    heading_line_num = text[:start_pos].count("\n") + 1
    heading_sline_idx = next(
        (i for i, sl in enumerate(scanned_lines) if sl.line_number == heading_line_num),
        None,
    )

    end_pos = len(text)
    if heading_sline_idx is not None:
        for idx in range(heading_sline_idx + 1, len(scanned_lines)):
            sl = scanned_lines[idx]
            if not sl.is_fenced and (sl.text.startswith("### ") or sl.text.startswith("## ")):
                end_pos = sum(len(sl2.text) + 1 for sl2 in scanned_lines[:idx])
                break

    old_block_text = text[start_pos:end_pos]
    if expect_task_hash:
        curr_h = hashlib.sha256(old_block_text.encode("utf-8")).hexdigest()
        if curr_h.lower() != expect_task_hash.strip().lower():
            raise ValueError(f"Task hash mismatch: expected {expect_task_hash}, actual {curr_h}")

    lines = old_block_text.splitlines(keepends=True)
    priority_updated = False
    size_updated = False
    kind_updated = False
    executor_updated = False
    labels_updated = False
    deps_updated = False
    decider_updated = False
    short_updated = False
    waiting_on_updated = False
    verify_by_updated = False
    status_line_idx: int | None = None

    parsed_lines: list[tuple[str, list[BulletSegment], str, bool, str]] = []

    for line in lines:
        line_clean = line.rstrip("\r\n")
        line_ending = line[len(line_clean):]

        if re.match(r"^\s*[-*]\s+", line_clean):
            prefix, segments = parse_bullet_line(line_clean)
            has_status = any(seg.key in ("status", "state") for seg in segments)
            if has_status and status_line_idx is None:
                status_line_idx = len(parsed_lines)

            if new_status is not None:
                for seg in segments:
                    if seg.key in ("status", "state"):
                        if "`" in seg.raw_value:
                            new_raw = f"`{new_status}`"
                        else:
                            new_raw = new_status
                        if status_note:
                            new_raw += f" ({status_note})"
                        seg.raw_value = new_raw
                        seg.clean_value = new_status

            if new_deps is not None:
                for seg in segments:
                    if seg.key in ("depends_on", "depends"):
                        seg.raw_value = update_depends_on_field(seg.raw_value, new_deps)
                        seg.clean_value = seg.raw_value
                        deps_updated = True

            if new_labels is not None:
                for seg in segments:
                    if seg.key in ("labels", "label"):
                        seg.raw_value = ", ".join(new_labels) if new_labels else "-"
                        seg.clean_value = seg.raw_value
                        labels_updated = True

            if new_priority is not None:
                for seg in segments:
                    if seg.key in ("priority",):
                        seg.raw_value = new_priority
                        seg.clean_value = new_priority
                        priority_updated = True

            if new_size is not None:
                for seg in segments:
                    if seg.key in ("size",):
                        seg.raw_value = new_size
                        seg.clean_value = new_size
                        size_updated = True

            if new_kind is not None:
                for seg in segments:
                    if seg.key in ("kind",):
                        seg.raw_value = new_kind
                        seg.clean_value = new_kind
                        kind_updated = True

            if new_executor is not None:
                for seg in segments:
                    if seg.key in ("executor",):
                        seg.raw_value = new_executor
                        seg.clean_value = new_executor
                        executor_updated = True

            if new_short is not None:
                for seg in segments:
                    if seg.key in ("short", "short_title"):
                        seg.raw_value = new_short
                        seg.clean_value = new_short
                        short_updated = True

            if new_decider is not None:
                to_remove = []
                for s_idx, seg in enumerate(segments):
                    if seg.key in ("decider",):
                        if new_decider == "-" or not new_decider.strip():
                            to_remove.append(s_idx)
                        else:
                            seg.raw_value = new_decider
                            seg.clean_value = new_decider
                        decider_updated = True
                for s_idx in reversed(to_remove):
                    segments.pop(s_idx)

            if new_conditions is not None:
                to_remove = []
                for s_idx, seg in enumerate(segments):
                    if seg.key in ("conditions",):
                        if new_conditions == "-" or not new_conditions.strip():
                            to_remove.append(s_idx)
                        else:
                            seg.raw_value = new_conditions
                            seg.clean_value = new_conditions
                for s_idx in reversed(to_remove):
                    segments.pop(s_idx)

            if new_waiting_on is not None or clear_waiting_on:
                to_remove = []
                for s_idx, seg in enumerate(segments):
                    if seg.key in ("waiting_on", "waiting-on"):
                        if clear_waiting_on or (new_waiting_on is not None and (new_waiting_on == "-" or not new_waiting_on.strip())):
                            to_remove.append(s_idx)
                        else:
                            seg.raw_value = new_waiting_on
                            seg.clean_value = new_waiting_on
                            waiting_on_updated = True
                for s_idx in reversed(to_remove):
                    segments.pop(s_idx)

            if new_verify_by is not None or clear_verify_by:
                to_remove = []
                for s_idx, seg in enumerate(segments):
                    if seg.key in ("verify_by", "verify-by"):
                        if clear_verify_by or (new_verify_by is not None and (new_verify_by == "-" or not new_verify_by.strip())):
                            to_remove.append(s_idx)
                        else:
                            seg.raw_value = new_verify_by
                            seg.clean_value = new_verify_by
                            verify_by_updated = True
                for s_idx in reversed(to_remove):
                    segments.pop(s_idx)

            if re.match(r"^\s*[-*]\s+waiting[-_]on:\s*", line_clean, re.IGNORECASE):
                if clear_waiting_on or (new_waiting_on is not None and (new_waiting_on == "-" or not new_waiting_on.strip())):
                    continue
                elif new_waiting_on is not None:
                    parsed_lines.append(("", [], line_ending, False, f"{prefix}waiting-on: {new_waiting_on}" + line_ending))
                    waiting_on_updated = True
                    continue

            if re.match(r"^\s*[-*]\s+verify[-_]by:\s*", line_clean, re.IGNORECASE):
                if clear_verify_by or (new_verify_by is not None and (new_verify_by == "-" or not new_verify_by.strip())):
                    continue
                elif new_verify_by is not None:
                    parsed_lines.append(("", [], line_ending, False, f"{prefix}verify-by: {new_verify_by}" + line_ending))
                    verify_by_updated = True
                    continue

            parsed_lines.append((prefix, segments, line_ending, True, line))
        else:
            parsed_lines.append(("", [], line, False, line))

    # If priority, size, kind, labels, or deps were not present in existing segments, insert them into the Status bullet
    if status_line_idx is None:
        for idx, (pfx, segs, le, is_b, orig) in enumerate(parsed_lines):
            if is_b:
                status_line_idx = idx
                break

    if status_line_idx is not None:
        prefix, segments, line_ending, is_b, orig = parsed_lines[status_line_idx]

        status_pos = None
        for i, seg in enumerate(segments):
            if seg.key in ("status", "state"):
                status_pos = i
                break
        insert_idx = (status_pos + 1) if status_pos is not None else len(segments)

        if new_size is not None and not size_updated:
            new_seg = BulletSegment(raw_key="Size", key="size", raw_value=new_size, clean_value=new_size)
            segments.insert(insert_idx, new_seg)
            insert_idx += 1
            size_updated = True

        if new_priority is not None and not priority_updated:
            new_seg = BulletSegment(raw_key="Priority", key="priority", raw_value=new_priority, clean_value=new_priority)
            segments.insert(insert_idx, new_seg)
            insert_idx += 1
            priority_updated = True

        if new_short is not None and not short_updated:
            new_seg = BulletSegment(raw_key="Short", key="short", raw_value=new_short, clean_value=new_short)
            segments.insert(insert_idx, new_seg)
            insert_idx += 1
            short_updated = True

        if new_kind is not None and not kind_updated:
            new_seg = BulletSegment(raw_key="Kind", key="kind", raw_value=new_kind, clean_value=new_kind)
            segments.insert(insert_idx, new_seg)
            insert_idx += 1
            kind_updated = True

        if new_executor is not None and not executor_updated:
            new_seg = BulletSegment(raw_key="Executor", key="executor", raw_value=new_executor, clean_value=new_executor)
            segments.insert(insert_idx, new_seg)
            insert_idx += 1
            executor_updated = True

        if new_deps is not None and not deps_updated:
            deps_val = update_depends_on_field("", new_deps)
            new_seg = BulletSegment(raw_key="Depends on", key="depends_on", raw_value=deps_val, clean_value=deps_val)
            segments.append(new_seg)
            deps_updated = True

        if new_labels is not None and not labels_updated:
            lbl_val = ", ".join(new_labels) if new_labels else "-"
            new_seg = BulletSegment(raw_key="Labels", key="labels", raw_value=lbl_val, clean_value=lbl_val)
            segments.append(new_seg)
            labels_updated = True

        if new_decider is not None and not decider_updated and new_decider != "-" and new_decider.strip():
            new_seg = BulletSegment(raw_key="Decider", key="decider", raw_value=new_decider, clean_value=new_decider)
            segments.insert(insert_idx, new_seg)
            insert_idx += 1
            decider_updated = True

        if new_waiting_on is not None and not waiting_on_updated and not clear_waiting_on and new_waiting_on != "-" and new_waiting_on.strip():
            new_seg = BulletSegment(raw_key="Waiting-on", key="waiting-on", raw_value=new_waiting_on, clean_value=new_waiting_on)
            segments.insert(insert_idx, new_seg)
            insert_idx += 1
            waiting_on_updated = True

        if new_verify_by is not None and not verify_by_updated and not clear_verify_by and new_verify_by != "-" and new_verify_by.strip():
            new_seg = BulletSegment(raw_key="Verify-by", key="verify-by", raw_value=new_verify_by, clean_value=new_verify_by)
            segments.insert(insert_idx, new_seg)
            insert_idx += 1
            verify_by_updated = True

        parsed_lines[status_line_idx] = (prefix, segments, line_ending, is_b, orig)

    new_lines: list[str] = []
    for prefix, segments, line_ending, is_b, orig in parsed_lines:
        if is_b:
            new_lines.append(serialize_bullet_segments(prefix, segments) + line_ending)
        else:
            new_lines.append(orig)

    new_block_text = "".join(new_lines)
    new_text = text[:start_pos] + new_block_text + text[end_pos:]

    diff_lines = list(difflib.unified_diff(
        text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=str(file_path),
        tofile=str(file_path) if not dry_run else f"{file_path} (dry-run)",
    ))
    diff_str = "".join(diff_lines)

    if not dry_run:
        _atomic_write_text(file_path, new_text, encoding="utf-8")
    new_hash = hashlib.sha256(new_block_text.encode("utf-8")).hexdigest()

    if return_diff:
        return new_block_text, new_hash, diff_str
    return new_block_text, new_hash


def move_block_to_closed(
    file_path: pathlib.Path,
    task_id: str,
    new_status: str | None = None,
    status_note: str | None = None,
    expect_task_hash: str | None = None,
    new_waiting_on: str | None = None,
    clear_waiting_on: bool = False,
    new_verify_by: str | None = None,
    clear_verify_by: bool = False,
) -> tuple[str, str]:
    """Move a block ### task_id to the ## Closed section of file_path.
    If new_status is given, the status line is updated first.
    Appends the block to ## Closed (creating ## Closed at end of file if not present).
    """
    if new_status is not None:
        rewrite_block_in_file(
            file_path,
            task_id,
            new_status=new_status,
            status_note=status_note,
            expect_task_hash=expect_task_hash,
            new_waiting_on=new_waiting_on,
            clear_waiting_on=clear_waiting_on,
            new_verify_by=new_verify_by,
            clear_verify_by=clear_verify_by,
        )

    text = file_path.read_text(encoding="utf-8")
    heading_re = re.compile(
        rf"^###\s+{re.escape(task_id)}\s+[—–-]\s+.*$",
        re.MULTILINE,
    )
    m = heading_re.search(text)
    if not m:
        raise ValueError(f"Block for task '{task_id}' not found in {file_path}")

    start_pos = m.start()
    scanned_lines, _ = scan_markdown_blocks(text)
    heading_line_num = text[:start_pos].count("\n") + 1
    heading_sline_idx = next(
        (i for i, sl in enumerate(scanned_lines) if sl.line_number == heading_line_num),
        None,
    )

    end_pos = len(text)
    if heading_sline_idx is not None:
        for idx in range(heading_sline_idx + 1, len(scanned_lines)):
            sl = scanned_lines[idx]
            if not sl.is_fenced and (sl.text.startswith("### ") or sl.text.startswith("## ")):
                end_pos = sum(len(sl2.text) + 1 for sl2 in scanned_lines[:idx])
                break

    block_text = text[start_pos:end_pos]
    if expect_task_hash and new_status is None:
        curr_h = hashlib.sha256(block_text.encode("utf-8")).hexdigest()
        if curr_h.lower() != expect_task_hash.strip().lower():
            raise ValueError(f"Task hash mismatch: expected {expect_task_hash}, actual {curr_h}")
    m_closed = re.search(r"^##\s+Closed\b.*$", text, re.MULTILINE)
    if m_closed and start_pos > m_closed.start():
        # Already under ## Closed
        return block_text, hashlib.sha256(block_text.encode("utf-8")).hexdigest()

    before = text[:start_pos].rstrip("\n")
    after = text[end_pos:].lstrip("\n")
    if before and after:
        text_without = before + "\n\n" + after
    elif before:
        text_without = before + "\n"
    else:
        text_without = after

    m_closed2 = re.search(r"^##\s+Closed\b.*$", text_without, re.MULTILINE)
    if m_closed2:
        post = text_without[m_closed2.end():]
        m_next = re.search(r"^##\s+", post, re.MULTILINE)
        if m_next:
            sec_end = m_closed2.end() + m_next.start()
            pre_sec = text_without[:sec_end].rstrip("\n")
            post_sec = text_without[sec_end:].lstrip("\n")
            new_text = pre_sec + "\n\n" + block_text.strip() + "\n\n" + post_sec
        else:
            new_text = text_without.rstrip("\n") + "\n\n" + block_text.strip() + "\n"
    else:
        new_text = text_without.rstrip("\n") + "\n\n## Closed\n\n" + block_text.strip() + "\n"

    _atomic_write_text(file_path, new_text, encoding="utf-8")
    new_h = hashlib.sha256(block_text.encode("utf-8")).hexdigest()
    return block_text, new_h


def move_block_to_open(
    file_path: pathlib.Path,
    task_id: str,
    new_status: str = "open",
    status_note: str | None = None,
    expect_task_hash: str | None = None,
) -> tuple[str, str]:
    """Move a block ### task_id out of ## Closed back into the open section of file_path.
    Inserts in sorted ID order among open sibling blocks.
    Removes ## Closed if no blocks remain in it.
    """
    new_block_text, new_h = rewrite_block_in_file(
        file_path, task_id, new_status=new_status, status_note=status_note, expect_task_hash=expect_task_hash
    )
    text = file_path.read_text(encoding="utf-8")
    heading_re = re.compile(
        rf"^###\s+{re.escape(task_id)}\s+[—–-]\s+.*$",
        re.MULTILINE,
    )
    m = heading_re.search(text)
    if not m:
        return new_block_text, new_h

    start_pos = m.start()
    scanned_lines, _ = scan_markdown_blocks(text)
    heading_line_num = text[:start_pos].count("\n") + 1
    heading_sline_idx = next(
        (i for i, sl in enumerate(scanned_lines) if sl.line_number == heading_line_num),
        None,
    )

    end_pos = len(text)
    if heading_sline_idx is not None:
        for idx in range(heading_sline_idx + 1, len(scanned_lines)):
            sl = scanned_lines[idx]
            if not sl.is_fenced and (sl.text.startswith("### ") or sl.text.startswith("## ")):
                end_pos = sum(len(sl2.text) + 1 for sl2 in scanned_lines[:idx])
                break

    m_closed = re.search(r"^##\s+Closed\b.*$", text, re.MULTILINE)
    if not m_closed or start_pos < m_closed.start():
        return new_block_text, new_h

    before = text[:start_pos].rstrip("\n")
    after = text[end_pos:].lstrip("\n")
    if before and after:
        text_without = before + "\n\n" + after
    elif before:
        text_without = before + "\n"
    else:
        text_without = after

    m_closed2 = re.search(r"^##\s+Closed\b.*$", text_without, re.MULTILINE)
    closed_start = m_closed2.start() if m_closed2 else len(text_without)

    open_headings = list(re.finditer(
        r"^###\s+((?:T\d{3,}|\d{2,})(?:\.\d+[a-z]?)+)\s+[—–-]\s+",
        text_without[:closed_start],
        re.MULTILINE,
    ))

    target_key = _natural_sort_key(task_id)
    insert_pos = None
    for oh in open_headings:
        if _natural_sort_key(oh.group(1)) > target_key:
            insert_pos = oh.start()
            break

    if insert_pos is not None:
        pre = text_without[:insert_pos].rstrip("\n")
        post = text_without[insert_pos:].lstrip("\n")
        new_text = pre + "\n\n" + new_block_text.strip() + "\n\n" + post
    else:
        pre = text_without[:closed_start].rstrip("\n")
        post = text_without[closed_start:].lstrip("\n")
        if post:
            new_text = pre + "\n\n" + new_block_text.strip() + "\n\n" + post
        else:
            new_text = pre + "\n\n" + new_block_text.strip() + "\n"

    # Check if ## Closed section is now empty
    m_closed3 = re.search(r"^##\s+Closed\b.*$", new_text, re.MULTILINE)
    if m_closed3:
        post_c = new_text[m_closed3.end():]
        m_next = re.search(r"^##\s+", post_c, re.MULTILINE)
        c_body = post_c[:m_next.start()] if m_next else post_c
        if not re.search(r"^###\s+", c_body, re.MULTILINE):
            pre_c = new_text[:m_closed3.start()].rstrip("\n")
            if m_next:
                new_text = pre_c + "\n\n" + post_c[m_next.start():].lstrip("\n")
            else:
                new_text = pre_c + "\n"

    _atomic_write_text(file_path, new_text, encoding="utf-8")
    new_h = hashlib.sha256(new_block_text.encode("utf-8")).hexdigest()
    return new_block_text, new_h


def rewrite_relative_markdown_links(
    text: str,
    old_target_rel: str,
    new_target_rel: str,
) -> str:
    """Rewrite Markdown links [label](url) where url targets old_target_rel to new_target_rel."""
    old_clean = old_target_rel.rstrip("/")
    new_clean = new_target_rel.rstrip("/")

    def _replace_link(m: re.Match) -> str:
        label = m.group(1)
        url = m.group(2)
        if url.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)

        url_path, sep, anchor = url.partition("#")
        if new_clean == f"done/{old_clean}":
            pat = rf"(^|(?<!done/)/)({re.escape(old_clean)})(?:/|$)"
            sub_pat = rf"(^|(?<!done/)/){re.escape(old_clean)}(/|$)"
        else:
            pat = rf"(^|/)({re.escape(old_clean)})(?:/|$)"
            sub_pat = rf"(^|/){re.escape(old_clean)}(/|$)"

        if re.search(pat, url_path):
            new_url_path = re.sub(
                sub_pat,
                rf"\g<1>{new_clean}\g<2>",
                url_path,
            )
            return f"[{label}]({new_url_path}{sep}{anchor})"
        return m.group(0)

    link_re = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    return link_re.sub(_replace_link, text)


def adjust_markdown_link_depth(text: str, depth_delta: int) -> str:
    """Adjust depth of relative links reaching outside the current folder.
    depth_delta = +1: folder moved 1 level deeper (e.g. into done/); ../ becomes ../../.
    depth_delta = -1: folder moved 1 level shallower; ../../ becomes ../.
    """
    if depth_delta == 0:
        return text

    def _replace_link(m: re.Match) -> str:
        label = m.group(1)
        url = m.group(2)
        if url.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)

        url_path, sep, anchor = url.partition("#")
        if depth_delta > 0:
            if url_path.startswith("../"):
                new_path = ("../" * depth_delta) + url_path
                return f"[{label}]({new_path}{sep}{anchor})"
        elif depth_delta < 0:
            remove_count = abs(depth_delta)
            prefix = "../" * remove_count
            if url_path.startswith(prefix):
                new_path = url_path[len(prefix):]
                return f"[{label}]({new_path}{sep}{anchor})"
        return m.group(0)

    link_re = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    return link_re.sub(_replace_link, text)


def rewrite_links_in_text(text: str, old_rel: str, new_rel: str) -> str:
    """Rewrite both markdown links and sources:/produced: header lines."""
    text = rewrite_relative_markdown_links(text, old_rel, new_rel)
    old_clean = old_rel.rstrip("/")
    new_clean = new_rel.rstrip("/")
    lines = text.splitlines(keepends=True)
    new_lines = []
    for line in lines:
        if re.match(r"^\s*[-*]?\s*(?:sources|produced):", line, re.IGNORECASE):
            if new_clean == f"done/{old_clean}":
                pat = rf"(^|[/\s](?<!done/))({re.escape(old_clean)})(?:/|[\s]|$)"
                sub_pat = rf"(^|[/\s](?<!done/)){re.escape(old_clean)}(/|[\s]|$)"
            else:
                pat = rf"(^|[/\s])({re.escape(old_clean)})(?:/|[\s]|$)"
                sub_pat = rf"(^|[/\s]){re.escape(old_clean)}(/|[\s]|$)"
            if re.search(pat, line):
                line = re.sub(
                    sub_pat,
                    rf"\g<1>{new_clean}\g<2>",
                    line,
                )
        new_lines.append(line)
    return "".join(new_lines)


def check_markdown_links(tasks_dir: pathlib.Path) -> list[str]:
    """Check all relative markdown links in tasks_dir to ensure targets exist."""
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    broken: list[str] = []
    link_re = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    for md_file in tasks_dir.rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in link_re.finditer(text):
            url = m.group(2).strip()
            if url.startswith(("http://", "https://", "mailto:", "#")):
                continue
            url_path = url.split("#")[0].strip()
            if not url_path:
                continue
            resolved = (md_file.parent / url_path).resolve()
            if not resolved.exists():
                broken.append(
                    f"{md_file.relative_to(tasks_dir).as_posix()}: link '{url}' does not resolve to existing path"
                )
    return broken


def move_folder_child_to_done(parent_dir: pathlib.Path, folder_child_id: str, tasks_dir: pathlib.Path) -> pathlib.Path:
    """Move an expanded folder child <parent_dir>/<id>-<slug> into <parent_dir>/done/<id>-<slug>."""
    parent_dir = pathlib.Path(parent_dir).resolve()
    matches = [
        d for d in parent_dir.iterdir()
        if d.is_dir() and (d.name == folder_child_id or d.name.startswith(f"{folder_child_id}-"))
    ]
    if not matches:
        raise ValueError(f"Folder child '{folder_child_id}' not found in {parent_dir}")
    src_folder = matches[0]
    folder_name = src_folder.name

    done_dir = parent_dir / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    dest_folder = done_dir / folder_name

    # Adjust link depth for markdown files inside folder (+1 depth delta)
    for md in src_folder.rglob("*.md"):
        old_t = md.read_text(encoding="utf-8")
        new_t = adjust_markdown_link_depth(old_t, depth_delta=1)
        if new_t != old_t:
            _atomic_write_text(md, new_t, encoding="utf-8")

    res = subprocess.run(
        ["git", "mv", str(src_folder), str(dest_folder)],
        cwd=str(tasks_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        shutil.move(str(src_folder), str(dest_folder))

    parent_md = parent_dir / "plan.md" if (parent_dir / "plan.md").is_file() else parent_dir / "README.md"
    if parent_md.is_file():
        p_text = parent_md.read_text(encoding="utf-8")
        old_bullet = f"- **Expanded:** [{folder_name}/]({folder_name}/README.md)"
        new_bullet = f"- **Expanded:** [done/{folder_name}/](done/{folder_name}/README.md)"
        if old_bullet in p_text:
            p_text = p_text.replace(old_bullet, new_bullet)
            _atomic_write_text(parent_md, p_text, encoding="utf-8")
        move_block_to_closed(parent_md, folder_child_id)

    rel_old = src_folder.relative_to(tasks_dir).as_posix()
    rel_new = dest_folder.relative_to(tasks_dir).as_posix()
    for md in tasks_dir.rglob("*.md"):
        if md.is_relative_to(dest_folder) or md == parent_md:
            continue
        md_text = md.read_text(encoding="utf-8")
        new_md_text = rewrite_links_in_text(md_text, rel_old, rel_new)
        if new_md_text != md_text:
            _atomic_write_text(md, new_md_text, encoding="utf-8")

    return dest_folder / "README.md"


def move_folder_child_to_open(parent_dir: pathlib.Path, folder_child_id: str, tasks_dir: pathlib.Path) -> pathlib.Path:
    """Move an expanded folder child back from <parent_dir>/done/<id>-<slug> to <parent_dir>/<id>-<slug>."""
    parent_dir = pathlib.Path(parent_dir).resolve()
    done_dir = parent_dir / "done"
    matches = [
        d for d in done_dir.iterdir()
        if d.is_dir() and (d.name == folder_child_id or d.name.startswith(f"{folder_child_id}-"))
    ]
    if not matches:
        raise ValueError(f"Folder child '{folder_child_id}' not found in {done_dir}")
    src_folder = matches[0]
    folder_name = src_folder.name
    dest_folder = parent_dir / folder_name

    # Adjust link depth for markdown files inside folder (-1 depth delta)
    for md in src_folder.rglob("*.md"):
        old_t = md.read_text(encoding="utf-8")
        new_t = adjust_markdown_link_depth(old_t, depth_delta=-1)
        if new_t != old_t:
            _atomic_write_text(md, new_t, encoding="utf-8")

    res = subprocess.run(
        ["git", "mv", str(src_folder), str(dest_folder)],
        cwd=str(tasks_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        shutil.move(str(src_folder), str(dest_folder))

    parent_md = parent_dir / "plan.md" if (parent_dir / "plan.md").is_file() else parent_dir / "README.md"
    if parent_md.is_file():
        move_block_to_open(parent_md, folder_child_id)
        p_text = parent_md.read_text(encoding="utf-8")
        old_bullet = f"- **Expanded:** [done/{folder_name}/](done/{folder_name}/README.md)"
        new_bullet = f"- **Expanded:** [{folder_name}/]({folder_name}/README.md)"
        if old_bullet in p_text:
            p_text = p_text.replace(old_bullet, new_bullet)
            _atomic_write_text(parent_md, p_text, encoding="utf-8")

    if done_dir.is_dir() and not list(done_dir.iterdir()):
        try:
            done_dir.rmdir()
        except Exception:
            pass

    rel_old = src_folder.relative_to(tasks_dir).as_posix()
    rel_new = dest_folder.relative_to(tasks_dir).as_posix()
    for md in tasks_dir.rglob("*.md"):
        if md.is_relative_to(dest_folder) or md == parent_md:
            continue
        md_text = md.read_text(encoding="utf-8")
        new_md_text = rewrite_links_in_text(md_text, rel_old, rel_new)
        if new_md_text != md_text:
            _atomic_write_text(md, new_md_text, encoding="utf-8")

    return dest_folder / "README.md"


def _status_value(raw: str) -> str:
    """The state written in a Status bullet, without its code span and parenthesised note:
    '`in progress` (2026-10-17; kilo)' -> 'in progress'; 'done with a caveat: x' is kept whole."""
    s = (raw or "").strip()
    m_tick = re.match(r"^`([^`]+)`", s)
    if m_tick:
        return m_tick.group(1).strip()
    m_note = re.match(r"^(.+?)\s*\([^)]*\)\s*$", s)
    return (m_note.group(1) if m_note else s).strip() or "open"


def parse_child_blocks(
    file_path: pathlib.Path,
    parent_id: str,
    parent_depth: int,
    tasks_dir: pathlib.Path,
    in_done: bool,
    in_closed_section: bool,
    parent_category: str = "",
) -> list[TaskNode]:
    """Parse child blocks ### <id> - <title> in file_path recursively."""
    if not file_path.is_file():
        return []

    text = file_path.read_text(encoding="utf-8")
    scanned_lines, _ = scan_markdown_blocks(text)
    nodes: list[TaskNode] = []

    block_indices: list[tuple[int, str, str, bool]] = []
    current_closed = in_closed_section

    for idx, sline in enumerate(scanned_lines):
        if sline.is_fenced:
            continue
        if sline.text.startswith("## "):
            m_sec = re.match(r"^##\s+(Closed\b.*)", sline.text, re.IGNORECASE)
            current_closed = in_closed_section or (m_sec is not None)
        elif sline.text.startswith("### "):
            m_head = re.match(r"^###\s+((?:T\d{3,}|\d{2,})(?:\.\d+[a-z]?)+)\s+[—–-]\s+(.+?)\s*$", sline.text)
            if m_head:
                cid = m_head.group(1)
                ctitle = m_head.group(2).strip()
                block_indices.append((idx, cid, ctitle, current_closed))

    raw_lines = [sl.text for sl in scanned_lines]

    for start_idx, cid, ctitle, is_closed in block_indices:
        # A block ends at the next `###`/`##` heading of any kind (also a non-canonical one such as
        # `### 12.2a - ...`), exactly where rewrite_block_in_file ends it: the block hash and the
        # rewritten span must be the same bytes, and a block must not absorb the bullets below it.
        end_idx = len(scanned_lines)
        for next_idx in range(start_idx + 1, len(scanned_lines)):
            sl = scanned_lines[next_idx]
            if not sl.is_fenced and (sl.text.startswith("### ") or sl.text.startswith("## ")):
                end_idx = next_idx
                break

        block_lines = raw_lines[start_idx:end_idx]
        block_text = "\n".join(block_lines) + "\n"
        block_hash = hashlib.sha256(block_text.encode("utf-8")).hexdigest()

        expanded_link: str | None = None
        for bl in block_lines[1:]:
            m_exp = EXPANDED_BULLET_RE.match(bl)
            if m_exp:
                expanded_link = m_exp.group(2)
                break

        if expanded_link:
            target_readme = file_path.parent / expanded_link
            rel_readme = target_readme.relative_to(tasks_dir).as_posix() if target_readme.is_relative_to(tasks_dir) else str(target_readme)
            is_done_readme = in_done or ("done" in target_readme.parts)
            c_node = TaskNode(
                id=cid,
                title=ctitle,
                parent=parent_id,
                depth=parent_depth + 1,
                node_type="container",
                is_leaf=False,
                is_container=True,
                children=[],
                own_fields={},
                fields={},
                labels=[],
                label_sources={},
                depends_on=[],
                expanded_depends_on=[],
                own_depends_on=[],
                depends_on_free_text="",
                state="open",
                canonical_state="open",
                derived_state="open",
                leaves_done=0,
                leaves_total=0,
                file_path=str(target_readme),
                rel_path=rel_readme,
                is_folder=True,
                in_done=is_done_readme,
                in_closed_section=is_closed,
                task_hash=block_hash,
                block_text=None,
                expanded_rel_path=expanded_link,
                category=parent_category,
                slug=slugify(ctitle),
                short=None,
                short_title=derive_short_title(ctitle),
                short_title_source="derived",
            )
            nodes.append(c_node)
            if target_readme.is_file():
                rtext = target_readme.read_text(encoding="utf-8")
                r_scanned, _ = scan_markdown_blocks(rtext)
                sub_own_fields: dict[str, Any] = {}
                for r_sl in r_scanned:
                    if r_sl.is_fenced or not r_sl.text.startswith("- "):
                        continue
                    _, segs = parse_bullet_line(r_sl.text)
                    for seg in segs:
                        if seg.key:
                            sub_own_fields[seg.key] = seg.clean_value
                c_node.own_fields = sub_own_fields
                if "short" in sub_own_fields and sub_own_fields["short"] and sub_own_fields["short"] != "-":
                    c_node.short = str(sub_own_fields["short"]).strip()
                    c_node.short_title = c_node.short
                    c_node.short_title_source = "field"
                if "priority" in sub_own_fields:
                    c_node.priority = sub_own_fields["priority"]
                if "executor" in sub_own_fields:
                    c_node.executor = sub_own_fields["executor"]
                if "kind" in sub_own_fields:
                    c_node.kind = sub_own_fields["kind"]
                if "labels" in sub_own_fields and sub_own_fields["labels"]:
                    raw_lbls = str(sub_own_fields["labels"]).strip()
                    c_node.labels = [l.strip() for l in raw_lbls.split(",") if l.strip() and l.strip() != "-"]
                    c_node.label_sources = {l: "own" for l in c_node.labels}
                if "coordinates" in sub_own_fields and sub_own_fields["coordinates"]:
                    raw_sub_c = str(sub_own_fields["coordinates"]).strip()
                    if raw_sub_c and raw_sub_c != "-":
                        sub_c_refs = [c.strip() for c in raw_sub_c.split(",") if c.strip() and c.strip() != "-"]
                        c_node.coordinates = resolve_coordinates(sub_c_refs, tasks_dir)
                sub_vb = sub_own_fields.get("verify_by") or sub_own_fields.get("verify-by")
                if sub_vb and str(sub_vb).strip() and str(sub_vb).strip() != "-":
                    c_node.verify_by = str(sub_vb).strip()

                sub_children = parse_child_blocks(
                    target_readme,
                    parent_id=cid,
                    parent_depth=parent_depth + 1,
                    tasks_dir=tasks_dir,
                    in_done=is_done_readme,
                    in_closed_section=is_closed,
                    parent_category=parent_category,
                )
                nodes.extend(sub_children)
        else:
            own_fields: dict[str, Any] = {}
            for bl in block_lines[1:]:
                if not bl.strip().startswith("- ") and not bl.strip().startswith("* "):
                    continue
                m_hdr = HEADER_LINE_RE.match(bl.strip())
                if m_hdr and m_hdr.group(1) in ("waiting-on", "waiting_on"):
                    own_fields["waiting_on"] = m_hdr.group(2).strip()
                elif m_hdr and m_hdr.group(1) in ("verify-by", "verify_by"):
                    own_fields["verify_by"] = m_hdr.group(2).strip()
                _, segs = parse_bullet_line(bl)
                for seg in segs:
                    if seg.key:
                        own_fields[seg.key] = seg.clean_value

            # A leaf of a shipped initiative (done/, merged/) with no Status bullet is a legacy plan
            # closed before blocks carried states: read it as done (the validator warns).
            default_status = "done" if in_done else "open"
            raw_status = _status_value(own_fields.get("status") or own_fields.get("state") or default_status)
            canon_st = normalize_state(raw_status)
            deps_val = own_fields.get("depends_on") or own_fields.get("depends") or ""
            parsed_deps, free_txt = parse_depends_on_field(deps_val)

            raw_wo = own_fields.get("waiting_on") or own_fields.get("waiting-on")
            if raw_wo and str(raw_wo).strip() and str(raw_wo).strip() != "-":
                leaf_wo = normalize_waiting_on(str(raw_wo).strip())
            else:
                leaf_wo = extract_waiting_on(raw_status)

            size_val = own_fields.get("size")
            if size_val and size_val.strip().upper() in VALID_SIZES:
                leaf_size = size_val.strip().upper()
                leaf_size_source = "own"
            else:
                leaf_size = "M"
                leaf_size_source = "default"
            p_val = own_fields.get("priority")
            p_src = "own" if p_val else "default"

            leaf_short = own_fields.get("short")
            if leaf_short and str(leaf_short).strip() and str(leaf_short).strip() != "-":
                leaf_short_val = str(leaf_short).strip()
                leaf_st = leaf_short_val
                leaf_st_src = "field"
            else:
                leaf_short_val = None
                leaf_st = derive_short_title(ctitle)
                leaf_st_src = "derived"

            coords_val = own_fields.get("coordinates")
            if coords_val and str(coords_val).strip() and str(coords_val).strip() != "-":
                plan_coords_refs = [c.strip() for c in str(coords_val).split(",") if c.strip() and c.strip() != "-"]
                node_coords = resolve_coordinates(plan_coords_refs, tasks_dir)
            else:
                node_coords = []

            cond_ids = parse_conditions_field(own_fields.get("conditions"))
            cond_list, is_cond = resolve_task_conditions(tasks_dir, cond_ids, raw_status)

            leaf_vb = own_fields.get("verify_by") or own_fields.get("verify-by") or extract_verify_by(raw_status)
            if leaf_vb and (not str(leaf_vb).strip() or str(leaf_vb).strip() == "-"):
                leaf_vb = None

            leaf_node = TaskNode(
                id=cid,
                title=ctitle,
                parent=parent_id,
                depth=parent_depth + 1,
                node_type="leaf",
                is_leaf=True,
                is_container=False,
                children=[],
                own_fields=own_fields,
                fields={},
                labels=[l.strip() for l in own_fields.get("labels", "").split(",") if l.strip()],
                label_sources={},
                depends_on=list(parsed_deps),
                expanded_depends_on=list(parsed_deps),
                own_depends_on=list(parsed_deps),
                depends_on_free_text=free_txt,
                state=raw_status,
                canonical_state=canon_st,
                derived_state=None,
                leaves_done=1 if canon_st in ("done", "done with a caveat") else 0,
                leaves_total=1,
                file_path=str(file_path),
                rel_path=file_path.relative_to(tasks_dir).as_posix(),
                is_folder=False,
                in_done=in_done,
                in_closed_section=is_closed,
                task_hash=block_hash,
                block_text=block_text,
                priority=p_val or "P2",
                priority_source=p_src,
                priority_reason=own_fields.get("priority_reason", f"Task {cid}"),
                size=leaf_size,
                size_source=leaf_size_source,
                kind=own_fields.get("kind"),
                executor=own_fields.get("executor", "kilo"),
                handoff=own_fields.get("handoff", f"Work on task {cid} in {file_path.relative_to(tasks_dir).as_posix()}"),
                category=parent_category,
                slug=slugify(ctitle),
                short=leaf_short_val,
                short_title=leaf_st,
                short_title_source=leaf_st_src,
                coordinates=node_coords,
                conditions=cond_list,
                conditional=is_cond,
                own_conditions=cond_ids,
                waiting_on=leaf_wo,
                verify_by=str(leaf_vb).strip() if leaf_vb else None,
            )
            nodes.append(leaf_node)

    return nodes


def propagate_inheritance(tree: dict[str, TaskNode], node_id: str) -> None:
    node = tree[node_id]
    parent = tree.get(node.parent) if node.parent else None

    # Priority default for root initiatives if not set
    if parent is None and node.node_type == "initiative":
        if "priority" in node.own_fields and node.own_fields["priority"]:
            node.fields["priority"] = {"value": node.own_fields["priority"], "source": "own"}
        else:
            node.fields["priority"] = {"value": "P2", "source": "default"}

    # 1. Inherited fields: executor, priority, profile, repo, paths
    for f in INHERITED_FIELDS:
        own_val = node.own_fields.get(f)
        if f == "paths" and not own_val:
            own_val = node.own_fields.get("focus_files") or node.own_fields.get("focus_file")
        if own_val is not None and own_val != "-" and own_val != "":
            node.fields[f] = {"value": own_val, "source": "own"}
        elif parent and f in parent.fields:
            p_field = parent.fields[f]
            anc_id = parent.id if p_field["source"] in ("own", "default") else p_field["source"].split(":", 1)[1]
            node.fields[f] = {"value": p_field["value"], "source": f"inherited:{anc_id}"}
        elif own_val is not None:
            node.fields[f] = {"value": own_val, "source": "own"}
        elif f == "priority":
            node.fields[f] = {"value": "P2", "source": "default"}

    # 2. Labels: union of own and ancestor labels
    own_labels = node.own_fields.get("labels", [])
    if isinstance(own_labels, str):
        own_labels = [l.strip() for l in own_labels.split(",") if l.strip()]
    label_sources: dict[str, str] = {l: "own" for l in own_labels}
    if parent:
        for l, src in parent.label_sources.items():
            if l not in label_sources:
                anc_id = parent.id if src == "own" else src.split(":", 1)[1]
                label_sources[l] = f"inherited:{anc_id}"
    all_labels = sorted(label_sources.keys())
    node.labels = all_labels
    node.label_sources = label_sources
    if all_labels:
        primary_source = "own" if any(s == "own" for s in label_sources.values()) else (list(label_sources.values())[0] if label_sources else "own")
        node.fields["labels"] = {"value": all_labels, "source": primary_source}

    # 3. Depends on: additive
    own_deps = list(node.own_depends_on)
    inherited_deps = []
    if parent:
        for dep in parent.depends_on:
            if dep not in own_deps and dep not in inherited_deps:
                inherited_deps.append(dep)
    node.depends_on = own_deps + inherited_deps
    node.fields["depends_on"] = {
        "value": node.depends_on,
        "source": "own" if own_deps else (f"inherited:{parent.id}" if parent and inherited_deps else "own"),
    }

    # 4. Non-inherited fields: kind, decider, status, verifier, verification_mode, verify_by, goal, handoff
    for f in ("kind", "decider", "status", "verifier", "verification_mode", "verify_by", "verify-by", "goal", "handoff"):
        if f in node.own_fields:
            node.fields[f] = {"value": node.own_fields[f], "source": "own"}
    if "verify_by" in node.own_fields or "verify-by" in node.own_fields:
        vb_val = node.own_fields.get("verify_by") or node.own_fields.get("verify-by")
        if vb_val and str(vb_val).strip() and str(vb_val).strip() != "-":
            node.verify_by = str(vb_val).strip()

    # Size (non-inherited; defaults to XS for microtask, M for others)
    if "size" in node.own_fields and node.own_fields["size"]:
        s_val = str(node.own_fields["size"]).strip().upper()
        if s_val in VALID_SIZES:
            node.size = s_val
            node.size_source = "own"
            node.fields["size"] = {"value": s_val, "source": "own"}
        else:
            default_s = "XS" if node.node_type == "microtask" else "M"
            node.size = default_s
            node.size_source = "default"
            node.fields["size"] = {"value": default_s, "source": "default"}
    else:
        default_s = "XS" if node.node_type == "microtask" else "M"
        node.size = default_s
        node.size_source = "default"
        node.fields["size"] = {"value": default_s, "source": "default"}

    if "executor" in node.fields:
        node.executor = node.fields["executor"]["value"]
    if "priority" in node.fields:
        node.priority = node.fields["priority"]["value"]
        node.priority_source = node.fields["priority"]["source"]
    if "handoff" in node.fields:
        node.handoff = node.fields["handoff"]["value"]

    for cid in node.children:
        if cid in tree:
            propagate_inheritance(tree, cid)


def evaluate_container_states(tree: dict[str, TaskNode], node_id: str) -> None:
    node = tree[node_id]
    for cid in node.children:
        if cid in tree:
            evaluate_container_states(tree, cid)

    if node.is_leaf:
        node.leaves_total = 1
        node.leaves_done = 1 if node.canonical_state in ("done", "done with a caveat") else 0
        node.derived_state = None
    else:
        child_nodes = [tree[cid] for cid in node.children if cid in tree]
        child_states = [c.state for c in child_nodes]
        if not child_nodes and node.node_type == "initiative" and node.in_done:
            derived = "done"
        else:
            derived = derive_container_state(child_states)
        node.derived_state = derived
        node.state = derived
        node.canonical_state = normalize_state(derived)
        node.leaves_total = sum(c.leaves_total for c in child_nodes)
        node.leaves_done = sum(c.leaves_done for c in child_nodes)


def expand_dependency_to_leaves(tree: dict[str, TaskNode], dep_id: str) -> list[str]:
    if dep_id not in tree:
        return [dep_id]
    node = tree[dep_id]
    if node.is_leaf:
        return [dep_id]
    leaves: list[str] = []
    def _collect(n: TaskNode) -> None:
        for cid in n.children:
            if cid in tree:
                c = tree[cid]
                if c.is_leaf:
                    leaves.append(c.id)
                else:
                    _collect(c)
    _collect(node)
    return leaves


def check_dependency_cycles(tree: dict[str, TaskNode]) -> list[str]:
    """Check for cycles on the expanded dependency graph (including ancestor/descendant deps)."""
    errors: list[str] = []

    for node in tree.values():
        ancestors: set[str] = set()
        curr = node.parent
        while curr and curr in tree:
            ancestors.add(curr)
            curr = tree[curr].parent

        descendants: set[str] = set()
        def _get_desc(n: TaskNode):
            for cid in n.children:
                descendants.add(cid)
                if cid in tree:
                    _get_desc(tree[cid])
        _get_desc(node)

        for dep in node.own_depends_on:
            if dep in ancestors:
                errors.append(f"{node.rel_path}: task {node.id} depends on its ancestor {dep} (cycle).")
            if dep in descendants:
                errors.append(f"{node.rel_path}: task {node.id} depends on its descendant {dep} (cycle).")

    expanded_graph: dict[str, set[str]] = {}
    for node in tree.values():
        expanded_deps: set[str] = set()
        for dep in node.depends_on:
            for leaf in expand_dependency_to_leaves(tree, dep):
                expanded_deps.add(leaf)
        expanded_graph[node.id] = expanded_deps

    visited: dict[str, int] = {}
    stack: list[str] = []

    def dfs(u: str) -> None:
        visited[u] = 1
        stack.append(u)
        for v in sorted(expanded_graph.get(u, set())):
            if visited.get(v, 0) == 1:
                cycle_start = stack.index(v)
                cycle_path = " -> ".join(stack[cycle_start:] + [v])
                errors.append(f"Cycle detected in dependencies: {cycle_path}")
            elif visited.get(v, 0) == 0:
                dfs(v)
        stack.pop()
        visited[u] = 2

    for nid in sorted(tree.keys()):
        if visited.get(nid, 0) == 0:
            dfs(nid)

    return errors


def discover_task_tree(tasks_dir: pathlib.Path) -> dict[str, TaskNode]:
    """Discover all tasks/nodes in the tasks hierarchy as a dictionary of id -> TaskNode."""
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    tree: dict[str, TaskNode] = {}
    if not tasks_dir.is_dir():
        return tree

    # 1. Initiatives (active, done, merged)
    initiative_dirs = []
    for entry in sorted(tasks_dir.iterdir()):
        if entry.is_dir() and INITIATIVE_DIR_RE.match(entry.name):
            initiative_dirs.append((entry, False))

    for loc in ("done", "merged"):
        loc_dir = tasks_dir / loc
        if loc_dir.is_dir():
            for entry in sorted(loc_dir.iterdir()):
                if entry.is_dir() and INITIATIVE_DIR_RE.match(entry.name):
                    initiative_dirs.append((entry, True))

    for entry, in_done in initiative_dirs:
        m = INITIATIVE_DIR_RE.match(entry.name)
        if not m:
            continue
        num, slug = m.group(1), m.group(2)
        plan_path = entry / "plan.md"
        if not plan_path.is_file():
            continue

        text = plan_path.read_text(encoding="utf-8")
        h1_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        raw_title = h1_m.group(1).strip() if h1_m else slug
        t_clean = re.sub(rf"^{num}\s+[—–-]\s+", "", raw_title).strip()

        scanned_lines, _ = scan_markdown_blocks(text)
        init_own_fields: dict[str, Any] = {}
        for sline in scanned_lines:
            if sline.is_fenced:
                continue
            if sline.text.startswith("## ") or sline.text.startswith("### "):
                break
            if sline.text.startswith("- ") or sline.text.startswith("* "):
                _, segs = parse_bullet_line(sline.text)
                for seg in segs:
                    if seg.key:
                        init_own_fields[seg.key] = seg.clean_value
                m_plain_short = re.match(r"^[-*]\s+short:\s*(.+?)\s*$", sline.text, flags=re.IGNORECASE)
                if m_plain_short and "short" not in init_own_fields:
                    init_own_fields["short"] = m_plain_short.group(1)

        init_short = init_own_fields.get("short")
        if init_short and str(init_short).strip() and str(init_short).strip() != "-":
            init_short_val = str(init_short).strip()
            init_st = init_short_val
            init_st_src = "field"
        else:
            init_short_val = None
            init_st = derive_short_title(t_clean)
            init_st_src = "derived"

        init_node = TaskNode(
            id=num,
            title=t_clean,
            parent=None,
            depth=0,
            node_type="initiative",
            is_leaf=False,
            is_container=True,
            children=[],
            own_fields=init_own_fields,
            fields={},
            labels=[],
            label_sources={},
            depends_on=[],
            expanded_depends_on=[],
            own_depends_on=[],
            depends_on_free_text="",
            state="open",
            canonical_state="open",
            derived_state="open",
            leaves_done=0,
            leaves_total=0,
            file_path=str(plan_path),
            rel_path=plan_path.relative_to(tasks_dir).as_posix(),
            is_folder=True,
            in_done=in_done,
            in_closed_section=False,
            task_hash=_file_sha256(plan_path),
            priority=init_own_fields.get("priority", "P2"),
            priority_source="own" if "priority" in init_own_fields else "default",
            size="M",
            size_source="default",
            category=slug,
            slug=slug,
            short=init_short_val,
            short_title=init_st,
            short_title_source=init_st_src,
        )
        tree[num] = init_node

        children = parse_child_blocks(
            plan_path,
            parent_id=num,
            parent_depth=0,
            tasks_dir=tasks_dir,
            in_done=in_done,
            in_closed_section=False,
            parent_category=slug,
        )
        for c in children:
            tree[c.id] = c

    # 2. Emergent Tasks
    emergent_raw = discover_emergent_tasks(tasks_dir)
    for et in emergent_raw:
        tid = et["id"]
        if not tid:
            continue
        fpath = pathlib.Path(et["file_path"])
        is_folder = et.get("is_folder", False)
        sub_nodes: list[TaskNode] = []
        if is_folder and fpath.is_file():
            sub_nodes = parse_child_blocks(
                fpath,
                parent_id=tid,
                parent_depth=0,
                tasks_dir=tasks_dir,
                in_done=et.get("in_done", False),
                in_closed_section=False,
                parent_category=et.get("category", ""),
            )

        is_container = len(sub_nodes) > 0
        is_leaf = not is_container
        is_micro = et.get("category") == "micro" or et.get("folder_category") == "micro"

        et_size = et.get("headers", {}).get("size")
        if et_size and et_size.strip().upper() in VALID_SIZES:
            node_size = et_size.strip().upper()
            node_size_source = "own"
        else:
            node_size = "XS" if is_micro else "M"
            node_size_source = "default"

        et_short = et.get("short") or et.get("headers", {}).get("short")
        if et_short and str(et_short).strip() and str(et_short).strip() != "-":
            node_short_val = str(et_short).strip()
            node_st = node_short_val
            node_st_src = "field"
        else:
            node_short_val = None
            node_st = derive_short_title(et["title"])
            node_st_src = "derived"

        node = TaskNode(
            id=tid,
            title=et["title"],
            parent=None,
            depth=0,
            node_type="container" if is_container else ("microtask" if is_micro else "leaf"),
            is_leaf=is_leaf,
            is_container=is_container,
            children=[],
            own_fields=dict(et["headers"]),
            fields={},
            labels=[l.strip() for l in et.get("headers", {}).get("labels", "").split(",") if l.strip() and l.strip() != "-"],
            label_sources={},
            depends_on=list(et.get("depends_on", [])),
            expanded_depends_on=list(et.get("depends_on", [])),
            own_depends_on=list(et.get("depends_on", [])),
            depends_on_free_text="",
            state=et["state"],
            canonical_state=et["canonical_state"],
            derived_state=et["state"] if is_container else None,
            leaves_done=1 if is_leaf and et["canonical_state"] in ("done", "done with a caveat") else 0,
            leaves_total=1 if is_leaf else 0,
            file_path=str(fpath),
            rel_path=et["rel_path"],
            is_folder=is_folder,
            in_done=et.get("in_done", False),
            in_closed_section=False,
            task_hash=et["bundle_sha256"],
            priority=et.get("priority", "P2"),
            priority_source="own" if et.get("headers", {}).get("priority") else "default",
            priority_reason=et.get("priority_reason", ""),
            size=node_size,
            size_source=node_size_source,
            kind=et.get("headers", {}).get("kind"),
            executor=et.get("executor", "kilo"),
            handoff=et.get("handoff", ""),
            category=et.get("category", "") or ("micro" if is_micro else ""),
            slug=slugify(et["title"]),
            short=node_short_val,
            short_title=node_st,
            short_title_source=node_st_src,
            conditions=et.get("conditions", []),
            conditional=et.get("conditional", False),
            own_conditions=et.get("conditions_ids", []),
            waiting_on=et.get("waiting_on"),
            verify_by=et.get("verify_by") or et.get("headers", {}).get("verify-by") or et.get("headers", {}).get("verify_by") or et.get("verifier"),
        )
        tree[tid] = node
        for sn in sub_nodes:
            tree[sn.id] = sn

    # 3. Microtasks
    micro_dirs = [tasks_dir / "micro", tasks_dir / "done" / "micro"]
    for m_dir in micro_dirs:
        if m_dir.is_dir():
            in_done_dir = m_dir.parent.name == "done"
            for mf in sorted(m_dir.glob("*.md")):
                if mf.name == "README.md":
                    continue
                m = re.match(r"^([A-Za-z0-9]+)-(.*)\.md$", mf.name)
                if m:
                    mid = m.group(1)
                    if mid not in tree:
                        et_parsed = parse_emergent_task_file(mf, tasks_dir, in_done=in_done_dir)
                        et_size = et_parsed.get("headers", {}).get("size")
                        if et_size and et_size.strip().upper() in VALID_SIZES:
                            node_size = et_size.strip().upper()
                            node_size_source = "own"
                        else:
                            node_size = "XS"
                            node_size_source = "default"
                        m_short = et_parsed.get("short") or et_parsed.get("headers", {}).get("short")
                        if m_short and str(m_short).strip() and str(m_short).strip() != "-":
                            m_short_val = str(m_short).strip()
                            m_st = m_short_val
                            m_st_src = "field"
                        else:
                            m_short_val = None
                            m_st = derive_short_title(et_parsed["title"])
                            m_st_src = "derived"

                        tree[mid] = TaskNode(
                            id=mid,
                            title=et_parsed["title"],
                            parent=None,
                            depth=0,
                            node_type="microtask",
                            is_leaf=True,
                            is_container=False,
                            children=[],
                            own_fields=dict(et_parsed["headers"]),
                            fields={},
                            labels=[l.strip() for l in et_parsed.get("headers", {}).get("labels", "").split(",") if l.strip() and l.strip() != "-"],
                            label_sources={},
                            depends_on=list(et_parsed.get("depends_on", [])),
                            expanded_depends_on=list(et_parsed.get("depends_on", [])),
                            own_depends_on=list(et_parsed.get("depends_on", [])),
            depends_on_free_text=et.get("depends_on_free_text", ""),
                            state=et_parsed["state"],
                            canonical_state=et_parsed["canonical_state"],
                            derived_state=None,
                            leaves_done=1 if et_parsed["canonical_state"] in ("done", "done with a caveat") else 0,
                            leaves_total=1,
                            file_path=str(mf),
                            rel_path=et_parsed["rel_path"],
                            is_folder=False,
                            in_done=in_done_dir,
                            in_closed_section=False,
                            task_hash=et_parsed["bundle_sha256"],
                            priority=et_parsed.get("priority", "P2"),
                            priority_source="own" if et_parsed.get("headers", {}).get("priority") else "default",
                            priority_reason=et_parsed.get("priority_reason", ""),
                            size=node_size,
                            size_source=node_size_source,
                            kind=et_parsed.get("headers", {}).get("kind"),
                            executor=et_parsed.get("executor", "kilo"),
                            handoff=et_parsed.get("handoff", ""),
                            short=m_short_val,
                            short_title=m_st,
                            short_title_source=m_st_src,
                            conditions=et_parsed.get("conditions", []),
                            conditional=et_parsed.get("conditional", False),
                            own_conditions=et_parsed.get("conditions_ids", []),
                            waiting_on=et_parsed.get("waiting_on"),
                        )

    # 4. Connect children
    for nid, node in tree.items():
        if node.parent and node.parent in tree:
            p_node = tree[node.parent]
            if nid not in p_node.children:
                p_node.children.append(nid)
            p_node.is_leaf = False
            p_node.is_container = True
            if p_node.node_type != "initiative":
                p_node.node_type = "container"

    for node in tree.values():
        node.children.sort(key=_natural_sort_key)

    # 5. Top-down inheritance
    for root_id in [nid for nid, n in tree.items() if n.parent is None]:
        propagate_inheritance(tree, root_id)

    # 6. Bottom-up container evaluation
    for root_id in [nid for nid, n in tree.items() if n.parent is None]:
        evaluate_container_states(tree, root_id)

    # 7. Expand dependencies to leaves
    for node in tree.values():
        exp_deps: set[str] = set()
        for dep in node.depends_on:
            for l in expand_dependency_to_leaves(tree, dep):
                exp_deps.add(l)
        node.expanded_depends_on = sorted(exp_deps)

    return tree


def allocate_child_id(tree: dict[str, TaskNode], parent_id: str, tasks_dir: pathlib.Path) -> str:
    """Allocate the next child ID <parent>.<n> taking the maximum over:
    - open children
    - ## Closed blocks
    - done/ folders
    under the lock.
    """
    suffixes: list[int] = []
    for node in tree.values():
        if node.parent == parent_id:
            m = re.match(rf"^{re.escape(parent_id)}\.(\d+)[a-z]?$", node.id)
            if m:
                suffixes.append(int(m.group(1)))

    parent_node = tree.get(parent_id)
    if parent_node and parent_node.file_path:
        p_path = pathlib.Path(parent_node.file_path)
        if p_path.is_file():
            text = p_path.read_text(encoding="utf-8")
            closed_sec = find_markdown_section(text, "Closed")
            if closed_sec:
                for line in closed_sec.lines:
                    m = re.match(rf"^###\s+{re.escape(parent_id)}\.(\d+)[a-z]?\b", line.text)
                    if m:
                        suffixes.append(int(m.group(1)))

        p_dir = p_path.parent
        done_dir = p_dir / "done"
        if done_dir.is_dir():
            for child in done_dir.iterdir():
                if child.is_dir():
                    m = re.match(rf"^{re.escape(parent_id)}\.(\d+)[a-z]?-", child.name)
                    if m:
                        suffixes.append(int(m.group(1)))

    next_num = max(suffixes) + 1 if suffixes else 1
    return f"{parent_id}.{next_num}"


def compute_operation_plan(operations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Compute S10 operation plan: every path with its before-hash and action.
    Returns (plan, plan_hash) where plan_hash is SHA256 over canonical JSON.
    """
    plan = []
    for op in operations:
        plan.append({
            "action": op.get("action", "modify"),
            "before_hash": op.get("before_hash", ""),
            "path": op["path"],
        })
    plan_sorted = sorted(plan, key=lambda x: (x["path"], x["action"]))
    canonical = json.dumps(plan_sorted, sort_keys=True, separators=(",", ":")).encode("utf-8")
    plan_hash = hashlib.sha256(canonical).hexdigest()
    return plan_sorted, plan_hash


def child_add(
    tasks_dir: pathlib.Path,
    parent_id: str,
    title: str,
    kind: str = "feature",
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
    short: str | None = None,
) -> dict[str, Any]:
    if short and short.strip() and short.strip() != "-":
        issues = validate_short_title(short.strip())
        if issues:
            return {"ok": False, "error": f"Invalid short title {short!r}: {'; '.join(issues)}."}

    short_val = short.strip() if short and short.strip() and short.strip() != "-" else derive_short_title(title.strip())

    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if parent_id not in tree:
            return {"ok": False, "error": f"Parent node '{parent_id}' not found."}
        parent = tree[parent_id]

        operations: list[dict[str, Any]] = []
        new_id = allocate_child_id(tree, parent_id, tasks_dir)

        if parent.is_leaf:
            if parent.canonical_state != "open":
                return {
                    "ok": False,
                    "error": f"Cannot add child to in-flight leaf '{parent_id}' in state '{parent.state}'. Leaf must be in state 'open'.",
                }
            slug = slugify(parent.title)
            parent_file = pathlib.Path(parent.file_path)

            if parent.block_text is not None:
                parent_dir = parent_file.parent
                new_folder = parent_dir / f"{parent_id}-{slug}"
                new_readme = new_folder / "README.md"

                parent_before_hash = _file_sha256(parent_file)
                operations.append({
                    "action": "modify",
                    "path": parent_file.relative_to(tasks_dir).as_posix(),
                    "before_hash": parent_before_hash,
                })
                operations.append({
                    "action": "create",
                    "path": (new_readme.relative_to(tasks_dir) if new_readme.is_relative_to(tasks_dir) else new_readme).as_posix(),
                    "before_hash": "",
                })

                plan, plan_hash = compute_operation_plan(operations)
                if dry_run:
                    return {
                        "ok": True,
                        "dry_run": True,
                        "allocated_id": new_id,
                        "plan": plan,
                        "plan_hash": plan_hash,
                    }
                if not expect_plan_hash:
                    return {
                        "ok": False,
                        "error": "Applying child add requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                        "plan_hash": plan_hash,
                    }
                if expect_plan_hash != plan_hash:
                    return {
                        "ok": False,
                        "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                        "plan_hash": plan_hash,
                    }

                old_text = parent_file.read_text(encoding="utf-8")
                block_lines = parent.block_text.splitlines()
                filtered_lines = []
                for bl in block_lines:
                    if re.match(r"^\s*[-*]\s+\*\*(Status|State):\*\*", bl):
                        continue
                    filtered_lines.append(bl)
                body_content = "\n".join(filtered_lines[1:]).strip()

                rel_folder_link = f"{parent_id}-{slug}/"
                rel_readme_link = f"{parent_id}-{slug}/README.md"
                expanded_block = f"### {parent_id} - {parent.title}\n\n- **Expanded:** [{rel_folder_link}]({rel_readme_link})\n"
                new_parent_text = old_text.replace(parent.block_text, expanded_block, 1)
                _atomic_write_text(parent_file, new_parent_text)

                readme_lines = [
                    f"# {parent_id} - {parent.title}",
                    "",
                ]
                if body_content:
                    readme_lines.append(body_content)
                    readme_lines.append("")
                    readme_lines.extend([
                        "## Subtasks",
                        "",
                        f"### {new_id} - {title}",
                        "",
                        f"- **Status:** `open` · **Short:** {short_val} · **Kind:** {kind}",
                        f"- **Goal:** {title}",
                        "",
                    ])
                new_folder.mkdir(parents=True, exist_ok=True)
                _atomic_write_text(new_readme, "\n".join(readme_lines))

                _emit_event(
                    tasks_dir,
                    "task.created",
                    {
                        "title": title,
                        "parent": parent_id,
                        "state": "open",
                        "from": None,
                        "to": "open",
                        "actor": "owner",
                    },
                    subject=new_id,
                    actor="owner",
                )
                return {
                    "ok": True,
                    "allocated_id": new_id,
                    "plan_hash": plan_hash,
                    "folder": str(new_folder),
                }
            else:
                parent_dir = parent_file.parent
                if not parent.is_folder:
                    # Single-file leaf -> convert to folder
                    new_folder = parent_dir / f"{parent_id}-{slug}"
                    new_readme = new_folder / "README.md"
                    operations.append({
                        "action": "delete",
                        "path": parent_file.relative_to(tasks_dir).as_posix(),
                        "before_hash": _file_sha256(parent_file),
                    })
                    operations.append({
                        "action": "create",
                        "path": new_readme.relative_to(tasks_dir).as_posix(),
                        "before_hash": "",
                    })
                    plan, plan_hash = compute_operation_plan(operations)
                    if dry_run:
                        return {
                            "ok": True,
                            "dry_run": True,
                            "allocated_id": new_id,
                            "plan": plan,
                            "plan_hash": plan_hash,
                        }
                    if not expect_plan_hash:
                        return {
                            "ok": False,
                            "error": "Applying child add requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                            "plan_hash": plan_hash,
                        }
                    if expect_plan_hash != plan_hash:
                        return {
                            "ok": False,
                            "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                            "plan_hash": plan_hash,
                        }

                    old_text = parent_file.read_text(encoding="utf-8")
                    child_block = (
                        f"\n### {new_id} - {title}\n\n"
                        f"- **Status:** `open` · **Short:** {short_val} · **Kind:** {kind}\n"
                        f"- **Goal:** {title}\n"
                    )
                    new_readme_text = old_text.rstrip() + f"\n\n## Subtasks\n{child_block}"
                    new_folder.mkdir(parents=True, exist_ok=True)
                    _atomic_write_text(new_readme, new_readme_text)
                    parent_file.unlink()
                    _emit_event(
                        tasks_dir,
                        "task.created",
                        {
                            "title": title,
                            "parent": parent_id,
                            "state": "open",
                            "from": None,
                            "to": "open",
                            "actor": "owner",
                        },
                        subject=new_id,
                        actor="owner",
                    )
                    return {
                        "ok": True,
                        "allocated_id": new_id,
                        "plan_hash": plan_hash,
                        "folder": str(new_folder),
                    }
                else:
                    # Folder leaf
                    operations.append({
                        "action": "modify",
                        "path": parent_file.relative_to(tasks_dir).as_posix(),
                        "before_hash": _file_sha256(parent_file),
                    })
                    plan, plan_hash = compute_operation_plan(operations)
                    if dry_run:
                        return {
                            "ok": True,
                            "dry_run": True,
                            "allocated_id": new_id,
                            "plan": plan,
                            "plan_hash": plan_hash,
                        }
                    if not expect_plan_hash:
                        return {
                            "ok": False,
                            "error": "Applying child add requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                            "plan_hash": plan_hash,
                        }
                    if expect_plan_hash != plan_hash:
                        return {
                            "ok": False,
                            "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                            "plan_hash": plan_hash,
                        }

                    old_text = parent_file.read_text(encoding="utf-8")
                    child_block = (
                        f"\n### {new_id} - {title}\n\n"
                        f"- **Status:** `open` · **Short:** {short_val} · **Kind:** {kind}\n"
                        f"- **Goal:** {title}\n"
                    )
                    if re.search(r"^##\s+Subtasks\b", old_text, re.MULTILINE):
                        closed_m = re.search(r"^##\s+Closed\b", old_text, re.MULTILINE)
                        if closed_m:
                            new_text = old_text[:closed_m.start()] + child_block.lstrip() + "\n" + old_text[closed_m.start():]
                        else:
                            new_text = old_text.rstrip() + "\n" + child_block
                    else:
                        closed_m = re.search(r"^##\s+Closed\b", old_text, re.MULTILINE)
                        if closed_m:
                            new_text = old_text[:closed_m.start()] + "## Subtasks\n" + child_block + "\n" + old_text[closed_m.start():]
                        else:
                            new_text = old_text.rstrip() + "\n\n## Subtasks\n" + child_block
                    _atomic_write_text(parent_file, new_text)
                    _emit_event(
                        tasks_dir,
                        "task.created",
                        {
                            "title": title,
                            "parent": parent_id,
                            "state": "open",
                            "from": None,
                            "to": "open",
                            "actor": "owner",
                        },
                        subject=new_id,
                        actor="owner",
                    )
                    return {
                        "ok": True,
                        "allocated_id": new_id,
                        "plan_hash": plan_hash,
                    }

        else:
            parent_file = pathlib.Path(parent.file_path)
            parent_before_hash = _file_sha256(parent_file)
            operations.append({
                "action": "modify",
                "path": parent_file.relative_to(tasks_dir).as_posix(),
                "before_hash": parent_before_hash,
            })
            plan, plan_hash = compute_operation_plan(operations)
            if dry_run:
                return {
                    "ok": True,
                    "dry_run": True,
                    "allocated_id": new_id,
                    "plan": plan,
                    "plan_hash": plan_hash,
                }
            if not expect_plan_hash:
                return {
                    "ok": False,
                    "error": "Applying child add requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                    "plan_hash": plan_hash,
                }
            if expect_plan_hash != plan_hash:
                return {
                    "ok": False,
                    "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                    "plan_hash": plan_hash,
                }

            child_block = (
                f"\n### {new_id} - {title}\n\n"
                f"- **Status:** `open` · **Kind:** {kind}\n"
                f"- **Goal:** {title}\n"
            )
            old_text = parent_file.read_text(encoding="utf-8")
            if parent_file.name == "README.md" and not re.search(r"^##\s+Subtasks\b", old_text, re.MULTILINE):
                closed_m = re.search(r"^##\s+Closed\b", old_text, re.MULTILINE)
                if closed_m:
                    new_text = old_text[:closed_m.start()] + "## Subtasks\n" + child_block + "\n" + old_text[closed_m.start():]
                else:
                    new_text = old_text.rstrip() + "\n\n## Subtasks\n" + child_block
            else:
                closed_m = re.search(r"^##\s+Closed\b", old_text, re.MULTILINE)
                if closed_m:
                    new_text = old_text[:closed_m.start()] + child_block.lstrip() + "\n" + old_text[closed_m.start():]
                else:
                    new_text = old_text.rstrip() + "\n" + child_block

            _atomic_write_text(parent_file, new_text)
            _emit_event(
                tasks_dir,
                "task.created",
                {
                    "title": title,
                    "parent": parent_id,
                    "state": "open",
                    "from": None,
                    "to": "open",
                    "actor": "owner",
                },
                subject=new_id,
                actor="owner",
            )
            return {
                "ok": True,
                "allocated_id": new_id,
                "plan_hash": plan_hash,
            }


def expand_node(
    tasks_dir: pathlib.Path,
    node_id: str,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Node '{node_id}' not found."}
        node = tree[node_id]
        if node.is_folder:
            return {"ok": False, "error": f"Node '{node_id}' is already a folder."}
        if node.block_text is None:
            return {"ok": False, "error": f"Node '{node_id}' is not an inline block."}

        parent_file = pathlib.Path(node.file_path)
        slug = slugify(node.title)
        folder = parent_file.parent / f"{node_id}-{slug}"
        readme = folder / "README.md"

        operations = [
            {
                "action": "modify",
                "path": parent_file.relative_to(tasks_dir).as_posix(),
                "before_hash": _file_sha256(parent_file),
            },
            {
                "action": "create",
                "path": (readme.relative_to(tasks_dir) if readme.is_relative_to(tasks_dir) else readme).as_posix(),
                "before_hash": "",
            },
        ]
        plan, plan_hash = compute_operation_plan(operations)
        if dry_run:
            return {"ok": True, "dry_run": True, "plan": plan, "plan_hash": plan_hash}
        if not expect_plan_hash:
            return {
                "ok": False,
                "error": "Applying expand requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                "plan_hash": plan_hash,
            }
        if expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                "plan_hash": plan_hash,
            }

        rel_folder = f"{node_id}-{slug}/"
        rel_readme = f"{node_id}-{slug}/README.md"
        expanded_block = f"### {node_id} - {node.title}\n\n- **Expanded:** [{rel_folder}]({rel_readme})\n"

        old_parent_text = parent_file.read_text(encoding="utf-8")
        new_parent_text = old_parent_text.replace(node.block_text, expanded_block, 1)

        block_lines = node.block_text.splitlines()
        bullet_lines = block_lines[1:]
        body_text = "\n".join(bullet_lines).strip()

        readme_text = f"# {node_id} - {node.title}\n\n{body_text}\n\n## Subtasks\n"

        folder.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(readme, readme_text)
        _atomic_write_text(parent_file, new_parent_text)

        _emit_event(
            tasks_dir,
            "task.expanded",
            {
                "folder": str(folder),
                "node_id": node_id,
            },
            subject=node_id,
        )

        return {"ok": True, "plan_hash": plan_hash, "folder": str(folder)}


def collapse_node(
    tasks_dir: pathlib.Path,
    node_id: str,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Node '{node_id}' not found."}
        node = tree[node_id]
        if not node.is_folder:
            return {"ok": False, "error": f"Node '{node_id}' is not an expanded folder."}

        for cid in node.children:
            if cid in tree and tree[cid].is_folder:
                return {
                    "ok": False,
                    "error": f"Cannot collapse '{node_id}': child '{cid}' is an expanded folder.",
                }

        folder = pathlib.Path(node.file_path).parent
        readme = folder / "README.md"

        if not node.parent or node.parent not in tree:
            return {"ok": False, "error": f"Cannot collapse root node '{node_id}'."}
        parent_node = tree[node.parent]
        parent_file = pathlib.Path(parent_node.file_path)

        operations = [
            {
                "action": "modify",
                "path": parent_file.relative_to(tasks_dir).as_posix(),
                "before_hash": _file_sha256(parent_file),
            },
            {
                "action": "delete",
                "path": readme.relative_to(tasks_dir).as_posix(),
                "before_hash": _file_sha256(readme),
            },
        ]
        plan, plan_hash = compute_operation_plan(operations)
        if dry_run:
            return {"ok": True, "dry_run": True, "plan": plan, "plan_hash": plan_hash}
        if not expect_plan_hash:
            return {
                "ok": False,
                "error": "Applying collapse requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                "plan_hash": plan_hash,
            }
        if expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                "plan_hash": plan_hash,
            }

        readme_text = readme.read_text(encoding="utf-8")
        lines = readme_text.splitlines()
        h1_idx = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
        subtasks_idx = next((i for i, ln in enumerate(lines) if ln.startswith("## Subtasks")), len(lines))

        node_bullets = "\n".join(lines[h1_idx + 1:subtasks_idx]).strip()

        restored_block = f"### {node_id} - {node.title}\n\n{node_bullets}\n"

        old_parent_text = parent_file.read_text(encoding="utf-8")
        exp_pat = re.compile(
            rf"^###\s+{re.escape(node_id)}\s+[—–-]\s+.*?\n\n-\s+\*\*Expanded:\*\*\s*\[[^\]]+\]\([^)]+\)\n?",
            re.MULTILINE | re.DOTALL,
        )
        m = exp_pat.search(old_parent_text)
        if not m:
            return {"ok": False, "error": f"Could not find expanded block for '{node_id}' in {parent_file}"}

        new_parent_text = old_parent_text[:m.start()] + restored_block + old_parent_text[m.end():]

        shutil.rmtree(folder)
        _atomic_write_text(parent_file, new_parent_text)

        _emit_event(
            tasks_dir,
            "task.collapsed",
            {
                "node_id": node_id,
            },
            subject=node_id,
        )

        return {"ok": True, "plan_hash": plan_hash}


def reopen_node(
    tasks_dir: pathlib.Path,
    node_id: str,
    reason: str,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]
        if not node.is_leaf:
            return {"ok": False, "error": f"Cannot reopen container '{node_id}': only leaf tasks can be reopened."}
        if node.canonical_state not in TERMINAL_STATES:
            return {
                "ok": False,
                "error": f"Task '{node_id}' is in state '{node.state}' (not a terminal state).",
            }

        file_path = pathlib.Path(node.file_path)

        # Check if inside a shipped initiative
        shipped_init: TaskNode | None = None
        curr_p = node.parent
        while curr_p and curr_p in tree:
            if tree[curr_p].node_type == "initiative" and tree[curr_p].in_done:
                shipped_init = tree[curr_p]
                break
            curr_p = tree[curr_p].parent

        # Check if inside a closed folder child
        closed_folder: TaskNode | None = None
        curr_p = node.parent
        while curr_p and curr_p in tree:
            if tree[curr_p].is_folder and tree[curr_p].node_type != "initiative" and tree[curr_p].in_done:
                closed_folder = tree[curr_p]
                break
            curr_p = tree[curr_p].parent

        operations: list[dict[str, Any]] = []

        if shipped_init:
            init_dir = pathlib.Path(shipped_init.file_path).parent
            init_name = init_dir.name
            for f in init_dir.rglob("*"):
                if f.is_file():
                    operations.append({
                        "action": "modify",
                        "path": f.relative_to(tasks_dir).as_posix(),
                        "before_hash": _file_sha256(f),
                    })
            index_path = tasks_dir / "00-INDEX.md"
            if index_path.is_file() and not any(op["path"] == "00-INDEX.md" for op in operations):
                operations.append({
                    "action": "modify",
                    "path": "00-INDEX.md",
                    "before_hash": _file_sha256(index_path),
                })
            for md in tasks_dir.rglob("*.md"):
                if md.is_relative_to(init_dir) or md == index_path:
                    continue
                if f"done/{init_name}" in md.read_text(encoding="utf-8"):
                    rel = md.relative_to(tasks_dir).as_posix()
                    if not any(op["path"] == rel for op in operations):
                        operations.append({
                            "action": "modify",
                            "path": rel,
                            "before_hash": _file_sha256(md),
                        })

        if closed_folder:
            fld_dir = pathlib.Path(closed_folder.file_path).parent
            for f in fld_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(tasks_dir).as_posix()
                    if not any(op["path"] == rel for op in operations):
                        operations.append({
                            "action": "modify",
                            "path": rel,
                            "before_hash": _file_sha256(f),
                        })
            if closed_folder.parent and closed_folder.parent in tree:
                parent_f = pathlib.Path(tree[closed_folder.parent].file_path)
                rel_pf = parent_f.relative_to(tasks_dir).as_posix()
                if not any(op["path"] == rel_pf for op in operations):
                    operations.append({
                        "action": "modify",
                        "path": rel_pf,
                        "before_hash": _file_sha256(parent_f),
                    })

        rel_fp = file_path.relative_to(tasks_dir).as_posix()
        if not any(op["path"] == rel_fp for op in operations):
            operations.append({
                "action": "modify",
                "path": rel_fp,
                "before_hash": _file_sha256(file_path),
            })

        ancestors_to_restore: list[tuple[TaskNode, str]] = []
        old_st = node.state
        old_cst = node.canonical_state
        node.state = "open"
        node.canonical_state = "open"

        curr = node.parent
        while curr and curr in tree:
            anc = tree[curr]
            child_nodes = [tree[cid] for cid in anc.children if cid in tree]
            child_states = [c.state for c in child_nodes]
            new_derived = derive_container_state(child_states)
            anc.derived_state = new_derived
            anc.state = new_derived
            anc.canonical_state = normalize_state(new_derived)
            if anc.file_path and pathlib.Path(anc.file_path).is_file():
                anc_file = pathlib.Path(anc.file_path)
                anc_text = anc_file.read_text(encoding="utf-8")
                m_state = re.search(r"^-\s+state:\s*(.*)$", anc_text, re.MULTILINE)
                if m_state:
                    anc_old_state = m_state.group(1).strip()
                    if normalize_state(anc_old_state) in TERMINAL_STATES and anc_old_state != new_derived:
                        ancestors_to_restore.append((anc, new_derived))
                        anc_rel = anc_file.relative_to(tasks_dir).as_posix()
                        if anc_file != file_path and not any(op["path"] == anc_rel for op in operations):
                            operations.append({
                                "action": "modify",
                                "path": anc_rel,
                                "before_hash": _file_sha256(anc_file),
                            })
            curr = anc.parent

        node.state = old_st
        node.canonical_state = old_cst

        plan, plan_hash = compute_operation_plan(operations)
        if dry_run:
            return {"ok": True, "dry_run": True, "plan": plan, "plan_hash": plan_hash}
        if not expect_plan_hash:
            return {
                "ok": False,
                "error": "Applying reopen requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                "plan_hash": plan_hash,
            }
        if expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                "plan_hash": plan_hash,
            }

        today = datetime.date.today().isoformat()
        reason_clean = reason.strip() if reason else "reopened"
        status_note = f"{today}; {reason_clean}"

        # 1. Restore shipped initiative if applicable
        if shipped_init:
            init_dir = pathlib.Path(shipped_init.file_path).parent
            init_name = init_dir.name
            restored_dir = tasks_dir / init_name
            res = subprocess.run(
                ["git", "mv", str(init_dir), str(restored_dir)],
                cwd=str(tasks_dir),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                shutil.move(str(init_dir), str(restored_dir))

            summary_f = restored_dir / "summary.md"
            if summary_f.is_file():
                s_text = summary_f.read_text(encoding="utf-8")
                s_text = s_text.rstrip() + f"\n- **Reopened:** {today} ({reason_clean})\n"
                _atomic_write_text(summary_f, s_text, encoding="utf-8")

            for md in restored_dir.rglob("*.md"):
                if md == summary_f:
                    continue
                old_t = md.read_text(encoding="utf-8")
                new_t = adjust_markdown_link_depth(old_t, depth_delta=-1)
                if new_t != old_t:
                    _atomic_write_text(md, new_t, encoding="utf-8")

            index_p = tasks_dir / "00-INDEX.md"
            if index_p.is_file():
                idx_t = index_p.read_text(encoding="utf-8")
                new_idx_t = rewrite_links_in_text(idx_t, f"done/{init_name}", init_name)
                if new_idx_t != idx_t:
                    _atomic_write_text(index_p, new_idx_t, encoding="utf-8")

            for md in tasks_dir.rglob("*.md"):
                if md.is_relative_to(restored_dir) or md == index_p:
                    continue
                m_t = md.read_text(encoding="utf-8")
                new_m_t = rewrite_links_in_text(m_t, f"done/{init_name}", init_name)
                if new_m_t != m_t:
                    _atomic_write_text(md, new_m_t, encoding="utf-8")

            rel_in_init = file_path.relative_to(init_dir)
            file_path = restored_dir / rel_in_init

        # 2. Restore closed folder child if applicable
        if closed_folder:
            parent_node = tree[closed_folder.parent]
            p_dir = pathlib.Path(parent_node.file_path).parent
            if shipped_init:
                p_dir = tasks_dir / init_name
            new_readme = move_folder_child_to_open(p_dir, closed_folder.id, tasks_dir)
            fld_orig_parent = pathlib.Path(closed_folder.file_path).parent
            if str(file_path).startswith(str(fld_orig_parent)):
                file_path = new_readme.parent / file_path.name

        # 3. Reopen the leaf block or task
        if node.block_text is not None:
            if node.in_closed_section:
                move_block_to_open(file_path, node_id, new_status="open", status_note=status_note)
            else:
                rewrite_block_in_file(file_path, node_id, new_status="open", status_note=status_note)
        else:
            if node.in_done:
                emergent = discover_emergent_tasks(tasks_dir)
                target = next((t for t in emergent if t["id"] == node_id), None)
                cat = (target.get("category") or "features") if target else "features"
                target_dir = tasks_dir / cat
                target_dir.mkdir(parents=True, exist_ok=True)
                dest_file = target_dir / file_path.name
                shutil.move(str(file_path), str(dest_file))
                file_path = dest_file
                _update_task_file_headers_and_state(file_path, "open")
                if target:
                    target["in_done"] = False
                    target["rel_path"] = dest_file.relative_to(tasks_dir).as_posix()
                    _update_index_task_path(tasks_dir, target, old_rel=node.rel_path)
            else:
                _update_task_file_headers_and_state(file_path, "open")
            t_dict = node.to_dict() if hasattr(node, "to_dict") else vars(node)
            _append_progress_log(t_dict, old_st, "open", actor="owner", verifier=None, reason=reason_clean)

        for anc, new_anc_state in ancestors_to_restore:
            anc_file = pathlib.Path(anc.file_path)
            if shipped_init:
                if anc_file.is_relative_to(tasks_dir / "done"):
                    rel_done = anc_file.relative_to(tasks_dir / "done")
                    anc_file = tasks_dir / rel_done
            _update_task_file_headers_and_state(anc_file, new_anc_state)
            anc_dict = anc.to_dict() if hasattr(anc, "to_dict") else vars(anc)
            _append_progress_log(
                anc_dict,
                anc.state,
                new_anc_state,
                actor="owner",
                verifier=None,
                reason=f"Restored ancestor because child {node_id} reopened: {reason_clean}",
            )

        _emit_event(
            tasks_dir,
            "task.transitioned",
            {
                "from": old_st,
                "to": "open",
                "actor": "owner",
                "reason": reason_clean,
            },
            subject=node_id,
            actor="owner",
        )
        for anc, new_anc_state in ancestors_to_restore:
            _emit_event(
                tasks_dir,
                "task.transitioned",
                {
                    "from": anc.state,
                    "to": new_anc_state,
                    "actor": "owner",
                    "reason": f"Restored ancestor because child {node_id} reopened: {reason_clean}",
                },
                subject=anc.id,
                actor="owner",
            )

        return {"ok": True, "task_id": node_id, "new_state": "open", "plan_hash": plan_hash}


def ship_initiative(
    tasks_dir: pathlib.Path,
    init_id: str,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Ship a completed initiative to tasks/done/NN-slug/ with summary.md skeleton and link rewriting."""
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if init_id not in tree:
            return {"ok": False, "error": f"Initiative '{init_id}' not found."}
        node = tree[init_id]
        if node.node_type != "initiative":
            return {"ok": False, "error": f"Node '{init_id}' is not an initiative."}
        if node.in_done:
            return {"ok": False, "error": f"Initiative '{init_id}' is already shipped (in done/)."}

        st = node.derived_state or node.state
        if normalize_state(st) not in TERMINAL_STATES:
            return {
                "ok": False,
                "error": f"Cannot ship initiative '{init_id}': derived state is '{st}' (not closed).",
            }

        plan_path = pathlib.Path(node.file_path)
        init_dir = plan_path.parent
        init_name = init_dir.name
        done_dir = tasks_dir / "done"
        target_dir = done_dir / init_name
        summary_path = target_dir / "summary.md"

        operations: list[dict[str, Any]] = []

        for f in init_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(tasks_dir).as_posix()
                operations.append({
                    "action": "modify",
                    "path": rel,
                    "before_hash": _file_sha256(f),
                })

        if not (init_dir / "summary.md").is_file():
            operations.append({
                "action": "create",
                "path": summary_path.relative_to(tasks_dir).as_posix(),
                "before_hash": "",
            })

        index_path = tasks_dir / "00-INDEX.md"
        if index_path.is_file():
            operations.append({
                "action": "modify",
                "path": "00-INDEX.md",
                "before_hash": _file_sha256(index_path),
            })

        other_files_to_rewrite: list[pathlib.Path] = []
        for md in tasks_dir.rglob("*.md"):
            if md == index_path or md.is_relative_to(init_dir):
                continue
            text = md.read_text(encoding="utf-8")
            if init_name in text:
                other_files_to_rewrite.append(md)
                rel = md.relative_to(tasks_dir).as_posix()
                if not any(op["path"] == rel for op in operations):
                    operations.append({
                        "action": "modify",
                        "path": rel,
                        "before_hash": _file_sha256(md),
                    })

        plan, plan_hash = compute_operation_plan(operations)
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "plan": plan,
                "plan_hash": plan_hash,
                "initiative_id": init_id,
                "folder": f"done/{init_name}",
            }
        if not expect_plan_hash:
            return {
                "ok": False,
                "error": "Applying ship requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                "plan_hash": plan_hash,
            }
        if expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                "plan_hash": plan_hash,
            }

        today = datetime.date.today().isoformat()
        summary_text = (
            f"# Summary: {init_id} - {node.title}\n\n"
            f"- **Shipped:** {today}\n"
            f"- **Plan:** [`plan.md`](plan.md)\n\n"
            f"## Outcome\n<outcome description: what landed, net effect>\n\n"
            f"## Deviations\n<deviations from original plan, if any>\n\n"
            f"## Follow-ups\n<follow-up tasks, unresolved questions or notes>\n"
        )
        init_summary = init_dir / "summary.md"
        # An existing summary is the author's: keep it (its links are rebased below)
        if not init_summary.is_file():
            _atomic_write_text(init_summary, summary_text, encoding="utf-8")

        for f in init_dir.rglob("*.md"):
            old_t = f.read_text(encoding="utf-8")
            new_t = adjust_markdown_link_depth(old_t, depth_delta=1)
            if new_t != old_t:
                _atomic_write_text(f, new_t, encoding="utf-8")

        done_dir.mkdir(parents=True, exist_ok=True)
        res = subprocess.run(
            ["git", "mv", str(init_dir), str(target_dir)],
            cwd=str(tasks_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            shutil.move(str(init_dir), str(target_dir))

        if index_path.is_file():
            idx_text = index_path.read_text(encoding="utf-8")
            new_idx_text = rewrite_links_in_text(
                idx_text,
                old_rel=init_name,
                new_rel=f"done/{init_name}",
            )
            if new_idx_text != idx_text:
                _atomic_write_text(index_path, new_idx_text, encoding="utf-8")

        for md in other_files_to_rewrite:
            md_text = md.read_text(encoding="utf-8")
            new_md_text = rewrite_links_in_text(
                md_text,
                old_rel=init_name,
                new_rel=f"done/{init_name}",
            )
            if new_md_text != md_text:
                _atomic_write_text(md, new_md_text, encoding="utf-8")

        _emit_event(
            tasks_dir,
            "task.shipped",
            {
                "initiative_id": init_id,
                "folder": f"done/{init_name}",
            },
            subject=init_id,
            actor="owner",
        )

        return {
            "ok": True,
            "plan_hash": plan_hash,
            "initiative_id": init_id,
            "folder": f"done/{init_name}",
        }


def archive_misplaced(
    tasks_dir: pathlib.Path,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Fix misplaced closed items at every level with dry-run plan."""
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        emergent = discover_emergent_tasks(tasks_dir)

        misplaced_emergent = [
            t for t in emergent
            if not t["in_done"] and t["canonical_state"] in TERMINAL_STATES and t["canonical_state"] != "moved" and not t.get("moved_to")
        ]

        misplaced_blocks: list[TaskNode] = []
        for n in tree.values():
            if n.is_leaf and n.block_text is not None and not n.in_done and not n.in_closed_section:
                if n.canonical_state in TERMINAL_STATES:
                    misplaced_blocks.append(n)

        misplaced_folders: list[TaskNode] = []
        for n in tree.values():
            if n.is_folder and n.parent is not None and not n.in_done:
                if n.canonical_state in TERMINAL_STATES:
                    misplaced_folders.append(n)

        total_misplaced = len(misplaced_emergent) + len(misplaced_blocks) + len(misplaced_folders)
        if total_misplaced == 0:
            plan, plan_hash = compute_operation_plan([])
            return {
                "ok": True,
                "dry_run": dry_run,
                "plan": [],
                "plan_hash": plan_hash,
                "message": "Nothing to archive.",
                "archived_count": 0,
            }

        operations: list[dict[str, Any]] = []
        for t in misplaced_emergent:
            fpath = pathlib.Path(t["file_path"])
            operations.append({
                "action": "modify",
                "path": fpath.relative_to(tasks_dir).as_posix(),
                "before_hash": _file_sha256(fpath),
            })

        files_with_blocks: set[pathlib.Path] = set()
        for b in misplaced_blocks:
            files_with_blocks.add(pathlib.Path(b.file_path))
        for f in files_with_blocks:
            operations.append({
                "action": "modify",
                "path": f.relative_to(tasks_dir).as_posix(),
                "before_hash": _file_sha256(f),
            })

        for fld in misplaced_folders:
            fpath = pathlib.Path(fld.file_path)
            operations.append({
                "action": "modify",
                "path": fpath.relative_to(tasks_dir).as_posix(),
                "before_hash": _file_sha256(fpath),
            })
            if fld.parent and fld.parent in tree:
                parent_f = pathlib.Path(tree[fld.parent].file_path)
                rel_pf = parent_f.relative_to(tasks_dir).as_posix()
                if not any(op["path"] == rel_pf for op in operations):
                    operations.append({
                        "action": "modify",
                        "path": rel_pf,
                        "before_hash": _file_sha256(parent_f),
                    })

        plan, plan_hash = compute_operation_plan(operations)
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "plan": plan,
                "plan_hash": plan_hash,
                "archived_count": total_misplaced,
                "misplaced_blocks": [b.id for b in misplaced_blocks],
                "misplaced_folders": [f.id for f in misplaced_folders],
                "misplaced_emergent": [e["id"] for e in misplaced_emergent],
            }
        if not expect_plan_hash:
            return {
                "ok": False,
                "error": "Applying archive requires --expect-plan-hash <hash>. Run with --dry-run to obtain the plan hash.",
                "plan_hash": plan_hash,
            }
        if expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed {plan_hash}",
                "plan_hash": plan_hash,
            }

        for b in misplaced_blocks:
            move_block_to_closed(pathlib.Path(b.file_path), b.id)
            _emit_event(
                tasks_dir,
                "task.archived",
                {"task_id": b.id, "type": "block", "file": b.rel_path},
                subject=b.id,
                actor="owner",
            )

        for fld in misplaced_folders:
            if fld.parent and fld.parent in tree:
                parent_dir = pathlib.Path(tree[fld.parent].file_path).parent
                move_folder_child_to_done(parent_dir, fld.id, tasks_dir)
                _emit_event(
                    tasks_dir,
                    "task.archived",
                    {"task_id": fld.id, "type": "folder", "id": fld.id},
                    subject=fld.id,
                    actor="owner",
                )

        for e in misplaced_emergent:
            dest = _move_task_to_done(e, tasks_dir)
            _emit_event(
                tasks_dir,
                "task.archived",
                {"task_id": e["id"], "type": "emergent", "to": dest.relative_to(tasks_dir).as_posix()},
                subject=e["id"],
                actor="owner",
            )

        return {
            "ok": True,
            "plan_hash": plan_hash,
            "archived_count": total_misplaced,
        }


def set_priority(
    tasks_dir: pathlib.Path,
    node_id: str,
    priority: str,
    reason: str | None = None,
    dry_run: bool = False,
    expect_task_hash: str | None = None,
) -> dict[str, Any]:
    priority = priority.strip().upper()
    if priority not in PRIORITIES:
        return {"ok": False, "error": f"Invalid priority '{priority}' (expected one of {', '.join(sorted(PRIORITIES))})."}

    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]

        if expect_task_hash and expect_task_hash.strip().lower() != node.task_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {node.task_hash}",
            }

        file_path = pathlib.Path(node.file_path)
        if node.block_text is not None:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                file_path,
                node_id,
                new_priority=priority,
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "priority",
                        "value": priority,
                        "priority": priority,
                        "reason": reason,
                    },
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "priority": priority,
                "task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = file_path.read_text(encoding="utf-8")
            new_text = re.sub(r"^-\s+priority:\s*.*$", f"- priority: {priority}", old_text, flags=re.MULTILINE)
            if reason is not None:
                new_text = re.sub(r"^-\s+priority-reason:\s*.*$", f"- priority-reason: {reason}", new_text, flags=re.MULTILINE)
            diff_lines = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(file_path),
                tofile=str(file_path) if not dry_run else f"{file_path} (dry-run)",
            ))
            diff_str = "".join(diff_lines)
            if not dry_run:
                _atomic_write_text(file_path, new_text, encoding="utf-8")
                new_hash = _file_sha256(file_path)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "priority",
                        "value": priority,
                        "priority": priority,
                        "reason": reason,
                    },
                    subject=node_id,
                )
            else:
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            return {
                "ok": True,
                "task_id": node_id,
                "priority": priority,
                "task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


def set_size(
    tasks_dir: pathlib.Path,
    node_id: str,
    size: str,
    dry_run: bool = False,
    expect_task_hash: str | None = None,
) -> dict[str, Any]:
    size = size.strip().upper()
    if size not in VALID_SIZES:
        return {"ok": False, "error": f"Invalid size '{size}' (expected one of {', '.join(sorted(VALID_SIZES))})."}

    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]

        if expect_task_hash and expect_task_hash.strip().lower() != node.task_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {node.task_hash}",
            }

        file_path = pathlib.Path(node.file_path)
        if node.block_text is not None:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                file_path,
                node_id,
                new_size=size,
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "size",
                        "value": size,
                        "size": size,
                    },
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "size": size,
                "task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = file_path.read_text(encoding="utf-8")
            if re.search(r"^-\s+size:\s*.*$", old_text, flags=re.MULTILINE):
                new_text = re.sub(r"^-\s+size:\s*.*$", f"- size: {size}", old_text, flags=re.MULTILINE)
            else:
                for anchor in (r"^-\s+verifier:\s*.*$", r"^-\s+verification-mode:\s*.*$", r"^-\s+profile:\s*.*$", r"^-\s+handoff:\s*.*$"):
                    m = re.search(anchor, old_text, flags=re.MULTILINE)
                    if m:
                        ins_pos = m.end()
                        new_text = old_text[:ins_pos] + f"\n- size: {size}" + old_text[ins_pos:]
                        break
                else:
                    new_text = old_text.replace("\n\n", f"\n- size: {size}\n\n", 1)
            diff_lines = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(file_path),
                tofile=str(file_path) if not dry_run else f"{file_path} (dry-run)",
            ))
            diff_str = "".join(diff_lines)
            if not dry_run:
                _atomic_write_text(file_path, new_text, encoding="utf-8")
                new_hash = _file_sha256(file_path)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "size",
                        "value": size,
                        "size": size,
                    },
                    subject=node_id,
                )
            else:
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            return {
                "ok": True,
                "task_id": node_id,
                "size": size,
                "task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


def set_deps(
    tasks_dir: pathlib.Path,
    node_id: str,
    add_ids: list[str] | str | None = None,
    remove_ids: list[str] | str | None = None,
    to_ids: list[str] | str | None = None,
    expect_task_hash: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]

        if expect_task_hash and expect_task_hash.strip().lower() != node.task_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {node.task_hash}",
            }

        add_norm = _normalize_id_list(add_ids)
        remove_norm = _normalize_id_list(remove_ids)
        to_norm = _normalize_id_list(to_ids) if to_ids is not None else None

        curr_deps = list(node.own_depends_on)
        if to_norm is not None:
            new_deps = list(to_norm)
        else:
            new_deps = list(curr_deps)
            if add_norm:
                for a in add_norm:
                    if a not in new_deps:
                        new_deps.append(a)
            if remove_norm:
                new_deps = [d for d in new_deps if d not in remove_norm]

        # Unknown ID check
        for d in new_deps:
            if is_external_task_ref(d):
                continue
            if d not in tree:
                return {"ok": False, "error": f"Unknown task id '{d}' in dependencies."}

        # Cycle check
        old_own = node.own_depends_on
        old_dep = node.depends_on
        node.own_depends_on = new_deps
        parent_deps = tree[node.parent].depends_on if node.parent and node.parent in tree else []
        node.depends_on = new_deps + parent_deps
        cycle_errors = check_dependency_cycles(tree)
        node.own_depends_on = old_own
        node.depends_on = old_dep
        if cycle_errors:
            return {"ok": False, "error": cycle_errors[0]}

        file_path = pathlib.Path(node.file_path)
        if node.block_text is not None:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                file_path,
                node_id,
                new_deps=new_deps,
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "depends_on",
                        "value": ", ".join(new_deps) if new_deps else "-",
                        "depends_on": new_deps,
                    },
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "depends_on": new_deps,
                "task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = file_path.read_text(encoding="utf-8")
            m = re.search(r"^-\s+depends-on:\s*(.*)$", old_text, flags=re.MULTILINE)
            if not m:
                return {"ok": False, "error": f"Header line '- depends-on:' not found in {file_path}"}
            raw_val = m.group(1)
            new_raw = update_depends_on_field(raw_val, new_deps)
            new_text = old_text[:m.start()] + f"- depends-on: {new_raw}" + old_text[m.end():]
            diff_lines = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(file_path),
                tofile=str(file_path) if not dry_run else f"{file_path} (dry-run)",
            ))
            diff_str = "".join(diff_lines)
            if not dry_run:
                _atomic_write_text(file_path, new_text, encoding="utf-8")
                new_hash = task_bundle_sha256(file_path)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "depends_on",
                        "value": new_raw,
                        "depends_on": new_deps,
                    },
                    subject=node_id,
                )
            else:
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            return {
                "ok": True,
                "task_id": node_id,
                "depends_on": new_deps,
                "task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


def set_kind(
    tasks_dir: pathlib.Path,
    node_id: str,
    kind: str,
    dry_run: bool = False,
    expect_task_hash: str | None = None,
) -> dict[str, Any]:
    kind = kind.strip().lower()
    if kind not in VALID_KINDS:
        return {"ok": False, "error": f"Invalid kind '{kind}' (expected one of {', '.join(sorted(VALID_KINDS))})."}

    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]

        if expect_task_hash and expect_task_hash.strip().lower() != node.task_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {node.task_hash}",
            }

        file_path = pathlib.Path(node.file_path)
        if node.block_text is not None:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                file_path,
                node_id,
                new_kind=kind,
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "kind",
                        "value": kind,
                        "kind": kind,
                    },
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "kind": kind,
                "task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = file_path.read_text(encoding="utf-8")
            if re.search(r"^-\s+kind:\s*.*$", old_text, flags=re.MULTILINE):
                new_text = re.sub(r"^-\s+kind:\s*.*$", f"- kind: {kind}", old_text, flags=re.MULTILINE)
            else:
                if node.node_type == "microtask" or node.category == "micro":
                    m = re.search(r"^-\s+title:\s*.*$", old_text, flags=re.MULTILINE)
                    if m:
                        ins = m.end()
                        new_text = old_text[:ins] + f"\n- kind: {kind}" + old_text[ins:]
                    else:
                        new_text = old_text.replace("\n\n", f"\n- kind: {kind}\n\n", 1)
                else:
                    for anchor in (
                        r"^-\s+size:\s*.*$",
                        r"^-\s+verifier:\s*.*$",
                        r"^-\s+verification-mode:\s*.*$",
                        r"^-\s+profile:\s*.*$",
                        r"^-\s+handoff:\s*.*$",
                    ):
                        m = re.search(anchor, old_text, flags=re.MULTILINE)
                        if m:
                            ins = m.end()
                            new_text = old_text[:ins] + f"\n- kind: {kind}" + old_text[ins:]
                            break
                    else:
                        new_text = old_text.replace("\n\n", f"\n- kind: {kind}\n\n", 1)
            diff_lines = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(file_path),
                tofile=str(file_path) if not dry_run else f"{file_path} (dry-run)",
            ))
            diff_str = "".join(diff_lines)
            if not dry_run:
                _atomic_write_text(file_path, new_text, encoding="utf-8")
                new_hash = _file_sha256(file_path)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "kind",
                        "value": kind,
                        "kind": kind,
                    },
                    subject=node_id,
                )
            else:
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            return {
                "ok": True,
                "task_id": node_id,
                "kind": kind,
                "task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


def set_executor(
    tasks_dir: pathlib.Path,
    node_id: str,
    executor: str,
    dry_run: bool = False,
    expect_task_hash: str | None = None,
) -> dict[str, Any]:
    executor = executor.strip()
    if not executor or executor == "-":
        return {"ok": False, "error": "Executor cannot be empty or '-'."}

    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]

        if expect_task_hash and expect_task_hash.strip().lower() != node.task_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {node.task_hash}",
            }

        file_path = pathlib.Path(node.file_path)
        if node.block_text is not None:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                file_path,
                node_id,
                new_executor=executor,
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "executor",
                        "value": executor,
                        "executor": executor,
                    },
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "executor": executor,
                "task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = file_path.read_text(encoding="utf-8")
            if re.search(r"^-\s+executor:\s*.*$", old_text, flags=re.MULTILINE):
                new_text = re.sub(r"^-\s+executor:\s*.*$", f"- executor: {executor}", old_text, flags=re.MULTILINE)
            else:
                for anchor in (
                    r"^-\s+state:\s*.*$",
                    r"^-\s+next-up:\s*.*$",
                    r"^-\s+priority-reason:\s*.*$",
                    r"^-\s+priority:\s*.*$",
                ):
                    m = re.search(anchor, old_text, flags=re.MULTILINE)
                    if m:
                        ins = m.end()
                        new_text = old_text[:ins] + f"\n- executor: {executor}" + old_text[ins:]
                        break
                else:
                    new_text = old_text.replace("\n\n", f"\n- executor: {executor}\n\n", 1)

            diff_lines = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(file_path),
                tofile=str(file_path) if not dry_run else f"{file_path} (dry-run)",
            ))
            diff_str = "".join(diff_lines)
            if not dry_run:
                _atomic_write_text(file_path, new_text, encoding="utf-8")
                new_hash = _file_sha256(file_path)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "executor",
                        "value": executor,
                        "executor": executor,
                    },
                    subject=node_id,
                )
            else:
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()

            return {
                "ok": True,
                "task_id": node_id,
                "executor": executor,
                "task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


def _clean_labels_arg(raw: list[str] | str | None) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    res: list[str] = []
    for item in raw:
        for piece in str(item).split(","):
            p = piece.strip()
            if p and p != "-":
                res.append(p)
    return res


def set_labels(
    tasks_dir: pathlib.Path,
    node_id: str,
    add_labels: list[str] | str | None = None,
    remove_labels: list[str] | str | None = None,
    to_labels: list[str] | str | None = None,
    expect_task_hash: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    clean_add = _clean_labels_arg(add_labels)
    clean_rem = _clean_labels_arg(remove_labels)
    clean_to = _clean_labels_arg(to_labels) if to_labels is not None else None

    labels_to_validate = clean_to if clean_to is not None else clean_add
    for lbl in labels_to_validate:
        if not LABEL_RE.match(lbl):
            return {"ok": False, "error": f"Invalid label {lbl!r} (must match '^[a-z0-9][a-z0-9-]{{0,23}}$')."}

    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]

        if expect_task_hash and expect_task_hash.strip().lower() != node.task_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {node.task_hash}",
            }

        if clean_rem:
            for rl in clean_rem:
                if rl in node.label_sources and node.label_sources[rl].startswith("inherited:"):
                    ancestor = node.label_sources[rl].split(":", 1)[1]
                    return {
                        "ok": False,
                        "error": f"Cannot remove inherited label '{rl}' (inherited from {ancestor}).",
                    }

        raw_own = node.own_fields.get("labels", [])
        if isinstance(raw_own, str):
            # Block bullets give the raw string ("runs, ui"); never split it into characters.
            raw_own = [l.strip() for l in raw_own.split(",") if l.strip() and l.strip() != "-"]
        curr_own = list(raw_own)
        if clean_to is not None:
            new_own = list(dict.fromkeys(clean_to))
        else:
            new_own = list(curr_own)
            if clean_add:
                for al in clean_add:
                    if al not in new_own:
                        new_own.append(al)
            if clean_rem:
                new_own = [l for l in new_own if l not in clean_rem]

        file_path = pathlib.Path(node.file_path)
        if node.block_text is not None:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                file_path,
                node_id,
                new_labels=new_own,
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "labels",
                        "value": ", ".join(new_own) if new_own else "-",
                        "labels": new_own,
                    },
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "labels": new_own,
                "task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = file_path.read_text(encoding="utf-8")
            labels_val = ", ".join(new_own) if new_own else "-"
            if re.search(r"^-\s+labels:\s*.*$", old_text, flags=re.MULTILINE):
                new_text = re.sub(r"^-\s+labels:\s*.*$", f"- labels: {labels_val}", old_text, flags=re.MULTILINE)
            else:
                if node.node_type == "microtask" or node.category == "micro":
                    for anchor in (r"^-\s+size:\s*.*$", r"^-\s+depends-on:\s*.*$"):
                        m = re.search(anchor, old_text, flags=re.MULTILINE)
                        if m:
                            ins = m.end()
                            new_text = old_text[:ins] + f"\n- labels: {labels_val}" + old_text[ins:]
                            break
                    else:
                        new_text = old_text.replace("\n\n", f"\n- labels: {labels_val}\n\n", 1)
                else:
                    for anchor in (
                        r"^-\s+kind:\s*.*$",
                        r"^-\s+size:\s*.*$",
                        r"^-\s+verifier:\s*.*$",
                        r"^-\s+verification-mode:\s*.*$",
                        r"^-\s+profile:\s*.*$",
                        r"^-\s+handoff:\s*.*$",
                    ):
                        m = re.search(anchor, old_text, flags=re.MULTILINE)
                        if m:
                            ins = m.end()
                            new_text = old_text[:ins] + f"\n- labels: {labels_val}" + old_text[ins:]
                            break
                    else:
                        new_text = old_text.replace("\n\n", f"\n- labels: {labels_val}\n\n", 1)
            diff_lines = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(file_path),
                tofile=str(file_path) if not dry_run else f"{file_path} (dry-run)",
            ))
            diff_str = "".join(diff_lines)
            if not dry_run:
                _atomic_write_text(file_path, new_text, encoding="utf-8")
                new_hash = _file_sha256(file_path)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "labels",
                        "value": labels_val,
                        "labels": new_own,
                    },
                    subject=node_id,
                )
            else:
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            return {
                "ok": True,
                "task_id": node_id,
                "labels": new_own,
                "task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


def set_short(
    tasks_dir: pathlib.Path,
    node_id: str,
    short_title: str,
    dry_run: bool = False,
    expect_task_hash: str | None = None,
) -> dict[str, Any]:
    short_title = short_title.strip()
    issues = validate_short_title(short_title)
    if issues:
        return {"ok": False, "error": f"Invalid short title {short_title!r}: {'; '.join(issues)}."}

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        target_file: pathlib.Path | None = None
        is_block = False
        target_node: TaskNode | None = None

        if node_id in tree:
            target_node = tree[node_id]
            target_file = pathlib.Path(target_node.file_path)
            is_block = target_node.block_text is not None
        elif QUESTION_ID_RE.match(node_id):
            questions = discover_questions(tasks_dir)
            for q in questions:
                if q["id"] == node_id:
                    target_file = pathlib.Path(q["file_path"])
                    break
        elif USE_CASE_ID_RE.match(node_id):
            use_cases = discover_use_cases(tasks_dir)
            for uc in use_cases:
                if uc["id"] == node_id:
                    target_file = pathlib.Path(uc["file_path"])
                    break
        elif NOTE_ID_RE.match(node_id):
            notes = discover_inbox_notes(tasks_dir)
            for n in notes:
                if n["id"] == node_id:
                    target_file = pathlib.Path(n["file_path"])
                    break

        if not target_file or not target_file.is_file():
            return {"ok": False, "error": f"Item '{node_id}' not found."}

        actual_hash = target_node.task_hash if target_node else _file_sha256(target_file)
        if expect_task_hash and expect_task_hash.strip().lower() != actual_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {actual_hash}",
            }

        if is_block:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                target_file,
                node_id,
                new_short=short_title,
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {"field": "short", "value": short_title, "short": short_title},
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "short": short_title,
                "task_hash": actual_hash if dry_run else new_block_hash,  # dry-run: the precondition to pass back
                "new_task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = target_file.read_text(encoding="utf-8")
            if re.search(r"^-\s+short:\s*.*$", old_text, flags=re.MULTILINE):
                new_text = re.sub(r"^-\s+short:\s*.*$", f"- short: {short_title}", old_text, flags=re.MULTILINE)
            elif re.search(r"^\*\*(?:Short):\*\*\s*.*$", old_text, flags=re.MULTILINE):
                new_text = re.sub(r"^\*\*(?:Short):\*\*\s*.*$", f"**Short:** {short_title}", old_text, flags=re.MULTILINE)
            else:
                # Keep the canonical optional-field order: insert after the last header field that precedes `short`.
                header_part = old_text.split("\n## ", 1)[0]
                preceding = OPTIONAL_EXTENSION_FIELDS[: OPTIONAL_EXTENSION_FIELDS.index("short")] if "short" in OPTIONAL_EXTENSION_FIELDS else ()
                last_pos = -1
                for fld in preceding:
                    for m_f in re.finditer(rf"^-\s+{re.escape(fld)}:\s*.*$", header_part, flags=re.MULTILINE):
                        last_pos = max(last_pos, m_f.end())
                if last_pos >= 0 and re.search(r"^-\s+handoff:\s*.*$", header_part, flags=re.MULTILINE):
                    new_text = old_text[:last_pos] + f"\n- short: {short_title}" + old_text[last_pos:]
                elif re.search(r"^-\s+handoff:\s*.*$", old_text, flags=re.MULTILINE):
                    new_text = re.sub(r"(^-\s+handoff:\s*.*$)", rf"\1\n- short: {short_title}", old_text, count=1, flags=re.MULTILINE)
                elif re.search(r"^-\s+recommended:\s*.*$", old_text, flags=re.MULTILINE):
                    new_text = re.sub(r"(^-\s+recommended:\s*.*$)", rf"\1\n- short: {short_title}", old_text, count=1, flags=re.MULTILINE)
                elif re.search(r"^-\s+last-verdict:\s*.*$", old_text, flags=re.MULTILINE):
                    new_text = re.sub(r"(^-\s+last-verdict:\s*.*$)", rf"\1\n- short: {short_title}", old_text, count=1, flags=re.MULTILINE)
                elif re.search(r"^-\s+processed-by:\s*.*$", old_text, flags=re.MULTILINE):
                    new_text = re.sub(r"(^-\s+processed-by:\s*.*$)", rf"\1\n- short: {short_title}", old_text, count=1, flags=re.MULTILINE)
                elif re.search(r"^-\s+depends-on:\s*.*$", old_text, flags=re.MULTILINE):
                    new_text = re.sub(r"(^-\s+depends-on:\s*.*$)", rf"\1\n- short: {short_title}", old_text, count=1, flags=re.MULTILINE)
                elif re.search(r"^-\s+title:\s*.*$", old_text, flags=re.MULTILINE):
                    new_text = re.sub(r"(^-\s+title:\s*.*$)", rf"\1\n- short: {short_title}", old_text, count=1, flags=re.MULTILINE)
                elif target_file.name == "plan.md":
                    new_text = re.sub(r"(^#\s+.*$)", rf"\1\n\n- **Short:** {short_title}", old_text, count=1, flags=re.MULTILINE)
                else:
                    new_text = re.sub(r"(^#\s+.*$)", rf"\1\n\n- short: {short_title}", old_text, count=1, flags=re.MULTILINE)

            diff_lines = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(target_file),
                tofile=str(target_file) if not dry_run else f"{target_file} (dry-run)",
            ))
            diff_str = "".join(diff_lines)
            if not dry_run:
                _atomic_write_text(target_file, new_text, encoding="utf-8")
                new_hash = _file_sha256(target_file)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {"field": "short", "value": short_title, "short": short_title},
                    subject=node_id,
                )
            else:
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            return {
                "ok": True,
                "task_id": node_id,
                "short": short_title,
                "task_hash": actual_hash if dry_run else new_hash,  # dry-run: the precondition to pass back
                "new_task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


def set_waiting_on(
    tasks_dir: pathlib.Path,
    node_id: str,
    waiting_on: str,
    dry_run: bool = False,
    expect_task_hash: str | None = None,
) -> dict[str, Any]:
    norm_wo = normalize_waiting_on(waiting_on)
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]

        if expect_task_hash and expect_task_hash.strip().lower() != node.task_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {node.task_hash}",
            }

        file_path = pathlib.Path(node.file_path)
        if node.block_text is not None:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                file_path,
                node_id,
                new_waiting_on=norm_wo or "-",
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "waiting_on",
                        "value": norm_wo,
                        "waiting_on": norm_wo,
                    },
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "waiting_on": norm_wo,
                "task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = file_path.read_text(encoding="utf-8")
            if dry_run:
                _update_task_file_headers_and_state(file_path, new_state=None, waiting_on=norm_wo or "-")
                new_text = file_path.read_text(encoding="utf-8")
                _atomic_write_text(file_path, old_text, encoding="utf-8")
                diff_lines = list(difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=str(file_path),
                    tofile=f"{file_path} (dry-run)",
                ))
                diff_str = "".join(diff_lines)
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            else:
                _update_task_file_headers_and_state(file_path, new_state=None, waiting_on=norm_wo or "-")
                new_text = file_path.read_text(encoding="utf-8")
                diff_lines = list(difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=str(file_path),
                    tofile=str(file_path),
                ))
                diff_str = "".join(diff_lines)
                new_hash = _file_sha256(file_path)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "waiting_on",
                        "value": norm_wo,
                        "waiting_on": norm_wo,
                    },
                    subject=node_id,
                )
            return {
                "ok": True,
                "task_id": node_id,
                "waiting_on": norm_wo,
                "bundle_sha256": new_hash,
                "task_hash": node.task_hash if dry_run else new_hash,
                "new_task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


def set_verify_by(
    tasks_dir: pathlib.Path,
    node_id: str,
    verify_by: str,
    check: str | None = None,
    dry_run: bool = False,
    expect_task_hash: str | None = None,
) -> dict[str, Any]:
    norm_vb = verify_by.strip() if verify_by else ""
    with task_write_lock(tasks_dir):
        tree = discover_task_tree(tasks_dir)
        if node_id not in tree:
            return {"ok": False, "error": f"Task '{node_id}' not found."}
        node = tree[node_id]

        if expect_task_hash and expect_task_hash.strip().lower() != node.task_hash.strip().lower():
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual {node.task_hash}",
            }

        file_path = pathlib.Path(node.file_path)
        if node.block_text is not None:
            _, new_block_hash, diff_str = rewrite_block_in_file(
                file_path,
                node_id,
                new_verify_by=norm_vb or "-",
                expect_task_hash=expect_task_hash,
                dry_run=dry_run,
                return_diff=True,
            )
            if not dry_run:
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "verify_by",
                        "value": norm_vb,
                        "verify_by": norm_vb,
                    },
                    subject=node_id,
                )
                idx_path = tasks_dir / "00-INDEX.md"
                if idx_path.is_file():
                    try:
                        existing_idx = idx_path.read_text(encoding="utf-8")
                        rendered_idx = render_synced_index(tasks_dir, existing_idx, adopt=True)
                        _atomic_write_text(idx_path, rendered_idx, encoding="utf-8")
                    except Exception:
                        pass
            return {
                "ok": True,
                "task_id": node_id,
                "verify_by": norm_vb,
                "check": check,
                "task_hash": new_block_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }
        else:
            old_text = file_path.read_text(encoding="utf-8")
            if dry_run:
                _update_task_file_headers_and_state(file_path, new_state=None, verify_by=norm_vb or "-", verify_check=check)
                new_text = file_path.read_text(encoding="utf-8")
                _atomic_write_text(file_path, old_text, encoding="utf-8")
                diff_lines = list(difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=str(file_path),
                    tofile=f"{file_path} (dry-run)",
                ))
                diff_str = "".join(diff_lines)
                new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            else:
                _update_task_file_headers_and_state(file_path, new_state=None, verify_by=norm_vb or "-", verify_check=check)
                new_text = file_path.read_text(encoding="utf-8")
                diff_lines = list(difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=str(file_path),
                    tofile=str(file_path),
                ))
                diff_str = "".join(diff_lines)
                new_hash = _file_sha256(file_path)
                _emit_event(
                    tasks_dir,
                    "task.updated",
                    {
                        "field": "verify_by",
                        "value": norm_vb,
                        "verify_by": norm_vb,
                    },
                    subject=node_id,
                )
                idx_path = tasks_dir / "00-INDEX.md"
                if idx_path.is_file():
                    try:
                        existing_idx = idx_path.read_text(encoding="utf-8")
                        rendered_idx = render_synced_index(tasks_dir, existing_idx, adopt=True)
                        _atomic_write_text(idx_path, rendered_idx, encoding="utf-8")
                    except Exception:
                        pass
            return {
                "ok": True,
                "task_id": node_id,
                "verify_by": norm_vb,
                "check": check,
                "bundle_sha256": new_hash,
                "task_hash": node.task_hash if dry_run else new_hash,
                "new_task_hash": new_hash,
                "dry_run": dry_run,
                "diff": diff_str,
            }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_emergent_task_file(
    file_path: pathlib.Path,
    tasks_dir: pathlib.Path,
    in_done: bool = False,
) -> dict[str, Any]:
    text = file_path.read_text(encoding="utf-8")
    scanned_lines, _ = scan_markdown_blocks(text)

    rel_path = file_path.relative_to(tasks_dir).as_posix()
    is_folder = file_path.name == "README.md"
    task_root = file_path.parent if is_folder else file_path

    # Locate H1 outside fences
    h1_idx: int | None = None
    h1_text = ""
    for idx, sline in enumerate(scanned_lines):
        if not sline.is_fenced and sline.text.startswith("# "):
            h1_idx = idx
            h1_text = sline.text[2:].strip()
            break

    header_keys: list[str] = []
    headers: dict[str, str] = {}
    header_start: int | None = None
    header_end: int | None = None

    if h1_idx is not None:
        idx = h1_idx + 1
        while idx < len(scanned_lines) and not scanned_lines[idx].text.strip():
            idx += 1
        header_start = idx
        while idx < len(scanned_lines):
            sline = scanned_lines[idx]
            if sline.is_fenced:
                break
            m = HEADER_LINE_RE.match(sline.text)
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
        while scan_idx < len(scanned_lines) and not scanned_lines[scan_idx].text.strip():
            scan_idx += 1
        if (
            scan_idx < len(scanned_lines)
            and not scanned_lines[scan_idx].is_fenced
            and scanned_lines[scan_idx].text.strip().lower().startswith("verification pending:")
        ):
            verification_pending = scanned_lines[scan_idx].text.strip().split(":", 1)[1].strip()

    sections = parse_markdown_sections(text, heading_prefix="## ")
    found_headings = {sec.heading for sec in sections if sec.heading}
    sections_present = [sec for sec in REQUIRED_SECTIONS if sec in found_headings]

    step_placeholders: list[str] = []
    verification_placeholders: list[str] = []
    for sec in sections:
        if sec.heading == "## Steps":
            for sline in sec.lines[1:]:
                if not sline.is_fenced and STEP_PLACEHOLDER_RE.match(sline.text):
                    step_placeholders.append(sline.text.strip())
        elif sec.heading == "## Verification":
            for sline in sec.lines[1:]:
                if not sline.is_fenced and VERIFICATION_PLACEHOLDER_RE.match(sline.text):
                    verification_placeholders.append(sline.text.strip())

    # Determine expected category from directory layout
    parts = file_path.relative_to(tasks_dir).parts
    if in_done:
        # done/<category>/T###-...
        folder_category = parts[1] if len(parts) >= 3 else ""
    else:
        # <category>/T###-...
        folder_category = parts[0] if len(parts) >= 2 else ""

    is_micro = (folder_category == "micro") or (headers.get("category") == "micro")

    raw_depends = headers.get("depends-on", "-")
    depends_list, depends_free_text = parse_depends_on_field(raw_depends) if raw_depends and raw_depends != "-" else ([], "")

    raw_labels = headers.get("labels", "")
    labels_list = (
        [l.strip() for l in raw_labels.split(",") if l.strip() and l.strip() != "-"]
        if raw_labels and raw_labels != "-"
        else []
    )

    raw_state = headers.get("state", "")
    attachments: list[dict[str, Any]] = []
    if is_folder:
        attachments_dir = task_root / "attachments"
        if attachments_dir.is_dir():
            for f in sorted(attachments_dir.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    att_class = classify_existing_attachment_file(f)
                    attachments.append({
                        "name": f.name,
                        "class": att_class,
                        "size": f.stat().st_size,
                    })

    short_field = headers.get("short")
    if short_field and str(short_field).strip() and str(short_field).strip() != "-":
        st_val = str(short_field).strip()
        st_src = "field"
    else:
        st_val = derive_short_title(headers.get("title") or h1_text)
        st_src = "derived"

    raw_coords = headers.get("coordinates")
    if raw_coords and str(raw_coords).strip() and str(raw_coords).strip() != "-":
        coords_refs = [c.strip() for c in str(raw_coords).split(",") if c.strip() and c.strip() != "-"]
        resolved_coords = resolve_coordinates(coords_refs, tasks_dir)
    else:
        coords_refs = []
        resolved_coords = []

    raw_cond = headers.get("conditions")
    cond_ids = parse_conditions_field(raw_cond)
    cond_list, is_cond = resolve_task_conditions(tasks_dir, cond_ids, raw_state or ("open" if is_micro else ""))

    raw_wo = headers.get("waiting-on") or headers.get("waiting_on")
    if raw_wo and str(raw_wo).strip() and str(raw_wo).strip() != "-":
        wo_val = normalize_waiting_on(str(raw_wo).strip())
    else:
        wo_val = extract_waiting_on(raw_state)

    task_dict = {
        "kind": headers.get("kind") or "emergent",
        "id": headers.get("id", ""),
        "title": headers.get("title", "") or h1_text,
        "short": short_field if (short_field and str(short_field).strip() != "-") else None,
        "short_title": st_val,
        "short_title_source": st_src,
        "h1": h1_text,
        "category": headers.get("category", "") or ("micro" if is_micro else folder_category),
        "folder_category": folder_category,
        "priority": headers.get("priority", "P2" if is_micro else ""),
        "priority_reason": headers.get("priority-reason", ""),
        "next_up": headers.get("next-up", "no" if is_micro else ""),
        "state": raw_state or ("open" if is_micro else ""),
        "canonical_state": normalize_state(raw_state or ("open" if is_micro else "")),
        "waiting_on": wo_val,
        "executor": headers.get("executor", "kilo" if is_micro else ""),
        "depends_on": depends_list,
        "depends_on_raw": raw_depends,
        "depends_on_free_text": depends_free_text,
        "decider": headers.get("decider", "-"),
        "sources": headers.get("sources", "-"),
        "paths": headers.get("paths", "-"),
        "conditions": cond_list,
        "conditional": is_cond,
        "conditions_ids": cond_ids,
        "conditions_raw": raw_cond or "-",
        "handoff": headers.get("handoff", f"Read {rel_path} and fix it." if is_micro else ""),
        "labels": labels_list,
        "node_type": "microtask" if is_micro else "leaf",
        "size": headers.get("size", "XS" if is_micro else "M"),
        "profile": headers.get("profile"),
        "verification_mode": headers.get("verification-mode"),
        "verifier": headers.get("verifier"),
        "verify_by": headers.get("verify-by") or headers.get("verify_by") or extract_verify_by(raw_state),
        "verify-by": headers.get("verify-by") or headers.get("verify_by") or extract_verify_by(raw_state),
        "verification_pending": verification_pending,
        "header_keys": header_keys,
        "headers": headers,
        "coordinates": resolved_coords,
        "coordinates_refs": coords_refs,
        "coordinates_raw": raw_coords,
        "moved_to": headers.get("moved-to"),
        "sections_present": sections_present,
        "found_headings": list(found_headings),
        "step_placeholders": step_placeholders,
        "verification_placeholders": verification_placeholders,
        "what_body": next((sec.body for sec in sections if sec.heading == "What"), "").strip(),
        "is_folder": is_folder,
        "in_done": in_done,
        "file_path": str(file_path),
        "task_root": str(task_root),
        "rel_path": rel_path,
        # `attachments` stays a list of names (UI contract since 09.2); details per file:
        "attachments": [a["name"] for a in attachments],
        "attachment_details": attachments,
    }
    task_dict["bundle_sha256"] = task_bundle_sha256(task_dict)
    return task_dict


# ---------------------------------------------------------------------------
# Blocking Questions (Q###) Data Model & Parsing
# ---------------------------------------------------------------------------

def parse_blocks_header(raw_blocks: str) -> list[tuple[str, str | None]]:
    if not raw_blocks or raw_blocks.strip() == "-":
        return []
    items: list[tuple[str, str | None]] = []
    for piece in raw_blocks.split(","):
        p = piece.strip()
        if not p:
            continue
        m = re.match(r"^([^\s(]+)(?:\s*\(([^)]+)\))?$", p)
        if m:
            items.append((m.group(1).strip(), m.group(2).strip() if m.group(2) else None))
        else:
            items.append((p, None))
    return items


def normalize_fenced_text(text: str) -> str:
    """Normalize text for storing inside a fenced code block per spec:
    The stored text is the given text with at most a single trailing newline
    (\\r\\n or \\n) normalized away. All other characters (leading spaces,
    internal newlines, trailing spaces on lines) are preserved byte-identical.
    """
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith("\n"):
        return text[:-1]
    return text


def _format_fenced_text(text: str) -> str:
    norm_text = normalize_fenced_text(text)
    runs = re.findall(r"`+", norm_text)
    max_len = max((len(r) for r in runs), default=0)
    fence_len = max(3, max_len + 1)
    fence = "`" * fence_len
    return f"{fence}text\n{norm_text}\n{fence}"


def format_question_content(
    id: str,
    title: str,
    question: str,
    status: str,
    blocks: str,
    decider: str,
    asked_by: str,
    asked: str,
    origin_run: str,
    open_answer: str,
    recommended: str,
    context: str,
    options: list[tuple[str, str, str | None]] | None = None,
    choice: str = "-",
    answered_by: str = "-",
    answered: str = "-",
    text: str | None = None,
    short: str | None = None,
    applied: str | None = None,
    moved_to: str | None = None,
    reason: str | None = None,
    notes: str | None = None,
) -> str:
    norm_context = normalize_fenced_text(context.rstrip("\r\n"))
    lines = [
        f"# {id} {title}",
        "",
        f"- id: {id}",
        f"- question: {question}",
        f"- status: {status}",
        f"- blocks: {blocks.strip() or '-'}",
        f"- decider: {decider}",
        f"- asked-by: {asked_by}",
        f"- asked: {asked}",
        f"- origin-run: {origin_run}",
        f"- open-answer: {open_answer}",
        f"- recommended: {recommended}",
    ]
    if applied is not None and str(applied).strip() and str(applied).strip() != "":
        lines.append(f"- applied: {str(applied).strip()}")
    if moved_to is not None and str(moved_to).strip() and str(moved_to).strip() != "":
        lines.append(f"- moved-to: {str(moved_to).strip()}")
    if reason is not None and str(reason).strip() and str(reason).strip() != "":
        lines.append(f"- reason: {str(reason).strip()}")
    if short and short.strip() and short.strip() != "-":
        lines.append(f"- short: {short.strip()}")
    lines.extend([
        "",
        "## Context",
        "",
        norm_context,
        "",
        "## Options",
        "",
    ])
    if options:
        for opt in options:
            label, opt_title, consequence = opt
            if consequence:
                lines.append(f"- **{label}** — {opt_title}: {consequence}")
            else:
                lines.append(f"- **{label}** — {opt_title}")
    lines.extend([
        "",
        "## Answer",
        "",
        f"- choice: {choice}",
        f"- answered-by: {answered_by}",
        f"- answered: {answered}",
    ])
    if text is not None and text != "":
        lines.extend([
            "",
            _format_fenced_text(text),
        ])
    if notes is not None and notes.strip():
        lines.extend([
            "",
            "## Notes",
            "",
            notes.strip(),
        ])
    lines.append("")
    return "\n".join(lines)


def parse_question_file(
    file_path: pathlib.Path,
    tasks_dir: pathlib.Path,
) -> dict[str, Any]:
    text = file_path.read_text(encoding="utf-8")
    scanned_lines, _ = scan_markdown_blocks(text)

    rel_path = file_path.relative_to(tasks_dir).as_posix()

    h1_idx: int | None = None
    h1_text = ""
    for idx, sline in enumerate(scanned_lines):
        if not sline.is_fenced and sline.text.startswith("# "):
            h1_idx = idx
            h1_text = sline.text[2:].strip()
            break

    title = h1_text
    if h1_text:
        parts = h1_text.split(None, 1)
        if len(parts) > 1 and QUESTION_ID_RE.match(parts[0]):
            title = parts[1].strip()

    header_keys: list[str] = []
    headers: dict[str, str] = {}
    header_end = 0

    if h1_idx is not None:
        idx = h1_idx + 1
        while idx < len(scanned_lines) and not scanned_lines[idx].text.strip():
            idx += 1
        while idx < len(scanned_lines):
            sline = scanned_lines[idx]
            if sline.is_fenced:
                break
            m = HEADER_LINE_RE.match(sline.text)
            if not m:
                break
            k, v = m.group(1), m.group(2).strip()
            header_keys.append(k)
            headers[k] = v
            idx += 1
        header_end = idx

    sections = parse_markdown_sections(text, heading_prefix="## ")
    sections_present = [sec.heading for sec in sections if sec.heading]
    sec_map = {sec.heading: sec for sec in sections if sec.heading}

    context_text = sec_map["## Context"].body.strip() if "## Context" in sec_map else ""
    options_text = sec_map["## Options"].body.strip() if "## Options" in sec_map else ""
    answer_text = sec_map["## Answer"].body.strip() if "## Answer" in sec_map else ""
    notes_heading = next((h for h in ("## Notes", "## Free notes", "## Discussion") if h in sec_map), None)
    notes_text = sec_map[notes_heading].body.strip() if notes_heading else None

    options: list[dict[str, str | None]] = []
    if "## Options" in sec_map:
        for sline in sec_map["## Options"].lines[1:]:
            if sline.is_fenced:
                continue
            line_s = sline.text.strip()
            if not line_s.startswith("-"):
                continue
            om = OPTION_LINE_RE.match(line_s)
            if om:
                lbl = om.group(1).strip()
                opt_title = om.group(2).strip()
                conseq = om.group(3).strip() if om.group(3) else None
                options.append({"label": lbl, "title": opt_title, "consequence": conseq, "raw": line_s})
            else:
                options.append({"label": "", "title": line_s, "consequence": None, "raw": line_s})

    choice = "-"
    answered_by = "-"
    answered = "-"
    fenced_text: str | None = None

    if "## Answer" in sec_map:
        ans_sec = sec_map["## Answer"]
        for sline in ans_sec.lines[1:]:
            if sline.is_fenced:
                continue
            line_s = sline.text.strip()
            if line_s.startswith("- choice:"):
                choice = line_s.split(":", 1)[1].strip()
            elif line_s.startswith("- answered-by:"):
                answered_by = line_s.split(":", 1)[1].strip()
            elif line_s.startswith("- answered:"):
                answered = line_s.split(":", 1)[1].strip()

        if ans_sec.code_blocks:
            fenced_text = ans_sec.code_blocks[0].content

    blocks_raw = headers.get("blocks", "")
    blocks_parsed = parse_blocks_header(blocks_raw)

    short_field = headers.get("short")
    if short_field and str(short_field).strip() and str(short_field).strip() != "-":
        q_st_val = str(short_field).strip()
        q_st_src = "field"
    else:
        q_st_val = derive_short_title(title or headers.get("question", ""))
        q_st_src = "derived"

    today = datetime.date.today()
    asked_str = headers.get("asked", "")
    age_days = 0
    if asked_str:
        try:
            asked_date = datetime.date.fromisoformat(str(asked_str).strip()[:10])
            age_days = max(0, (today - asked_date).days)
        except Exception:
            age_days = 0

    return {
        "id": headers.get("id", ""),
        "question": headers.get("question", ""),
        "status": headers.get("status", ""),
        "short": short_field if (short_field and str(short_field).strip() != "-") else None,
        "short_title": q_st_val,
        "short_title_source": q_st_src,
        "blocks": blocks_raw,
        "blocks_parsed": blocks_parsed,
        "decider": headers.get("decider", ""),
        "asked_by": headers.get("asked-by", ""),
        "asked": headers.get("asked", ""),
        "age_days": age_days,
        "origin_run": headers.get("origin-run", ""),
        "open_answer": headers.get("open-answer", ""),
        "recommended": headers.get("recommended", ""),
        "applied": headers.get("applied", "-"),
        "moved_to": headers.get("moved-to"),
        "reason": headers.get("reason"),
        "notes": notes_text,
        "title": title,
        "context": context_text,
        "options": options,
        "answer": {
            "choice": choice,
            "answered_by": answered_by,
            "answered": answered,
            "text": fenced_text,
        },
        "header_keys": header_keys,
        "headers": headers,
        "sections_present": sections_present,
        "file_path": str(file_path),
        "rel_path": rel_path,
        "filename": file_path.name,
    }


def discover_questions(tasks_dir: pathlib.Path) -> list[dict[str, Any]]:
    questions_dir = tasks_dir / "questions"
    if not questions_dir.is_dir():
        return []
    applied_map: dict[str, dict[str, Any]] = {}
    ledger_file = questions_dir / "applied.jsonl"
    if ledger_file.is_file():
        try:
            for line in ledger_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and "question" in rec:
                        applied_map[rec["question"]] = rec
        except Exception:
            pass

    questions: list[dict[str, Any]] = []
    for entry in sorted(questions_dir.rglob("*.md")):
        if entry.is_file() and not entry.name.startswith(".") and QUESTION_ID_RE.match(entry.name.split("-")[0]):
            try:
                q = parse_question_file(entry, tasks_dir)
                header_applied = (q["headers"].get("applied") or "").strip().lower()
                if header_applied == "yes" or q["id"] in applied_map:
                    q["applied"] = True
                    q["applied_record"] = applied_map.get(q["id"])
                else:
                    q["applied"] = False
                    q["applied_record"] = None
                questions.append(q)
            except Exception:
                pass
    return questions


def _find_earliest_prior_state_for_task(tasks_dir: pathlib.Path, task_id: str, question_ids: list[str]) -> str:
    all_questions = discover_questions(tasks_dir)
    q_map = {q["id"]: q for q in all_questions}
    sorted_qids = sorted(question_ids)
    for qid in sorted_qids:
        q = q_map.get(qid)
        if not q:
            continue
        for tid, prior_state in q["blocks_parsed"]:
            if tid == task_id and prior_state and prior_state not in ("waiting", "blocked") and prior_state in CANONICAL_STATES:
                return prior_state
    return "open"


# ---------------------------------------------------------------------------
# Use Cases Discovery, Management & AI Validation (Spec 15)
# ---------------------------------------------------------------------------

def parse_use_case_file(file_path: pathlib.Path, tasks_dir: pathlib.Path) -> dict[str, Any]:
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    h1_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    h1_title = h1_match.group(1).strip() if h1_match else file_path.stem

    headers: dict[str, str] = {}
    for line in lines:
        if line.startswith("#"):
            continue
        m = re.match(r"^-\s+([a-zA-Z0-9_-]+):\s*(.*)$", line)
        if m:
            headers[m.group(1).strip().lower()] = m.group(2).strip()
        elif headers and not line.strip():
            break

    uc_id = headers.get("id") or file_path.stem.split("-")[0]
    title = headers.get("title") or (h1_title.split("-", 1)[-1].strip() if "-" in h1_title else h1_title)
    actor = headers.get("actor", "End-User")
    status = headers.get("status", "draft")
    priority = headers.get("priority", "P1")
    linked_raw = headers.get("linked-tasks") or headers.get("linked_tasks") or ""
    linked_tasks = [t.strip() for t in linked_raw.split(",") if t.strip() and t.strip() != "-"]
    vtype = headers.get("verification-type") or headers.get("verification_type") or "automated-probe"
    last_tested = headers.get("last-tested") or headers.get("last_tested")
    last_verdict = headers.get("last-verdict") or headers.get("last_verdict")

    def _extract_section(heading: str) -> str:
        pos = text.find(heading)
        if pos < 0:
            return ""
        after = text[pos + len(heading):]
        next_pos = re.search(r"\n##\s+", after)
        if next_pos:
            return after[:next_pos.start()].strip()
        return after.strip()

    desc = _extract_section("## Description & Business Value") or _extract_section("## Description")
    preconditions = _extract_section("## Preconditions")
    scenario = _extract_section("## Scenario / Interaction Steps") or _extract_section("## Scenario")
    command = _extract_section("## Automated Verification Command") or _extract_section("## Verification Command")
    cmd_clean = command
    cmd_m = re.search(r"```(?:bash|sh)?\n(.*?)\n```", command, re.DOTALL)
    if cmd_m:
        cmd_clean = cmd_m.group(1).strip()

    criteria = _extract_section("## Acceptance Criteria")
    log = _extract_section("## AI Validation Log") or _extract_section("## Validation History")

    short_field = headers.get("short")
    if short_field and str(short_field).strip() and str(short_field).strip() != "-":
        uc_st_val = str(short_field).strip()
        uc_st_src = "field"
    else:
        uc_st_val = derive_short_title(title)
        uc_st_src = "derived"

    return {
        "id": uc_id,
        "title": title,
        "short": short_field if (short_field and str(short_field).strip() != "-") else None,
        "short_title": uc_st_val,
        "short_title_source": uc_st_src,
        "actor": actor,
        "status": status,
        "priority": priority,
        "linked_tasks": linked_tasks,
        "verification_type": vtype,
        "last_tested": last_tested,
        "last_verdict": last_verdict,
        "description": desc,
        "preconditions": preconditions,
        "scenario": scenario,
        "verification_command": cmd_clean,
        "acceptance_criteria": criteria,
        "validation_log": log,
        "file_path": str(file_path),
        "rel_path": str(file_path.relative_to(tasks_dir)),
        "content": text,
    }


def discover_use_cases(tasks_dir: pathlib.Path) -> list[dict[str, Any]]:
    uc_dir = tasks_dir / "use-cases"
    if not uc_dir.is_dir():
        return []
    use_cases: list[dict[str, Any]] = []
    for entry in sorted(uc_dir.iterdir()):
        if entry.is_file() and entry.suffix == ".md":
            prefix = entry.name.split("-")[0]
            if USE_CASE_ID_RE.match(prefix):
                try:
                    uc = parse_use_case_file(entry, tasks_dir)
                    use_cases.append(uc)
                except Exception:
                    pass
    return use_cases


def create_or_update_use_case(tasks_dir: pathlib.Path, data: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    uc_id = data.get("id")
    if not uc_id or not USE_CASE_ID_RE.match(uc_id):
        return False, {"error": f"Invalid use case id {uc_id!r}, must match UC###"}
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    with task_write_lock(tasks_dir):
        title = data.get("title", "Untitled Use Case")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        fname = f"{uc_id}-{slug}.md"
        uc_dir = tasks_dir / "use-cases"
        uc_dir.mkdir(parents=True, exist_ok=True)
        fpath = uc_dir / fname

        existing = list(uc_dir.glob(f"{uc_id}-*.md"))
        if existing:
            fpath = existing[0]

        linked_tasks_str = ", ".join(data.get("linked_tasks", [])) or "-"
        short_val = data.get("short")
        if short_val and str(short_val).strip() and str(short_val).strip() != "-":
            short_val = str(short_val).strip()
        else:
            short_val = derive_short_title(title)

        content = f"""# {uc_id} - {title}

- id: {uc_id}
- title: {title}
- actor: {data.get("actor", "End-User")}
- status: {data.get("status", "draft")}
- priority: {data.get("priority", "P1")}
- linked-tasks: {linked_tasks_str}
- verification-type: {data.get("verification_type", "automated-probe")}
- last-tested: {data.get("last_tested") or "-"}
- last-verdict: {data.get("last_verdict") or "-"}
- short: {short_val}

## Description & Business Value
{data.get("description", "Describe user value and business context.")}

## Preconditions
{data.get("preconditions", "- System running and initialized.")}

## Scenario / Interaction Steps
{data.get("scenario", "1. User initiates action.\\n2. System responds.")}

## Automated Verification Command
```bash
{data.get("verification_command", "echo 'No verification command specified'")}
```

## Acceptance Criteria
{data.get("acceptance_criteria", "- [ ] Core flow works as expected.")}

## AI Validation Log
{data.get("validation_log", "")}
"""
        _atomic_write_text(fpath, content)
        return True, {"ok": True, "id": uc_id, "file_path": str(fpath), "rel_path": str(fpath.relative_to(tasks_dir))}


def record_use_case_validation(
    tasks_dir: pathlib.Path,
    uc_id: str,
    verdict: str,
    summary: str,
    evidence: str = "",
    actor: str = "ai-validator",
    gaps: list[str] | None = None,
) -> tuple[bool, dict[str, Any]]:
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    with task_write_lock(tasks_dir):
        use_cases = discover_use_cases(tasks_dir)
        target = next((u for u in use_cases if u["id"] == uc_id), None)
        if not target:
            return False, {"error": f"Use case {uc_id} not found"}

        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        now_date = datetime.date.today().isoformat()
        verdict_clean = verdict.strip().lower()
        new_status = "verified" if verdict_clean == "pass" else ("failing" if verdict_clean == "fail" else "partial")

        log_entry = f"\n### [{now_iso}] AI Validation by {actor}\n- **Verdict:** `{verdict.upper()}`\n- **Summary:** {summary}\n"
        if evidence:
            log_entry += f"- **Evidence:**\n{evidence}\n"
        if gaps:
            log_entry += "- **Gaps Found:**\n" + "\n".join(f"  - {g}" for g in gaps) + "\n"

        existing_content = target["content"]
        updated_content = re.sub(r"-\s+last-tested:\s*.*$", f"- last-tested: {now_date}", existing_content, flags=re.MULTILINE)
        updated_content = re.sub(r"-\s+last-verdict:\s*.*$", f"- last-verdict: {verdict_clean}", updated_content, flags=re.MULTILINE)
        updated_content = re.sub(r"-\s+status:\s*.*$", f"- status: {new_status}", updated_content, flags=re.MULTILINE)

        if "## AI Validation Log" in updated_content:
            updated_content = updated_content.rstrip() + "\n" + log_entry
        else:
            updated_content = updated_content.rstrip() + "\n\n## AI Validation Log\n" + log_entry

        fpath = pathlib.Path(target["file_path"])
        _atomic_write_text(fpath, updated_content)
        return True, {
            "ok": True,
            "id": uc_id,
            "verdict": verdict,
            "status": new_status,
            "summary": summary,
            "file_path": str(fpath),
            "rel_path": str(fpath.relative_to(tasks_dir)),
        }


def validate_use_case_probe(
    tasks_dir: pathlib.Path,
    uc_id: str,
    timeout_seconds: int = 60,
    actor: str = "automated-probe",
) -> tuple[bool, dict[str, Any]]:
    """Execute the automated verification command of a use case and record the verdict."""
    use_cases = discover_use_cases(tasks_dir)
    target = next((u for u in use_cases if u["id"] == uc_id), None)
    if not target:
        return False, {"error": f"Use case {uc_id} not found"}

    cmd = target.get("verification_command", "").strip()
    if not cmd or cmd.startswith("echo 'No verification command"):
        return True, {
            "ok": True,
            "id": uc_id,
            "verdict": target.get("last_verdict") or "untested",
            "status": target.get("status"),
            "message": "No runnable verification command specified; manual or AI agent audit required.",
        }

    workspace = tasks_dir.parent
    start_t = time.time()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        elapsed = time.time() - start_t
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        exit_code = proc.returncode

        if exit_code == 0:
            verdict = "pass"
            summary = f"Automated probe passed in {elapsed:.2f}s with exit code 0"
            evidence = f"```\n$ {cmd}\n(exit code 0)\n{out[:500]}\n```"
            gaps = None
        else:
            verdict = "fail"
            summary = f"Automated probe failed with exit code {exit_code} in {elapsed:.2f}s"
            evidence = f"```\n$ {cmd}\n(exit code {exit_code})\nSTDOUT:\n{out[:300]}\nSTDERR:\n{err[:300]}\n```"
            gaps = [err or out or f"Command failed with exit code {exit_code}"]

        ok, res = record_use_case_validation(
            tasks_dir=tasks_dir,
            uc_id=uc_id,
            verdict=verdict,
            summary=summary,
            evidence=evidence,
            actor=actor,
            gaps=gaps,
        )
        res["exit_code"] = exit_code
        res["elapsed_seconds"] = round(elapsed, 2)
        res["command"] = cmd
        return ok, res
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_t
        summary = f"Automated probe timed out after {timeout_seconds}s"
        evidence = f"Command timed out: `{cmd}`"
        ok, res = record_use_case_validation(
            tasks_dir=tasks_dir,
            uc_id=uc_id,
            verdict="fail",
            summary=summary,
            evidence=evidence,
            actor=actor,
            gaps=[f"Timeout after {timeout_seconds}s"],
        )
        res["exit_code"] = -1
        res["elapsed_seconds"] = round(elapsed, 2)
        res["command"] = cmd
        return ok, res
    except Exception as e:
        return False, {"error": f"Failed to execute probe: {e}"}


def run_validation_campaign(
    tasks_dir: pathlib.Path,
    timeout_seconds: int = 60,
    actor_filter: str | None = None,
    actor_name: str = "campaign-runner",
) -> dict[str, Any]:
    """Execute all active use cases, compute product functional readiness, and detect regressions."""
    use_cases = discover_use_cases(tasks_dir)
    if actor_filter:
        use_cases = [u for u in use_cases if u.get("actor", "").lower() == actor_filter.lower()]

    results: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []

    for uc in use_cases:
        prev_verdict = (uc.get("last_verdict") or "").lower()
        ok, res = validate_use_case_probe(tasks_dir, uc["id"], timeout_seconds=timeout_seconds, actor=actor_name)
        res["title"] = uc["title"]
        res["actor"] = uc["actor"]
        res["previous_verdict"] = prev_verdict
        new_verdict = (res.get("verdict") or "").lower()
        if prev_verdict == "pass" and new_verdict == "fail":
            regressions.append(res)
        results.append(res)

    total = len(results)
    passed = sum(1 for r in results if r.get("verdict") == "pass")
    failed = sum(1 for r in results if r.get("verdict") == "fail")
    score_pct = round((passed / total * 100), 1) if total > 0 else 0.0

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reports_dir = tasks_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"validation-campaign-{int(time.time())}.md"

    report_lines = [
        f"# Product Validation Campaign Report — {now_iso}",
        "",
        f"- **Readiness Score:** `{score_pct}%` ({passed}/{total} Use Cases Verified)",
        f"- **Total Tested:** {total}",
        f"- **Passed:** {passed}",
        f"- **Failed:** {failed}",
        f"- **Regressions Detected:** {len(regressions)}",
        "",
        "## Compliance Matrix by Use Case",
        "",
        "| ID | Title | Actor | Verdict | Command |",
        "| :--- | :--- | :--- | :---: | :--- |",
    ]
    for r in results:
        v_badge = "PASS" if r.get("verdict") == "pass" else ("FAIL" if r.get("verdict") == "fail" else "UNTESTED")
        cmd_snippet = f"`{r.get('command')[:40]}...`" if r.get("command") else "-"
        report_lines.append(f"| **{r['id']}** | {r['title']} | {r['actor']} | `{v_badge}` | {cmd_snippet} |")

    if regressions:
        report_lines.extend([
            "",
            "## Regressions Detected",
            "",
            "The following use cases previously passed but failed in this campaign:",
            "",
        ])
        for reg in regressions:
            report_lines.append(f"- **{reg['id']}**: {reg['title']} — {reg.get('summary')}")

    report_content = "\n".join(report_lines) + "\n"
    _atomic_write_text(report_file, report_content)

    return {
        "ok": True,
        "timestamp": now_iso,
        "readiness_score": score_pct,
        "total": total,
        "passed": passed,
        "failed": failed,
        "regressions_count": len(regressions),
        "regressions": regressions,
        "report_file": str(report_file),
        "results": results,
    }


def parse_option_arg(opt: str) -> tuple[str, str, str | None]:
    opt = opt.strip()
    m = re.match(r"^(?:-\s+)?\*\*([A-Za-z0-9]+)\*\*\s+[—–-]\s+(.+?)(?::\s*(.*))?$", opt)
    if m:
        label = m.group(1).strip()
        title = m.group(2).strip()
        consequence = m.group(3).strip() if m.group(3) else None
        return label, title, consequence
    if "=" in opt:
        label, rest = opt.split("=", 1)
        label = label.strip()
        if ":" in rest:
            title, consequence = rest.split(":", 1)
            return label, title.strip(), consequence.strip()
        return label, rest.strip(), None
    m2 = re.match(r"^([A-Za-z0-9]+)\s+[—–-]\s+(.+?)(?::\s*(.*))?$", opt)
    if m2:
        label = m2.group(1).strip()
        title = m2.group(2).strip()
        consequence = m2.group(3).strip() if m2.group(3) else None
        return label, title, consequence
    if ":" in opt:
        label, title = opt.split(":", 1)
        return label.strip(), title.strip(), None
    return opt, opt, None


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


def _format_depends_on(ids: list[str]) -> str:
    """Comma-separated id list, or '-' (the `depends_on` string exposed to the UI and `tasks list`)."""
    return ", ".join(dict.fromkeys(ids)) or "-"


def _read_index_initiative_statuses(tasks_dir: pathlib.Path) -> dict[str, str]:
    """Initiative states from the 00-INDEX.md Initiatives table (legacy plans without task blocks)."""
    index_path = tasks_dir / "00-INDEX.md"
    statuses: dict[str, str] = {}
    if not index_path.is_file():
        return statuses
    for line in index_path.read_text(encoding="utf-8").splitlines():
        m_idx = re.match(r"^\|\s*\d+\s*\|\s*(\d{2,})\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([^|]+)\|", line)
        if m_idx:
            st_col = m_idx.group(4).lower()
            if "not merged" in st_col or "progress" in st_col:
                statuses[m_idx.group(1)] = "in progress"
            elif "merged" in st_col or "done" in st_col:
                statuses[m_idx.group(1)] = "done"
            else:
                statuses[m_idx.group(1)] = "open"
    return statuses


def _legacy_initiative_status(
    entry: pathlib.Path, num: str, in_done: bool, scanned_lines: list[ScannedLine], index_statuses: dict[str, str]
) -> str:
    """Initiative state for a plan with no `### NN.T - title` blocks (nothing to derive from)."""
    if in_done or (entry / "summary.md").is_file():
        return "done"
    if num in index_statuses:
        return index_statuses[num]
    for sline in scanned_lines:
        if sline.is_fenced:
            continue
        sm = re.search(r"^\s*>\s*\*\*Status:\*\*\s*([^\n·]+)", sline.text, re.IGNORECASE)
        if sm:
            st_raw = sm.group(1).lower()
            if "not merged" in st_raw or "progress" in st_raw:
                return "in progress"
            if "done" in st_raw or "merged" in st_raw:
                return "done"
            return "open"
    return "open"


def _legacy_plan_tasks(
    tasks_dir: pathlib.Path, entry: pathlib.Path, num: str, text: str, scanned_lines: list[ScannedLine], init_status: str
) -> list[dict[str, Any]]:
    """Non-canonical plan items (table rows, `NN.T-*.md` files), read-only, for plans not yet normalized
    (`plan_format_warnings` flags them; spec subtasks §5 / plan 11.5)."""
    expanded_tasks = []
    for sub in sorted(entry.glob(f"{num}.*-*.md")):
        sub_m = re.match(rf"^({re.escape(num)}\.\d+)-(.+)\.md$", sub.name)
        if sub_m:
            sub_title = sub_m.group(2)
            expanded_tasks.append(
                {"id": sub_m.group(1), "title": sub_title, "rel_path": sub.relative_to(tasks_dir).as_posix(),
                 "state": init_status, "depends_on": "-", "legacy": True,
                 "short": None, "short_title": derive_short_title(sub_title), "short_title_source": "derived"}
            )
    if expanded_tasks:
        return expanded_tasks
    table_tasks = []
    for sline in scanned_lines:
        if sline.is_fenced:
            continue
        tm = re.match(r"^\|\s*\*\*(T\w+|\d+\.\d+)\*\*\s*\|\s*(.+?)\s*\|", sline.text)
        if not tm:
            continue
        sub_id, raw_content = tm.groups()
        title_m = re.match(r"^\*\*([^*]+)\*\*[:\s]*(.*)$", raw_content.strip())
        sub_title = title_m.group(1).strip() if title_m else raw_content.strip()
        sub_state = init_status
        if init_status == "in progress":
            if re.search(rf"\b{re.escape(sub_id)}\b.*?\bverified\b", text, re.IGNORECASE):
                sub_state = "verified"
            elif re.search(rf"\b{re.escape(sub_id)}\b.*?\bdelivered\b", text, re.IGNORECASE):
                sub_state = "delivered"
            elif re.search(rf"\b{re.escape(sub_id)}\b.*?\bqueued\b", text, re.IGNORECASE):
                sub_state = "open"
        table_tasks.append({
            "id": sub_id,
            "title": sub_title,
            "state": sub_state,
            "depends_on": "-",
            "legacy": True,
            "short": None,
            "short_title": derive_short_title(sub_title),
            "short_title_source": "derived",
        })
    return table_tasks


def _node_task_dict(cn: "TaskNode") -> dict[str, Any]:
    return {
        "id": cn.id,
        "title": cn.title,
        "short": cn.short,
        "short_title": cn.short_title,
        "short_title_source": cn.short_title_source,
        "parent": cn.parent,
        "depth": cn.depth,
        "node_type": cn.node_type,
        "state": cn.state,
        "canonical_state": cn.canonical_state,
        "derived_state": cn.derived_state,
        "priority": cn.priority,
        "priority_reason": cn.priority_reason,
        "executor": cn.executor,
        "handoff": cn.handoff,
        "rel_path": cn.rel_path,
        "file_path": cn.file_path,
        "is_leaf": cn.is_leaf,
        "is_container": cn.is_container,
        "leaves_done": cn.leaves_done,
        "leaves_total": cn.leaves_total,
        "bundle_sha256": cn.task_hash,
        "task_hash": cn.task_hash,
        # String form kept for the UI / `tasks list` consumers; the id lists are alongside.
        "depends_on": _format_depends_on(cn.depends_on),
        "depends_on_ids": list(cn.depends_on),
        "expanded_depends_on": cn.expanded_depends_on,
        "fields": cn.fields,
        "labels": cn.labels,
        "in_closed_section": cn.in_closed_section,
        "conditions": list(cn.conditions),
        "conditional": cn.conditional,
        "waiting_on": cn.waiting_on,
    }


def discover_initiatives(tasks_dir: pathlib.Path, tree: dict[str, "TaskNode"] | None = None) -> list[dict[str, Any]]:
    initiatives: list[dict[str, Any]] = []
    if not tasks_dir.is_dir():
        return initiatives

    if tree is None:
        tree = discover_task_tree(tasks_dir)
    init_nodes = [n for n in tree.values() if n.node_type == "initiative"]
    init_nodes.sort(key=lambda n: n.id)
    index_statuses: dict[str, str] | None = None

    for n in init_nodes:
        child_tasks: list[dict[str, Any]] = []

        def _collect_tasks(cid: str) -> None:
            if cid not in tree:
                return
            cn = tree[cid]
            child_tasks.append(_node_task_dict(cn))
            for ccid in cn.children:
                _collect_tasks(ccid)

        for cid in n.children:
            _collect_tasks(cid)

        plan_path = pathlib.Path(n.file_path)
        entry = plan_path.parent
        location = "active"
        if n.in_done:
            location = "merged" if entry.parent.name == "merged" else "done"
        status = n.derived_state or n.state
        legacy = False
        if not child_tasks:
            # No canonical blocks: keep the pre-11.1 reading of legacy plans (nothing to derive from).
            if index_statuses is None:
                index_statuses = _read_index_initiative_statuses(tasks_dir)
            text = plan_path.read_text(encoding="utf-8")
            scanned_lines, _ = scan_markdown_blocks(text)
            status = _legacy_initiative_status(entry, n.id, n.in_done, scanned_lines, index_statuses)
            child_tasks = _legacy_plan_tasks(tasks_dir, entry, n.id, text, scanned_lines, status)
            legacy = bool(child_tasks)
        initiatives.append({
            "id": n.id,
            "slug": n.slug,
            "folder": entry.name,
            "title": n.title,
            "short": n.short,
            "short_title": n.short_title,
            "short_title_source": n.short_title_source,
            "status": status,
            "derived_state": n.derived_state,
            "location": location,
            "rel_path": n.rel_path,
            "has_summary": (entry / "summary.md").is_file(),
            "tasks": child_tasks,
            "legacy_tasks": legacy,
            "bundle_sha256": n.task_hash,
            "leaves_done": n.leaves_done,
            "leaves_total": n.leaves_total,
        })
    return initiatives


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Non-canonical task items in a plan: bullets/headings/table rows with T<n> ids, or
# NN.T headings without the " - " separator. Canonical form: "### NN.T - <title>".
_LEGACY_PLAN_ITEM_RES = (
    ("bullet task `T<n>`", re.compile(r"^\s*[-*]\s+\*{0,2}T\d+[a-z]?\b")),
    ("table row task `T<n>`", re.compile(r"^\|\s*\*{0,2}T\d+[a-z]?\*{0,2}\s*\|")),
    ("heading task `T<n>`", re.compile(r"^#{2,4}\s+T\d+[a-z]?\b")),
    ("`NN.T` heading without ' - ' separator", re.compile(r"^#{2,4}\s+\d{2,}(?:\.\d+[a-z]?)+(?!\w)(?!\s+[\u2014\u2013-]\s)")),
)


def plan_format_warnings(plan_path: pathlib.Path, rel: str) -> list[str]:
    """Warnings for task items the engine cannot see as canonical `### NN.T - title` blocks."""
    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError:
        return []
    counts: dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for label, rx in _LEGACY_PLAN_ITEM_RES:
            if rx.match(line):
                counts[label] = counts.get(label, 0) + 1
                break
    if not counts:
        return []
    found = ", ".join(f"{n} {label}" for label, n in counts.items())
    return [
        f"{rel}: non-canonical task items ({found}); plan tasks must be `### NN.T - <title>` blocks "
        "with a `- **Status:**` line (task-pipeline: 'Normalizing existing tasks')."
    ]


def validate_tasks_tree(tasks_dir: pathlib.Path) -> tuple[list[str], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[str] = []
    warnings: list[str] = []

    tree = discover_task_tree(tasks_dir)
    emergent = discover_emergent_tasks(tasks_dir)
    initiatives = discover_initiatives(tasks_dir)
    all_questions = discover_questions(tasks_dir)
    known_question_ids = {q["id"] for q in all_questions}

    seen_ids: dict[str, str] = {}
    known_task_ids: set[str] = set()
    cached_trees: dict[str, dict[str, TaskNode]] = {str(tasks_dir): tree}
    cached_emergent: dict[str, list[dict[str, Any]]] = {str(tasks_dir): emergent}

    for init in initiatives:
        known_task_ids.add(init["id"])
        for t in init.get("tasks", []):
            known_task_ids.add(t["id"])
        rel_plan = init.get("rel_path")
        if rel_plan and rel_plan.endswith("plan.md"):
            plan_path = tasks_dir / rel_plan
            warnings.extend(plan_format_warnings(plan_path, rel_plan))
            if plan_path.is_file():
                try:
                    p_text = plan_path.read_text(encoding="utf-8")
                    scanned_lines, _ = scan_markdown_blocks(p_text)
                    in_task_sec = False
                    for sline in scanned_lines:
                        if sline.is_fenced:
                            continue
                        if sline.text.startswith("## "):
                            in_task_sec = bool(re.search(r"\b(?:tasks|closed|subtasks)\b", sline.text, re.IGNORECASE))
                        elif in_task_sec and sline.text.startswith("### "):
                            if not INLINE_TASK_HEADING_RE.match(sline.text):
                                errors.append(
                                    f"{rel_plan}: heading {sline.text.strip()!r} in task section does not parse as a task."
                                )
                except OSError:
                    pass

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

    for nid, node in tree.items():
        rel = node.rel_path
        if nid not in seen_ids:
            seen_ids[nid] = rel
        elif seen_ids[nid] != rel:
            errors.append(f"{rel}: duplicate task id {nid!r} (already defined in {seen_ids[nid]}).")
        known_task_ids.add(nid)

        if node.depth > 4:
            warnings.append(f"{rel}: node {nid} depth {node.depth} > 4 (consider turning this subtree into an initiative).")

        if node.is_container and not node.children:
            warnings.append(f"{rel}: empty container {nid} (no children).")

        if node.block_text is not None:
            if not node.in_done and not node.fields.get("goal") and not node.own_fields.get("goal"):
                errors.append(f"{rel}: node {nid} missing required 'Goal'.")

            if node.is_leaf:
                if not node.fields.get("status") and not node.own_fields.get("status") and not node.fields.get("state") and not node.own_fields.get("state"):
                    if node.in_done:
                        warnings.append(f"{rel}: archived leaf node {nid} has no 'Status' (read as done).")
                    else:
                        errors.append(f"{rel}: leaf node {nid} missing required 'Status'.")

        for dep in node.own_depends_on:
            if is_external_task_ref(dep):
                if not parse_external_task_ref(dep):
                    errors.append(f"{rel}: invalid external dependency reference {dep!r}.")
                continue
            if dep not in tree:
                warnings.append(f"{rel}: node {nid} depends on unknown id {dep!r}.")
            elif tree[dep].is_container and not tree[dep].children:
                warnings.append(f"{rel}: node {nid} depends on empty container {dep!r} (dependency will never be satisfied).")

        if node.block_text is not None:
            if "size" in node.own_fields and node.own_fields["size"]:
                s_val = str(node.own_fields["size"]).strip().upper()
                if s_val not in VALID_SIZES:
                    warnings.append(f"{rel}: non-canonical size {node.own_fields['size']!r} on node {nid} (expected one of {sorted(VALID_SIZES)}).")
            if "kind" in node.own_fields and node.own_fields["kind"] and node.own_fields["kind"] != "-":
                k_val = str(node.own_fields["kind"]).strip().lower()
                if k_val not in VALID_KINDS:
                    errors.append(f"{rel}: invalid kind {node.own_fields['kind']!r} on node {nid} (expected one of {sorted(VALID_KINDS)}).")
            if "labels" in node.own_fields and node.own_fields["labels"] and node.own_fields["labels"] != "-":
                raw_l = str(node.own_fields["labels"]).strip()
                for lbl in [l.strip() for l in raw_l.split(",") if l.strip()]:
                    if not LABEL_RE.match(lbl):
                        errors.append(f"{rel}: invalid label {lbl!r} on node {nid} (must match '^[a-z0-9][a-z0-9-]{{0,23}}$').")
            if "short" in node.own_fields and node.own_fields["short"] and str(node.own_fields["short"]).strip() != "-":
                s_val = str(node.own_fields["short"]).strip()
                for v in validate_short_title(s_val):
                    warnings.append(f"{rel}: short title {s_val!r} on node {nid} violates conventions ({v}).")

        if node.is_leaf and node.canonical_state == "waiting":
            raw_wo = node.own_fields.get("waiting_on") or node.own_fields.get("waiting-on") or getattr(node, "waiting_on", None)
            has_wo = bool(raw_wo and str(raw_wo).strip() and str(raw_wo).strip() != "-")
            raw_dec = str(node.own_fields.get("decider") or node.fields.get("decider", {}).get("value") or "").strip()
            has_dec = bool(raw_dec and raw_dec != "-")
            raw_cond = str(node.own_fields.get("conditions") or "").strip()
            has_cond = bool(node.conditions or (raw_cond and raw_cond != "-"))
            if not (has_wo or has_dec or has_cond):
                if not any(f"task {nid} in waiting state has no waiting-on" in w for w in warnings):
                    warnings.append(
                        f"{rel}: task {nid} in waiting state has no waiting-on, decider, or conditions; "
                        f"set --waiting-on <question:Q###|owner:...|external:...|session:...>."
                    )

        # Check conditions on plan task node
        if "conditions" in node.own_fields and node.own_fields["conditions"]:
            raw_cond = str(node.own_fields["conditions"]).strip()
            if raw_cond and raw_cond != "-":
                for qid in parse_conditions_field(raw_cond):
                    if not QUESTION_ID_RE.match(qid):
                        errors.append(f"{rel}: invalid question id {qid!r} in conditions on node {nid}.")
                    elif qid not in known_question_ids:
                        errors.append(f"{rel}: condition question {qid!r} on node {nid} not found in questions/.")

        # Check coordinates on plan task node
        if "coordinates" in node.own_fields and node.own_fields["coordinates"]:
            raw_c = str(node.own_fields["coordinates"]).strip()
            if raw_c and raw_c != "-":
                for ref_str in [c.strip() for c in raw_c.split(",") if c.strip()]:
                    try:
                        parsed_c = parse_qualified_ref(ref_str)
                    except ValueError as ex:
                        errors.append(f"{rel}: invalid coordinates reference {ref_str!r}: {ex}.")
                        continue
                    c_proj = parsed_c.get("project")
                    c_id = parsed_c.get("id")
                    if not c_proj:
                        errors.append(f"{rel}: coordinates reference must be 'project/ID', got {ref_str!r}.")
                        continue
                    p_tasks_dir = resolve_project_tasks_dir(c_proj, tasks_dir)
                    if p_tasks_dir is None:
                        warnings.append(f"{rel}: cannot resolve project '{c_proj}' for coordinates reference '{ref_str}'.")
                        continue
                    if str(p_tasks_dir) not in cached_trees:
                        try:
                            cached_trees[str(p_tasks_dir)] = discover_task_tree(p_tasks_dir)
                        except Exception:
                            cached_trees[str(p_tasks_dir)] = {}
                    if str(p_tasks_dir) not in cached_emergent:
                        try:
                            cached_emergent[str(p_tasks_dir)] = discover_emergent_tasks(p_tasks_dir)
                        except Exception:
                            cached_emergent[str(p_tasks_dir)] = []
                    p_tree = cached_trees[str(p_tasks_dir)]
                    p_emergent = cached_emergent[str(p_tasks_dir)]
                    task_exists = (c_id in p_tree) or any(t["id"] == c_id for t in p_emergent)
                    if not task_exists:
                        warnings.append(f"{rel}: target task '{c_id}' in project '{c_proj}' does not exist.")

        # Check cross-project qualified ref in plan task depends-on
        plan_raw_deps = node.own_fields.get("depends_on") or node.own_fields.get("depends")
        if plan_raw_deps and plan_raw_deps != "-":
            for item in str(plan_raw_deps).split(","):
                clean_item = re.sub(r"\s*\(.*?\)", "", item).strip().strip("`").strip()
                if not clean_item or clean_item == "-":
                    continue
                if is_external_task_ref(clean_item) and not parse_external_task_ref(clean_item):
                    errors.append(
                        f"{node.rel_path}: invalid external dependency reference {clean_item!r}."
                    )

        cstate = node.canonical_state
        if node.in_done and cstate not in TERMINAL_STATES:
            errors.append(f"{rel}: task {nid} is under done/ but state is {node.state!r} (not terminal).")
        if node.in_closed_section and cstate not in TERMINAL_STATES:
            errors.append(f"{rel}: task {nid} is in ## Closed but state is {node.state!r} (not terminal).")
        if node.is_folder and node.parent is not None and not node.in_done and cstate in TERMINAL_STATES:
            warnings.append(f"{rel}: folder child {nid} has terminal state {node.state!r} but has not been moved to done/ (run 'ai-orch tasks archive' to fix).")

    for ce in check_dependency_cycles(tree):
        errors.append(ce)

    for task in emergent:
        tid = task["id"]
        rel = task["rel_path"]
        if not tid:
            errors.append(f"{rel}: missing required 'id' header field.")
        else:
            if not EMERGENT_ID_RE.match(tid):
                errors.append(f"{rel}: invalid emergent task id {tid!r} (expected format T###).")

        # Check filename starts with ID
        target_name = pathlib.Path(task["task_root"]).name
        if tid and not target_name.startswith(f"{tid}-"):
            errors.append(f"{rel}: file/folder name {target_name!r} does not start with '{tid}-'.")

        # Validate header fields & order
        keys = task["header_keys"]
        is_pointer = (task.get("canonical_state") == "moved") or (task.get("state") == "moved") or ("moved-to" in task.get("headers", {}))
        is_micro = (task.get("folder_category") == "micro") or (task.get("category") == "micro")
        is_full_format = ("handoff" in keys and "category" in keys and ("## Goal" in task.get("found_headings", []) or "## Goal" in task.get("sections_present", [])))

        if is_micro and not is_full_format:
            missing_micro = [k for k in MICRO_MANDATORY_HEADER_FIELDS if k not in keys]
            if missing_micro:
                errors.append(f"{rel}: missing mandatory microtask header field(s): {', '.join(missing_micro)}.")

            unknown_keys = [k for k in keys if k not in MICRO_HEADER_FIELDS]
            if unknown_keys:
                errors.append(f"{rel}: unknown microtask header field(s): {', '.join(unknown_keys)}.")

            present_micro = [k for k in keys if k in MICRO_HEADER_FIELDS]
            expected_micro = [k for k in MICRO_HEADER_FIELDS if k in present_micro]
            if present_micro != expected_micro:
                misplaced_m = []
                seen_m = set()
                for k in present_micro:
                    if present_micro.index(k) != expected_micro.index(k) and k not in seen_m:
                        seen_m.add(k)
                        c_idx = MICRO_HEADER_FIELDS.index(k)
                        prec = MICRO_HEADER_FIELDS[c_idx - 1] if c_idx > 0 else None
                        succ = MICRO_HEADER_FIELDS[c_idx + 1] if c_idx + 1 < len(MICRO_HEADER_FIELDS) else None
                        where_str = (f"after '{prec}'" if prec else "") + (f" and before '{succ}'" if prec and succ else (f"before '{succ}'" if succ else ""))
                        misplaced_m.append(f"field '{k}' belongs {where_str}")
                where_msg_m = f" ({'; '.join(misplaced_m)})" if misplaced_m else ""
                errors.append(
                    f"{rel}: microtask header fields out of order: got {present_micro}, expected {expected_micro}. "
                    f"Canonical sequence: {list(MICRO_HEADER_FIELDS)}.{where_msg_m}"
                )

            # Check empty values
            for k in MICRO_MANDATORY_HEADER_FIELDS:
                if k in task["headers"] and task["headers"][k] == "":
                    errors.append(f"{rel}: header field '{k}' cannot be empty (use '-' when empty).")

            # Check kind
            k_val = task["headers"].get("kind", "").strip().lower()
            if not k_val or k_val == "-":
                errors.append(f"{rel}: microtask missing required 'kind' header field.")
            elif k_val not in VALID_KINDS:
                errors.append(f"{rel}: invalid kind {task['headers']['kind']!r} (expected one of {sorted(VALID_KINDS)}).")

            # Priority
            if task["priority"] and task["priority"] not in PRIORITIES:
                errors.append(f"{rel}: invalid priority {task['priority']!r} (expected one of {sorted(PRIORITIES)}).")

            # State
            if not task["state"] or not is_valid_state(task["state"]):
                errors.append(
                    f"{rel}: invalid state {task['state']!r} (expected one of {sorted(CANONICAL_STATES)})."
                )

            # Done placement consistency
            cstate = task["canonical_state"]
            if task["in_done"] and cstate not in TERMINAL_STATES:
                errors.append(f"{rel}: task is under done/ but state is {task['state']!r} (not terminal).")
            if not task["in_done"] and cstate in TERMINAL_STATES and cstate != "moved":
                warnings.append(f"{rel}: task has terminal state {task['state']!r} but has not been moved to done/ (run 'ai-orch tasks archive' to fix).")

            # Size (optional)
            if "size" in task.get("headers", {}) and task["headers"]["size"] and task["headers"]["size"] != "-":
                s_val = task["headers"]["size"].strip().upper()
                if s_val not in VALID_SIZES:
                    errors.append(f"{rel}: invalid size {task['headers']['size']!r} (expected one of {sorted(VALID_SIZES)}).")

            # Labels (optional)
            raw_labels = task["headers"].get("labels", "").strip()
            if raw_labels and raw_labels != "-":
                for lbl in [l.strip() for l in raw_labels.split(",") if l.strip()]:
                    if not LABEL_RE.match(lbl):
                        errors.append(f"{rel}: invalid label {lbl!r} (must match '^[a-z0-9][a-z0-9-]{{0,23}}$').")

            # Short title (optional)
            if "short" in task.get("headers", {}) and task["headers"]["short"] and task["headers"]["short"] != "-":
                s_val = task["headers"]["short"].strip()
                for v in validate_short_title(s_val):
                    warnings.append(f"{rel}: microtask short title {s_val!r} violates conventions ({v}).")

            # Required section: ## What
            if "## What" not in task.get("found_headings", []):
                errors.append(f"{rel}: missing required Markdown section '## What'.")

        else:
            if not is_pointer:
                missing_core = [k for k in CORE_HEADER_FIELDS if k not in keys]
                if missing_core:
                    errors.append(f"{rel}: missing mandatory header field(s): {', '.join(missing_core)}.")

            unknown_keys = [k for k in keys if k not in ALL_ALLOWED_HEADER_FIELDS]
            if unknown_keys:
                errors.append(f"{rel}: unknown header field(s): {', '.join(unknown_keys)}.")

            # Check exact ordering of CORE_HEADER_FIELDS and optional extension fields after handoff
            if not is_pointer:
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
                present_ext = [k for k in keys if k in OPTIONAL_EXTENSION_FIELDS and keys.index(k) > handoff_pos]
                expected_ext = [k for k in OPTIONAL_EXTENSION_FIELDS if k in present_ext]
                if present_ext != expected_ext:
                    misplaced = []
                    seen_misplaced = set()
                    for k in present_ext:
                        if present_ext.index(k) != expected_ext.index(k) and k not in seen_misplaced:
                            seen_misplaced.add(k)
                            c_idx = OPTIONAL_EXTENSION_FIELDS.index(k)
                            prec = OPTIONAL_EXTENSION_FIELDS[c_idx - 1] if c_idx > 0 else "handoff"
                            succ = OPTIONAL_EXTENSION_FIELDS[c_idx + 1] if c_idx + 1 < len(OPTIONAL_EXTENSION_FIELDS) else None
                            where_str = f"after '{prec}'" + (f" and before '{succ}'" if succ else "")
                            misplaced.append(f"field '{k}' belongs {where_str}")
                    where_msg = f" ({'; '.join(misplaced)})" if misplaced else ""
                    errors.append(
                        f"{rel}: optional header fields out of order: got {present_ext}, expected {expected_ext}. "
                        f"Canonical sequence: {list(OPTIONAL_EXTENSION_FIELDS)}.{where_msg}"
                    )

            # Check empty values
            if not is_pointer:
                for k in CORE_HEADER_FIELDS:
                    if k in task["headers"] and task["headers"][k] == "":
                        errors.append(f"{rel}: header field '{k}' cannot be empty (use '-' when empty).")

            # Category match
            if not is_pointer:
                if task["category"] and task["folder_category"] and task["category"] != task["folder_category"]:
                    errors.append(
                        f"{rel}: header category {task['category']!r} does not match folder {task['folder_category']!r}."
                    )

            # Priority
            if task["priority"] and task["priority"] not in PRIORITIES:
                errors.append(f"{rel}: invalid priority {task['priority']!r} (expected one of {sorted(PRIORITIES)}).")

            if not is_pointer:
                if not task["priority_reason"] or task["priority_reason"] == "-":
                    errors.append(f"{rel}: 'priority-reason' must be a non-empty explanation.")

            # next-up
            if not is_pointer:
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
            if not task["in_done"] and cstate in TERMINAL_STATES and cstate != "moved":
                warnings.append(f"{rel}: task has terminal state {task['state']!r} but has not been moved to done/ (run 'ai-orch tasks archive' to fix).")

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
            if "size" in task.get("headers", {}) and task["headers"]["size"] and task["headers"]["size"] != "-":
                s_val = task["headers"]["size"].strip().upper()
                if s_val not in VALID_SIZES:
                    errors.append(f"{rel}: invalid size {task['headers']['size']!r} (expected one of {sorted(VALID_SIZES)}).")

            if "kind" in task.get("headers", {}) and task["headers"]["kind"] and task["headers"]["kind"] != "-":
                k_val = task["headers"]["kind"].strip().lower()
                if k_val not in VALID_KINDS:
                    errors.append(f"{rel}: invalid kind {task['headers']['kind']!r} (expected one of {sorted(VALID_KINDS)}).")

            raw_labels = task["headers"].get("labels", "").strip()
            if raw_labels and raw_labels != "-":
                for lbl in [l.strip() for l in raw_labels.split(",") if l.strip()]:
                    if not LABEL_RE.match(lbl):
                        errors.append(f"{rel}: invalid label {lbl!r} (must match '^[a-z0-9][a-z0-9-]{{0,23}}$').")

            # Short title (optional)
            if "short" in task.get("headers", {}) and task["headers"]["short"] and task["headers"]["short"] != "-":
                s_val = task["headers"]["short"].strip()
                for v in validate_short_title(s_val):
                    warnings.append(f"{rel}: short title {s_val!r} violates conventions ({v}).")

            # moved-to header validation
            if "moved-to" in task.get("headers", {}):
                raw_mt = task["headers"]["moved-to"].strip()
                if raw_mt and raw_mt != "-":
                    try:
                        parsed_mt = parse_qualified_ref(raw_mt)
                        if not parsed_mt.get("project"):
                            errors.append(f"{rel}: moved-to reference must be 'project/ID', got {raw_mt!r}.")
                    except ValueError as ex:
                        errors.append(f"{rel}: invalid moved-to reference {raw_mt!r}: {ex}.")

            # coordinates header validation
            if "coordinates" in task.get("headers", {}):
                raw_c = task["headers"]["coordinates"].strip()
                if raw_c and raw_c != "-":
                    for ref_str in [c.strip() for c in raw_c.split(",") if c.strip()]:
                        try:
                            parsed_c = parse_qualified_ref(ref_str)
                        except ValueError as ex:
                            errors.append(f"{rel}: invalid coordinates reference {ref_str!r}: {ex}.")
                            continue
                        c_proj = parsed_c.get("project")
                        c_id = parsed_c.get("id")
                        if not c_proj:
                            errors.append(f"{rel}: coordinates reference must be 'project/ID', got {ref_str!r}.")
                            continue
                        p_tasks_dir = resolve_project_tasks_dir(c_proj, tasks_dir)
                        if p_tasks_dir is None:
                            warnings.append(f"{rel}: cannot resolve project '{c_proj}' for coordinates reference '{ref_str}'.")
                            continue
                        if str(p_tasks_dir) not in cached_trees:
                            try:
                                cached_trees[str(p_tasks_dir)] = discover_task_tree(p_tasks_dir)
                            except Exception:
                                cached_trees[str(p_tasks_dir)] = {}
                        if str(p_tasks_dir) not in cached_emergent:
                            try:
                                cached_emergent[str(p_tasks_dir)] = discover_emergent_tasks(p_tasks_dir)
                            except Exception:
                                cached_emergent[str(p_tasks_dir)] = []
                        p_tree = cached_trees[str(p_tasks_dir)]
                        p_emergent = cached_emergent[str(p_tasks_dir)]
                        task_exists = (c_id in p_tree) or any(t["id"] == c_id for t in p_emergent)
                        if not task_exists:
                            warnings.append(f"{rel}: target task '{c_id}' in project '{c_proj}' does not exist.")

            # cross-project depends-on validation
            raw_deps = task["headers"].get("depends-on")
            if raw_deps and raw_deps != "-":
                for item in str(raw_deps).split(","):
                    clean_item = re.sub(r"\s*\(.*?\)", "", item).strip().strip("`").strip()
                    if not clean_item or clean_item == "-":
                        continue
                    if is_external_task_ref(clean_item) and not parse_external_task_ref(clean_item):
                        errors.append(
                            f"{rel}: invalid external dependency reference {clean_item!r}."
                        )

            # conditions validation
            if "conditions" in task.get("headers", {}):
                raw_cond = str(task["headers"]["conditions"]).strip()
                if raw_cond and raw_cond != "-":
                    for qid in parse_conditions_field(raw_cond):
                        if not QUESTION_ID_RE.match(qid):
                            errors.append(f"{rel}: invalid question id {qid!r} in conditions.")
                        elif qid not in known_question_ids:
                            errors.append(f"{rel}: condition question {qid!r} not found in questions/.")

            # Legacy decider warning
            raw_dec = task.get("decider", "").strip()
            if raw_dec and raw_dec != "-":
                if not re.match(r"^Q\d{3,}(?:,\s*Q\d{3,})*$", raw_dec):
                    warnings.append(
                        f"{rel}: legacy free-text decider {raw_dec!r}; "
                        f"consider converting with 'questions ask --from-task {tid}'."
                    )

            # Check waiting tasks have qualifier, decider, or conditions
            cstate = task.get("canonical_state") or normalize_state(task.get("state", "open"))
            if cstate == "waiting":
                raw_wo = task.get("headers", {}).get("waiting-on") or task.get("headers", {}).get("waiting_on") or task.get("waiting_on")
                has_wo = bool(raw_wo and str(raw_wo).strip() and str(raw_wo).strip() != "-")
                has_dec = bool(raw_dec and raw_dec != "-")
                raw_cond = task.get("conditions_raw", "") or task.get("headers", {}).get("conditions", "")
                has_cond = bool(task.get("conditions") or (raw_cond and str(raw_cond).strip() != "-"))
                if not (has_wo or has_dec or has_cond):
                    warnings.append(
                        f"{rel}: task {tid} in waiting state has no waiting-on, decider, or conditions; "
                        f"set --waiting-on <question:Q###|owner:...|external:...|session:...>."
                    )

            # Required sections
            if not is_pointer:
                missing_sections = [s for s in REQUIRED_SECTIONS if s not in task["sections_present"]]
                if missing_sections:
                    errors.append(f"{rel}: missing required Markdown section(s): {', '.join(missing_sections)}.")

                if not is_micro:
                    cstate = task.get("canonical_state") or normalize_state(task.get("state", "open"))
                    is_active_or_terminal = cstate in ("in progress", "delivered", "verified", "done", "done with a caveat")

                    for ph in task.get("step_placeholders", []):
                        if is_active_or_terminal:
                            errors.append(f"{rel}: task in state {task['state']!r} contains unedited placeholder in ## Steps: {ph!r}.")
                        else:
                            warnings.append(f"{rel}: task contains unedited placeholder in ## Steps: {ph!r}.")

                    for ph in task.get("verification_placeholders", []):
                        if is_active_or_terminal:
                            errors.append(f"{rel}: task in state {task['state']!r} contains unedited placeholder in ## Verification: {ph!r}.")
                        else:
                            warnings.append(f"{rel}: task contains unedited placeholder in ## Verification: {ph!r}.")

    # Validate dependency DAG acyclicity & valid dependency references
    adj: dict[str, list[str]] = {}
    for task in emergent:
        tid = task["id"]
        if not tid:
            continue
        deps_for_tid = adj.setdefault(tid, [])
        for dep in task["depends_on"]:
            if is_external_task_ref(dep):
                if not parse_external_task_ref(dep):
                    errors.append(f"{task['rel_path']}: invalid depends-on reference {dep!r}.")
                continue
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

    # Warn if .ai-orch.lock is not ignored by git when inside a git repository
    lock_file = tasks_dir / ".ai-orch.lock"
    try:
        res = subprocess.run(
            ["git", "check-ignore", "-q", str(lock_file)],
            cwd=str(tasks_dir),
            capture_output=True,
            check=False,
        )
        if res.returncode == 1:
            warnings.append(
                f"{lock_file.name} is not ignored by git in {tasks_dir}. "
                "Add '.ai-orch.lock' to .gitignore to avoid committing the lock file."
            )
    except (FileNotFoundError, OSError):
        pass

    # Validate question files
    questions_dir = tasks_dir / "questions"
    emergent_map = {t["id"]: t for t in emergent}
    seen_q_ids: dict[str, str] = {}

    # Warn on legacy un-normalized initiative plans (11.5)
    for init in initiatives:
        if init.get("legacy"):
            warnings.append(
                f"Initiative #{init['id']} ({init['slug']}) has no canonical task blocks; "
                f"found {len(init['tasks'])} candidate legacy task(s) in plan.md. "
                "Consider normalizing task blocks into canonical format."
            )

    if questions_dir.is_dir():
        applied_map: dict[str, dict[str, Any]] = {}
        ledger_file = questions_dir / "applied.jsonl"
        if ledger_file.is_file():
            try:
                for line in ledger_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        if isinstance(rec, dict) and "question" in rec:
                            applied_map[rec["question"]] = rec
            except Exception:
                pass

        for q_entry in sorted(questions_dir.rglob("*.md")):
            if q_entry.name.startswith(".") or not q_entry.is_file():
                continue
            q_rel = q_entry.relative_to(tasks_dir).as_posix()

            # Filename check
            fm = QUESTION_FILE_RE.match(q_entry.name)
            if not fm:
                errors.append(f"{q_rel}: invalid question filename {q_entry.name!r} (expected format Q###-<slug>.md).")

            try:
                q = parse_question_file(q_entry, tasks_dir)
            except Exception as e:
                errors.append(f"{q_rel}: failed to parse question file: {e}")
                continue

            qid = q["id"]
            if not qid:
                errors.append(f"{q_rel}: missing required 'id' header field.")
            else:
                if not QUESTION_ID_RE.match(qid):
                    errors.append(f"{q_rel}: invalid question id {qid!r} (expected format Q###).")
                if fm and fm.group(1) != qid:
                    errors.append(f"{q_rel}: id header {qid!r} does not match filename prefix {fm.group(1)!r}.")
                if qid in seen_q_ids:
                    errors.append(f"{q_rel}: duplicate question id {qid!r} (already defined in {seen_q_ids[qid]}).")
                else:
                    seen_q_ids[qid] = q_rel

            # Validate header fields & order
            keys = q["header_keys"]
            missing_q_hdr = [k for k in QUESTION_MANDATORY_HEADER_FIELDS if k not in keys]
            if missing_q_hdr:
                errors.append(f"{q_rel}: missing mandatory header field(s): {', '.join(missing_q_hdr)}.")

            unknown_q_hdr = [k for k in keys if k not in QUESTION_HEADER_FIELDS]
            if unknown_q_hdr:
                errors.append(f"{q_rel}: unknown header field(s): {', '.join(unknown_q_hdr)}.")

            expected_order = [k for k in QUESTION_HEADER_FIELDS if k in keys]
            if keys != expected_order:
                errors.append(f"{q_rel}: header fields out of order: got {keys}, expected {list(QUESTION_HEADER_FIELDS)}.")

            # Check empty values
            for k in QUESTION_HEADER_FIELDS:
                if k in q["headers"] and q["headers"][k] == "":
                    errors.append(f"{q_rel}: header field '{k}' cannot be empty (use '-' when empty).")

            # Short title (optional)
            if "short" in q.get("headers", {}) and q["headers"]["short"] and q["headers"]["short"] != "-":
                s_val = q["headers"]["short"].strip()
                for v in validate_short_title(s_val):
                    warnings.append(f"{q_rel}: question short title {s_val!r} violates conventions ({v}).")

            # Question text
            q_text = q["question"]
            if not q_text:
                errors.append(f"{q_rel}: 'question' header field cannot be empty.")
            else:
                if "\n" in q_text:
                    errors.append(f"{q_rel}: 'question' must be a single line.")
                if len(q_text) > 160:
                    errors.append(f"{q_rel}: 'question' text exceeds 160 characters ({len(q_text)} chars).")
                if not q_text.endswith("?"):
                    errors.append(f"{q_rel}: 'question' must end with '?'.")

            # Status
            st = q["status"]
            if st not in QUESTION_STATUSES:
                errors.append(f"{q_rel}: invalid status {st!r} (expected one of {sorted(QUESTION_STATUSES)}).")

            # Asked date
            asked_date = q["asked"]
            if asked_date and asked_date != "-":
                try:
                    datetime.date.fromisoformat(asked_date)
                except ValueError:
                    errors.append(f"{q_rel}: invalid ISO date for 'asked': {asked_date!r}.")

            # Open answer
            oa = q["open_answer"]
            if oa not in ("yes", "no"):
                errors.append(f"{q_rel}: invalid open-answer {oa!r} (expected 'yes' or 'no').")

            # Required sections and order
            core_sections = ["## Context", "## Options", "## Answer"]
            allowed_sections = {"## Context", "## Options", "## Answer", "## Notes", "## Free notes", "## Discussion"}
            present_secs = q["sections_present"]

            missing_core = [s for s in core_sections if s not in present_secs]
            if missing_core:
                errors.append(f"{q_rel}: missing required section(s): {', '.join(missing_core)}.")

            unknown_secs = [s for s in present_secs if s not in allowed_sections]
            if unknown_secs:
                errors.append(
                    f"{q_rel}: unexpected section(s): {', '.join(unknown_secs)} (allowed: Context, Options, Answer, and optional Notes)."
                )

            core_present = [s for s in present_secs if s in core_sections]
            if core_present != core_sections:
                errors.append(
                    f"{q_rel}: core sections out of order: got {core_present}, expected {core_sections}."
                )

            # Context
            ctx = q["context"]
            if not ctx:
                errors.append(f"{q_rel}: '## Context' section cannot be empty.")
            elif "Converted from the legacy decider header of " in ctx and "context to be completed by the owner." in ctx:
                warnings.append(f"{q_rel}: context-not-completed (converted from legacy decider).")

            # Options
            opts = q["options"]
            labels = [opt["label"] for opt in opts if opt["label"]]
            if len(labels) != len(set(labels)):
                errors.append(f"{q_rel}: duplicate option labels: {labels}.")

            for opt in opts:
                if "(recommended)" in opt["raw"].lower():
                    errors.append(f"{q_rel}: option bullet contains '(recommended)' marker: {opt['raw']!r}.")
                if not opt["label"]:
                    errors.append(f"{q_rel}: invalid option bullet format: {opt['raw']!r}.")

            if oa == "no":
                if len(opts) < 2:
                    errors.append(f"{q_rel}: at least 2 options required when open-answer is 'no' (got {len(opts)}).")
            elif oa == "yes":
                if len(opts) == 1:
                    errors.append(f"{q_rel}: options must be empty (pure open question) or have at least 2 options (got 1).")

            # Recommended
            rec = q["recommended"]
            if len(opts) == 0:
                if rec != "-":
                    errors.append(f"{q_rel}: recommended must be '-' when options are empty (got {rec!r}).")
            else:
                if rec != "-" and rec not in labels:
                    errors.append(f"{q_rel}: recommended option {rec!r} not found in options {labels}.")

            # Answer consistency
            ans = q["answer"]
            choice = ans["choice"]
            ans_by = ans["answered_by"]
            ans_date = ans["answered"]
            ans_text = ans["text"]

            if st == "open":
                if choice != "-":
                    errors.append(f"{q_rel}: status is 'open' but choice is {choice!r} (expected '-').")
                if ans_by != "-":
                    errors.append(f"{q_rel}: status is 'open' but answered-by is {ans_by!r} (expected '-').")
                if ans_date != "-":
                    errors.append(f"{q_rel}: status is 'open' but answered is {ans_date!r} (expected '-').")
                if ans_text is not None and ans_text.strip():
                    errors.append(f"{q_rel}: status is 'open' but answer contains free text.")
            elif st == "answered":
                if choice == "open":
                    if oa != "yes":
                        errors.append(f"{q_rel}: choice is 'open' but open-answer is 'no'.")
                    if not ans_text or not ans_text.strip():
                        errors.append(f"{q_rel}: choice is 'open' requires a non-empty text block.")
                elif choice in labels:
                    pass
                else:
                    errors.append(f"{q_rel}: invalid choice {choice!r} (expected one of {labels} or 'open').")
                if ans_by in ("", "-"):
                    errors.append(f"{q_rel}: answered question requires answered-by.")
                if ans_date in ("", "-"):
                    errors.append(f"{q_rel}: answered question requires answered date.")
                else:
                    try:
                        datetime.date.fromisoformat(ans_date)
                    except ValueError:
                        errors.append(f"{q_rel}: invalid ISO date for 'answered': {ans_date!r}.")
                hdr_app = (q["headers"].get("applied") or "-").strip().lower()
                is_applied = (hdr_app == "yes") or (qid in applied_map)
                if not is_applied:
                    st_title = q.get("short_title") or derive_short_title(q.get("title") or q["question"])
                    warnings.append(
                        f"{q_rel}: answered question {qid} ({st_title}) has not been applied (run 'ai-orch questions apply {qid} --note \"...\"' to record application)."
                    )
            elif st == "withdrawn":
                if choice != "withdrawn":
                    errors.append(f"{q_rel}: status is 'withdrawn' but choice is {choice!r} (expected 'withdrawn').")
                if ans_by in ("", "-"):
                    errors.append(f"{q_rel}: withdrawn question requires answered-by.")
                if ans_date in ("", "-"):
                    errors.append(f"{q_rel}: withdrawn question requires answered date.")
                else:
                    try:
                        datetime.date.fromisoformat(ans_date)
                    except ValueError:
                        errors.append(f"{q_rel}: invalid ISO date for 'answered': {ans_date!r}.")
                if not ans_text or not ans_text.strip():
                    errors.append(f"{q_rel}: withdrawn question requires reason in text block.")
            elif st == "moved":
                if not q["headers"].get("moved-to") or q["headers"]["moved-to"].strip() == "-":
                    errors.append(f"{q_rel}: status is 'moved' but missing required 'moved-to' header.")
                if choice != "moved":
                    errors.append(f"{q_rel}: status is 'moved' but choice is {choice!r} (expected 'moved').")
                if ans_by in ("", "-"):
                    errors.append(f"{q_rel}: moved question requires answered-by.")
                if ans_date in ("", "-"):
                    errors.append(f"{q_rel}: moved question requires answered date.")
                else:
                    try:
                        datetime.date.fromisoformat(ans_date)
                    except ValueError:
                        errors.append(f"{q_rel}: invalid ISO date for 'answered': {ans_date!r}.")

            # Blocks & status consistency
            for tid, prior_st in q["blocks_parsed"]:
                if not TASK_NODE_ID_RE.match(tid):
                    errors.append(f"{q_rel}: invalid task ID {tid!r} in blocks.")
                elif tid not in tree:
                    errors.append(f"{q_rel}: blocked task {tid!r} not found in tasks tree.")
                elif not tree[tid].is_leaf:
                    errors.append(f"{q_rel}: cannot block container {tid!r} (questions can only block leaf tasks).")
                else:
                    target_task = tree[tid]
                    target_st = target_task.canonical_state
                    target_dec = target_task.fields.get("decider", {}).get("value", "") or target_task.own_fields.get("decider", "")
                    if st == "open":
                        if target_st != "waiting":
                            errors.append(
                                f"{q_rel}: question is 'open' but blocked task {tid!r} is in state {target_task.state!r} (expected 'waiting')."
                            )
                        if qid and qid not in re.findall(r"Q\d{3,}", target_dec):
                            errors.append(
                                f"{q_rel}: question is 'open' but task {tid!r} decider {target_dec!r} does not reference {qid}."
                            )
                    else:
                        target_dec_qids = re.findall(r"Q\d{3,}", target_dec)
                        if target_st != "waiting" and qid in target_dec_qids:
                            errors.append(
                                f"{q_rel}: question is resolved ({st}) and task {tid!r} is '{target_task.state}', but task decider still references {qid}."
                            )

    # Validate use cases
    uc_dir = tasks_dir / "use-cases"
    seen_uc_ids: dict[str, str] = {}
    if uc_dir.is_dir():
        for uc_entry in sorted(uc_dir.iterdir()):
            if uc_entry.name.startswith(".") or not uc_entry.is_file() or uc_entry.suffix != ".md":
                continue
            uc_rel = uc_entry.relative_to(tasks_dir).as_posix()
            try:
                uc = parse_use_case_file(uc_entry, tasks_dir)
            except Exception as e:
                errors.append(f"{uc_rel}: failed to parse use case file: {e}")
                continue

            ucid = uc["id"]
            if not ucid:
                errors.append(f"{uc_rel}: missing required 'id' header field.")
            else:
                if not USE_CASE_ID_RE.match(ucid):
                    errors.append(f"{uc_rel}: invalid use case id {ucid!r} (expected format UC###).")
                if ucid in seen_uc_ids:
                    errors.append(f"{uc_rel}: duplicate use case id {ucid!r} (already defined in {seen_uc_ids[ucid]}).")
                else:
                    seen_uc_ids[ucid] = uc_rel

            st = uc.get("status", "draft")
            if st not in USE_CASE_STATUSES:
                errors.append(f"{uc_rel}: invalid use case status {st!r} (allowed: {sorted(USE_CASE_STATUSES)}).")

            prio = uc.get("priority", "P1")
            if prio not in PRIORITIES:
                errors.append(f"{uc_rel}: invalid priority {prio!r} (allowed: {sorted(PRIORITIES)}).")

            vt = uc.get("verification_type", "automated-probe")
            if vt not in USE_CASE_VERIFICATION_TYPES:
                errors.append(f"{uc_rel}: invalid verification-type {vt!r} (allowed: {sorted(USE_CASE_VERIFICATION_TYPES)}).")

            # Short title (optional)
            if "short" in uc.get("headers", {}) and uc["headers"]["short"] and uc["headers"]["short"] != "-":
                s_val = uc["headers"]["short"].strip()
                for v in validate_short_title(s_val):
                    warnings.append(f"{uc_rel}: use case short title {s_val!r} violates conventions ({v}).")

            for ltid in uc.get("linked_tasks", []):
                if ltid not in tree:
                    warnings.append(f"{uc_rel}: linked task {ltid!r} not found in tasks tree.")

    # Warn if a task references an unknown use case
    for nid, node in tree.items():
        fields = node.own_fields or {}
        uc_refs = fields.get("use-cases") or fields.get("use_cases")
        if uc_refs and uc_refs != "-":
            for ref in [r.strip() for r in str(uc_refs).split(",") if r.strip()]:
                if ref not in seen_uc_ids:
                    warnings.append(f"{node.rel_path}: task references unknown use case {ref!r}.")

    # Placement warnings (Requirement 3)
    is_ws, ws_projects = is_workspace_task_tree(tasks_dir)
    if is_ws:
        for task in emergent:
            if task.get("canonical_state") == "moved" or task.get("moved_to"):
                continue
            rel = task["rel_path"]
            raw_c = task["headers"].get("coordinates", "")
            has_coords = raw_c and raw_c.strip() and raw_c.strip() != "-"
            if has_coords:
                projs = set()
                for c in raw_c.split(","):
                    c_s = c.strip()
                    if c_s:
                        try:
                            parsed_c = parse_qualified_ref(c_s)
                            if parsed_c.get("project"):
                                projs.add(parsed_c["project"])
                        except ValueError:
                            pass
                if len(projs) == 1:
                    single_p = next(iter(projs))
                    warnings.append(f"{rel}: belongs in project {single_p}; use tasks move.")
            else:
                raw_paths = task["headers"].get("paths", "")
                if raw_paths and raw_paths.strip() and raw_paths.strip() != "-":
                    paths_list = [p.strip() for p in raw_paths.split(",") if p.strip() and p.strip() != "-"]
                    if paths_list:
                        for p in ws_projects:
                            p_slug = p.get("slug")
                            if not p_slug or p_slug == "_workspace":
                                continue
                            p_path = p.get("path", "").strip("/")
                            if not p_path:
                                continue
                            def _is_inside(fpath: str, pdir: str) -> bool:
                                norm_f = os.path.normpath(fpath).replace("\\", "/")
                                norm_p = os.path.normpath(pdir).replace("\\", "/")
                                return norm_f == norm_p or norm_f.startswith(norm_p + "/")
                            if all(_is_inside(pth, p_path) for pth in paths_list):
                                warnings.append(f"{rel}: belongs in project {p_slug}; use tasks move.")
                                break

        for nid, node in tree.items():
            if not node.is_leaf or nid.startswith("T"):
                continue
            rel = node.rel_path
            raw_c = str(node.own_fields.get("coordinates", ""))
            has_coords = raw_c and raw_c.strip() and raw_c.strip() != "-"
            if has_coords:
                projs = set()
                for c in raw_c.split(","):
                    c_s = c.strip()
                    if c_s:
                        try:
                            parsed_c = parse_qualified_ref(c_s)
                            if parsed_c.get("project"):
                                projs.add(parsed_c["project"])
                        except ValueError:
                            pass
                if len(projs) == 1:
                    single_p = next(iter(projs))
                    warnings.append(f"{rel}: belongs in project {single_p}; use tasks move.")
            else:
                raw_paths = str(node.fields.get("paths", {}).get("value") or node.own_fields.get("paths", ""))
                if raw_paths and raw_paths.strip() and raw_paths.strip() != "-":
                    paths_list = [p.strip() for p in raw_paths.split(",") if p.strip() and p.strip() != "-"]
                    if paths_list:
                        for p in ws_projects:
                            p_slug = p.get("slug")
                            if not p_slug or p_slug == "_workspace":
                                continue
                            p_path = p.get("path", "").strip("/")
                            if not p_path:
                                continue
                            def _is_inside_node(fpath: str, pdir: str) -> bool:
                                norm_f = os.path.normpath(fpath).replace("\\", "/")
                                norm_p = os.path.normpath(pdir).replace("\\", "/")
                                return norm_f == norm_p or norm_f.startswith(norm_p + "/")
                            if all(_is_inside_node(pth, p_path) for pth in paths_list):
                                warnings.append(f"{rel}: belongs in project {p_slug}; use tasks move.")
                                break

    idx_file = tasks_dir / "00-INDEX.md"
    if idx_file.is_file():
        try:
            idx_text = idx_file.read_text(encoding="utf-8")
            if "<<<<<<<" in idx_text or re.search(r"^(<{7}|={7}|>{7})\b", idx_text, re.MULTILINE):
                errors.append(
                    "00-INDEX.md contains unresolved git conflict markers; run 'ai-orch tasks sync-index --apply' to resolve automatically."
                )
        except OSError:
            pass

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
    new_state: str | None,
    verifier: str | None = None,
    verify_by: str | None = None,
    clear_verify_by: bool = False,
    verify_check: str | None = None,
    decider: str | None = None,
    clear_next_up: bool = False,
    conditions: str | None = None,
    waiting_on: str | None = None,
    clear_waiting_on: bool = False,
) -> None:
    if waiting_on is not None:
        waiting_on = normalize_waiting_on(waiting_on)
    if new_state is not None:
        cstate_check = normalize_state(new_state)
        if cstate_check != "waiting" and waiting_on is None:
            clear_waiting_on = True

    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    h1_idx = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
    idx = h1_idx + 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    header_end = idx
    verifier_line_idx: int | None = None
    verify_by_line_idx: int | None = None
    conditions_line_idx: int | None = None
    waiting_on_line_idx: int | None = None
    handoff_line_idx: int | None = None

    while header_end < len(lines):
        m = HEADER_LINE_RE.match(lines[header_end])
        if not m:
            break
        key = m.group(1)
        if key == "state" and new_state is not None:
            lines[header_end] = f"- state: {new_state}"
        elif key == "decider" and decider is not None:
            lines[header_end] = f"- decider: {decider}"
        elif key == "conditions" and conditions is not None:
            conditions_line_idx = header_end
            lines[header_end] = f"- conditions: {conditions}"
        elif key in ("waiting-on", "waiting_on"):
            if clear_waiting_on or (waiting_on is not None and waiting_on.strip() in ("", "-")):
                del lines[header_end]
                continue
            elif waiting_on is not None:
                lines[header_end] = f"- waiting-on: {waiting_on}"
                waiting_on_line_idx = header_end
            else:
                waiting_on_line_idx = header_end
        elif key in ("verify-by", "verify_by"):
            verify_by_line_idx = header_end
            if clear_verify_by or (verify_by is not None and verify_by.strip() in ("", "-")):
                del lines[header_end]
                continue
            elif verify_by is not None:
                lines[header_end] = f"- verify-by: {verify_by}"
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
        insert_pos = header_end
        fields_after_verifier = {"verify-by", "verify_by", "size", "kind", "labels", "branch", "worktree", "run-id", "use-cases", "use_cases", "coordinates", "moved-to", "conditions", "waiting-on", "waiting_on", "short"}
        for i in range(handoff_line_idx + 1, header_end):
            m_key = HEADER_LINE_RE.match(lines[i])
            if m_key and m_key.group(1) in fields_after_verifier:
                insert_pos = i
                break
        lines.insert(insert_pos, f"- verifier: {verifier}")
        header_end += 1
        if verify_by_line_idx is not None and insert_pos <= verify_by_line_idx:
            verify_by_line_idx += 1

    if verify_by is not None and not clear_verify_by and verify_by.strip() not in ("", "-") and verify_by_line_idx is None and handoff_line_idx is not None:
        insert_pos = header_end
        fields_after_verify_by = {"size", "kind", "labels", "branch", "worktree", "run-id", "use-cases", "use_cases", "coordinates", "moved-to", "conditions", "waiting-on", "waiting_on", "short"}
        for i in range(handoff_line_idx + 1, header_end):
            m_key = HEADER_LINE_RE.match(lines[i])
            if m_key and m_key.group(1) in fields_after_verify_by:
                insert_pos = i
                break
        lines.insert(insert_pos, f"- verify-by: {verify_by}")
        header_end += 1

    if conditions is not None and conditions_line_idx is None and handoff_line_idx is not None:
        insert_pos = header_end
        fields_after_conditions = {"waiting-on", "waiting_on", "short"}
        for i in range(handoff_line_idx + 1, header_end):
            m_key = HEADER_LINE_RE.match(lines[i])
            if m_key and m_key.group(1) in fields_after_conditions:
                insert_pos = i
                break
        lines.insert(insert_pos, f"- conditions: {conditions}")
        header_end += 1

    if waiting_on is not None and not clear_waiting_on and waiting_on_line_idx is None and handoff_line_idx is not None and waiting_on.strip() not in ("", "-"):
        insert_pos = header_end
        fields_after_waiting_on = {"short"}
        for i in range(handoff_line_idx + 1, header_end):
            m_key = HEADER_LINE_RE.match(lines[i])
            if m_key and m_key.group(1) in fields_after_waiting_on:
                insert_pos = i
                break
        lines.insert(insert_pos, f"- waiting-on: {waiting_on}")
        header_end += 1

    # Manage `verification pending:` line right after header
    eff_state = new_state
    if eff_state is None:
        for ln in lines:
            m_st = HEADER_LINE_RE.match(ln)
            if m_st and m_st.group(1) == "state":
                eff_state = m_st.group(2).strip()
                break
    cstate = normalize_state(eff_state) if eff_state else ""
    scan_idx = header_end
    while scan_idx < len(lines) and not lines[scan_idx].strip():
        scan_idx += 1

    has_vp_line = (
        scan_idx < len(lines)
        and lines[scan_idx].strip().lower().startswith("verification pending:")
    )
    if cstate == "delivered" or (verify_by is not None and verify_by.strip() not in ("", "-") and new_state is None):
        eff_vb = verify_by
        if not eff_vb:
            for ln in lines:
                m_vb = HEADER_LINE_RE.match(ln)
                if m_vb and m_vb.group(1) in ("verify-by", "verify_by"):
                    eff_vb = m_vb.group(2).strip()
                    break
        if eff_vb and eff_vb != "-":
            curr_check = None
            if has_vp_line:
                curr_vp_text = lines[scan_idx].strip().split(":", 1)[1].strip()
                m_vpre = re.sub(r"\s*\([^)]*\)", "", curr_vp_text).strip()
                if m_vpre and m_vpre != "run Verification checks":
                    curr_check = m_vpre
            check_str = verify_check or curr_check or "run Verification checks"
            vp_line = f"verification pending: {check_str} (verify-by: {eff_vb})"
        else:
            vp_target = verifier or "independent verifier"
            vp_line = f"verification pending: run Verification checks ({vp_target})"
        if has_vp_line:
            lines[scan_idx] = vp_line
        else:
            lines.insert(header_end, "")
            lines.insert(header_end + 1, vp_line)
    elif has_vp_line and (new_state is not None and cstate != "delivered"):
        # Remove `verification pending:` line once no longer in `delivered`
        del lines[scan_idx]
        if scan_idx < len(lines) and not lines[scan_idx].strip() and scan_idx > 0 and not lines[scan_idx - 1].strip():
            del lines[scan_idx]

    _atomic_write_text(file_path, "\n".join(lines).rstrip() + "\n", encoding="utf-8")


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
    if progress_path is None:
        if (file_path.parent / "PROGRESS.md").exists():
            progress_path = file_path.parent / "PROGRESS.md"
        elif file_path.is_file():
            content = file_path.read_text(encoding="utf-8")
            if "## Log" in content or verifier or reason:
                progress_path = file_path
    if progress_path is None and not (file_path.parent / "PROGRESS.md").exists():
        # For single-file tasks that bounce or get owner-verified, only write PROGRESS.md if it's a folder task
        return None

    today = datetime.date.today().isoformat()
    who = verifier or actor or "orchestrator"
    detail = f" — {reason}" if reason else ""
    entry_line = f"- {today}, {who}: state `{old_state}` -> `{new_state}`{detail}"

    if progress_path and progress_path.exists():
        content = progress_path.read_text(encoding="utf-8")
        scanned_lines, _ = scan_markdown_blocks(content)
        log_line_idx: int | None = None
        for idx, sline in enumerate(scanned_lines):
            if not sline.is_fenced and sline.text.startswith("## Log"):
                log_line_idx = idx
                break
        if log_line_idx is not None:
            all_lines = content.splitlines()
            log_line = all_lines[log_line_idx]
            heading_suffix = log_line[6:]
            before_lines = all_lines[:log_line_idx]
            after_lines = all_lines[log_line_idx + 1:]
            rest = "\n".join(after_lines).lstrip("\n")
            prefix = ("\n".join(before_lines) + "\n") if before_lines else ""
            new_content = f"{prefix}## Log{heading_suffix}\n\n{entry_line}\n"
            if rest:
                new_content += f"{rest.rstrip()}\n"
            _atomic_write_text(progress_path, new_content, encoding="utf-8")
        else:
            _atomic_write_text(progress_path, content.rstrip() + f"\n\n## Log (newest first)\n\n{entry_line}\n", encoding="utf-8")
    elif progress_path:
        _atomic_write_text(
            progress_path,
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


def _collect_descendant_leaves(node_id: str, tree: dict[str, TaskNode]) -> list[TaskNode]:
    result: list[TaskNode] = []
    if node_id not in tree:
        return result
    stack = list(tree[node_id].children)
    seen = set()
    while stack:
        cid = stack.pop(0)
        if cid in seen or cid not in tree:
            continue
        seen.add(cid)
        cnode = tree[cid]
        if cnode.is_leaf:
            result.append(cnode)
        else:
            stack.extend(cnode.children)
    result.sort(key=lambda c: _natural_sort_key(c.id))
    return result


def transition_task(
    tasks_dir: pathlib.Path,
    task_id: str,
    new_state: str,
    actor: str | None = None,
    verifier: str | None = None,
    reason: str | None = None,
    expect_task_hash: str | None = None,
    force_unblock: bool = False,
    waiting_on: str | None = None,
    verify_by: str | None = None,
    verify_check: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "task_id": task_id,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            if not is_valid_state(new_state):
                return False, {
                    "ok": False,
                    "task_id": task_id,
                    "error": f"Invalid target state {new_state!r}. Allowed states: {sorted(CANONICAL_STATES)}.",
                }

            tree = discover_task_tree(tasks_dir)
            if task_id not in tree:
                return False, {
                    "ok": False,
                    "task_id": task_id,
                    "error": f"Task {task_id!r} not found in {tasks_dir}.",
                }

            node = tree[task_id]
            if not node.is_leaf:
                is_initiative = (
                    node.node_type == "initiative"
                    or node.kind == "initiative"
                    or bool(re.match(r"^\d{2}(-[a-z0-9-]+)?$", task_id))
                )
                if is_initiative:
                    init_num = task_id.split("-", 1)[0]
                    leaves = _collect_descendant_leaves(task_id, tree)
                    open_children = [c for c in leaves if c.canonical_state not in TERMINAL_STATES]
                    if open_children:
                        child_lines = "\n".join(
                            f"  - {c.id} ({c.short_title or (c.short if c.short else derive_short_title(c.title))}): {c.state}"
                            for c in open_children
                        )
                        msg = (
                            f"Initiative '{task_id}' state is derived from its child tasks.\n"
                            f"Open child tasks:\n{child_lines}\n"
                            f"To ship a completed initiative once all children are closed, run: ai-orch tasks ship {init_num} --summary \"...\""
                        )
                    else:
                        msg = (
                            f"Initiative '{task_id}' state is derived from its child tasks.\n"
                            f"All child tasks are closed.\n"
                            f"To ship a completed initiative once all children are closed, run: ai-orch tasks ship {init_num} --summary \"...\""
                        )
                    return False, {
                        "ok": False,
                        "task_id": task_id,
                        "error": "derived state; transition its leaves",
                        "message": msg,
                        "open_children": [
                            {
                                "id": c.id,
                                "short_title": c.short_title or (c.short if c.short else derive_short_title(c.title)),
                                "state": c.state,
                            }
                            for c in open_children
                        ],
                    }
                return False, {
                    "ok": False,
                    "task_id": task_id,
                    "error": "derived state; transition its leaves",
                }

            if node.block_text is not None:
                current_hash = node.task_hash
                if expect_task_hash is not None:
                    if current_hash.lower() != expect_task_hash.strip().lower():
                        return False, {
                            "ok": False,
                            "task_id": task_id,
                            "error": "stale-task",
                            "expected": expect_task_hash,
                            "actual": current_hash,
                        }

                old_state = node.state
                old_canon = node.canonical_state
                new_canon = normalize_state(new_state)
                extracted_wo = extract_waiting_on(new_state)
                if new_canon == "waiting":
                    if waiting_on is None:
                        waiting_on = extracted_wo
                    if waiting_on:
                        waiting_on = normalize_waiting_on(waiting_on)
                    clear_wo = False
                else:
                    clear_wo = (waiting_on is None)

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
                            f"Allowed target states from '{old_state}': {sorted(allowed)}."
                        ),
                    }

                if old_canon == "delivered" and new_canon == "done":
                    return False, {
                        "ok": False,
                        "task_id": task_id,
                        "old_state": old_state,
                        "new_state": new_state,
                        "error": (
                            "Illegal transition 'delivered' -> 'done': delivered tasks must transition to 'verified' "
                            "before 'done' (or to 'done with a caveat: ...' if unverified)."
                        ),
                    }

                executor = node.executor or "kilo"
                vmode = node.fields.get("verification_mode", {}).get("value") or node.own_fields.get("verification_mode")
                if new_canon == "verified":
                    if vmode == "self" and not verifier and (actor or "").lower() != "owner":
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
                    if not _is_independent_verifier(executor, actor, verifier):
                        return False, {
                            "ok": False,
                            "task_id": task_id,
                            "old_state": old_state,
                            "new_state": new_state,
                            "error": (
                                f"Independent verification guard failed: task executor is {executor!r}, "
                                f"so transitioning 'delivered' -> 'verified' requires an independent verifier."
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

                effective_state = "waiting" if new_canon == "waiting" else new_state
                if new_canon == "done with a caveat" and ":" not in new_state and reason:
                    effective_state = f"done with a caveat: {reason.strip()}"
                elif new_canon == "done with a caveat" and ":" not in new_state and vmode == "self":
                    effective_state = "done with a caveat: self-verified only"

                note_parts = [datetime.date.today().isoformat()]
                if actor and actor.strip():
                    note_parts.append(actor.strip())
                if reason and reason.strip() and reason.strip() not in effective_state:
                    note_parts.append(reason.strip())
                file_path = pathlib.Path(node.file_path)
                if new_canon in TERMINAL_STATES:
                    _, new_h = move_block_to_closed(
                        file_path,
                        task_id,
                        new_status=effective_state,
                        status_note="; ".join(note_parts),
                        expect_task_hash=expect_task_hash,
                        new_waiting_on=waiting_on,
                        clear_waiting_on=clear_wo,
                    )
                    if node.parent and node.parent in tree:
                        parent_node = tree[node.parent]
                        if parent_node.is_folder and parent_node.parent is not None:
                            sub_tree = discover_task_tree(tasks_dir)
                            if node.parent in sub_tree:
                                p_derived = sub_tree[node.parent].derived_state
                                if p_derived and normalize_state(p_derived) in TERMINAL_STATES and not sub_tree[node.parent].in_done:
                                    p_dir = pathlib.Path(sub_tree[parent_node.parent].file_path).parent if parent_node.parent in sub_tree else file_path.parent.parent
                                    move_folder_child_to_done(p_dir, node.parent, tasks_dir)
                                    _emit_event(
                                        tasks_dir,
                                        "task.transitioned",
                                        {
                                             "from": parent_node.state,
                                             "to": p_derived,
                                             "actor": actor or "owner",
                                             "reason": f"All children closed on child {task_id} closing",
                                        },
                                        subject=node.parent,
                                        actor=actor or "owner",
                                    )
                else:
                    _, new_h = rewrite_block_in_file(
                        file_path,
                        task_id,
                        new_status=effective_state,
                        status_note="; ".join(note_parts),
                        expect_task_hash=expect_task_hash,
                        new_waiting_on=waiting_on,
                        clear_waiting_on=clear_wo,
                        new_verify_by=verify_by,
                    )
                _emit_event(
                    tasks_dir,
                    "task.transitioned",
                    {
                        "from": old_state,
                        "to": effective_state,
                        "actor": actor or "owner",
                        "reason": reason,
                        "verifier": verifier,
                        "verify_by": verify_by,
                    },
                    subject=task_id,
                    actor=actor or "owner",
                )
                return True, {
                    "ok": True,
                    "task_id": task_id,
                    "kind": "initiative_task" if not task_id.startswith("T") else "emergent_child",
                    "old_state": old_state,
                    "new_state": effective_state,
                    "waiting_on": waiting_on if (new_canon == "waiting" and waiting_on) else None,
                    "verify_by": verify_by or (getattr(node, "verify_by", None)),
                    "file_path": str(file_path),
                    "rel_path": node.rel_path,
                    "task_hash": new_h,
                    "bundle_sha256": new_h,
                }

            emergent = discover_emergent_tasks(tasks_dir)
            target = next((t for t in emergent if t["id"] == task_id), None)
            if target is None:
                return False, {
                    "ok": False,
                    "task_id": task_id,
                    "error": f"Task {task_id!r} not found in {tasks_dir}.",
                }

            current_hash = task_bundle_sha256(target)
            if expect_task_hash is not None:
                if current_hash.lower() != expect_task_hash.strip().lower():
                    return False, {
                        "ok": False,
                        "task_id": task_id,
                        "error": "stale-task",
                        "expected": expect_task_hash,
                        "actual": current_hash,
                    }

            old_state = target["state"]
            old_canon = target["canonical_state"]
            new_canon = normalize_state(new_state)
            extracted_wo = extract_waiting_on(new_state)
            if new_canon == "waiting":
                if waiting_on is None:
                    waiting_on = extracted_wo
                if waiting_on:
                    waiting_on = normalize_waiting_on(waiting_on)
                clear_wo = False
            else:
                clear_wo = (waiting_on is None)

            decider_to_set: str | None = None
            if old_canon == "waiting":
                raw_dec = target.get("decider", "").strip()
                q_ids = re.findall(r"Q\d{3,}", raw_dec)
                if q_ids:
                    all_questions = discover_questions(tasks_dir)
                    q_map = {q["id"]: q for q in all_questions}
                    open_q = [qid for qid in q_ids if qid in q_map and q_map[qid]["status"] == "open"]
                    if open_q:
                        if not force_unblock:
                            return False, {
                                "ok": False,
                                "task_id": task_id,
                                "old_state": old_state,
                                "new_state": new_state,
                                "error": (
                                    f"Waiting invariant violated: task {task_id!r} is waiting on open question(s): "
                                    f"{', '.join(open_q)}. Resolve them via 'questions answer' or 'questions withdraw', "
                                    "or pass --force-unblock --reason TEXT."
                                ),
                            }
                        if not (reason and reason.strip()):
                            return False, {
                                "ok": False,
                                "task_id": task_id,
                                "old_state": old_state,
                                "new_state": new_state,
                                "error": "Transitioning with --force-unblock requires non-empty --reason TEXT.",
                            }
                        for qid in open_q:
                            _withdraw_question_file_only(
                                tasks_dir,
                                q_map[qid],
                                reason=reason.strip(),
                                by=actor or "owner",
                            )
                        decider_to_set = "-"

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
            effective_state = "waiting" if new_canon == "waiting" else new_state
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
                verify_by=verify_by,
                verify_check=verify_check,
                decider=decider_to_set,
                clear_next_up=is_terminal,
                waiting_on=waiting_on,
                clear_waiting_on=clear_wo,
            )
            _append_progress_log(target, old_state, effective_state, actor, verifier, reason)

            final_path = file_path
            if is_terminal and not target["in_done"]:
                final_path = _move_task_to_done(target, tasks_dir)

            new_bundle_hash = task_bundle_sha256(final_path)
            eff_verify_by = verify_by or target.get("verify_by") or target.get("verify-by")
            _emit_event(
                tasks_dir,
                "task.transitioned",
                {
                    "from": old_state,
                    "to": effective_state,
                    "actor": actor or "owner",
                    "reason": reason,
                    "verifier": verifier or target.get("verifier"),
                    "verify_by": eff_verify_by,
                },
                subject=task_id,
                actor=actor or "owner",
            )
            return True, {
                "ok": True,
                "task_id": task_id,
                "old_state": old_state,
                "new_state": effective_state,
                "waiting_on": waiting_on if (new_canon == "waiting" and waiting_on) else None,
                "verifier": verifier or target.get("verifier"),
                "verify_by": eff_verify_by,
                "reason": reason,
                "file_path": str(final_path),
                "rel_path": final_path.relative_to(tasks_dir).as_posix(),
                "bundle_sha256": new_bundle_hash,
            }
    except LockTimeoutError as e:
        return False, {
            "ok": False,
            "task_id": task_id,
            "error": "lock-timeout",
            "message": str(e),
        }
    except UnsupportedPlatformError as e:
        return False, {
            "ok": False,
            "task_id": task_id,
            "error": "unsupported-platform",
            "message": str(e),
        }


def close_task(
    tasks_dir: pathlib.Path,
    task_id: str,
    actor: str | None = None,
    verifier: str | None = None,
    reason: str | None = None,
    owner_approved: bool = False,
    caveat: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "task_id": task_id,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            tree = discover_task_tree(tasks_dir)
            if task_id not in tree:
                return False, {
                    "ok": False,
                    "task_id": task_id,
                    "error": f"Task {task_id!r} not found in {tasks_dir}.",
                }

            node = tree[task_id]
            if not node.is_leaf:
                is_initiative = (
                    node.node_type == "initiative"
                    or node.kind == "initiative"
                    or bool(re.match(r"^\d{2}(-[a-z0-9-]+)?$", task_id))
                )
                if is_initiative:
                    init_num = task_id.split("-", 1)[0]
                    leaves = _collect_descendant_leaves(task_id, tree)
                    open_children = [c for c in leaves if c.canonical_state not in TERMINAL_STATES]
                    if open_children:
                        child_lines = "\n".join(
                            f"  - {c.id} ({c.short_title or (c.short if c.short else derive_short_title(c.title))}): {c.state}"
                            for c in open_children
                        )
                        msg = (
                            f"Initiative '{task_id}' state is derived from its child tasks.\n"
                            f"Open child tasks:\n{child_lines}\n"
                            f"To ship a completed initiative once all children are closed, run: ai-orch tasks ship {init_num} --summary \"...\""
                        )
                    else:
                        msg = (
                            f"Initiative '{task_id}' state is derived from its child tasks.\n"
                            f"All child tasks are closed.\n"
                            f"To ship a completed initiative once all children are closed, run: ai-orch tasks ship {init_num} --summary \"...\""
                        )
                    return False, {
                        "ok": False,
                        "task_id": task_id,
                        "error": "derived state; transition its leaves",
                        "message": msg,
                        "open_children": [
                            {
                                "id": c.id,
                                "short_title": c.short_title or (c.short if c.short else derive_short_title(c.title)),
                                "state": c.state,
                            }
                            for c in open_children
                        ],
                    }
                return False, {
                    "ok": False,
                    "task_id": task_id,
                    "error": "derived state; transition its leaves",
                }

            curr_state = node.state
            curr_canon = node.canonical_state
            if curr_canon in TERMINAL_STATES or node.in_done or node.in_closed_section:
                return False, {
                    "ok": False,
                    "task_id": task_id,
                    "error": f"Task {task_id!r} is already closed in state '{curr_state}'.",
                }

            valid_start = ("open", "in progress", "delivered", "verified", "bounced")
            if curr_canon not in valid_start:
                return False, {
                    "ok": False,
                    "task_id": task_id,
                    "error": f"Cannot close task from state '{curr_state}'. Expected one of: {', '.join(valid_start)}.",
                }

            executor = node.executor or "kilo"
            vmode = None
            if node.block_text is not None:
                vmode = node.fields.get("verification_mode", {}).get("value") or node.own_fields.get("verification_mode")
            else:
                emergent = discover_emergent_tasks(tasks_dir)
                target = next((t for t in emergent if t["id"] == task_id), None)
                if target:
                    vmode = (target.get("verification_mode") or "cross-agent").strip()
                    executor = target.get("executor") or executor
            if vmode in (None, "", "-"):
                vmode = "cross-agent"

            is_already_verified = (curr_canon == "verified")
            is_self_vmode = (vmode == "self")

            if not is_already_verified and not is_self_vmode:
                if owner_approved:
                    pass
                elif verifier:
                    exec_norm = executor.strip().lower()
                    verif_norm = verifier.strip().lower()
                    tool_prefix = verif_norm.split(":", 1)[0].strip()
                    if verif_norm == exec_norm or tool_prefix == exec_norm:
                        return False, {
                            "ok": False,
                            "task_id": task_id,
                            "error": (
                                f"Closing task requires an independent verifier (--verifier <v>, different from executor {executor!r}) "
                                "or owner approval (--owner-approved)."
                            ),
                        }
                else:
                    return False, {
                        "ok": False,
                        "task_id": task_id,
                        "error": (
                            f"Closing task requires an independent verifier (--verifier <v>, different from executor {executor!r}) "
                            "or owner approval (--owner-approved)."
                        ),
                    }

            if caveat and caveat.strip():
                c_text = caveat.strip()
                target_terminal = c_text if c_text.startswith("done with a caveat") else f"done with a caveat: {c_text}"
            elif is_self_vmode and not verifier and not owner_approved:
                target_terminal = "done with a caveat: self-verified only"
            else:
                target_terminal = "done"

            steps: list[str] = []
            if curr_canon in ("open", "bounced"):
                steps.extend(["in progress", "delivered"])
            elif curr_canon == "in progress":
                steps.append("delivered")

            if is_self_vmode and not verifier and not owner_approved:
                pass
            elif curr_canon == "verified":
                pass
            else:
                steps.append("verified")

            steps.append(target_terminal)

            transitions_recorded: list[dict[str, Any]] = []
            last_payload: dict[str, Any] = {}

            for next_st in steps:
                next_canon = normalize_state(next_st)
                if next_canon == "verified":
                    step_actor = "owner" if owner_approved else (actor or "owner")
                    step_verifier = verifier or ("owner" if owner_approved else None)
                elif next_canon in TERMINAL_STATES:
                    step_actor = "owner" if owner_approved else (actor or verifier or executor or "owner")
                    step_verifier = verifier or ("owner" if owner_approved else None)
                else:
                    step_actor = actor or executor
                    step_verifier = verifier or ("owner" if owner_approved else None)
                step_reason = reason

                ok, res = transition_task(
                    tasks_dir=tasks_dir,
                    task_id=task_id,
                    new_state=next_st,
                    actor=step_actor,
                    verifier=step_verifier,
                    reason=step_reason,
                )
                if not ok:
                    return False, {
                        "ok": False,
                        "task_id": task_id,
                        "error": f"Failed during transition to '{next_st}': {res.get('error')}",
                        "details": res,
                        "completed_transitions": transitions_recorded,
                    }
                last_payload = res
                transitions_recorded.append({
                    "from": res.get("old_state"),
                    "to": res.get("new_state"),
                    "task_hash": res.get("bundle_sha256") or res.get("task_hash"),
                })

            idx_path = tasks_dir / "00-INDEX.md"
            if idx_path.is_file():
                existing_idx = idx_path.read_text(encoding="utf-8")
                rendered_idx = render_synced_index(tasks_dir, existing_idx, adopt=True)
                _atomic_write_text(idx_path, rendered_idx, encoding="utf-8")

            return True, {
                "ok": True,
                "task_id": task_id,
                "old_state": curr_state,
                "new_state": last_payload.get("new_state", target_terminal),
                "verifier": verifier or ("owner" if owner_approved else None),
                "reason": reason,
                "transitions": transitions_recorded,
                "rel_path": last_payload.get("rel_path"),
                "file_path": last_payload.get("file_path"),
                "task_hash": last_payload.get("task_hash") or last_payload.get("bundle_sha256"),
                "bundle_sha256": last_payload.get("bundle_sha256") or last_payload.get("task_hash"),
            }
    except LockTimeoutError as e:
        return False, {
            "ok": False,
            "task_id": task_id,
            "error": "lock-timeout",
            "message": str(e),
        }
    except UnsupportedPlatformError as e:
        return False, {
            "ok": False,
            "task_id": task_id,
            "error": "unsupported-platform",
            "message": str(e),
        }


# ---------------------------------------------------------------------------
# 00-INDEX.md Synchronizer
# ---------------------------------------------------------------------------


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


def _strip_conflict_markers_ours(text: str) -> str:
    """Strip git conflict markers (<<<<<<<, =======, >>>>>>>, |||||||), preserving the HEAD/ours side."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    state = "normal"
    for line in lines:
        if line.startswith("<<<<<<<"):
            state = "ours"
            continue
        if state == "ours" and line.startswith("|||||||"):
            state = "base"
            continue
        if state in ("ours", "base") and line.startswith("======="):
            state = "theirs"
            continue
        if state in ("ours", "base", "theirs") and line.startswith(">>>>>>>"):
            state = "normal"
            continue
        if state in ("normal", "ours"):
            out.append(line)
    return "".join(out)


def adopt_markers(existing_index: str) -> str:
    if "<<<<<<<" in existing_index:
        existing_index = _strip_conflict_markers_ours(existing_index)
    updated = existing_index

    # 0. Initiatives
    pat_init = re.compile(r"^##\s+Initiatives\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m_init = pat_init.search(updated)
    if m_init:
        sec = m_init.group(0)
        if not _marker_pattern("initiatives").search(sec):
            lines = sec.splitlines(keepends=True)
            start_idx, end_idx = _find_table_range(lines)
            if start_idx is not None and end_idx is not None:
                tbl = "".join(lines[start_idx:end_idx + 1]).strip()
                replacement = f"<!-- ai-orch:generated initiatives -->\n{tbl}\n<!-- /ai-orch:generated initiatives -->\n"
                new_sec = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx + 1:])
            else:
                new_sec = sec.rstrip() + "\n\n<!-- ai-orch:generated initiatives -->\n<!-- /ai-orch:generated initiatives -->\n\n"
            updated = updated[:m_init.start()] + new_sec + updated[m_init.end():]

    # 0.5. Specs
    pat_specs = re.compile(r"^##\s+Specs\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m_specs = pat_specs.search(updated)
    if m_specs:
        sec = m_specs.group(0)
        if not _marker_pattern("specs").search(sec):
            lines = sec.splitlines(keepends=True)
            start_idx, end_idx = _find_table_range(lines)
            if start_idx is not None and end_idx is not None:
                tbl = "".join(lines[start_idx:end_idx + 1]).strip()
                replacement = f"<!-- ai-orch:generated specs -->\n{tbl}\n<!-- /ai-orch:generated specs -->\n"
                new_sec = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx + 1:])
            else:
                new_sec = sec.rstrip() + "\n\n<!-- ai-orch:generated specs -->\n<!-- /ai-orch:generated specs -->\n\n"
            updated = updated[:m_specs.start()] + new_sec + updated[m_specs.end():]

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

    # 3.5. Conditional
    pat_cond = re.compile(r"^##\s+Conditional\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m_cond = pat_cond.search(updated)
    if m_cond:
        sec = m_cond.group(0)
        if not _marker_pattern("conditional").search(sec):
            lines = sec.splitlines(keepends=True)
            start_idx, end_idx = _find_table_range(lines)
            if start_idx is not None and end_idx is not None:
                for idx in range(end_idx + 1, len(lines)):
                    if "Stale conditions" in lines[idx]:
                        end_idx = idx
                tbl = "".join(lines[start_idx:end_idx + 1]).strip()
                replacement = f"<!-- ai-orch:generated conditional -->\n{tbl}\n<!-- /ai-orch:generated conditional -->\n"
                new_sec = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx + 1:])
            else:
                new_sec = sec.rstrip() + "\n\n<!-- ai-orch:generated conditional -->\n<!-- /ai-orch:generated conditional -->\n\n"
            updated = updated[:m_cond.start()] + new_sec + updated[m_cond.end():]

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
        sec = find_markdown_section(rtext, "Goal and scope")
        if sec and sec.body.strip():
            first_line = sec.body.strip().splitlines()[0]
            first_sentence = first_line.strip().split(". ")[0].rstrip(".")
            goal_line = f"{first_sentence}."
    return f"{goal_line} Owner session: {owner} ([README]({category}/README.md))."


def _extract_existing_category_order(existing_index: str) -> list[str]:
    cats: list[str] = []
    sec = find_markdown_section(existing_index, "Tasks by category")
    if sec:
        for sline in sec.lines[1:]:
            if sline.is_fenced:
                continue
            cm = re.match(r"^###\s+([A-Za-z0-9_-]+)\s*$", sline.text)
            if cm:
                cname = cm.group(1)
                if cname not in cats:
                    cats.append(cname)
    return cats


def _extract_existing_initiative_next_up_rows(existing_index: str) -> list[str]:
    """Preserve initiative task rows (e.g. `01.1`, `03.1`) already listed in `## Next up`."""
    rows: list[str] = []
    sec = find_markdown_section(existing_index, "Next up")
    if not sec:
        return rows
    for sline in sec.lines[1:]:
        if sline.is_fenced:
            continue
        line_s = sline.text.strip()
        if not line_s.startswith("|"):
            continue
        cells = [c.strip() for c in line_s.strip("|").split("|")]
        if not cells:
            continue
        row_id = cells[0]
        if re.match(r"^\d{2,}(?:\.\d+[a-z]?)+$", row_id) or row_id.startswith("INIT-"):
            rows.append(line_s)
    return rows


def render_synced_index(tasks_dir: pathlib.Path, existing_index: str, adopt: bool = False) -> str:
    has_conflict_markers = bool(re.search(r"^(<{7}|={7}|>{7}|\|{7})\b", existing_index, re.MULTILINE)) or ("<<<<<<<" in existing_index)
    if has_conflict_markers:
        existing_index = _strip_conflict_markers_ours(existing_index)
        adopt = True

    emergent = discover_emergent_tasks(tasks_dir)
    initiatives = discover_initiatives(tasks_dir)
    conditional_tasks = [t for t in emergent if t.get("conditional")]
    active_tasks = [t for t in emergent if not t["in_done"] and t["canonical_state"] not in TERMINAL_STATES and not t.get("conditional")]
    done_tasks = [t for t in emergent if (t["in_done"] or t["canonical_state"] in TERMINAL_STATES) and not t.get("conditional")]

    active_tasks.sort(key=lambda t: (PRIORITY_SORT_KEY.get(t["priority"], 99), _natural_sort_key(t["id"])))
    done_tasks.sort(key=lambda t: _natural_sort_key(t["id"]), reverse=True)

    resolved_ids: set[str] = set(t["id"] for t in emergent)
    for init in initiatives:
        resolved_ids.add(str(init["id"]))
        resolved_ids.add(f"INIT-{init['id']}")
        for sub_t in init.get("tasks", []):
            resolved_ids.add(sub_t["id"])
            resolved_ids.add(f"{init['id']}.{sub_t['id']}")

    if existing_index.strip():
        if adopt:
            existing_index = adopt_markers(existing_index)
        elif not has_generated_markers(existing_index):
            raise ValueError(
                "Index has no generated-region markers (<!-- ai-orch:generated <section> -->). "
                "Run with --adopt to wrap existing tables in markers."
            )

    tree = discover_task_tree(tasks_dir)
    pat_init_sec = re.compile(r"^##\s+Initiatives\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m_init = pat_init_sec.search(existing_index)
    if m_init:
        init_sec_text = m_init.group(0)
        m_init_marker = _marker_pattern("initiatives").search(init_sec_text)
        has_init_marker = m_init_marker is not None
        region_to_search = m_init_marker.group(1) if has_init_marker else init_sec_text

        hdr_init, sep_init = _extract_existing_table_header(region_to_search, 6) or (
            "| Priority | # | Initiative | Status | Depends on | Size |",
            "| --- | --- | --- | --- | --- | --- |",
        )
        preamble_lines: list[str] = []
        init_rows: dict[str, tuple[list[str], str]] = {}
        for line in region_to_search.splitlines():
            line_s = line.strip()
            if line_s.startswith(("<", "=", ">")):
                continue
            if not line_s.startswith("|"):
                if not init_rows and line_s:
                    preamble_lines.append(line)
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Priority", "---") or cells[0].startswith("---"):
                continue
            if len(cells) >= 6:
                init_num = cells[1]
                if init_num in init_rows:
                    continue
                if init_num in tree:
                    init_node = tree[init_num]
                    if init_node.children:
                        derived_st = init_node.derived_state or init_node.state
                        if derived_st == "done":
                            new_status = "done"
                        elif derived_st == "open":
                            new_status = "open"
                        elif derived_st == "waiting" and getattr(init_node, "waiting_on", None):
                            new_status = f"waiting ({init_node.waiting_on})"
                        else:
                            leaf_nodes = []
                            def _collect_leaves_rec(nid: str):
                                if nid in tree:
                                    n = tree[nid]
                                    if n.is_leaf:
                                        leaf_nodes.append(n)
                                    for c in n.children:
                                        _collect_leaves_rec(c)
                            for c in init_node.children:
                                _collect_leaves_rec(c)

                            done_leaves = [l for l in leaf_nodes if l.canonical_state in ("done", "done with a caveat", "dropped")]
                            running_leaves = [l for l in leaf_nodes if l.canonical_state in ("in progress", "bounced")]
                            # Finished by the executor, waiting for a check (delivered) or for closing (verified)
                            to_check_leaves = [l for l in leaf_nodes if l.canonical_state in ("delivered", "verified")]
                            open_leaves = [l for l in leaf_nodes if l.canonical_state == "open"]
                            blocked_leaves = [l for l in leaf_nodes if l.canonical_state == "blocked"]
                            waiting_leaves = [l for l in leaf_nodes if l.canonical_state == "waiting"]

                            summary_parts = []
                            if done_leaves:
                                summary_parts.append(f"done: {format_id_ranges([l.id for l in done_leaves])}")
                            if running_leaves:
                                summary_parts.append(f"running: {format_id_ranges([l.id for l in running_leaves])}")
                            if to_check_leaves:
                                summary_parts.append(f"to verify: {format_id_ranges([l.id for l in to_check_leaves])}")
                            if running_leaves or to_check_leaves:
                                pass  # active work already summarised; "next" only when nothing is active
                            elif open_leaves:
                                summary_parts.append(f"next: {format_id_ranges([l.id for l in open_leaves])}")
                            elif blocked_leaves:
                                summary_parts.append(f"blocked: {format_id_ranges([l.id for l in blocked_leaves])}")
                            elif waiting_leaves:
                                w_parts = [f"{l.id} ({l.waiting_on})" if l.waiting_on else l.id for l in waiting_leaves]
                                summary_parts.append(f"waiting: {', '.join(w_parts) if any(l.waiting_on for l in waiting_leaves) else format_id_ranges([l.id for l in waiting_leaves])}")

                            if summary_parts:
                                new_status = f"{derived_st} ({'; '.join(summary_parts)})"
                            else:
                                new_status = derived_st
                        cells[3] = new_status
                new_line = "| " + " | ".join(cells) + " |"
                init_rows[init_num] = (cells, new_line)

        for init in initiatives:
            inum = str(init["id"])
            if inum not in init_rows and inum in tree:
                inode = tree[inum]
                st = inode.derived_state or inode.state
                dep = inode.fields.get("depends_on", {}).get("value") or "-"
                sz = inode.own_fields.get("size", "-")
                pri = str(len(init_rows) + 1)
                new_cells = [pri, inum, f"[{inode.title}]({inode.rel_path})", st, dep, sz]
                init_rows[inum] = (new_cells, "| " + " | ".join(new_cells) + " |")

        def _init_sort_key(item: tuple[list[str], str]) -> tuple:
            cells = item[0]
            pri_str = cells[0].strip()
            pri_num = int(pri_str) if pri_str.isdigit() else 999
            return (pri_num, _natural_sort_key(cells[1]))

        sorted_init_rows = sorted(init_rows.values(), key=_init_sort_key)
        init_table_lines = [hdr_init, sep_init] + [r[1] for r in sorted_init_rows]
        init_lines = preamble_lines + ([""] if preamble_lines else []) + init_table_lines

        new_region_content = "\n".join(init_lines)
        if region_to_search.endswith("\n"):
            new_region_content += "\n"
        if has_init_marker:
            existing_index = _replace_generated_region(existing_index, "initiatives", new_region_content)
        else:
            existing_index = existing_index[:m_init.start()] + new_region_content + existing_index[m_init.end():]

    # 0.5. Specs section
    pat_specs_sec = re.compile(r"^##\s+Specs\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m_specs = pat_specs_sec.search(existing_index)
    if m_specs:
        specs_sec_text = m_specs.group(0)
        m_specs_marker = _marker_pattern("specs").search(specs_sec_text)
        has_specs_marker = m_specs_marker is not None
        region_to_search = m_specs_marker.group(1) if has_specs_marker else specs_sec_text

        hdr_specs, sep_specs = _extract_existing_table_header(region_to_search, 2) or (
            "| Spec | Drives |",
            "| --- | --- |",
        )
        preamble_lines = []
        spec_rows: dict[str, str] = {}
        for line in region_to_search.splitlines():
            line_s = line.strip()
            if line_s.startswith(("<", "=", ">")):
                continue
            if not line_s.startswith("|"):
                if not spec_rows and line_s:
                    preamble_lines.append(line)
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Spec", "---") or cells[0].startswith("---"):
                continue
            slug_match = re.search(r"\[([^\]]+)\]", cells[0])
            slug = slug_match.group(1) if slug_match else cells[0]
            if slug not in spec_rows:
                spec_rows[slug] = line_s

        specs_dir = tasks_dir / "specs"
        if specs_dir.is_dir():
            for sf in sorted(specs_dir.glob("*.md")):
                if sf.name.startswith(".") or not sf.is_file():
                    continue
                slug = sf.stem
                if slug not in spec_rows:
                    spec_rows[slug] = f"| [{slug}](specs/{sf.name}) | - |"

        sorted_slugs = sorted(spec_rows.keys(), key=_natural_sort_key)
        specs_table_lines = [hdr_specs, sep_specs] + [spec_rows[s] for s in sorted_slugs]
        specs_lines = preamble_lines + ([""] if preamble_lines else []) + specs_table_lines
        new_specs_content = "\n".join(specs_lines)
        if region_to_search.endswith("\n"):
            new_specs_content += "\n"
        if has_specs_marker:
            existing_index = _replace_generated_region(existing_index, "specs", new_specs_content)
        else:
            lines = specs_sec_text.splitlines(keepends=True)
            start_idx, end_idx = _find_table_range(lines)
            if start_idx is not None and end_idx is not None:
                new_sec = "".join(lines[:start_idx]) + new_specs_content.strip() + "\n\n" + "".join(lines[end_idx + 1:])
                existing_index = existing_index[:m_specs.start()] + new_sec + existing_index[m_specs.end():]

    # 1. Next up section
    m_next = _marker_pattern("next-up").search(existing_index) if existing_index.strip() else None
    existing_next_region = m_next.group(1) if m_next else existing_index
    if existing_next_region:
        existing_next_region = _strip_conflict_markers_ours(existing_next_region)

    hdr_next, sep_next = _extract_existing_table_header(existing_next_region, 5) or (
        "| Id | Priority | Task | Executor | Handoff |",
        "| --- | --- | --- | --- | --- |",
    )

    existing_next_rows: list[tuple[str, list[str], str]] = []
    if existing_next_region:
        for line in existing_next_region.splitlines():
            line_s = line.strip()
            if line_s.startswith(("<", "=", ">")):
                continue
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Id", "---") or cells[0].startswith("---"):
                continue
            existing_next_rows.append((cells[0], cells, line_s))

    emergent_next_map = {
        t["id"]: t
        for t in active_tasks
        if t["next_up"] == "yes" and t.get("canonical_state") != "paused"
    }
    seen_next_ids: set[str] = set()
    next_up_candidates: list[tuple[str, str, str]] = []

    for row_id, cells, raw_line in existing_next_rows:
        base_id = re.sub(r"\s*\(.*?\)", "", row_id).strip()
        if base_id in seen_next_ids:
            continue
        if re.match(r"^\d{2,}(?:\.\d+[a-z]?)+$", base_id) or base_id.startswith("INIT-"):
            seen_next_ids.add(base_id)
            pri = cells[1] if len(cells) > 1 else "P2"
            next_up_candidates.append((base_id, pri, raw_line))
        elif base_id in emergent_next_map:
            t = emergent_next_map[base_id]
            seen_next_ids.add(base_id)
            st_disp = f" ({t['short_title']})" if t.get("short_title") else ""
            line = f"| {t['id']}{st_disp} | {t['priority']} | [{t['title']}]({t['rel_path']}) | {t['executor']} | `{t['handoff']}` |"
            next_up_candidates.append((base_id, t.get("priority", "P2"), line))
        elif base_id not in resolved_ids:
            seen_next_ids.add(base_id)
            pri = cells[1] if len(cells) > 1 else "P2"
            task_cell = cells[2] if len(cells) > 2 else "-"
            if not task_cell.endswith("(missing)"):
                task_cell = f"{task_cell} (missing)"
            exc = cells[3] if len(cells) > 3 else "unassigned"
            hnd = cells[4] if len(cells) > 4 else "-"
            line = f"| {row_id} | {pri} | {task_cell} | {exc} | {hnd} |"
            next_up_candidates.append((base_id, pri, line))

    for t in active_tasks:
        if t["next_up"] == "yes" and t.get("canonical_state") != "paused" and t["id"] not in seen_next_ids:
            seen_next_ids.add(t["id"])
            st_disp = f" ({t['short_title']})" if t.get("short_title") else ""
            line = f"| {t['id']}{st_disp} | {t['priority']} | [{t['title']}]({t['rel_path']}) | {t['executor']} | `{t['handoff']}` |"
            next_up_candidates.append((t["id"], t.get("priority", "P2"), line))

    next_up_candidates.sort(key=lambda item: (PRIORITY_SORT_KEY.get(item[1], 99), _natural_sort_key(item[0])))
    next_up_lines = [hdr_next, sep_next] + [item[2] for item in next_up_candidates[:5]]
    next_up_content = "\n".join(next_up_lines)

    # 2. Tasks by category section
    m_cat = _marker_pattern("tasks-by-category").search(existing_index) if existing_index.strip() else None
    existing_cat_region = m_cat.group(1) if m_cat else existing_index
    if existing_cat_region:
        existing_cat_region = _strip_conflict_markers_ours(existing_cat_region)

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
                if line_s.startswith(("<", "=", ">")):
                    continue
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
        cat_rows: list[tuple[str, str]] = []

        for row_id, cells in existing_by_cat.get(cat, []):
            base_id = re.sub(r"\s*\(.*?\)", "", row_id).strip()
            if base_id in seen_cat_ids:
                continue
            if base_id in cat_tasks:
                t = cat_tasks[base_id]
                seen_cat_ids.add(base_id)
                st_disp = f" ({t['short_title']})" if t.get("short_title") else ""
                st_val = t['state']
                if t.get("canonical_state") == "waiting" and t.get("waiting_on"):
                    st_val = f"waiting ({t['waiting_on']})"
                elif t.get("canonical_state") == "delivered":
                    vb = t.get("verify_by") or t.get("verify-by") or t.get("headers", {}).get("verify-by") or t.get("headers", {}).get("verify_by")
                    if vb and str(vb).strip() and str(vb).strip() != "-":
                        st_val = f"delivered (verify-by: {str(vb).strip()})"
                cat_rows.append(
                    (
                        base_id,
                        f"| {t['id']}{st_disp} | {t['priority']} | [{t['title']}]({t['rel_path']}) | "
                        f"{st_val} | {t['executor']} | {t['depends_on_raw']} |",
                    )
                )
            elif base_id not in resolved_ids:
                seen_cat_ids.add(base_id)
                pri = cells[1] if len(cells) > 1 else "P2"
                task_cell = cells[2] if len(cells) > 2 else "-"
                if not task_cell.endswith("(missing)"):
                    task_cell = f"{task_cell} (missing)"
                st = cells[3] if len(cells) > 3 else "open"
                exc = cells[4] if len(cells) > 4 else "unassigned"
                dep = cells[5] if len(cells) > 5 else "-"
                cat_rows.append((base_id, f"| {row_id} | {pri} | {task_cell} | {st} | {exc} | {dep} |"))

        new_cat_tasks = [t for tid, t in cat_tasks.items() if tid not in seen_cat_ids]
        for t in new_cat_tasks:
            seen_cat_ids.add(t["id"])
            st_disp = f" ({t['short_title']})" if t.get("short_title") else ""
            st_val = t['state']
            if t.get("canonical_state") == "waiting" and t.get("waiting_on"):
                st_val = f"waiting ({t['waiting_on']})"
            elif t.get("canonical_state") == "delivered":
                vb = t.get("verify_by") or t.get("verify-by") or t.get("headers", {}).get("verify-by") or t.get("headers", {}).get("verify_by")
                if vb and str(vb).strip() and str(vb).strip() != "-":
                    st_val = f"delivered (verify-by: {str(vb).strip()})"
            cat_rows.append(
                (
                    t["id"],
                    f"| {t['id']}{st_disp} | {t['priority']} | [{t['title']}]({t['rel_path']}) | "
                    f"{st_val} | {t['executor']} | {t['depends_on_raw']} |",
                )
            )

        cat_rows.sort(key=lambda r: _natural_sort_key(r[0]))
        cat_lines.extend([r[1] for r in cat_rows])

    cat_content = "\n".join(cat_lines)

    # 3. Decisions waiting section
    m_dec = _marker_pattern("decisions").search(existing_index) if existing_index.strip() else None
    existing_dec_region = m_dec.group(1) if m_dec else existing_index
    if existing_dec_region:
        existing_dec_region = _strip_conflict_markers_ours(existing_dec_region)

    all_questions = discover_questions(tasks_dir)
    open_questions = [q for q in all_questions if q["status"] == "open"]
    open_questions.sort(key=lambda q: _natural_sort_key(q["id"]))

    existing_5_col = _extract_existing_table_header(existing_dec_region, 5) is not None

    if open_questions or existing_5_col:
        hdr_dec, sep_dec = _extract_existing_table_header(existing_dec_region, 5) or (
            "| Key | Question | Blocks | Decider | Recommended |",
            "| --- | --- | --- | --- | --- |",
        )
        use_5_cols = True
    else:
        hdr_dec, sep_dec = _extract_existing_table_header(existing_dec_region, 4) or (
            "| Task / Initiative | Question (exact) | Decider | Blocks |",
            "| --- | --- | --- | --- |",
        )
        use_5_cols = False

    dec_lines = [hdr_dec, sep_dec]

    if use_5_cols:
        for q in open_questions:
            q_key = f"[{q['id']}](questions/{q['filename']})"
            q_text = q["question"]
            blocks_clean = ", ".join(
                [re.sub(r"\s*\([^)]*\)", "", b).strip() for b in q["blocks"].split(",") if b.strip()]
            ) or "-"
            dec_lines.append(f"| {q_key} | {q_text} | {blocks_clean} | {q['decider']} | {q['recommended']} |")

    existing_dec_rows: list[tuple[str, list[str]]] = []
    if existing_dec_region:
        for line in existing_dec_region.splitlines():
            line_s = line.strip()
            if line_s.startswith(("<", "=", ">")):
                continue
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Key", "Task", "Task / Initiative", "---") or cells[0].startswith("---"):
                continue
            if cells[0] != "-":
                existing_dec_rows.append((cells[0], cells))

    qualifying_tasks: dict[str, dict[str, Any]] = {
        t["id"]: t
        for t in active_tasks
        if t["canonical_state"] in ("waiting", "blocked")
        and t["decider"]
        and t["decider"].strip() not in ("", "-")
        and not re.match(r"^Q\d{3,}(?:,\s*Q\d{3,})*$", t["decider"].strip())
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
            m_t = re.match(r"^(T\d+)(?:\s*\(.*\))?$", cells[0])
            if len(cells) >= 4 and m_t:
                tid, st = m_t.group(1), cells[3]
                if normalize_state(st) in ("waiting", "blocked") and tid not in [r[0] for r in existing_dec_rows]:
                    existing_waiting_ids_without_dec.add(tid)

    legacy_dec_rows: list[tuple[str, str]] = []
    seen_dec_ids: set[str] = set()

    for row_id, cells in existing_dec_rows:
        if row_id.startswith("Q") or row_id.startswith("[Q"):
            continue
        if row_id in seen_dec_ids:
            continue
        if row_id in qualifying_tasks:
            seen_dec_ids.add(row_id)
            wt = qualifying_tasks[row_id]
            q_cell = cells[1] if len(cells) > 1 and cells[1] not in ("", "-") else ""
            if not q_cell:
                raw_dec = wt["decider"]
                q_cell = raw_dec.split(":", 1)[1].strip() if ":" in raw_dec else raw_dec
            raw_dec = wt["decider"]
            who = raw_dec.split(":", 1)[0].strip() if ":" in raw_dec else raw_dec
            blocks_str = ", ".join(blocks_map.get(row_id, [])) or "-"
            if use_5_cols:
                line = f"| {row_id} | {q_cell} | {blocks_str} | {who} | - |"
            else:
                line = f"| {row_id} | {q_cell} | {who} | {blocks_str} |"
            legacy_dec_rows.append((row_id, line))
        elif row_id not in resolved_ids:
            seen_dec_ids.add(row_id)
            task_cell = f"{row_id} (missing)" if not row_id.endswith("(missing)") else row_id
            q_cell = cells[1] if len(cells) > 1 else "-"
            if len(cells) >= 5:
                blk_cell = cells[2]
                dec_cell = cells[3]
            else:
                dec_cell = cells[2] if len(cells) > 2 else "-"
                blk_cell = cells[3] if len(cells) > 3 else "-"
            if use_5_cols:
                line = f"| {task_cell} | {q_cell} | {blk_cell} | {dec_cell} | - |"
            else:
                line = f"| {task_cell} | {q_cell} | {dec_cell} | {blk_cell} |"
            legacy_dec_rows.append((row_id, line))

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
        if use_5_cols:
            line = f"| {wt['id']} | {question} | {blocks_str} | {who} | - |"
        else:
            line = f"| {wt['id']} | {question} | {who} | {blocks_str} |"
        legacy_dec_rows.append((wt["id"], line))

    legacy_dec_rows.sort(key=lambda r: _natural_sort_key(r[0]))
    for r in legacy_dec_rows:
        dec_lines.append(r[1])

    if len(dec_lines) == 2:
        if use_5_cols:
            dec_lines.append("| - | None. | - | - | - |")
        else:
            dec_lines.append("| - | None. | - | - |")
    dec_content = "\n".join(dec_lines)

    # 4. Done section
    m_done = _marker_pattern("done").search(existing_index) if existing_index.strip() else None
    existing_done_region = m_done.group(1) if m_done else existing_index
    if existing_done_region:
        existing_done_region = _strip_conflict_markers_ours(existing_done_region)

    hdr_done, sep_done = _extract_existing_table_header(existing_done_region, 4) or (
        "| Id | Task | Result | Closed |",
        "| --- | --- | --- | --- |",
    )
    hdr_cond = "| Id | Task | Result | Closed |"
    sep_cond = "| --- | --- | --- | --- |"
    cond_lines = [hdr_cond, sep_cond]
    stale_entries: list[str] = []
    for ct in sorted(conditional_tasks, key=lambda t: _natural_sort_key(t["id"]), reverse=True):
        st_disp = f" ({ct['short_title']})" if ct.get("short_title") else ""
        task_cell = f"[{ct['title']}]({ct['rel_path']})"
        open_conditions = [c for c in ct.get("conditions", []) if c.get("status") != "answered"]
        cond_list_to_show = open_conditions if open_conditions else ct.get("conditions", [])
        cond_tokens: list[str] = []
        for c in cond_list_to_show:
            cond_str = f"{c['id']} ({c.get('age_days', 0)} d, {c.get('decider', 'owner')})"
            cond_tokens.append(cond_str)
            if c.get("status") != "answered" and c.get("age_days", 0) > 7:
                stale_entries.append(f"{cond_str} on {ct['id']}")
        qids_str = ", ".join(cond_tokens) if cond_tokens else "-"
        res_str = f"done, conditional ({qids_str})"
        closed_val = _git_closed_date(tasks_dir, ct["rel_path"])
        cond_lines.append(f"| {ct['id']}{st_disp} | {task_cell} | {res_str} | {closed_val} |")
    cond_content = "\n".join(cond_lines)
    if stale_entries:
        cond_content += f"\n\nStale conditions (> 7 days): {', '.join(stale_entries)}"

    done_lines = [hdr_done, sep_done]

    existing_done_rows: list[tuple[str, list[str]]] = []
    if existing_done_region:
        for line in existing_done_region.splitlines():
            line_s = line.strip()
            if line_s.startswith(("<", "=", ">")):
                continue
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Id", "---") or cells[0].startswith("---"):
                continue
            if cells[0] != "-":
                existing_done_rows.append((cells[0], cells))

    done_tasks_map = {dt["id"]: dt for dt in done_tasks}
    seen_done_ids: set[str] = set()
    done_rows: list[tuple[str, str]] = []

    for row_id, cells in existing_done_rows:
        base_id = re.sub(r"\s*\(.*?\)", "", row_id).strip()
        if base_id in seen_done_ids:
            continue
        if any(ct["id"] == base_id for ct in conditional_tasks):
            continue
        if base_id in done_tasks_map:
            dt = done_tasks_map[base_id]
            seen_done_ids.add(base_id)
            task_cell = f"[{dt['title']}]({dt['rel_path']})"
            res_val = cells[2] if len(cells) > 2 and cells[2] not in ("", "-") else dt["state"]
            closed_val = cells[3] if len(cells) > 3 and cells[3] not in ("", "-") else _git_closed_date(tasks_dir, dt["rel_path"])
            st_disp = f" ({dt['short_title']})" if dt.get("short_title") else ""
            done_rows.append((base_id, f"| {dt['id']}{st_disp} | {task_cell} | {res_val} | {closed_val} |"))
        elif base_id not in resolved_ids:
            seen_done_ids.add(base_id)
            task_cell = cells[1] if len(cells) > 1 else "-"
            if not task_cell.endswith("(missing)"):
                task_cell = f"{task_cell} (missing)"
            res_val = cells[2] if len(cells) > 2 else "done"
            closed_val = cells[3] if len(cells) > 3 else datetime.date.today().isoformat()
            done_rows.append((base_id, f"| {row_id} | {task_cell} | {res_val} | {closed_val} |"))

    new_done_tasks = [dt for dt_id, dt in done_tasks_map.items() if dt_id not in seen_done_ids]
    new_done_tasks.sort(key=lambda t: _natural_sort_key(t["id"]), reverse=True)
    for dt in new_done_tasks:
        dt_id = dt["id"]
        seen_done_ids.add(dt_id)
        task_cell = f"[{dt['title']}]({dt['rel_path']})"
        res_val = dt["state"]
        closed_val = _git_closed_date(tasks_dir, dt["rel_path"])
        st_disp = f" ({dt['short_title']})" if dt.get("short_title") else ""
        done_rows.append((dt_id, f"| {dt_id}{st_disp} | {task_cell} | {res_val} | {closed_val} |"))

    if has_conflict_markers:
        done_rows.sort(key=lambda r: _natural_sort_key(r[0]), reverse=True)

    done_lines.extend([r[1] for r in done_rows])
    done_content = "\n".join(done_lines)

    if not existing_index.strip() or not has_generated_markers(existing_index):
        title_header = existing_index.strip() if existing_index.strip() else "# Task Index"
        cond_block = ""
        if conditional_tasks:
            cond_block = (
                "## Conditional\n\n"
                f"<!-- ai-orch:generated conditional -->\n{cond_content}\n<!-- /ai-orch:generated conditional -->\n\n"
            )
        return (
            f"{title_header}\n\n"
            "## Next up\n\n"
            f"<!-- ai-orch:generated next-up -->\n{next_up_content}\n<!-- /ai-orch:generated next-up -->\n\n"
            "## Tasks by category\n\n"
            f"<!-- ai-orch:generated tasks-by-category -->\n{cat_content}\n<!-- /ai-orch:generated tasks-by-category -->\n\n"
            "## Decisions waiting\n\n"
            f"<!-- ai-orch:generated decisions -->\n{dec_content}\n<!-- /ai-orch:generated decisions -->\n\n"
            f"{cond_block}"
            "## Done\n\n"
            f"<!-- ai-orch:generated done -->\n{done_content}\n<!-- /ai-orch:generated done -->\n"
        )

    updated = existing_index
    updated = _replace_generated_region(updated, "next-up", next_up_content)
    updated = _replace_generated_region(updated, "tasks-by-category", cat_content)
    updated = _replace_generated_region(updated, "decisions", dec_content)

    if conditional_tasks:
        cond_block = (
            "## Conditional\n\n"
            f"<!-- ai-orch:generated conditional -->\n{cond_content}\n<!-- /ai-orch:generated conditional -->\n\n"
        )
        if _marker_pattern("conditional").search(updated):
            updated = _replace_generated_region(updated, "conditional", cond_content)
        else:
            pat_done = re.compile(r"^##\s+Done\b.*", re.MULTILINE)
            m_d = pat_done.search(updated)
            if m_d:
                updated = updated[:m_d.start()] + cond_block + updated[m_d.start():]
            else:
                updated = updated.rstrip() + "\n\n" + cond_block
    else:
        pat_cond = re.compile(r"^##\s+Conditional\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
        m_c = pat_cond.search(updated)
        if m_c:
            updated = updated[:m_c.start()] + updated[m_c.end():]
            updated = re.sub(r"\n{3,}", "\n\n", updated)

    updated = _replace_generated_region(updated, "done", done_content)
    return updated


# ---------------------------------------------------------------------------
# Timeline / Dependency Graph (Spec 10)
# ---------------------------------------------------------------------------

def compute_tasks_graph(
    tasks_dir: pathlib.Path,
    kind_filter: list[str] | set[str] | None = None,
    label_filter: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    tree = discover_task_tree(tasks_dir)

    def _clean_filter_set(raw: Any) -> set[str] | None:
        if not raw:
            return None
        if isinstance(raw, str):
            raw = [raw]
        res = set()
        for item in raw:
            for piece in str(item).split(","):
                p = piece.strip().lower()
                if p and p != "-":
                    res.add(p)
        return res if res else None

    kind_set = _clean_filter_set(kind_filter)
    label_set = _clean_filter_set(label_filter)

    # 1. Identify leaf/microtask nodes
    all_leaf_nodes: list[TaskNode] = []
    for nid in sorted(tree.keys(), key=_natural_sort_key):
        n = tree[nid]
        if n.is_leaf or n.node_type == "microtask":
            all_leaf_nodes.append(n)

    # 2. Map groups: initiative or category
    def _get_group(node: TaskNode) -> str:
        curr: TaskNode | None = node
        while curr:
            if curr.node_type == "initiative":
                return curr.id
            if curr.parent and curr.parent in tree:
                curr = tree[curr.parent]
            else:
                break
        if node.category:
            return node.category
        if "." in node.id:
            return node.id.split(".")[0]
        return "emergent"

    def _is_paused_or_under_paused(node: TaskNode) -> bool:
        curr: TaskNode | None = node
        while curr:
            if curr.canonical_state == "paused":
                return True
            if curr.parent and curr.parent in tree:
                curr = tree[curr.parent]
            else:
                break
        return False

    # 3. Columns calculation across all open (non-terminal, non-paused) leaves
    open_leaves_all = [
        n for n in all_leaf_nodes
        if n.canonical_state not in TERMINAL_STATES and not _is_paused_or_under_paused(n)
    ]
    open_set_all = {n.id for n in open_leaves_all}

    blocked_by_map: dict[str, list[str]] = {}
    for n in all_leaf_nodes:
        if n.id in open_set_all:
            blocked = []
            for d in n.expanded_depends_on:
                if is_external_task_ref(d):
                    ext = resolve_external_task_ref(d, tasks_dir)
                    if (not ext.get("resolved")) or (
                        ext.get("canonical_state") not in (
                            "done",
                            "done with a caveat",
                            "verified",
                            "delivered",
                        )
                    ):
                        blocked.append(d)
                elif d in tree and tree[d].canonical_state not in TERMINAL_STATES:
                    blocked.append(d)
            blocked_by_map[n.id] = sorted(blocked, key=_natural_sort_key)
        else:
            blocked_by_map[n.id] = []

    col_memo: dict[str, int] = {}
    visiting: set[str] = set()

    def _col_for(nid: str) -> int:
        if nid in col_memo:
            return col_memo[nid]
        if nid in visiting:
            return 0
        visiting.add(nid)
        deps = blocked_by_map.get(nid, [])
        if not deps:
            c = 0
        else:
            open_deps = [d for d in deps if d in open_set_all]
            if not open_deps:
                c = 1
            else:
                c = 1 + max(_col_for(d) for d in open_deps)
        visiting.remove(nid)
        col_memo[nid] = c
        return c

    columns_all: dict[str, int] = {}
    for n in open_leaves_all:
        columns_all[n.id] = _col_for(n.id)

    # Filter leaf nodes if filters active
    def _matches_filters(node: TaskNode) -> bool:
        k = (node.kind or node.own_fields.get("kind") or "").strip().lower()
        if kind_set is not None:
            if not k or k not in kind_set:
                return False
        if label_set is not None:
            node_labels = {l.strip().lower() for l in node.labels}
            if not any(l in node_labels for l in label_set):
                return False
        return True

    if kind_set is not None or label_set is not None:
        leaf_nodes = [n for n in all_leaf_nodes if _matches_filters(n)]
    else:
        leaf_nodes = all_leaf_nodes

    open_leaves = [
        n for n in leaf_nodes
        if n.canonical_state not in TERMINAL_STATES and not _is_paused_or_under_paused(n)
    ]
    open_set = {n.id for n in open_leaves}
    columns = {nid: columns_all[nid] for nid in open_set if nid in columns_all}

    # 4. Ready queue: column-0 tasks sorted by priority, then next-up: yes first, then id
    col0_nodes = [
        n for n in open_leaves
        if columns_all.get(n.id) == 0 and n.canonical_state in ("open", "bounced")
    ]

    def _ready_sort_key(n: TaskNode):
        p_rank = PRIORITY_SORT_KEY.get(n.priority, 2)
        next_up_val = n.own_fields.get("next_up") or n.own_fields.get("next-up") or "no"
        nu_rank = 0 if next_up_val == "yes" else 1
        return (p_rank, nu_rank, _natural_sort_key(n.id))

    col0_nodes.sort(key=_ready_sort_key)
    ready_queue = [n.id for n in col0_nodes]

    # 5. Heaviest chain: DAG longest path with vertex weights
    dp_weight: dict[str, int] = {}
    dp_path: dict[str, list[str]] = {}

    topo_order = sorted(open_leaves, key=lambda n: (columns_all.get(n.id, 0), _natural_sort_key(n.id)))

    for n in topo_order:
        w = SIZE_WEIGHTS.get(n.size.upper(), 3)
        deps = [d for d in blocked_by_map.get(n.id, []) if d in open_set]
        if not deps:
            dp_weight[n.id] = w
            dp_path[n.id] = [n.id]
        else:
            best_pred = max(
                deps,
                key=lambda d: (
                    dp_weight.get(d, 0),
                    -PRIORITY_SORT_KEY.get(tree[d].priority, 2),
                    _natural_sort_key(d),
                ),
            )
            dp_weight[n.id] = dp_weight[best_pred] + w
            dp_path[n.id] = dp_path[best_pred] + [n.id]

    heaviest_chain: list[str] = []
    heaviest_chain_weight = 0
    if topo_order:
        best_end = max(
            topo_order,
            key=lambda n: (
                dp_weight.get(n.id, 0),
                columns_all.get(n.id, 0),
                -PRIORITY_SORT_KEY.get(n.priority, 2),
                _natural_sort_key(n.id),
            ),
        )
        heaviest_chain = dp_path.get(best_end.id, [])
        heaviest_chain_weight = dp_weight.get(best_end.id, 0)

    # 6. Edges: dependencies between leaf nodes
    leaf_ids = {n.id for n in leaf_nodes}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    for n in leaf_nodes:
        for dep in n.expanded_depends_on:
            if dep in tree and tree[dep].is_leaf and dep in leaf_ids:
                edge_pair = (dep, n.id)
                if edge_pair not in seen_edges:
                    seen_edges.add(edge_pair)
                    edges.append({
                        "from": dep,
                        "to": n.id,
                        "source": dep,
                        "target": n.id,
                    })
    edges.sort(key=lambda e: (_natural_sort_key(e["from"]), _natural_sort_key(e["to"])))

    # 7. Totals: per state, per size, per group, overall
    by_state: dict[str, int] = {}
    for n in leaf_nodes:
        by_state[n.canonical_state] = by_state.get(n.canonical_state, 0) + 1

    by_size: dict[str, int] = {"XS": 0, "S": 0, "M": 0, "L": 0, "XL": 0}
    by_group: dict[str, dict[str, Any]] = {}

    for n in leaf_nodes:
        grp = _get_group(n)
        if grp not in by_group:
            by_group[grp] = {
                "id": grp,
                "by_size": {"XS": 0, "S": 0, "M": 0, "L": 0, "XL": 0},
                "by_state": {},
                "total_open": 0,
                "total_leaves": 0,
            }
        g_info = by_group[grp]
        g_info["total_leaves"] += 1
        g_info["by_state"][n.canonical_state] = g_info["by_state"].get(n.canonical_state, 0) + 1

        if n.id in open_set:
            s = n.size.upper() if n.size.upper() in VALID_SIZES else "M"
            by_size[s] = by_size.get(s, 0) + 1
            g_info["by_size"][s] = g_info["by_size"].get(s, 0) + 1
            g_info["total_open"] += 1

    overall_parts = [f"{by_size[s]} {s}" for s in ("XS", "S", "M", "L", "XL") if by_size.get(s, 0) > 0]
    overall_str = ", ".join(overall_parts) if overall_parts else "0 M"

    totals = {
        "overall": overall_str,
        "by_state": by_state,
        "by_size": by_size,
        "by_group": by_group,
        "total_open": len(open_leaves),
        "total_leaves": len(leaf_nodes),
        **by_state,
        **by_size,
    }

    # 8. Node dicts
    nodes_list: list[dict[str, Any]] = []
    for n in leaf_nodes:
        is_open = n.id in open_set
        col = columns_all.get(n.id) if is_open else None
        nodes_list.append({
            "id": n.id,
            "node_type": n.node_type,
            "kind": n.kind or n.own_fields.get("kind") or ("initiative_task" if "." in n.id and not n.id.startswith("T") else ("emergent" if n.id.startswith("T") else "initiative")),
            "labels": list(n.labels),
            "title": n.title,
            "short": n.short,
            "short_title": n.short_title,
            "short_title_source": n.short_title_source,
            "group": _get_group(n),
            "state": n.state,
            "canonical_state": n.canonical_state,
            "priority": n.priority,
            "priority_source": n.priority_source,
            "size": n.size,
            "size_source": n.size_source,
            "depends_on": list(n.depends_on),
            "expanded_depends_on": list(n.expanded_depends_on),
            "column": col,
            "blocked_by": blocked_by_map.get(n.id, []),
            "next_up": n.own_fields.get("next_up") or n.own_fields.get("next-up") or "no",
            "executor": n.executor,
            "coordinates": list(n.coordinates) if hasattr(n, "coordinates") else [],
        })

    return {
        "ok": True,
        "tasks_dir": str(tasks_dir),
        "nodes": nodes_list,
        "nodes_by_id": {n["id"]: n for n in nodes_list},
        "edges": edges,
        "columns": columns,
        "ready_queue": ready_queue,
        "longest_chain": heaviest_chain,
        "heaviest_chain": heaviest_chain,
        "heaviest_chain_weight": heaviest_chain_weight,
        "totals": totals,
    }



def _edge_ends(e: Any) -> tuple[str, str]:
    if isinstance(e, dict):
        return str(e.get("from") or e.get("source") or ""), str(e.get("to") or e.get("target") or "")
    return str(e[0]), str(e[1])


CLOSED_GRAPH_STATES = {"done", "done with a caveat", "dropped"}


def render_mermaid_graph(
    graph_data: dict[str, Any], tasks_dir: pathlib.Path | None = None, include_closed: bool = False
) -> str:
    lines = ["flowchart LR"]
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    if not include_closed:
        # Closed work is history: the diagram shows what is still ahead.
        nodes = [n for n in nodes if n.get("canonical_state") not in CLOSED_GRAPH_STATES]
        kept = {n["id"] for n in nodes}
        edges = [e for e in edges if _edge_ends(e)[0] in kept and _edge_ends(e)[1] in kept]

    groups: dict[str, list[dict[str, Any]]] = {}
    for n in nodes:
        grp = n.get("group", "emergent")
        groups.setdefault(grp, []).append(n)

    for grp_id in sorted(groups.keys(), key=_natural_sort_key):
        grp_nodes = groups[grp_id]
        safe_grp_id = f"subgraph_{re.sub(r'[^a-zA-Z0-9_]', '_', grp_id)}"
        grp_title = grp_id
        if tasks_dir:
            for parent_dir in (tasks_dir, tasks_dir / "done"):
                if parent_dir.is_dir():
                    for init_dir in parent_dir.iterdir():
                        if init_dir.is_dir() and init_dir.name.startswith(f"{grp_id}-"):
                            grp_title = init_dir.name
                            break
                    if grp_title != grp_id:
                        break
        lines.append(f'  subgraph {safe_grp_id} ["{grp_title}"]')
        for n in sorted(grp_nodes, key=lambda x: _natural_sort_key(x["id"])):
            safe_node_id = f"node_{re.sub(r'[^a-zA-Z0-9_]', '_', n['id'])}"
            clean_title = n["title"].replace('"', "'")
            prio = n.get("priority", "P2")
            sz = n.get("size", "M")
            lines.append(f'    {safe_node_id}["{n["id"]} ({prio}, {sz}) - {clean_title}"]')
        lines.append("  end")

    for e in edges:
        s_id = f"node_{re.sub(r'[^a-zA-Z0-9_]', '_', e['from'])}"
        t_id = f"node_{re.sub(r'[^a-zA-Z0-9_]', '_', e['to'])}"
        lines.append(f"  {s_id} --> {t_id}")

    lines.append("  classDef p0 fill:#ff4d4f,stroke:#d9363e,color:#fff;")
    lines.append("  classDef p1 fill:#ffa940,stroke:#d46b08,color:#fff;")
    lines.append("  classDef p2 fill:#4096ff,stroke:#0958d9,color:#fff;")
    lines.append("  classDef p3 fill:#91caff,stroke:#1677ff,color:#000;")
    for n in nodes:
        safe_node_id = f"node_{re.sub(r'[^a-zA-Z0-9_]', '_', n['id'])}"
        p = n.get("priority", "P2").lower()
        if p in ("p0", "p1", "p2", "p3"):
            lines.append(f"  class {safe_node_id} {p};")

    return "\n".join(lines) + "\n"


def _clean_filter_set(raw: Any) -> set[str] | None:
    if not raw:
        return None
    if isinstance(raw, str):
        raw = [raw]
    res = set()
    for item in raw:
        for piece in str(item).split(","):
            p = piece.strip().lower()
            if p and p != "-":
                res.add(p)
    return res if res else None


def _build_tasks_list(
    tasks_dir: pathlib.Path,
    tree: dict[str, TaskNode],
    emergent: list[dict[str, Any]],
    initiatives: list[dict[str, Any]],
    tree_dicts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    tree_keys = (
        "parent", "depth", "node_type", "is_leaf", "is_container", "derived_state",
        "leaves_done", "leaves_total", "labels", "fields", "expanded_depends_on",
        "children", "size", "size_source", "priority_source", "coordinates",
        "conditions", "conditional", "waiting_on"
    )

    all_tasks: list[dict[str, Any]] = []
    for et in emergent:
        item = dict(et)
        td = tree_dicts.get(et["id"])
        if td:
            for k in tree_keys:
                item[k] = td[k]
            if td["is_container"]:
                item["state"] = td["state"]
                item["canonical_state"] = td["canonical_state"]
        deps = item.get("depends_on") or []
        if isinstance(deps, str):
            deps, _ = parse_depends_on_field(deps)
        ext_deps = [d for d in deps if is_external_task_ref(d)]
        if ext_deps:
            item["external_dependencies"] = [
                resolve_external_task_ref(d, tasks_dir) for d in ext_deps
            ]
        exec_val = str(item.get("executor") or "").strip()
        if exec_val.startswith("workspace:"):
            item["external_executor"] = {
                "kind": "workspace",
                "workspace": exec_val[len("workspace:"):].strip().split("/")[0],
            }
        elif exec_val.startswith("session:"):
            item["external_executor"] = {
                "kind": "session",
                "session": exec_val[len("session:"):].strip(),
            }
        all_tasks.append(item)

    def _child_item(td: dict[str, Any], category: str, next_up: str, fallback_handoff: str) -> dict[str, Any]:
        node = tree[td["id"]]
        item = dict(td)
        item.update({
            "kind": node.kind or ("initiative_task" if not td["id"].startswith("T") else "emergent_child"),
            "category": category,
            "next_up": next_up,
            "depends_on": _format_depends_on(node.depends_on),
            "depends_on_ids": list(node.depends_on),
            "handoff": td.get("handoff") or fallback_handoff,
            "waiting_on": td.get("waiting_on") or node.waiting_on,
        })
        deps = list(node.depends_on)
        ext_deps = [d for d in deps if is_external_task_ref(d)]
        if ext_deps:
            item["external_dependencies"] = [
                resolve_external_task_ref(d, tasks_dir) for d in ext_deps
            ]
        exec_val = str(node.executor or item.get("executor") or "").strip()
        if exec_val.startswith("workspace:"):
            item["external_executor"] = {
                "kind": "workspace",
                "workspace": exec_val[len("workspace:"):].strip().split("/")[0],
            }
        elif exec_val.startswith("session:"):
            item["external_executor"] = {
                "kind": "session",
                "session": exec_val[len("session:"):].strip(),
            }
        return item

    for init in initiatives:
        init_st = init.get("status", "open")
        category = init.get("slug", init.get("folder", "initiative"))
        if init.get("legacy_tasks"):
            for sub_t in init["tasks"]:
                sub_id = sub_t["id"]
                if not (sub_id.startswith(init["id"]) or sub_id.startswith("T")):
                    sub_id = f"{init['id']}.{sub_id}"
                sub_st = sub_t.get("short_title") or derive_short_title(sub_t["title"])
                all_tasks.append({
                    "kind": "initiative_task",
                    "id": sub_id,
                    "title": sub_t["title"],
                    "short": sub_t.get("short"),
                    "short_title": sub_st,
                    "short_title_source": sub_t.get("short_title_source", "derived"),
                    "category": category,
                    "priority": "P1",
                    "priority_reason": f"Subtask of Initiative #{init['id']}",
                    "next_up": "yes" if init_st == "in progress" and sub_t.get("state") != "done" else "no",
                    "state": sub_t.get("state", init_st),
                    "waiting_on": sub_t.get("waiting_on"),
                    "executor": "kilo",
                    "depends_on": "-",
                    "handoff": f"Work on task {sub_id} in {init.get('rel_path')}",
                    "file_path": str(tasks_dir / init["rel_path"]),
                    "in_done": sub_t.get("state", init_st) == "done",
                    "bundle_sha256": init.get("bundle_sha256"),
                    "legacy": True,
                })
        elif init.get("tasks"):
            for sub_t in init["tasks"]:
                td = tree_dicts[sub_t["id"]]
                nu = "yes" if init_st == "in progress" and td["is_leaf"] and td["canonical_state"] not in TERMINAL_STATES else "no"
                all_tasks.append(_child_item(td, category, nu, f"Work on task {td['id']} in {td['rel_path']}"))
        else:
            all_tasks.append({
                "kind": "initiative",
                "id": f"INIT-{init['id']}",
                "title": init["title"],
                "short": init.get("short"),
                "short_title": init.get("short_title") or derive_short_title(init["title"]),
                "short_title_source": init.get("short_title_source", "derived"),
                "category": category,
                "priority": "P1",
                "priority_reason": f"Initiative container #{init['id']}",
                "next_up": "yes" if init_st == "in progress" else "no",
                "state": init_st,
                "executor": "architect",
                "handoff": f"Review plan for Initiative #{init['id']} in {init.get('rel_path')}",
                "file_path": str(tasks_dir / init["rel_path"]),
                "in_done": init_st == "done",
                "bundle_sha256": init.get("bundle_sha256"),
            })

    listed = {t["id"] for t in all_tasks}
    for nid, td in tree_dicts.items():
        if nid in listed or td["node_type"] == "initiative":
            continue
        root = nid.split(".")[0]
        if td["parent"] is None and td["node_type"] != "microtask":
            continue
        cat = tree[root].category if root in tree else ""
        all_tasks.append(_child_item(td, cat, "no", f"Work on task {nid} in {td['rel_path']}"))

    return all_tasks


def resolve_workspace_and_projects(
    workspace_arg: str | None = None,
    tasks_dir: pathlib.Path | None = None,
) -> tuple[pathlib.Path, str, list[dict[str, Any]]]:
    """Resolve workspace root, workspace slug, and all constituent projects."""
    ws_reg = None
    ws_root: pathlib.Path | None = None
    ws_slug: str | None = None

    if workspace_arg:
        if orchestration_registry is not None and hasattr(orchestration_registry, "find_workspace_for_arg"):
            try:
                ws_reg = orchestration_registry.find_workspace_for_arg(workspace_arg)
                if ws_reg:
                    ws_root = pathlib.Path(ws_reg["canonical_path"]).resolve()
                    ws_slug = ws_reg.get("slug") or ws_reg.get("id") or ws_root.name
            except Exception:
                ws_reg = None
        if ws_root is None:
            cand_p = pathlib.Path(workspace_arg).expanduser().resolve()
            if cand_p.is_dir():
                ws_root = cand_p
                ws_slug = cand_p.name
                if orchestration_registry is not None and hasattr(orchestration_registry, "resolve_workspace_for_path"):
                    try:
                        near_ws, _ = orchestration_registry.resolve_workspace_for_path(cand_p)
                        if near_ws and pathlib.Path(near_ws["canonical_path"]).resolve() == ws_root:
                            ws_slug = near_ws["slug"]
                    except Exception:
                        pass
            else:
                raise ValueError(f"Workspace not found for argument {workspace_arg!r}")
    else:
        start_p = tasks_dir.resolve() if tasks_dir else pathlib.Path.cwd().resolve()
        if start_p.name == "tasks" and start_p.is_dir():
            start_p = start_p.parent
        if orchestration_registry is not None and hasattr(orchestration_registry, "resolve_workspace_for_path"):
            try:
                ws_reg, _ = orchestration_registry.resolve_workspace_for_path(start_p)
                if ws_reg:
                    ws_root = pathlib.Path(ws_reg["canonical_path"]).resolve()
                    ws_slug = ws_reg["slug"]
            except Exception:
                ws_reg = None
        if ws_root is None:
            curr: pathlib.Path | None = start_p
            ws_root = start_p
            ws_slug = start_p.name
            while curr and curr != curr.parent:
                for cfg in (".ai-orchestration.local.toml", "orchestration.toml"):
                    if (curr / cfg).is_file():
                        ws_root = curr
                        ws_slug = curr.name
                        break
                if ws_root != start_p:
                    break
                curr = curr.parent

    projects: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    used_slugs: set[str] = set()

    # 1. Registered projects in SQLite if available
    if ws_slug and orchestration_registry is not None and hasattr(orchestration_registry, "list_projects"):
        try:
            proj_data = orchestration_registry.list_projects(ws_slug)
            for item in proj_data.get("items", []):
                if item.get("kind") == "sub_workspace":
                    continue
                p_slug = item.get("slug")
                rel_p = item.get("path", "")
                norm_rel = os.path.normpath(rel_p)
                t_dir = (ws_root / rel_p / "tasks").resolve() if rel_p not in (".", "") else (ws_root / "tasks").resolve()
                if t_dir.is_dir():
                    is_ws = (p_slug == "_workspace" or norm_rel == ".")
                    eff_slug = "_workspace" if is_ws else p_slug
                    seen_paths.add(norm_rel)
                    used_slugs.add(eff_slug)
                    projects.append({
                        "slug": eff_slug,
                        "path": rel_p,
                        "tasks_dir": t_dir,
                        "kind": "_workspace" if is_ws else "project",
                        "scope": "workspace" if is_ws else "project",
                    })
        except Exception:
            pass

    # 2. Check orchestration.toml or .ai-orchestration.local.toml at ws_root
    for cfg_name in (".ai-orchestration.local.toml", "orchestration.toml"):
        cfg_file = ws_root / cfg_name
        if cfg_file.is_file() and tomllib is not None:
            try:
                cfg_dict = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
                toml_projs = cfg_dict.get("workspace", {}).get("projects", [])
                for p in toml_projs:
                    rel_p = p.get("path", "")
                    norm_rel = os.path.normpath(rel_p)
                    if norm_rel in seen_paths:
                        continue
                    p_slug = p.get("id") or p.get("slug") or (pathlib.Path(rel_p).name if rel_p != "." else "_workspace")
                    t_dir = (ws_root / rel_p / "tasks").resolve() if rel_p not in (".", "") else (ws_root / "tasks").resolve()
                    if t_dir.is_dir():
                        is_ws = (p_slug == "_workspace" or norm_rel == ".")
                        eff_slug = "_workspace" if is_ws else p_slug
                        seen_paths.add(norm_rel)
                        used_slugs.add(eff_slug)
                        projects.append({
                            "slug": eff_slug,
                            "path": rel_p,
                            "tasks_dir": t_dir,
                            "kind": "_workspace" if is_ws else "project",
                            "scope": "workspace" if is_ws else "project",
                        })
            except Exception:
                pass

    # 3. Check root tasks/ (_workspace)
    if "." not in seen_paths:
        root_tasks = ws_root / "tasks"
        if (root_tasks / "00-INDEX.md").is_file() or root_tasks.is_dir():
            seen_paths.add(".")
            used_slugs.add("_workspace")
            projects.append({
                "slug": "_workspace",
                "path": ".",
                "tasks_dir": root_tasks.resolve(),
                "kind": "_workspace",
                "scope": "workspace",
            })

    # 4. Scan child directories for tasks/
    exclude_dirs = {
        "node_modules", "build", "dist", "target", "venv", ".venv",
        "scratch", "fixtures", "references", "__pycache__"
    }
    for root, dirs, _ in os.walk(str(ws_root)):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in exclude_dirs]
        for d in list(dirs):
            folder_p = (pathlib.Path(root) / d).resolve()
            if folder_p == ws_root:
                continue
            index_file = folder_p / "tasks" / "00-INDEX.md"
            cand_tasks = folder_p / "tasks"
            if index_file.is_file() or cand_tasks.is_dir():
                dirs.remove(d)
                rel_path = str(folder_p.relative_to(ws_root))
                norm_rel = os.path.normpath(rel_path)
                if norm_rel not in seen_paths:
                    seen_paths.add(norm_rel)
                    raw_slug = folder_p.name
                    p_slug = raw_slug
                    suffix = 2
                    while p_slug in used_slugs:
                        p_slug = f"{raw_slug}-{suffix}"
                        suffix += 1
                    used_slugs.add(p_slug)
                    projects.append({
                        "slug": p_slug,
                        "path": rel_path,
                        "tasks_dir": cand_tasks.resolve(),
                        "kind": "project",
                        "scope": "project",
                    })

    projects.sort(key=lambda p: (0 if p["slug"] == "_workspace" else 1, p["path"]))
    return ws_root, ws_slug or "workspace", projects


# ---------------------------------------------------------------------------
# CLI Subcommands
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    workspace_arg = getattr(args, "workspace", None)
    all_projects = getattr(args, "all_projects", False)

    kind_set = _clean_filter_set(getattr(args, "kind", None))
    label_set = _clean_filter_set(getattr(args, "label", None))
    state_filter = getattr(args, "state", None)
    active_only = getattr(args, "active_only", False)
    limit = getattr(args, "limit", None)

    def _matches_filters(t: dict[str, Any], node_tree: dict[str, TaskNode]) -> bool:
        node = node_tree.get(t.get("id", ""))
        tk = (node.kind if node and node.kind else (t.get("headers", {}).get("kind") or t.get("kind") or "")).strip().lower()
        if tk in ("emergent", "initiative", "initiative_task", "emergent_child"):
            tk = (t.get("headers", {}).get("kind") or "").strip().lower()
        if kind_set is not None:
            if not tk or tk not in kind_set:
                return False
        if label_set is not None:
            t_labels = list(node.labels) if node else t.get("labels", [])
            if isinstance(t_labels, str):
                t_labels = [x.strip().lower() for x in t_labels.split(",") if x.strip()]
            else:
                t_labels = [str(x).strip().lower() for x in t_labels if str(x).strip()]
            if not any(x in label_set for x in t_labels):
                return False
        if active_only:
            if t.get("in_done"):
                return False
            cst = (t.get("canonical_state") or t.get("state") or "").strip().lower()
            if cst in TERMINAL_STATES:
                return False
        if state_filter is not None:
            st = (t.get("state") or "").strip().lower()
            cst = (t.get("canonical_state") or "").strip().lower()
            tgt = state_filter.strip().lower()
            if st != tgt and cst != tgt:
                return False
        return True

    if workspace_arg is not None or all_projects:
        td_val = getattr(args, "tasks_dir", None)
        td_path = pathlib.Path(td_val) if td_val and td_val != "tasks" else None
        try:
            ws_root, ws_slug, projects = resolve_workspace_and_projects(
                workspace_arg=workspace_arg,
                tasks_dir=td_path,
            )
        except Exception as e:
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "error": str(e)}, indent=2))
            else:
                print(f"[FAIL] {e}", file=sys.stderr)
            return 2

        all_tasks_combined: list[dict[str, Any]] = []
        all_emergent_combined: list[dict[str, Any]] = []
        all_initiatives_combined: list[dict[str, Any]] = []
        trees_combined: dict[str, Any] = {}

        for proj in projects:
            p_tasks_dir = proj["tasks_dir"]
            if not p_tasks_dir.is_dir():
                continue
            p_slug = proj["slug"]
            p_scope = proj["scope"]

            p_tree = discover_task_tree(p_tasks_dir)
            p_emergent = discover_emergent_tasks(p_tasks_dir)
            p_initiatives = discover_initiatives(p_tasks_dir, p_tree)
            p_tree_dicts = {nid: node.to_dict() for nid, node in p_tree.items()}
            trees_combined[p_slug] = p_tree_dicts

            p_tasks = _build_tasks_list(p_tasks_dir, p_tree, p_emergent, p_initiatives, p_tree_dicts)

            for t in p_tasks:
                if _matches_filters(t, p_tree):
                    t_copy = dict(t)
                    t_copy["project"] = p_slug
                    t_copy["qualified_id"] = f"{p_slug}/{t_copy['id']}"
                    t_copy["scope"] = p_scope
                    all_tasks_combined.append(t_copy)

            for et in p_emergent:
                if _matches_filters(et, p_tree):
                    et_copy = dict(et)
                    et_copy["project"] = p_slug
                    et_copy["qualified_id"] = f"{p_slug}/{et_copy['id']}"
                    et_copy["scope"] = p_scope
                    all_emergent_combined.append(et_copy)

            for init in p_initiatives:
                init_copy = dict(init)
                matching_subs = [st for st in init.get("tasks", []) if _matches_filters(st, p_tree)]
                if matching_subs or _matches_filters(init, p_tree):
                    init_copy["tasks"] = matching_subs
                    init_copy["project"] = p_slug
                    init_copy["qualified_id"] = f"{p_slug}/INIT-{init_copy['id']}"
                    init_copy["scope"] = p_scope
                    all_initiatives_combined.append(init_copy)

        def _task_sort_key(t: dict[str, Any]):
            p_rank = PRIORITY_SORT_KEY.get(t.get("priority", "P2"), 99)
            nu_rank = 0 if t.get("next_up") == "yes" else 1
            qid = t.get("qualified_id", t.get("id", ""))
            return (p_rank, nu_rank, qid)

        all_tasks_combined.sort(key=_task_sort_key)

        if limit is not None and limit > 0:
            all_tasks_combined = all_tasks_combined[:limit]

        payload = {
            "ok": True,
            "workspace": ws_slug,
            "workspace_root": str(ws_root),
            "projects": [p["slug"] for p in projects],
            "all_tasks": all_tasks_combined,
            "tasks": all_tasks_combined,
            "emergent_tasks": all_emergent_combined,
            "initiatives": all_initiatives_combined,
            "trees": trees_combined,
            "tree": trees_combined.get("_workspace", {}),
        }
        if (ws_root / "tasks").is_dir():
            payload["tasks_dir"] = str(ws_root / "tasks")
        else:
            payload["tasks_dir"] = str(ws_root)

        args._last_result = payload
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            print(f"Workspace  : {ws_slug} ({ws_root})")
            print(f"Projects   : {len(projects)} ({', '.join(p['slug'] for p in projects)})")
            print(f"Initiatives: {len(all_initiatives_combined)}")
            print(f"Emergent   : {len(all_emergent_combined)}")
            print(f"Total tasks: {len(all_tasks_combined)}")
            for t in all_tasks_combined:
                qid = t.get("qualified_id", t["id"])
                pri = t.get("priority", "P2")
                st = t.get("state", "open")
                print(f"  [{pri}] {qid} ({st}) - {t.get('title', '')}")
        return 0

    # Single-project path
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    tree = discover_task_tree(tasks_dir)
    emergent = discover_emergent_tasks(tasks_dir)
    initiatives = discover_initiatives(tasks_dir, tree)
    tree_dicts = {nid: node.to_dict() for nid, node in tree.items()}

    all_tasks = _build_tasks_list(tasks_dir, tree, emergent, initiatives, tree_dicts)

    all_tasks = [t for t in all_tasks if _matches_filters(t, tree)]
    emergent = [t for t in emergent if _matches_filters(t, tree)]
    filtered_inits = []
    for init in initiatives:
        init_copy = dict(init)
        matching_subtasks = [st for st in init.get("tasks", []) if _matches_filters(st, tree)]
        if matching_subtasks or _matches_filters(init, tree):
            init_copy["tasks"] = matching_subtasks
            filtered_inits.append(init_copy)
    initiatives = filtered_inits

    if limit is not None and limit > 0:
        all_tasks = all_tasks[:limit]

    payload = {
        "ok": True,
        "tasks_dir": str(tasks_dir),
        "tree": tree_dicts,
        "all_tasks": all_tasks,
        "tasks": all_tasks,
        "emergent_tasks": emergent,
        "initiatives": initiatives,
    }
    args._last_result = payload
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"Tasks dir  : {tasks_dir}")
        print(f"Initiatives: {len(initiatives)}")
        for init in initiatives:
            print(f"  [{init['id']}] {init['title']} ({init['location']}, {len(init['tasks'])} tasks, state={init['status']})")
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
    expect_task_hash = getattr(args, "expect_task_hash", None)
    force_unblock = getattr(args, "force_unblock", False)
    is_json = getattr(args, "json", False)

    pos_state = getattr(args, "new_state", None)
    flag_state = getattr(args, "to_state", None)

    if pos_state and flag_state:
        if pos_state != flag_state:
            err_msg = f"Conflicting target states provided: positional '{pos_state}' vs --to '{flag_state}'."
            if is_json:
                print(json.dumps({"ok": False, "error": "conflicting-states", "message": err_msg}, indent=2))
            else:
                print(f"[FAIL] {err_msg}", file=sys.stderr)
            return 2
        effective_new_state = pos_state
    elif pos_state:
        effective_new_state = pos_state
    elif flag_state:
        effective_new_state = flag_state
    else:
        err_msg = "Missing target state: provide either positional <state> or --to <state>."
        if is_json:
            print(json.dumps({"ok": False, "error": "missing-state", "message": err_msg}, indent=2))
        else:
            print(f"[FAIL] {err_msg}", file=sys.stderr)
        return 2

    ok, payload = transition_task(
        tasks_dir=tasks_dir,
        task_id=args.task_id,
        new_state=effective_new_state,
        actor=args.actor,
        verifier=args.verifier,
        reason=args.reason,
        expect_task_hash=expect_task_hash,
        force_unblock=force_unblock,
        waiting_on=getattr(args, "waiting_on", None),
        verify_by=getattr(args, "verify_by", None),
        verify_check=getattr(args, "verify_check", None),
    )
    args._last_result = payload
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        if ok:
            print(f"[ok] {args.task_id}: {payload['old_state']!r} -> {payload['new_state']!r} ({payload['rel_path']})")
        else:
            err = payload.get("error", "transition failed")
            if "expected" in payload and "actual" in payload:
                print(f"[FAIL] {err}: expected {payload['expected']}, got {payload['actual']}", file=sys.stderr)
            elif "message" in payload:
                print(f"[FAIL] {err}: {payload['message']}", file=sys.stderr)
            else:
                print(f"[FAIL] {err}", file=sys.stderr)
    return 0 if ok else 1


def cmd_close(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    task_id = getattr(args, "task_id", None) or getattr(args, "id", None)
    verifier = getattr(args, "verifier", None)
    reason = getattr(args, "reason", None)
    actor = getattr(args, "actor", None)
    owner_approved = getattr(args, "owner_approved", False)
    caveat = getattr(args, "caveat", None)

    ok, payload = close_task(
        tasks_dir=tasks_dir,
        task_id=task_id,
        actor=actor,
        verifier=verifier,
        reason=reason,
        owner_approved=owner_approved,
        caveat=caveat,
    )
    args._last_result = payload
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        if ok:
            print(f"[ok] Closed {task_id}: {payload['old_state']!r} -> {payload['new_state']!r} ({payload.get('rel_path', '')})")
        else:
            err = payload.get("error", "close failed")
            if "message" in payload:
                print(f"[FAIL] {err}: {payload['message']}", file=sys.stderr)
            else:
                print(f"[FAIL] {err}", file=sys.stderr)
    return 0 if ok else 1


def cmd_child_add(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_plan_hash = getattr(args, "expect_plan_hash", None)
    res = child_add(
        tasks_dir=tasks_dir,
        parent_id=args.parent,
        title=args.title,
        kind=getattr(args, "kind", "feature"),
        dry_run=dry_run,
        expect_plan_hash=expect_plan_hash,
        short=getattr(args, "short", None),
    )
    args._last_result = res
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            action = "planned" if dry_run else "added"
            print(f"[ok] {action} child task {res.get('allocated_id')} under {args.parent}")
        else:
            print(f"[FAIL] {res.get('error', 'child add failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_expand(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_plan_hash = getattr(args, "expect_plan_hash", None)
    res = expand_node(
        tasks_dir=tasks_dir,
        node_id=args.id,
        dry_run=dry_run,
        expect_plan_hash=expect_plan_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            action = "planned expansion of" if dry_run else "expanded"
            print(f"[ok] {action} {args.id} into folder")
        else:
            print(f"[FAIL] {res.get('error', 'expand failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_collapse(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_plan_hash = getattr(args, "expect_plan_hash", None)
    res = collapse_node(
        tasks_dir=tasks_dir,
        node_id=args.id,
        dry_run=dry_run,
        expect_plan_hash=expect_plan_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            action = "planned collapse of" if dry_run else "collapsed"
            print(f"[ok] {action} {args.id} back to block")
        else:
            print(f"[FAIL] {res.get('error', 'collapse failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_reopen(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_plan_hash = getattr(args, "expect_plan_hash", None)
    res = reopen_node(
        tasks_dir=tasks_dir,
        node_id=args.id,
        reason=args.reason,
        dry_run=dry_run,
        expect_plan_hash=expect_plan_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            action = "planned reopening of" if dry_run else "reopened"
            print(f"[ok] {action} {args.id}")
        else:
            print(f"[FAIL] {res.get('error', 'reopen failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_ship(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_plan_hash = getattr(args, "expect_plan_hash", None)
    res = ship_initiative(
        tasks_dir=tasks_dir,
        init_id=args.id,
        dry_run=dry_run,
        expect_plan_hash=expect_plan_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            action = "planned shipping of" if dry_run else "shipped"
            print(f"[ok] {action} initiative {args.id} -> {res.get('folder')}")
        else:
            print(f"[FAIL] {res.get('error', 'ship failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_archive(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_plan_hash = getattr(args, "expect_plan_hash", None)
    res = archive_misplaced(
        tasks_dir=tasks_dir,
        dry_run=dry_run,
        expect_plan_hash=expect_plan_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            if res.get("plan"):
                action = "planned archiving of" if dry_run else "archived"
                count = res.get("archived_count", len(res["plan"]))
                print(f"[ok] {action} {count} item(s)")
            else:
                print(f"[ok] {res.get('message', 'Nothing to archive.')}")
        else:
            print(f"[FAIL] {res.get('error', 'archive failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_graph(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    graph_data = compute_tasks_graph(
        tasks_dir,
        kind_filter=getattr(args, "kind", None),
        label_filter=getattr(args, "label", None),
    )
    if getattr(args, "mermaid", False):
        print(render_mermaid_graph(graph_data, tasks_dir=tasks_dir, include_closed=getattr(args, "all", False)), end="")
    elif getattr(args, "json", False):
        print(json.dumps(graph_data, indent=2))
    else:
        totals = graph_data["totals"]
        print(f"Tasks Graph ({tasks_dir.name}/)")
        print("=" * (len(tasks_dir.name) + 14))
        print(f"Totals: {totals['overall']} ({totals['total_open']} open leaves, {totals['total_leaves']} total)")
        st_parts = [f"{v} {k}" for k, v in sorted(totals["by_state"].items())]
        print(f"States: {', '.join(st_parts)}")
        print("\nReady Queue (Column 0):")
        nodes_by_id = graph_data["nodes_by_id"]
        for idx, qid in enumerate(graph_data["ready_queue"], 1):
            n = nodes_by_id.get(qid, {})
            print(f"  {idx}. [{n.get('priority', 'P2')}] {qid} - {n.get('title', '')} (size: {n.get('size', 'M')})")
        print("\nColumns:")
        col_groups: dict[int, list[str]] = {}
        for nid, col in sorted(graph_data["columns"].items(), key=lambda x: (x[1], _natural_sort_key(x[0]))):
            col_groups.setdefault(col, []).append(nid)
        for col in sorted(col_groups.keys()):
            tasks_str = ", ".join(col_groups[col])
            print(f"  Col {col}: {tasks_str}")
        print("\nHeaviest Chain:")
        if graph_data["heaviest_chain"]:
            chain_parts = [f"{cid} ({nodes_by_id.get(cid, {}).get('size', 'M')})" for cid in graph_data["heaviest_chain"]]
            print(f"  {' -> '.join(chain_parts)} (total weight: {graph_data['heaviest_chain_weight']})")
        else:
            print("  (empty)")
    return 0


def cmd_set_priority(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_task_hash = getattr(args, "expect_task_hash", None)
    res = set_priority(
        tasks_dir=tasks_dir,
        node_id=args.id,
        priority=args.priority,
        reason=getattr(args, "reason", None),
        dry_run=dry_run,
        expect_task_hash=expect_task_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if dry_run:
            if res.get("ok"):
                diff = res.get("diff", "")
                if diff:
                    print(diff, end="")
                else:
                    print(f"[dry-run] no changes for {args.id}")
            else:
                print(f"[FAIL] {res.get('error', 'set-priority failed')}", file=sys.stderr)
        else:
            if res.get("ok"):
                print(f"[ok] updated priority for {args.id}: {res.get('priority')}")
            else:
                print(f"[FAIL] {res.get('error', 'set-priority failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_set_size(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_task_hash = getattr(args, "expect_task_hash", None)
    res = set_size(
        tasks_dir=tasks_dir,
        node_id=args.id,
        size=args.size,
        dry_run=dry_run,
        expect_task_hash=expect_task_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if dry_run:
            if res.get("ok"):
                diff = res.get("diff", "")
                if diff:
                    print(diff, end="")
                else:
                    print(f"[dry-run] no changes for {args.id}")
            else:
                print(f"[FAIL] {res.get('error', 'set-size failed')}", file=sys.stderr)
        else:
            if res.get("ok"):
                print(f"[ok] updated size for {args.id}: {res.get('size')}")
            else:
                print(f"[FAIL] {res.get('error', 'set-size failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_set_deps(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_task_hash = getattr(args, "expect_task_hash", None)
    pos_deps = getattr(args, "deps", None)
    to_ids = getattr(args, "to", None)
    if to_ids is None and pos_deps:
        to_ids = pos_deps
    res = set_deps(
        tasks_dir=tasks_dir,
        node_id=args.id,
        add_ids=getattr(args, "add", None),
        remove_ids=getattr(args, "remove", None),
        to_ids=to_ids,
        expect_task_hash=expect_task_hash,
        dry_run=dry_run,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if dry_run:
            if res.get("ok"):
                diff = res.get("diff", "")
                if diff:
                    print(diff, end="")
                else:
                    print(f"[dry-run] no changes for {args.id}")
            else:
                print(f"[FAIL] {res.get('error', 'set-deps failed')}", file=sys.stderr)
        else:
            if res.get("ok"):
                print(f"[ok] updated dependencies for {args.id}: {res.get('depends_on')}")
            else:
                print(f"[FAIL] {res.get('error', 'set-deps failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_set_labels(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    expect_task_hash = getattr(args, "expect_task_hash", None)
    dry_run = getattr(args, "dry_run", False)
    res = set_labels(
        tasks_dir=tasks_dir,
        node_id=args.id,
        add_labels=getattr(args, "add", None),
        remove_labels=getattr(args, "remove", None),
        to_labels=getattr(args, "to", None),
        expect_task_hash=expect_task_hash,
        dry_run=dry_run,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            if res.get("dry_run"):
                print(f"[ok] dry-run: labels for {args.id} would become: {res.get('labels')}")
                if res.get("diff"):
                    print(res.get("diff"), end="")
            else:
                print(f"[ok] updated labels for {args.id}: {res.get('labels')}")
        else:
            print(f"[FAIL] {res.get('error', 'set-labels failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def _parse_bulk_short_source(source: str) -> list[tuple[str, str]]:
    raw = source.strip()
    if raw == "-":
        content = sys.stdin.read()
    elif pathlib.Path(raw).is_file():
        content = pathlib.Path(raw).read_text(encoding="utf-8")
    else:
        content = raw

    content = content.strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return [(str(k).strip(), str(v).strip()) for k, v in data.items() if str(k).strip()]
        elif isinstance(data, list):
            items: list[tuple[str, str]] = []
            for entry in data:
                if isinstance(entry, dict):
                    k = entry.get("id") or entry.get("task_id") or entry.get("node_id")
                    v = entry.get("short") or entry.get("short_title") or entry.get("title")
                    if k and v:
                        items.append((str(k).strip(), str(v).strip()))
            return items
    except (json.JSONDecodeError, ValueError):
        pass

    items = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            items.append((k.strip(), v.strip()))
        elif ":" in line:
            k, v = line.split(":", 1)
            items.append((k.strip(), v.strip()))
    return items


def cmd_set_short(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    from_source = getattr(args, "from_source", None)
    expect_task_hash = getattr(args, "expect_task_hash", None)
    dry_run = getattr(args, "dry_run", False)
    is_json = getattr(args, "json", False)

    if from_source is not None:
        try:
            pairs = _parse_bulk_short_source(from_source)
        except Exception as e:
            err_msg = f"Failed parsing --from source: {e}"
            if is_json:
                print(json.dumps({"ok": False, "error": err_msg}, indent=2))
            else:
                print(f"[FAIL] {err_msg}", file=sys.stderr)
            return 2

        if not pairs:
            err_msg = "No short title pairs found in --from source."
            if is_json:
                print(json.dumps({"ok": False, "error": err_msg}, indent=2))
            else:
                print(f"[FAIL] {err_msg}", file=sys.stderr)
            return 2

        updated: list[dict[str, Any]] = []
        with task_write_lock(tasks_dir):
            for item_id, short_title in pairs:
                res = set_short(
                    tasks_dir=tasks_dir,
                    node_id=item_id,
                    short_title=short_title,
                    dry_run=dry_run,
                    expect_task_hash=expect_task_hash,
                )
                if not res.get("ok"):
                    err_msg = f"Failed setting short title on {item_id}: {res.get('error')}"
                    args._last_result = {"ok": False, "error": err_msg, "failed_id": item_id, "updated": updated}
                    if is_json:
                        print(json.dumps(args._last_result, indent=2))
                    else:
                        print(f"[FAIL] {err_msg}", file=sys.stderr)
                    return 1
                th = res.get("new_task_hash") or res.get("task_hash")
                updated.append({"id": item_id, "short_title": short_title, "task_hash": th})

            if not dry_run and updated:
                idx_path = tasks_dir / "00-INDEX.md"
                if idx_path.is_file():
                    existing_idx = idx_path.read_text(encoding="utf-8")
                    rendered_idx = render_synced_index(tasks_dir, existing_idx, adopt=True)
                    _atomic_write_text(idx_path, rendered_idx, encoding="utf-8")

        payload = {"ok": True, "updated": updated}
        args._last_result = payload
        if is_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[ok] Updated short title for {len(updated)} item(s)")
            for u in updated:
                print(f"  - {u['id']}: {u['short_title']}")
        return 0

    if not getattr(args, "id", None) or not getattr(args, "short", None):
        err_msg = "Both item ID and short title are required unless --from is provided."
        if is_json:
            print(json.dumps({"ok": False, "error": err_msg}, indent=2))
        else:
            print(f"[FAIL] {err_msg}", file=sys.stderr)
        return 2

    res = set_short(
        tasks_dir=tasks_dir,
        node_id=args.id,
        short_title=args.short,
        dry_run=dry_run,
        expect_task_hash=expect_task_hash,
    )
    if res.get("task_hash") and "plan_hash" not in res:
        res["plan_hash"] = res["task_hash"]  # same name the UI/VS Code bridges use for the other set-* commands
    args._last_result = res
    if is_json:
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            if res.get("dry_run"):
                print(f"[ok] dry-run: short title for {args.id} would become: {res.get('short')}")
                if res.get("diff"):
                    print(res.get("diff"), end="")
            else:
                print(f"[ok] updated short title for {args.id}: {res.get('short')}")
        else:
            print(f"[FAIL] {res.get('error', 'set-short failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_set_waiting_on(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_task_hash = getattr(args, "expect_task_hash", None)
    is_json = getattr(args, "json", False)

    res = set_waiting_on(
        tasks_dir=tasks_dir,
        node_id=args.id,
        waiting_on=args.waiting_on,
        dry_run=dry_run,
        expect_task_hash=expect_task_hash,
    )
    if res.get("task_hash") and "plan_hash" not in res:
        res["plan_hash"] = res["task_hash"]
    args._last_result = res
    if is_json:
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            if res.get("dry_run"):
                print(f"[ok] dry-run: waiting-on for {args.id} would become: {res.get('waiting_on')}")
                if res.get("diff"):
                    print(res.get("diff"), end="")
            else:
                print(f"[ok] updated waiting-on for {args.id}: {res.get('waiting_on')}")
        else:
            print(f"[FAIL] {res.get('error', 'set-waiting-on failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_set_executor(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_task_hash = getattr(args, "expect_task_hash", None)
    is_json = getattr(args, "json", False)

    res = set_executor(
        tasks_dir=tasks_dir,
        node_id=args.id,
        executor=args.executor,
        dry_run=dry_run,
        expect_task_hash=expect_task_hash,
    )
    if res.get("task_hash") and "plan_hash" not in res:
        res["plan_hash"] = res["task_hash"]
    args._last_result = res
    if is_json:
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            if res.get("dry_run"):
                print(f"[ok] dry-run: executor for {args.id} would become: {res.get('executor')}")
                if res.get("diff"):
                    print(res.get("diff"), end="")
            else:
                print(f"[ok] updated executor for {args.id}: {res.get('executor')}")
        else:
            print(f"[FAIL] {res.get('error', 'set-executor failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_set_verify_by(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    expect_task_hash = getattr(args, "expect_task_hash", None)
    is_json = getattr(args, "json", False)
    target = getattr(args, "target", None) or getattr(args, "by_target", None)
    check = getattr(args, "check", None)

    if not target:
        err_msg = "Missing target: provide <target> (or --by <target>)."
        if is_json:
            print(json.dumps({"ok": False, "error": "missing-target", "message": err_msg}, indent=2))
        else:
            print(f"[FAIL] {err_msg}", file=sys.stderr)
        return 2

    res = set_verify_by(
        tasks_dir=tasks_dir,
        node_id=args.id,
        verify_by=target,
        check=check,
        dry_run=dry_run,
        expect_task_hash=expect_task_hash,
    )
    if res.get("task_hash") and "plan_hash" not in res:
        res["plan_hash"] = res["task_hash"]
    args._last_result = res
    if is_json:
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            if res.get("dry_run"):
                print(f"[ok] dry-run: verify-by for {args.id} would become: {res.get('verify_by')}")
                if res.get("diff"):
                    print(res.get("diff"), end="")
            else:
                print(f"[ok] updated verify-by for {args.id}: {res.get('verify_by')}")
        else:
            print(f"[FAIL] {res.get('error', 'set-verify-by failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def match_verify_by(task_verify_by: str | None, target: str | None) -> bool:
    if not task_verify_by or not str(task_verify_by).strip() or str(task_verify_by).strip() == "-":
        return False
    if not target or not str(target).strip() or str(target).strip() == "-":
        return True
    tv = str(task_verify_by).strip()
    tgt = str(target).strip()
    if tv.lower() == tgt.lower():
        return True

    tv_bare = tv[len("workspace:"):].strip() if tv.lower().startswith("workspace:") else tv
    tgt_bare = tgt[len("workspace:"):].strip() if tgt.lower().startswith("workspace:") else tgt
    if tv_bare.lower() == tgt_bare.lower():
        return True

    if tgt.lower().startswith("session:"):
        tgt_prefix = tgt[len("session:"):].rstrip("*").lower()
        if tv.lower().startswith("session:"):
            cand_sess = tv[len("session:"):].lower()
            if cand_sess.startswith(tgt_prefix):
                return True
        elif tv.lower().startswith(tgt_prefix):
            return True
    elif tv.lower().startswith("session:"):
        cand_sess = tv[len("session:"):].lower()
        if cand_sess.startswith(tgt_bare.lower()):
            return True

    return False


def collect_task_dirs_to_scan(
    tasks_dir: pathlib.Path,
    workspace_arg: str | None = None,
    all_workspaces: bool = False,
    for_target: str | None = None,
) -> list[tuple[str, str, pathlib.Path]]:
    """Collect (workspace_slug, project_slug, tasks_dir_path) to scan."""
    tasks_dir = tasks_dir.resolve()
    seen_dirs: set[pathlib.Path] = set()
    results: list[tuple[str, str, pathlib.Path]] = []

    ws_root: pathlib.Path | None = None
    ws_slug: str | None = None
    try:
        ws_root, ws_slug, projects = resolve_workspace_and_projects(
            workspace_arg=workspace_arg, tasks_dir=tasks_dir
        )
        for p in projects:
            td = p["tasks_dir"].resolve()
            if td.is_dir() and td not in seen_dirs:
                seen_dirs.add(td)
                results.append((ws_slug, p["slug"], td))
    except Exception:
        td = tasks_dir.resolve()
        if td.is_dir() and td not in seen_dirs:
            seen_dirs.add(td)
            ws_name = td.parent.name if td.name == "tasks" else td.name
            results.append((ws_name, "_workspace", td))

    if for_target is not None or all_workspaces:
        if orchestration_registry is not None and hasattr(orchestration_registry, "list_workspaces"):
            try:
                ws_list = orchestration_registry.list_workspaces()
                for w in ws_list:
                    w_path = pathlib.Path(w["canonical_path"]).resolve()
                    if w_path.is_dir():
                        try:
                            _, w_slug_reg, w_projects = resolve_workspace_and_projects(
                                workspace_arg=str(w_path)
                            )
                            eff_ws_slug = w.get("slug") or w_slug_reg or w_path.name
                            for p in w_projects:
                                td = p["tasks_dir"].resolve()
                                if td.is_dir() and td not in seen_dirs:
                                    seen_dirs.add(td)
                                    results.append((eff_ws_slug, p["slug"], td))
                        except Exception:
                            cand_td = (w_path / "tasks").resolve()
                            if cand_td.is_dir() and cand_td not in seen_dirs:
                                seen_dirs.add(cand_td)
                                results.append((w.get("slug") or w_path.name, "_workspace", cand_td))
            except Exception:
                pass

        parent_dirs: list[pathlib.Path] = []
        if ws_root is not None:
            parent_dirs.append(ws_root.parent)
        cand_parent = tasks_dir.parent
        if cand_parent.name == "tasks":
            cand_parent = cand_parent.parent
        if cand_parent.parent not in parent_dirs:
            parent_dirs.append(cand_parent.parent)

        for pdir in parent_dirs:
            if not pdir.is_dir():
                continue
            try:
                for child in sorted(pdir.iterdir()):
                    if (
                        child.is_dir()
                        and not child.name.startswith(".")
                        and child != ws_root
                        and child.name not in ("node_modules", "target", "build", "dist", "venv", ".venv", "__pycache__")
                    ):
                        cand_tasks = child / "tasks"
                        if (cand_tasks / "00-INDEX.md").is_file() or cand_tasks.is_dir():
                            try:
                                _, sib_slug, sib_projects = resolve_workspace_and_projects(
                                    workspace_arg=str(child)
                                )
                                for sp in sib_projects:
                                    td = sp["tasks_dir"].resolve()
                                    if td.is_dir() and td not in seen_dirs:
                                        seen_dirs.add(td)
                                        results.append((sib_slug or child.name, sp["slug"], td))
                            except Exception:
                                td = cand_tasks.resolve()
                                if td.is_dir() and td not in seen_dirs:
                                    seen_dirs.add(td)
                                    results.append((child.name, "_workspace", td))
            except Exception:
                pass

    return results


def get_verification_queue(
    tasks_dir: pathlib.Path,
    target: str | None = None,
    workspace_arg: str | None = None,
    all_workspaces: bool = False,
) -> dict[str, Any]:
    task_dirs = collect_task_dirs_to_scan(
        tasks_dir=tasks_dir,
        workspace_arg=workspace_arg,
        all_workspaces=all_workspaces,
        for_target=target,
    )
    items: list[dict[str, Any]] = []
    seen_tasks: set[tuple[str, str, str]] = set()

    for ws_slug, p_slug, td in task_dirs:
        if not td.is_dir():
            continue

        emergent = discover_emergent_tasks(td)
        for t in emergent:
            t_id = t["id"]
            if (ws_slug, p_slug, t_id) in seen_tasks:
                continue
            cstate = t.get("canonical_state") or normalize_state(t.get("state", ""))
            if cstate == "delivered":
                vb = (
                    t.get("verify_by")
                    or t.get("verify-by")
                    or t.get("headers", {}).get("verify-by")
                    or t.get("headers", {}).get("verify_by")
                    or t.get("verifier")
                )
                if vb and str(vb).strip() and str(vb).strip() != "-":
                    vb_str = str(vb).strip()
                    if match_verify_by(vb_str, target):
                        seen_tasks.add((ws_slug, p_slug, t_id))
                        t_title = t.get("title", "")
                        t_short = t.get("short_title") or derive_short_title(t_title)
                        t_exec = t.get("executor") or "unassigned"
                        if p_slug in ("_workspace", ws_slug):
                            qid = f"workspace:{ws_slug}/{t_id}"
                        else:
                            qid = f"workspace:{ws_slug}/{p_slug}/{t_id}"
                        items.append({
                            "id": t_id,
                            "qualified_id": qid,
                            "workspace": ws_slug,
                            "project": p_slug,
                            "title": t_title,
                            "short_title": t_short,
                            "state": "delivered",
                            "verify_by": vb_str,
                            "executor": t_exec,
                            "tasks_dir": str(td),
                            "priority": t.get("priority", "P2"),
                        })

        try:
            tree = discover_task_tree(td)
            for nid, node in tree.items():
                if not node.is_leaf:
                    continue
                if (ws_slug, p_slug, nid) in seen_tasks:
                    continue
                cstate = node.canonical_state or normalize_state(node.state)
                if cstate == "delivered":
                    vb = (
                        getattr(node, "verify_by", None)
                        or node.own_fields.get("verify_by")
                        or node.own_fields.get("verify-by")
                        or node.fields.get("verify_by", {}).get("value")
                        or node.fields.get("verify-by", {}).get("value")
                        or node.fields.get("verifier", {}).get("value")
                        or node.own_fields.get("verifier")
                    )
                    if vb and str(vb).strip() and str(vb).strip() != "-":
                        vb_str = str(vb).strip()
                        if match_verify_by(vb_str, target):
                            seen_tasks.add((ws_slug, p_slug, nid))
                            t_title = node.title
                            t_short = node.short_title or derive_short_title(t_title)
                            t_exec = node.executor or "unassigned"
                            if p_slug in ("_workspace", ws_slug):
                                qid = f"workspace:{ws_slug}/{nid}"
                            else:
                                qid = f"workspace:{ws_slug}/{p_slug}/{nid}"
                            items.append({
                                "id": nid,
                                "qualified_id": qid,
                                "workspace": ws_slug,
                                "project": p_slug,
                                "title": t_title,
                                "short_title": t_short,
                                "state": "delivered",
                                "verify_by": vb_str,
                                "executor": t_exec,
                                "tasks_dir": str(td),
                                "priority": node.priority or "P2",
                            })
        except Exception:
            pass

    def _sort_key(item: dict[str, Any]):
        pri_rank = PRIORITY_SORT_KEY.get(item.get("priority", "P2"), 99)
        return (pri_rank, item.get("workspace", ""), item.get("project", ""), _natural_sort_key(item.get("id", "")))

    items.sort(key=_sort_key)
    clean_items = []
    for it in items:
        clean_items.append({
            "id": it["id"],
            "qualified_id": it["qualified_id"],
            "workspace": it["workspace"],
            "project": it["project"],
            "title": it["title"],
            "short_title": it["short_title"],
            "state": "delivered",
            "verify_by": it["verify_by"],
            "executor": it["executor"],
            "tasks_dir": it["tasks_dir"],
        })

    return {
        "ok": True,
        "for": target,
        "count": len(clean_items),
        "items": clean_items,
    }


def cmd_verification_queue(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    target = getattr(args, "for_target", None)
    workspace_arg = getattr(args, "workspace", None)
    all_workspaces = getattr(args, "all_workspaces", False)
    is_json = getattr(args, "json", False)

    payload = get_verification_queue(
        tasks_dir=tasks_dir,
        target=target,
        workspace_arg=workspace_arg,
        all_workspaces=all_workspaces,
    )
    args._last_result = payload
    if is_json:
        print(json.dumps(payload, indent=2))
    else:
        items = payload.get("items", [])
        if not items:
            if target:
                print(f"[ok] verification queue for '{target}' is empty.")
            else:
                print("[ok] verification queue is empty.")
        else:
            hdr = f"Verification queue for '{target}' ({len(items)} items):" if target else f"Verification queue ({len(items)} items):"
            print(hdr)
            for it in items:
                qid = it.get("qualified_id", it.get("id"))
                st = it.get("short_title") or derive_short_title(it.get("title", ""))
                vb = it.get("verify_by", "-")
                exc = it.get("executor", "-")
                print(f"- {qid} ({st}): verify-by: {vb} (executor: {exc})")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    task_id = args.task_id
    tree = discover_task_tree(tasks_dir)
    emergent = discover_emergent_tasks(tasks_dir)
    task_data: dict[str, Any] | None = None
    if task_id in tree:
        task_data = tree[task_id].to_dict()
    else:
        target = next((t for t in emergent if t["id"] == task_id), None)
        if target:
            task_data = dict(target)

    if task_data is None:
        err_msg = f"Task '{task_id}' not found."
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": err_msg}, indent=2))
        else:
            print(f"[FAIL] {err_msg}", file=sys.stderr)
        return 1

    deps = task_data.get("depends_on") or []
    if isinstance(deps, str):
        deps, _ = parse_depends_on_field(deps)
    ext_deps = [d for d in deps if is_external_task_ref(d)]
    if ext_deps:
        task_data["external_dependencies"] = [
            resolve_external_task_ref(d, tasks_dir) for d in ext_deps
        ]

    executor_val = str(task_data.get("executor") or "").strip()
    if executor_val.startswith("workspace:"):
        ws_slug = executor_val[len("workspace:"):].strip().split("/")[0]
        task_data["external_executor"] = {
            "kind": "workspace",
            "workspace": ws_slug,
        }
    elif executor_val.startswith("session:"):
        task_data["external_executor"] = {
            "kind": "session",
            "session": executor_val[len("session:"):].strip(),
        }

    args._last_result = {"ok": True, "task": task_data}
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "task": task_data}, indent=2))
    else:
        print(f"Task: {task_data.get('id')} - {task_data.get('title')}")
        print(f"State: {task_data.get('state')} (canonical: {task_data.get('canonical_state')})")
        if task_data.get("waiting_on"):
            print(f"Waiting on: {task_data.get('waiting_on')}")
        if task_data.get("external_executor"):
            print(f"External executor: {task_data['external_executor']}")
        if task_data.get("external_dependencies"):
            print("External dependencies:")
            for ed in task_data["external_dependencies"]:
                st = f" ({ed.get('short_title')})" if ed.get("short_title") else ""
                print(f"  - {ed['ref']}: state={ed.get('state')}{st} (resolved={ed['resolved']})")
    return 0


def cmd_tasks_next(args: argparse.Namespace) -> int:
    workspace_arg = getattr(args, "workspace", None)
    all_projects = getattr(args, "all_projects", False)
    limit = getattr(args, "limit", None)

    if workspace_arg is not None or all_projects:
        td_val = getattr(args, "tasks_dir", None)
        td_path = pathlib.Path(td_val) if td_val and td_val != "tasks" else None
        try:
            ws_root, ws_slug, projects = resolve_workspace_and_projects(
                workspace_arg=workspace_arg,
                tasks_dir=td_path,
            )
        except Exception as e:
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "error": str(e)}, indent=2))
            else:
                print(f"[FAIL] {e}", file=sys.stderr)
            return 2

        kind_filter = getattr(args, "kind", None)
        label_filter = getattr(args, "label", None)

        all_ready_tasks: list[dict[str, Any]] = []
        coords_cache: dict[str, Any] = {}
        for proj in projects:
            p_tasks_dir = proj["tasks_dir"]
            if not p_tasks_dir.is_dir():
                continue
            try:
                graph_data = compute_tasks_graph(
                    p_tasks_dir,
                    kind_filter=kind_filter,
                    label_filter=label_filter,
                )
                ready_ids = graph_data["ready_queue"]
                nodes_by_id = graph_data["nodes_by_id"]
                for qid in ready_ids:
                    if qid not in nodes_by_id:
                        continue
                    t = dict(nodes_by_id[qid])
                    t["project"] = proj["slug"]
                    t["qualified_id"] = f"{proj['slug']}/{t['id']}"
                    t["scope"] = proj["scope"]
                    if t.get("coordinates") and (ws_root / "tasks").is_dir():
                        t["expanded_coordinates"] = resolve_coordinates(
                            t["coordinates"],
                            context_tasks_dir=ws_root / "tasks",
                            project_tree_cache=coords_cache,
                        )
                    all_ready_tasks.append(t)
            except Exception:
                pass

        # Sort results by priority (P0..P3), next_up == "yes" first, then qualified_id
        def _task_sort_key(t: dict[str, Any]):
            p_rank = PRIORITY_SORT_KEY.get(t.get("priority", "P2"), 99)
            nu_rank = 0 if t.get("next_up") == "yes" else 1
            qid = t.get("qualified_id", t.get("id", ""))
            return (p_rank, nu_rank, qid)

        all_ready_tasks.sort(key=_task_sort_key)

        if limit is not None and limit > 0:
            all_ready_tasks = all_ready_tasks[:limit]

        ready_queue = [t["qualified_id"] for t in all_ready_tasks]

        payload = {
            "ok": True,
            "workspace": ws_slug,
            "workspace_root": str(ws_root),
            "projects": [p["slug"] for p in projects],
            "ready_queue": ready_queue,
            "tasks": all_ready_tasks,
        }
        if (ws_root / "tasks").is_dir():
            payload["tasks_dir"] = str(ws_root / "tasks")
        else:
            payload["tasks_dir"] = str(ws_root)

        args._last_result = payload
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            print(f"Ready Queue ({len(all_ready_tasks)}):")
            for idx, t in enumerate(all_ready_tasks, 1):
                st = t.get("short_title", "")
                st_disp = f" ({st})" if st else ""
                qid = t.get("qualified_id", t["id"])
                print(f"  {idx}. [{t.get('priority', 'P2')}] {qid}{st_disp} - {t.get('title', '')} (size: {t.get('size', 'M')})")
        return 0

    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    graph_data = compute_tasks_graph(
        tasks_dir,
        kind_filter=getattr(args, "kind", None),
        label_filter=getattr(args, "label", None),
    )
    ready_ids = graph_data["ready_queue"]
    nodes_by_id = graph_data["nodes_by_id"]
    ready_tasks = [nodes_by_id[qid] for qid in ready_ids if qid in nodes_by_id]
    if limit is not None and limit > 0:
        ready_tasks = ready_tasks[:limit]
        ready_ids = [t["id"] for t in ready_tasks]

    payload = {
        "ok": True,
        "tasks_dir": str(tasks_dir),
        "ready_queue": ready_ids,
        "tasks": ready_tasks,
    }
    args._last_result = payload
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"Ready Queue ({len(ready_tasks)}):")
        for idx, t in enumerate(ready_tasks, 1):
            st = t.get("short_title", "")
            st_disp = f" ({st})" if st else ""
            print(f"  {idx}. [{t.get('priority', 'P2')}] {t['id']}{st_disp} - {t.get('title', '')} (size: {t.get('size', 'M')})")
    return 0


def get_next_task_id(tasks_dir: pathlib.Path) -> dict[str, Any]:
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    nums: list[int] = []

    if tasks_dir.is_dir():
        try:
            emergent = discover_emergent_tasks(tasks_dir)
            for t in emergent:
                tid = t.get("id", "")
                m = re.match(r"^T(\d+)", tid)
                if m:
                    nums.append(int(m.group(1)))
        except Exception:
            pass

        try:
            tree = discover_task_tree(tasks_dir)
            for tid in tree.keys():
                m = re.match(r"^T(\d+)", tid)
                if m:
                    nums.append(int(m.group(1)))
        except Exception:
            pass

        for p in tasks_dir.rglob("T[0-9][0-9][0-9]*"):
            if any(part.startswith(".") for part in p.parts):
                continue
            m = re.match(r"^T(\d{3,})", p.name)
            if m:
                nums.append(int(m.group(1)))

    if nums:
        highest_num = max(nums)
        highest_id = f"T{highest_num:03d}"
        next_num = highest_num + 1
        next_id = f"T{next_num:03d}"
    else:
        highest_id = None
        next_id = "T001"

    return {
        "ok": True,
        "highest_id": highest_id,
        "next_id": next_id,
    }


def cmd_tasks_next_id(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    res = get_next_task_id(tasks_dir)
    args._last_result = res
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res["highest_id"]:
            print(f"Next task ID: {res['next_id']} (highest: {res['highest_id']})")
        else:
            print(f"Next task ID: {res['next_id']}")
    return 0


def _build_index_sync_data(tasks_dir: pathlib.Path) -> dict[str, Any]:
    emergent = discover_emergent_tasks(tasks_dir)
    active_tasks = [t for t in emergent if not t.get("in_done") and t.get("canonical_state") not in TERMINAL_STATES]
    done_tasks = [t for t in emergent if t.get("in_done") or t.get("canonical_state") in TERMINAL_STATES]
    all_questions = discover_questions(tasks_dir)
    return {
        "active_tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "short_title": t.get("short_title") or derive_short_title(t["title"]),
                "short_title_source": t.get("short_title_source", "derived"),
            }
            for t in active_tasks
        ],
        "done_tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "short_title": t.get("short_title") or derive_short_title(t["title"]),
                "short_title_source": t.get("short_title_source", "derived"),
            }
            for t in done_tasks
        ],
        "questions": [
            {
                "id": q["id"],
                "title": q.get("title", ""),
                "question": q["question"],
                "short_title": q.get("short_title") or derive_short_title(q.get("title") or q["question"]),
                "short_title_source": q.get("short_title_source", "derived"),
            }
            for q in all_questions
        ],
    }


def cmd_sync_index(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    index_path = tasks_dir / "00-INDEX.md"

    adopt = getattr(args, "adopt", False)
    apply_flag = getattr(args, "apply", False)
    check_flag = getattr(args, "check", False)
    expect_hash = getattr(args, "expect_hash", None)

    # If --apply, run under exclusive task-write lock
    if apply_flag:
        if not is_platform_supported():
            err_msg = "Mutating commands are unsupported on Windows (requires fcntl for flock)."
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"ok": False, "applied": False, "error": "unsupported-platform", "message": err_msg, "path": str(index_path)},
                        indent=2,
                    )
                )
            else:
                print(f"[FAIL] unsupported-platform: {err_msg}", file=sys.stderr)
            return 1

        try:
            with task_write_lock(tasks_dir):
                existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
                current_hash = _file_sha256(index_path)

                has_conflict = ("<<<<<<<" in existing) or bool(
                    re.search(r"^(<{7}|={7}|>{7}|\|{7})\b", existing, re.MULTILINE)
                )
                if has_conflict:
                    adopt = True

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

                # 2. Check adopt + apply requires --expect-hash (unless auto-adopted due to conflict markers)
                if adopt and apply_flag and not has_conflict:
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
                if existing.strip() and not has_markers and not adopt and apply_flag and not has_conflict:
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

                # 5. Apply
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
                                "sync_data": _build_index_sync_data(tasks_dir),
                            },
                            indent=2,
                        )
                    )
                else:
                    action = "adopted and updated" if adopt else "updated"
                    print(f"[ok] {action} {index_path}")
                return 0
        except LockTimeoutError as e:
            err_msg = str(e)
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"ok": False, "applied": False, "error": "lock-timeout", "message": err_msg, "path": str(index_path)},
                        indent=2,
                    )
                )
            else:
                print(f"[FAIL] lock-timeout: {err_msg}", file=sys.stderr)
            return 1

    # Read-only modes (check, preview, adopt preview)
    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    current_hash = _file_sha256(index_path)

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

    has_conflict = ("<<<<<<<" in existing) or bool(
        re.search(r"^(<{7}|={7}|>{7}|\|{7})\b", existing, re.MULTILINE)
    )
    if has_conflict:
        adopt = True

    has_markers = has_generated_markers(existing) if existing.strip() else True

    # 2. Check adopt + apply requires --expect-hash
    if adopt and apply_flag and not has_conflict:
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
    if existing.strip() and not has_markers and not adopt and apply_flag and not has_conflict:
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
                        "sync_data": _build_index_sync_data(tasks_dir),
                    },
                    indent=2,
                )
            )
        else:
            if diff_str:
                sys.stdout.write(diff_str)
                print(
                    f"[preview] apply with: --adopt --apply --expect-hash {current_hash}",
                    file=sys.stderr,
                )
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
                        "sync_data": _build_index_sync_data(tasks_dir),
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
                        "sync_data": _build_index_sync_data(tasks_dir),
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
                    "sync_data": _build_index_sync_data(tasks_dir),
                },
                indent=2,
            )
        )
    else:
        sys.stdout.write(rendered)
    return 0


def cmd_merge_index(args: argparse.Namespace) -> int:
    base = getattr(args, "base", None)
    ours = getattr(args, "ours", None)
    theirs = getattr(args, "theirs", None)
    tasks_dir_arg = getattr(args, "tasks_dir", None)

    if tasks_dir_arg:
        tasks_dir = pathlib.Path(tasks_dir_arg).resolve()
    elif ours:
        ours_p = pathlib.Path(ours).resolve()
        if ours_p.name == "00-INDEX.md":
            tasks_dir = ours_p.parent
        elif (ours_p.parent / "00-INDEX.md").is_file():
            tasks_dir = ours_p.parent
        elif (ours_p.parent.parent / "tasks" / "00-INDEX.md").is_file():
            tasks_dir = (ours_p.parent.parent / "tasks").resolve()
        elif pathlib.Path("tasks").is_dir():
            tasks_dir = pathlib.Path("tasks").resolve()
        else:
            tasks_dir = ours_p.parent
    else:
        tasks_dir = pathlib.Path("tasks").resolve()

    if ours:
        target_path = pathlib.Path(ours).resolve()
    else:
        target_path = tasks_dir / "00-INDEX.md"

    if not is_platform_supported():
        err_msg = "Mutating commands are unsupported on Windows (requires fcntl for flock)."
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": "unsupported-platform", "message": err_msg}))
        else:
            print(f"[FAIL] unsupported-platform: {err_msg}", file=sys.stderr)
        return 1

    try:
        with task_write_lock(tasks_dir):
            existing = target_path.read_text(encoding="utf-8") if target_path.is_file() else ""
            if not existing and (tasks_dir / "00-INDEX.md").is_file():
                existing = (tasks_dir / "00-INDEX.md").read_text(encoding="utf-8")

            rendered = render_synced_index(tasks_dir, existing, adopt=True)
            _atomic_write_text(target_path, rendered, encoding="utf-8")
            if target_path.resolve() != (tasks_dir / "00-INDEX.md").resolve() and (tasks_dir / "00-INDEX.md").exists():
                _atomic_write_text(tasks_dir / "00-INDEX.md", rendered, encoding="utf-8")

            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "merged": True,
                            "path": str(target_path),
                            "tasks_dir": str(tasks_dir),
                        },
                        indent=2,
                    )
                )
            else:
                print(f"[ok] merged index {target_path}")
            return 0
    except LockTimeoutError as e:
        err_msg = str(e)
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": "lock-timeout", "message": err_msg}))
        else:
            print(f"[FAIL] lock-timeout: {err_msg}", file=sys.stderr)
        return 1


def upgrade_tasks_tree(tasks_dir: pathlib.Path, dry_run: bool = False, migrate_plans: bool = False) -> dict[str, Any]:
    """Upgrade a tasks/ directory to the latest task-pipeline v0.3.0 convention:
      1. Updates tasks/AGENTS.md with canonical task-pipeline rules and skill names.
      2. Ensures tasks/.gitignore exists and ignores .ai-orch.lock.
      2.5. Ensures tasks/.gitattributes exists and configures 00-INDEX.md merge=ai-orch-index.
      3. Ensures standard directories exist (_inbox/to-analyze, _inbox/analyzed).
      3.5. Discovers and reports/migrates legacy plans/ directories.
      4. Regenerates/updates 00-INDEX.md with standard tables (Initiatives, Specs, Next up, Tasks by category, Decisions waiting, Done).
      5. Validates the upgraded tree.
    """
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if not is_platform_supported():
        return {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
            "upgraded_files": [],
            "created": [],
            "updated": [],
            "dry_run": dry_run,
            "emergent_count": 0,
            "initiative_count": 0,
            "legacy_plans": [],
            "errors": ["unsupported-platform: Mutating commands are unsupported on Windows"],
            "warnings": [],
        }

    try:
        with task_write_lock(tasks_dir):
            upgraded_files: list[str] = []
            created: list[str] = []
            updated: list[str] = []

            # 1. Update tasks/AGENTS.md
            agents_md = tasks_dir / "AGENTS.md"
            existing_agents = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else ""
            if existing_agents.strip() != CANONICAL_TASKS_AGENTS_MD.strip():
                if not agents_md.is_file():
                    created.append(str(agents_md))
                else:
                    updated.append(str(agents_md))
                if not dry_run:
                    _atomic_write_text(agents_md, CANONICAL_TASKS_AGENTS_MD, encoding="utf-8")
                upgraded_files.append(str(agents_md))

            # 2. Ensure tasks/.gitignore exists and contains .ai-orch.lock
            gitignore_path = tasks_dir / ".gitignore"
            if not gitignore_path.is_file():
                created.append(str(gitignore_path))
                upgraded_files.append(str(gitignore_path))
                if not dry_run:
                    _atomic_write_text(gitignore_path, ".ai-orch.lock\n", encoding="utf-8")
            else:
                existing_gi = gitignore_path.read_text(encoding="utf-8")
                gi_lines = [line.strip() for line in existing_gi.splitlines()]
                if ".ai-orch.lock" not in gi_lines:
                    updated.append(str(gitignore_path))
                    upgraded_files.append(str(gitignore_path))
                    new_gi = existing_gi + ("\n" if existing_gi and not existing_gi.endswith("\n") else "") + ".ai-orch.lock\n"
                    if not dry_run:
                        _atomic_write_text(gitignore_path, new_gi, encoding="utf-8")

            # 2.5. Ensure tasks/.gitattributes exists and contains 00-INDEX.md merge=ai-orch-index
            gitattributes_path = tasks_dir / ".gitattributes"
            rule_line = "00-INDEX.md merge=ai-orch-index"
            if not gitattributes_path.is_file():
                created.append(str(gitattributes_path))
                upgraded_files.append(str(gitattributes_path))
                if not dry_run:
                    _atomic_write_text(gitattributes_path, f"{rule_line}\n", encoding="utf-8")
            else:
                existing_ga = gitattributes_path.read_text(encoding="utf-8")
                ga_lines = [line.strip() for line in existing_ga.splitlines()]
                if not any(line == rule_line or line.startswith("00-INDEX.md merge=") for line in ga_lines):
                    updated.append(str(gitattributes_path))
                    upgraded_files.append(str(gitattributes_path))
                    new_ga = existing_ga + ("\n" if existing_ga and not existing_ga.endswith("\n") else "") + f"{rule_line}\n"
                    if not dry_run:
                        _atomic_write_text(gitattributes_path, new_ga, encoding="utf-8")

            # 3. Ensure standard directories
            if not dry_run:
                (tasks_dir / "_inbox" / "to-analyze").mkdir(parents=True, exist_ok=True)
                (tasks_dir / "_inbox" / "analyzed").mkdir(parents=True, exist_ok=True)

            # 3.5. Legacy plans discovery & migration
            legacy_plans: list[dict[str, Any]] = []
            plans_dirs: list[pathlib.Path] = []
            if tasks_dir.name == "tasks":
                sibling_plans = tasks_dir.parent / "plans"
                if sibling_plans.is_dir() and sibling_plans.resolve() != tasks_dir.resolve():
                    plans_dirs.append(sibling_plans)
            nested_plans = tasks_dir / "plans"
            if nested_plans.is_dir() and nested_plans.resolve() not in [p.resolve() for p in plans_dirs]:
                plans_dirs.append(nested_plans)

            seen_sources: set[pathlib.Path] = set()

            for p_dir in plans_dirs:
                for child in sorted(p_dir.iterdir()):
                    if child.name.startswith("."):
                        continue
                    if child.resolve() in seen_sources:
                        continue

                    if child.is_dir():
                        m_init = INITIATIVE_DIR_RE.match(child.name)
                        if m_init:
                            plan_file = child / "plan.md"
                            src_file = plan_file if plan_file.is_file() else child
                            seen_sources.add(child.resolve())
                            if plan_file.is_file():
                                seen_sources.add(plan_file.resolve())

                            dest_dir = tasks_dir / child.name
                            dest_file = dest_dir / "plan.md"

                            if dest_file.exists():
                                action = "conflict"
                            else:
                                should_migrate = bool(migrate_plans or True)  # non-conflicting NN-<slug>
                                if should_migrate:
                                    if not dry_run:
                                        dest_dir.mkdir(parents=True, exist_ok=True)
                                        for subitem in child.iterdir():
                                            if subitem.is_file():
                                                target_sub = dest_dir / subitem.name
                                                if not target_sub.exists():
                                                    shutil.copy2(subitem, target_sub)
                                                    created.append(str(target_sub))
                                                    upgraded_files.append(str(target_sub))
                                        action = "migrated"
                                    else:
                                        action = "would_migrate"
                                else:
                                    action = "suggested"

                            legacy_plans.append({
                                "source": str(src_file.resolve()),
                                "path": str(src_file.resolve()),
                                "destination": str(dest_file.resolve()),
                                "suggested_dest": str(dest_file.resolve()),
                                "action": action,
                                "status": action,
                            })
                        else:
                            for subfile in sorted(child.glob("**/*.md")):
                                if subfile.resolve() in seen_sources:
                                    continue
                                seen_sources.add(subfile.resolve())
                                slug = slugify(subfile.stem)
                                dest_file = tasks_dir / "specs" / f"{slug}.md"
                                if dest_file.exists():
                                    action = "conflict"
                                else:
                                    if migrate_plans:
                                        if not dry_run:
                                            (tasks_dir / "specs").mkdir(parents=True, exist_ok=True)
                                            shutil.copy2(subfile, dest_file)
                                            created.append(str(dest_file))
                                            upgraded_files.append(str(dest_file))
                                            action = "migrated"
                                        else:
                                            action = "would_migrate"
                                    else:
                                        action = "suggested"

                                legacy_plans.append({
                                    "source": str(subfile.resolve()),
                                    "path": str(subfile.resolve()),
                                    "destination": str(dest_file.resolve()),
                                    "suggested_dest": str(dest_file.resolve()),
                                    "action": action,
                                    "status": action,
                                })

                    elif child.is_file() and child.suffix == ".md":
                        seen_sources.add(child.resolve())
                        m_init = INITIATIVE_DIR_RE.match(child.stem)
                        if m_init:
                            dest_dir = tasks_dir / child.stem
                            dest_file = dest_dir / "plan.md"
                            if dest_file.exists():
                                action = "conflict"
                            else:
                                if migrate_plans:
                                    if not dry_run:
                                        dest_dir.mkdir(parents=True, exist_ok=True)
                                        shutil.copy2(child, dest_file)
                                        created.append(str(dest_file))
                                        upgraded_files.append(str(dest_file))
                                        action = "migrated"
                                    else:
                                        action = "would_migrate"
                                else:
                                    action = "suggested"
                        else:
                            slug = slugify(child.stem)
                            dest_file = tasks_dir / "specs" / f"{slug}.md"
                            if dest_file.exists():
                                action = "conflict"
                            else:
                                if migrate_plans:
                                    if not dry_run:
                                        (tasks_dir / "specs").mkdir(parents=True, exist_ok=True)
                                        shutil.copy2(child, dest_file)
                                        created.append(str(dest_file))
                                        upgraded_files.append(str(dest_file))
                                        action = "migrated"
                                    else:
                                        action = "would_migrate"
                                else:
                                    action = "suggested"

                        legacy_plans.append({
                            "source": str(child.resolve()),
                            "path": str(child.resolve()),
                            "destination": str(dest_file.resolve()),
                            "suggested_dest": str(dest_file.resolve()),
                            "action": action,
                            "status": action,
                        })

            # 4. Re-sync 00-INDEX.md
            idx_path = tasks_dir / "00-INDEX.md"
            existing_idx = idx_path.read_text(encoding="utf-8") if idx_path.is_file() else ""
            rendered_idx = render_synced_index(tasks_dir, existing_idx, adopt=True)
            if existing_idx.strip() != rendered_idx.strip():
                if not idx_path.is_file():
                    created.append(str(idx_path))
                else:
                    updated.append(str(idx_path))
                if not dry_run:
                    _atomic_write_text(idx_path, rendered_idx, encoding="utf-8")
                upgraded_files.append(str(idx_path))

            # 5. Validate
            errors, warnings, emergent, initiatives = validate_tasks_tree(tasks_dir)

            return {
                "ok": len(errors) == 0,
                "upgraded_files": upgraded_files,
                "created": created,
                "updated": updated,
                "dry_run": dry_run,
                "emergent_count": len(emergent),
                "initiative_count": len(initiatives),
                "legacy_plans": legacy_plans,
                "errors": errors,
                "warnings": warnings,
            }
    except LockTimeoutError as e:
        return {
            "ok": False,
            "error": "lock-timeout",
            "message": str(e),
            "upgraded_files": [],
            "created": [],
            "updated": [],
            "dry_run": dry_run,
            "emergent_count": 0,
            "initiative_count": 0,
            "legacy_plans": [],
            "errors": [f"lock-timeout: {e}"],
            "warnings": [],
        }


def cmd_upgrade(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    dry_run = getattr(args, "dry_run", False)
    migrate_plans = getattr(args, "migrate_plans", False)
    res = upgrade_tasks_tree(tasks_dir, dry_run=dry_run, migrate_plans=migrate_plans)
    args._last_result = res
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        prefix = "[dry-run] " if dry_run else ""
        if res["upgraded_files"]:
            print(f"[ok] {prefix}Upgraded {len(res['upgraded_files'])} file(s) in {tasks_dir}:")
            for f in res["upgraded_files"]:
                print(f"  - {f}")
        else:
            print(f"[ok] {tasks_dir} is already up-to-date with latest task-pipeline convention.")
        if res.get("legacy_plans"):
            print(f"\n[legacy-plans] {prefix}Discovered {len(res['legacy_plans'])} legacy plan(s):")
            for lp in res["legacy_plans"]:
                act = lp.get("action", "suggested")
                print(f"  - [{act}] {lp['source']} -> {lp['destination']}")
        if res["warnings"]:
            for w in res["warnings"]:
                print(f"[WARN] {w}")
        if res["errors"]:
            for e in res["errors"]:
                print(f"[FAIL] {e}")
    return 0 if res["ok"] else 1


# ---------------------------------------------------------------------------
# Blocking Questions Operations & Commands
# ---------------------------------------------------------------------------

def ask_question(
    tasks_dir: pathlib.Path,
    question: str | None = None,
    context: str | None = None,
    context_file: str | pathlib.Path | None = None,
    options: list[tuple[str, str, str | None]] | None = None,
    recommended: str = "-",
    open_answer: str = "no",
    blocks: str | None = None,
    decider: str = "owner",
    asked_by: str = "owner",
    origin_run: str = "-",
    from_task: str | None = None,
    short: str | None = None,
    notes: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    if short and short.strip() and short.strip() != "-":
        issues = validate_short_title(short.strip())
        if issues:
            return False, {"ok": False, "error": f"Invalid short title {short!r}: {'; '.join(issues)}."}

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            emergent = discover_emergent_tasks(tasks_dir)
            emergent_map = {t["id"]: t for t in emergent}

            tasks_to_update: list[tuple[dict[str, Any], str, str]] = []
            blocks_entries: list[str] = []

            if from_task:
                if from_task not in emergent_map:
                    return False, {"ok": False, "error": f"Task {from_task!r} not found in {tasks_dir}."}
                target_t = emergent_map[from_task]
                raw_dec = target_t.get("decider", "").strip()
                if not raw_dec or raw_dec == "-":
                    return False, {"ok": False, "error": f"Task {from_task!r} has no legacy decider to convert."}
                if re.match(r"^Q\d{3,}(?:,\s*Q\d{3,})*$", raw_dec):
                    return False, {"ok": False, "error": f"Task {from_task!r} already has a question decider ({raw_dec})."}

                if ":" in raw_dec:
                    actor, q_txt = [p.strip() for p in raw_dec.split(":", 1)]
                else:
                    actor = "owner"
                    q_txt = raw_dec.strip()

                if not q_txt.endswith("?"):
                    q_txt += "?"
                if len(q_txt) > 160:
                    q_txt = q_txt[:159] + "?"

                question = q_txt
                context = f"Converted from the legacy decider header of {from_task}; context to be completed by the owner."
                options = []
                recommended = "-"
                open_answer = "yes"
                decider = actor or "owner"
                asked_by = actor or "owner"
                origin_run = "-"
                tasks_to_update.append((target_t, "waiting", "SET"))
                blocks_entries.append(f"{from_task} ({target_t['state']})")
            else:
                if not question or not question.strip():
                    return False, {"ok": False, "error": "Missing required --question."}
                question = question.strip()
                if not question.endswith("?"):
                    return False, {"ok": False, "error": "Question must end with '?'."}
                if len(question) > 160:
                    return False, {"ok": False, "error": f"Question length ({len(question)}) exceeds 160 characters."}
                if "\n" in question:
                    return False, {"ok": False, "error": "Question must be a single line."}

                if context_file:
                    cpath = pathlib.Path(context_file)
                    if not cpath.is_file():
                        return False, {"ok": False, "error": f"Context file not found: {context_file}"}
                    context = cpath.read_text(encoding="utf-8")
                if not context or not context.strip():
                    return False, {"ok": False, "error": "Missing required context (via --context or --context-file)."}

                if not blocks or not blocks.strip():
                    blocks = "-"

                options = options or []
                opt_labels = [opt[0] for opt in options if opt[0]]
                if len(opt_labels) != len(set(opt_labels)):
                    return False, {"ok": False, "error": f"Option labels must be unique: {opt_labels}."}

                if open_answer not in ("yes", "no"):
                    return False, {"ok": False, "error": f"Invalid open-answer: {open_answer!r}."}

                if open_answer == "no" and len(options) < 2:
                    return False, {"ok": False, "error": f"At least 2 options required when open-answer is 'no' (got {len(options)})."}
                if open_answer == "yes" and len(options) == 1:
                    return False, {"ok": False, "error": "Options must be empty (pure open question) or have at least 2 options (got 1)."}

                if len(options) == 0:
                    if recommended != "-":
                        return False, {"ok": False, "error": f"recommended must be '-' when options are empty (got {recommended!r})."}
                else:
                    if recommended != "-" and recommended not in opt_labels:
                        return False, {"ok": False, "error": f"recommended option {recommended!r} not found in options {opt_labels}."}

                # Parse blocks and check task states
                # `-` means the question blocks no task (spec §2), e.g. a decision gating an initiative task
                tree = discover_task_tree(tasks_dir)
                blocks_list = [] if blocks.strip() == "-" else [b.strip() for b in blocks.split(",") if b.strip()]
                for b in blocks_list:
                    bm = DEP_ID_RE.match(b.strip())
                    if not bm:
                        return False, {"ok": False, "error": f"Invalid task ID {b!r} in blocks."}
                    tid = bm.group(1)
                    if tid not in tree:
                        return False, {"ok": False, "error": f"Blocked task {tid!r} not found in tasks tree."}
                    t = tree[tid]
                    if not t.is_leaf:
                        return False, {"ok": False, "error": f"Cannot block container '{tid}': questions can only block leaf tasks."}
                    cstate = t.canonical_state

                    if cstate in TERMINAL_STATES:
                        return False, {"ok": False, "error": f"Cannot block task {tid!r} in terminal state '{cstate}'."}
                    if cstate in ("waiting", "blocked"):
                        raw_dec = t.fields.get("decider", {}).get("value", "") or t.own_fields.get("decider", "")
                        if cstate == "waiting" and re.match(r"^Q\d{3,}(?:,\s*Q\d{3,})*$", str(raw_dec).strip()):
                            tasks_to_update.append((t, "waiting", "APPEND"))
                            blocks_entries.append(f"{tid} (waiting)")
                        elif cstate == "blocked":
                            # A blocked task can be formally gated on an explicit blocking question Q###!
                            tasks_to_update.append((t, "waiting", "SET"))
                            blocks_entries.append(f"{tid} (blocked)")
                        elif cstate == "waiting":
                            # Legacy free-form decider: convert to new question
                            tasks_to_update.append((t, "waiting", "SET"))
                            blocks_entries.append(f"{tid} (waiting)")
                    elif cstate in ("open", "in progress", "paused"):
                        tasks_to_update.append((t, "waiting", "SET"))
                        blocks_entries.append(f"{tid} ({cstate})")
                    else:
                        return False, {"ok": False, "error": f"Cannot block task {tid!r} in state '{t.state}'."}

            created_files: list[pathlib.Path] = []
            modified_files: dict[pathlib.Path, str] = {}
            for t, _, _ in tasks_to_update:
                tp = pathlib.Path(t.file_path if hasattr(t, "file_path") else t["file_path"])
                if tp not in modified_files:
                    modified_files[tp] = tp.read_text(encoding="utf-8")
                if getattr(t, "is_folder", False) or (isinstance(t, dict) and t.get("is_folder")):
                    pp = tp.parent / "PROGRESS.md"
                    if pp.is_file() and pp not in modified_files:
                        modified_files[pp] = pp.read_text(encoding="utf-8")

            # Allocate Q### with O_EXCL
            questions_dir = tasks_dir / "questions"
            questions_dir.mkdir(parents=True, exist_ok=True)
            existing_nums = []
            for f in questions_dir.iterdir():
                if f.is_file() and f.suffix == ".md":
                    m_num = QUESTION_ID_RE.match(f.name.split("-")[0])
                    if m_num:
                        existing_nums.append(int(f.name.split("-")[0][1:]))
            next_num = max(existing_nums, default=0) + 1

            slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")
            slug = slug[:50].rstrip("-") or "question"

            fd: int | None = None
            q_file_path: pathlib.Path | None = None
            q_id = ""
            filename = ""
            while True:
                q_id = f"Q{next_num:03d}"
                filename = f"{q_id}-{slug}.md"
                q_file_path = questions_dir / filename
                try:
                    fd = os.open(str(q_file_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    created_files.append(q_file_path)
                    break
                except FileExistsError:
                    next_num += 1

            try:
                title = question.rstrip("?").strip()
                today = datetime.date.today().isoformat()
                blocks_header_val = ", ".join(blocks_entries)
                short_val = short.strip() if short and short.strip() and short.strip() != "-" else derive_short_title(title or question)
                content = format_question_content(
                    id=q_id,
                    title=title,
                    question=question,
                    status="open",
                    blocks=blocks_header_val,
                    decider=decider or "owner",
                    asked_by=asked_by or "owner",
                    asked=today,
                    origin_run=origin_run or "-",
                    open_answer=open_answer,
                    recommended=recommended,
                    context=context,
                    options=options,
                    choice="-",
                    answered_by="-",
                    answered="-",
                    text=None,
                    short=short_val,
                    notes=notes,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)

                # Update tasks
                for t, new_st, dec_mode in tasks_to_update:
                    if hasattr(t, "block_text") and t.block_text is not None:
                        curr_dec = str(t.own_fields.get("decider", "") or t.fields.get("decider", {}).get("value", "")).strip() if hasattr(t, "own_fields") else ""
                        if dec_mode == "SET":
                            new_dec = q_id
                        else:
                            new_dec = f"{curr_dec}, {q_id}" if curr_dec and curr_dec != "-" else q_id
                        rewrite_block_in_file(pathlib.Path(t.file_path), t.id, new_status=new_st, new_decider=new_dec, new_waiting_on=f"question:{q_id}")
                    else:
                        tp = pathlib.Path(t.file_path if hasattr(t, "file_path") else t["file_path"])
                        curr_dec = (t.fields.get("decider", {}).get("value", "") or t.own_fields.get("decider", "")) if hasattr(t, "own_fields") else t.get("decider", "")
                        old_st = t.state if hasattr(t, "state") else t["state"]
                        t_dict = t.to_dict() if hasattr(t, "to_dict") else t
                        if dec_mode == "SET":
                            new_dec = q_id
                        else:
                            new_dec = f"{curr_dec}, {q_id}" if curr_dec and curr_dec != "-" else q_id
                        _update_task_file_headers_and_state(tp, new_st, decider=new_dec, waiting_on=f"question:{q_id}")
                        _append_progress_log(
                            t_dict,
                            old_st,
                            new_st,
                            asked_by,
                            verifier=None,
                            reason=f"Blocked by question {q_id}",
                        )

                _emit_event(
                    tasks_dir,
                    "question.asked",
                    {
                        "question": question,
                        "context": context,
                        "options": [opt[0] for opt in options] if options else [],
                        "blocks": blocks or "",
                        "by": asked_by or "owner",
                        "origin_run": origin_run or "-",
                    },
                    subject=q_id,
                    actor=asked_by or "owner",
                )
                for t, new_st, _ in tasks_to_update:
                    old_st = t.state if hasattr(t, "state") else t["state"]
                    tid = t.id if hasattr(t, "id") else t["id"]
                    _emit_event(
                        tasks_dir,
                        "task.transitioned",
                        {
                            "from": old_st,
                            "to": new_st,
                            "actor": asked_by or "owner",
                            "reason": f"Blocked by question {q_id}",
                        },
                        subject=tid,
                        actor=asked_by or "owner",
                    )

                return True, {
                    "ok": True,
                    "id": q_id,
                    "filename": filename,
                    "file_path": str(q_file_path),
                    "rel_path": f"questions/{filename}",
                }
            except Exception:
                for cp in created_files:
                    try:
                        if cp.is_file():
                            cp.unlink()
                    except OSError:
                        pass
                for mp, orig_text in modified_files.items():
                    try:
                        _atomic_write_text(mp, orig_text)
                    except OSError:
                        pass
                raise
    except LockTimeoutError:
        return False, {
            "ok": False,
            "error": "lock-timeout",
            "message": "Timed out waiting for task-write lock in tasks/.",
        }


def answer_question(
    tasks_dir: pathlib.Path,
    question_id: str,
    choice: str,
    text: str | None = None,
    by: str = "owner",
    changes_result: bool = False,
    apply_ref: str | None = None,
    apply_note: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            questions = discover_questions(tasks_dir)
            target_q = next((q for q in questions if q["id"] == question_id), None)
            if target_q is None:
                return False, {"ok": False, "error": f"Question {question_id!r} not found in {tasks_dir}."}
            if target_q["status"] != "open":
                return False, {"ok": False, "error": f"Question {question_id!r} is not open (status: {target_q['status']!r})."}

            opt_labels = [opt["label"] for opt in target_q["options"] if opt["label"]]
            if choice == "open":
                if target_q["open_answer"] != "yes":
                    return False, {"ok": False, "error": f"Choice 'open' is not allowed (open-answer is 'no')."}
                if not text or not text.strip():
                    return False, {"ok": False, "error": "Choice 'open' requires non-empty text."}
            elif choice in opt_labels:
                pass
            else:
                return False, {"ok": False, "error": f"Invalid choice {choice!r}. Allowed options: {opt_labels} or 'open'."}

            q_file = pathlib.Path(target_q["file_path"])
            modified_files: dict[pathlib.Path, str] = {q_file: q_file.read_text(encoding="utf-8")}

            emergent = discover_emergent_tasks(tasks_dir)
            emergent_map = {t["id"]: t for t in emergent}

            for tid, _ in target_q["blocks_parsed"]:
                if tid in emergent_map:
                    t = emergent_map[tid]
                    tp = pathlib.Path(t["file_path"])
                    if tp not in modified_files:
                        modified_files[tp] = tp.read_text(encoding="utf-8")
                    if t["is_folder"]:
                        pp = tp.parent / "PROGRESS.md"
                        if pp.is_file() and pp not in modified_files:
                            modified_files[pp] = pp.read_text(encoding="utf-8")

            try:
                today = datetime.date.today().isoformat()
                new_q_content = format_question_content(
                    id=target_q["id"],
                    title=target_q["title"],
                    question=target_q["question"],
                    status="answered",
                    blocks=target_q["blocks"],
                    decider=target_q["decider"],
                    asked_by=target_q["asked_by"],
                    asked=target_q["asked"],
                    origin_run=target_q["origin_run"],
                    open_answer=target_q["open_answer"],
                    recommended=target_q["recommended"],
                    context=target_q["context"],
                    options=[(opt["label"], opt["title"], opt["consequence"]) for opt in target_q["options"]],
                    choice=choice,
                    answered_by=by or "owner",
                    answered=today,
                    text=text if (text is not None and text != "") else None,
                    short=target_q.get("short"),
                    applied="no",
                    notes=target_q.get("notes"),
                )
                _atomic_write_text(q_file, new_q_content)

                q_status_map = {q["id"]: q["status"] for q in questions}
                q_status_map[question_id] = "answered"

                unblocked: list[str] = []
                unblocked_states: dict[str, str] = {}
                tree = discover_task_tree(tasks_dir)
                for tid, _ in target_q["blocks_parsed"]:
                    if tid in tree:
                        t_node = tree[tid]
                        if t_node.block_text is not None:
                            restored_state = _find_earliest_prior_state_for_task(tasks_dir, tid, [question_id])
                            rewrite_block_in_file(pathlib.Path(t_node.file_path), tid, new_status=restored_state, new_decider="-")
                            unblocked.append(tid)
                            unblocked_states[tid] = restored_state
                            continue
                    if tid not in emergent_map:
                        continue
                    t = emergent_map[tid]
                    tp = pathlib.Path(t["file_path"])
                    t_dec = t.get("decider", "").strip()
                    linked_qids = [qid.strip() for qid in t_dec.split(",") if qid.strip()]

                    all_resolved = all(q_status_map.get(qid) in ("answered", "withdrawn", "moved") for qid in linked_qids)
                    if all_resolved:
                        restored_state = _find_earliest_prior_state_for_task(tasks_dir, tid, linked_qids)
                        _update_task_file_headers_and_state(tp, restored_state, decider="-")
                        _append_progress_log(
                            t,
                            "waiting",
                            restored_state,
                            by or "owner",
                            verifier=None,
                            reason=f"Unblocked: question {question_id} answered",
                        )
                        unblocked.append(tid)
                        unblocked_states[tid] = restored_state

                _emit_event(
                    tasks_dir,
                    "question.answered",
                    {
                        "choice": choice,
                        "text": text,
                        "by": by or "owner",
                        "unblocked_tasks": unblocked,
                    },
                    subject=question_id,
                    actor=by or "owner",
                )
                for tid in unblocked:
                    _emit_event(
                        tasks_dir,
                        "task.transitioned",
                        {
                            "from": "waiting",
                            "to": unblocked_states.get(tid, "open"),
                            "actor": by or "owner",
                            "reason": f"Unblocked: question {question_id} answered",
                        },
                        subject=tid,
                        actor=by or "owner",
                    )

                # Check tasks with conditions listing this question
                conditions_resolved: list[str] = []
                resolved_tasks: list[dict[str, Any]] = []

                for et_item in emergent:
                    raw_c = et_item.get("headers", {}).get("conditions", "")
                    if question_id in parse_conditions_field(raw_c):
                        conditions_resolved.append(et_item["id"])
                        resolved_tasks.append(et_item)

                for n_id, n_node in tree.items():
                    if n_node.is_leaf and n_node.own_fields.get("conditions"):
                        raw_c = n_node.own_fields["conditions"]
                        if question_id in parse_conditions_field(raw_c) and n_id not in conditions_resolved:
                            conditions_resolved.append(n_id)
                            resolved_tasks.append({
                                "id": n_id,
                                "title": n_node.title,
                                "category": n_node.category,
                                "rel_path": n_node.rel_path,
                            })

                follow_up_tasks: list[str] = []
                if changes_result:
                    for rt in resolved_tasks:
                        cat = rt.get("category")
                        if not cat or cat == "micro" or cat.startswith((".", "_")) or INITIATIVE_DIR_RE.match(cat):
                            cat = "server-and-bindings"
                        category_dir = tasks_dir / cat
                        if not category_dir.is_dir() or cat in RESERVED_DIRS:
                            cat = "server-and-bindings"
                        fu_title = f"Follow-up for {rt['id']}: {question_id} answered"
                        sources_val = f"{rt['id']}, {question_id}"
                        goal_val = f"Address changes to finished result of {rt['id']} after {question_id} was answered ({choice})."
                        pri_reason = f"Follow-up required because {question_id} answer changes result of {rt['id']}."
                        ok_fu, res_fu = tasks_new_from_note(
                            tasks_dir=tasks_dir,
                            from_note=None,
                            category=cat,
                            title=fu_title,
                            priority="P2",
                            priority_reason=pri_reason,
                            goal=goal_val,
                            sources=sources_val,
                        )
                        if ok_fu:
                            follow_up_tasks.append(res_fu["id"])

                ret_payload: dict[str, Any] = {
                    "ok": True,
                    "id": question_id,
                    "status": "answered",
                    "choice": choice,
                    "unblocked_tasks": unblocked,
                    "conditions_resolved": conditions_resolved,
                }
                if changes_result:
                    ret_payload["follow_up_tasks"] = follow_up_tasks
                    ret_payload["follow_up_id"] = follow_up_tasks[0] if follow_up_tasks else None

                if apply_ref or apply_note:
                    ok_app, app_res = apply_question(tasks_dir, question_id, by=by, ref=apply_ref, note=apply_note)
                    if ok_app:
                        ret_payload["applied"] = True
                        ret_payload["applied_record"] = app_res.get("record")

                return True, ret_payload
            except Exception:
                for mp, orig_text in modified_files.items():
                    try:
                        _atomic_write_text(mp, orig_text)
                    except OSError:
                        pass
                raise
    except LockTimeoutError:
        return False, {
            "ok": False,
            "error": "lock-timeout",
            "message": "Timed out waiting for task-write lock in tasks/.",
        }


def _withdraw_question_file_only(
    tasks_dir: pathlib.Path,
    q_dict: dict[str, Any],
    reason: str,
    by: str = "owner",
) -> None:
    q_file = pathlib.Path(q_dict["file_path"])
    today = datetime.date.today().isoformat()
    new_q_content = format_question_content(
        id=q_dict["id"],
        title=q_dict["title"],
        question=q_dict["question"],
        status="withdrawn",
        blocks=q_dict["blocks"],
        decider=q_dict["decider"],
        asked_by=q_dict["asked_by"],
        asked=q_dict["asked"],
        origin_run=q_dict["origin_run"],
        open_answer=q_dict["open_answer"],
        recommended=q_dict["recommended"],
        context=q_dict["context"],
        options=[(opt["label"], opt["title"], opt["consequence"]) for opt in q_dict["options"]],
        choice="withdrawn",
        answered_by=by or "owner",
        answered=today,
        text=reason if (reason is not None and reason != "") else None,
        short=q_dict.get("short"),
        notes=q_dict.get("notes"),
    )
    _atomic_write_text(q_file, new_q_content)


def withdraw_question(
    tasks_dir: pathlib.Path,
    question_id: str,
    reason: str,
    by: str = "owner",
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            questions = discover_questions(tasks_dir)
            target_q = next((q for q in questions if q["id"] == question_id), None)
            if target_q is None:
                return False, {"ok": False, "error": f"Question {question_id!r} not found in {tasks_dir}."}
            if target_q["status"] != "open":
                return False, {"ok": False, "error": f"Question {question_id!r} is not open (status: {target_q['status']!r})."}

            if not reason or not reason.strip():
                return False, {"ok": False, "error": "Withdrawing a question requires non-empty --reason."}

            q_file = pathlib.Path(target_q["file_path"])
            modified_files: dict[pathlib.Path, str] = {q_file: q_file.read_text(encoding="utf-8")}

            emergent = discover_emergent_tasks(tasks_dir)
            emergent_map = {t["id"]: t for t in emergent}

            for tid, _ in target_q["blocks_parsed"]:
                if tid in emergent_map:
                    t = emergent_map[tid]
                    tp = pathlib.Path(t["file_path"])
                    if tp not in modified_files:
                        modified_files[tp] = tp.read_text(encoding="utf-8")
                    if t["is_folder"]:
                        pp = tp.parent / "PROGRESS.md"
                        if pp.is_file() and pp not in modified_files:
                            modified_files[pp] = pp.read_text(encoding="utf-8")

            try:
                _withdraw_question_file_only(tasks_dir, target_q, reason=reason, by=by)

                q_status_map = {q["id"]: q["status"] for q in questions}
                q_status_map[question_id] = "withdrawn"

                unblocked: list[str] = []
                unblocked_states: dict[str, str] = {}
                tree = discover_task_tree(tasks_dir)
                for tid, _ in target_q["blocks_parsed"]:
                    if tid in tree:
                        t_node = tree[tid]
                        if t_node.block_text is not None:
                            restored_state = _find_earliest_prior_state_for_task(tasks_dir, tid, [question_id])
                            rewrite_block_in_file(pathlib.Path(t_node.file_path), tid, new_status=restored_state, new_decider="-")
                            unblocked.append(tid)
                            unblocked_states[tid] = restored_state
                            continue
                    if tid not in emergent_map:
                        continue
                    t = emergent_map[tid]
                    tp = pathlib.Path(t["file_path"])
                    t_dec = t.get("decider", "").strip()
                    linked_qids = [qid.strip() for qid in t_dec.split(",") if qid.strip()]

                    all_resolved = all(q_status_map.get(qid) in ("answered", "withdrawn", "moved") for qid in linked_qids)
                    if all_resolved:
                        restored_state = _find_earliest_prior_state_for_task(tasks_dir, tid, linked_qids)
                        _update_task_file_headers_and_state(tp, restored_state, decider="-")
                        _append_progress_log(
                            t,
                            "waiting",
                            restored_state,
                            by or "owner",
                            verifier=None,
                            reason=f"Unblocked: question {question_id} withdrawn: {reason.strip()}",
                        )
                        unblocked.append(tid)
                        unblocked_states[tid] = restored_state

                _emit_event(
                    tasks_dir,
                    "question.withdrawn",
                    {
                        "reason": reason.strip(),
                        "by": by or "owner",
                        "unblocked_tasks": unblocked,
                    },
                    subject=question_id,
                    actor=by or "owner",
                )
                for tid in unblocked:
                    _emit_event(
                        tasks_dir,
                        "task.transitioned",
                        {
                            "from": "waiting",
                            "to": unblocked_states.get(tid, "open"),
                            "actor": by or "owner",
                            "reason": f"Unblocked: question {question_id} withdrawn: {reason.strip()}",
                        },
                        subject=tid,
                        actor=by or "owner",
                    )

                return True, {
                    "ok": True,
                    "id": question_id,
                    "status": "withdrawn",
                    "reason": reason.strip(),
                    "unblocked_tasks": unblocked,
                }
            except Exception:
                for mp, orig_text in modified_files.items():
                    try:
                        _atomic_write_text(mp, orig_text)
                    except OSError:
                        pass
                raise
    except LockTimeoutError:
        return False, {
            "ok": False,
            "error": "lock-timeout",
            "message": "Timed out waiting for task-write lock in tasks/.",
        }


def show_question(tasks_dir: pathlib.Path, question_id: str) -> tuple[bool, dict[str, Any]]:
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    questions = discover_questions(tasks_dir)
    target_q = next((q for q in questions if q["id"] == question_id), None)
    if target_q is None:
        return False, {"ok": False, "error": f"Question {question_id!r} not found in {tasks_dir}."}
    return True, {"ok": True, "question": target_q}


def list_questions(
    tasks_dir: pathlib.Path,
    status: str = "all",
    blocks: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    questions = discover_questions(tasks_dir)

    unapplied = [
        q for q in questions
        if q["status"] == "answered"
        and (q.get("headers", {}).get("applied") or "-").strip().lower() != "yes"
        and not q.get("applied")
    ]

    filtered = questions
    if status == "unapplied":
        filtered = unapplied
    elif status != "all":
        filtered = [q for q in filtered if q["status"] == status]
    if blocks:
        filtered = [q for q in filtered if any(tid == blocks for tid, _ in q["blocks_parsed"])]

    def _sort_key(q: dict[str, Any]) -> tuple[int, int]:
        is_open = 0 if q["status"] == "open" else 1
        num = int(q["id"][1:]) if QUESTION_ID_RE.match(q["id"]) else 0
        return (is_open, -num)

    filtered.sort(key=_sort_key)
    return True, {
        "ok": True,
        "questions": filtered,
        "unapplied_answers": unapplied,
    }


def cmd_questions_list(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    status = getattr(args, "status", "all")
    blocks = getattr(args, "blocks", None)
    ok, res = list_questions(tasks_dir, status=status, blocks=blocks)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        qs = res.get("questions", [])
        if not qs:
            print(f"No questions found in {tasks_dir}/questions.")
        else:
            print(f"Questions ({len(qs)}):")
            for q in qs:
                blocks_clean = ", ".join(
                    [re.sub(r"\s*\([^)]*\)", "", b).strip() for b in q["blocks"].split(",") if b.strip()]
                ) or "-"
                print(f"  [{q['id']}] ({q['status']}) {q['question']} (blocks: {blocks_clean}, decider: {q['decider']})")
        unapplied = res.get("unapplied_answers", [])
        if unapplied and status != "unapplied":
            unapplied_desc = ", ".join(
                f"{q['id']} ({q.get('short_title') or derive_short_title(q.get('title') or q['question'])})"
                for q in unapplied
            )
            print(f"\n[NOTICE] {len(unapplied)} answered question(s) waiting to be applied: {unapplied_desc}")
            print("Run 'ai-orch questions apply Q### --note \"...\"' to record application.")
    return 0 if ok else 1


def cmd_questions_show(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = show_question(tasks_dir, args.question_id)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            q = res["question"]
            print(f"Question: {q['id']} — {q['question']}")
            print(f"Status  : {q['status']}")
            print(f"Blocks  : {q['blocks']}")
            print(f"Decider : {q['decider']}")
            print(f"Asked by: {q['asked_by']} on {q['asked']}")
            print(f"Rec     : {q['recommended']}")
            if q.get("moved_to"):
                print(f"Moved to: {q['moved_to']}")
            if q.get("reason"):
                print(f"Reason  : {q['reason']}")
            if q.get("headers", {}).get("applied"):
                print(f"Applied : {q['headers']['applied']}")
            print(f"\nContext:\n{q['context']}")
            if q.get("notes"):
                print(f"\nNotes:\n{q['notes']}")
            if q["options"]:
                print("\nOptions:")
                for opt in q["options"]:
                    if opt["consequence"]:
                        print(f"  - **{opt['label']}** — {opt['title']}: {opt['consequence']}")
                    else:
                        print(f"  - **{opt['label']}** — {opt['title']}")
            print("\nAnswer:")
            print(f"  Choice     : {q['answer']['choice']}")
            print(f"  Answered by: {q['answer']['answered_by']}")
            print(f"  Answered on: {q['answer']['answered']}")
            if q["answer"]["text"]:
                print(f"  Text       :\n{q['answer']['text']}")
            if q.get("applied"):
                rec = q.get("applied_record") or {}
                print(f"  Applied by : {rec.get('by', '-')} on {rec.get('at', '-')} (ref: {rec.get('ref', '-')})")
                if rec.get("note") and rec.get("note") != rec.get("ref"):
                    print(f"  Note       : {rec['note']}")
        else:
            print(f"[FAIL] {res.get('error', 'not found')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_questions_ask(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    raw_options = getattr(args, "option", [])
    parsed_options = [parse_option_arg(opt) for opt in raw_options] if raw_options else []

    ok, res = ask_question(
        tasks_dir=tasks_dir,
        question=args.question,
        context=args.context,
        context_file=args.context_file,
        options=parsed_options,
        recommended=args.recommended,
        open_answer=args.open_answer,
        blocks=args.blocks,
        decider=args.decider,
        asked_by=args.asked_by,
        origin_run=args.origin_run,
        from_task=args.from_task,
        short=getattr(args, "short", None),
        notes=getattr(args, "notes", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Created question {res['id']}: {res['rel_path']}")
        else:
            print(f"[FAIL] {res.get('error', 'ask failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_questions_answer(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    changes_result = getattr(args, "changes_result", False)
    ok, res = answer_question(
        tasks_dir=tasks_dir,
        question_id=args.question_id,
        choice=args.choice,
        text=args.text,
        by=args.by,
        changes_result=changes_result,
        apply_ref=getattr(args, "apply_ref", None),
        apply_note=getattr(args, "apply_note", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            unb = ", ".join(res["unblocked_tasks"]) if res["unblocked_tasks"] else "none"
            cond_res = ", ".join(res.get("conditions_resolved", [])) if res.get("conditions_resolved") else "none"
            msg = f"[ok] Answered {res['id']} with choice {res['choice']!r} (unblocked tasks: {unb}; conditions resolved: {cond_res})"
            if res.get("follow_up_tasks"):
                msg += f" [created follow-up: {', '.join(res['follow_up_tasks'])}]"
            print(msg)
        else:
            print(f"[FAIL] {res.get('error', 'answer failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_questions_withdraw(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = withdraw_question(
        tasks_dir=tasks_dir,
        question_id=args.question_id,
        reason=args.reason,
        by=args.by,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            unb = ", ".join(res["unblocked_tasks"]) if res["unblocked_tasks"] else "none"
            print(f"[ok] Withdrew {res['id']} with reason {res['reason']!r} (unblocked tasks: {unb})")
        else:
            print(f"[FAIL] {res.get('error', 'withdraw failed')}", file=sys.stderr)
    return 0 if ok else 1


def move_question(
    tasks_dir: pathlib.Path,
    question_id: str,
    to: str,
    reason: str | None = None,
    by: str = "owner",
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    if not to or not to.strip():
        return False, {"ok": False, "error": "Moving a question requires non-empty --to."}

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            questions = discover_questions(tasks_dir)
            target_q = next((q for q in questions if q["id"] == question_id), None)
            if target_q is None:
                return False, {"ok": False, "error": f"Question {question_id!r} not found in {tasks_dir}."}
            if target_q["status"] == "moved":
                return False, {"ok": False, "error": f"Question {question_id!r} is already in status 'moved'."}

            q_file = pathlib.Path(target_q["file_path"])
            dest_dir = tasks_dir / "questions" / "answered"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / q_file.name

            modified_files: dict[pathlib.Path, str] = {q_file: q_file.read_text(encoding="utf-8")}
            created_files: list[pathlib.Path] = []

            emergent = discover_emergent_tasks(tasks_dir)
            emergent_map = {t["id"]: t for t in emergent}

            # Backup affected task files for rollback
            for tid, _ in target_q["blocks_parsed"]:
                if tid in emergent_map:
                    t = emergent_map[tid]
                    tp = pathlib.Path(t["file_path"])
                    if tp not in modified_files:
                        modified_files[tp] = tp.read_text(encoding="utf-8")
                    if t["is_folder"]:
                        pp = tp.parent / "PROGRESS.md"
                        if pp.is_file() and pp not in modified_files:
                            modified_files[pp] = pp.read_text(encoding="utf-8")

            try:
                today = datetime.date.today().isoformat()
                ans_text = reason.strip() if (reason and reason.strip()) else f"Moved to {to.strip()}"
                new_q_content = format_question_content(
                    id=target_q["id"],
                    title=target_q["title"],
                    question=target_q["question"],
                    status="moved",
                    blocks=target_q["blocks"],
                    decider=target_q["decider"],
                    asked_by=target_q["asked_by"],
                    asked=target_q["asked"],
                    origin_run=target_q["origin_run"],
                    open_answer=target_q["open_answer"],
                    recommended=target_q["recommended"],
                    context=target_q["context"],
                    options=[(opt["label"], opt["title"], opt["consequence"]) for opt in target_q["options"]],
                    choice="moved",
                    answered_by=by or "owner",
                    answered=today,
                    text=ans_text,
                    short=target_q.get("short"),
                    moved_to=to.strip(),
                    reason=reason.strip() if (reason and reason.strip()) else None,
                    notes=target_q.get("notes"),
                )

                if dest_file != q_file:
                    _atomic_write_text(dest_file, new_q_content)
                    created_files.append(dest_file)
                    try:
                        q_file.unlink()
                    except OSError:
                        pass
                else:
                    _atomic_write_text(q_file, new_q_content)

                q_status_map = {q["id"]: q["status"] for q in questions}
                q_status_map[question_id] = "moved"

                unblocked: list[str] = []
                unblocked_states: dict[str, str] = {}
                tree = discover_task_tree(tasks_dir)

                for tid, _ in target_q["blocks_parsed"]:
                    if tid in tree:
                        t_node = tree[tid]
                        if t_node.block_text is not None:
                            restored_state = _find_earliest_prior_state_for_task(tasks_dir, tid, [question_id])
                            rewrite_block_in_file(pathlib.Path(t_node.file_path), tid, new_status=restored_state, new_decider="-")
                            unblocked.append(tid)
                            unblocked_states[tid] = restored_state
                            continue
                    if tid not in emergent_map:
                        continue
                    t = emergent_map[tid]
                    tp = pathlib.Path(t["file_path"])
                    t_dec = t.get("decider", "").strip()
                    linked_qids = [qid.strip() for qid in t_dec.split(",") if qid.strip()]

                    all_resolved = all(q_status_map.get(qid) in ("answered", "withdrawn", "moved") for qid in linked_qids)
                    if all_resolved:
                        restored_state = _find_earliest_prior_state_for_task(tasks_dir, tid, linked_qids)
                        _update_task_file_headers_and_state(tp, restored_state, decider="-")
                        _append_progress_log(
                            t,
                            "waiting",
                            restored_state,
                            by or "owner",
                            verifier=None,
                            reason=f"Unblocked: question {question_id} moved to tracker ({to.strip()})",
                        )
                        unblocked.append(tid)
                        unblocked_states[tid] = restored_state

                # Clear question_id from conditions of tasks
                for et_item in emergent:
                    tp = pathlib.Path(et_item["file_path"])
                    raw_c = et_item.get("headers", {}).get("conditions", "")
                    cond_list = parse_conditions_field(raw_c)
                    if question_id in cond_list:
                        new_conds = [c for c in cond_list if c != question_id]
                        new_c_val = ", ".join(new_conds) if new_conds else "-"
                        if tp not in modified_files:
                            modified_files[tp] = tp.read_text(encoding="utf-8")
                        _update_task_file_headers_and_state(tp, None, conditions=new_c_val)

                for n_id, n_node in tree.items():
                    if n_node.is_leaf and n_node.own_fields.get("conditions"):
                        raw_c = n_node.own_fields["conditions"]
                        cond_list = parse_conditions_field(raw_c)
                        if question_id in cond_list:
                            new_conds = [c for c in cond_list if c != question_id]
                            new_c_val = ", ".join(new_conds) if new_conds else "-"
                            plan_p = pathlib.Path(n_node.file_path)
                            if plan_p not in modified_files:
                                modified_files[plan_p] = plan_p.read_text(encoding="utf-8")
                            rewrite_block_in_file(plan_p, n_id, new_conditions=new_c_val)

                index_path = tasks_dir / "00-INDEX.md"
                if index_path.is_file():
                    idx_text = index_path.read_text(encoding="utf-8")
                    if idx_text.strip():
                        if index_path not in modified_files:
                            modified_files[index_path] = idx_text
                        try:
                            rendered = render_synced_index(tasks_dir, idx_text)
                            _atomic_write_text(index_path, rendered)
                        except Exception:
                            pass

                _emit_event(
                    tasks_dir,
                    "question.moved",
                    {
                        "to": to.strip(),
                        "reason": reason.strip() if reason else None,
                        "by": by or "owner",
                        "unblocked_tasks": unblocked,
                    },
                    subject=question_id,
                    actor=by or "owner",
                )
                for tid in unblocked:
                    _emit_event(
                        tasks_dir,
                        "task.transitioned",
                        {
                            "from": "waiting",
                            "to": unblocked_states.get(tid, "open"),
                            "actor": by or "owner",
                            "reason": f"Unblocked: question {question_id} moved to tracker ({to.strip()})",
                        },
                        subject=tid,
                        actor=by or "owner",
                    )

                return True, {
                    "ok": True,
                    "id": question_id,
                    "status": "moved",
                    "moved_to": to.strip(),
                    "reason": reason.strip() if reason else None,
                    "unblocked_tasks": unblocked,
                    "file_path": str(dest_file),
                    "rel_path": dest_file.relative_to(tasks_dir).as_posix(),
                }
            except Exception:
                for cp in created_files:
                    try:
                        if cp.is_file():
                            cp.unlink()
                    except OSError:
                        pass
                for mp, orig_text in modified_files.items():
                    try:
                        _atomic_write_text(mp, orig_text)
                    except OSError:
                        pass
                raise
    except LockTimeoutError:
        return False, {
            "ok": False,
            "error": "lock-timeout",
            "message": "Timed out waiting for task-write lock in tasks/.",
        }


def cmd_questions_move(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = move_question(
        tasks_dir=tasks_dir,
        question_id=args.question_id,
        to=args.to,
        reason=getattr(args, "reason", None),
        by=getattr(args, "by", "owner"),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            unb = ", ".join(res["unblocked_tasks"]) if res["unblocked_tasks"] else "none"
            print(f"[ok] Moved {res['id']} to {res['moved_to']} (unblocked tasks: {unb})")
        else:
            print(f"[FAIL] {res.get('error', 'move failed')}", file=sys.stderr)
    return 0 if ok else 1


def read_applied_ledger(tasks_dir: pathlib.Path) -> list[dict[str, Any]]:
    ledger_path = pathlib.Path(tasks_dir) / "questions" / "applied.jsonl"
    if not ledger_path.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    records.append(entry)
    except Exception:
        pass
    return records


def apply_question(
    tasks_dir: pathlib.Path,
    question_id: str,
    by: str = "owner",
    ref: str | None = None,
    note: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            questions = discover_questions(tasks_dir)
            target_q = next((q for q in questions if q["id"] == question_id), None)
            if target_q is None:
                return False, {"ok": False, "error": f"Question {question_id!r} not found in {tasks_dir}."}

            if target_q["status"] != "answered":
                return False, {
                    "ok": False,
                    "error": f"Question {question_id!r} is in status '{target_q['status']}', expected 'answered'.",
                }

            questions_dir = tasks_dir / "questions"
            ledger_path = questions_dir / "applied.jsonl"
            if ledger_path.is_file() and not force:
                try:
                    for line in ledger_path.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        entry = json.loads(line)
                        if isinstance(entry, dict) and entry.get("question") == question_id:
                            return False, {
                                "ok": False,
                                "error": f"Question {question_id!r} is already recorded as applied. Pass --force to re-apply.",
                            }
                except Exception:
                    pass

            resolved_ref = ref or note or "-"
            resolved_note = note or ref or "-"
            by_clean = by.strip() if by else "owner"

            if dry_run:
                return True, {
                    "ok": True,
                    "dry_run": True,
                    "id": question_id,
                    "by": by_clean,
                    "ref": resolved_ref,
                    "note": resolved_note,
                }

            questions_dir.mkdir(parents=True, exist_ok=True)
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            record = {
                "question": question_id,
                "by": by_clean,
                "at": now_iso,
                "ref": resolved_ref,
                "note": resolved_note,
            }

            line_str = json.dumps(record, sort_keys=True) + "\n"
            with open(ledger_path, "a", encoding="utf-8") as f:
                f.write(line_str)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

            q_file = pathlib.Path(target_q["file_path"])
            if q_file.is_file():
                q_text = q_file.read_text(encoding="utf-8")
                if re.search(r"^-\s+applied:", q_text, re.MULTILINE):
                    new_q_text = re.sub(r"^-\s+applied:.*$", "- applied: yes", q_text, flags=re.MULTILINE)
                else:
                    m = re.search(r"^(-\s+recommended:.*$)", q_text, re.MULTILINE)
                    if m:
                        new_q_text = q_text[:m.end()] + "\n- applied: yes" + q_text[m.end():]
                    else:
                        m2 = re.search(r"^(-\s+status:.*$)", q_text, re.MULTILINE)
                        new_q_text = q_text[:m2.end()] + "\n- applied: yes" + q_text[m2.end():]
                _atomic_write_text(q_file, new_q_text)

            _emit_event(
                tasks_dir,
                "question.applied",
                record,
                subject=question_id,
                actor=by_clean,
            )

            return True, {
                "ok": True,
                "id": question_id,
                "status": "applied",
                "by": by_clean,
                "record": record,
            }
    except LockTimeoutError:
        return False, {
            "ok": False,
            "error": "lock-timeout",
            "message": "Timed out waiting for task-write lock in tasks/.",
        }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def cmd_questions_apply(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = apply_question(
        tasks_dir=tasks_dir,
        question_id=args.question_id,
        by=getattr(args, "by", "owner") or "owner",
        ref=getattr(args, "ref", None),
        note=getattr(args, "note", None),
        force=getattr(args, "force", False),
        dry_run=getattr(args, "dry_run", False),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            action = "Planned application of" if getattr(args, "dry_run", False) else "Applied"
            rec = res.get("record", {})
            print(f"[ok] {action} decision for {res['id']} by {res.get('by', rec.get('by', 'owner'))}")
        else:
            print(f"[FAIL] {res.get('error', 'apply failed')}", file=sys.stderr)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Use Cases Commands (Spec 15)
# ---------------------------------------------------------------------------

def cmd_use_cases_list(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ucs = discover_use_cases(tasks_dir)
    status_filter = getattr(args, "status", None)
    if status_filter and status_filter != "all":
        ucs = [u for u in ucs if u.get("status") == status_filter]

    payload = {
        "ok": True,
        "tasks_dir": str(tasks_dir),
        "total": len(ucs),
        "use_cases": ucs,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        if not ucs:
            print(f"No use cases found in {tasks_dir}/use-cases.")
        else:
            print(f"Use Cases ({len(ucs)}):")
            for u in ucs:
                v = f"[{u.get('last_verdict') or 'untested'}]"
                print(f"  [{u['id']}] ({u.get('status')}) {u['title']} — Actor: {u.get('actor')} {v}")
    return 0


def cmd_use_cases_show(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ucs = discover_use_cases(tasks_dir)
    target = next((u for u in ucs if u["id"] == args.uc_id), None)
    if not target:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": f"Use case {args.uc_id} not found"}, indent=2))
        else:
            print(f"[FAIL] Use case {args.uc_id} not found.")
        return 1

    payload = {"ok": True, "use_case": target}
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"Use Case : {target['id']} — {target['title']}")
        print(f"Actor    : {target['actor']}")
        print(f"Status   : {target['status']} (Last tested: {target.get('last_tested') or '-'}, Verdict: {target.get('last_verdict') or '-'})")
        print(f"Priority : {target['priority']}")
        print(f"Linked   : {', '.join(target['linked_tasks']) or '-'}")
        if target.get("verification_command"):
            print(f"Command  : {target['verification_command']}")
    return 0


def cmd_use_cases_create(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    linked_raw = getattr(args, "linked_tasks", "") or ""
    data = {
        "id": args.id,
        "title": args.title,
        "actor": getattr(args, "actor", "End-User"),
        "status": getattr(args, "status", "draft"),
        "priority": getattr(args, "priority", "P1"),
        "linked_tasks": [t.strip() for t in linked_raw.split(",") if t.strip() and t.strip() != "-"],
        "verification_type": getattr(args, "verification_type", "automated-probe"),
        "verification_command": getattr(args, "verification_command", "echo 'No verification command specified'"),
        "description": getattr(args, "description", ""),
        "preconditions": getattr(args, "preconditions", ""),
        "scenario": getattr(args, "scenario", ""),
        "short": getattr(args, "short", None),
    }
    ok, res = create_or_update_use_case(tasks_dir, data)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Created use case {args.id} at {res['file_path']}")
        else:
            print(f"[FAIL] {res.get('error')}")
    return 0 if ok else 1


def cmd_use_cases_record_validation(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    gaps_raw = getattr(args, "gaps", None)
    gaps = [g.strip() for g in gaps_raw.split(";") if g.strip()] if gaps_raw else None
    ok, res = record_use_case_validation(
        tasks_dir=tasks_dir,
        uc_id=args.uc_id,
        verdict=args.verdict,
        summary=args.summary,
        evidence=getattr(args, "evidence", ""),
        actor=getattr(args, "actor", "ai-validator"),
        gaps=gaps,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Recorded validation for {args.uc_id}: verdict={res['verdict']}, status={res['status']}")
        else:
            print(f"[FAIL] {res.get('error')}")
    return 0 if ok else 1


def cmd_use_cases_validate(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    timeout = getattr(args, "timeout", 60)
    actor = getattr(args, "actor", "ai-validator")
    ok, res = validate_use_case_probe(tasks_dir, args.uc_id, timeout_seconds=timeout, actor=actor)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            v = res.get("verdict", "unknown").upper()
            print(f"[{v}] {args.uc_id}: {res.get('summary')}")
            if res.get("command"):
                print(f"  Command: {res['command']}")
            if res.get("exit_code") is not None:
                print(f"  Exit code: {res['exit_code']} ({res.get('elapsed_seconds')}s)")
        else:
            print(f"[FAIL] {res.get('error')}")
    return 0 if ok and res.get("verdict") == "pass" else 1


def cmd_use_cases_campaign(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    timeout = getattr(args, "timeout", 60)
    actor = getattr(args, "actor", "campaign-runner")
    actor_filter = getattr(args, "filter_actor", None)
    res = run_validation_campaign(tasks_dir, timeout_seconds=timeout, actor_filter=actor_filter, actor_name=actor)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        print(f"Product Validation Campaign ({res['timestamp']}):")
        print(f"  Readiness Score: {res['readiness_score']}% ({res['passed']}/{res['total']} verified)")
        print(f"  Passed: {res['passed']}, Failed: {res['failed']}, Regressions: {res['regressions_count']}")
        print(f"  Report: {res['report_file']}")
        if res["regressions"]:
            print("\n  REGRESSIONS:")
            for reg in res["regressions"]:
                print(f"    - {reg['id']}: {reg['title']}")
    return 0 if res["failed"] == 0 else 1


# ---------------------------------------------------------------------------
# Inbox Notes (N###) Data Model, Operations & Commands
# ---------------------------------------------------------------------------

def sniff_image_type(data: bytes, original_suffix: str = "") -> tuple[str, str] | None:
    """Sniff image type from magic bytes. Returns (type_name, extension) or None."""
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", ".png"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        ext = ".jpeg" if original_suffix.lower() == ".jpeg" else ".jpg"
        return "jpeg", ext
    if len(data) >= 6 and (data[:6] == b"GIF87a" or data[:6] == b"GIF89a"):
        return "gif", ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", ".webp"
    return None


def validate_and_classify_attachment(
    data: bytes, original_suffix: str
) -> tuple[bool, str, str, str, str]:
    """Validate and classify attachment data.
    Returns (ok, att_class, real_ext, error_code, error_message).
    Classes: 'image', 'pdf', 'text'.
    """
    if len(data) > MAX_ATTACHMENT_SIZE:
        return False, "", "", "size-limit-exceeded", f"Attachment exceeds 10 MB limit ({len(data)} bytes)."

    ext_lower = original_suffix.lower()

    # 1. Image check by magic bytes
    sniff = sniff_image_type(data, original_suffix=original_suffix)
    if sniff is not None:
        return True, "image", sniff[1], "", ""

    # 2. PDF check
    if data.startswith(b"%PDF-"):
        return True, "pdf", ".pdf", "", ""

    # If image extension was specified but magic bytes failed
    if ext_lower in IMAGE_EXTENSIONS:
        return (
            False,
            "",
            "",
            "invalid-image-type",
            "File is not a supported image (magic bytes do not match png, jpeg, gif, or webp).",
        )

    # If PDF extension was specified but didn't start with %PDF-
    if ext_lower == ".pdf":
        return (
            False,
            "",
            "",
            "invalid-pdf-type",
            "File is not a valid PDF (content must start with '%PDF-').",
        )

    # 3. Text check
    if ext_lower in TEXT_EXTENSIONS:
        if b"\x00" in data[:65536]:
            return (
                False,
                "",
                "",
                "invalid-text-type",
                f"File with extension {ext_lower!r} contains NUL byte in the first 64 KB.",
            )
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as ue:
            return (
                False,
                "",
                "",
                "invalid-text-type",
                f"File with extension {ext_lower!r} is not valid UTF-8: {ue}",
            )
        return True, "text", ext_lower, "", ""

    return (
        False,
        "",
        "",
        "invalid-attachment-type",
        f"Unsupported attachment type with extension {ext_lower!r}. Allowed classes are images (png, jpeg, gif, webp), PDFs (starting with '%PDF-'), and plain text files ({', '.join(sorted(TEXT_EXTENSIONS))}).",
    )


def classify_existing_attachment_file(path: pathlib.Path) -> str:
    """Classify an existing attachment file on disk into 'image', 'pdf', or 'text'."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            chunk = f.read(min(size, 65536))
    except Exception:
        return "text"
    if sniff_image_type(chunk, original_suffix=path.suffix) is not None:
        return "image"
    if chunk.startswith(b"%PDF-"):
        return "pdf"
    return "text"


def sanitize_attachment_name(stem: str, ext: str, index: int) -> str:
    """Sanitize attachment name to <NN>-<clean><ext> (lowercase, [a-z0-9._-], max 60 chars)."""
    nn = f"{index:02d}"
    clean = re.sub(r"[^a-z0-9._-]+", "-", stem.lower()).strip("-._")
    if not clean:
        clean = "attachment"
    max_stem_len = 60 - len(nn) - 1 - len(ext)
    clean = clean[:max_stem_len].rstrip("-._")
    if not clean:
        clean = "att"
    return f"{nn}-{clean}{ext}"


def validate_attachment_name(name: str, attachments_dir: pathlib.Path) -> pathlib.Path:
    """Validate attachment name against path traversal and return resolved path."""
    if not name or "/" in name or "\\" in name or "\x00" in name or name in (".", "..") or ".." in name:
        raise ValueError(f"Invalid attachment name: path traversal or invalid characters in {name!r}")
    target = (attachments_dir / name).resolve()
    base = attachments_dir.resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Invalid attachment name: path traversal in {name!r}")
    if not target.is_file():
        raise FileNotFoundError(f"Attachment {name!r} not found in {attachments_dir}")
    return target


def note_bundle_sha256(path: pathlib.Path) -> str:
    """Compute sha256 of a note folder bundle (or legacy single-file note)."""
    if path.is_dir():
        return _folder_bundle_sha256(path)
    return _file_sha256(path)


def format_note_content(
    id: str,
    title: str,
    kind: str,
    status: str,
    created: str,
    author: str = "owner",
    about: str = "-",
    produced: str = "-",
    processed_by: str = "-",
    body: str = "",
    short: str | None = None,
) -> str:
    lines = [
        f"# {id} {title}",
        "",
        f"- id: {id}",
        f"- title: {title}",
        f"- kind: {kind}",
        f"- status: {status}",
        f"- created: {created}",
        f"- author: {author}",
        f"- about: {about if about and about.strip() else '-'}",
        f"- produced: {produced if produced and produced.strip() else '-'}",
        f"- processed-by: {processed_by if processed_by and processed_by.strip() else '-'}",
    ]
    if short and short.strip() and short.strip() != "-":
        lines.append(f"- short: {short.strip()}")
    lines.append("")
    if body:
        lines.append(body.strip("\r\n"))
        lines.append("")
    return "\n".join(lines)


def parse_note_folder(
    folder_path: pathlib.Path,
    tasks_dir: pathlib.Path,
    in_analyzed: bool = False,
) -> dict[str, Any]:
    note_file = folder_path / "note.md"
    text = note_file.read_text(encoding="utf-8")
    scanned_lines, _ = scan_markdown_blocks(text)

    rel_path = note_file.relative_to(tasks_dir).as_posix()

    h1_idx: int | None = None
    h1_text = ""
    for idx, sline in enumerate(scanned_lines):
        if not sline.is_fenced and sline.text.startswith("# "):
            h1_idx = idx
            h1_text = sline.text[2:].strip()
            break

    header_keys: list[str] = []
    headers: dict[str, str] = {}

    scan_start = (h1_idx + 1) if h1_idx is not None else 0
    idx = scan_start
    while idx < len(scanned_lines) and not scanned_lines[idx].text.strip():
        idx += 1
    while idx < len(scanned_lines):
        sline = scanned_lines[idx]
        if sline.is_fenced:
            break
        m = HEADER_LINE_RE.match(sline.text)
        if not m:
            break
        k, v = m.group(1), m.group(2).strip()
        header_keys.append(k)
        headers[k] = v
        idx += 1
    header_end = idx

    body_lines = [sline.text for sline in scanned_lines[header_end:]]
    body = "\n".join(body_lines).strip()

    attachments_dir = folder_path / "attachments"
    attachments: list[dict[str, Any]] = []
    if attachments_dir.is_dir():
        for f in sorted(attachments_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                att_class = classify_existing_attachment_file(f)
                attachments.append({
                    "name": f.name,
                    "class": att_class,
                    "size": f.stat().st_size,
                })

    note_id = headers.get("id", "")
    title = headers.get("title", "")
    if not title and h1_text:
        parts = h1_text.split(None, 1)
        if len(parts) > 1 and NOTE_ID_RE.match(parts[0]):
            title = parts[1].strip()
        else:
            title = h1_text

    bundle_hash = _folder_bundle_sha256(folder_path)

    short_field = headers.get("short")
    if short_field and str(short_field).strip() and str(short_field).strip() != "-":
        n_st_val = str(short_field).strip()
        n_st_src = "field"
    else:
        n_st_val = derive_short_title(title)
        n_st_src = "derived"

    return {
        "id": note_id,
        "title": title,
        "short": short_field if (short_field and str(short_field).strip() != "-") else None,
        "short_title": n_st_val,
        "short_title_source": n_st_src,
        "kind": headers.get("kind", "note"),
        "status": headers.get("status", "draft"),
        "created": headers.get("created", ""),
        "author": headers.get("author", "owner"),
        "about": headers.get("about", "-"),
        "produced": headers.get("produced", "-"),
        "processed_by": headers.get("processed-by", "-"),
        "body": body,
        # `attachments` stays a list of names (UI contract since 09.2); details per file:
        "attachments": [a["name"] for a in attachments],
        "attachment_details": attachments,
        "bundle_sha256": bundle_hash,
        "legacy": False,
        "folder_name": folder_path.name,
        "folder_path": str(folder_path),
        "file_path": str(note_file),
        "rel_path": rel_path,
        "in_analyzed": in_analyzed,
        "headers": headers,
        "header_keys": header_keys,
    }


def parse_legacy_note_file(
    file_path: pathlib.Path,
    tasks_dir: pathlib.Path,
    in_analyzed: bool = False,
) -> dict[str, Any]:
    text = file_path.read_text(encoding="utf-8")
    scanned_lines, _ = scan_markdown_blocks(text)
    rel_path = file_path.relative_to(tasks_dir).as_posix()

    h1_text = ""
    for sline in scanned_lines:
        if not sline.is_fenced and sline.text.startswith("# "):
            h1_text = sline.text[2:].strip()
            break

    title = h1_text or file_path.stem
    m_date = re.match(r"^(\d{4}-\d{2}-\d{2})", file_path.stem)
    if m_date:
        created = f"{m_date.group(1)}T00:00:00Z"
    else:
        try:
            mtime = file_path.stat().st_mtime
            created = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()
        except OSError:
            created = "-"

    status = "processed" if in_analyzed else "ready"
    bundle_hash = _file_sha256(file_path)

    return {
        "id": "-",
        "title": title,
        "short": None,
        "short_title": derive_short_title(title),
        "short_title_source": "derived",
        "kind": "note",
        "status": status,
        "created": created,
        "author": "owner",
        "about": "-",
        "produced": "-",
        "processed_by": "-",
        "body": text.strip(),
        "attachments": [],
        "attachment_details": [],
        "bundle_sha256": bundle_hash,
        "legacy": True,
        "folder_name": file_path.name,
        "folder_path": str(file_path.parent),
        "file_path": str(file_path),
        "rel_path": rel_path,
        "in_analyzed": in_analyzed,
        "headers": {},
        "header_keys": [],
    }


def discover_inbox_notes(tasks_dir: pathlib.Path) -> list[dict[str, Any]]:
    inbox_dir = tasks_dir / "_inbox"
    if not inbox_dir.is_dir():
        return []

    notes: list[dict[str, Any]] = []

    def scan_dir(d: pathlib.Path, in_analyzed: bool) -> None:
        if not d.is_dir():
            return
        for child in sorted(d.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                if (child / "note.md").is_file():
                    try:
                        notes.append(parse_note_folder(child, tasks_dir, in_analyzed=in_analyzed))
                    except Exception:
                        pass
            elif child.is_file() and child.suffix == ".md":
                try:
                    notes.append(parse_legacy_note_file(child, tasks_dir, in_analyzed=in_analyzed))
                except Exception:
                    pass

    scan_dir(inbox_dir / "to-analyze", in_analyzed=False)
    scan_dir(inbox_dir / "analyzed", in_analyzed=True)
    return notes


def find_inbox_note(tasks_dir: pathlib.Path, target: str) -> dict[str, Any] | None:
    notes = discover_inbox_notes(tasks_dir)
    target_clean = target.strip()
    if NOTE_ID_RE.match(target_clean):
        for n in notes:
            if n["id"] == target_clean:
                return n
        return None

    for n in notes:
        if n["folder_name"] == target_clean or n["rel_path"] == target_clean:
            return n
    for n in notes:
        if n["legacy"] and (pathlib.Path(n["file_path"]).stem == target_clean or n["folder_name"].startswith(target_clean)):
            return n
    return None


def convert_legacy_note_to_folder(tasks_dir: pathlib.Path, note: dict[str, Any]) -> dict[str, Any]:
    all_notes = discover_inbox_notes(tasks_dir)
    existing_nums = [
        int(n["id"][1:]) for n in all_notes if n["id"] and NOTE_ID_RE.match(n["id"])
    ]
    next_num = max(existing_nums, default=0) + 1
    new_id = f"N{next_num:03d}"

    legacy_file = pathlib.Path(note["file_path"])
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", legacy_file.stem.lower()).strip("-")[:40] or "note"
    folder_name = f"{ts}-{slug}"

    parent_dir = legacy_file.parent
    folder_path = parent_dir / folder_name
    idx_suffix = 1
    while folder_path.exists():
        idx_suffix += 1
        folder_path = parent_dir / f"{ts}-{slug}-{idx_suffix}"

    folder_path.mkdir(parents=True, exist_ok=False)
    (folder_path / "attachments").mkdir(parents=True, exist_ok=True)

    title = note["title"] or legacy_file.stem
    content = format_note_content(
        id=new_id,
        title=title,
        kind="note",
        status=note["status"],
        created=note["created"] if note["created"] and note["created"] != "-" else now.isoformat(),
        author=note["author"],
        about="-",
        produced="-",
        processed_by="-",
        body=note["body"],
    )

    note_path = folder_path / "note.md"
    _atomic_write_text(note_path, content)
    try:
        legacy_file.unlink()
    except OSError:
        pass

    return parse_note_folder(folder_path, tasks_dir, in_analyzed=note["in_analyzed"])


def inbox_add(
    tasks_dir: pathlib.Path,
    title: str,
    kind: str = "note",
    body: str | None = None,
    body_file: str | pathlib.Path | None = None,
    about: str = "-",
    author: str = "owner",
    status: str = "draft",
    short: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    if short and short.strip() and short.strip() != "-":
        issues = validate_short_title(short.strip())
        if issues:
            return False, {"ok": False, "error": f"Invalid short title {short!r}: {'; '.join(issues)}."}

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if not title or not title.strip():
        return False, {"ok": False, "error": "Missing required --title."}
    title = title.strip()

    if kind not in NOTE_KINDS:
        return False, {"ok": False, "error": f"Invalid kind {kind!r} (expected one of {sorted(NOTE_KINDS)})."}

    if status not in ("draft", "ready"):
        return False, {"ok": False, "error": f"Initial status must be 'draft' or 'ready' (got {status!r})."}

    if body_file:
        bf = pathlib.Path(body_file)
        if not bf.is_file():
            return False, {"ok": False, "error": f"Body file not found: {body_file}"}
        body_text = bf.read_text(encoding="utf-8")
    else:
        body_text = body or ""

    try:
        with task_write_lock(tasks_dir):
            all_notes = discover_inbox_notes(tasks_dir)
            existing_nums = [
                int(n["id"][1:]) for n in all_notes if n["id"] and NOTE_ID_RE.match(n["id"])
            ]
            next_num = max(existing_nums, default=0) + 1

            to_analyze_dir = tasks_dir / "_inbox" / "to-analyze"
            to_analyze_dir.mkdir(parents=True, exist_ok=True)

            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "note"
            now = datetime.datetime.now(datetime.timezone.utc)
            ts = now.strftime("%Y%m%d-%H%M%S")

            note_id = ""
            folder_path = None
            fd = None

            while True:
                note_id = f"N{next_num:03d}"
                folder_name = f"{ts}-{slug}"
                candidate_folder = to_analyze_dir / folder_name
                if candidate_folder.exists():
                    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
                    folder_name = f"{ts}-{slug}-{next_num}"
                    candidate_folder = to_analyze_dir / folder_name
                try:
                    candidate_folder.mkdir(parents=True, exist_ok=False)
                except FileExistsError:
                    next_num += 1
                    continue

                attachments_dir = candidate_folder / "attachments"
                attachments_dir.mkdir(parents=True, exist_ok=True)

                candidate_file = candidate_folder / "note.md"
                try:
                    fd = os.open(str(candidate_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    folder_path = candidate_folder
                    break
                except FileExistsError:
                    next_num += 1

            created_iso = now.isoformat()
            short_val = short.strip() if short and short.strip() and short.strip() != "-" else derive_short_title(title.strip())
            content = format_note_content(
                id=note_id,
                title=title,
                kind=kind,
                status=status,
                created=created_iso,
                author=author or "owner",
                about=about or "-",
                produced="-",
                processed_by="-",
                body=body_text,
                short=short_val,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
            except BaseException:
                if folder_path and folder_path.exists():
                    shutil.rmtree(folder_path, ignore_errors=True)
                raise

            parsed = parse_note_folder(folder_path, tasks_dir, in_analyzed=False)
            if status == "ready":
                _emit_event(
                    tasks_dir,
                    "note.ready",
                    {
                        "id": note_id,
                        "title": title,
                        "kind": kind,
                        "status": "ready",
                        "author": author,
                    },
                    subject=note_id,
                    actor=author,
                )
            else:
                _emit_event(
                    tasks_dir,
                    "note.created",
                    {
                        "id": note_id,
                        "title": title,
                        "kind": kind,
                        "status": status or "draft",
                        "author": author,
                    },
                    subject=note_id,
                    actor=author,
                )
            return True, {
                "ok": True,
                "id": note_id,
                "folder": folder_path.name,
                "rel_path": parsed["rel_path"],
                "bundle_sha256": parsed["bundle_sha256"],
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def inbox_edit(
    tasks_dir: pathlib.Path,
    target: str,
    title: str | None = None,
    kind: str | None = None,
    body: str | None = None,
    body_file: str | pathlib.Path | None = None,
    about: str | None = None,
    author: str | None = None,
    status: str | None = None,
    expect_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            note = find_inbox_note(tasks_dir, target)
            if not note:
                return False, {"ok": False, "error": f"Inbox note {target!r} not found."}

            if note["legacy"]:
                note = convert_legacy_note_to_folder(tasks_dir, note)

            folder_path = pathlib.Path(note["folder_path"])

            current_status = note["status"]
            if current_status == "processing":
                return False, {
                    "ok": False,
                    "error": "locked-processing",
                    "message": f"Note {note['id']} is currently processing and locked against edits.",
                }
            if current_status in ("processed", "discarded"):
                return False, {
                    "ok": False,
                    "error": "note-closed",
                    "message": f"Note {note['id']} is {current_status}; reopen it first before editing.",
                }

            if expect_hash:
                actual_hash = note["bundle_sha256"]
                if actual_hash != expect_hash:
                    return False, {
                        "ok": False,
                        "error": "stale-note",
                        "expected": expect_hash,
                        "actual": actual_hash,
                    }

            new_title = title.strip() if title is not None else note["title"]
            new_kind = kind.strip() if kind is not None else note["kind"]
            if new_kind not in NOTE_KINDS:
                return False, {"ok": False, "error": f"Invalid kind {new_kind!r}."}

            if status is not None:
                if status not in ("draft", "ready"):
                    return False, {
                        "ok": False,
                        "error": f"Invalid status transition to {status!r} via edit (only 'draft' or 'ready' allowed).",
                    }
                new_status = status
            else:
                new_status = note["status"]

            if body_file:
                bf = pathlib.Path(body_file)
                if not bf.is_file():
                    return False, {"ok": False, "error": f"Body file not found: {body_file}"}
                new_body = bf.read_text(encoding="utf-8")
            elif body is not None:
                new_body = body
            else:
                new_body = note["body"]

            new_about = about.strip() if about is not None else note["about"]
            new_author = author.strip() if author is not None else note["author"]

            content = format_note_content(
                id=note["id"],
                title=new_title,
                kind=new_kind,
                status=new_status,
                created=note["created"],
                author=new_author,
                about=new_about,
                produced=note["produced"],
                processed_by=note["processed_by"],
                body=new_body,
            )

            note_file = folder_path / "note.md"
            _atomic_write_text(note_file, content)

            updated = parse_note_folder(folder_path, tasks_dir, in_analyzed=note["in_analyzed"])
            if new_status == "ready" and note.get("status") != "ready":
                _emit_event(
                    tasks_dir,
                    "note.ready",
                    {
                        "id": updated["id"],
                        "status": "ready",
                    },
                    subject=updated["id"],
                )
            else:
                _emit_event(
                    tasks_dir,
                    "note.updated",
                    {
                        "id": updated["id"],
                        "status": updated["status"],
                    },
                    subject=updated["id"],
                )
            return True, {
                "ok": True,
                "id": updated["id"],
                "status": updated["status"],
                "bundle_sha256": updated["bundle_sha256"],
                "rel_path": updated["rel_path"],
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def inbox_attach(
    tasks_dir: pathlib.Path,
    target: str,
    file_path: str | pathlib.Path,
    name: str | None = None,
    expect_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if name:
        if "/" in name or "\\" in name or "\x00" in name or ".." in name:
            return False, {
                "ok": False,
                "error": "invalid-attachment-name",
                "message": f"Invalid attachment name: path traversal or invalid characters in {name!r}",
            }

    src = pathlib.Path(file_path).resolve()
    if not src.is_file():
        return False, {"ok": False, "error": f"Attachment file not found: {file_path}"}

    data = src.read_bytes()
    ok_att, att_class, real_ext, err_code, err_msg = validate_and_classify_attachment(data, src.suffix)
    if not ok_att:
        return False, {
            "ok": False,
            "error": err_code,
            "message": err_msg,
        }

    try:
        with task_write_lock(tasks_dir):
            note = find_inbox_note(tasks_dir, target)
            if not note:
                return False, {"ok": False, "error": f"Inbox note {target!r} not found."}

            if note["legacy"]:
                note = convert_legacy_note_to_folder(tasks_dir, note)

            folder_path = pathlib.Path(note["folder_path"])
            current_status = note["status"]
            if current_status == "processing":
                return False, {
                    "ok": False,
                    "error": "locked-processing",
                    "message": f"Note {note['id']} is currently processing and locked against edits.",
                }
            if current_status in ("processed", "discarded"):
                return False, {
                    "ok": False,
                    "error": "note-closed",
                    "message": f"Note {note['id']} is {current_status}; reopen it first before modifying attachments.",
                }

            if expect_hash:
                actual_hash = note["bundle_sha256"]
                if actual_hash != expect_hash:
                    return False, {
                        "ok": False,
                        "error": "stale-note",
                        "expected": expect_hash,
                        "actual": actual_hash,
                    }

            attachments_dir = folder_path / "attachments"
            attachments_dir.mkdir(parents=True, exist_ok=True)

            existing_files = [f.name for f in attachments_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
            if len(existing_files) >= MAX_ATTACHMENTS_PER_NOTE:
                return False, {
                    "ok": False,
                    "error": "attachment-limit-reached",
                    "message": f"Note {note['id']} already has the maximum allowed attachments ({MAX_ATTACHMENTS_PER_NOTE}).",
                }

            existing_nums = [
                int(m.group(1)) for f in existing_files if (m := re.match(r"^(\d{2})-", f))
            ]
            next_idx = max(existing_nums, default=0) + 1

            stem = name if name else src.stem
            dest_filename = sanitize_attachment_name(stem, real_ext, next_idx)
            dest_path = attachments_dir / dest_filename

            shutil.copy2(src, dest_path)

            if att_class == "image":
                markdown_ref = f"![](attachments/{dest_filename})"
            else:
                markdown_ref = f"[{dest_filename}](attachments/{dest_filename})"

            updated = parse_note_folder(folder_path, tasks_dir, in_analyzed=note["in_analyzed"])

            _emit_event(
                tasks_dir,
                "note.attached",
                {
                    "id": updated["id"],
                    "name": dest_filename,
                    "class": att_class,
                    "path": str(dest_path),
                },
                subject=updated["id"],
            )

            return True, {
                "ok": True,
                "id": updated["id"],
                "attachment": dest_filename,
                "class": att_class,
                "markdown": markdown_ref,
                "path": str(dest_path),
                "bundle_sha256": updated["bundle_sha256"],
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def inbox_detach(
    tasks_dir: pathlib.Path,
    target: str,
    name: str,
    expect_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if not name or "/" in name or "\\" in name or "\x00" in name or ".." in name:
        return False, {
            "ok": False,
            "error": "invalid-attachment",
            "message": f"Invalid attachment name: {name!r}",
        }

    try:
        with task_write_lock(tasks_dir):
            note = find_inbox_note(tasks_dir, target)
            if not note:
                return False, {"ok": False, "error": f"Inbox note {target!r} not found."}

            if note["legacy"]:
                return False, {"ok": False, "error": "Legacy notes have no attachments."}

            folder_path = pathlib.Path(note["folder_path"])
            current_status = note["status"]
            if current_status == "processing":
                return False, {
                    "ok": False,
                    "error": "locked-processing",
                    "message": f"Note {note['id']} is currently processing and locked.",
                }
            if current_status in ("processed", "discarded"):
                return False, {
                    "ok": False,
                    "error": "note-closed",
                    "message": f"Note {note['id']} is {current_status}; reopen it first.",
                }

            if expect_hash:
                actual_hash = note["bundle_sha256"]
                if actual_hash != expect_hash:
                    return False, {
                        "ok": False,
                        "error": "stale-note",
                        "expected": expect_hash,
                        "actual": actual_hash,
                    }

            attachments_dir = folder_path / "attachments"
            try:
                target_file = validate_attachment_name(name, attachments_dir)
            except (ValueError, FileNotFoundError) as ve:
                return False, {"ok": False, "error": "invalid-attachment", "message": str(ve)}

            target_file.unlink()
            updated = parse_note_folder(folder_path, tasks_dir, in_analyzed=note["in_analyzed"])

            _emit_event(
                tasks_dir,
                "note.detached",
                {
                    "id": updated["id"],
                    "name": name,
                },
                subject=updated["id"],
            )

            return True, {
                "ok": True,
                "id": updated["id"],
                "detached": name,
                "bundle_sha256": updated["bundle_sha256"],
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def _rewrite_sources_value(
    sources_val: str,
    old_folder_rel: str,
    new_folder_rel: str,
    legacy_rel: str | None = None,
) -> tuple[str, bool]:
    val = sources_val
    changed = False

    if legacy_rel and legacy_rel in val:
        legacy_pat = re.compile(
            rf"(^|[\s,;\[\(\"\'])(?:tasks/)?{re.escape(legacy_rel)}(?=[\s,;\)\]\"\']|$)"
        )
        new_val = legacy_pat.sub(
            lambda m: f"{m.group(1)}{new_folder_rel}/note.md", val
        )
        if new_val != val:
            val = new_val
            changed = True

    pat = re.compile(
        rf"(^|[\s,;\[\(\"\'])(?:tasks/)?{re.escape(old_folder_rel)}((?:/[^\s,;\)\]\"\']*)?)(?=[\s,;\)\]\"\']|$)"
    )

    def _repl(m: re.Match[str]) -> str:
        lead = m.group(1)
        tail = m.group(2)
        return f"{lead}{new_folder_rel}{tail}"

    new_val = pat.sub(_repl, val)
    if new_val != val:
        val = new_val
        changed = True

    return val, changed


def _rewrite_task_sources(
    content: str,
    old_folder_rel: str,
    new_folder_rel: str,
    legacy_rel: str | None = None,
) -> tuple[str, bool]:
    raw_lines = content.splitlines()
    scanned_lines, _ = scan_markdown_blocks(content)

    h1_idx: int | None = None
    for idx, sline in enumerate(scanned_lines):
        if not sline.is_fenced and sline.text.startswith("# "):
            h1_idx = idx
            break

    if h1_idx is None:
        return content, False

    scan_start = h1_idx + 1
    while scan_start < len(scanned_lines) and not scanned_lines[scan_start].text.strip():
        scan_start += 1

    idx = scan_start
    sources_idx: int | None = None
    old_val = ""

    while idx < len(scanned_lines):
        sline = scanned_lines[idx]
        if sline.is_fenced:
            break
        m = HEADER_LINE_RE.match(sline.text)
        if not m:
            break
        k, v = m.group(1), m.group(2).strip()
        if k == "sources":
            sources_idx = idx
            old_val = v
            break
        idx += 1

    if sources_idx is None:
        return content, False

    new_val, changed = _rewrite_sources_value(
        old_val,
        old_folder_rel=old_folder_rel,
        new_folder_rel=new_folder_rel,
        legacy_rel=legacy_rel,
    )
    if not changed:
        return content, False

    raw_lines[sources_idx] = f"- sources: {new_val}"
    new_content = "\n".join(raw_lines)
    if content.endswith("\r\n"):
        new_content += "\r\n"
    elif content.endswith("\n"):
        new_content += "\n"
    return new_content, True


def _move_note_folder_and_rewrite_sources(
    tasks_dir: pathlib.Path,
    folder_path: pathlib.Path,
    dst_dir: pathlib.Path,
    new_note_content: str,
    produced_hint: str | None = None,
    legacy_info: tuple[pathlib.Path, str, str] | None = None,
) -> tuple[pathlib.Path, list[str]]:
    folder_name = folder_path.name
    dst_folder = dst_dir / folder_name
    old_folder_rel = folder_path.relative_to(tasks_dir).as_posix()
    new_folder_rel = dst_folder.relative_to(tasks_dir).as_posix()
    legacy_rel = legacy_info[2] if legacy_info else None

    note_file = folder_path / "note.md"
    original_note_content = note_file.read_text(encoding="utf-8") if note_file.is_file() else ""

    produced_ids: list[str] = []
    if produced_hint and produced_hint.strip() and produced_hint.strip() != "-":
        produced_ids = re.findall(r"T\d{3,}", produced_hint)

    all_emergent = discover_emergent_tasks(tasks_dir)
    task_map = {t["id"]: t for t in all_emergent if t.get("id")}

    ordered_tasks: list[dict[str, Any]] = []
    seen_tids: set[str] = set()

    for pid in produced_ids:
        if pid in task_map and pid not in seen_tids:
            ordered_tasks.append(task_map[pid])
            seen_tids.add(pid)

    for t in all_emergent:
        tid = t.get("id")
        if tid and tid in seen_tids:
            continue
        ordered_tasks.append(t)
        if tid:
            seen_tids.add(tid)

    tasks_to_update: list[tuple[str, pathlib.Path, str, str]] = []
    for t in ordered_tasks:
        tfile = pathlib.Path(t["file_path"])
        try:
            task_text = tfile.read_text(encoding="utf-8")
        except Exception:
            continue
        new_task_text, changed = _rewrite_task_sources(
            task_text,
            old_folder_rel=old_folder_rel,
            new_folder_rel=new_folder_rel,
            legacy_rel=legacy_rel,
        )
        if changed:
            tasks_to_update.append((t.get("id", ""), tfile, task_text, new_task_text))

    written_tasks: list[tuple[pathlib.Path, str]] = []
    note_md_written = False
    folder_moved = False

    try:
        _atomic_write_text(note_file, new_note_content)
        note_md_written = True

        dst_dir.mkdir(parents=True, exist_ok=True)
        os.replace(folder_path, dst_folder)
        folder_moved = True

        for tid, tfile, orig_text, new_text in tasks_to_update:
            _atomic_write_text(tfile, new_text)
            written_tasks.append((tfile, orig_text))

    except BaseException as e:
        for tfile, orig_text in written_tasks:
            try:
                tfile.write_text(orig_text, encoding="utf-8")
            except Exception:
                pass

        if folder_moved:
            try:
                if dst_folder.exists() and not folder_path.exists():
                    os.replace(dst_folder, folder_path)
                    folder_moved = False
            except Exception:
                pass

        if note_md_written:
            target_note_file = (folder_path if not folder_moved else dst_folder) / "note.md"
            try:
                target_note_file.write_text(original_note_content, encoding="utf-8")
            except Exception:
                pass

        if legacy_info:
            leg_file, leg_text, _ = legacy_info
            try:
                if folder_path.exists():
                    shutil.rmtree(folder_path)
                leg_file.write_text(leg_text, encoding="utf-8")
            except Exception:
                pass

        raise e

    return dst_folder, [tid for tid, _, _, _ in tasks_to_update if tid]


def inbox_resolve(
    tasks_dir: pathlib.Path,
    target: str,
    produced: str,
    by: str = "owner",
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if not produced or not produced.strip():
        return False, {"ok": False, "error": "Missing required --produced."}

    try:
        with task_write_lock(tasks_dir):
            note = find_inbox_note(tasks_dir, target)
            if not note:
                return False, {"ok": False, "error": f"Inbox note {target!r} not found."}

            if note["in_analyzed"]:
                return False, {"ok": False, "error": f"Note {note['id']} is already in analyzed/."}

            legacy_info = None
            if note["legacy"]:
                leg_file = pathlib.Path(note["file_path"])
                leg_text = leg_file.read_text(encoding="utf-8")
                leg_rel = note["rel_path"]
                legacy_info = (leg_file, leg_text, leg_rel)
                note = convert_legacy_note_to_folder(tasks_dir, note)

            folder_path = pathlib.Path(note["folder_path"])

            content = format_note_content(
                id=note["id"],
                title=note["title"],
                kind=note["kind"],
                status="processed",
                created=note["created"],
                author=note["author"],
                about=note["about"],
                produced=produced.strip(),
                processed_by=by.strip() or "owner",
                body=note["body"],
            )

            analyzed_dir = tasks_dir / "_inbox" / "analyzed"
            dst_folder, updated_task_ids = _move_note_folder_and_rewrite_sources(
                tasks_dir=tasks_dir,
                folder_path=folder_path,
                dst_dir=analyzed_dir,
                new_note_content=content,
                produced_hint=produced.strip(),
                legacy_info=legacy_info,
            )

            updated = parse_note_folder(dst_folder, tasks_dir, in_analyzed=True)
            _emit_event(
                tasks_dir,
                "note.processed",
                {
                    "id": updated["id"],
                    "status": "processed",
                    "produced": updated["produced"],
                    "by": by.strip() or "owner",
                },
                subject=updated["id"],
                actor=by.strip() or "owner",
            )
            return True, {
                "ok": True,
                "id": updated["id"],
                "status": "processed",
                "produced": updated["produced"],
                "processed_by": updated["processed_by"],
                "folder": dst_folder.name,
                "rel_path": updated["rel_path"],
                "sources_updated": updated_task_ids,
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def inbox_discard(
    tasks_dir: pathlib.Path,
    target: str,
    reason: str,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if not reason or not reason.strip():
        return False, {"ok": False, "error": "Missing required --reason."}

    try:
        with task_write_lock(tasks_dir):
            note = find_inbox_note(tasks_dir, target)
            if not note:
                return False, {"ok": False, "error": f"Inbox note {target!r} not found."}

            if note["in_analyzed"]:
                return False, {"ok": False, "error": f"Note {note['id']} is already in analyzed/."}

            legacy_info = None
            if note["legacy"]:
                leg_file = pathlib.Path(note["file_path"])
                leg_text = leg_file.read_text(encoding="utf-8")
                leg_rel = note["rel_path"]
                legacy_info = (leg_file, leg_text, leg_rel)
                note = convert_legacy_note_to_folder(tasks_dir, note)

            folder_path = pathlib.Path(note["folder_path"])

            body = note["body"]
            if body:
                body += f"\n\n## Discard Reason\n\n{reason.strip()}"
            else:
                body = f"## Discard Reason\n\n{reason.strip()}"

            content = format_note_content(
                id=note["id"],
                title=note["title"],
                kind=note["kind"],
                status="discarded",
                created=note["created"],
                author=note["author"],
                about=note["about"],
                produced=note["produced"],
                processed_by=note["processed_by"],
                body=body,
            )

            analyzed_dir = tasks_dir / "_inbox" / "analyzed"
            dst_folder, updated_task_ids = _move_note_folder_and_rewrite_sources(
                tasks_dir=tasks_dir,
                folder_path=folder_path,
                dst_dir=analyzed_dir,
                new_note_content=content,
                produced_hint=note.get("produced"),
                legacy_info=legacy_info,
            )

            updated = parse_note_folder(dst_folder, tasks_dir, in_analyzed=True)
            _emit_event(
                tasks_dir,
                "note.processed",
                {
                    "id": updated["id"],
                    "status": "discarded",
                    "reason": reason.strip(),
                },
                subject=updated["id"],
            )
            return True, {
                "ok": True,
                "id": updated["id"],
                "status": "discarded",
                "reason": reason.strip(),
                "folder": dst_folder.name,
                "rel_path": updated["rel_path"],
                "sources_updated": updated_task_ids,
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def inbox_reopen(
    tasks_dir: pathlib.Path,
    target: str,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    try:
        with task_write_lock(tasks_dir):
            note = find_inbox_note(tasks_dir, target)
            if not note:
                return False, {"ok": False, "error": f"Inbox note {target!r} not found."}

            if not note["in_analyzed"]:
                return False, {"ok": False, "error": f"Note {note['id']} is not in analyzed/ (already open)."}

            folder_path = pathlib.Path(note["folder_path"])

            content = format_note_content(
                id=note["id"],
                title=note["title"],
                kind=note["kind"],
                status="ready",
                created=note["created"],
                author=note["author"],
                about=note["about"],
                produced=note["produced"],
                processed_by=note["processed_by"],
                body=note["body"],
            )

            to_analyze_dir = tasks_dir / "_inbox" / "to-analyze"
            dst_folder, updated_task_ids = _move_note_folder_and_rewrite_sources(
                tasks_dir=tasks_dir,
                folder_path=folder_path,
                dst_dir=to_analyze_dir,
                new_note_content=content,
                produced_hint=note.get("produced"),
            )

            updated = parse_note_folder(dst_folder, tasks_dir, in_analyzed=False)
            _emit_event(
                tasks_dir,
                "note.ready",
                {
                    "id": updated["id"],
                    "status": "ready",
                },
                subject=updated["id"],
            )
            return True, {
                "ok": True,
                "id": updated["id"],
                "status": "ready",
                "folder": dst_folder.name,
                "rel_path": updated["rel_path"],
                "sources_updated": updated_task_ids,
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def _update_index_task_path(tasks_dir: pathlib.Path, old_rel: str, new_rel: str) -> None:
    index_path = tasks_dir / "00-INDEX.md"
    if not index_path.is_file():
        return
    try:
        content = index_path.read_text(encoding="utf-8")
        if old_rel in content:
            new_content = content.replace(f"({old_rel})", f"({new_rel})").replace(f"tasks/{old_rel}", f"tasks/{new_rel}")
            if new_content != content:
                _atomic_write_text(index_path, new_content, encoding="utf-8")
    except Exception:
        pass


def _rewrite_attachment_references_to_local(text: str) -> str:
    pat = re.compile(r"(?:tasks/)?_inbox/(?:to-analyze|analyzed)/[^/\s\)\"\']+/attachments/([^\s\)\"\']+)")
    return pat.sub(r"attachments/\1", text)


def tasks_new_from_note(
    tasks_dir: pathlib.Path,
    from_note: str | None,
    category: str | None,
    title: str,
    priority: str = "P2",
    priority_reason: str | None = None,
    executor: str = "kilo",
    next_up: str = "no",
    depends_on: str = "-",
    decider: str = "-",
    goal: str | None = None,
    sources: str | None = None,
    paths: str | None = None,
    parent: str | None = None,
    short: str | None = None,
    steps: list[str] | None = None,
    verifications: list[str] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Create an emergent task `T###`, from an inbox note (`from_note`) or standalone
    (then `goal` and `priority_reason` are required), or as a child under `parent`."""
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    if short and short.strip() and short.strip() != "-":
        issues = validate_short_title(short.strip())
        if issues:
            return False, {"ok": False, "error": f"Invalid short title {short!r}: {'; '.join(issues)}."}

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    from_note = (from_note or "").strip()
    category = (category or "").strip()
    parent = (parent or "").strip() if parent else None

    if parent:
        with task_write_lock(tasks_dir):
            tree = discover_task_tree(tasks_dir)
            if parent not in tree:
                return False, {"ok": False, "error": f"Parent node {parent!r} not found."}
            p_node = tree[parent]
            if p_node.is_leaf and p_node.canonical_state != "open":
                return False, {
                    "ok": False,
                    "error": f"Cannot add child to in-flight leaf '{parent}' in state '{p_node.state}'. Leaf must be in state 'open'.",
                }
            note = None
            if from_note:
                note = find_inbox_note(tasks_dir, from_note)
                if not note:
                    return False, {"ok": False, "error": f"Inbox note {from_note!r} not found."}

            kind = note.get("kind", "feature") if note else "feature"
            if kind not in VALID_KINDS:
                kind = "feature"
            t_title = title.strip() if title and title.strip() else (note.get("title") if note else "")
            if not t_title:
                return False, {"ok": False, "error": "Missing required --title."}

            if goal and goal.strip():
                g_text = goal.strip()
            elif note:
                body = note.get("body", "").strip()
                paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
                g_text = paragraphs[0] if paragraphs else f"Goal derived from inbox note {from_note}."
            else:
                g_text = t_title

            new_id = allocate_child_id(tree, parent, tasks_dir)
            parent_file = pathlib.Path(p_node.file_path)
            slug = slugify(p_node.title)
            short_val = short.strip() if short and short.strip() and short.strip() != "-" else derive_short_title(t_title)
            child_block = f"\n### {new_id} - {t_title}\n\n- **Status:** `open` · **Short:** {short_val} · **Kind:** {kind}\n- **Goal:** {g_text}\n"

            if p_node.is_leaf:
                if p_node.block_text is not None:
                    parent_dir = parent_file.parent
                    new_folder = parent_dir / f"{parent}-{slug}"
                    new_readme = new_folder / "README.md"

                    old_text = parent_file.read_text(encoding="utf-8")
                    block_lines = p_node.block_text.splitlines()
                    filtered_lines = [bl for bl in block_lines if not re.match(r"^\s*[-*]\s+\*\*(Status|State):\*\*", bl)]
                    body_content = "\n".join(filtered_lines[1:]).strip()

                    rel_folder_link = f"{parent}-{slug}/"
                    rel_readme_link = f"{parent}-{slug}/README.md"
                    expanded_block = f"### {parent} - {p_node.title}\n\n- **Expanded:** [{rel_folder_link}]({rel_readme_link})\n"
                    new_parent_text = old_text.replace(p_node.block_text, expanded_block, 1)
                    _atomic_write_text(parent_file, new_parent_text)

                    readme_lines = [f"# {parent} - {p_node.title}", ""]
                    if body_content:
                        readme_lines.append(body_content)
                        readme_lines.append("")
                    readme_lines.extend([
                        "## Subtasks",
                        "",
                        f"### {new_id} - {t_title}",
                        "",
                        f"- **Status:** `open` · **Short:** {short_val} · **Kind:** {kind}",
                        f"- **Goal:** {g_text}",
                        "",
                    ])
                    new_folder.mkdir(parents=True, exist_ok=True)
                    _atomic_write_text(new_readme, "\n".join(readme_lines))
                    target_file = new_readme
                else:
                    if not p_node.is_folder:
                        parent_dir = parent_file.parent
                        new_folder = parent_dir / f"{parent}-{slug}"
                        new_readme = new_folder / "README.md"
                        old_text = parent_file.read_text(encoding="utf-8")
                        new_readme_text = old_text.rstrip() + f"\n\n## Subtasks\n{child_block}"
                        new_folder.mkdir(parents=True, exist_ok=True)
                        _atomic_write_text(new_readme, new_readme_text)
                        parent_file.unlink()
                        target_file = new_readme
                    else:
                        old_text = parent_file.read_text(encoding="utf-8")
                        if re.search(r"^##\s+Subtasks\b", old_text, re.MULTILINE):
                            closed_m = re.search(r"^##\s+Closed\b", old_text, re.MULTILINE)
                            if closed_m:
                                new_text = old_text[:closed_m.start()] + child_block.lstrip() + "\n" + old_text[closed_m.start():]
                            else:
                                new_text = old_text.rstrip() + "\n" + child_block
                        else:
                            closed_m = re.search(r"^##\s+Closed\b", old_text, re.MULTILINE)
                            if closed_m:
                                new_text = old_text[:closed_m.start()] + "## Subtasks\n" + child_block + "\n" + old_text[closed_m.start():]
                            else:
                                new_text = old_text.rstrip() + "\n\n## Subtasks\n" + child_block
                        _atomic_write_text(parent_file, new_text)
                        target_file = parent_file
            else:
                old_text = parent_file.read_text(encoding="utf-8")
                if parent_file.name == "README.md" and not re.search(r"^##\s+Subtasks\b", old_text, re.MULTILINE):
                    closed_m = re.search(r"^##\s+Closed\b", old_text, re.MULTILINE)
                    if closed_m:
                        new_text = old_text[:closed_m.start()] + "## Subtasks\n" + child_block + "\n" + old_text[closed_m.start():]
                    else:
                        new_text = old_text.rstrip() + "\n\n## Subtasks\n" + child_block
                else:
                    closed_m = re.search(r"^##\s+Closed\b", old_text, re.MULTILINE)
                    if closed_m:
                        new_text = old_text[:closed_m.start()] + child_block.lstrip() + "\n" + old_text[closed_m.start():]
                    else:
                        new_text = old_text.rstrip() + "\n" + child_block
                _atomic_write_text(parent_file, new_text)
                target_file = parent_file

            rel_path = target_file.relative_to(tasks_dir).as_posix()
            return True, {
                "ok": True,
                "id": new_id,
                "parent": parent,
                "file_path": str(target_file),
                "rel_path": rel_path,
                "sources": note["rel_path"] if note else (sources or "-"),
                "paths": paths or "-",
            }
    if from_note and not category:
        note_for_hint = find_inbox_note(tasks_dir, from_note)
        if note_for_hint:
            nk = note_for_hint.get("kind", "")
            if nk == "bug":
                category = "bugfix"
            elif nk in ("feature", "request"):
                category = "feature"

    if not from_note:
        if not goal or not goal.strip():
            return False, {"ok": False, "error": "Without --from-note, --goal is required."}
        if not priority_reason or not priority_reason.strip():
            return False, {"ok": False, "error": "Without --from-note, --priority-reason is required."}
    if not category:
        return False, {"ok": False, "error": "Missing required --category."}
    if not title or not title.strip():
        return False, {"ok": False, "error": "Missing required --title."}

    category = category.strip()
    if category in RESERVED_DIRS or category.startswith(".") or category.startswith("_"):
        return False, {"ok": False, "error": f"Invalid category name {category!r} (cannot be reserved directory)."}

    if priority not in PRIORITIES:
        return False, {"ok": False, "error": f"Invalid priority {priority!r} (expected one of {sorted(PRIORITIES)})."}

    if next_up not in NEXT_UP_VALUES:
        return False, {"ok": False, "error": f"Invalid next-up {next_up!r} (expected 'yes' or 'no')."}

    try:
        with task_write_lock(tasks_dir):
            note = None
            if from_note:
                note = find_inbox_note(tasks_dir, from_note)
                if not note:
                    return False, {"ok": False, "error": f"Inbox note {from_note!r} not found."}

            emergent = discover_emergent_tasks(tasks_dir)
            existing_nums = []
            for t in emergent:
                tid = t.get("id", "")
                if tid and EMERGENT_ID_RE.match(tid):
                    existing_nums.append(int(tid[1:]))

            next_num = max(existing_nums, default=0) + 1

            category_dir = tasks_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)

            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50].rstrip("-") or "task"

            fd = None
            t_id = ""
            filename = ""
            task_file_path = None

            note_attachments: list[pathlib.Path] = []
            if note and not note.get("legacy"):
                note_folder = pathlib.Path(note["folder_path"])
                att_dir = note_folder / "attachments"
                if att_dir.is_dir():
                    note_attachments = [
                        f for f in sorted(att_dir.iterdir())
                        if f.is_file() and not f.name.startswith(".")
                    ]

            task_folder: pathlib.Path | None = None
            if note_attachments:
                while True:
                    t_id = f"T{next_num:03d}"
                    folder_name = f"{t_id}-{slug}"
                    task_folder = category_dir / folder_name
                    if task_folder.exists():
                        next_num += 1
                        continue
                    try:
                        task_folder.mkdir(parents=True, exist_ok=False)
                    except FileExistsError:
                        next_num += 1
                        continue

                    task_att_dir = task_folder / "attachments"
                    task_att_dir.mkdir(parents=True, exist_ok=True)
                    for naf in note_attachments:
                        shutil.copy2(naf, task_att_dir / naf.name)

                    task_file_path = task_folder / "README.md"
                    try:
                        fd = os.open(str(task_file_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                        filename = f"{folder_name}/README.md"
                        break
                    except FileExistsError:
                        shutil.rmtree(task_folder, ignore_errors=True)
                        next_num += 1
            else:
                while True:
                    t_id = f"T{next_num:03d}"
                    filename = f"{t_id}-{slug}.md"
                    task_file_path = category_dir / filename
                    try:
                        fd = os.open(str(task_file_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                        break
                    except FileExistsError:
                        next_num += 1

            handoff = f"Read tasks/{category}/{filename}, do the open steps, run the Verification, update the task and the registry."
            if note:
                p_reason = (
                    priority_reason.strip()
                    if priority_reason and priority_reason.strip()
                    else f"Derived from inbox note {note['id'] if note['id'] != '-' else from_note}"
                )
                sources = note["rel_path"]
                paths = note["about"].strip() if note["about"] and note["about"].strip() != "-" else "-"
                body = note.get("body", "").strip()
                paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
                if not (goal and goal.strip()):
                    goal = paragraphs[0] if paragraphs else f"Goal derived from inbox note {from_note}."
            else:
                p_reason = priority_reason.strip()
                sources = (sources or "").strip() or "-"
                paths = (paths or "").strip() or "-"
            goal = _rewrite_attachment_references_to_local(goal.strip())

            short_val = short.strip() if short and short.strip() and short.strip() != "-" else derive_short_title(title.strip())

            if steps:
                steps_formatted = []
                for s in steps:
                    s_str = s.strip()
                    if not s_str:
                        continue
                    if re.match(r"^[-*]\s+\[[ xX]\]\s+", s_str):
                        steps_formatted.append(s_str)
                    elif re.match(r"^\[[ xX]\]\s+", s_str):
                        steps_formatted.append(f"- {s_str}")
                    else:
                        steps_formatted.append(f"- [ ] {s_str}")
                steps_block = "\n".join(steps_formatted) if steps_formatted else "- [ ] Step 1"
            else:
                steps_block = "- [ ] Step 1"

            if verifications:
                verifs_formatted = []
                for v in verifications:
                    v_str = v.strip()
                    if not v_str:
                        continue
                    if re.match(r"^[-*]\s+", v_str):
                        verifs_formatted.append(v_str)
                    else:
                        verifs_formatted.append(f"- {v_str}")
                verifs_block = "\n".join(verifs_formatted) if verifs_formatted else "- Command or check that proves completion"
            else:
                verifs_block = "- Command or check that proves completion"

            task_content = f"""# {t_id} {title.strip()}

- id: {t_id}
- title: {title.strip()}
- category: {category}
- priority: {priority}
- priority-reason: {p_reason}
- next-up: {next_up}
- state: open
- executor: {executor.strip() or 'kilo'}
- depends-on: {depends_on.strip() or '-'}
- decider: {decider.strip() or '-'}
- sources: {sources}
- paths: {paths}
- handoff: {handoff}
- short: {short_val}

## Goal

{goal}

## Steps

{steps_block}

## Verification

{verifs_block}
"""
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(task_content)
            except BaseException:
                if note_attachments and task_folder and task_folder.exists():
                    shutil.rmtree(task_folder, ignore_errors=True)
                elif task_file_path and task_file_path.exists():
                    task_file_path.unlink()
                raise

            rel_task = task_file_path.relative_to(tasks_dir).as_posix()

            errors, warnings, _, _ = validate_tasks_tree(tasks_dir)
            task_errors = [e for e in errors if rel_task in e]
            if task_errors:
                try:
                    if note_attachments and task_folder:
                        shutil.rmtree(task_folder, ignore_errors=True)
                    elif task_file_path:
                        task_file_path.unlink()
                except OSError:
                    pass
                return False, {"ok": False, "error": f"Created task failed validation: {'; '.join(task_errors)}"}

            _emit_event(
                tasks_dir,
                "task.created",
                {
                    "title": title,
                    "category": category,
                    "state": "open",
                    "from": None,
                    "to": "open",
                    "actor": executor or "owner",
                    "sources": sources,
                    "paths": paths,
                },
                subject=t_id,
                actor=executor or "owner",
            )

            return True, {
                "ok": True,
                "id": t_id,
                "file_path": str(task_file_path),
                "rel_path": rel_task,
                "sources": sources,
                "paths": paths,
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


create_new_task = tasks_new_from_note


def tasks_micro(
    tasks_dir: pathlib.Path,
    title: str,
    kind: str = "chore",
    priority: str = "P2",
    paths: str = "-",
    depends_on: str = "-",
    labels: list[str] | str | None = None,
    size: str | None = None,
    executor: str = "kilo",
    what: str | None = None,
    short: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    if short and short.strip() and short.strip() != "-":
        issues = validate_short_title(short.strip())
        if issues:
            return False, {"ok": False, "error": f"Invalid short title {short!r}: {'; '.join(issues)}."}

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if not title or not title.strip():
        return False, {"ok": False, "error": "Title must be a non-empty string."}

    kind_clean = (kind or "chore").strip().lower()
    if kind_clean not in VALID_KINDS:
        return False, {
            "ok": False,
            "error": f"Invalid kind {kind!r} (expected one of {sorted(VALID_KINDS)}).",
        }

    prio_clean = (priority or "P2").strip()
    if prio_clean not in PRIORITIES:
        return False, {
            "ok": False,
            "error": f"Invalid priority {priority!r} (expected one of {sorted(PRIORITIES)}).",
        }

    size_clean = (size.strip().upper() if size and size.strip() and size.strip() != "-" else None)
    if size_clean is not None and size_clean not in VALID_SIZES:
        return False, {
            "ok": False,
            "error": f"Invalid size {size!r} (expected one of {sorted(VALID_SIZES)}).",
        }

    clean_labels = _clean_labels_arg(labels)
    for lbl in clean_labels:
        if not LABEL_RE.match(lbl):
            return False, {
                "ok": False,
                "error": f"Invalid label {lbl!r} (must match '^[a-z0-9][a-z0-9-]{{0,23}}$').",
            }

    try:
        with task_write_lock(tasks_dir):
            micro_dir = tasks_dir / "micro"
            micro_dir.mkdir(parents=True, exist_ok=True)
            readme_path = micro_dir / "README.md"
            if not readme_path.exists():
                _atomic_write_text(readme_path, "# micro\n\nMicrotasks: small bugs, fixes, chores and docs touch-ups.\n")

            tree = discover_task_tree(tasks_dir)
            emergent = discover_emergent_tasks(tasks_dir)
            all_tids: set[str] = set(tree.keys()) | {t["id"] for t in emergent}

            existing_nums: list[int] = []
            for tid in all_tids:
                if tid.startswith("T"):
                    m_num = re.match(r"^T(\d+)", tid)
                    if m_num:
                        existing_nums.append(int(m_num.group(1)))

            next_num = max(existing_nums, default=0) + 1
            slug = slugify(title.strip())

            while True:
                t_id = f"T{next_num:03d}"
                filename = f"{t_id}-{slug}.md"
                task_file_path = micro_dir / filename
                try:
                    fd = os.open(str(task_file_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    break
                except FileExistsError:
                    next_num += 1

            # Build microtask header in exact closed order:
            # id, title, kind, priority, state, executor, paths, depends-on, size, labels
            hdr_lines = [
                f"# {t_id} {title.strip()}",
                "",
                f"- id: {t_id}",
                f"- title: {title.strip()}",
                f"- kind: {kind_clean}",
                f"- priority: {prio_clean}",
                f"- state: open",
                f"- executor: {executor.strip() or 'kilo'}",
                f"- paths: {paths.strip() or '-'}",
                f"- depends-on: {depends_on.strip() or '-'}",
            ]
            if size_clean is not None:
                hdr_lines.append(f"- size: {size_clean}")
            if clean_labels:
                hdr_lines.append(f"- labels: {', '.join(clean_labels)}")
            short_val = short.strip() if short and short.strip() and short.strip() != "-" else derive_short_title(title.strip())
            hdr_lines.append(f"- short: {short_val}")

            what_body = (what.strip() if what and what.strip() else f"What to change for {title.strip()}.")
            content = "\n".join(hdr_lines) + f"\n\n## What\n\n{what_body}\n"

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
            except BaseException:
                if task_file_path.exists():
                    task_file_path.unlink()
                raise

            rel_task = task_file_path.relative_to(tasks_dir).as_posix()
            errors, warnings, _, _ = validate_tasks_tree(tasks_dir)
            task_errors = [e for e in errors if rel_task in e]
            if task_errors:
                try:
                    task_file_path.unlink()
                except OSError:
                    pass
                return False, {"ok": False, "error": f"Created microtask failed validation: {'; '.join(task_errors)}"}

            _emit_event(
                tasks_dir,
                "task.created",
                {
                    "title": title.strip(),
                    "kind": kind_clean,
                    "priority": prio_clean,
                    "state": "open",
                    "from": None,
                    "to": "open",
                    "actor": "owner",
                },
                subject=t_id,
                actor="owner",
            )

            return True, {
                "ok": True,
                "id": t_id,
                "title": title.strip(),
                "kind": kind_clean,
                "priority": prio_clean,
                "size": size_clean or "XS",
                "labels": clean_labels,
                "rel_path": rel_task,
                "file_path": str(task_file_path),
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def tasks_promote(
    tasks_dir: pathlib.Path,
    task_id: str,
    category: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    target_category = (category.strip() if category and category.strip() else "maintenance")
    if target_category in RESERVED_DIRS or target_category.startswith(".") or target_category.startswith("_") or target_category == "micro" or INITIATIVE_DIR_RE.match(target_category):
        return False, {"ok": False, "error": f"Invalid target category {target_category!r}."}

    try:
        with task_write_lock(tasks_dir):
            target_file: pathlib.Path | None = None
            in_done = False
            for parent_dir, is_d in ((tasks_dir / "micro", False), (tasks_dir / "done" / "micro", True)):
                if parent_dir.is_dir():
                    for f in parent_dir.glob("*.md"):
                        if f.name.startswith(f"{task_id}-") and f.name != "README.md":
                            target_file = f
                            in_done = is_d
                            break
                if target_file:
                    break

            if not target_file:
                return False, {"ok": False, "error": f"Microtask {task_id!r} not found in tasks/micro/."}

            parsed = parse_emergent_task_file(target_file, tasks_dir, in_done=in_done)
            headers = dict(parsed.get("headers", {}))
            title = parsed["title"]
            slug = slugify(title)

            dest_dir = (tasks_dir / "done" / target_category) if in_done else (tasks_dir / target_category)
            dest_dir.mkdir(parents=True, exist_ok=True)
            readme_path = dest_dir / "README.md"
            if not readme_path.exists():
                _atomic_write_text(readme_path, f"# {target_category}\n\nTasks in category {target_category}.\n")

            new_filename = f"{task_id}-{slug}.md"
            dest_file = dest_dir / new_filename
            handoff = f"Read tasks/{target_category}/{new_filename}, do the open steps, run the Verification, update the task and the registry."

            hdr_lines = [
                f"# {task_id} {title}",
                "",
                f"- id: {task_id}",
                f"- title: {title}",
                f"- category: {target_category}",
                f"- priority: {headers.get('priority', 'P2')}",
                f"- priority-reason: {headers.get('priority-reason') or f'Promoted from microtask {task_id}'}",
                f"- next-up: {headers.get('next-up', 'no')}",
                f"- state: {parsed['state'] or 'open'}",
                f"- executor: {headers.get('executor', 'kilo')}",
                f"- depends-on: {headers.get('depends-on', '-')}",
                f"- decider: {headers.get('decider', '-')}",
                f"- sources: {headers.get('sources') or f'Promoted from microtask {task_id}'}",
                f"- paths: {headers.get('paths', '-')}",
                f"- handoff: {handoff}",
            ]
            if "size" in headers and headers["size"] and headers["size"] != "-":
                hdr_lines.append(f"- size: {headers['size']}")
            if "kind" in headers and headers["kind"] and headers["kind"] != "-":
                hdr_lines.append(f"- kind: {headers['kind']}")
            if "labels" in headers and headers["labels"] and headers["labels"] != "-":
                hdr_lines.append(f"- labels: {headers['labels']}")

            body_content = parsed.get("what_body") or f"Goal for {title}."
            full_content = "\n".join(hdr_lines) + f"\n\n## Goal\n\n{body_content}\n\n## Steps\n\n- [ ] Implement task steps.\n\n## Verification\n\n- [ ] Verify task implementation.\n"

            _atomic_write_text(dest_file, full_content, encoding="utf-8")
            old_rel = target_file.relative_to(tasks_dir).as_posix()
            new_rel = dest_file.relative_to(tasks_dir).as_posix()
            target_file.unlink()

            errors, warnings, _, _ = validate_tasks_tree(tasks_dir)
            task_errors = [e for e in errors if new_rel in e]
            if task_errors:
                dest_file.unlink()
                return False, {"ok": False, "error": f"Promoted task failed validation: {'; '.join(task_errors)}"}

            _emit_event(
                tasks_dir,
                "task.created",
                {
                    "task_id": task_id,
                    "category": target_category,
                    "state": parsed["state"] or "open",
                    "from": old_state if "old_state" in locals() else "open",
                    "to": "open",
                    "actor": "owner",
                    "promoted_from": old_rel,
                },
                subject=task_id,
                actor="owner",
            )

            return True, {
                "ok": True,
                "id": task_id,
                "category": target_category,
                "old_rel_path": old_rel,
                "rel_path": new_rel,
                "file_path": str(dest_file),
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def tasks_attach(
    tasks_dir: pathlib.Path,
    target: str,
    file_path: str | pathlib.Path,
    name: str | None = None,
    expect_task_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    target_clean = (target or "").strip()
    if re.match(r"^\d{2,}(?:\.\d+[a-z]?)*$", target_clean):
        return False, {
            "ok": False,
            "error": "plan-task-attachments-unsupported",
            "message": f"Plan tasks ({target_clean}) do not support attachments; only emergent tasks (T###) can have attachments.",
        }
    if not EMERGENT_ID_RE.match(target_clean):
        return False, {
            "ok": False,
            "error": "invalid-task-id",
            "message": f"Invalid emergent task ID {target_clean!r} (expected format T###).",
        }

    if name:
        if "/" in name or "\\" in name or "\x00" in name or ".." in name:
            return False, {
                "ok": False,
                "error": "invalid-attachment-name",
                "message": f"Invalid attachment name: path traversal or invalid characters in {name!r}",
            }

    src = pathlib.Path(file_path).resolve()
    if not src.is_file():
        return False, {"ok": False, "error": f"Attachment file not found: {file_path}"}

    data = src.read_bytes()
    ok_att, att_class, real_ext, err_code, err_msg = validate_and_classify_attachment(data, src.suffix)
    if not ok_att:
        return False, {
            "ok": False,
            "error": err_code,
            "message": err_msg,
        }

    try:
        with task_write_lock(tasks_dir):
            all_emergent = discover_emergent_tasks(tasks_dir)
            task = next((t for t in all_emergent if t.get("id") == target_clean), None)
            if not task:
                tree = discover_task_tree(tasks_dir)
                if target_clean in tree:
                    return False, {
                        "ok": False,
                        "error": "plan-task-attachments-unsupported",
                        "message": f"Plan tasks ({target_clean}) do not support attachments; only emergent tasks (T###) can have attachments.",
                    }
                return False, {"ok": False, "error": f"Task {target_clean!r} not found."}

            if expect_task_hash:
                actual_hash = task["bundle_sha256"]
                if actual_hash != expect_task_hash:
                    return False, {
                        "ok": False,
                        "error": "stale-task-hash",
                        "message": f"Task bundle hash mismatch: expected {expect_task_hash}, actual {actual_hash}",
                        "expected": expect_task_hash,
                        "actual": actual_hash,
                    }

            is_folder = task["is_folder"]
            if not is_folder:
                # Convert single-file task to folder form byte-identically
                single_file = pathlib.Path(task["file_path"])
                task_folder = single_file.parent / single_file.stem
                task_folder.mkdir(parents=True, exist_ok=True)
                readme_file = task_folder / "README.md"
                content_bytes = single_file.read_bytes()
                readme_file.write_bytes(content_bytes)
                single_file.unlink()
                _update_index_task_path(
                    tasks_dir,
                    old_rel=task["rel_path"],
                    new_rel=readme_file.relative_to(tasks_dir).as_posix(),
                )
            else:
                task_folder = pathlib.Path(task["task_root"])
                readme_file = task_folder / "README.md"

            attachments_dir = task_folder / "attachments"
            attachments_dir.mkdir(parents=True, exist_ok=True)

            existing_files = [f.name for f in attachments_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
            if len(existing_files) >= MAX_ATTACHMENTS_PER_TASK:
                return False, {
                    "ok": False,
                    "error": "attachment-limit-reached",
                    "message": f"Task {task['id']} already has the maximum allowed attachments ({MAX_ATTACHMENTS_PER_TASK}).",
                }

            existing_nums = [
                int(m.group(1)) for f in existing_files if (m := re.match(r"^(\d{2})-", f))
            ]
            next_idx = max(existing_nums, default=0) + 1

            stem = name if name else src.stem
            dest_filename = sanitize_attachment_name(stem, real_ext, next_idx)
            dest_path = attachments_dir / dest_filename

            shutil.copy2(src, dest_path)

            if att_class == "image":
                markdown_ref = f"![](attachments/{dest_filename})"
            else:
                markdown_ref = f"[{dest_filename}](attachments/{dest_filename})"

            updated = parse_emergent_task_file(readme_file, tasks_dir, in_done=task["in_done"])

            _emit_event(
                tasks_dir,
                "task.attached",
                {
                    "name": dest_filename,
                    "class": att_class,
                    "path": str(dest_path),
                },
                subject=updated["id"],
            )

            return True, {
                "ok": True,
                "id": updated["id"],
                "attachment": dest_filename,
                "class": att_class,
                "markdown": markdown_ref,
                "path": str(dest_path),
                "bundle_sha256": updated["bundle_sha256"],
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def tasks_detach(
    tasks_dir: pathlib.Path,
    target: str,
    name: str,
    expect_task_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    target_clean = (target or "").strip()
    if re.match(r"^\d{2,}(?:\.\d+[a-z]?)*$", target_clean):
        return False, {
            "ok": False,
            "error": "plan-task-attachments-unsupported",
            "message": f"Plan tasks ({target_clean}) do not support attachments; only emergent tasks (T###) can have attachments.",
        }
    if not EMERGENT_ID_RE.match(target_clean):
        return False, {
            "ok": False,
            "error": "invalid-task-id",
            "message": f"Invalid emergent task ID {target_clean!r} (expected format T###).",
        }

    if not name or "/" in name or "\\" in name or "\x00" in name or ".." in name:
        return False, {
            "ok": False,
            "error": "invalid-attachment",
            "message": f"Invalid attachment name: {name!r}",
        }

    try:
        with task_write_lock(tasks_dir):
            all_emergent = discover_emergent_tasks(tasks_dir)
            task = next((t for t in all_emergent if t.get("id") == target_clean), None)
            if not task:
                tree = discover_task_tree(tasks_dir)
                if target_clean in tree:
                    return False, {
                        "ok": False,
                        "error": "plan-task-attachments-unsupported",
                        "message": f"Plan tasks ({target_clean}) do not support attachments; only emergent tasks (T###) can have attachments.",
                    }
                return False, {"ok": False, "error": f"Task {target_clean!r} not found."}

            if expect_task_hash:
                actual_hash = task["bundle_sha256"]
                if actual_hash != expect_task_hash:
                    return False, {
                        "ok": False,
                        "error": "stale-task-hash",
                        "message": f"Task bundle hash mismatch: expected {expect_task_hash}, actual {actual_hash}",
                        "expected": expect_task_hash,
                        "actual": actual_hash,
                    }

            if not task["is_folder"]:
                return False, {
                    "ok": False,
                    "error": "no-attachments",
                    "message": f"Task {target_clean} is a single-file task and has no attachments.",
                }

            task_folder = pathlib.Path(task["task_root"])
            attachments_dir = task_folder / "attachments"
            if not attachments_dir.is_dir():
                return False, {
                    "ok": False,
                    "error": "no-attachments",
                    "message": f"Task {target_clean} has no attachments directory.",
                }

            try:
                target_file = validate_attachment_name(name, attachments_dir)
            except (ValueError, FileNotFoundError) as ve:
                return False, {"ok": False, "error": "invalid-attachment", "message": str(ve)}

            target_file.unlink()
            readme_file = task_folder / "README.md"
            updated = parse_emergent_task_file(readme_file, tasks_dir, in_done=task["in_done"])

            _emit_event(
                tasks_dir,
                "task.detached",
                {
                    "name": name,
                },
                subject=updated["id"],
            )

            return True, {
                "ok": True,
                "id": updated["id"],
                "detached": name,
                "bundle_sha256": updated["bundle_sha256"],
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def _parse_task_step_items(text: str) -> tuple[MarkdownSection | None, list[dict[str, Any]]]:
    """Parse checklist items in ## Steps of a markdown task file.
    Returns (steps_section, items_list) where items_list has dicts:
    {"index": 1-based int, "checked": bool, "text": str, "line_number": int, "line_idx": int}
    """
    sections = parse_markdown_sections(text, heading_prefix="## ")
    sec = next((s for s in sections if s.heading == "## Steps"), None)
    if not sec:
        return None, []
    items: list[dict[str, Any]] = []
    idx = 1
    for sline in sec.lines[1:]:
        if sline.is_fenced:
            continue
        m = STEP_ITEM_RE.match(sline.text)
        if m:
            checked = m.group(2).lower() == "x"
            step_text = m.group(3).strip()
            items.append({
                "index": idx,
                "checked": checked,
                "text": step_text,
                "line_number": sline.line_number,
                "line_idx": sline.line_number - 1,
            })
            idx += 1
    return sec, items


def tasks_step_list(tasks_dir: pathlib.Path, task_id: str) -> tuple[bool, dict[str, Any]]:
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    target_clean = (task_id or "").strip()
    if re.match(r"^t\d{3,}$", target_clean):
        target_clean = target_clean.upper()
    all_emergent = discover_emergent_tasks(tasks_dir)
    task = next((t for t in all_emergent if t.get("id") == target_clean), None)
    if not task:
        tree = discover_task_tree(tasks_dir)
        if target_clean in tree:
            return False, {"ok": False, "error": f"Plan task ({target_clean}) does not have a ## Steps section; only emergent tasks (T###) support step commands."}
        return False, {"ok": False, "error": f"Task {target_clean!r} not found in {tasks_dir}."}

    task_file = pathlib.Path(task["file_path"])
    try:
        content = task_file.read_text(encoding="utf-8")
    except OSError as e:
        return False, {"ok": False, "error": f"Failed to read task file {task_file}: {e}"}

    sec, items = _parse_task_step_items(content)
    if sec is None:
        return False, {"ok": False, "error": f"Task {target_clean!r} has no '## Steps' section."}

    clean_items = [{"index": it["index"], "checked": it["checked"], "text": it["text"]} for it in items]
    return True, {
        "ok": True,
        "task_id": target_clean,
        "steps": clean_items,
        "count": len(clean_items),
    }


def tasks_step_add(
    tasks_dir: pathlib.Path,
    task_id: str,
    text: str,
    expect_task_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }
    if not text or not text.strip():
        return False, {"ok": False, "error": "Step text cannot be empty."}

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    target_clean = (task_id or "").strip()
    if re.match(r"^t\d{3,}$", target_clean):
        target_clean = target_clean.upper()

    try:
        with task_write_lock(tasks_dir):
            all_emergent = discover_emergent_tasks(tasks_dir)
            task = next((t for t in all_emergent if t.get("id") == target_clean), None)
            if not task:
                tree = discover_task_tree(tasks_dir)
                if target_clean in tree:
                    return False, {"ok": False, "error": f"Plan task ({target_clean}) does not have a ## Steps section; only emergent tasks (T###) support step commands."}
                return False, {"ok": False, "error": f"Task {target_clean!r} not found in {tasks_dir}."}

            task_file = pathlib.Path(task["file_path"])
            if expect_task_hash:
                actual_hash = task_bundle_sha256(task_file)
                if actual_hash != expect_task_hash:
                    return False, {
                        "ok": False,
                        "error": "stale-task-hash",
                        "message": f"Task bundle hash mismatch: expected {expect_task_hash}, actual {actual_hash}",
                        "expected": expect_task_hash,
                        "actual": actual_hash,
                    }

            content = task_file.read_text(encoding="utf-8")
            sec, items = _parse_task_step_items(content)
            if sec is None:
                return False, {"ok": False, "error": f"Task {target_clean!r} has no '## Steps' section."}

            raw_s = text.strip()
            if re.match(r"^[-*]\s+\[\s*\]\s*", raw_s):
                clean_text = re.sub(r"^[-*]\s+\[\s*\]\s*", "", raw_s).strip()
                new_step_line = f"- [ ] {clean_text}"
            elif re.match(r"^[-*]\s+\[[xX]\]\s*", raw_s):
                clean_text = re.sub(r"^[-*]\s+\[[xX]\]\s*", "", raw_s).strip()
                new_step_line = f"- [x] {clean_text}"
            elif re.match(r"^\[\s*\]\s*", raw_s):
                clean_text = re.sub(r"^\[\s*\]\s*", "", raw_s).strip()
                new_step_line = f"- [ ] {clean_text}"
            elif re.match(r"^\[[xX]\]\s*", raw_s):
                clean_text = re.sub(r"^\[[xX]\]\s*", "", raw_s).strip()
                new_step_line = f"- [x] {clean_text}"
            else:
                clean_text = raw_s
                new_step_line = f"- [ ] {clean_text}"

            lines = content.splitlines(keepends=True)
            nl = "\r\n" if "\r\n" in content else "\n"

            # Check if replacing a solitary placeholder
            only_placeholder = (
                len(items) == 1
                and (
                    STEP_PLACEHOLDER_RE.match(lines[items[0]["line_idx"]])
                    or items[0]["text"].lower() in ("step 1", "todo: step 1", "implement task steps.", "implement task steps")
                )
            )

            if only_placeholder:
                target_idx = items[0]["line_idx"]
                orig_ending = nl
                if lines[target_idx].endswith("\r\n"):
                    orig_ending = "\r\n"
                elif lines[target_idx].endswith("\n"):
                    orig_ending = "\n"
                lines[target_idx] = new_step_line + orig_ending
            else:
                if items:
                    last_idx = items[-1]["line_idx"]
                    orig_ending = nl
                    if lines[last_idx].endswith("\r\n"):
                        orig_ending = "\r\n"
                    elif lines[last_idx].endswith("\n"):
                        orig_ending = "\n"
                    lines.insert(last_idx + 1, new_step_line + orig_ending)
                else:
                    head_idx = sec.lines[0].line_number - 1
                    insert_at = head_idx + 1
                    if insert_at < len(lines) and lines[insert_at].strip() == "":
                        insert_at += 1
                    else:
                        lines.insert(insert_at, nl)
                        insert_at += 1
                    lines.insert(insert_at, new_step_line + nl)

            new_content = "".join(lines)
            _atomic_write_text(task_file, new_content, encoding="utf-8")

            _, updated_items = _parse_task_step_items(new_content)
            clean_updated = [{"index": it["index"], "checked": it["checked"], "text": it["text"]} for it in updated_items]
            added_it = next((it for it in clean_updated if it["text"] == clean_text), clean_updated[-1] if clean_updated else None)
            new_hash = task_bundle_sha256(task_file)

            _emit_event(
                tasks_dir,
                "task.updated",
                {
                    "field": "steps",
                    "action": "add",
                    "text": clean_text,
                    "index": added_it["index"] if added_it else len(clean_updated),
                },
                subject=target_clean,
                actor="owner",
            )

            return True, {
                "ok": True,
                "task_id": target_clean,
                "step": added_it,
                "steps": clean_updated,
                "task_hash": new_hash,
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def _toggle_task_step(
    tasks_dir: pathlib.Path,
    task_id: str,
    target: str,
    check: bool,
    expect_task_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }
    target_str = str(target).strip()
    if not target_str:
        return False, {"ok": False, "error": "Target step index or substring is required."}

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    target_clean = (task_id or "").strip()
    if re.match(r"^t\d{3,}$", target_clean):
        target_clean = target_clean.upper()

    try:
        with task_write_lock(tasks_dir):
            all_emergent = discover_emergent_tasks(tasks_dir)
            task = next((t for t in all_emergent if t.get("id") == target_clean), None)
            if not task:
                tree = discover_task_tree(tasks_dir)
                if target_clean in tree:
                    return False, {"ok": False, "error": f"Plan task ({target_clean}) does not have a ## Steps section; only emergent tasks (T###) support step commands."}
                return False, {"ok": False, "error": f"Task {target_clean!r} not found in {tasks_dir}."}

            task_file = pathlib.Path(task["file_path"])
            if expect_task_hash:
                actual_hash = task_bundle_sha256(task_file)
                if actual_hash != expect_task_hash:
                    return False, {
                        "ok": False,
                        "error": "stale-task-hash",
                        "message": f"Task bundle hash mismatch: expected {expect_task_hash}, actual {actual_hash}",
                        "expected": expect_task_hash,
                        "actual": actual_hash,
                    }

            content = task_file.read_text(encoding="utf-8")
            sec, items = _parse_task_step_items(content)
            if sec is None:
                return False, {"ok": False, "error": f"Task {target_clean!r} has no '## Steps' section."}
            if not items:
                return False, {"ok": False, "error": f"Task {target_clean} has no step checklist items."}

            try:
                t_idx = int(target_str)
                is_int = True
            except ValueError:
                is_int = False

            if is_int:
                if 1 <= t_idx <= len(items):
                    matched_item = items[t_idx - 1]
                else:
                    return False, {"ok": False, "error": f"Step index {t_idx} out of range (1..{len(items)})."}
            else:
                sub_lower = target_str.lower()
                matches = [it for it in items if sub_lower in it["text"].lower()]
                if len(matches) == 0:
                    return False, {"ok": False, "error": f"No step matching {target_str!r} found in task {target_clean}."}
                if len(matches) > 1:
                    matched_desc = ", ".join(f"#{m['index']} ({m['text']})" for m in matches)
                    return False, {
                        "ok": False,
                        "error": f"Multiple steps match {target_str!r} in task {target_clean} ({len(matches)} matches: {matched_desc}). Use index or more specific text.",
                    }
                matched_item = matches[0]

            lines = content.splitlines(keepends=True)
            line_idx = matched_item["line_idx"]
            old_line = lines[line_idx]

            if check:
                new_line = re.sub(r"^(\s*[-*]|\s*\d+\.)(\s+\[)[ ](\]\s*)", r"\g<1>\g<2>x\g<3>", old_line)
            else:
                new_line = re.sub(r"^(\s*[-*]|\s*\d+\.)(\s+\[)[xX](\]\s*)", r"\g<1>\g<2> \g<3>", old_line)

            lines[line_idx] = new_line
            new_content = "".join(lines)
            _atomic_write_text(task_file, new_content, encoding="utf-8")

            _, updated_items = _parse_task_step_items(new_content)
            clean_updated = [{"index": it["index"], "checked": it["checked"], "text": it["text"]} for it in updated_items]
            updated_it = clean_updated[matched_item["index"] - 1]
            new_hash = task_bundle_sha256(task_file)

            action_name = "check" if check else "uncheck"
            _emit_event(
                tasks_dir,
                "task.updated",
                {
                    "field": "steps",
                    "action": action_name,
                    "index": updated_it["index"],
                    "text": updated_it["text"],
                    "checked": updated_it["checked"],
                },
                subject=target_clean,
                actor="owner",
            )

            return True, {
                "ok": True,
                "task_id": target_clean,
                "step": updated_it,
                "steps": clean_updated,
                "task_hash": new_hash,
            }
    except Exception as e:
        return False, {"ok": False, "error": str(e)}


def tasks_step_check(
    tasks_dir: pathlib.Path,
    task_id: str,
    target: str,
    expect_task_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    return _toggle_task_step(tasks_dir, task_id, target, check=True, expect_task_hash=expect_task_hash)


def tasks_step_uncheck(
    tasks_dir: pathlib.Path,
    task_id: str,
    target: str,
    expect_task_hash: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    return _toggle_task_step(tasks_dir, task_id, target, check=False, expect_task_hash=expect_task_hash)


def cmd_tasks_step_list(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_step_list(tasks_dir, args.task_id)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            steps = res.get("steps", [])
            if not steps:
                print(f"No steps found for {res['task_id']}.")
            else:
                print(f"Step checklist for {res['task_id']} ({len(steps)} items):")
                for s in steps:
                    box = "[x]" if s["checked"] else "[ ]"
                    print(f"  {s['index']}. {box} {s['text']}")
        else:
            print(f"[FAIL] {res.get('error', 'tasks step list failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_tasks_step_add(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_step_add(
        tasks_dir=tasks_dir,
        task_id=args.task_id,
        text=args.text,
        expect_task_hash=getattr(args, "expect_task_hash", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            step = res.get("step") or {}
            print(f"[ok] Added step {step.get('index', '?')} to {res['task_id']}: {step.get('text', '')}")
        else:
            print(f"[FAIL] {res.get('error', 'tasks step add failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_tasks_step_check(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_step_check(
        tasks_dir=tasks_dir,
        task_id=args.task_id,
        target=args.target,
        expect_task_hash=getattr(args, "expect_task_hash", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            step = res.get("step") or {}
            print(f"[ok] Marked step {step.get('index', '?')} of {res['task_id']} as checked: {step.get('text', '')}")
        else:
            print(f"[FAIL] {res.get('error', 'tasks step check failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_tasks_step_uncheck(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_step_uncheck(
        tasks_dir=tasks_dir,
        task_id=args.task_id,
        target=args.target,
        expect_task_hash=getattr(args, "expect_task_hash", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            step = res.get("step") or {}
            print(f"[ok] Marked step {step.get('index', '?')} of {res['task_id']} as unchecked: {step.get('text', '')}")
        else:
            print(f"[FAIL] {res.get('error', 'tasks step uncheck failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_inbox_list(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    status = getattr(args, "status", "all")
    notes = discover_inbox_notes(tasks_dir)
    if status != "all":
        notes = [n for n in notes if n["status"] == status]

    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "notes": notes}, indent=2))
    else:
        print(f"[ok] Found {len(notes)} note(s) in {tasks_dir / '_inbox'}:")
        for n in notes:
            legacy_flag = " (legacy)" if n["legacy"] else ""
            att_info = f", attachments: {len(n['attachments'])}" if n["attachments"] else ""
            print(f"  - {n['id']} [{n['status']}] ({n['kind']}) {n['title']}{legacy_flag}{att_info}")
    return 0


def cmd_inbox_show(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    note = find_inbox_note(tasks_dir, args.note_id)
    if not note:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": f"Inbox note {args.note_id!r} not found."}, indent=2))
        else:
            print(f"[FAIL] Inbox note {args.note_id!r} not found.", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "note": note}, indent=2))
    else:
        print(f"Note: {note['id']} ({note['status']})")
        print(f"Title: {note['title']}")
        print(f"Kind: {note['kind']}")
        print(f"Created: {note['created']}")
        print(f"Author: {note['author']}")
        print(f"About: {note['about']}")
        print(f"Produced: {note['produced']}")
        print(f"Processed by: {note['processed_by']}")
        print(f"Bundle hash: {note['bundle_sha256']}")
        att_str = ", ".join((a["name"] if isinstance(a, dict) else a) for a in note["attachments"]) if note["attachments"] else "none"
        print(f"Attachments ({len(note['attachments'])}): {att_str}")
        print("\n--- Body ---")
        print(note["body"])
    return 0


def cmd_inbox_add(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = inbox_add(
        tasks_dir=tasks_dir,
        title=args.title,
        kind=args.kind,
        body=getattr(args, "body", None),
        body_file=getattr(args, "body_file", None),
        about=getattr(args, "about", "-"),
        author=getattr(args, "author", "owner"),
        status=getattr(args, "status", "draft"),
        short=getattr(args, "short", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Created note {res['id']}: {res['rel_path']}")
        else:
            print(f"[FAIL] {res.get('error', 'inbox add failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_inbox_edit(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = inbox_edit(
        tasks_dir=tasks_dir,
        target=args.note_id,
        title=getattr(args, "title", None),
        kind=getattr(args, "kind", None),
        body=getattr(args, "body", None),
        body_file=getattr(args, "body_file", None),
        about=getattr(args, "about", None),
        author=getattr(args, "author", None),
        status=getattr(args, "status", None),
        expect_hash=getattr(args, "expect_hash", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Updated note {res['id']}: status={res['status']}, hash={res['bundle_sha256']}")
        else:
            print(f"[FAIL] {res.get('error') or res.get('message', 'inbox edit failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_inbox_attach(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = inbox_attach(
        tasks_dir=tasks_dir,
        target=args.note_id,
        file_path=args.file,
        name=getattr(args, "name", None),
        expect_hash=getattr(args, "expect_hash", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Attached {res['attachment']}: {res['markdown']}")
        else:
            print(f"[FAIL] {res.get('error') or res.get('message', 'inbox attach failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_inbox_detach(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = inbox_detach(
        tasks_dir=tasks_dir,
        target=args.note_id,
        name=args.name,
        expect_hash=getattr(args, "expect_hash", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Detached {res['detached']} from note {res['id']}")
        else:
            print(f"[FAIL] {res.get('error') or res.get('message', 'inbox detach failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_tasks_attach(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_attach(
        tasks_dir=tasks_dir,
        target=args.task_id,
        file_path=args.file,
        name=getattr(args, "name", None),
        expect_task_hash=getattr(args, "expect_task_hash", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Attached {res['attachment']} to {res['id']}: {res['markdown']}")
        else:
            print(f"[FAIL] {res.get('error') or res.get('message', 'tasks attach failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_tasks_detach(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_detach(
        tasks_dir=tasks_dir,
        target=args.task_id,
        name=args.name,
        expect_task_hash=getattr(args, "expect_task_hash", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Detached {res['detached']} from {res['id']}")
        else:
            print(f"[FAIL] {res.get('error') or res.get('message', 'tasks detach failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_inbox_resolve(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = inbox_resolve(
        tasks_dir=tasks_dir,
        target=args.note_id,
        produced=args.produced,
        by=getattr(args, "by", "owner"),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Resolved note {res['id']} -> {res['folder']} (produced: {res['produced']})")
        else:
            print(f"[FAIL] {res.get('error', 'inbox resolve failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_inbox_discard(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = inbox_discard(
        tasks_dir=tasks_dir,
        target=args.note_id,
        reason=args.reason,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Discarded note {res['id']} -> {res['folder']}")
        else:
            print(f"[FAIL] {res.get('error', 'inbox discard failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_inbox_reopen(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = inbox_reopen(
        tasks_dir=tasks_dir,
        target=args.note_id,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Reopened note {res['id']} -> {res['folder']} (status: ready)")
        else:
            print(f"[FAIL] {res.get('error', 'inbox reopen failed')}", file=sys.stderr)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Feedback Channel (T034)
# ---------------------------------------------------------------------------

def _resolve_global_config_dir() -> pathlib.Path:
    try:
        import orchestration_broker_lock
        return orchestration_broker_lock.get_global_config_dir()
    except ImportError:
        pass
    try:
        repo_root = _find_repo_root()
        if repo_root is not None:
            sdir = repo_root / "scripts"
            if sdir.is_dir() and str(sdir) not in sys.path:
                sys.path.insert(0, str(sdir))
        import orchestration_broker_lock
        return orchestration_broker_lock.get_global_config_dir()
    except Exception:
        pass
    env_val = os.environ.get("AI_ORCHESTRATION_CONFIG")
    if env_val:
        p = pathlib.Path(env_val).expanduser().resolve()
        if p.is_file() or p.suffix == ".toml" or p.name.endswith(".toml"):
            return p.parent
        return p
    return pathlib.Path.home() / ".config" / "ai-orchestration"


def _resolve_feedback_author(explicit_author: str | None = None) -> tuple[str, str]:
    cwd = pathlib.Path.cwd().resolve()
    ws_slug = None
    ws_canonical = None
    try:
        reg = orchestration_registry
        if reg is None:
            repo_root = _find_repo_root()
            if repo_root is not None:
                sdir = repo_root / "scripts"
                if sdir.is_dir() and str(sdir) not in sys.path:
                    sys.path.insert(0, str(sdir))
            import orchestration_registry as reg
        if reg is not None and hasattr(reg, "resolve_workspace_for_path"):
            nearest_ws, _ = reg.resolve_workspace_for_path(cwd)
            if nearest_ws and nearest_ws.get("slug"):
                ws_slug = nearest_ws["slug"]
                ws_canonical = nearest_ws.get("canonical_path")
    except Exception:
        pass

    git_top = None
    try:
        cur = cwd
        for p in [cur, *cur.parents]:
            if (p / ".git").exists():
                git_top = p
                break
    except Exception:
        pass

    if explicit_author and explicit_author.strip():
        author = explicit_author.strip()
    elif ws_slug:
        author = ws_slug
    elif git_top:
        author = git_top.name
    else:
        author = cwd.name or "unknown"

    workspace_path = ws_canonical or (str(git_top) if git_top else str(cwd))
    return author, workspace_path


def _get_ai_orch_version_or_commit() -> str:
    repo_root = _find_repo_root()
    if repo_root is not None:
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return f"1.1.0 ({res.stdout.strip()})"
        except Exception:
            pass
    return "1.1.0"


def resolve_feedback_target(
    config_dir: pathlib.Path | None = None,
    for_flush: bool = False,
) -> tuple[str, pathlib.Path | None]:
    """Resolve the target tasks directory for feedback.

    Order of resolution:
      1. $AI_ORCH_FEEDBACK_TASKS_DIR
      2. [feedback] tasks_dir in global config (orchestration.toml)
      3. The tasks/ dir of the repository that contains the running bin/ai-orch,
         if that repository is ai-orchestration (it has tasks/00-INDEX.md and
         plugins/architect-side/skills/task-pipeline).
      4. Otherwise a local outbox <global config dir>/feedback-outbox/
         (or None if for_flush=True).

    Returns:
      (source, path) where source is 'env', 'config', 'repo', or 'outbox'.
    """
    # 1. Environment variable
    env_dir = os.environ.get("AI_ORCH_FEEDBACK_TASKS_DIR")
    if env_dir and env_dir.strip():
        return "env", pathlib.Path(env_dir.strip()).expanduser().resolve()

    # 2. Global config [feedback] tasks_dir
    gdir = config_dir if config_dir is not None else _resolve_global_config_dir()
    cfg_file = gdir / "orchestration.toml"
    if cfg_file.is_file():
        try:
            cfg_text = cfg_file.read_text(encoding="utf-8")
            if tomllib is not None:
                parsed = tomllib.loads(cfg_text)
                fb_td = parsed.get("feedback", {}).get("tasks_dir")
                if fb_td and str(fb_td).strip():
                    return "config", pathlib.Path(str(fb_td).strip()).expanduser().resolve()
        except Exception:
            pass

    # 3. Running bin/ai-orch repository if it is ai-orchestration
    repo_root = _find_repo_root()
    running_bin = None
    for cand in [
        os.environ.get("AI_ORCH_BIN"),
        sys.argv[0] if (sys.argv and sys.argv[0] and sys.argv[0].endswith("ai-orch")) else None,
        shutil.which("ai-orch"),
        str(repo_root / "bin" / "ai-orch") if repo_root is not None else None,
    ]:
        if cand:
            p = pathlib.Path(cand).resolve()
            if p.is_file():
                running_bin = p
                break

    if running_bin is not None:
        cand_repo = running_bin.parent.parent
        if (
            (cand_repo / "tasks" / "00-INDEX.md").is_file()
            and (cand_repo / "plugins" / "architect-side" / "skills" / "task-pipeline").is_dir()
        ):
            return "repo", (cand_repo / "tasks").resolve()

    # 4. Outbox
    if for_flush:
        return "outbox", None
    return "outbox", (gdir / "feedback-outbox").resolve()


def _queue_feedback_outbox(
    outbox_dir: pathlib.Path,
    title: str,
    kind: str,
    full_body: str,
    author: str,
    about: str = "-",
    short: str | None = None,
) -> tuple[pathlib.Path, str]:
    outbox_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "note"

    existing_notes = [
        d for d in outbox_dir.iterdir()
        if (d.is_dir() and (d / "note.md").is_file()) or (d.is_file() and d.suffix == ".md")
    ]
    next_num = len(existing_notes) + 1
    note_id = f"N{next_num:03d}"

    folder_name = f"{ts}-{slug}"
    candidate_folder = outbox_dir / folder_name
    if candidate_folder.exists():
        folder_name = f"{ts}-{slug}-{next_num}"
        candidate_folder = outbox_dir / folder_name
    candidate_folder.mkdir(parents=True, exist_ok=False)
    (candidate_folder / "attachments").mkdir(parents=True, exist_ok=True)

    short_val = short.strip() if short and short.strip() and short.strip() != "-" else derive_short_title(title.strip())
    content = format_note_content(
        id=note_id,
        title=title,
        kind=kind,
        status="ready",
        created=now.isoformat(),
        author=author,
        about=about,
        produced="-",
        processed_by="-",
        body=full_body,
        short=short_val,
    )
    note_file = candidate_folder / "note.md"
    note_file.write_text(content, encoding="utf-8")
    return candidate_folder, note_id


def _parse_outbox_note_file(nfile: pathlib.Path) -> dict[str, Any]:
    text = nfile.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = ""
    kind = "note"
    author = "owner"
    about = "-"
    short = None
    body_lines = []
    in_header = False
    in_body = False

    for line in lines:
        if not in_header and not in_body and line.startswith("# "):
            raw_title = line[2:].strip()
            m_id = re.match(r"^N\d+\s+(.*)$", raw_title)
            title = m_id.group(1).strip() if m_id else raw_title
            in_header = True
            continue
        if in_header:
            if not line.strip():
                in_header = False
                in_body = True
                continue
            m = HEADER_LINE_RE.match(line)
            if m:
                k, v = m.group(1), m.group(2).strip()
                if k == "title" and v:
                    title = v
                elif k == "kind" and v:
                    kind = v
                elif k == "author" and v:
                    author = v
                elif k == "about" and v:
                    about = v
                elif k == "short" and v and v != "-":
                    short = v
            else:
                in_header = False
                in_body = True
                body_lines.append(line)
        elif in_body:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return {
        "title": title or "Feedback note",
        "kind": kind,
        "author": author,
        "about": about,
        "short": short,
        "body": body,
    }


def cmd_feedback(args: argparse.Namespace) -> int:
    is_json = bool(getattr(args, "json", False) or "--json" in sys.argv)
    if getattr(args, "feedback_cmd", None) == "flush":
        return cmd_feedback_flush(args)

    kind = getattr(args, "kind", None)
    if not kind or kind not in ("bug", "feature", "idea", "request"):
        msg = f"Missing or invalid required --kind (got {kind!r}, expected one of: bug, feature, idea, request)."
        if is_json:
            print(json.dumps({"ok": False, "error": "invalid-kind", "message": msg}, indent=2))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 2

    title = getattr(args, "title", None)
    if not title or not title.strip():
        msg = "Missing required --title."
        if is_json:
            print(json.dumps({"ok": False, "error": "missing-title", "message": msg}, indent=2))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 2
    title = title.strip()

    body_file = getattr(args, "body_file", None)
    body_val = getattr(args, "body", None)
    if body_file:
        bf = pathlib.Path(body_file)
        if not bf.is_file():
            msg = f"Body file not found: {body_file}"
            if is_json:
                print(json.dumps({"ok": False, "error": "body-file-not-found", "message": msg}, indent=2))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2
        body_text = bf.read_text(encoding="utf-8")
    elif body_val is not None:
        body_text = body_val
    else:
        msg = "Missing required --body or --body-file."
        if is_json:
            print(json.dumps({"ok": False, "error": "missing-body", "message": msg}, indent=2))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 2

    author, ws_path = _resolve_feedback_author(getattr(args, "author", None))
    about = getattr(args, "about", "-") or "-"
    short = getattr(args, "short", None)
    if short and short.strip() and short.strip() != "-":
        issues = validate_short_title(short.strip())
        if issues:
            msg = f"Invalid short title {short!r}: {'; '.join(issues)}."
            if is_json:
                print(json.dumps({"ok": False, "error": "invalid-short-title", "message": msg}, indent=2))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2
        short = short.strip()
    else:
        short = derive_short_title(title)

    footer = (
        f"---\n"
        f"- Author: {author}\n"
        f"- Workspace: {ws_path}\n"
        f"- ai-orch: {_get_ai_orch_version_or_commit()}\n"
        f"- Date: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    full_body = f"{body_text.strip()}\n\n{footer}" if body_text.strip() else footer

    source, target_path = resolve_feedback_target()
    is_dry_run = bool(getattr(args, "dry_run", False))

    broker_held = False
    orig_target = target_path
    if source in ("env", "config", "repo"):
        b_status = _get_broker_status()
        if b_status is not None and getattr(b_status, "held", False) and not os.environ.get("AI_ORCH_BROKER_CHILD"):
            pid = getattr(b_status, "pid", None)
            pid_alive = bool(getattr(b_status, "pid_alive", False))
            if pid is not None and not pid_alive:
                broker_held = False
            elif pid_alive and getattr(b_status, "port", None):
                ret = _try_forward_to_live_broker(b_status, is_json)
                if ret is not None:
                    return ret
                broker_held = False
            else:
                broker_held = True
                source = "outbox"
                target_path = (_resolve_global_config_dir() / "feedback-outbox").resolve()

    if is_dry_run:
        if is_json:
            print(json.dumps({
                "ok": True,
                "dry_run": True,
                "target": str(target_path),
                "target_source": source,
                "broker_lock_held": broker_held,
                "note": {
                    "title": title,
                    "kind": kind,
                    "status": "ready",
                    "author": author,
                    "about": about,
                    "short": short,
                    "body": full_body,
                },
            }, indent=2))
        else:
            if broker_held:
                print(f"[notice] Broker lock is held on {orig_target} (broker-owns-writes); note would be queued in outbox.")
            print(f"[dry-run] Target: {target_path} (source: {source})")
            print("--- Note ---")
            print(f"# {title}\n")
            print(f"- title: {title}")
            print(f"- kind: {kind}")
            print(f"- status: ready")
            print(f"- author: {author}")
            print(f"- about: {about}")
            print(f"- short: {short}\n")
            print(full_body)
        return 0

    if source in ("env", "config", "repo"):
        ok, res = inbox_add(
            tasks_dir=target_path,
            title=title,
            kind=kind,
            body=full_body,
            about=about,
            author=author,
            status="ready",
            short=short,
        )
        if ok:
            if is_json:
                print(json.dumps({
                    "ok": True,
                    "id": res["id"],
                    "target": str(target_path),
                    "target_source": source,
                    "folder": res.get("folder"),
                    "rel_path": res.get("rel_path"),
                    "bundle_sha256": res.get("bundle_sha256"),
                }, indent=2))
            else:
                print(f"[ok] Created feedback note {res['id']}: {res['rel_path']}")
            return 0
        else:
            err = res.get("error", "inbox add failed")
            if "broker-owns-writes" in str(err) or "lock-timeout" in str(err):
                source = "outbox"
                target_path = (_resolve_global_config_dir() / "feedback-outbox").resolve()
                broker_held = True
            else:
                if is_json:
                    print(json.dumps({"ok": False, "error": err, "target": str(target_path)}, indent=2))
                else:
                    print(f"[FAIL] {err}", file=sys.stderr)
                return 1

    outbox_folder, note_id = _queue_feedback_outbox(
        outbox_dir=target_path,
        title=title,
        kind=kind,
        full_body=full_body,
        author=author,
        about=about,
        short=short,
    )
    gdir = _resolve_global_config_dir()
    if is_json:
        print(json.dumps({
            "ok": True,
            "queued": True,
            "broker_lock_held": broker_held,
            "target": str(target_path),
            "target_source": "outbox",
            "folder": outbox_folder.name,
            "rel_path": str((outbox_folder / "note.md").relative_to(target_path)),
            "id": note_id,
            "message": (
                "Feedback note queued in outbox. Configure [feedback] tasks_dir in "
                "orchestration.toml or run 'ai-orch feedback flush'."
            ),
        }, indent=2))
    else:
        if broker_held:
            print(f"[notice] Broker lock is held on {orig_target} (broker-owns-writes); queued note in outbox.")
        print(f"[ok] Feedback note queued in {outbox_folder / 'note.md'}")
        print(f"To deliver feedback directly to a tasks tree, configure [feedback] tasks_dir in your global orchestration.toml (under {gdir}) or set AI_ORCH_FEEDBACK_TASKS_DIR.")
        print("Run 'ai-orch feedback flush' to move queued notes once configured.")
    return 0


def cmd_feedback_flush(args: argparse.Namespace) -> int:
    is_json = bool(getattr(args, "json", False) or "--json" in sys.argv)
    is_dry_run = bool(getattr(args, "dry_run", False))

    source, target_path = resolve_feedback_target(for_flush=True)
    if target_path is None or source == "outbox":
        msg = (
            "Cannot flush: target tasks directory is not configured. "
            "Set [feedback] tasks_dir in orchestration.toml or set AI_ORCH_FEEDBACK_TASKS_DIR."
        )
        if is_json:
            print(json.dumps({"ok": False, "error": "target-not-configured", "message": msg}, indent=2))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 1

    b_status = _get_broker_status()
    if b_status is not None and getattr(b_status, "held", False) and not os.environ.get("AI_ORCH_BROKER_CHILD"):
        pid = getattr(b_status, "pid", None)
        pid_alive = bool(getattr(b_status, "pid_alive", False))
        if pid is not None and not pid_alive:
            pass
        elif pid_alive and getattr(b_status, "port", None):
            ret = _try_forward_to_live_broker(b_status, is_json)
            if ret is not None:
                return ret
        else:
            msg = "Cannot flush: broker lock is held on target tasks tree (broker-owns-writes)."
            if is_json:
                print(json.dumps({"ok": False, "error": "broker-owns-writes", "message": msg}, indent=2))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 1

    outbox_dir = _resolve_global_config_dir() / "feedback-outbox"
    if not outbox_dir.is_dir():
        if is_json:
            print(json.dumps({"ok": True, "flushed_count": 0, "notes": [], "message": "Outbox is empty (0 notes to flush)."}, indent=2))
        else:
            print("[ok] Outbox is empty (0 notes to flush).")
        return 0

    note_items: list[tuple[pathlib.Path, pathlib.Path]] = []
    for item in sorted(outbox_dir.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir() and (item / "note.md").is_file():
            note_items.append((item, item / "note.md"))
        elif item.is_file() and item.suffix == ".md":
            note_items.append((item, item))

    if not note_items:
        if is_json:
            print(json.dumps({"ok": True, "flushed_count": 0, "notes": [], "message": "Outbox is empty (0 notes to flush)."}, indent=2))
        else:
            print("[ok] Outbox is empty (0 notes to flush).")
        return 0

    if is_dry_run:
        notes_info = [{"folder": item.name, "file": str(nfile)} for item, nfile in note_items]
        if is_json:
            print(json.dumps({
                "ok": True,
                "dry_run": True,
                "would_flush_count": len(note_items),
                "target": str(target_path),
                "notes": notes_info,
            }, indent=2))
        else:
            print(f"[dry-run] Would flush {len(note_items)} note(s) from {outbox_dir} to {target_path}:")
            for item, nfile in note_items:
                print(f"  - {item.name}")
        return 0

    flushed: list[dict[str, Any]] = []
    for item, nfile in note_items:
        parsed = _parse_outbox_note_file(nfile)
        ok, res = inbox_add(
            tasks_dir=target_path,
            title=parsed["title"],
            kind=parsed["kind"],
            body=parsed["body"],
            about=parsed["about"],
            author=parsed["author"],
            status="ready",
            short=parsed.get("short"),
        )
        if not ok:
            err_msg = res.get("error", "inbox add failed during flush")
            if is_json:
                print(json.dumps({
                    "ok": False,
                    "error": err_msg,
                    "flushed_count": len(flushed),
                    "notes": flushed,
                }, indent=2))
            else:
                print(f"[FAIL] Flush failed on {item.name}: {err_msg}", file=sys.stderr)
            return 1

        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except OSError:
                pass
        flushed.append({"id": res["id"], "title": parsed["title"], "rel_path": res["rel_path"]})

    if is_json:
        print(json.dumps({
            "ok": True,
            "flushed_count": len(flushed),
            "target": str(target_path),
            "notes": flushed,
        }, indent=2))
    else:
        print(f"[ok] Flushed {len(flushed)} note(s) to {target_path}:")
        for f in flushed:
            print(f"  - {f['id']}: {f['title']}")
    return 0


def cmd_tasks_new(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_new_from_note(
        tasks_dir=tasks_dir,
        from_note=args.from_note,
        category=args.category,
        title=args.title,
        priority=getattr(args, "priority", "P2"),
        priority_reason=getattr(args, "priority_reason", None),
        executor=getattr(args, "executor", "kilo"),
        next_up=getattr(args, "next_up", "no"),
        depends_on=getattr(args, "depends_on", "-"),
        decider=getattr(args, "decider", "-"),
        goal=getattr(args, "goal", None),
        sources=getattr(args, "sources", None),
        paths=getattr(args, "paths", None),
        parent=getattr(args, "parent", None),
        short=getattr(args, "short", None),
        steps=getattr(args, "steps", None),
        verifications=getattr(args, "verifications", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Created task {res['id']}: {res['rel_path']}")
        else:
            print(f"[FAIL] {res.get('error', 'tasks new failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_tasks_micro(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_micro(
        tasks_dir=tasks_dir,
        title=args.title,
        kind=getattr(args, "kind", "chore"),
        priority=getattr(args, "priority", "P2"),
        paths=getattr(args, "paths", "-"),
        depends_on=getattr(args, "depends_on", "-"),
        labels=getattr(args, "label", None),
        size=getattr(args, "size", None),
        executor=getattr(args, "executor", "kilo"),
        what=getattr(args, "what", None),
        short=getattr(args, "short", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Created microtask {res['id']}: {res['rel_path']}")
        else:
            print(f"[FAIL] {res.get('error', 'tasks micro failed')}", file=sys.stderr)
    return 0 if ok else 1


def cmd_tasks_promote(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    ok, res = tasks_promote(
        tasks_dir=tasks_dir,
        task_id=args.task_id,
        category=getattr(args, "category", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Promoted {res['id']} to category '{res['category']}': {res['rel_path']}")
        else:
            print(f"[FAIL] {res.get('error', 'tasks promote failed')}", file=sys.stderr)
    return 0 if ok else 1


def move_task(
    tasks_dir: pathlib.Path,
    task_id: str,
    to_project: str | None = None,
    to_tasks_dir: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_task_hash: str | None = None,
) -> dict[str, Any]:
    src_tasks_dir = pathlib.Path(tasks_dir).resolve()

    if not to_project and not to_tasks_dir:
        return {"ok": False, "error": "Either --to-project or --to-tasks-dir must be specified."}

    if to_tasks_dir is not None:
        target_tasks_dir = pathlib.Path(to_tasks_dir).resolve()
        target_proj_slug = to_project or target_tasks_dir.parent.name
    else:
        assert to_project is not None
        target_proj_slug = to_project
        resolved = resolve_project_tasks_dir(to_project, src_tasks_dir)
        if resolved is None:
            return {
                "ok": False,
                "error": f"Cannot resolve target project {to_project!r} from workspace configuration.",
            }
        target_tasks_dir = resolved

    # Validate task_id format
    if not EMERGENT_ID_RE.match(task_id):
        return {"ok": False, "error": f"tasks move only supports emergent tasks (T###), got {task_id!r}."}

    emergent = discover_emergent_tasks(src_tasks_dir)
    target_task = next((t for t in emergent if t.get("id") == task_id), None)
    if not target_task:
        return {"ok": False, "error": f"Task {task_id!r} not found in {src_tasks_dir}."}

    if target_task.get("canonical_state") == "moved" or target_task.get("moved_to"):
        return {"ok": False, "error": f"Task {task_id!r} has already been moved ({target_task.get('moved_to')})."}

    # Check CAS hash if provided
    if expect_task_hash is not None:
        curr_b_hash = target_task.get("bundle_sha256", "")
        curr_f_hash = _file_sha256(pathlib.Path(target_task["file_path"]))
        exp = expect_task_hash.strip().lower()
        if curr_b_hash.lower() != exp and curr_f_hash.lower() != exp:
            return {
                "ok": False,
                "error": f"Task hash mismatch: expected {expect_task_hash}, actual bundle={curr_b_hash}, file={curr_f_hash}.",
                "expected": expect_task_hash,
                "actual": curr_b_hash,
            }

    # Find next free T### in target tree
    target_nums: list[int] = []
    if target_tasks_dir.is_dir():
        target_emergent = discover_emergent_tasks(target_tasks_dir)
        for t in target_emergent:
            tid = t.get("id", "")
            if tid and EMERGENT_ID_RE.match(tid):
                target_nums.append(int(tid[1:]))
        for p in target_tasks_dir.rglob("T[0-9][0-9][0-9]*"):
            m_t = re.match(r"^(T\d{3,})", p.name)
            if m_t:
                target_nums.append(int(m_t.group(1)[1:]))

    next_num = max(target_nums, default=0) + 1
    new_tid = f"T{next_num:03d}"

    category = target_task.get("folder_category") or target_task.get("category") or "tasks"
    src_file = pathlib.Path(target_task["file_path"])
    is_folder = target_task.get("is_folder", False)
    src_root = pathlib.Path(target_task["task_root"])
    src_stem = src_root.name if is_folder else src_file.stem
    slug = re.sub(r"^T\d{3,}-", "", src_stem) or target_task.get("slug") or slugify(target_task.get("title", "task"))

    target_cat_dir = target_tasks_dir / category
    if is_folder:
        target_task_root = target_cat_dir / f"{new_tid}-{slug}"
        target_file = target_task_root / "README.md"
    else:
        target_task_root = target_cat_dir
        target_file = target_cat_dir / f"{new_tid}-{slug}.md"

    # Rewrite target content: replace ID in header and title
    src_old_text = src_file.read_text(encoding="utf-8")
    target_text = re.sub(
        r"^-\s+id:\s*.*$",
        f"- id: {new_tid}",
        src_old_text,
        count=1,
        flags=re.MULTILINE,
    )
    target_text = re.sub(
        r"^-\s+category:\s*.*$",
        f"- category: {category}",
        target_text,
        count=1,
        flags=re.MULTILINE,
    )
    # Heading rewrite: `# T### ...` -> `# T### ...`
    target_text = re.sub(
        rf"^#\s+{re.escape(task_id)}\b",
        f"# {new_tid}",
        target_text,
        count=1,
        flags=re.MULTILINE,
    )

    # Paths and handoff are relative to the tree's root: rebase them from the workspace root to the project root.
    try:
        ws_root = pathlib.Path(tasks_dir).resolve().parent
        proj_root = target_tasks_dir.resolve().parent
        proj_prefix = proj_root.relative_to(ws_root).as_posix()
    except (ValueError, OSError):
        proj_prefix = ""
    if proj_prefix and proj_prefix != ".":
        def _rebase_paths(m: "re.Match[str]") -> str:
            items = [x.strip() for x in m.group(1).split(",")]
            rebased = [x[len(proj_prefix) + 1:] if x.startswith(proj_prefix + "/") else x for x in items]
            return "- paths: " + ", ".join(rebased)
        target_text = re.sub(r"^-\s+paths:\s*(.*)$", _rebase_paths, target_text, count=1, flags=re.MULTILINE)
    try:
        old_rel = src_file.resolve().relative_to(pathlib.Path(tasks_dir).resolve().parent).as_posix()
        new_rel = target_file.resolve().relative_to(target_tasks_dir.resolve().parent).as_posix()
        target_text = target_text.replace(old_rel, new_rel)
    except (ValueError, OSError):
        pass

    # Pointer content for source tree
    title = target_task.get("title") or "Task"
    priority = target_task.get("priority") or "P2"
    executor = target_task.get("executor") or "kilo"
    pointer_text = f"""# {task_id} - {title} (moved)

- id: {task_id}
- title: {title} (moved)
- category: {category}
- priority: {priority}
- priority-reason: Moved to {target_proj_slug}/{new_tid}
- next-up: no
- state: moved
- executor: {executor}
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Moved to {target_proj_slug}/{new_tid}
- moved-to: {target_proj_slug}/{new_tid}

## Goal

Task moved to {target_proj_slug} as {new_tid}.

## Steps

- [x] Moved to {target_proj_slug} as {new_tid}.

## Verification

- [x] Moved to {target_proj_slug} as {new_tid}.
"""

    diff_source = "".join(difflib.unified_diff(
        src_old_text.splitlines(keepends=True),
        pointer_text.splitlines(keepends=True),
        fromfile=str(src_file),
        tofile=f"{src_file} (pointer)",
    ))
    diff_target = "".join(difflib.unified_diff(
        [],
        target_text.splitlines(keepends=True),
        fromfile="/dev/null",
        tofile=str(target_file),
    ))

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "task_id": task_id,
            "new_task_id": new_tid,
            "to_project": target_proj_slug,
            "source_file": str(src_file),
            "target_file": str(target_file),
            "diff_source": diff_source,
            "diff_target": diff_target,
            "diffs": [diff_source, diff_target],
        }

    # Non-dry-run: write files and sync both indexes under lock
    lock_dirs = sorted([src_tasks_dir, target_tasks_dir], key=lambda p: str(p))
    with task_write_lock(lock_dirs[0]):
        with task_write_lock(lock_dirs[1]):
            # 1. Write target
            target_cat_dir.mkdir(parents=True, exist_ok=True)
            if is_folder:
                target_task_root.mkdir(parents=True, exist_ok=True)
                for item in src_root.iterdir():
                    if item.name == "README.md":
                        continue
                    if item.is_file():
                        shutil.copy2(item, target_task_root / item.name)
                    elif item.is_dir():
                        shutil.copytree(item, target_task_root / item.name, dirs_exist_ok=True)
                target_file.write_text(target_text, encoding="utf-8")
                for item in src_root.iterdir():
                    if item.name == "README.md":
                        continue
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                src_file.write_text(pointer_text, encoding="utf-8")
            else:
                target_file.write_text(target_text, encoding="utf-8")
                src_file.write_text(pointer_text, encoding="utf-8")

            # 2. Sync source index with --apply
            src_index_file = src_tasks_dir / "00-INDEX.md"
            src_index_txt = src_index_file.read_text(encoding="utf-8") if src_index_file.exists() else ""
            new_src_index = render_synced_index(src_tasks_dir, src_index_txt, adopt=True)
            src_index_file.write_text(new_src_index, encoding="utf-8")

            # 3. Sync target index with --apply
            target_index_file = target_tasks_dir / "00-INDEX.md"
            target_index_txt = target_index_file.read_text(encoding="utf-8") if target_index_file.exists() else ""
            new_target_index = render_synced_index(target_tasks_dir, target_index_txt, adopt=True)
            target_index_file.write_text(new_target_index, encoding="utf-8")

    return {
        "ok": True,
        "dry_run": False,
        "task_id": task_id,
        "new_task_id": new_tid,
        "to_project": target_proj_slug,
        "source_file": str(src_file),
        "target_file": str(target_file),
        "diff_source": diff_source,
        "diff_target": diff_target,
    }


def cmd_tasks_move(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(getattr(args, "tasks_dir", "tasks")).resolve()
    to_proj = getattr(args, "to_project", None)
    to_tasks = getattr(args, "to_tasks_dir", None)
    to_tasks_dir = pathlib.Path(to_tasks).resolve() if to_tasks else None
    dry_run = getattr(args, "dry_run", False)
    expect_hash = getattr(args, "expect_task_hash", None)

    res = move_task(
        tasks_dir=tasks_dir,
        task_id=args.task_id,
        to_project=to_proj,
        to_tasks_dir=to_tasks_dir,
        dry_run=dry_run,
        expect_task_hash=expect_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if not res.get("ok"):
            print(f"[FAIL] {res.get('error', 'tasks move failed')}", file=sys.stderr)
            return 1
        if dry_run:
            print(f"Preview: move {args.task_id} to project {res.get('to_project')} as {res.get('new_task_id')}")
            print(f"--- Source diff: {res.get('source_file')} ---")
            print(res.get("diff_source", ""), end="")
            print(f"--- Target diff: {res.get('target_file')} ---")
            print(res.get("diff_target", ""), end="")
        else:
            print(f"[ok] Moved {args.task_id} to {res.get('to_project')}/{res.get('new_task_id')} ({res.get('target_file')})")
    return 0 if res.get("ok") else 1


def cmd_set_kind(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    expect_task_hash = getattr(args, "expect_task_hash", None)
    dry_run = getattr(args, "dry_run", False)
    res = set_kind(
        tasks_dir=tasks_dir,
        node_id=args.id,
        kind=args.kind,
        dry_run=dry_run,
        expect_task_hash=expect_task_hash,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if res.get("ok"):
            if res.get("dry_run"):
                print(f"[ok] dry-run: kind for {args.id} would become: {res.get('kind')}")
                if res.get("diff"):
                    print(res.get("diff"), end="")
            else:
                print(f"[ok] updated kind for {args.id}: {res.get('kind')}")
        else:
            print(f"[FAIL] {res.get('error', 'set-kind failed')}", file=sys.stderr)
    return 0 if res.get("ok") else 1


def cmd_labels(args: argparse.Namespace) -> int:
    tasks_dir = pathlib.Path(args.tasks_dir).resolve()
    tree = discover_task_tree(tasks_dir)
    counts: dict[str, int] = {}
    for node in tree.values():
        for lbl in node.labels:
            counts[lbl] = counts.get(lbl, 0) + 1
    sorted_labels = [{"label": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    payload = {
        "ok": True,
        "tasks_dir": str(tasks_dir),
        "labels": sorted_labels,
        "counts": counts,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        if not counts:
            print("No labels in use.")
        else:
            print(f"Labels in use: {len(counts)}")
            for item in sorted_labels:
                print(f"  {item['label']} ({item['count']})")
    return 0


def _instrument_subparsers(sub_action: Any) -> Any:
    orig = sub_action.add_parser

    def add_parser(*args: Any, **kwargs: Any) -> argparse.ArgumentParser:
        p = orig(*args, **kwargs)
        p.add_argument(
            "--idempotency-key",
            default=None,
            help="Idempotency key (8-128 chars from [A-Za-z0-9_.:-]) for deduplicating mutations",
        )
        return p

    sub_action.add_parser = add_parser
    return sub_action


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="Output structured JSON on stdout")
    ap.add_argument(
        "--idempotency-key",
        default=None,
        help="Idempotency key (8-128 chars from [A-Za-z0-9_.:-]) for deduplicating mutations",
    )

    sub = _instrument_subparsers(ap.add_subparsers(dest="cmd", required=True))

    p_list = sub.add_parser("list", help="List all emergent tasks and initiatives in tasks/")
    p_list.add_argument("--kind", action="append", default=None, help="Filter by kind (repeatable, OR within field)")
    p_list.add_argument("--label", action="append", default=None, help="Filter by label (repeatable, OR within field)")
    p_list.add_argument("--workspace", default=None, help="Workspace slug, UUID, or path")
    p_list.add_argument("--all-projects", action="store_true", help="List tasks across all projects in workspace")
    p_list.add_argument("--state", default=None, help="Filter by state (e.g. open)")
    p_list.add_argument("--active-only", action="store_true", help="Filter active (non-terminal) tasks")
    p_list.add_argument("--limit", type=int, default=None, help="Maximum number of tasks to return")
    p_list.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_list.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show task details")
    p_show.add_argument("task_id", help="Task ID (e.g. T001, 01.1)")
    p_show.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_show.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_show.set_defaults(func=cmd_show)

    p_val = sub.add_parser("validate", help="Validate task headers, IDs, sections, and dependency DAG")
    p_val.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_val.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_val.set_defaults(func=cmd_validate)

    p_tr = sub.add_parser("transition", help="Transition a task to a new state enforcing state-machine guards")
    p_tr.add_argument("task_id", help="Task ID (e.g. T001)")
    p_tr.add_argument("new_state", nargs="?", default=None, help="New state (e.g. 'in progress', 'delivered', 'verified', 'bounced', 'done')")
    p_tr.add_argument("--to", dest="to_state", default=None, help="Target state (alternative to positional new_state)")
    p_tr.add_argument("--waiting-on", default=None, help="Waiting-on qualifier when transitioning to waiting (e.g. question:Q###, owner:..., external:..., session:...)")
    p_tr.add_argument("--actor", default=None, help="Actor performing the transition (e.g. kilo, claude, owner)")
    p_tr.add_argument("--verifier", default=None, help="Independent verifier identifier (e.g. claude:deep-reasoning, blind-subagent:deep-reasoning, owner)")
    p_tr.add_argument("--verify-by", default=None, help="Durable verification request target (e.g. gcube_atlas, workspace:gcube_atlas, session:...)")
    p_tr.add_argument("--verify-check", default=None, help="What to check during verification")
    p_tr.add_argument("--reason", default=None, help="Bounce findings (B1..Bn), caveat reason, or transition note")
    p_tr.add_argument("--expect-task-hash", default=None, help="Refuse to transition if task bundle SHA256 does not match this hash")
    p_tr.add_argument("--force-unblock", action="store_true", help="Force move task out of waiting, withdrawing open questions with --reason")
    p_tr.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_tr.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_tr.set_defaults(func=cmd_transition)

    p_close = sub.add_parser("close", help="One-shot close a task through legal intermediate transitions to done")
    p_close.add_argument("task_id", metavar="id", help="Task ID (e.g. T001, 01.1)")
    p_close.add_argument("--verifier", default=None, help="Independent verifier identifier (e.g. reviewer, owner)")
    p_close.add_argument("--reason", default=None, help="Closure reason or caveat reason")
    p_close.add_argument("--actor", default=None, help="Actor performing the close")
    p_close.add_argument("--owner-approved", action="store_true", default=False, help="Flag indicating explicit owner approval for verification")
    p_close.add_argument("--caveat", default=None, help="Caveat description for closing to 'done with a caveat'")
    p_close.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_close.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_close.set_defaults(func=cmd_close)

    p_q = sub.add_parser("questions", help="Manage blocking question files (Q###) and task decision linkage")
    p_q.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_q.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    q_sub = _instrument_subparsers(p_q.add_subparsers(dest="q_cmd", required=True))

    # questions list
    p_ql = q_sub.add_parser("list", help="List blocking questions")
    p_ql.add_argument("--status", choices=["open", "answered", "withdrawn", "moved", "unapplied", "all"], default="all")
    p_ql.add_argument("--blocks", default=None, help="Filter by blocked task id")
    p_ql.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_ql.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_ql.set_defaults(func=cmd_questions_list)

    # questions show
    p_qs = q_sub.add_parser("show", help="Show a blocking question")
    p_qs.add_argument("question_id", help="Question ID (e.g. Q001)")
    p_qs.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_qs.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_qs.set_defaults(func=cmd_questions_show)

    # questions ask
    p_qa = q_sub.add_parser("ask", help="Ask a blocking question")
    p_qa.add_argument("--question", default=None, help="Question text (<= 160 chars, ends with ?)")
    p_qa.add_argument("--context", default=None, help="Context text")
    p_qa.add_argument("--context-file", default=None, help="Path to file containing context Markdown")
    p_qa.add_argument("--option", action="append", default=[], help="Option formatted as 'A=Title: consequence' or '- **A** — Title: consequence'")
    p_qa.add_argument("--recommended", default="-", help="Recommended option label or -")
    p_qa.add_argument("--open-answer", choices=["yes", "no"], default="no", help="Whether open free-text answers are allowed")
    p_qa.add_argument("--blocks", default="-", help="Comma-separated blocked task IDs (e.g. T013, T014) or '-' for non-blocking")
    p_qa.add_argument("--decider", default="owner", help="Decider role or person")
    p_qa.add_argument("--asked-by", default="owner", help="Who asked the question")
    p_qa.add_argument("--origin-run", default="-", help="Origin run ID or -")
    p_qa.add_argument("--from-task", default=None, help="Convert legacy decider header from task T###")
    p_qa.add_argument("--short", default=None, help="Short title (1-5 words, <=40 chars); derived when omitted")
    p_qa.add_argument("--notes", default=None, help="Optional free notes / discussion text")
    p_qa.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_qa.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_qa.set_defaults(func=cmd_questions_ask)

    # questions answer
    p_qans = q_sub.add_parser("answer", help="Answer a blocking question")
    p_qans.add_argument("question_id", help="Question ID (e.g. Q001)")
    p_qans.add_argument("--choice", required=True, help="Selected option label or 'open'")
    p_qans.add_argument("--text", default=None, help="Free-text answer")
    p_qans.add_argument("--by", default="owner", help="Who answered the question")
    p_qans.add_argument("--changes-result", action="store_true", default=False, help="Flag that answer changes a finished task's result, creating follow-up task(s)")
    p_qans.add_argument("--apply-ref", default=None, help="Reference to immediately record application")
    p_qans.add_argument("--apply-note", default=None, help="Note to immediately record application")
    p_qans.add_argument("--note", default=None, dest="apply_note", help="Note to immediately record application (alias for --apply-note)")
    p_qans.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_qans.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_qans.set_defaults(func=cmd_questions_answer)

    # questions withdraw
    p_qw = q_sub.add_parser("withdraw", help="Withdraw a blocking question")
    p_qw.add_argument("question_id", help="Question ID (e.g. Q001)")
    p_qw.add_argument("--reason", required=True, help="Reason for withdrawing the question")
    p_qw.add_argument("--by", default="owner", help="Who withdrew the question")
    p_qw.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_qw.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_qw.set_defaults(func=cmd_questions_withdraw)

    # questions move
    p_qm = q_sub.add_parser("move", help="Move a question to an external tracker (status: moved)")
    p_qm.add_argument("question_id", help="Question ID (e.g. Q001)")
    p_qm.add_argument("--to", required=True, help="External tracker URL or reference (e.g. https://tracker.example/issue/42)")
    p_qm.add_argument("--reason", default=None, help="Optional reason for moving the question")
    p_qm.add_argument("--by", default="owner", help="Who moved the question")
    p_qm.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_qm.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_qm.set_defaults(func=cmd_questions_move)

    # questions apply
    p_qapp = q_sub.add_parser("apply", help="Record that an answered question's decision was applied into the ledger")
    p_qapp.add_argument("question_id", help="Question ID (e.g. Q001)")
    p_qapp.add_argument("--by", default="owner", help="Who applied the question (default: owner)")
    p_qapp.add_argument("--ref", default=None, help="Reference (task ID, commit, PR, or config change)")
    p_qapp.add_argument("--note", default=None, help="Note or description of how the decision was applied")
    p_qapp.add_argument("--force", action="store_true", help="Apply even if already recorded in ledger")
    p_qapp.add_argument("--dry-run", action="store_true", help="Preview apply without writing ledger or emitting event")
    p_qapp.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_qapp.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_qapp.set_defaults(func=cmd_questions_apply)

    p_sync = sub.add_parser("sync-index", help="Deterministically synchronize tasks/00-INDEX.md tables from task headers")
    p_sync.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sync.add_argument("--apply", action="store_true", help="Write updated 00-INDEX.md in place")
    p_sync.add_argument("--check", action="store_true", help="Exit non-zero if 00-INDEX.md is out of sync")
    p_sync.add_argument("--adopt", action="store_true", help="Preview wrapping existing generated tables in markers (apply with --adopt --apply --expect-hash <hash>)")
    p_sync.add_argument("--expect-hash", default=None, help="Refuse to apply if current index SHA256 does not match this hash")
    p_sync.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sync.set_defaults(func=cmd_sync_index)

    p_merge = sub.add_parser("merge-index", help="Conflict-free merge driver and resolver for tasks/00-INDEX.md")
    p_merge.add_argument("base", nargs="?", default=None, help="Base/ancestor file (%%O)")
    p_merge.add_argument("ours", nargs="?", default=None, help="Ours file to overwrite (%%A)")
    p_merge.add_argument("theirs", nargs="?", default=None, help="Theirs file (%%B)")
    p_merge.add_argument("--tasks-dir", default=None, help="Path to tasks/ directory")
    p_merge.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_merge.set_defaults(func=cmd_merge_index)

    p_upg = sub.add_parser("upgrade", help="Upgrade a tasks/ directory to the latest task-pipeline v0.3.0 convention")
    p_upg.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_upg.add_argument("--dry-run", action="store_true", default=False, help="Preview changes without writing to disk")
    p_upg.add_argument("--migrate-plans", action="store_true", default=False, help="Migrate discovered legacy plans into tasks/ directory")
    p_upg.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_upg.set_defaults(func=cmd_upgrade)

    p_inbox = sub.add_parser("inbox", help="Manage inbox draft notes, image attachments, and triage")
    p_inbox.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_inbox.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    inbox_sub = _instrument_subparsers(p_inbox.add_subparsers(dest="inbox_cmd", required=True))

    # inbox list
    p_il = inbox_sub.add_parser("list", help="List inbox notes")
    p_il.add_argument("--status", choices=["draft", "ready", "processing", "processed", "discarded", "all"], default="all")
    p_il.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_il.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_il.set_defaults(func=cmd_inbox_list)

    # inbox show
    p_is = inbox_sub.add_parser("show", help="Show an inbox note")
    p_is.add_argument("note_id", help="Note ID (e.g. N001) or legacy filename")
    p_is.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_is.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_is.set_defaults(func=cmd_inbox_show)

    # inbox add
    p_ia = inbox_sub.add_parser("add", help="Add a new inbox note")
    p_ia.add_argument("--title", required=True, help="Short title of the note")
    p_ia.add_argument("--kind", choices=sorted(NOTE_KINDS), default="note", help="Kind of note")
    p_ia.add_argument("--body", default=None, help="Markdown body text")
    p_ia.add_argument("--body-file", default=None, help="Path to file containing body Markdown")
    p_ia.add_argument("--about", default="-", help="About paths, repos or task IDs")
    p_ia.add_argument("--author", default="owner", help="Author of the note")
    p_ia.add_argument("--status", choices=["draft", "ready"], default="draft", help="Initial status")
    p_ia.add_argument("--short", default=None, help="Short title (1-5 words, <=40 chars); derived when omitted")
    p_ia.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_ia.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_ia.set_defaults(func=cmd_inbox_add)

    # inbox edit
    p_ie = inbox_sub.add_parser("edit", help="Edit an inbox note")
    p_ie.add_argument("note_id", help="Note ID (e.g. N001) or legacy filename")
    p_ie.add_argument("--title", default=None, help="Updated title")
    p_ie.add_argument("--kind", choices=sorted(NOTE_KINDS), default=None, help="Updated kind")
    p_ie.add_argument("--body", default=None, help="Updated body text")
    p_ie.add_argument("--body-file", default=None, help="Updated body file")
    p_ie.add_argument("--about", default=None, help="Updated about")
    p_ie.add_argument("--author", default=None, help="Updated author")
    p_ie.add_argument("--status", choices=["draft", "ready"], default=None, help="Updated status")
    p_ie.add_argument("--expect-hash", default=None, help="Refuse edit if bundle SHA256 does not match")
    p_ie.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_ie.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_ie.set_defaults(func=cmd_inbox_edit)

    # inbox attach
    p_iatt = inbox_sub.add_parser("attach", help="Attach a file to an inbox note")
    p_iatt.add_argument("note_id", help="Note ID (e.g. N001)")
    p_iatt.add_argument("--file", required=True, help="Path to file to attach (image, text, pdf; <=10MB)")
    p_iatt.add_argument("--name", default=None, help="Custom attachment name/stem")
    p_iatt.add_argument("--expect-hash", default=None, help="Refuse attach if bundle SHA256 does not match")
    p_iatt.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_iatt.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_iatt.set_defaults(func=cmd_inbox_attach)

    # inbox detach
    p_idet = inbox_sub.add_parser("detach", help="Detach an attachment from an inbox note")
    p_idet.add_argument("note_id", help="Note ID (e.g. N001)")
    p_idet.add_argument("--name", required=True, help="Attachment filename to detach")
    p_idet.add_argument("--expect-hash", default=None, help="Refuse detach if bundle SHA256 does not match")
    p_idet.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_idet.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_idet.set_defaults(func=cmd_inbox_detach)

    # inbox resolve
    p_ires = inbox_sub.add_parser("resolve", help="Mark an inbox note processed and move to analyzed/")
    p_ires.add_argument("note_id", help="Note ID (e.g. N001)")
    p_ires.add_argument("--produced", required=True, help="IDs/paths produced by processing")
    p_ires.add_argument("--by", default="owner", help="Who processed the note")
    p_ires.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_ires.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_ires.set_defaults(func=cmd_inbox_resolve)

    # inbox discard
    p_idisc = inbox_sub.add_parser("discard", help="Discard an inbox note and move to analyzed/")
    p_idisc.add_argument("note_id", help="Note ID (e.g. N001)")
    p_idisc.add_argument("--reason", required=True, help="Reason for discarding the note")
    p_idisc.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_idisc.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_idisc.set_defaults(func=cmd_inbox_discard)

    # inbox reopen
    p_ireop = inbox_sub.add_parser("reopen", help="Reopen an inbox note and move back to to-analyze/ as ready")
    p_ireop.add_argument("note_id", help="Note ID (e.g. N001)")
    p_ireop.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_ireop.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_ireop.set_defaults(func=cmd_inbox_reopen)

    # tasks move
    p_move = sub.add_parser("move", help="Move an emergent task from the workspace tree into a project")
    p_move.add_argument("task_id", help="ID of the emergent task to move (e.g. T014)")
    p_move.add_argument("--to-project", "-p", dest="to_project", default=None, help="Target project slug")
    p_move.add_argument("--to-tasks-dir", dest="to_tasks_dir", default=None, help="Explicit target tasks/ directory")
    p_move.add_argument("--dry-run", action="store_true", help="Preview move without writing files")
    p_move.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task file/bundle hash")
    p_move.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_move.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_move.set_defaults(func=cmd_tasks_move)

    # tasks new
    p_new = sub.add_parser("new", help="Create a new task from an inbox note")
    p_new.add_argument("--from-note", default=None, help="Source inbox note ID (e.g. N001) or filename; omit to create a standalone task")
    p_new.add_argument("--parent", default=None, help="Parent task/initiative ID to create task as a child")
    p_new.add_argument("--goal", default=None, help="Goal paragraph (required without --from-note)")
    p_new.add_argument("--sources", default=None, help="Sources header value (standalone tasks)")
    p_new.add_argument("--paths", default=None, help="Paths header value (standalone tasks)")
    p_new.add_argument("--category", default=None, help="Category folder name (defaults to kind hint if --from-note given)")
    p_new.add_argument("--title", required=True, help="Task title")
    p_new.add_argument("--priority", choices=sorted(PRIORITIES), default="P2", help="Priority (default P2)")
    p_new.add_argument("--priority-reason", default=None, help="Priority explanation")
    p_new.add_argument("--executor", default="kilo", help="Assigned executor")
    p_new.add_argument("--next-up", choices=sorted(NEXT_UP_VALUES), default="no", help="Next up flag")
    p_new.add_argument("--depends-on", default="-", help="Dependencies")
    p_new.add_argument("--decider", default="-", help="Decider")
    p_new.add_argument("--short", default=None, help="Short title (1-5 words, <=40 chars); derived when omitted")
    p_new.add_argument("--step", action="append", dest="steps", metavar="STEP", default=None, help="Add a step item under ## Steps (repeatable)")
    p_new.add_argument("--verification", action="append", dest="verifications", metavar="VERIFICATION", default=None, help="Add a verification item under ## Verification (repeatable)")
    p_new.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_new.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_new.set_defaults(func=cmd_tasks_new)

    # tasks attach
    p_tatt = sub.add_parser("attach", help="Attach a file to an emergent task")
    p_tatt.add_argument("task_id", help="Task ID (e.g. T001)")
    p_tatt.add_argument("--file", required=True, help="Path to file to attach (image, text, pdf; <=10MB)")
    p_tatt.add_argument("--name", default=None, help="Optional attachment name stem")
    p_tatt.add_argument("--expect-task-hash", default=None, help="Expected task bundle SHA256")
    p_tatt.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_tatt.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_tatt.set_defaults(func=cmd_tasks_attach)

    # tasks detach
    p_tdet = sub.add_parser("detach", help="Detach an attachment from an emergent task")
    p_tdet.add_argument("task_id", help="Task ID (e.g. T001)")
    p_tdet.add_argument("--name", required=True, help="Attachment file name to detach (e.g. 01-doc.pdf)")
    p_tdet.add_argument("--expect-task-hash", default=None, help="Expected task bundle SHA256")
    p_tdet.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_tdet.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_tdet.set_defaults(func=cmd_tasks_detach)

    # tasks child add
    p_child = sub.add_parser("child", help="Structure commands: child tasks")
    p_child.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_child.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    child_sub = _instrument_subparsers(p_child.add_subparsers(dest="child_cmd", required=True))

    p_cadd = child_sub.add_parser("add", help="Add a child task under a parent")
    p_cadd.add_argument("parent", help="Parent ID (e.g. '07' or '07.4')")
    p_cadd.add_argument("--title", required=True, help="Child task title")
    p_cadd.add_argument("--kind", default="feature", help="Child task kind")
    p_cadd.add_argument("--short", default=None, help="Short title (1-5 words, <=40 chars); derived when omitted")
    p_cadd.add_argument("--dry-run", action="store_true", help="Compute plan without writing")
    p_cadd.add_argument("--expect-plan-hash", default=None, help="Expected plan hash")
    p_cadd.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_cadd.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_cadd.set_defaults(func=cmd_child_add)

    # tasks expand
    p_exp = sub.add_parser("expand", help="Expand an inline block into a folder")
    p_exp.add_argument("id", help="Node ID to expand")
    p_exp.add_argument("--dry-run", action="store_true", help="Compute plan without writing")
    p_exp.add_argument("--expect-plan-hash", default=None, help="Expected plan hash")
    p_exp.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_exp.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_exp.set_defaults(func=cmd_expand)

    # tasks collapse
    p_col = sub.add_parser("collapse", help="Collapse an expanded folder back into an inline block")
    p_col.add_argument("id", help="Node ID to collapse")
    p_col.add_argument("--dry-run", action="store_true", help="Compute plan without writing")
    p_col.add_argument("--expect-plan-hash", default=None, help="Expected plan hash")
    p_col.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_col.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_col.set_defaults(func=cmd_collapse)

    # tasks reopen
    p_reop_task = sub.add_parser("reopen", help="Reopen a terminal leaf task back to open")
    p_reop_task.add_argument("id", help="Node ID to reopen")
    p_reop_task.add_argument("--reason", required=True, help="Reason for reopening")
    p_reop_task.add_argument("--dry-run", action="store_true", help="Compute plan without writing")
    p_reop_task.add_argument("--expect-plan-hash", default=None, help="Expected plan hash")
    p_reop_task.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_reop_task.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_reop_task.set_defaults(func=cmd_reopen)

    # tasks ship
    p_ship = sub.add_parser("ship", help="Ship a completed initiative to tasks/done/NN-slug/ with summary.md skeleton and link rewriting")
    p_ship.add_argument("id", help="Initiative ID to ship (e.g. 01, 15)")
    p_ship.add_argument("--dry-run", action="store_true", help="Compute plan without writing")
    p_ship.add_argument("--expect-plan-hash", default=None, help="Expected plan hash")
    p_ship.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_ship.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_ship.set_defaults(func=cmd_ship)

    # tasks archive
    p_arch = sub.add_parser("archive", help="Fix misplaced closed items at every level with dry-run plan")
    p_arch.add_argument("--dry-run", action="store_true", help="Compute plan without writing")
    p_arch.add_argument("--expect-plan-hash", default=None, help="Expected plan hash")
    p_arch.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_arch.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_arch.set_defaults(func=cmd_archive)

    # tasks graph
    p_graph = sub.add_parser("graph", help="Compute abstract timeline dependency graph")
    p_graph.add_argument("--kind", action="append", default=None, help="Filter by kind (repeatable, OR within field)")
    p_graph.add_argument("--label", action="append", default=None, help="Filter by label (repeatable, OR within field)")
    p_graph.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_graph.add_argument("--mermaid", action="store_true", default=False, help="Output Mermaid flowchart")
    p_graph.add_argument("--all", action="store_true", default=False, help="Mermaid: include closed tasks too")
    p_graph.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_graph.set_defaults(func=cmd_graph)

    # tasks next
    p_next = sub.add_parser("next", help="Show ready queue / next actionable tasks")
    p_next.add_argument("--kind", action="append", default=None, help="Filter by kind (repeatable, OR within field)")
    p_next.add_argument("--label", action="append", default=None, help="Filter by label (repeatable, OR within field)")
    p_next.add_argument("--workspace", default=None, help="Workspace slug, UUID, or path")
    p_next.add_argument("--all-projects", action="store_true", help="Show ready queue across all projects in workspace")
    p_next.add_argument("--limit", type=int, default=None, help="Maximum number of tasks to return")
    p_next.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_next.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_next.set_defaults(func=cmd_tasks_next)

    # tasks next-id
    p_nid = sub.add_parser("next-id", help="Preview next available emergent task ID")
    p_nid.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_nid.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_nid.set_defaults(func=cmd_tasks_next_id)

    # tasks set-priority
    p_sp = sub.add_parser("set-priority", help="Set priority for a task")
    p_sp.add_argument("id", help="Node ID")
    p_sp.add_argument("priority", help="Priority (P0, P1, P2, P3)")
    p_sp.add_argument("--reason", default=None, help="Priority reason (for emergent tasks)")
    p_sp.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_sp.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file hash")
    p_sp.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sp.set_defaults(func=cmd_set_priority)

    # tasks set-size
    p_ss = sub.add_parser("set-size", help="Set size for a task")
    p_ss.add_argument("id", help="Node ID")
    p_ss.add_argument("size", help="Size (XS, S, M, L, XL)")
    p_ss.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_ss.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file hash")
    p_ss.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_ss.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_ss.set_defaults(func=cmd_set_size)

    # tasks set-deps
    p_sd = sub.add_parser("set-deps", help="Set dependencies for a task")
    p_sd.add_argument("id", help="Node ID")
    p_sd.add_argument("deps", nargs="*", default=None, help="Dependency IDs (e.g. '06.8, 07.4')")
    p_sd.add_argument("--add", nargs="*", default=None, help="Add dependency IDs")
    p_sd.add_argument("--remove", nargs="*", default=None, help="Remove dependency IDs")
    p_sd.add_argument("--to", nargs="*", default=None, help="Set exact dependency IDs")
    p_sd.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_sd.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block hash")
    p_sd.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sd.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sd.set_defaults(func=cmd_set_deps)

    # tasks set-kind
    p_sk = sub.add_parser("set-kind", help="Set kind for a task")
    p_sk.add_argument("id", help="Node ID")
    p_sk.add_argument("kind", help="Kind value (feature, bug, fix, chore, docs, investigation)")
    p_sk.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_sk.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file hash")
    p_sk.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sk.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sk.set_defaults(func=cmd_set_kind)

    # tasks set-labels
    p_sl = sub.add_parser("set-labels", help="Set labels for a task")
    p_sl.add_argument("id", help="Node ID")
    p_sl.add_argument("--add", nargs="*", default=None, help="Add labels")
    p_sl.add_argument("--remove", nargs="*", default=None, help="Remove labels")
    p_sl.add_argument("--to", nargs="*", default=None, help="Set exact labels")
    p_sl.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_sl.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file hash")
    p_sl.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sl.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sl.set_defaults(func=cmd_set_labels)

    # tasks set-short
    p_sshort = sub.add_parser("set-short", help="Set short title (1-5 words, <=40 chars) for an item")
    p_sshort.add_argument("id", nargs="?", default=None, help="Node or item ID (e.g. T001, 08.1, Q004, UC001, N001)")
    p_sshort.add_argument("short", nargs="?", default=None, help="Short title (1-5 words, <=40 chars, no trailing punctuation)")
    p_sshort.add_argument("--from", dest="from_source", default=None, help="Path to JSON or pairs file, inline JSON string, or '-' for stdin")
    p_sshort.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_sshort.add_argument("--expect-task-hash", "--expect-plan-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file/plan hash")
    p_sshort.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sshort.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sshort.set_defaults(func=cmd_set_short)

    # tasks set-waiting-on
    p_swo = sub.add_parser("set-waiting-on", help="Set waiting-on qualifier for a task")
    p_swo.add_argument("id", help="Task ID (e.g. T001, 01.1)")
    p_swo.add_argument("waiting_on", help="Waiting-on qualifier (e.g. question:Q###, owner:..., external:..., session:...)")
    p_swo.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_swo.add_argument("--expect-task-hash", "--expect-plan-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file/plan hash")
    p_swo.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_swo.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_swo.set_defaults(func=cmd_set_waiting_on)

    # tasks set-executor
    p_se = sub.add_parser("set-executor", help="Set executor for a task")
    p_se.add_argument("id", help="Task ID (e.g. T001, 01.1)")
    p_se.add_argument("executor", help="Executor (e.g. kilo, claude, workspace:<ws-slug>, session:<name>)")
    p_se.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_se.add_argument("--expect-task-hash", "--expect-plan-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file/plan hash")
    p_se.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_se.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_se.set_defaults(func=cmd_set_executor)

    # tasks set-verify-by
    p_svb = sub.add_parser("set-verify-by", help="Set durable verification request target and optional check for a task")
    p_svb.add_argument("id", help="Task ID (e.g. T001, 01.1)")
    p_svb.add_argument("target", nargs="?", default=None, help="Target workspace or session (e.g. gcube_atlas, workspace:gcube_atlas, session:...)")
    p_svb.add_argument("--by", dest="by_target", default=None, help="Target workspace or session (alternative to positional target)")
    p_svb.add_argument("--check", default=None, help="What to check during verification")
    p_svb.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_svb.add_argument("--expect-task-hash", "--expect-plan-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file/plan hash")
    p_svb.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_svb.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_svb.set_defaults(func=cmd_set_verify_by)

    # tasks request-verification (alias for set-verify-by)
    p_req = sub.add_parser("request-verification", help="Request verification from a workspace or session (alias for set-verify-by)")
    p_req.add_argument("id", help="Task ID (e.g. T001, 01.1)")
    p_req.add_argument("target", nargs="?", default=None, help="Target workspace or session")
    p_req.add_argument("--by", dest="by_target", default=None, help="Target workspace or session")
    p_req.add_argument("--check", default=None, help="What to check during verification")
    p_req.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    p_req.add_argument("--expect-task-hash", "--expect-plan-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task block/file/plan hash")
    p_req.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_req.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_req.set_defaults(func=cmd_set_verify_by)

    # tasks verification-queue
    p_vq = sub.add_parser("verification-queue", help="List delivered tasks pending verification across workspaces or filtered by target")
    p_vq.add_argument("--for", dest="for_target", default=None, help="Filter to items whose verify_by matches target (e.g. gcube_atlas, workspace:gcube_atlas, session:...)")
    p_vq.add_argument("--workspace", default=None, help="Workspace slug, UUID, or path")
    p_vq.add_argument("--all-workspaces", action="store_true", default=False, help="Scan all registered workspaces")
    p_vq.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_vq.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_vq.set_defaults(func=cmd_verification_queue)

    # tasks labels
    p_lbls = sub.add_parser("labels", help="List all labels in use with their counts")
    p_lbls.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_lbls.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_lbls.set_defaults(func=cmd_labels)

    # tasks micro
    p_micro = sub.add_parser("micro", help="Create a lightweight microtask under tasks/micro/")
    p_micro.add_argument("--title", required=True, help="Microtask title")
    p_micro.add_argument("--kind", choices=sorted(VALID_KINDS), default="chore", help="Classification kind (default: chore)")
    p_micro.add_argument("--priority", choices=sorted(PRIORITIES), default="P2", help="Priority (default: P2)")
    p_micro.add_argument("--paths", default="-", help="Paths header value (default: -)")
    p_micro.add_argument("--depends-on", default="-", help="Dependencies (default: -)")
    p_micro.add_argument("--label", action="append", default=None, help="Label (repeatable or comma-separated)")
    p_micro.add_argument("--size", choices=sorted(VALID_SIZES), default=None, help="Size (default: XS)")
    p_micro.add_argument("--executor", default="kilo", help="Assigned executor (default: kilo)")
    p_micro.add_argument("--what", default=None, help="What section body")
    p_micro.add_argument("--short", default=None, help="Short title (1-5 words, <=40 chars); derived when omitted")
    p_micro.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_micro.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_micro.set_defaults(func=cmd_tasks_micro)

    # tasks promote
    p_prom = sub.add_parser("promote", help="Promote a microtask into a full emergent task in a chosen category")
    p_prom.add_argument("task_id", help="Microtask ID (e.g. T015)")
    p_prom.add_argument("--category", default=None, help="Target category (default: maintenance)")
    p_prom.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_prom.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_prom.set_defaults(func=cmd_tasks_promote)

    # use-cases (Spec 15)
    p_uc = sub.add_parser("use-cases", help="Manage use cases and recorded AI validations (Spec 15)")
    p_uc.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_uc.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    uc_sub = _instrument_subparsers(p_uc.add_subparsers(dest="uc_cmd", required=True))

    uc_list = uc_sub.add_parser("list", help="List use cases")
    uc_list.add_argument("--tasks-dir", default="tasks")
    uc_list.add_argument("--status", choices=["all", "draft", "active", "verified", "failing", "partial"], default="all")
    uc_list.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    uc_list.set_defaults(func=cmd_use_cases_list)

    uc_show = uc_sub.add_parser("show", help="Show use case detail")
    uc_show.add_argument("uc_id", help="Use case ID (e.g. UC001)")
    uc_show.add_argument("--tasks-dir", default="tasks")
    uc_show.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    uc_show.set_defaults(func=cmd_use_cases_show)

    uc_create = uc_sub.add_parser("create", help="Create or update a use case")
    uc_create.add_argument("--id", required=True, help="Use case ID (e.g. UC001)")
    uc_create.add_argument("--title", required=True, help="Use case title")
    uc_create.add_argument("--actor", default="End-User", help="Primary actor / persona")
    uc_create.add_argument("--status", choices=list(USE_CASE_STATUSES), default="draft")
    uc_create.add_argument("--priority", choices=list(PRIORITIES), default="P1")
    uc_create.add_argument("--linked-tasks", default="", help="Comma-separated task IDs")
    uc_create.add_argument("--verification-type", choices=list(USE_CASE_VERIFICATION_TYPES), default="automated-probe")
    uc_create.add_argument("--verification-command", default="")
    uc_create.add_argument("--description", default="")
    uc_create.add_argument("--preconditions", default="")
    uc_create.add_argument("--scenario", default="")
    uc_create.add_argument("--short", default=None, help="Short title (1-5 words, <=40 chars); derived when omitted")
    uc_create.add_argument("--tasks-dir", default="tasks")
    uc_create.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    uc_create.set_defaults(func=cmd_use_cases_create)

    uc_rec = uc_sub.add_parser("record-validation", help="Record an AI validation result on a use case")
    uc_rec.add_argument("uc_id", help="Use case ID (e.g. UC001)")
    uc_rec.add_argument("--verdict", choices=["pass", "fail", "partial"], required=True)
    uc_rec.add_argument("--summary", required=True, help="Summary of validation findings")
    uc_rec.add_argument("--evidence", default="", help="Execution evidence / output snippet")
    uc_rec.add_argument("--gaps", default="", help="Semicolon-separated list of gaps found")
    uc_rec.add_argument("--actor", default="ai-validator", help="Validating agent name / model")
    uc_rec.add_argument("--tasks-dir", default="tasks")
    uc_rec.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    uc_rec.set_defaults(func=cmd_use_cases_record_validation)

    uc_val = uc_sub.add_parser("validate", help="Run automated probe/validation on a use case")
    uc_val.add_argument("uc_id", help="Use case ID (e.g. UC001)")
    uc_val.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")
    uc_val.add_argument("--actor", default="automated-probe")
    uc_val.add_argument("--tasks-dir", default="tasks")
    uc_val.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    uc_val.set_defaults(func=cmd_use_cases_validate)

    uc_camp = uc_sub.add_parser("campaign", help="Run full product validation campaign across all use cases")
    uc_camp.add_argument("--filter-actor", default=None, help="Filter by actor")
    uc_camp.add_argument("--timeout", type=int, default=60, help="Timeout in seconds per probe")
    uc_camp.add_argument("--actor", default="campaign-runner")
    uc_camp.add_argument("--tasks-dir", default="tasks")
    uc_camp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    uc_camp.set_defaults(func=cmd_use_cases_campaign)

    # tasks step
    p_step = sub.add_parser("step", help="Checklist commands for ## Steps of an emergent task")
    p_step.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_step.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    step_sub = _instrument_subparsers(p_step.add_subparsers(dest="step_cmd", required=True))

    # step list
    p_sl = step_sub.add_parser("list", help="List checklist items in ## Steps of a task")
    p_sl.add_argument("task_id", help="Task ID (e.g. T001)")
    p_sl.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sl.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sl.set_defaults(func=cmd_tasks_step_list)

    # step add
    p_sa = step_sub.add_parser("add", help="Add a checklist item to ## Steps of a task")
    p_sa.add_argument("task_id", help="Task ID (e.g. T001)")
    p_sa.add_argument("text", help="Step text to add")
    p_sa.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task bundle SHA256")
    p_sa.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sa.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sa.set_defaults(func=cmd_tasks_step_add)

    # step check
    p_sc = step_sub.add_parser("check", help="Mark a step in ## Steps as checked (- [x])")
    p_sc.add_argument("task_id", help="Task ID (e.g. T001)")
    p_sc.add_argument("target", metavar="index-or-substring", help="1-based step index or substring to match")
    p_sc.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task bundle SHA256")
    p_sc.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_sc.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_sc.set_defaults(func=cmd_tasks_step_check)

    # step uncheck
    p_suc = step_sub.add_parser("uncheck", help="Mark a step in ## Steps as unchecked (- [ ])")
    p_suc.add_argument("task_id", help="Task ID (e.g. T001)")
    p_suc.add_argument("target", metavar="index-or-substring", help="1-based step index or substring to match")
    p_suc.add_argument("--expect-task-hash", "--expect-hash", dest="expect_task_hash", default=None, help="Expected task bundle SHA256")
    p_suc.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_suc.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_suc.set_defaults(func=cmd_tasks_step_uncheck)

    # feedback (T034)
    p_fb = sub.add_parser("feedback", help="Report tooling needs, defects, or improvements")
    p_fb.add_argument("--kind", choices=["bug", "feature", "idea", "request"], default=None, help="Kind of feedback")
    p_fb.add_argument("--title", default=None, help="Short title of the feedback")
    p_fb.add_argument("--body", default=None, help="Body text (what, where, expected vs actual)")
    p_fb.add_argument("--body-file", default=None, help="Path to file containing body Markdown")
    p_fb.add_argument("--short", default=None, help="Short title (1-5 words, <=40 chars); derived when omitted")
    p_fb.add_argument("--author", default=None, help="Author name")
    p_fb.add_argument("--about", default="-", help="About paths, repos or task IDs")
    p_fb.add_argument("--dry-run", action="store_true", default=False, help="Print target and note without writing")
    p_fb.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")

    fb_sub = _instrument_subparsers(p_fb.add_subparsers(dest="feedback_cmd"))
    p_flush = fb_sub.add_parser("flush", help="Move queued feedback notes into configured tasks tree")
    p_flush.add_argument("--dry-run", action="store_true", default=False, help="Print notes that would be flushed")
    p_flush.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_flush.set_defaults(func=cmd_feedback_flush)

    p_fb.set_defaults(func=cmd_feedback)

    return ap


IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


def is_mutating_command(args: argparse.Namespace) -> bool:
    cmd = getattr(args, "cmd", None)
    if not cmd:
        return False
    if cmd == "feedback":
        return False
    if cmd == "sync-index":
        return bool(getattr(args, "apply", False))
    if cmd in ("list", "validate", "graph", "next", "labels", "next-id", "verification-queue"):
        return False
    if cmd == "questions":
        q_cmd = getattr(args, "q_cmd", None)
        return q_cmd in ("ask", "answer", "withdraw", "apply")
    if cmd == "inbox":
        inbox_cmd = getattr(args, "inbox_cmd", None)
        return inbox_cmd in ("add", "edit", "attach", "detach", "resolve", "discard", "reopen")
    if cmd == "use-cases":
        uc_cmd = getattr(args, "uc_cmd", None)
        return uc_cmd in ("create", "record-validation")
    if cmd == "child":
        child_cmd = getattr(args, "child_cmd", None)
        return child_cmd == "add"
    if cmd == "step":
        step_cmd = getattr(args, "step_cmd", None)
        return step_cmd in ("add", "check", "uncheck")
    if cmd in (
        "close",
        "transition",
        "new",
        "attach",
        "detach",
        "expand",
        "collapse",
        "reopen",
        "ship",
        "archive",
        "set-priority",
        "set-size",
        "set-deps",
        "set-kind",
        "set-labels",
        "set-short",
        "set-waiting-on",
        "set-executor",
        "set-verify-by",
        "request-verification",
        "micro",
        "promote",
        "upgrade",
    ):
        return True
    return False


def get_canonical_args(args: argparse.Namespace) -> dict[str, Any]:
    ignored = {"idempotency_key", "json", "func", "_last_result"}
    out: dict[str, Any] = {}
    for k, v in sorted(vars(args).items()):
        if k in ignored or k.startswith("_"):
            continue
        if isinstance(v, pathlib.Path):
            out[k] = str(v.resolve())
        elif isinstance(v, (set, list, tuple)):
            out[k] = [str(x.resolve()) if isinstance(x, pathlib.Path) else x for x in v]
        else:
            out[k] = v
    return out


def dispatch_command(args: argparse.Namespace) -> int:
    is_json = bool(getattr(args, "json", False) or "--json" in sys.argv)
    if is_mutating_command(args):
        # 1. Broker singleton guard (exit 75 if broker holds lock unless AI_ORCH_BROKER_CHILD is set)
        b_status = _get_broker_status()
        if b_status is not None and getattr(b_status, "held", False) and not os.environ.get("AI_ORCH_BROKER_CHILD"):
            pid = getattr(b_status, "pid", None)
            pid_alive = bool(getattr(b_status, "pid_alive", False))
            if pid is not None and not pid_alive:
                pass
            elif pid_alive and getattr(b_status, "port", None):
                ret = _try_forward_to_live_broker(b_status, is_json)
                if ret is not None:
                    return ret
            else:
                live_pid = getattr(b_status, "live_pid", None)
                if live_pid is None and pid is not None and _is_pid_alive(pid):
                    live_pid = pid
                pid_str = str(live_pid) if live_pid is not None else "unknown"
                err_msg = f"route through the broker (MCP) \u2014 it is running as pid {pid_str}"
                payload = {
                    "ok": False,
                    "error": "broker-owns-writes",
                    "message": err_msg,
                }
                if is_json:
                    print(json.dumps(payload, indent=2))
                else:
                    print(f"[FAIL] broker-owns-writes: {err_msg}", file=sys.stderr)
                return 75

        # 2. Idempotency key handling
        idemp_key = getattr(args, "idempotency_key", None)
        if idemp_key is not None and str(idemp_key).strip():
            key = str(idemp_key).strip()
            if not IDEMPOTENCY_KEY_RE.match(key):
                err_payload = {
                    "ok": False,
                    "error": "invalid-idempotency-key",
                    "message": f"Idempotency key {key!r} is invalid; must match '^[A-Za-z0-9_.:-]{{8,128}}$'.",
                }
                if is_json:
                    print(json.dumps(err_payload, indent=2))
                else:
                    print(f"[FAIL] invalid-idempotency-key: {err_payload['message']}", file=sys.stderr)
                return 2

            tasks_dir = pathlib.Path(getattr(args, "tasks_dir", "tasks")).resolve()
            project_root = _resolve_workspace_from_tasks_dir(tasks_dir)
            idemp_dir = project_root / ".ai-orchestration" / "idempotency"
            idemp_dir.mkdir(parents=True, exist_ok=True)
            key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
            idemp_file = idemp_dir / f"{key_hash}.json"
            canonical_args = get_canonical_args(args)

            with task_write_lock(tasks_dir):
                if idemp_file.is_file():
                    try:
                        stored_data = json.loads(idemp_file.read_text(encoding="utf-8"))
                    except Exception:
                        stored_data = {}

                    if stored_data.get("canonical_args") != canonical_args:
                        err_payload = {
                            "ok": False,
                            "error": "idempotency-key-reused",
                            "message": f"Idempotency key {key!r} already used with different arguments.",
                        }
                        if is_json:
                            print(json.dumps(err_payload, indent=2))
                        else:
                            print(f"[FAIL] idempotency-key-reused: {err_payload['message']}", file=sys.stderr)
                        return 2

                    stored_result = stored_data.get("result", {})
                    stored_exit_code = stored_data.get("exit_code", 0)
                    stored_stdout = stored_data.get("stdout", "")
                    if is_json:
                        print(json.dumps(stored_result, indent=2))
                    else:
                        if stored_stdout:
                            sys.stdout.write(stored_stdout)
                        else:
                            print(json.dumps(stored_result, indent=2))
                    return stored_exit_code

                # First call: execute under the same lock
                stdout_buf = io.StringIO()
                with contextlib.redirect_stdout(stdout_buf):
                    exit_code = args.func(args)
                captured_stdout = stdout_buf.getvalue()
                sys.stdout.write(captured_stdout)

                result_json = None
                last_res = getattr(args, "_last_result", None)
                if isinstance(last_res, dict):
                    result_json = last_res
                else:
                    try:
                        result_json = json.loads(captured_stdout)
                    except Exception:
                        result_json = {"stdout": captured_stdout, "exit_code": exit_code}

                record = {
                    "key": key,
                    "canonical_args": canonical_args,
                    "created_at": time.time(),
                    "exit_code": exit_code,
                    "result": result_json,
                    "stdout": captured_stdout,
                }
                idemp_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

                # Prune records older than 7 days on write
                now = time.time()
                seven_days = 7 * 86400
                try:
                    for p in idemp_dir.glob("*.json"):
                        if p.name != idemp_file.name:
                            try:
                                if now - p.stat().st_mtime > seven_days:
                                    p.unlink(missing_ok=True)
                            except OSError:
                                pass
                except Exception:
                    pass

                return exit_code

    return args.func(args)


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    sys.exit(dispatch_command(args))


if __name__ == "__main__":
    main()
