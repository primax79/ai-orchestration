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
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterator

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

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
RESERVED_DIRS: set[str] = {"_inbox", "_reviews", "specs", "done", "merged", "notes", "reviews", "questions"}

QUESTION_HEADER_FIELDS: tuple[str, ...] = (
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

QUESTION_STATUSES: set[str] = {"open", "answered", "withdrawn"}
QUESTION_ID_RE = re.compile(r"^Q\d{3,}$")
QUESTION_FILE_RE = re.compile(r"^(Q\d{3,})-([a-z0-9-]+)\.md$")
OPTION_LINE_RE = re.compile(r"^-\s+\*\*([A-Za-z0-9]+)\*\*\s+[—–-]\s+(.+?)(?::\s*(.*))?$")

NOTE_HEADER_FIELDS: tuple[str, ...] = (
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
NOTE_KINDS: set[str] = {"note", "bug", "idea", "request", "question"}
NOTE_STATUSES: set[str] = {"draft", "ready", "processing", "processed", "discarded"}
NOTE_ID_RE = re.compile(r"^N\d{3,}$")
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS_PER_NOTE = 20

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
    task_dict = {
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
        "",
        "## Context",
        "",
        norm_context,
        "",
        "## Options",
        "",
    ]
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

    return {
        "id": headers.get("id", ""),
        "question": headers.get("question", ""),
        "status": headers.get("status", ""),
        "blocks": blocks_raw,
        "blocks_parsed": blocks_parsed,
        "decider": headers.get("decider", ""),
        "asked_by": headers.get("asked-by", ""),
        "asked": headers.get("asked", ""),
        "origin_run": headers.get("origin-run", ""),
        "open_answer": headers.get("open-answer", ""),
        "recommended": headers.get("recommended", ""),
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
    questions: list[dict[str, Any]] = []
    for entry in sorted(questions_dir.iterdir()):
        if entry.is_file() and entry.suffix == ".md" and QUESTION_ID_RE.match(entry.name.split("-")[0]):
            try:
                q = parse_question_file(entry, tasks_dir)
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
            if tid == task_id and prior_state and prior_state != "waiting" and prior_state in CANONICAL_STATES:
                return prior_state
    return "open"


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
            scanned_lines, _ = scan_markdown_blocks(text)
            h1_match = next((sline.text[2:].strip() for sline in scanned_lines if not sline.is_fenced and sline.text.startswith("# ")), None)
            title = h1_match if h1_match else entry.name

            # Determine initiative status
            if location in ("merged", "done") or (entry / "summary.md").is_file():
                init_status = "done"
            elif num in index_statuses:
                init_status = index_statuses[num]
            else:
                status_m = None
                for sline in scanned_lines:
                    if not sline.is_fenced:
                        sm = re.search(r"^\s*>\s*\*\*Status:\*\*\s*([^\n·]+)", sline.text, re.IGNORECASE)
                        if sm:
                            status_m = sm
                            break
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

            inline_tasks = []
            for sline in scanned_lines:
                if not sline.is_fenced:
                    tm = INLINE_TASK_HEADING_RE.match(sline.text)
                    if tm:
                        inline_tasks.append({"id": tm.group(1), "title": tm.group(2).strip(), "state": init_status})

            # Also check table tasks in plan.md (e.g. | **T1** | **Title**: desc |)
            table_tasks = []
            for sline in scanned_lines:
                if not sline.is_fenced:
                    tm = re.match(r"^\|\s*\*\*(T\w+|\d+\.\d+)\*\*\s*\|\s*(.+?)\s*\|", sline.text)
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
                    "bundle_sha256": _file_sha256(plan_path),
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

        # Legacy decider warning
        raw_dec = task.get("decider", "").strip()
        if raw_dec and raw_dec != "-":
            if not re.match(r"^Q\d{3,}(?:,\s*Q\d{3,})*$", raw_dec):
                warnings.append(
                    f"{rel}: legacy free-text decider {raw_dec!r}; "
                    f"consider converting with 'questions ask --from-task {tid}'."
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

    if questions_dir.is_dir():
        for q_entry in sorted(questions_dir.iterdir()):
            if q_entry.name.startswith(".") or not q_entry.is_file() or q_entry.suffix != ".md":
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
            missing_q_hdr = [k for k in QUESTION_HEADER_FIELDS if k not in keys]
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
            expected_sections = ["## Context", "## Options", "## Answer"]
            if q["sections_present"] != expected_sections:
                errors.append(
                    f"{q_rel}: sections must be exactly {expected_sections} in order; got {q['sections_present']}."
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

            # Blocks & status consistency
            for tid, prior_st in q["blocks_parsed"]:
                if not EMERGENT_ID_RE.match(tid):
                    errors.append(f"{q_rel}: invalid task ID {tid!r} in blocks (must be format T###).")
                elif tid not in emergent_map:
                    errors.append(f"{q_rel}: blocked task {tid!r} not found in tasks tree.")
                else:
                    target_task = emergent_map[tid]
                    target_st = target_task["canonical_state"]
                    target_dec = target_task.get("decider", "")
                    if st == "open":
                        if target_st != "waiting":
                            errors.append(
                                f"{q_rel}: question is 'open' but blocked task {tid!r} is in state {target_task['state']!r} (expected 'waiting')."
                            )
                        if qid and qid not in re.findall(r"Q\d{3,}", target_dec):
                            errors.append(
                                f"{q_rel}: question is 'open' but task {tid!r} decider {target_dec!r} does not reference {qid}."
                            )
                    else:
                        target_dec_qids = re.findall(r"Q\d{3,}", target_dec)
                        if target_st != "waiting" and qid in target_dec_qids:
                            errors.append(
                                f"{q_rel}: question is resolved ({st}) and task {tid!r} is '{target_task['state']}', but task decider still references {qid}."
                            )

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
    decider: str | None = None,
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
        elif key == "decider" and decider is not None:
            lines[header_end] = f"- decider: {decider}"
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


def transition_task(
    tasks_dir: pathlib.Path,
    task_id: str,
    new_state: str,
    actor: str | None = None,
    verifier: str | None = None,
    reason: str | None = None,
    expect_task_hash: str | None = None,
    force_unblock: bool = False,
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
                decider=decider_to_set,
                clear_next_up=is_terminal,
            )
            _append_progress_log(target, old_state, effective_state, actor, verifier, reason)

            final_path = file_path
            if is_terminal and not target["in_done"]:
                final_path = _move_task_to_done(target, tasks_dir)

            new_bundle_hash = task_bundle_sha256(final_path)
            return True, {
                "ok": True,
                "task_id": task_id,
                "old_state": old_state,
                "new_state": effective_state,
                "verifier": verifier or target.get("verifier"),
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

    all_questions = discover_questions(tasks_dir)
    open_questions = [q for q in all_questions if q["status"] == "open"]
    open_questions.sort(key=lambda q: int(q["id"][1:]) if QUESTION_ID_RE.match(q["id"]) else 0)

    # Determine whether to use 5-column table (open questions or existing 5-col table)
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

    # Render open question rows first
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
            if not line_s.startswith("|"):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            if not cells or cells[0] in ("Key", "Task", "Task / Initiative", "---") or cells[0].startswith("---"):
                continue
            if cells[0] != "-":
                existing_dec_rows.append((cells[0], cells))

    # Only tasks in state waiting or blocked with a non-question decider belong in legacy decisions
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
            if len(cells) >= 4 and re.match(r"^T\d+$", cells[0]):
                tid, st = cells[0], cells[3]
                if normalize_state(st) in ("waiting", "blocked") and tid not in [r[0] for r in existing_dec_rows]:
                    existing_waiting_ids_without_dec.add(tid)

    seen_dec_ids: set[str] = set()

    # 1. Existing legacy rows in original order
    for row_id, cells in existing_dec_rows:
        if row_id.startswith("Q") or row_id.startswith("[Q"):
            # Question rows handled above from live question files
            continue
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
            if use_5_cols:
                dec_lines.append(f"| {row_id} | {q_cell} | {blocks_str} | {who} | - |")
            else:
                dec_lines.append(f"| {row_id} | {q_cell} | {who} | {blocks_str} |")
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
                dec_lines.append(f"| {task_cell} | {q_cell} | {blk_cell} | {dec_cell} | - |")
            else:
                dec_lines.append(f"| {task_cell} | {q_cell} | {dec_cell} | {blk_cell} |")

    # 2. Append new qualifying legacy tasks
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
            dec_lines.append(f"| {wt['id']} | {question} | {blocks_str} | {who} | - |")
        else:
            dec_lines.append(f"| {wt['id']} | {question} | {who} | {blocks_str} |")

    if len(dec_lines) == 2:
        if use_5_cols:
            dec_lines.append("| - | None. | - | - | - |")
        else:
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
                    "bundle_sha256": init.get("bundle_sha256") or _file_sha256(tasks_dir / init["rel_path"]),
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
                    "bundle_sha256": init.get("bundle_sha256") or _file_sha256(tasks_dir / init["rel_path"]),
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
    expect_task_hash = getattr(args, "expect_task_hash", None)
    force_unblock = getattr(args, "force_unblock", False)
    ok, payload = transition_task(
        tasks_dir=tasks_dir,
        task_id=args.task_id,
        new_state=args.new_state,
        actor=args.actor,
        verifier=args.verifier,
        reason=args.reason,
        expect_task_hash=expect_task_hash,
        force_unblock=force_unblock,
    )
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
    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if not is_platform_supported():
        return {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
            "upgraded_files": [],
            "emergent_count": 0,
            "initiative_count": 0,
            "errors": ["unsupported-platform: Mutating commands are unsupported on Windows"],
            "warnings": [],
        }

    try:
        with task_write_lock(tasks_dir):
            upgraded_files: list[str] = []

            # 1. Update tasks/AGENTS.md
            agents_md = tasks_dir / "AGENTS.md"
            existing_agents = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else ""
            if existing_agents.strip() != CANONICAL_TASKS_AGENTS_MD.strip():
                _atomic_write_text(agents_md, CANONICAL_TASKS_AGENTS_MD, encoding="utf-8")
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
    except LockTimeoutError as e:
        return {
            "ok": False,
            "error": "lock-timeout",
            "message": str(e),
            "upgraded_files": [],
            "emergent_count": 0,
            "initiative_count": 0,
            "errors": [f"lock-timeout: {e}"],
            "warnings": [],
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
                    return False, {"ok": False, "error": "Missing required --blocks."}

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
                blocks_list = [] if blocks.strip() == "-" else [b.strip() for b in blocks.split(",") if b.strip()]
                for b in blocks_list:
                    bm = re.match(r"^(T\d{3,})", b)
                    if not bm:
                        return False, {"ok": False, "error": f"Invalid task ID {b!r} in blocks (must be T###)."}
                    tid = bm.group(1)
                    if tid not in emergent_map:
                        return False, {"ok": False, "error": f"Blocked task {tid!r} not found in tasks tree."}
                    t = emergent_map[tid]
                    cstate = t["canonical_state"]

                    if cstate in TERMINAL_STATES:
                        return False, {"ok": False, "error": f"Cannot block task {tid!r} in terminal state '{cstate}'."}
                    if cstate in ("waiting", "blocked"):
                        raw_dec = t.get("decider", "").strip()
                        if cstate == "waiting" and re.match(r"^Q\d{3,}(?:,\s*Q\d{3,})*$", raw_dec):
                            tasks_to_update.append((t, "waiting", "APPEND"))
                            blocks_entries.append(f"{tid} (waiting)")
                        else:
                            return False, {
                                "ok": False,
                                "error": f"Asking against task {tid!r} waiting/blocked for a non-question reason is refused.",
                            }
                    elif cstate in ("open", "in progress"):
                        tasks_to_update.append((t, "waiting", "SET"))
                        blocks_entries.append(f"{tid} ({cstate})")
                    else:
                        return False, {"ok": False, "error": f"Cannot block task {tid!r} in state '{t['state']}'."}

            created_files: list[pathlib.Path] = []
            modified_files: dict[pathlib.Path, str] = {}
            for t, _, _ in tasks_to_update:
                tp = pathlib.Path(t["file_path"])
                if tp not in modified_files:
                    modified_files[tp] = tp.read_text(encoding="utf-8")
                if t["is_folder"]:
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
                )
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)

                # Update tasks
                for t, new_st, dec_mode in tasks_to_update:
                    tp = pathlib.Path(t["file_path"])
                    if dec_mode == "SET":
                        new_dec = q_id
                    else:
                        new_dec = f"{t['decider']}, {q_id}"
                    _update_task_file_headers_and_state(tp, new_st, decider=new_dec)
                    _append_progress_log(
                        t,
                        t["state"],
                        new_st,
                        asked_by,
                        verifier=None,
                        reason=f"Blocked by question {q_id}",
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
                )
                _atomic_write_text(q_file, new_q_content)

                q_status_map = {q["id"]: q["status"] for q in questions}
                q_status_map[question_id] = "answered"

                unblocked: list[str] = []
                for tid, _ in target_q["blocks_parsed"]:
                    if tid not in emergent_map:
                        continue
                    t = emergent_map[tid]
                    tp = pathlib.Path(t["file_path"])
                    t_dec = t.get("decider", "").strip()
                    linked_qids = [qid.strip() for qid in t_dec.split(",") if qid.strip()]

                    all_resolved = all(q_status_map.get(qid) in ("answered", "withdrawn") for qid in linked_qids)
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

                return True, {
                    "ok": True,
                    "id": question_id,
                    "status": "answered",
                    "choice": choice,
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
                for tid, _ in target_q["blocks_parsed"]:
                    if tid not in emergent_map:
                        continue
                    t = emergent_map[tid]
                    tp = pathlib.Path(t["file_path"])
                    t_dec = t.get("decider", "").strip()
                    linked_qids = [qid.strip() for qid in t_dec.split(",") if qid.strip()]

                    all_resolved = all(q_status_map.get(qid) in ("answered", "withdrawn") for qid in linked_qids)
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

    filtered = questions
    if status != "all":
        filtered = [q for q in filtered if q["status"] == status]
    if blocks:
        filtered = [q for q in filtered if any(tid == blocks for tid, _ in q["blocks_parsed"])]

    def _sort_key(q: dict[str, Any]) -> tuple[int, int]:
        is_open = 0 if q["status"] == "open" else 1
        num = int(q["id"][1:]) if QUESTION_ID_RE.match(q["id"]) else 0
        return (is_open, -num)

    filtered.sort(key=_sort_key)
    return True, {"ok": True, "questions": filtered}


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
            print(f"\nContext:\n{q['context']}")
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
    ok, res = answer_question(
        tasks_dir=tasks_dir,
        question_id=args.question_id,
        choice=args.choice,
        text=args.text,
        by=args.by,
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            unb = ", ".join(res["unblocked_tasks"]) if res["unblocked_tasks"] else "none"
            print(f"[ok] Answered {res['id']} with choice {res['choice']!r} (unblocked tasks: {unb})")
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


def sanitize_attachment_name(stem: str, ext: str, index: int) -> str:
    """Sanitize attachment name to <NN>-<clean><ext> (lowercase, [a-z0-9._-], max 60 chars)."""
    nn = f"{index:02d}"
    clean = re.sub(r"[^a-z0-9._-]+", "-", stem.lower()).strip("-._")
    if not clean:
        clean = "image"
    max_stem_len = 60 - len(nn) - 1 - len(ext)
    clean = clean[:max_stem_len].rstrip("-._")
    if not clean:
        clean = "img"
    return f"{nn}-{clean}{ext}"


def validate_attachment_name(name: str, attachments_dir: pathlib.Path) -> pathlib.Path:
    """Validate attachment name against path traversal and return resolved path."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
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
        "",
    ]
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
    attachments: list[str] = []
    if attachments_dir.is_dir():
        for f in sorted(attachments_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                attachments.append(f.name)

    note_id = headers.get("id", "")
    title = headers.get("title", "")
    if not title and h1_text:
        parts = h1_text.split(None, 1)
        if len(parts) > 1 and NOTE_ID_RE.match(parts[0]):
            title = parts[1].strip()
        else:
            title = h1_text

    bundle_hash = _folder_bundle_sha256(folder_path)

    return {
        "id": note_id,
        "title": title,
        "kind": headers.get("kind", "note"),
        "status": headers.get("status", "draft"),
        "created": headers.get("created", ""),
        "author": headers.get("author", "owner"),
        "about": headers.get("about", "-"),
        "produced": headers.get("produced", "-"),
        "processed_by": headers.get("processed-by", "-"),
        "body": body,
        "attachments": attachments,
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
        "kind": "note",
        "status": status,
        "created": created,
        "author": "owner",
        "about": "-",
        "produced": "-",
        "processed_by": "-",
        "body": text.strip(),
        "attachments": [],
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
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

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
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
            except BaseException:
                if folder_path and folder_path.exists():
                    shutil.rmtree(folder_path, ignore_errors=True)
                raise

            parsed = parse_note_folder(folder_path, tasks_dir, in_analyzed=False)
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
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    src = pathlib.Path(file_path).resolve()
    if not src.is_file():
        return False, {"ok": False, "error": f"Attachment file not found: {file_path}"}

    data = src.read_bytes()
    if len(data) > MAX_ATTACHMENT_SIZE:
        return False, {
            "ok": False,
            "error": "size-limit-exceeded",
            "message": f"Attachment exceeds 10 MB limit ({len(data)} bytes).",
        }

    sniff = sniff_image_type(data, original_suffix=src.suffix)
    if sniff is None:
        return False, {
            "ok": False,
            "error": "invalid-image-type",
            "message": "File is not a supported image (magic bytes do not match png, jpeg, gif, or webp).",
        }
    img_type, real_ext = sniff

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

            attachments_dir = folder_path / "attachments"
            attachments_dir.mkdir(parents=True, exist_ok=True)

            existing_files = [f.name for f in attachments_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
            if len(existing_files) >= MAX_ATTACHMENTS_PER_NOTE:
                return False, {
                    "ok": False,
                    "error": "attachment-limit-reached",
                    "message": f"Note {note['id']} already has the maximum allowed attachments (20).",
                }

            existing_nums = [
                int(m.group(1)) for f in existing_files if (m := re.match(r"^(\d{2})-", f))
            ]
            next_idx = max(existing_nums, default=0) + 1

            stem = name if name else src.stem
            dest_filename = sanitize_attachment_name(stem, real_ext, next_idx)
            dest_path = attachments_dir / dest_filename

            shutil.copy2(src, dest_path)

            markdown_ref = f"![](attachments/{dest_filename})"
            updated = parse_note_folder(folder_path, tasks_dir, in_analyzed=note["in_analyzed"])

            return True, {
                "ok": True,
                "id": updated["id"],
                "attachment": dest_filename,
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

            attachments_dir = folder_path / "attachments"
            try:
                target_file = validate_attachment_name(name, attachments_dir)
            except (ValueError, FileNotFoundError) as ve:
                return False, {"ok": False, "error": "invalid-attachment", "message": str(ve)}

            target_file.unlink()
            updated = parse_note_folder(folder_path, tasks_dir, in_analyzed=note["in_analyzed"])

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


def tasks_new_from_note(
    tasks_dir: pathlib.Path,
    from_note: str,
    category: str,
    title: str,
    priority: str = "P2",
    priority_reason: str | None = None,
    executor: str = "kilo",
    next_up: str = "no",
    depends_on: str = "-",
    decider: str = "-",
) -> tuple[bool, dict[str, Any]]:
    if not is_platform_supported():
        return False, {
            "ok": False,
            "error": "unsupported-platform",
            "message": "Mutating commands are unsupported on Windows (requires fcntl for flock).",
        }

    tasks_dir = pathlib.Path(tasks_dir).resolve()
    if not from_note or not from_note.strip():
        return False, {"ok": False, "error": "Missing required --from-note."}
    if not category or not category.strip():
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
            note = find_inbox_note(tasks_dir, from_note)
            if not note:
                return False, {"ok": False, "error": f"Inbox note {from_note!r} not found."}

            emergent = discover_emergent_tasks(tasks_dir)
            existing_nums = []
            for t in emergent:
                tid = t.get("id", "")
                if tid and TASK_ID_RE.match(tid):
                    existing_nums.append(int(tid[1:]))

            next_num = max(existing_nums, default=0) + 1

            category_dir = tasks_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)

            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50].rstrip("-") or "task"

            fd = None
            t_id = ""
            filename = ""
            task_file_path = None

            while True:
                t_id = f"T{next_num:03d}"
                filename = f"{t_id}-{slug}.md"
                task_file_path = category_dir / filename
                try:
                    fd = os.open(str(task_file_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    break
                except FileExistsError:
                    next_num += 1

            p_reason = (
                priority_reason.strip()
                if priority_reason and priority_reason.strip()
                else f"Derived from inbox note {note['id'] if note['id'] != '-' else from_note}"
            )

            sources = note["rel_path"]
            paths = note["about"].strip() if note["about"] and note["about"].strip() != "-" else "-"
            handoff = f"Read tasks/{category}/{filename}, do the open steps, run the Verification, update the task and the registry."

            body = note.get("body", "").strip()
            paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
            goal = paragraphs[0] if paragraphs else f"Goal derived from inbox note {from_note}."

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

## Goal

{goal}

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
"""
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(task_content)
            except BaseException:
                if task_file_path and task_file_path.exists():
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
                return False, {"ok": False, "error": f"Created task failed validation: {'; '.join(task_errors)}"}

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
        print(f"Attachments ({len(note['attachments'])}): {', '.join(note['attachments']) if note['attachments'] else 'none'}")
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
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Detached {res['detached']} from note {res['id']}")
        else:
            print(f"[FAIL] {res.get('error') or res.get('message', 'inbox detach failed')}", file=sys.stderr)
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
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if ok:
            print(f"[ok] Created task {res['id']}: {res['rel_path']}")
        else:
            print(f"[FAIL] {res.get('error', 'tasks new failed')}", file=sys.stderr)
    return 0 if ok else 1


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
    p_tr.add_argument("--expect-task-hash", default=None, help="Refuse to transition if task bundle SHA256 does not match this hash")
    p_tr.add_argument("--force-unblock", action="store_true", help="Force move task out of waiting, withdrawing open questions with --reason")
    p_tr.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_tr.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_tr.set_defaults(func=cmd_transition)

    p_q = sub.add_parser("questions", help="Manage blocking question files (Q###) and task decision linkage")
    p_q.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_q.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    q_sub = p_q.add_subparsers(dest="q_cmd", required=True)

    # questions list
    p_ql = q_sub.add_parser("list", help="List blocking questions")
    p_ql.add_argument("--status", choices=["open", "answered", "withdrawn", "all"], default="all")
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
    p_qa.add_argument("--blocks", default=None, help="Comma-separated blocked task IDs (e.g. T013, T014)")
    p_qa.add_argument("--decider", default="owner", help="Decider role or person")
    p_qa.add_argument("--asked-by", default="owner", help="Who asked the question")
    p_qa.add_argument("--origin-run", default="-", help="Origin run ID or -")
    p_qa.add_argument("--from-task", default=None, help="Convert legacy decider header from task T###")
    p_qa.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_qa.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_qa.set_defaults(func=cmd_questions_ask)

    # questions answer
    p_qans = q_sub.add_parser("answer", help="Answer a blocking question")
    p_qans.add_argument("question_id", help="Question ID (e.g. Q001)")
    p_qans.add_argument("--choice", required=True, help="Selected option label or 'open'")
    p_qans.add_argument("--text", default=None, help="Free-text answer")
    p_qans.add_argument("--by", default="owner", help="Who answered the question")
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

    p_inbox = sub.add_parser("inbox", help="Manage inbox draft notes, image attachments, and triage")
    p_inbox.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_inbox.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    inbox_sub = p_inbox.add_subparsers(dest="inbox_cmd", required=True)

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
    p_iatt = inbox_sub.add_parser("attach", help="Attach an image to an inbox note")
    p_iatt.add_argument("note_id", help="Note ID (e.g. N001)")
    p_iatt.add_argument("--file", required=True, help="Path to image file (png, jpeg, gif, webp; <=10MB)")
    p_iatt.add_argument("--name", default=None, help="Custom attachment name/stem")
    p_iatt.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_iatt.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_iatt.set_defaults(func=cmd_inbox_attach)

    # inbox detach
    p_idet = inbox_sub.add_parser("detach", help="Detach an attachment from an inbox note")
    p_idet.add_argument("note_id", help="Note ID (e.g. N001)")
    p_idet.add_argument("--name", required=True, help="Attachment filename to detach")
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

    # tasks new
    p_new = sub.add_parser("new", help="Create a new task from an inbox note")
    p_new.add_argument("--from-note", required=True, help="Source inbox note ID (e.g. N001) or filename")
    p_new.add_argument("--category", required=True, help="Category folder name")
    p_new.add_argument("--title", required=True, help="Task title")
    p_new.add_argument("--priority", choices=sorted(PRIORITIES), default="P2", help="Priority (default P2)")
    p_new.add_argument("--priority-reason", default=None, help="Priority explanation")
    p_new.add_argument("--executor", default="kilo", help="Assigned executor")
    p_new.add_argument("--next-up", choices=sorted(NEXT_UP_VALUES), default="no", help="Next up flag")
    p_new.add_argument("--depends-on", default="-", help="Dependencies")
    p_new.add_argument("--decider", default="-", help="Decider")
    p_new.add_argument("--tasks-dir", default="tasks", help="Path to tasks/ directory")
    p_new.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output structured JSON")
    p_new.set_defaults(func=cmd_tasks_new)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
