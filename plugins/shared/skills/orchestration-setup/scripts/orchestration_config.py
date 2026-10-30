#!/usr/bin/env python3
"""orchestration_config.py — Deterministic manager for Global + Project
`orchestration.toml` and project `AGENTS.md` orchestration blocks.

Designed as the shared engine for:
  1. The `interactive-role-setup` skill (interactive setup & verification)
  2. Direct CLI usage (`python3 orchestration_config.py <subcommand>`)
  3. Future Web Server / VS Code Extension integration (via `--json`)

Zero external dependencies on Python 3.11+ (uses stdlib `tomllib`, `json`,
`pathlib`, `re`).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime
import difflib
import hashlib
import json
import logging
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from typing import Any, Iterator

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

logger = logging.getLogger("orchestration_config")

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore

WORKSPACE_SLUG_REGEX = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")


def is_valid_workspace_slug(slug: Any) -> bool:
    return isinstance(slug, str) and bool(WORKSPACE_SLUG_REGEX.match(slug))


def is_valid_project_slug(slug: Any) -> bool:
    return isinstance(slug, str) and (slug == "_workspace" or bool(WORKSPACE_SLUG_REGEX.match(slug)))


def is_valid_uuid4(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    try:
        u = uuid.UUID(val)
        return u.version == 4
    except Exception:
        return False


PROFILES = ("deep-reasoning", "orchestration", "bulk-execution", "exploration")
PROFILE_SET = set(PROFILES)
BASIS_VALUES = {
    "host-metadata",
    "provider-tier-naming",
    "model-self-knowledge",
    "operator-stated",
    "template-default",
}
VERIFICATION_MODES = {"self", "independent-session", "cross-agent", "panel", "owner"}
KNOWN_NO_XHIGH_SUBSTRINGS = ("opus-4.6", "sonnet-4.6", "opus 4.6", "sonnet 4.6")

HEADLESS_ALLOWED_KEYS = {
    "argv",
    "resume_argv",
    "prompt_via",
    "permission_mode",
    "sandbox",
    "allowed_tools",
}
HEADLESS_ALLOWED_TOOLS_MODES = {"execute", "verify", "orchestrate"}
ALLOWED_PLACEHOLDERS = {
    "cwd",
    "model",
    "variant",
    "effort",
    "session_id",
    "permission_mode",
    "sandbox",
    "prompt_file",
}

DEFAULT_CLAUDE_ALLOWED_TOOLS: dict[str, list[str]] = {
    "execute": [
        "Read",
        "Edit",
        "Write",
        "Glob",
        "Grep",
        "Bash(git status:*)",
        "Bash(git diff:*)",
        "Bash(git add:*)",
        "Bash(git commit:*)",
        "Bash(git log:*)",
        "Bash(pytest:*)",
        "Bash(python -m pytest:*)",
        "Bash(python3 -m pytest:*)",
        "Bash(uv run:*)",
        "Bash(npm test:*)",
        "Bash(npm run build:*)",
    ],
    "verify": [
        "Read",
        "Glob",
        "Grep",
        "Bash(git status:*)",
        "Bash(git diff:*)",
        "Bash(git log:*)",
        "Bash(pytest:*)",
        "Bash(python -m pytest:*)",
        "Bash(python3 -m pytest:*)",
        "Bash(uv run:*)",
        "Bash(npm test:*)",
        "Bash(npm run build:*)",
    ],
    "orchestrate": [
        "Read",
        "Edit",
        "Write",
        "Glob",
        "Grep",
        "Bash(git status:*)",
        "Bash(git diff:*)",
        "Bash(git add:*)",
        "Bash(git commit:*)",
        "Bash(git log:*)",
        "Bash(pytest:*)",
        "Bash(python -m pytest:*)",
        "Bash(python3 -m pytest:*)",
        "Bash(uv run:*)",
        "Bash(npm test:*)",
        "Bash(npm run build:*)",
        "mcp__kilo-mcp__*",
    ],
    "triage": [
        "Read",
        "Glob",
        "Grep",
        "Bash(git status:*)",
        "Bash(git diff:*)",
        "Bash(git log:*)",
        "Bash(git show:*)",
    ],
}

BEGIN_MARKER = "<!-- BEGIN ai-orchestration -->"
END_MARKER = "<!-- END ai-orchestration -->"

PROFILE_DESCRIPTIONS = {
    "deep-reasoning": (
        "High complexity / silent-failure risk",
        "Complex multi-file architecture & core logic, tricky bug root-cause analysis, "
        "blind spec/code review (`task-spec-authoring`), and semantic merge-conflict resolution (`conflict-resolver`).",
    ),
    "orchestration": (
        "Planning, dispatch & verification",
        "Main session task decomposition, spec drafting, integration verification, and evaluating Executor outputs.",
    ),
    "bulk-execution": (
        "Well-specified implementation",
        "Executing self-contained task specs with clear `focus_files`, isolated modules/plugins, UI adjustments, and unit/smoke tests.",
    ),
    "exploration": (
        "Fast read-only discovery & checks",
        "Fast codebase search (`explore` / RAG), caller tracing, catalog/JSON inspection, and running read-only verification checks.",
    ),
}

DEFAULT_GLOBAL_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "last_verified": datetime.date.today().isoformat(),
    "routing": {
        # Owner default (2026-10-17): Claude orchestrates, Kilo executes.
        "default_orchestrator": "claude",
        "default_executor": "kilo",
        "default_profile": "bulk-execution",
    },
    "verification": {
        "default_mode": "cross-agent",
        "cross_agent_order": [
            "claude:deep-reasoning",
            "kilo:deep-reasoning",
            "codex:deep-reasoning",
        ],
        "panel_reviewers": [
            "kilo:deep-reasoning",
            "claude:deep-reasoning",
            "codex:deep-reasoning",
        ],
        "panel_require_blind": True,
    },
    "agents_md": {
        "strict_main_session": False,
    },
    "tools": {
        "kilo": {
            "enabled": True,
            "native_worktree_tool": 'agent_manager(mode="worktree")',
            "native_local_tool": 'agent_manager(mode="local")',
            "native_subagent_tool": "task",
            "mcp_server": "kilo-mcp",
            "mcp_implement_tool": "kilo_implement",
            "mcp_progress_tool": "kilo_task_progress",
            "mcp_wait_tool": "kilo_task_wait",
            "mcp_result_tool": "kilo_task_result",
            "mcp_cancel_tool": "kilo_task_cancel",
            "mcp_rag_tool": "kilo_rag_search",
            "cli_command": "kilo",
            "profiles": {
                "deep-reasoning": {
                    "model": "google/gemini-4-argon",
                    "variant": "high",
                    "basis": "template-default",
                },
                "orchestration": {
                    "model": "google/gemini-4-argon",
                    "variant": "medium",
                    "basis": "template-default",
                },
                "bulk-execution": {
                    "model": "google/gemini-3.8-flash",
                    "variant": "medium",
                    "basis": "template-default",
                },
                "exploration": {
                    "model": "google/gemini-3.8-flash",
                    "variant": "low",
                    "basis": "template-default",
                },
            },
        },
        "claude": {
            "enabled": True,
            "native_worktree_tool": 'Agent(isolation="worktree")',
            "native_local_tool": "Agent",
            "native_subagent_tool": "Agent",
            "mcp_server": "claude-mcp",
            "mcp_implement_tool": "claude_implement",
            "mcp_progress_tool": "claude_task_progress",
            "mcp_result_tool": "claude_task_result",
            "mcp_cancel_tool": "claude_task_cancel",
            "cli_command": "claude",
            "profiles": {
                "deep-reasoning": {
                    "model": "opus",
                    "effort": "high",
                    "basis": "template-default",
                },
                "orchestration": {
                    "model": "sonnet",
                    "effort": "medium",
                    "basis": "template-default",
                },
                "bulk-execution": {
                    "model": "sonnet",
                    "effort": "medium",
                    "basis": "template-default",
                },
                "exploration": {
                    "model": "haiku",
                    "effort": "low",
                    "basis": "template-default",
                },
            },
        },
        "codex": {
            "enabled": True,
            "native_worktree_tool": 'codex exec -C <worktree> -s workspace-write',
            "native_local_tool": "codex exec resume --last",
            "native_subagent_tool": "codex exec / codex review",
            "mcp_server": "codex-mcp (codex mcp-server)",
            "mcp_implement_tool": "codex_exec",
            "cli_command": "codex",
            "profiles": {
                "deep-reasoning": {
                    "model": "gpt-5-codex",
                    "effort": "high",
                    "basis": "template-default",
                },
                "orchestration": {
                    "model": "gpt-5-codex",
                    "effort": "medium",
                    "basis": "template-default",
                },
                "bulk-execution": {
                    "model": "gpt-5-codex-mini",
                    "effort": "medium",
                    "basis": "template-default",
                },
                "exploration": {
                    "model": "gpt-5-codex-mini",
                    "effort": "low",
                    "basis": "template-default",
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Paths & TOML Load / Dump
# ---------------------------------------------------------------------------

def default_global_config_path() -> pathlib.Path:
    env_path = os.environ.get("AI_ORCHESTRATION_CONFIG")
    if env_path and env_path.strip():
        p = pathlib.Path(env_path).expanduser().resolve()
        if p.is_dir():
            return p / "orchestration.toml"
        if p.is_file() or p.suffix.lower() == ".toml" or p.name.endswith(".toml"):
            return p
        return p / "orchestration.toml"
    env_dir = os.environ.get("AI_ORCH_CONFIG_DIR")
    if env_dir and env_dir.strip():
        return pathlib.Path(env_dir).expanduser().resolve() / "orchestration.toml"
    env_home = os.environ.get("AI_ORCH_HOME")
    if env_home and env_home.strip():
        return pathlib.Path(env_home).expanduser().resolve() / ".config" / "ai-orchestration" / "orchestration.toml"
    return pathlib.Path.home() / ".config" / "ai-orchestration" / "orchestration.toml"


def global_config_dir() -> pathlib.Path:
    """Return the directory containing global orchestration configuration."""
    env_path = os.environ.get("AI_ORCHESTRATION_CONFIG")
    if env_path and env_path.strip():
        p = pathlib.Path(env_path).expanduser().resolve()
        if p.is_file() or p.suffix == ".toml" or p.name.endswith(".toml"):
            return p.parent
        return p
    env_dir = os.environ.get("AI_ORCH_CONFIG_DIR")
    if env_dir and env_dir.strip():
        return pathlib.Path(env_dir).expanduser().resolve()
    env_home = os.environ.get("AI_ORCH_HOME")
    if env_home and env_home.strip():
        return pathlib.Path(env_home).expanduser().resolve() / ".config" / "ai-orchestration"
    return pathlib.Path.home() / ".config" / "ai-orchestration"


def project_config_candidates(
    workspace: pathlib.Path | str,
    global_path: pathlib.Path | str | None = None,
) -> list[tuple[pathlib.Path, str, bool]]:
    """Return ordered (path, label, is_legacy) candidates for a project's configuration.

    Documented precedence order:
      1. `<workspace>/.ai-orchestration.local.toml` (canonical, local unversioned, read-write)
      2. `~/.config/ai-orchestration/projects/<workspace-name>/orchestration.toml` (canonical, external, read-write)
      3. `<workspace>/orchestration.toml` (legacy, read-only with warning)
      4. `<workspace>/.ai-orchestration/orchestration.toml` (legacy, read-only with warning)
      5. `<workspace>/tasks/orchestration.toml` (legacy, read-only with warning)
      6. `<workspace>/.ai-orchestration.toml` (legacy, read-only with warning)
    """
    ws = pathlib.Path(workspace)
    ws_resolved = ws.resolve()
    if global_path is not None:
        gp = pathlib.Path(global_path).expanduser().resolve()
        if gp.is_dir():
            gpath = gp / "orchestration.toml"
        elif gp.is_file() or gp.suffix.lower() == ".toml" or gp.name.endswith(".toml"):
            gpath = gp
        else:
            gpath = gp / "orchestration.toml"
    else:
        gpath = default_global_config_path()
    projects_root = gpath.parent / "projects"
    ext_path = projects_root / ws_resolved.name / "orchestration.toml"
    ext_label = f"~/.config/ai-orchestration/projects/{ws_resolved.name}/orchestration.toml"

    return [
        (ws / ".ai-orchestration.local.toml", ".ai-orchestration.local.toml", False),
        (ext_path, ext_label, False),
        (ws / "orchestration.toml", "orchestration.toml", True),
        (ws / ".ai-orchestration" / "orchestration.toml", ".ai-orchestration/orchestration.toml", True),
        (ws / "tasks" / "orchestration.toml", "tasks/orchestration.toml", True),
        (ws / ".ai-orchestration.toml", ".ai-orchestration.toml", True),
    ]


def inspect_project_config(
    workspace: pathlib.Path | str,
    global_path: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Inspect all canonical and legacy project configuration candidates for `workspace`.

    Returns a dict with:
      - `path`: pathlib.Path — active config path for reading (first existing candidate, or canonical external default)
      - `write_path`: pathlib.Path — canonical config path for writing (never a legacy location)
      - `exists`: bool — whether `path` exists on disk
      - `is_legacy`: bool — True when `path` is one of the read-only legacy paths
      - `label`: str — short display label of `path`
      - `candidates`: list[dict] — all existing candidate files in precedence order
      - `legacy_paths`: list[pathlib.Path] — all existing legacy config files on disk
      - `warnings`: list[str] — deprecation warnings for any legacy config files found on disk
    """
    cands = project_config_candidates(workspace, global_path)
    local_dot_path = cands[0][0]
    default_ext_path, default_ext_label, _ = cands[1]

    write_path = local_dot_path if local_dot_path.is_file() else default_ext_path

    existing: list[dict[str, Any]] = []
    seen_resolved: set[pathlib.Path] = set()
    for p, lbl, is_leg in cands:
        if not p.is_file():
            continue
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp in seen_resolved:
            continue
        seen_resolved.add(rp)
        existing.append({"path": p, "label": lbl, "is_legacy": is_leg})

    if existing:
        active = existing[0]
        active_path: pathlib.Path = active["path"]
        active_label: str = active["label"]
        active_legacy: bool = bool(active["is_legacy"])
        active_exists = True
    else:
        active_path = default_ext_path
        active_label = default_ext_label
        active_legacy = False
        active_exists = False

    legacy_paths: list[pathlib.Path] = [c["path"] for c in existing if c["is_legacy"]]
    warnings: list[str] = []
    for c in existing:
        if c["is_legacy"]:
            c_path = c["path"]
            c_lbl = c["label"]
            if c_path == active_path:
                warnings.append(
                    f"{c_lbl}: legacy project config path '{c_path}' is deprecated and read-only; "
                    f"move it to '{write_path}' (or '{local_dot_path}')."
                )
            else:
                warnings.append(
                    f"{c_lbl}: legacy project config path '{c_path}' is deprecated (read-only) and shadowed by '{active_path}'; "
                    f"move or merge it into '{write_path}'."
                )

    return {
        "path": active_path,
        "write_path": write_path,
        "exists": active_exists,
        "is_legacy": active_legacy,
        "label": active_label,
        "candidates": existing,
        "legacy_paths": legacy_paths,
        "warnings": warnings,
    }


def find_project_config_path(
    workspace: pathlib.Path | str,
    global_path: pathlib.Path | str | None = None,
    *,
    for_write: bool = False,
) -> pathlib.Path:
    """Return the project configuration path for `workspace`.

    Agent/model/tool choices are local to the developer's machine and must NOT
    be committed to the repository's versioned `tasks/` tree.
    Precedence when reading (`for_write=False`, default):
      1. `<workspace>/.ai-orchestration.local.toml` (canonical, local gitignored)
      2. `~/.config/ai-orchestration/projects/<workspace-name>/orchestration.toml` (canonical, external)
      3. `<workspace>/orchestration.toml` (legacy, read-only with warning)
      4. `<workspace>/.ai-orchestration/orchestration.toml` (legacy, read-only with warning)
      5. `<workspace>/tasks/orchestration.toml` (legacy, read-only with warning)
      6. `<workspace>/.ai-orchestration.toml` (legacy, read-only with warning)
    If none exist on disk, returns (2).

    When writing (`for_write=True`), legacy locations (3–6) are ignored so they remain
    strictly read-only: returns (1) if it already exists, otherwise (2).
    """
    info = inspect_project_config(workspace, global_path)
    return info["write_path"] if for_write else info["path"]


def format_diff_path(
    path: pathlib.Path,
    prefix: str = "a",
    workspace: pathlib.Path | None = None,
) -> str:
    """Format path for unified diff headers (fromfile / tofile).

    Preserves the real target path:
      - Paths within workspace: <prefix>/<relative-to-workspace>
      - Paths within user home: <prefix>/~/<relative-to-home>
      - Absolute paths outside home: <prefix><absolute-path> (or <prefix>/<absolute-path>)
    Never returns a bare filename that reads like a repository file.
    """
    resolved = path.resolve()
    if workspace is not None:
        try:
            rel = resolved.relative_to(workspace.resolve())
            return f"{prefix}/{rel}"
        except (ValueError, RuntimeError):
            pass
    try:
        rel = resolved.relative_to(pathlib.Path.home().resolve())
        return f"{prefix}/~/{rel}"
    except (ValueError, RuntimeError):
        pass
    p_str = str(resolved)
    if p_str.startswith("/"):
        return f"{prefix}{p_str}"
    return f"{prefix}/{p_str}"


def load_toml_file(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_bytes()
    if tomllib is not None:
        return tomllib.loads(raw.decode("utf-8"))
    raise RuntimeError("Python 3.11+ (stdlib tomllib) is required to parse orchestration.toml")


def _format_toml_value(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(val, list):
        inner = ", ".join(_format_toml_value(x) for x in val)
        return f"[{inner}]"
    raise TypeError(f"Unsupported TOML scalar/list value: {val!r}")


def dump_toml(data: dict[str, Any]) -> str:
    """Deterministic TOML serializer for orchestration.toml structures."""
    lines: list[str] = []

    def emit_table(prefix: str, table: dict[str, Any]) -> None:
        scalars: list[tuple[str, Any]] = []
        subtables: list[tuple[str, dict[str, Any]]] = []
        array_tables: list[tuple[str, list[dict[str, Any]]]] = []

        for k, v in table.items():
            if v is None:
                continue
            if isinstance(v, dict):
                subtables.append((k, v))
            elif isinstance(v, list) and v and all(isinstance(item, dict) for item in v):
                array_tables.append((k, v))
            else:
                scalars.append((k, v))

        if prefix and (scalars or not subtables):
            lines.append(f"[{prefix}]")
        for k, v in scalars:
            key_str = f'"{k}"' if not re.match(r"^[A-Za-z0-9_-]+$", k) else k
            lines.append(f"{key_str} = {_format_toml_value(v)}")
        if scalars and (subtables or array_tables):
            lines.append("")

        for k, sub in subtables:
            key_str = f'"{k}"' if not re.match(r"^[A-Za-z0-9_-]+$", k) else k
            child_prefix = f"{prefix}.{key_str}" if prefix else key_str
            emit_table(child_prefix, sub)
            if lines and lines[-1] != "":
                lines.append("")

        for k, arr in array_tables:
            key_str = f'"{k}"' if not re.match(r"^[A-Za-z0-9_-]+$", k) else k
            child_prefix = f"{prefix}.{key_str}" if prefix else key_str
            for item in arr:
                lines.append(f"[[{child_prefix}]]")
                for ik, iv in item.items():
                    if iv is not None:
                        lines.append(f"{ik} = {_format_toml_value(iv)}")
                lines.append("")

    emit_table("", data)
    return "\n".join(lines).rstrip() + "\n"


def parse_table_header(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("[") or stripped.startswith("[["):
        return None
    m = re.match(r"^\[\s*([^\[\]]+?)\s*\]\s*(?:#.*)?$", stripped)
    if not m:
        return None
    header_content = m.group(1).strip()
    parts: list[str] = []
    token_re = re.compile(
        r"""(?:\s*\.\s*|^\s*)(?:"([^"\\]*(?:\\.[^"\\]*)*)"|'([^']*)'|([A-Za-z0-9_-]+))\s*"""
    )
    idx = 0
    while idx < len(header_content):
        m_part = token_re.match(header_content, idx)
        if not m_part:
            return None
        if m_part.group(1) is not None:
            val = bytes(m_part.group(1), "utf-8").decode("unicode_escape")
            parts.append(val)
        elif m_part.group(2) is not None:
            parts.append(m_part.group(2))
        else:
            parts.append(m_part.group(3))
        idx = m_part.end()
    return parts


def match_key_line(line: str) -> tuple[str, str, str] | None:
    s = line.lstrip()
    if not s or s.startswith("#") or s.startswith("["):
        return None
    indent = line[: len(line) - len(s)]
    m = re.match(
        r"""^(?P<key>[A-Za-z0-9_-]+|"[^"\\]*(?:\\.[^"\\]*)*"|'[^']*')\s*=\s*(?P<rest>.*)$""",
        s,
        re.DOTALL,
    )
    if not m:
        return None
    raw_key = m.group("key")
    rest = m.group("rest")
    if (raw_key.startswith('"') and raw_key.endswith('"')) or (
        raw_key.startswith("'") and raw_key.endswith("'")
    ):
        k_name = raw_key[1:-1]
    else:
        k_name = raw_key
    return indent, k_name, rest


def extract_inline_comment(line: str) -> str:
    in_double = False
    in_single = False
    escape = False
    for idx, ch in enumerate(line):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_double:
            escape = True
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == "#" and not in_double and not in_single:
            start_ws = idx
            while start_ws > 0 and line[start_ws - 1] in " \t":
                start_ws -= 1
            return line[start_ws:].rstrip("\r\n")
    return ""


def set_toml_value(text: str, table_path: list[str], key: str, value: Any) -> str:
    """Surgically update or insert a key inside a TOML table, preserving formatting.

    Preserves comments, blank lines, ordering, and untouched values.
    Validates by re-parsing with tomllib; raises ValueError if parsing fails or
    the resulting value differs from the expected value.
    """
    expanded_table_path: list[str] = []
    for p in table_path:
        expanded_table_path.extend(p.split("."))
    table_path = expanded_table_path

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)

    table_found = False
    body_start = 0
    body_end = len(lines)

    if not table_path:
        table_found = True
        body_start = 0
        for idx, line in enumerate(lines):
            if parse_table_header(line) is not None or line.lstrip().startswith("[["):
                body_end = idx
                break
    else:
        for idx, line in enumerate(lines):
            hdr = parse_table_header(line)
            if hdr == table_path:
                table_found = True
                body_start = idx + 1
                body_end = len(lines)
                for next_idx in range(body_start, len(lines)):
                    next_line = lines[next_idx]
                    if (
                        parse_table_header(next_line) is not None
                        or next_line.lstrip().startswith("[[")
                    ):
                        body_end = next_idx
                        break
                break

    formatted_val = _format_toml_value(value) if value is not None else ""
    key_str = key if re.match(r"^[A-Za-z0-9_-]+$", key) else f'"{key}"'

    if table_found:
        key_found = False
        key_start = -1
        key_end = -1
        indent = ""

        idx = body_start
        while idx < body_end:
            matched = match_key_line(lines[idx])
            if matched and matched[1] == key:
                key_found = True
                key_start = idx
                indent = matched[0]
                j = idx + 1
                while j <= body_end:
                    candidate = "".join(lines[idx:j])
                    try:
                        if tomllib is not None:
                            tomllib.loads(candidate)
                        break
                    except Exception:
                        j += 1
                else:
                    j = idx + 1
                key_end = j
                break
            idx += 1

        if key_found:
            if value is None:
                del lines[key_start:key_end]
            else:
                comment = extract_inline_comment(lines[key_start])
                new_line = f"{indent}{key_str} = {formatted_val}{comment}{newline}"
                lines[key_start:key_end] = [new_line]
        else:
            if value is not None:
                for l in lines[body_start:body_end]:
                    m = match_key_line(l)
                    if m:
                        indent = m[0]
                        break

                insert_idx = body_end
                while insert_idx > body_start and lines[insert_idx - 1].strip() == "":
                    insert_idx -= 1

                new_line = f"{indent}{key_str} = {formatted_val}{newline}"
                lines.insert(insert_idx, new_line)
    else:
        if value is not None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] = lines[-1] + newline
            if lines and lines[-1].strip() != "":
                lines.append(newline)

            header_str = ".".join(
                p if re.match(r"^[A-Za-z0-9_-]+$", p) else f'"{p}"' for p in table_path
            )
            lines.append(f"[{header_str}]{newline}")
            lines.append(f"{key_str} = {formatted_val}{newline}")

    new_text = "".join(lines)

    if tomllib is None:
        raise RuntimeError("Python 3.11+ (tomllib) required")
    try:
        parsed = tomllib.loads(new_text)
    except Exception as e:
        raise ValueError(f"Surgical TOML update produced invalid TOML: {e}") from e

    cur: Any = parsed
    for p in table_path:
        if not isinstance(cur, dict) or p not in cur:
            raise ValueError(
                f"Surgical TOML update: table path {table_path} not found in parsed result"
            )
        cur = cur[p]

    if value is None:
        if key in cur:
            raise ValueError(f"Surgical TOML update: key {key!r} was not removed")
    else:
        if key not in cur:
            raise ValueError(
                f"Surgical TOML update: key {key!r} not found in parsed table {table_path}"
            )
        if cur[key] != value:
            raise ValueError(
                f"Surgical TOML update: parsed value {cur[key]!r} does not match expected {value!r}"
            )

    return new_text


def write_file_atomic(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    try:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


_CONFIG_LOCK_COUNTS: dict[str, int] = {}
_CONFIG_LOCK_FDS: dict[str, int] = {}
_CONFIG_THREAD_LOCKS: dict[str, threading.RLock] = {}
_CONFIG_GLOBAL_LOCK = threading.Lock()


def _get_config_thread_lock(lock_key: str) -> threading.RLock:
    with _CONFIG_GLOBAL_LOCK:
        if lock_key not in _CONFIG_THREAD_LOCKS:
            _CONFIG_THREAD_LOCKS[lock_key] = threading.RLock()
        return _CONFIG_THREAD_LOCKS[lock_key]


@contextlib.contextmanager
def config_lock(target_path: pathlib.Path | str) -> Iterator[pathlib.Path]:
    """Exclusive fcntl.flock on <target_path>.lock file beside the target.

    Serialized across processes via fcntl.flock; re-entrant across nested calls
    and serialized across threads in the same process via threading.RLock.
    """
    target = pathlib.Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_file = target.parent / f"{target.name}.lock"
    lock_key = str(lock_file)
    thread_lock = _get_config_thread_lock(lock_key)

    with thread_lock:
        count = _CONFIG_LOCK_COUNTS.get(lock_key, 0)
        if count > 0:
            _CONFIG_LOCK_COUNTS[lock_key] = count + 1
            try:
                yield lock_file
            finally:
                _CONFIG_LOCK_COUNTS[lock_key] -= 1
                if _CONFIG_LOCK_COUNTS[lock_key] == 0:
                    _CONFIG_LOCK_COUNTS.pop(lock_key, None)
            return

        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            _CONFIG_LOCK_COUNTS[lock_key] = 1
            _CONFIG_LOCK_FDS[lock_key] = fd
            yield lock_file
        finally:
            _CONFIG_LOCK_COUNTS.pop(lock_key, None)
            _CONFIG_LOCK_FDS.pop(lock_key, None)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)


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
    except Exception as e:
        logger.warning("Could not import orchestration_events: %s", e)
        return None


def _emit_config_changed(
    *,
    scope: str,
    target_path: pathlib.Path,
    workspace: pathlib.Path | None,
    keys_changed: list[str],
    before_hash: str,
    after_hash: str,
) -> dict[str, Any] | None:
    """Emit config.changed event through orchestration_events into workspace event store."""
    ws_to_use: pathlib.Path | None = None
    if scope == "project":
        ws_to_use = workspace or pathlib.Path(".").resolve()
    elif scope == "global":
        if workspace is not None:
            ws_to_use = pathlib.Path(workspace).resolve()
        else:
            # Spec §0c E10: config.changed covers project config only;
            # global writes without a workspace emit nothing.
            logger.info("Global config write without workspace: skipping config.changed event emission")
            return None

    orch_events = _get_orchestration_events()
    if orch_events is None:
        print(
            "[warning] could not import orchestration_events; config.changed event omitted",
            file=sys.stderr,
        )
        return None

    payload = {
        "scope": scope,
        "path": str(target_path.resolve()),
        "keys": keys_changed,
        "keys_changed": keys_changed,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "before_sha256": before_hash,
        "after_sha256": after_hash,
    }

    try:
        ev = orch_events.emit(
            ws_to_use,
            "config.changed",
            payload,
            source="orchestration_config",
            subject=str(target_path.resolve()),
        )
        return ev
    except Exception as e:
        print(
            f"[warning] failed to emit config.changed event: {e}",
            file=sys.stderr,
        )
        return None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def resolve_config(
    global_path: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    gpath = global_path or default_global_config_path()
    global_cfg = load_toml_file(gpath) if gpath.exists() else copy.deepcopy(DEFAULT_GLOBAL_CONFIG)

    project_cfg: dict[str, Any] = {}
    ppath: pathlib.Path | None = None
    proj_info: dict[str, Any] | None = None
    if workspace is not None:
        proj_info = inspect_project_config(workspace, gpath)
        ppath = proj_info["path"]
        # Load only the selected highest-precedence project config file; lower-precedence files are shadowed.
        if proj_info["exists"] and ppath.is_file():
            project_cfg = load_toml_file(ppath)

    merged = deep_merge(DEFAULT_GLOBAL_CONFIG, global_cfg)
    if project_cfg:
        merged = deep_merge(merged, project_cfg)

    meta = {
        "global_config_path": str(gpath),
        "global_config_exists": gpath.exists(),
        "project_config_path": str(ppath) if ppath else None,
        "project_config_exists": bool(ppath and ppath.exists()),
        "project_config_write_path": str(proj_info["write_path"]) if proj_info else None,
        "project_config_legacy": bool(proj_info and proj_info["is_legacy"]),
        "warnings": list(proj_info["warnings"]) if proj_info else [],
    }
    return merged, meta


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_config(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    tools = cfg.get("tools", {})
    if not isinstance(tools, dict) or not tools:
        errors.append("No [tools.<name>] sections defined.")
        return errors, warnings

    enabled_tools = [name for name, t in tools.items() if isinstance(t, dict) and t.get("enabled", True)]
    if not enabled_tools:
        errors.append("At least one tool in [tools.<name>] must have enabled = true.")

    for tname, tcfg in tools.items():
        if not isinstance(tcfg, dict):
            continue

        headless = tcfg.get("headless")
        if headless is not None:
            if not isinstance(headless, dict):
                errors.append(f"Tool '{tname}' [tools.{tname}.headless] must be a table.")
            else:
                for hk in headless:
                    if hk not in HEADLESS_ALLOWED_KEYS:
                        errors.append(
                            f"Tool '{tname}' headless has unknown key {hk!r} "
                            f"(allowed: {sorted(HEADLESS_ALLOWED_KEYS)})."
                        )

                for argv_key in ("argv", "resume_argv"):
                    if argv_key in headless:
                        val = headless[argv_key]
                        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                            errors.append(
                                f"Tool '{tname}' headless '{argv_key}' must be a list of strings."
                            )
                        else:
                            for arg_str in val:
                                for placeholder in re.findall(r"\{([^{}]+)\}", arg_str):
                                    if placeholder not in ALLOWED_PLACEHOLDERS:
                                        errors.append(
                                            f"Tool '{tname}' headless {argv_key} contains invalid placeholder "
                                            f"'{{{placeholder}}}' (allowed: {sorted('{' + p + '}' for p in ALLOWED_PLACEHOLDERS)})."
                                        )

                if "prompt_via" in headless:
                    pv = headless["prompt_via"]
                    if pv not in ("stdin", "file"):
                        errors.append(
                            f"Tool '{tname}' headless 'prompt_via' must be 'stdin' or 'file' (got {pv!r})."
                        )

                if "permission_mode" in headless:
                    pm = headless["permission_mode"]
                    if not isinstance(pm, str):
                        errors.append(
                            f"Tool '{tname}' headless 'permission_mode' must be a string."
                        )

                if "sandbox" in headless:
                    sb = headless["sandbox"]
                    if not isinstance(sb, str):
                        errors.append(f"Tool '{tname}' headless 'sandbox' must be a string.")

                if "allowed_tools" in headless:
                    at = headless["allowed_tools"]
                    if isinstance(at, list):
                        if not all(isinstance(x, str) for x in at):
                            errors.append(
                                f"Tool '{tname}' headless 'allowed_tools' must be a list of strings."
                            )
                    elif isinstance(at, dict):
                        for mk, mv in at.items():
                            if mk not in HEADLESS_ALLOWED_TOOLS_MODES:
                                errors.append(
                                    f"Tool '{tname}' headless 'allowed_tools' has unknown mode {mk!r} "
                                    f"(allowed: {sorted(HEADLESS_ALLOWED_TOOLS_MODES)})."
                                )
                            if not isinstance(mv, list) or not all(isinstance(x, str) for x in mv):
                                errors.append(
                                    f"Tool '{tname}' headless 'allowed_tools.{mk}' must be a list of strings."
                                )
                    else:
                        errors.append(
                            f"Tool '{tname}' headless 'allowed_tools' must be a list of strings or a table with keys {sorted(HEADLESS_ALLOWED_TOOLS_MODES)}."
                        )

        if not tcfg.get("enabled", True):
            continue
        profiles = tcfg.get("profiles", {})
        for prof in PROFILES:
            pentry = profiles.get(prof)
            if not pentry or not str(pentry.get("model", "")).strip():
                warnings.append(f"Tool '{tname}' is enabled but missing model for profile '{prof}'.")
                continue
            model = str(pentry.get("model", ""))
            effort = str(pentry.get("effort", "") or pentry.get("variant", ""))
            if effort == "xhigh" and any(s in model.lower() for s in KNOWN_NO_XHIGH_SUBSTRINGS):
                errors.append(
                    f"Tool '{tname}' profile '{prof}' pins effort/variant='xhigh' on {model!r}, "
                    "which is known not to support xhigh."
                )
            basis = pentry.get("basis")
            if basis and basis not in BASIS_VALUES:
                errors.append(
                    f"Tool '{tname}' profile '{prof}' has invalid basis {basis!r} "
                    f"(must be one of {sorted(BASIS_VALUES)})."
                )

    routing = cfg.get("routing", {})
    for key in ("default_orchestrator", "default_executor"):
        val = routing.get(key)
        if val and val not in tools:
            errors.append(f"[routing].{key} = {val!r} refers to unknown tool (known: {sorted(tools)}).")
        elif val and not tools.get(val, {}).get("enabled", True):
            warnings.append(f"[routing].{key} = {val!r} refers to a disabled tool.")

    ver = cfg.get("verification", {})
    vmode = ver.get("default_mode", "cross-agent")
    if vmode not in VERIFICATION_MODES:
        errors.append(
            f"[verification].default_mode = {vmode!r} is invalid (must be one of {sorted(VERIFICATION_MODES)})."
        )

    for list_key in ("cross_agent_order", "panel_reviewers"):
        for item in ver.get(list_key, []):
            if ":" not in str(item):
                errors.append(f"[verification].{list_key} entry {item!r} must have format '<tool>:<profile>'.")
                continue
            t_id, p_id = str(item).split(":", 1)
            if t_id not in tools:
                errors.append(f"[verification].{list_key} entry {item!r} references unknown tool {t_id!r}.")
            if p_id not in PROFILE_SET:
                errors.append(f"[verification].{list_key} entry {item!r} references invalid profile {p_id!r}.")

    agents_md = cfg.get("agents_md")
    if agents_md is not None:
        if not isinstance(agents_md, dict):
            errors.append("[agents_md] must be a table.")
        elif "strict_main_session" in agents_md and not isinstance(agents_md["strict_main_session"], bool):
            errors.append("[agents_md].strict_main_session must be a boolean.")

    ws_cfg = cfg.get("workspace")
    if ws_cfg is not None:
        if not isinstance(ws_cfg, dict):
            errors.append("[workspace] must be a table.")
        else:
            ws_uuid = ws_cfg.get("uuid")
            if ws_uuid is None:
                errors.append("[workspace].uuid is required.")
            elif not is_valid_uuid4(ws_uuid):
                errors.append(f"[workspace].uuid = {ws_uuid!r} must be a valid UUID4 string.")

            ws_id = ws_cfg.get("id")
            if ws_id is None:
                errors.append("[workspace].id is required.")
            elif not is_valid_workspace_slug(ws_id):
                errors.append(
                    f"[workspace].id = {ws_id!r} must be a lowercase slug matching ^[a-z0-9][a-z0-9-]{{1,47}}$."
                )

            if "title" in ws_cfg:
                title = ws_cfg["title"]
                if not isinstance(title, str):
                    errors.append("[workspace].title must be a string.")

            projects = ws_cfg.get("projects")
            if projects is not None:
                if not isinstance(projects, list):
                    errors.append("[[workspace.projects]] must be a list of tables.")
                else:
                    seen_pids: set[str] = set()
                    seen_puuids: set[str] = set()
                    seen_paths: set[str] = set()
                    for idx, p in enumerate(projects):
                        if not isinstance(p, dict):
                            errors.append(f"[[workspace.projects]] item {idx} must be a table.")
                            continue
                        puuid = p.get("uuid")
                        if puuid is None:
                            errors.append(f"[[workspace.projects]] item {idx} is missing 'uuid'.")
                        elif not is_valid_uuid4(puuid):
                            errors.append(
                                f"[[workspace.projects]] item {idx} uuid {puuid!r} must be a valid UUID4 string."
                            )
                        elif puuid in seen_puuids:
                            errors.append(f"[[workspace.projects]] duplicate project uuid: {puuid!r}.")
                        else:
                            seen_puuids.add(puuid)

                        pid = p.get("id")
                        if pid is None:
                            errors.append(f"[[workspace.projects]] item {idx} is missing 'id'.")
                        elif not is_valid_project_slug(pid):
                            errors.append(
                                f"[[workspace.projects]] item {idx} id {pid!r} must be '_workspace' or match ^[a-z0-9][a-z0-9-]{{1,47}}$."
                            )
                        elif pid in seen_pids:
                            errors.append(f"[[workspace.projects]] duplicate project id: {pid!r}.")
                        else:
                            seen_pids.add(pid)

                        ppath = p.get("path")
                        if ppath is None:
                            errors.append(f"[[workspace.projects]] item {idx} is missing 'path'.")
                        elif not isinstance(ppath, str) or not ppath.strip():
                            errors.append(f"[[workspace.projects]] item {idx} path must be a non-empty string.")
                        else:
                            norm_path = os.path.normpath(ppath.strip())
                            if norm_path in seen_paths:
                                errors.append(f"[[workspace.projects]] duplicate project path: {ppath!r}.")
                            else:
                                seen_paths.add(norm_path)

    proj_cfg = cfg.get("project")
    if isinstance(proj_cfg, dict):
        pf_cfg = proj_cfg.get("preflight")
        if pf_cfg is not None:
            if not isinstance(pf_cfg, dict):
                errors.append("[project.preflight] must be a table.")
            else:
                for pkey in ("free_ports", "ports"):
                    if pkey in pf_cfg:
                        pval = pf_cfg[pkey]
                        if not isinstance(pval, list):
                            errors.append(f"[project.preflight].{pkey} must be a list.")
                        else:
                            for p_item in pval:
                                if isinstance(p_item, bool):
                                    errors.append(f"[project.preflight].{pkey} contains invalid port {p_item!r}.")
                                elif isinstance(p_item, int):
                                    if not (1 <= p_item <= 65535):
                                        errors.append(
                                            f"[project.preflight].{pkey} port {p_item} must be in 1..65535."
                                        )
                                elif isinstance(p_item, dict):
                                    pnum = p_item.get("port")
                                    if isinstance(pnum, bool) or not isinstance(pnum, int) or not (1 <= pnum <= 65535):
                                        errors.append(
                                            f"[project.preflight].{pkey} entry {p_item!r} must have 'port' in 1..65535."
                                        )
                for dkey in ("min_disk_mb", "min_disk_gb", "disk_free_mb", "disk_free_gb", "min_free_mb", "min_free_gb"):
                    if dkey in pf_cfg:
                        dval = pf_cfg[dkey]
                        if isinstance(dval, bool) or not isinstance(dval, (int, float)) or dval < 0:
                            errors.append(f"[project.preflight].{dkey} must be a non-negative number.")

        for t_table_key in ("timeouts", "command_timeouts"):
            if t_table_key in proj_cfg:
                t_table = proj_cfg[t_table_key]
                if not isinstance(t_table, dict):
                    errors.append(f"[project.{t_table_key}] must be a table.")
                else:
                    for tk, tv in t_table.items():
                        if isinstance(tv, bool) or not isinstance(tv, (int, float)) or tv <= 0:
                            errors.append(
                                f"[project.{t_table_key}].{tk} must be a positive number (seconds)."
                            )

    return errors, warnings


# ---------------------------------------------------------------------------
# Project Preflight, Command Timeouts & Verification Checks (Task 19.7)
# ---------------------------------------------------------------------------

_PREFLIGHT_RESERVED_KEYS = {
    "enabled",
    "tools",
    "binaries",
    "required_tools",
    "executables",
    "free_ports",
    "ports",
    "services",
    "active_services",
    "required_services",
    "min_disk_mb",
    "min_disk_gb",
    "disk_free_mb",
    "disk_free_gb",
    "min_free_mb",
    "min_free_gb",
    "disk_space_mb",
    "disk_space_gb",
    "disk",
    "commands",
    "checks",
    "timeout",
    "timeout_seconds",
    "command_timeout",
    "command_timeout_seconds",
    "default_command_timeout",
    "test_timeout_seconds",
    "timeouts",
    "command_timeouts",
}


def parse_version_tuple(version_str: str | int | float | None) -> tuple[int, ...] | None:
    """Extract numeric version tuple (major, minor, ...) from a version string."""
    if version_str is None or isinstance(version_str, bool):
        return None
    s = str(version_str).strip()
    if not s or s in ("*", "any", "latest"):
        return None
    m = re.search(r"(\d+(?:\.\d+)*)", s)
    if not m:
        return None
    try:
        return tuple(int(part) for part in m.group(1).split("."))
    except ValueError:
        return None


def compare_versions(actual: tuple[int, ...], minimum: tuple[int, ...]) -> bool:
    """Return True if actual >= minimum (padding shorter tuple with trailing zeros)."""
    max_len = max(len(actual), len(minimum))
    act_padded = actual + (0,) * (max_len - len(actual))
    min_padded = minimum + (0,) * (max_len - len(minimum))
    return act_padded >= min_padded


def resolve_project_command_timeouts(cfg: dict[str, Any] | None) -> dict[str, int]:
    """Resolve per-project command timeouts (in seconds) from merged/project config.

    Supports:
      - `[project]` scalars: `command_timeout_seconds`, `command_timeout`,
        `default_command_timeout`, `timeout_seconds`, `timeout`, `test_timeout_seconds`
      - `[project.timeouts]` / `[project.command_timeouts]` tables (e.g. `default = 600`, `test = 900`)
      - `[project.preflight]` scalars and `[project.preflight.timeouts]` / `[project.preflight.command_timeouts]`
      - Top-level `[timeouts]` / `[command_timeouts]`
      - Per-check `timeout` / `timeout_seconds` under `[project.verification_checks.<name>]`
    """
    if not cfg or not isinstance(cfg, dict):
        return {}

    result: dict[str, int] = {}

    def _add_timeout(key: str, val: Any) -> None:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if val <= 0:
            return
        norm_key = key
        if key in (
            "command_timeout_seconds",
            "command_timeout",
            "default_command_timeout",
            "default_seconds",
            "command_seconds",
            "command",
            "timeout_seconds",
            "timeout",
        ):
            norm_key = "default"
        elif key in ("test_timeout_seconds", "test_timeout", "tests_timeout"):
            norm_key = "test"
        result[norm_key] = int(val)

    def _scan_table(tbl: Any) -> None:
        if not isinstance(tbl, dict):
            return
        for k, v in tbl.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                _add_timeout(k, v)

    # 1. Top-level fallback tables
    _scan_table(cfg.get("timeouts"))
    _scan_table(cfg.get("command_timeouts"))

    # 2. [project] and [project.preflight]
    proj = cfg.get("project")
    if isinstance(proj, dict):
        for scalar_k in (
            "command_timeout_seconds",
            "command_timeout",
            "default_command_timeout",
            "timeout_seconds",
            "timeout",
            "test_timeout_seconds",
        ):
            if scalar_k in proj:
                _add_timeout(scalar_k, proj[scalar_k])

        _scan_table(proj.get("timeouts"))
        _scan_table(proj.get("command_timeouts"))

        pf = proj.get("preflight")
        if isinstance(pf, dict):
            for scalar_k in (
                "command_timeout_seconds",
                "command_timeout",
                "default_command_timeout",
                "timeout_seconds",
                "timeout",
                "test_timeout_seconds",
            ):
                if scalar_k in pf:
                    _add_timeout(scalar_k, pf[scalar_k])
            _scan_table(pf.get("timeouts"))
            _scan_table(pf.get("command_timeouts"))

        v_checks = proj.get("verification_checks")
        if isinstance(v_checks, dict):
            for comp_name, comp_cfg in v_checks.items():
                if isinstance(comp_cfg, dict):
                    t_val = comp_cfg.get("timeout_seconds") or comp_cfg.get("timeout")
                    if isinstance(t_val, (int, float)) and not isinstance(t_val, bool) and t_val > 0:
                        result.setdefault(f"verification_checks.{comp_name}", int(t_val))

    # 3. Top-level [preflight] fallback
    pf_top = cfg.get("preflight")
    if isinstance(pf_top, dict):
        for scalar_k in (
            "command_timeout_seconds",
            "command_timeout",
            "default_command_timeout",
            "timeout_seconds",
            "timeout",
            "test_timeout_seconds",
        ):
            if scalar_k in pf_top:
                _add_timeout(scalar_k, pf_top[scalar_k])
        _scan_table(pf_top.get("timeouts"))
        _scan_table(pf_top.get("command_timeouts"))

    return result


def format_command_timeouts_prompt_block(
    cfg: dict[str, Any] | None = None,
    timeouts: dict[str, Any] | int | float | None = None,
) -> list[str]:
    """Build the `## Command Timeouts` Markdown block for executor/verifier prompts.

    Returns an empty list when no command timeouts are configured so existing
    projects without timeouts produce identical prompts and plan hashes.
    """
    resolved = resolve_project_command_timeouts(cfg) if cfg else {}
    if isinstance(timeouts, (int, float)) and not isinstance(timeouts, bool) and timeouts > 0:
        resolved["default"] = int(timeouts)
    elif isinstance(timeouts, dict):
        for k, v in timeouts.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                resolved[str(k)] = int(v)

    if not resolved:
        return []

    default_sec = resolved.get("default") or resolved.get("test") or max(resolved.values())
    default_ms = default_sec * 1000
    lines: list[str] = [
        "## Command Timeouts",
        "",
        f"- Per-project command timeout: `{default_sec}s` (`{default_ms}ms`). Pass `timeout={default_ms}` (ms) or `{default_sec}s` to shell/bash tool calls for test suites and builds instead of the default 120s timeout.",
    ]
    for k, sec in sorted(resolved.items()):
        lines.append(f"- **{k}**: `{sec}s` (`{sec * 1000}ms`)")
    lines.append("")
    return lines


def _is_tcp_port_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if a TCP listener accepts connections on (host, port)."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_tool_version(exe: str, version_flag: str = "--version", timeout: float = 5.0) -> str | None:
    """Run executable with version flag(s) and return first line containing a version number."""
    flags_to_try = [version_flag]
    for fallback_flag in ("--version", "-v", "-V", "version"):
        if fallback_flag not in flags_to_try:
            flags_to_try.append(fallback_flag)

    first_nonempty: str | None = None
    for flag in flags_to_try:
        try:
            argv = [exe, *flag.split()] if flag else [exe]
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
            if not combined:
                continue
            for line in combined.splitlines():
                line_s = line.strip()
                if not line_s:
                    continue
                if first_nonempty is None:
                    first_nonempty = line_s
                if parse_version_tuple(line_s) is not None:
                    return line_s
        except Exception:
            continue
    return first_nonempty


def _normalize_preflight_tool_entries(preflight_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized tool requirement dicts from `[project.preflight]`."""
    entries: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    def _add_entry(
        name: str,
        min_version: str | None = None,
        path: str | None = None,
        version_flag: str = "--version",
    ) -> None:
        clean_name = name.strip()
        if not clean_name:
            return
        min_v = str(min_version).strip() if min_version is not None else None
        if min_v in ("", "*", "any", "latest", "True", "true"):
            min_v = None
        if min_v is not None:
            min_v = re.sub(r"^(?:>=|>|==|=|v|V)\s*", "", min_v).strip() or None
        if clean_name in seen_names:
            for existing in entries:
                if existing["name"] == clean_name:
                    if min_v is not None:
                        existing["min_version"] = min_v
                    if path is not None:
                        existing["path"] = path
                    break
            return
        seen_names.add(clean_name)
        entries.append(
            {
                "name": clean_name,
                "min_version": min_v,
                "path": path,
                "version_flag": version_flag,
            }
        )

    def _parse_tool_spec(spec: Any, key_name: str | None = None) -> None:
        if isinstance(spec, bool):
            if spec and key_name:
                _add_entry(key_name, None)
            return
        if isinstance(spec, (int, float)):
            if key_name:
                _add_entry(key_name, str(spec))
            return
        if isinstance(spec, str):
            s = spec.strip()
            if not s:
                if key_name:
                    _add_entry(key_name, None)
                return
            if key_name:
                _add_entry(key_name, s)
            else:
                # String in a list: e.g. "bun", "bun >= 1.0.0", "node>=18.0", "python3 3.11"
                m = re.match(r"^([^\s><=]+)\s*(?:(?:>=|>|==|=)\s*|\s+)(v?\d+(?:\.\d+)*)$", s)
                if m:
                    _add_entry(m.group(1), m.group(2))
                else:
                    _add_entry(s, None)
            return
        if isinstance(spec, dict):
            if spec.get("enabled") is False or spec.get("required") is False:
                return
            t_name = (
                spec.get("name")
                or spec.get("tool")
                or spec.get("binary")
                or spec.get("cmd")
                or spec.get("command")
                or key_name
            )
            if not t_name:
                return
            min_v = spec.get("min_version")
            if min_v is None:
                min_v = spec.get("version")
            t_path = spec.get("path")
            v_flag = spec.get("version_flag", "--version")
            _add_entry(str(t_name), str(min_v) if min_v is not None and not isinstance(min_v, bool) else None, t_path, v_flag)

    for key in ("tools", "binaries", "required_tools", "executables"):
        raw = preflight_cfg.get(key)
        if isinstance(raw, dict):
            for k, v in raw.items():
                _parse_tool_spec(v, key_name=str(k))
        elif isinstance(raw, list):
            for item in raw:
                _parse_tool_spec(item)
        elif isinstance(raw, str):
            _parse_tool_spec(raw)

    # Also support direct tool keys under [project.preflight], e.g. `bun = "1.0.0"`
    for k, v in preflight_cfg.items():
        if k in _PREFLIGHT_RESERVED_KEYS:
            continue
        if isinstance(v, (str, bool, int, float, dict)):
            _parse_tool_spec(v, key_name=str(k))

    return entries


def _resolve_tool_executable(
    name: str,
    explicit_path: str | None,
    base_dirs: list[pathlib.Path],
) -> str | None:
    """Locate a tool binary in explicit_path, relative to base_dirs, or in PATH."""
    candidates_to_check = [explicit_path, name] if explicit_path else [name]
    for cand in candidates_to_check:
        if not cand:
            continue
        if "/" in cand or cand.startswith("."):
            p = pathlib.Path(cand).expanduser()
            if p.is_absolute():
                if p.is_file() and os.access(p, os.X_OK):
                    return str(p)
            else:
                for bdir in base_dirs:
                    rp = (bdir / p).resolve()
                    if rp.is_file() and os.access(rp, os.X_OK):
                        return str(rp)
        found = shutil.which(cand)
        if found:
            return found
        for bdir in base_dirs:
            rp = (bdir / cand).resolve()
            if rp.is_file() and os.access(rp, os.X_OK):
                return str(rp)
    return None


def _run_shell_command_with_timeout(
    command: str,
    cwd: pathlib.Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run a shell command in its own process group with a wall-clock timeout."""
    t0 = time.monotonic()
    timed_out = False
    stdout_str = ""
    stderr_str = ""
    exit_code: int | None = None

    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout_str, stderr_str = proc.communicate(timeout=timeout_seconds)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            stdout_str, stderr_str = proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            stdout_str, stderr_str = proc.communicate()
        exit_code = proc.returncode if proc.returncode is not None else -1

    duration = round(time.monotonic() - t0, 3)
    ok = (not timed_out) and (exit_code == 0)
    return {
        "command": command,
        "ok": ok,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": duration,
        "stdout": (stdout_str or "").strip(),
        "stderr": (stderr_str or "").strip(),
    }


def list_project_preflight_checks(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Return the configured `[project.preflight]` checks without executing them (side-effect-free).

    Used by `run preview` (single task, batch, and triage) so previewing a run never executes
    commands or probes host state.
    """
    if not cfg or not isinstance(cfg, dict):
        return {"configured": False, "executed": False, "checks": []}

    proj = cfg.get("project", {}) if isinstance(cfg.get("project"), dict) else {}
    pf_cfg = proj.get("preflight")
    if pf_cfg is None:
        pf_cfg = cfg.get("preflight")

    if not pf_cfg or not isinstance(pf_cfg, dict) or pf_cfg.get("enabled") is False:
        return {"configured": False, "executed": False, "checks": []}

    checks: list[dict[str, Any]] = []

    # 1. Tools / binaries
    for t_entry in _normalize_preflight_tool_entries(pf_cfg):
        t_name = t_entry["name"]
        min_ver = t_entry.get("min_version")
        t_path = t_entry.get("path")
        checks.append(
            {
                "kind": "tool",
                "name": t_name,
                "min_version": min_ver,
                "path": t_path,
                "summary": f"tool '{t_name}' >= {min_ver}" if min_ver else f"tool '{t_name}'",
            }
        )

    # 2. Free TCP ports
    raw_ports: list[Any] = []
    for pkey in ("free_ports", "ports"):
        pval = pf_cfg.get(pkey)
        if isinstance(pval, list):
            raw_ports.extend(pval)
        elif isinstance(pval, (int, str)) and not isinstance(pval, bool):
            raw_ports.append(pval)

    for p_item in raw_ports:
        host = "127.0.0.1"
        port_num: int | None = None
        if isinstance(p_item, int) and not isinstance(p_item, bool):
            port_num = p_item
        elif isinstance(p_item, str):
            s = p_item.strip()
            if ":" in s:
                h_part, p_part = s.rsplit(":", 1)
                host = h_part.strip() or "127.0.0.1"
                try:
                    port_num = int(p_part.strip())
                except ValueError:
                    port_num = None
            else:
                try:
                    port_num = int(s)
                except ValueError:
                    port_num = None
        elif isinstance(p_item, dict):
            host = str(p_item.get("host") or "127.0.0.1")
            try:
                port_num = int(p_item["port"])
            except (KeyError, TypeError, ValueError):
                port_num = None

        if port_num is not None and (1 <= port_num <= 65535):
            checks.append(
                {
                    "kind": "free_port",
                    "name": f"{host}:{port_num}",
                    "host": host,
                    "port": port_num,
                    "summary": f"free_port {host}:{port_num}",
                }
            )
        else:
            checks.append(
                {
                    "kind": "free_port",
                    "name": str(p_item),
                    "host": host,
                    "port": port_num,
                    "summary": f"free_port {p_item}",
                }
            )

    # 3. Active services
    svc_items: list[tuple[str, Any]] = []
    for skey in ("services", "active_services", "required_services"):
        sval = pf_cfg.get(skey)
        if isinstance(sval, dict):
            for k, v in sval.items():
                svc_items.append((str(k), v))
        elif isinstance(sval, list):
            for item in sval:
                if isinstance(item, dict):
                    sname = str(item.get("name") or item.get("service") or item.get("unit") or item.get("port") or "service")
                    svc_items.append((sname, item))
                elif isinstance(item, (str, int)) and not isinstance(item, bool):
                    svc_items.append((str(item), item))

    for svc_name, svc_spec in svc_items:
        if isinstance(svc_spec, bool) and not svc_spec:
            continue
        if isinstance(svc_spec, dict) and (svc_spec.get("enabled") is False or svc_spec.get("required") is False):
            continue
        checks.append(
            {
                "kind": "service",
                "name": svc_name,
                "spec": svc_spec,
                "summary": f"service '{svc_name}'",
            }
        )

    # 4. Disk space
    req_disk_bytes: int | None = None
    for mb_key in ("min_disk_mb", "disk_free_mb", "min_free_mb", "disk_space_mb"):
        val = pf_cfg.get(mb_key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            req_disk_bytes = max(req_disk_bytes or 0, int(float(val) * 1024 * 1024))
    for gb_key in ("min_disk_gb", "disk_free_gb", "min_free_gb", "disk_space_gb"):
        val = pf_cfg.get(gb_key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            req_disk_bytes = max(req_disk_bytes or 0, int(float(val) * (1024 ** 3)))

    disk_sub = pf_cfg.get("disk")
    if isinstance(disk_sub, (int, float)) and not isinstance(disk_sub, bool) and disk_sub > 0:
        req_disk_bytes = max(req_disk_bytes or 0, int(float(disk_sub) * 1024 * 1024))
    elif isinstance(disk_sub, dict):
        for mb_key in ("min_mb", "min_disk_mb", "free_mb", "min_free_mb", "mb"):
            val = disk_sub.get(mb_key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
                req_disk_bytes = max(req_disk_bytes or 0, int(float(val) * 1024 * 1024))
        for gb_key in ("min_gb", "min_disk_gb", "free_gb", "min_free_gb", "gb"):
            val = disk_sub.get(gb_key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
                req_disk_bytes = max(req_disk_bytes or 0, int(float(val) * (1024 ** 3)))

    if req_disk_bytes is not None and req_disk_bytes > 0:
        req_mb = req_disk_bytes / (1024 * 1024)
        checks.append(
            {
                "kind": "disk",
                "name": "disk_space",
                "required_bytes": req_disk_bytes,
                "summary": f"disk_space >= {req_mb:.1f} MB",
            }
        )

    # 5. Custom preflight commands
    raw_cmds = pf_cfg.get("commands")
    if isinstance(raw_cmds, str):
        raw_cmds = [raw_cmds]
    if isinstance(raw_cmds, list):
        for cmd_item in raw_cmds:
            if not isinstance(cmd_item, str) or not cmd_item.strip():
                continue
            c_str = cmd_item.strip()
            checks.append(
                {
                    "kind": "command",
                    "name": c_str,
                    "command": c_str,
                    "summary": f"command: {c_str}",
                }
            )

    return {
        "configured": True,
        "executed": False,
        "checks": checks,
    }


def run_project_preflight(
    cfg: dict[str, Any] | None,
    workspace: pathlib.Path | str | None = None,
    target_repo: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Execute `[project.preflight]` checks on the current host (Task 19.7).

    Checks:
      1. Required tools/binaries and optional minimum versions (`tools` / `binaries`)
      2. Free TCP ports (`free_ports` / `ports`)
      3. Active services (`services` / `active_services`: TCP port, HTTP URL, command, or systemd/process)
      4. Available disk space (`min_disk_mb` / `min_disk_gb` / `disk`)
      5. Custom preflight shell commands (`commands`)
    """
    ws = pathlib.Path(workspace or ".").resolve()
    repo = pathlib.Path(target_repo).resolve() if target_repo else ws
    base_dirs: list[pathlib.Path] = [repo]
    if ws != repo:
        base_dirs.append(ws)

    if not cfg or not isinstance(cfg, dict):
        return {"ok": True, "configured": False, "executed": True, "checks": [], "failures": []}

    proj = cfg.get("project", {}) if isinstance(cfg.get("project"), dict) else {}
    pf_cfg = proj.get("preflight")
    if pf_cfg is None:
        pf_cfg = cfg.get("preflight")

    if not pf_cfg or not isinstance(pf_cfg, dict) or pf_cfg.get("enabled") is False:
        return {"ok": True, "configured": False, "executed": True, "checks": [], "failures": []}

    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    # 1. Tools / binaries
    for t_entry in _normalize_preflight_tool_entries(pf_cfg):
        t_name = t_entry["name"]
        min_ver = t_entry.get("min_version")
        t_path = t_entry.get("path")
        v_flag = t_entry.get("version_flag") or "--version"

        exe = _resolve_tool_executable(t_name, t_path, base_dirs)
        if not exe:
            msg = f"Required tool '{t_name}' not found on host"
            checks.append(
                {
                    "kind": "tool",
                    "name": t_name,
                    "ok": False,
                    "path": None,
                    "version": None,
                    "min_version": min_ver,
                    "message": msg,
                }
            )
            failures.append(msg)
            continue

        if min_ver:
            raw_ver = _probe_tool_version(exe, version_flag=v_flag)
            actual_tuple = parse_version_tuple(raw_ver)
            min_tuple = parse_version_tuple(min_ver)
            if min_tuple is not None and (actual_tuple is None or not compare_versions(actual_tuple, min_tuple)):
                detected_str = ".".join(str(x) for x in actual_tuple) if actual_tuple else (raw_ver or "unknown")
                msg = (
                    f"Required tool '{t_name}' version '{detected_str}' is below minimum required version '{min_ver}'"
                )
                checks.append(
                    {
                        "kind": "tool",
                        "name": t_name,
                        "ok": False,
                        "path": exe,
                        "version": detected_str,
                        "min_version": min_ver,
                        "message": msg,
                    }
                )
                failures.append(msg)
                continue
            detected_str = ".".join(str(x) for x in actual_tuple) if actual_tuple else (raw_ver or "ok")
            checks.append(
                {
                    "kind": "tool",
                    "name": t_name,
                    "ok": True,
                    "path": exe,
                    "version": detected_str,
                    "min_version": min_ver,
                    "message": f"Tool '{t_name}' found at {exe} (version {detected_str} >= {min_ver})",
                }
            )
        else:
            checks.append(
                {
                    "kind": "tool",
                    "name": t_name,
                    "ok": True,
                    "path": exe,
                    "version": None,
                    "min_version": None,
                    "message": f"Tool '{t_name}' found at {exe}",
                }
            )

    # 2. Free TCP ports
    raw_ports: list[Any] = []
    for pkey in ("free_ports", "ports"):
        pval = pf_cfg.get(pkey)
        if isinstance(pval, list):
            raw_ports.extend(pval)
        elif isinstance(pval, (int, str)) and not isinstance(pval, bool):
            raw_ports.append(pval)

    for p_item in raw_ports:
        host = "127.0.0.1"
        port_num: int | None = None
        if isinstance(p_item, int) and not isinstance(p_item, bool):
            port_num = p_item
        elif isinstance(p_item, str):
            s = p_item.strip()
            if ":" in s:
                h_part, p_part = s.rsplit(":", 1)
                host = h_part.strip() or "127.0.0.1"
                try:
                    port_num = int(p_part.strip())
                except ValueError:
                    port_num = None
            else:
                try:
                    port_num = int(s)
                except ValueError:
                    port_num = None
        elif isinstance(p_item, dict):
            host = str(p_item.get("host") or "127.0.0.1")
            try:
                port_num = int(p_item["port"])
            except (KeyError, TypeError, ValueError):
                port_num = None

        if port_num is None or not (1 <= port_num <= 65535):
            msg = f"Invalid free_ports entry {p_item!r}"
            checks.append({"kind": "free_port", "name": str(p_item), "ok": False, "message": msg})
            failures.append(msg)
            continue

        in_use = _is_tcp_port_listening(host, port_num)
        if in_use:
            msg = f"Required free port {port_num} ({host}:{port_num}) is already in use"
            checks.append(
                {
                    "kind": "free_port",
                    "name": f"{host}:{port_num}",
                    "port": port_num,
                    "host": host,
                    "ok": False,
                    "message": msg,
                }
            )
            failures.append(msg)
        else:
            checks.append(
                {
                    "kind": "free_port",
                    "name": f"{host}:{port_num}",
                    "port": port_num,
                    "host": host,
                    "ok": True,
                    "message": f"Port {port_num} ({host}:{port_num}) is free",
                }
            )

    # 3. Active services
    svc_items: list[tuple[str, Any]] = []
    for skey in ("services", "active_services", "required_services"):
        sval = pf_cfg.get(skey)
        if isinstance(sval, dict):
            for k, v in sval.items():
                svc_items.append((str(k), v))
        elif isinstance(sval, list):
            for item in sval:
                if isinstance(item, dict):
                    sname = str(item.get("name") or item.get("service") or item.get("unit") or item.get("port") or "service")
                    svc_items.append((sname, item))
                elif isinstance(item, (str, int)) and not isinstance(item, bool):
                    svc_items.append((str(item), item))

    for svc_name, svc_spec in svc_items:
        if isinstance(svc_spec, bool):
            if not svc_spec:
                continue
            svc_spec = svc_name

        svc_ok = False
        svc_detail = ""

        if isinstance(svc_spec, int):
            svc_ok = _is_tcp_port_listening("127.0.0.1", svc_spec, timeout=1.0)
            svc_detail = f"127.0.0.1:{svc_spec}"
        elif isinstance(svc_spec, str):
            s = svc_spec.strip()
            if s.startswith(("http://", "https://")):
                svc_detail = s
                try:
                    req = urllib.request.Request(s, method="GET")
                    with urllib.request.urlopen(req, timeout=2.0) as resp:
                        svc_ok = 200 <= resp.status < 400
                except Exception as exc:
                    svc_ok = False
                    svc_detail = f"{s} ({exc})"
            elif re.match(r"^(?:[A-Za-z0-9._-]+)?:?\d+$", s) and (":" in s or s.isdigit()):
                if ":" in s:
                    h_part, p_part = s.rsplit(":", 1)
                    h_str = h_part.strip() or "127.0.0.1"
                    p_int = int(p_part.strip())
                else:
                    h_str = "127.0.0.1"
                    p_int = int(s)
                svc_ok = _is_tcp_port_listening(h_str, p_int, timeout=1.0)
                svc_detail = f"{h_str}:{p_int}"
            else:
                unit = svc_name if s in ("active", "running", "true", "True", "*") else s
                svc_detail = unit
                systemctl_bin = shutil.which("systemctl")
                if systemctl_bin:
                    r_sys = subprocess.run(
                        [systemctl_bin, "is-active", "--quiet", unit],
                        capture_output=True,
                        timeout=3.0,
                        check=False,
                    )
                    if r_sys.returncode == 0:
                        svc_ok = True
                    else:
                        r_usr = subprocess.run(
                            [systemctl_bin, "--user", "is-active", "--quiet", unit],
                            capture_output=True,
                            timeout=3.0,
                            check=False,
                        )
                        if r_usr.returncode == 0:
                            svc_ok = True
                if not svc_ok and shutil.which("pgrep"):
                    r_pg = subprocess.run(
                        ["pgrep", "-x", unit],
                        capture_output=True,
                        timeout=3.0,
                        check=False,
                    )
                    if r_pg.returncode == 0:
                        svc_ok = True
        elif isinstance(svc_spec, dict):
            if svc_spec.get("enabled") is False or svc_spec.get("required") is False:
                continue
            if "port" in svc_spec:
                h_str = str(svc_spec.get("host") or "127.0.0.1")
                p_int = int(svc_spec["port"])
                svc_ok = _is_tcp_port_listening(h_str, p_int, timeout=1.0)
                svc_detail = f"{h_str}:{p_int}"
            elif "url" in svc_spec:
                u_str = str(svc_spec["url"])
                svc_detail = u_str
                try:
                    req = urllib.request.Request(u_str, method="GET")
                    with urllib.request.urlopen(req, timeout=2.0) as resp:
                        svc_ok = 200 <= resp.status < 400
                except Exception as exc:
                    svc_ok = False
                    svc_detail = f"{u_str} ({exc})"
            elif "command" in svc_spec or "cmd" in svc_spec:
                cmd_str = str(svc_spec.get("command") or svc_spec.get("cmd"))
                svc_detail = cmd_str
                cmd_res = _run_shell_command_with_timeout(cmd_str, repo, timeout_seconds=5.0)
                svc_ok = cmd_res["ok"]
            else:
                unit = str(svc_spec.get("systemd") or svc_spec.get("unit") or svc_spec.get("service") or svc_name)
                svc_detail = unit
                systemctl_bin = shutil.which("systemctl")
                if systemctl_bin:
                    r_sys = subprocess.run(
                        [systemctl_bin, "is-active", "--quiet", unit],
                        capture_output=True,
                        timeout=3.0,
                        check=False,
                    )
                    if r_sys.returncode == 0:
                        svc_ok = True
                    else:
                        r_usr = subprocess.run(
                            [systemctl_bin, "--user", "is-active", "--quiet", unit],
                            capture_output=True,
                            timeout=3.0,
                            check=False,
                        )
                        if r_usr.returncode == 0:
                            svc_ok = True
                if not svc_ok and shutil.which("pgrep"):
                    r_pg = subprocess.run(
                        ["pgrep", "-x", unit],
                        capture_output=True,
                        timeout=3.0,
                        check=False,
                    )
                    if r_pg.returncode == 0:
                        svc_ok = True

        if svc_ok:
            checks.append(
                {
                    "kind": "service",
                    "name": svc_name,
                    "ok": True,
                    "message": f"Service '{svc_name}' is active ({svc_detail})",
                }
            )
        else:
            msg = f"Required service '{svc_name}' is not active ({svc_detail})"
            checks.append(
                {
                    "kind": "service",
                    "name": svc_name,
                    "ok": False,
                    "message": msg,
                }
            )
            failures.append(msg)

    # 4. Disk space
    req_disk_bytes: int | None = None
    disk_check_path = repo
    for mb_key in ("min_disk_mb", "disk_free_mb", "min_free_mb", "disk_space_mb"):
        val = pf_cfg.get(mb_key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            req_disk_bytes = max(req_disk_bytes or 0, int(float(val) * 1024 * 1024))
    for gb_key in ("min_disk_gb", "disk_free_gb", "min_free_gb", "disk_space_gb"):
        val = pf_cfg.get(gb_key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            req_disk_bytes = max(req_disk_bytes or 0, int(float(val) * (1024 ** 3)))

    disk_sub = pf_cfg.get("disk")
    if isinstance(disk_sub, (int, float)) and not isinstance(disk_sub, bool) and disk_sub > 0:
        req_disk_bytes = max(req_disk_bytes or 0, int(float(disk_sub) * 1024 * 1024))
    elif isinstance(disk_sub, dict):
        if disk_sub.get("path"):
            p_cand = pathlib.Path(str(disk_sub["path"])).expanduser()
            disk_check_path = p_cand if p_cand.is_absolute() else (repo / p_cand).resolve()
        for mb_key in ("min_mb", "min_disk_mb", "free_mb", "min_free_mb", "mb"):
            val = disk_sub.get(mb_key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
                req_disk_bytes = max(req_disk_bytes or 0, int(float(val) * 1024 * 1024))
        for gb_key in ("min_gb", "min_disk_gb", "free_gb", "min_free_gb", "gb"):
            val = disk_sub.get(gb_key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
                req_disk_bytes = max(req_disk_bytes or 0, int(float(val) * (1024 ** 3)))

    if req_disk_bytes is not None and req_disk_bytes > 0:
        target_for_du = disk_check_path if disk_check_path.exists() else ws
        usage = shutil.disk_usage(str(target_for_du))
        free_mb = usage.free / (1024 * 1024)
        req_mb = req_disk_bytes / (1024 * 1024)
        if usage.free < req_disk_bytes:
            msg = (
                f"Insufficient disk space on '{target_for_du}': "
                f"{free_mb:.1f} MB free, minimum required is {req_mb:.1f} MB"
            )
            checks.append(
                {
                    "kind": "disk",
                    "name": "disk_space",
                    "ok": False,
                    "free_bytes": usage.free,
                    "required_bytes": req_disk_bytes,
                    "message": msg,
                }
            )
            failures.append(msg)
        else:
            checks.append(
                {
                    "kind": "disk",
                    "name": "disk_space",
                    "ok": True,
                    "free_bytes": usage.free,
                    "required_bytes": req_disk_bytes,
                    "message": f"Disk space ok ({free_mb:.1f} MB free >= {req_mb:.1f} MB required)",
                }
            )

    # 5. Custom preflight commands
    raw_cmds = pf_cfg.get("commands")
    if isinstance(raw_cmds, str):
        raw_cmds = [raw_cmds]
    if isinstance(raw_cmds, list):
        timeouts_map = resolve_project_command_timeouts(cfg)
        cmd_timeout = float(timeouts_map.get("default") or 30.0)
        for cmd_item in raw_cmds:
            if not isinstance(cmd_item, str) or not cmd_item.strip():
                continue
            c_res = _run_shell_command_with_timeout(cmd_item.strip(), repo, timeout_seconds=cmd_timeout)
            if c_res["ok"]:
                checks.append(
                    {
                        "kind": "command",
                        "name": cmd_item.strip(),
                        "ok": True,
                        "exit_code": 0,
                        "message": f"Preflight command succeeded: {cmd_item.strip()}",
                    }
                )
            else:
                detail = c_res["stderr"] or c_res["stdout"] or f"exit code {c_res['exit_code']}"
                if c_res["timed_out"]:
                    detail = f"timed out after {cmd_timeout}s"
                msg = f"Preflight command '{cmd_item.strip()}' failed ({detail})"
                checks.append(
                    {
                        "kind": "command",
                        "name": cmd_item.strip(),
                        "ok": False,
                        "exit_code": c_res["exit_code"],
                        "message": msg,
                    }
                )
                failures.append(msg)

    return {
        "ok": len(failures) == 0,
        "configured": True,
        "executed": True,
        "checks": checks,
        "failures": failures,
    }


def run_verification_checks(
    cfg: dict[str, Any] | None,
    workspace: pathlib.Path | str | None = None,
    *,
    selected_checks: list[str] | None = None,
    timeout_override: float | None = None,
    fail_fast: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute `[project.verification_checks]` commands (Task 19.7 `ai-orch verify-checks`)."""
    ws = pathlib.Path(workspace or ".").resolve()
    proj = cfg.get("project", {}) if (cfg and isinstance(cfg.get("project"), dict)) else {}
    v_checks = proj.get("verification_checks")
    if v_checks is None and isinstance(cfg, dict):
        v_checks = cfg.get("verification_checks")
    if not isinstance(v_checks, dict):
        v_checks = {}

    timeouts_map = resolve_project_command_timeouts(cfg)
    default_timeout = float(
        timeout_override
        if (timeout_override is not None and timeout_override > 0)
        else (timeouts_map.get("verification") or timeouts_map.get("test") or timeouts_map.get("default") or 120.0)
    )

    failures: list[str] = []
    check_results: list[dict[str, Any]] = []

    if selected_checks:
        wanted: list[str] = []
        for s in selected_checks:
            for part in str(s).split(","):
                p = part.strip()
                if p and p not in wanted:
                    wanted.append(p)
        missing = [name for name in wanted if name not in v_checks]
        if missing:
            for m in missing:
                failures.append(f"Verification check '{m}' not found in [project.verification_checks]")
            return {
                "ok": False,
                "workspace": str(ws),
                "timeout_seconds": default_timeout,
                "passed_count": 0,
                "failed_count": len(missing),
                "checks": [],
                "failures": failures,
            }
        items_to_run = [(name, v_checks[name]) for name in wanted]
    else:
        items_to_run = list(v_checks.items())

    passed_count = 0
    failed_count = 0

    for comp_name, comp_cfg in items_to_run:
        desc = ""
        cmds: list[str] = []
        chk_timeout = default_timeout
        chk_cwd = ws

        if isinstance(comp_cfg, dict):
            desc = str(comp_cfg.get("description") or "")
            raw_cmds = comp_cfg.get("commands")
            if raw_cmds is None and "command" in comp_cfg:
                raw_cmds = comp_cfg.get("command")
            if isinstance(raw_cmds, str):
                cmds = [raw_cmds]
            elif isinstance(raw_cmds, list):
                cmds = [str(c) for c in raw_cmds if str(c).strip()]
            if timeout_override is None:
                c_to = comp_cfg.get("timeout_seconds") or comp_cfg.get("timeout")
                if isinstance(c_to, (int, float)) and not isinstance(c_to, bool) and c_to > 0:
                    chk_timeout = float(c_to)
            if comp_cfg.get("cwd"):
                cand_cwd = pathlib.Path(str(comp_cfg["cwd"])).expanduser()
                chk_cwd = cand_cwd if cand_cwd.is_absolute() else (ws / cand_cwd).resolve()
        elif isinstance(comp_cfg, list):
            cmds = [str(c) for c in comp_cfg if str(c).strip()]
        elif isinstance(comp_cfg, str) and comp_cfg.strip():
            cmds = [comp_cfg.strip()]

        cmd_outcomes: list[dict[str, Any]] = []
        comp_ok = True

        for cmd_str in cmds:
            if dry_run:
                cmd_outcomes.append(
                    {
                        "command": cmd_str,
                        "ok": True,
                        "dry_run": True,
                        "exit_code": 0,
                        "timed_out": False,
                        "duration_seconds": 0.0,
                        "stdout": "",
                        "stderr": "",
                    }
                )
                continue

            res = _run_shell_command_with_timeout(cmd_str, chk_cwd, timeout_seconds=chk_timeout)
            cmd_outcomes.append(res)
            if not res["ok"]:
                comp_ok = False
                if res["timed_out"]:
                    failures.append(f"[{comp_name}] Command timed out after {chk_timeout}s: {cmd_str}")
                else:
                    err_snip = res["stderr"] or res["stdout"] or f"exit {res['exit_code']}"
                    failures.append(f"[{comp_name}] Command failed (exit {res['exit_code']}): {cmd_str} — {err_snip}")
                if fail_fast:
                    break

        if comp_ok:
            passed_count += 1
        else:
            failed_count += 1

        check_results.append(
            {
                "name": comp_name,
                "description": desc,
                "ok": comp_ok,
                "timeout_seconds": chk_timeout,
                "cwd": str(chk_cwd),
                "commands": cmd_outcomes,
            }
        )

        if not comp_ok and fail_fast:
            break

    return {
        "ok": failed_count == 0 and len(failures) == 0,
        "workspace": str(ws),
        "timeout_seconds": default_timeout,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "checks": check_results,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Catalog & Topology Helpers
# ---------------------------------------------------------------------------

_KILO_MODELS_CACHE: set[str] | None = None


def get_kilo_models(timeout: float = 20.0) -> set[str] | None:
    """Return set of model IDs from `kilo models`, or None if command fails/unavailable."""
    global _KILO_MODELS_CACHE
    if _KILO_MODELS_CACHE is not None:
        return _KILO_MODELS_CACHE
    try:
        proc = subprocess.run(
            ["kilo", "models"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode == 0:
            models = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
            _KILO_MODELS_CACHE = models
            return _KILO_MODELS_CACHE
    except Exception:
        pass
    return None


def reset_kilo_models_cache(cached: set[str] | None = None) -> None:
    """Reset or preset the in-memory cache of `kilo models`."""
    global _KILO_MODELS_CACHE
    _KILO_MODELS_CACHE = cached


def get_active_tool_ids(cfg: dict[str, Any]) -> list[str]:
    """Return ordered list of tool IDs relevant to the active topology and verification."""
    proj = cfg.get("project", {})
    routing = cfg.get("routing", {})
    ver = cfg.get("verification", {})
    tools = cfg.get("tools", {})

    orchestrator_id = proj.get("primary_orchestrator") or routing.get("default_orchestrator", "kilo")
    executor_id = routing.get("default_executor", orchestrator_id)
    v_mode = ver.get("default_mode", "cross-agent")

    active_tool_ids: list[str] = []
    for tid in (orchestrator_id, executor_id):
        if tid in tools and tid not in active_tool_ids:
            active_tool_ids.append(tid)

    if v_mode in ("cross-agent", "panel"):
        check_list = ver.get("cross_agent_order", []) if v_mode == "cross-agent" else ver.get("panel_reviewers", [])
        for item in check_list:
            t = str(item).split(":", 1)[0]
            if t in tools and tools[t].get("enabled", True) and t not in active_tool_ids:
                active_tool_ids.append(t)

    return active_tool_ids


# ---------------------------------------------------------------------------
# AGENTS.md Renderer (modeled on ~/works/ricerca_auto/AGENTS.md)
# ---------------------------------------------------------------------------

def render_agents_md_block(
    cfg: dict[str, Any],
    workspace: pathlib.Path | None = None,
    global_path: pathlib.Path | None = None,
) -> str:
    proj = cfg.get("project", {})
    routing = cfg.get("routing", {})
    ver = cfg.get("verification", {})
    tools = cfg.get("tools", {})

    ws = workspace or pathlib.Path(".")
    proj_cfg_path = find_project_config_path(ws, global_path, for_write=True)
    gpath = global_path or default_global_config_path()

    orchestrator_id = proj.get("primary_orchestrator") or routing.get("default_orchestrator", "kilo")
    executor_id = routing.get("default_executor", orchestrator_id)
    orch_tool = tools.get(orchestrator_id, {})
    exec_tool = tools.get(executor_id, orch_tool)

    # Determine dispatch tools description:
    # - When orchestrator == executor (Single-Framework Native mode): only native mechanisms are shown.
    # - When orchestrator != executor (Cross-Framework MCP mode): MCP implement tool is primary.
    same_framework = orchestrator_id == executor_id

    agents_md_cfg = cfg.get("agents_md", {})
    if not isinstance(agents_md_cfg, dict):
        agents_md_cfg = {}
    strict_main_session = bool(
        agents_md_cfg.get("strict_main_session", False)
        or proj.get("strict_main_session", False)
        or proj.get("agents_md", {}).get("strict_main_session", False)
    )

    if strict_main_session:
        main_role_phrase = (
            "acts strictly as the **Architect & Orchestrator** (discovery, task specification, "
            "parallel dispatch, verification, and integration), delegating implementation and "
            "heavy exploration to isolated **Worktree sessions** and **Subagents**."
        )
        rule_1_heading = "### Rule 1: Keep the Main Session Free (Orchestrate, Don't Implement)"
        rule_1_body = (
            "- The main session exists to **analyze requirements, design task specs, "
            "orchestrate parallel execution, and evaluate/verify results** with the user.\n"
            "- **Do not perform feature implementation or multi-file coding in the main session**, "
            'even when a change looks quick ("it\'s small, I\'ll just do it" is forbidden).\n'
            "- **Only exception:** During Phase 5 (Verification), the Architect may apply a "
            "trivial 1–5 line fix (e.g., typo, missing import) directly in the Executor's "
            "worktree rather than doing a full round-trip. Any logic or multi-line change must "
            "be bounced back to the Executor session.\n"
            "- **Capture emergent work immediately:** If a bug, follow-up, or side requirement "
            "surfaces mid-conversation and won't be finished in the current turn, record it in "
            "`tasks/` (`task-pipeline`) and update `tasks/00-INDEX.md` before continuing. "
            "Keep the main session's context lean.\n"
            "- **Register as Orchestrator & Heartbeat:** When orchestrating in a workspace "
            "with `ai-orch` installed, register this session with `ai-orch sessions register --role orchestrator` "
            "and send periodic heartbeats (`ai-orch sessions heartbeat <session_id>`). Interactive sessions (e.g. Claude Code) "
            "do not send automatic heartbeats: emit a heartbeat on each turn or periodic check. Note that a "
            '"stale" status for an active interactive holder indicates idle time between prompts, not absence.'
        )
    else:
        main_role_phrase = (
            "acts primarily as the **Architect & Orchestrator** (discovery, task specification, "
            "parallel dispatch, verification, and integration), delegating larger implementation "
            "work and heavy exploration to isolated **Worktree sessions** and **Subagents**."
        )
        rule_1_heading = "### Rule 1: Focus the Main Session on Architecture & Orchestration"
        rule_1_body = (
            "- The main session focuses on **analyzing requirements, designing task specs, "
            "orchestrating execution, and evaluating/verifying results** with the user.\n"
            "- **Prefer delegating multi-file implementations, large refactors, or parallel tasks** "
            "to isolated worktrees or subagents to keep the main session context clean and focused. "
            "Small, direct adjustments and surgical edits may be performed in the main session "
            "when appropriate.\n"
            "- **Capture emergent work immediately:** If a bug, follow-up, or side requirement "
            "surfaces mid-conversation and won't be finished in the current turn, record it in "
            "`tasks/` (`task-pipeline`) and update `tasks/00-INDEX.md` before continuing. "
            "Keep the main session's context lean.\n"
            "- **Register as Orchestrator & Heartbeat:** When orchestrating in a workspace "
            "with `ai-orch` installed, register this session with `ai-orch sessions register --role orchestrator` "
            "and send periodic heartbeats (`ai-orch sessions heartbeat <session_id>`). Interactive sessions (e.g. Claude Code) "
            "do not send automatic heartbeats: emit a heartbeat on each turn or periodic check. Note that a "
            '"stale" status for an active interactive holder indicates idle time between prompts, not absence.'
        )

    if same_framework:
        orch_skill_line = (
            "- **`orchestration-workflow`** — Core 6-phase Architect/Executor loop "
            "(Discovery → Isolation → Delegation → Monitoring → Verification → Closure & Merge)."
        )
    else:
        mcp_srv = exec_tool.get("mcp_server", "")
        if mcp_srv == "kilo-mcp":
            mcp_skill_name = "kilo-mcp-orchestrator"
        elif mcp_srv:
            mcp_skill_name = f"{mcp_srv}-orchestrator"
        else:
            mcp_skill_name = "orchestration-workflow"
        orch_skill_line = (
            f"- **`orchestration-workflow`** (or **`{mcp_skill_name}`** when driving via MCP) — "
            "Core 6-phase Architect/Executor loop (Discovery → Isolation → Delegation → "
            "Monitoring → Verification → Closure & Merge)."
        )

    domain_skills = proj.get("domain_skills", [])
    domain_skill_lines = []
    for ds in domain_skills:
        ds_name = ds.get("name", "domain-skill")
        ds_path = ds.get("path", "")
        ds_when = ds.get("when_to_use", "Domain-specific tasks.")
        path_part = f" (`{ds_path}`)" if ds_path else ""
        domain_skill_lines.append(f"- **`{ds_name}`**{path_part} — {ds_when}")
    domain_skill_section = "\n".join(domain_skill_lines)
    if domain_skill_section:
        domain_skill_section = "\n" + domain_skill_section

    isolation = proj.get("isolation", {})
    shared_dbs = isolation.get("shared_databases", [])
    shared_ports = isolation.get("shared_ports", [])
    worker_ports = isolation.get("worker_port_range", [])
    conflict_files = isolation.get("conflict_prone_files", [])
    registries = isolation.get("zero_conflict_registries", [])

    conflict_hint = (
        f" (e.g., {', '.join(f'`{f}`' for f in conflict_files)})"
        if conflict_files
        else ""
    )
    registry_hint = (
        f" or use the zero-conflict registry pattern ({', '.join(f'`{r}`' for r in registries)})"
        if registries
        else ""
    )

    isolation_bullets = []
    if shared_dbs:
        dbs_str = ", ".join(f"`{d}`" for d in shared_dbs)
        isolation_bullets.append(
            f"  - **Databases ({dbs_str}):** Delegated tasks must **never** mutate or lock live databases "
            "during testing. Always use a disposable copy or ephemeral test DB for verification."
        )
    if shared_ports or worker_ports:
        ports_str = ", ".join(f"`:{p}`" for p in shared_ports) if shared_ports else "default ports"
        range_str = (
            f" (assign worker ports from `{worker_ports[0]}..{worker_ports[1]}`)"
            if len(worker_ports) == 2
            else ""
        )
        isolation_bullets.append(
            f"  - **Ports & Containers ({ports_str}):** If parallel tasks start a server/container, "
            f"assign each task a distinct port in the task spec{range_str} so they do not collide."
        )
    isolation_bullets.append(
        "  - **Git Config (`.git/config`):** Shared across all worktrees. Delegated tasks must never run "
        "`git config` or install hooks automatically."
    )
    isolation_block = "\n".join(isolation_bullets)

    # Dispatch mechanisms for Rule 3
    if same_framework:
        worktree_mech = f'`{orch_tool.get("native_worktree_tool", "worktree")}`'
        sub_tool = orch_tool.get("native_subagent_tool", "subagent")
        if orchestrator_id == "kilo":
            subagent_mech = f'`{sub_tool}` (`explore` or `general`)'
        else:
            subagent_mech = f'`{sub_tool}`'
        local_mech = f'`{orch_tool.get("native_local_tool", "local session")}`'
    else:
        mcp_impl = exec_tool.get("mcp_implement_tool")
        if mcp_impl:
            worktree_mech = f'`{mcp_impl}(isolation="worktree")`'
            local_mech = f'`{mcp_impl}(continue_session_id=...)`'
        else:
            worktree_mech = f'`{orch_tool.get("native_worktree_tool", "worktree")}`'
            local_mech = f'`{orch_tool.get("native_local_tool", "local session")}`'

        sub_tool = orch_tool.get("native_subagent_tool", "subagent")
        if orchestrator_id == "kilo":
            subagent_mech = f'`{sub_tool}` (`explore` or `general`)'
        else:
            subagent_mech = f'`{sub_tool}`'

    # Build Role-to-Model table for the active executor/orchestrator tools
    active_tool_ids = get_active_tool_ids(cfg)

    role_rows = []
    for prof in PROFILES:
        short_desc, typical_tasks = PROFILE_DESCRIPTIONS[prof]
        model_cells = []
        for tid in active_tool_ids:
            pentry = tools.get(tid, {}).get("profiles", {}).get(prof, {})
            model_id = pentry.get("model")
            if not model_id:
                continue
            mod_var = pentry.get("variant") or pentry.get("effort")
            var_str = f" (`{mod_var}`)" if mod_var else ""
            label = f"**{tid}**: `{model_id}`{var_str}" if len(active_tool_ids) > 1 else f"`{model_id}`{var_str}"
            model_cells.append(label)
        models_col = "<br>".join(model_cells) if model_cells else "*(unconfigured)*"
        role_rows.append(
            f"| **`{prof}`** *({short_desc})* | {models_col} | {typical_tasks} |"
        )
    role_table = "\n".join(role_rows)

    # Verification checks
    v_mode = ver.get("default_mode", "cross-agent")
    cross_order = ", ".join(f"`{x}`" for x in ver.get("cross_agent_order", []))
    v_checks = proj.get("verification_checks", {})
    v_check_lines = []
    if isinstance(v_checks, dict) and v_checks:
        for comp_name, comp_cfg in v_checks.items():
            desc = comp_cfg.get("description", "")
            cmds = comp_cfg.get("commands", [])
            cmd_str = "; ".join(f"`{c}`" for c in cmds)
            sep = ": " if desc and cmd_str else ""
            v_check_lines.append(f"     - **{comp_name}**: {desc}{sep}{cmd_str}".rstrip())
    else:
        v_check_lines.append(
            "     - Run the project's build, lint, and test commands against a disposable environment."
        )
    v_checks_block = "\n".join(v_check_lines)

    # Monitoring mechanism
    if not same_framework and exec_tool.get("mcp_wait_tool"):
        wait_tool = exec_tool["mcp_wait_tool"]
        monitor_mech = f" (or await via `{wait_tool}` / background completion watcher)"
    else:
        monitor_mech = " (via background completion watcher or status checks)"

    return f"""{BEGIN_MARKER}
# Agent Orchestration & Development Guidelines (`AGENTS.md`)

> **Managed by `ai-orchestration` (`orchestration_config.py render-agents-md`).**
> Edit `{proj_cfg_path}` (project) or `{gpath}` (global) and re-run `render-agents-md --apply` to update.

This repository uses an **Architect / Executor** development workflow (`primary_orchestrator = "{orchestrator_id}"`, `default_executor = "{executor_id}"`, `verification_mode = "{v_mode}"`). The **main session** {main_role_phrase}

---

## 1. Required Skills

Load and follow these skills whenever planning, delegating, executing, or reviewing work:

{orch_skill_line}
- **`task-spec-authoring`** — Authoring unambiguous, grounded task specs (`focus_files`, caller tracing, negative-claim rule, disjoint parallel write scopes, one-task-one-commit, risk-calibrated verification).
- **`task-pipeline`** — Structuring multi-task initiatives, specs, and emergent mid-session tasks inside `tasks/` (`00-INDEX.md`, `CONTEXT.md`, `specs/`, `NN-<slug>/plan.md`, `T###-<slug>`).
- **`task-worktree-ops`** — Operational git/worktree mechanics for inspecting, fixing, and merging Executor worktrees safely without racing active sessions.
- **`executor-contract`** — Behavioral contract for all delegated Executor sessions (zero interactivity, strict scope adherence, real verification before reporting, structured `Final Report`).
- **`conflict-resolver`** — Resolving merge conflicts across parallel Executor branches while preserving the semantics of each feature.
- **`orchestration-setup`** — Mapping abstract role profiles (`deep-reasoning`, `orchestration`, `bulk-execution`, `exploration`) to concrete models and reasoning variants.{domain_skill_section}

---

## 2. Core Operating Rules

{rule_1_heading}

{rule_1_body}

### Rule 2: Define Execution Tasks Before Delegating

Every delegated unit of work must have a well-defined specification (inline in the delegation prompt for a single self-contained task, or as a task file in `tasks/` for multi-step/parallel initiatives) containing:

1. **Goal & Non-Goals:** Exact outcome expected and explicit exclusions to prevent scope creep.
2. **Grounded `focus_files` & Callers:** Real file paths and symbol/line references verified via `grep`/`read` (never guessed). Instruct the Executor to re-`grep` if line numbers may have shifted. Trace all callers of any modified function or API route.
3. **Disjoint Write Scope (for Parallel Batches):**
   - Assign each parallel task an explicit, non-overlapping file/directory scope.
   - If multiple tasks must touch a shared file{conflict_hint}, either serialize those tasks, pre-assign exact sections/symbols{registry_hint}.
4. **One Task = One Commit:** Instruct the Executor to create a single, atomic commit scoped strictly to its task.
5. **Runnable Verification Criteria:** Concrete commands the Executor must run before reporting `delivered`. If correctness relies on a **negative claim** ("X is unused / dead code"), mandate a full regression check across the codebase.

### Rule 3: Delegate Maximum Work & Evaluate Worktree vs. Local/Subtask Isolation

Before dispatching, explicitly evaluate whether the task requires **Git Worktree isolation** or can run as a **same-tree Subagent / Local session**:

| Execution Mode | Tool / Mechanism | When to Use |
| :--- | :--- | :--- |
| **Isolated Git Worktree** *(Default for parallel code changes)* | {worktree_mech} | Parallel implementation tasks modifying tracked files; multi-file features or refactors; comparing alternative implementations; long-running implementation work while keeping the main session clean. |
| **Background / Foreground Subagent** *(Read-only or strictly disjoint single-file work)* | {subagent_mech} | Codebase discovery, caller tracing, architectural analysis, **independent blind review of a draft spec or delivered task**, or strictly isolated single-file creation when no other git writer is active. |
| **Local / Follow-up Session** | {local_mech} | Follow-up steering inside an already-created worktree or single sequential task when explicitly requested in the current checkout. |

**Isolation Safety Checks (Shared Host Resources Are NOT Isolated by Worktrees):**

- **Never run concurrent code-modifying tasks in the same working tree** unless their write scopes are 100% file-disjoint and neither runs git mutations while the other is active. When in doubt, use worktree isolation.
{isolation_block}

### Rule 4: Select the Right Model & Reasoning Effort per Task

When dispatching tasks, explicitly select the `model` and reasoning effort/variant matching the task's role profile (configured in `orchestration.toml`):

| Role Profile | Configured Model & Variant / Effort | Typical Tasks |
| :--- | :--- | :--- |
{role_table}

---

## 3. Orchestration Lifecycle & Cross-Agent Verification Gate

Track every task through explicit states (`open` → `in progress` → `delivered` → `verified` → `done`). **An Executor can only mark a task `delivered`; `verified` must be set by someone other than the Executor (or after explicit owner approval recorded in `PROGRESS.md`).**

1. **Discover:** Use fast read-only searches (`grep`, `glob`, `read`, or exploration subagents/RAG) to gather ground-truth context.
2. **Specify & Dispatch:** Write the task spec(s) and launch non-blocking parallel sessions.
3. **Monitor & Intervene:** Monitor progress{monitor_mech}. If a session drifts off-spec or stalls, cancel/stop early and steer the same session.
4. **Verify Independently (Default mode: `{v_mode}`, fallback order: {cross_order}):**
   - Never trust the Executor's `Final Report` alone. Inspect `git status` and `git diff` in the Executor's worktree.
   - Re-run the task's Verification checks (directly or by dispatching an independent **Cross-Agent Verifier != Executor** on the `deep-reasoning` profile):
{v_checks_block}
   - If any criterion fails, mark the task `bounced` and send the exact failing criterion / `B1..Bn` findings back to the **same** Executor session.
5. **Integrate & Clean Up:**
   - Always checkout the target integration branch explicitly before merging:
     `git status --short` → `git checkout <target-branch>` → `git merge --no-ff <task-branch> -m "Merge <task-id>: <summary>"` → `git log --oneline --graph -5`.
   - **Post-Merge Integration Gate:** Run lint, tests, and a full consuming build on the integrated tree.
   - Remove completed worktrees (`git worktree remove <path>`) on merge, cancellation, or discard.
{END_MARKER}
"""


def inject_or_replace_agents_block(existing_text: str, new_block: str) -> str:
    pattern = re.compile(
        re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(existing_text):
        return pattern.sub(new_block.rstrip() + "\n", existing_text)
    if not existing_text.strip():
        return new_block.rstrip() + "\n"
    return existing_text.rstrip() + "\n\n" + new_block.rstrip() + "\n"


LEGACY_INTRO_HEADING_RE = re.compile(
    r"^#\s+Agent Orchestration\s*&\s*Development Guidelines\b",
    re.IGNORECASE,
)
LEGACY_REQUIRED_SKILLS_HEADING_RE = re.compile(
    r"^##\s+(?:\d+\.\s+)?Required Skills\b",
    re.IGNORECASE,
)
LEGACY_CORE_RULES_HEADING_RE = re.compile(
    r"^##\s+(?:\d+\.\s+)?Core Operating Rules\b",
    re.IGNORECASE,
)
LEGACY_LIFECYCLE_HEADING_RE = re.compile(
    r"^##\s+(?:\d+\.\s+)?Orchestration Lifecycle\b",
    re.IGNORECASE,
)
CANONICAL_RULE_SUBHEADING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^###\s+Rule\s+1:\s+(?:Keep the Main Session Free|Focus the Main Session on Architecture)",
        re.IGNORECASE,
    ),
    re.compile(r"^###\s+Rule\s+2:\s+Define Execution Tasks Before Delegating\b", re.IGNORECASE),
    re.compile(r"^###\s+Rule\s+3:\s+Delegate Maximum Work\b", re.IGNORECASE),
    re.compile(r"^###\s+Rule\s+4:\s+Select the Right Model\b", re.IGNORECASE),
)

LEGACY_INTRO_SIGNATURES: tuple[str, ...] = (
    "architect / executor",
    "primary_orchestrator",
    "default_executor",
    "verification_mode",
    "managed by `ai-orchestration`",
    "render-agents-md",
    "orchestration.toml",
    "roles.toml",
    "architect & orchestrator",
)

LEGACY_REQUIRED_SKILLS_SIGNATURES: tuple[str, ...] = (
    "`orchestration-workflow`",
    "`kilo-mcp-orchestrator`",
    "`task-spec-authoring`",
    "`task-pipeline`",
    "`macroplan-authoring`",
    "`task-worktree-ops`",
    "`task-delegation`",
    "`executor-contract`",
    "`kilo-mcp-executor-contract`",
    "`conflict-resolver`",
    "`orchestration-setup`",
    "`interactive-role-setup`",
    "load and follow these skills whenever planning, delegating, executing, or reviewing work",
)

LEGACY_CORE_RULES_SIGNATURES: tuple[str, ...] = (
    "rule 1: keep the main session free",
    "rule 1: focus the main session on architecture",
    "rule 2: define execution tasks before delegating",
    "rule 3: delegate maximum work",
    "rule 4: select the right model",
    "`focus_files`",
    "disjoint write scope",
    "one task = one commit",
    "isolated git worktree",
    "isolation safety checks",
    "shared host resources are not isolated by worktrees",
    "deep-reasoning",
    "bulk-execution",
)

LEGACY_LIFECYCLE_SIGNATURES: tuple[str, ...] = (
    "`open` → `in progress` → `delivered`",
    "`open` -> `in progress` -> `delivered`",
    "an executor can only mark a task",
    "verify independently",
    "cross-agent verifier",
    "post-merge integration gate",
    "git worktree remove",
    "`final report`",
)

CANONICAL_REQUIRED_SKILLS_EXCERPT = (
    "## 1. Required Skills\n\n"
    "Load and follow these skills whenever planning, delegating, executing, or reviewing work:\n"
    "- `orchestration-workflow` `task-spec-authoring` `task-pipeline` `task-worktree-ops` `executor-contract`"
)
CANONICAL_CORE_RULES_EXCERPT = (
    "## 2. Core Operating Rules\n\n"
    "### Rule 1: Keep the Main Session Free (Orchestrate, Don't Implement)\n"
    "### Rule 2: Define Execution Tasks Before Delegating\n"
    "Grounded `focus_files`, Disjoint Write Scope, One Task = One Commit."
)
CANONICAL_LIFECYCLE_EXCERPT = (
    "## 3. Orchestration Lifecycle & Cross-Agent Verification Gate\n\n"
    "Track every task through explicit states (`open` → `in progress` → `delivered` → `verified` → `done`). "
    "Verify Independently and run the Post-Merge Integration Gate."
)


def _count_signature_hits(text_lower: str, signatures: tuple[str, ...]) -> int:
    return sum(1 for sig in signatures if sig in text_lower)


def _section_matches_legacy_orchestration(heading: str, section_text: str) -> tuple[bool, list[str]]:
    """Positively match a markdown section against known legacy ai-orchestration renderings.

    Requires multiple canonical signatures (or high sequence similarity to the canonical template)
    inside the section body so ordinary user-authored sections with similar titles are never
    treated as orchestration duplicates.
    """
    h_stripped = heading.strip()
    sec_lower = section_text.lower()

    if LEGACY_INTRO_HEADING_RE.match(h_stripped):
        hits = _count_signature_hits(sec_lower, LEGACY_INTRO_SIGNATURES)
        if hits >= 2:
            return (True, [h_stripped])
        return (False, [])

    if LEGACY_REQUIRED_SKILLS_HEADING_RE.match(h_stripped):
        hits = _count_signature_hits(sec_lower, LEGACY_REQUIRED_SKILLS_SIGNATURES)
        sim = difflib.SequenceMatcher(None, sec_lower, CANONICAL_REQUIRED_SKILLS_EXCERPT.lower()).ratio()
        if hits >= 2 or sim >= 0.55:
            return (True, [h_stripped])
        return (False, [])

    if LEGACY_CORE_RULES_HEADING_RE.match(h_stripped):
        hits = _count_signature_hits(sec_lower, LEGACY_CORE_RULES_SIGNATURES)
        sim = difflib.SequenceMatcher(None, sec_lower, CANONICAL_CORE_RULES_EXCERPT.lower()).ratio()
        if hits >= 2 or sim >= 0.55:
            matched_headings = [h_stripped]
            in_fenced = False
            for raw_line in section_text.splitlines()[1:]:
                sline = raw_line.strip()
                if sline.startswith("```"):
                    in_fenced = not in_fenced
                    continue
                if not in_fenced and any(pat.match(sline) for pat in CANONICAL_RULE_SUBHEADING_PATTERNS):
                    matched_headings.append(sline)
            return (True, matched_headings)
        return (False, [])

    if LEGACY_LIFECYCLE_HEADING_RE.match(h_stripped):
        hits = _count_signature_hits(sec_lower, LEGACY_LIFECYCLE_SIGNATURES)
        sim = difflib.SequenceMatcher(None, sec_lower, CANONICAL_LIFECYCLE_EXCERPT.lower()).ratio()
        if hits >= 2 or sim >= 0.55:
            return (True, [h_stripped])
        return (False, [])

    return (False, [])


def _analyze_legacy_orchestration_segment(segment: str) -> tuple[list[tuple[int, int]], list[str]]:
    """Pure read-only analysis of a markdown segment outside managed markers.

    Parses top-level (`#`) and second-level (`##`) sections outside fenced code blocks and
    returns `(byte_or_char_spans, matched_headings)` for sections that positively match
    known legacy orchestration renderings.
    """
    lines = segment.splitlines(keepends=True)
    if not lines:
        return ([], [])

    # Locate `#` and `##` section boundaries outside fenced code blocks
    boundaries: list[tuple[int, int, str]] = []  # (char_offset, heading_level, heading_stripped)
    offset = 0
    in_fenced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fenced = not in_fenced
        elif not in_fenced:
            m = re.match(r"^(#{1,2})\s+", stripped)
            if m:
                boundaries.append((offset, len(m.group(1)), stripped))
        offset += len(line)

    if not boundaries:
        return ([], [])

    spans: list[tuple[int, int]] = []
    matched_headings: list[str] = []
    for idx, (start_pos, _level, heading_str) in enumerate(boundaries):
        end_pos = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(segment)
        sec_text = segment[start_pos:end_pos]
        is_match, sec_headings = _section_matches_legacy_orchestration(heading_str, sec_text)
        if is_match:
            spans.append((start_pos, end_pos))
            matched_headings.extend(sec_headings)

    return (spans, matched_headings)


def find_duplicated_handwritten_agents_sections(existing_text: str) -> list[str]:
    """Return list of duplicated hand-written orchestration section headings outside markers.

    Pure read-only predicate using positive signature/similarity matching; never invokes
    destructive stripping.
    """
    block_re = re.compile(
        re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?",
        re.DOTALL,
    )
    matches = list(block_re.finditer(existing_text))
    found: list[str] = []

    if not matches:
        _, headings = _analyze_legacy_orchestration_segment(existing_text)
        return headings

    first = matches[0]
    before = existing_text[: first.start()]
    after = existing_text[first.end() :]

    if len(matches) > 1:
        for _ in matches[1:]:
            found.append("duplicate <!-- BEGIN ai-orchestration --> block")
        after = block_re.sub("", after)

    _, headings_before = _analyze_legacy_orchestration_segment(before)
    _, headings_after = _analyze_legacy_orchestration_segment(after)
    found.extend(headings_before)
    found.extend(headings_after)
    return found


def _remove_spans_from_segment(segment: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return segment
    out: list[str] = []
    cursor = 0
    for start_pos, end_pos in spans:
        if start_pos > cursor:
            out.append(segment[cursor:start_pos])
        cursor = end_pos
    if cursor < len(segment):
        out.append(segment[cursor:])
    return "".join(out)


def strip_duplicated_handwritten_agents_sections(existing_text: str) -> tuple[str, list[str]]:
    """Strip positively matched legacy orchestration sections outside
    <!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration --> markers,
    while preserving all user-authored sections outside markers byte-for-byte."""
    block_re = re.compile(
        re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?",
        re.DOTALL,
    )
    matches = list(block_re.finditer(existing_text))
    removed: list[str] = []

    if not matches:
        spans, headings = _analyze_legacy_orchestration_segment(existing_text)
        if not spans:
            return (existing_text, [])
        return (_remove_spans_from_segment(existing_text, spans), headings)

    first = matches[0]
    before = existing_text[: first.start()]
    managed = existing_text[first.start() : first.end()]
    after = existing_text[first.end() :]

    if len(matches) > 1:
        for _ in matches[1:]:
            removed.append("duplicate <!-- BEGIN ai-orchestration --> block")
        after = block_re.sub("", after)

    spans_before, rem_before = _analyze_legacy_orchestration_segment(before)
    spans_after, rem_after = _analyze_legacy_orchestration_segment(after)
    removed.extend(rem_before)
    removed.extend(rem_after)

    if not removed:
        return (existing_text, [])

    cleaned_before = _remove_spans_from_segment(before, spans_before)
    cleaned_after = _remove_spans_from_segment(after, spans_after)
    return (cleaned_before + managed + cleaned_after, removed)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_show(args: argparse.Namespace) -> int:
    ws_arg = getattr(args, "workspace", None) or "."
    ws = pathlib.Path(ws_arg).resolve()
    cfg, meta = resolve_config(getattr(args, "global_config", None), ws)
    errors, val_warnings = validate_config(cfg)
    warnings = list(meta.get("warnings", [])) + [w for w in val_warnings if w not in meta.get("warnings", [])]
    payload = {
        "meta": meta,
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "config": cfg,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Global config : {meta['global_config_path']} (exists={meta['global_config_exists']})")
        print(f"Project config: {meta['project_config_path']} (exists={meta['project_config_exists']})")
        for w in meta.get("warnings", []):
            print(f"[WARN] {w}")
        print(f"Orchestrator  : {cfg.get('routing', {}).get('default_orchestrator')}")
        print(f"Executor      : {cfg.get('routing', {}).get('default_executor')}")
        print(f"Verify mode   : {cfg.get('verification', {}).get('default_mode')}")
        for tid, tcfg in cfg.get("tools", {}).items():
            if not isinstance(tcfg, dict):
                continue
            status = "enabled" if tcfg.get("enabled", True) else "disabled"
            print(f"\n[tools.{tid}] ({status}, mcp={tcfg.get('mcp_server') or '-'})")
            for prof in PROFILES:
                p = tcfg.get("profiles", {}).get(prof, {})
                if p:
                    var = p.get("variant") or p.get("effort") or "-"
                    print(f"  {prof:<16} -> {p.get('model')} (effort/variant={var})")
    return 0 if not errors else 1


def cmd_validate(args: argparse.Namespace) -> int:
    # Also run kit-internal checks if --plugin-dir is supplied
    from validate_roles import check_kit_internal  # same directory

    kit_ok = True
    for pdir in args.plugin_dir:
        kit_ok = check_kit_internal(pdir) and kit_ok

    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    cfg, meta = resolve_config(args.global_config, ws)
    errors, val_warnings = validate_config(cfg)
    warnings = list(meta.get("warnings", [])) + [w for w in val_warnings if w not in meta.get("warnings", [])]
    ok = kit_ok and (len(errors) == 0)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "kit_internal_ok": kit_ok,
                    "meta": meta,
                    "errors": errors,
                    "warnings": warnings,
                },
                indent=2,
            )
        )
    else:
        for w in warnings:
            print(f"[WARN] {w}")
        for e in errors:
            print(f"[FAIL] {e}")
        if ok:
            print("[ok] orchestration configuration & skill requirements valid")
    return 0 if ok else 1


def cmd_init_global(args: argparse.Namespace) -> int:
    gpath = args.global_config or default_global_config_path()
    with config_lock(gpath):
        if gpath.exists() and not args.force:
            msg = f"{gpath} already exists (pass --force to overwrite)."
            if args.json:
                print(json.dumps({"ok": False, "path": str(gpath), "message": msg}))
            else:
                print(f"[skip] {msg}")
            return 0
        before_bytes = gpath.read_bytes() if gpath.exists() else b""
        before_hash = hashlib.sha256(before_bytes).hexdigest()
        content = dump_toml(DEFAULT_GLOBAL_CONFIG)
        write_file_atomic(gpath, content)
        after_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        ws = getattr(args, "workspace", None)
        target_ws = pathlib.Path(ws).resolve() if ws else None
        _emit_config_changed(
            scope="global",
            target_path=gpath,
            workspace=target_ws,
            keys_changed=list(DEFAULT_GLOBAL_CONFIG.keys()),
            before_hash=before_hash,
            after_hash=after_hash,
        )
    if args.json:
        print(json.dumps({"ok": True, "path": str(gpath)}))
    else:
        print(f"[ok] wrote global config to {gpath}")
    return 0


def cmd_set_profile(args: argparse.Namespace) -> int:
    if args.profile not in PROFILE_SET:
        msg = f"invalid profile {args.profile!r}; must be one of {sorted(PROFILES)}"
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 2
    if args.basis and args.basis not in BASIS_VALUES:
        msg = f"invalid basis {args.basis!r}; must be one of {sorted(BASIS_VALUES)}"
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 2

    gpath = getattr(args, "global_config", None)
    if args.scope == "project":
        ws = pathlib.Path(args.workspace or ".").resolve()
        target_path = find_project_config_path(ws, gpath, for_write=True)
    else:
        ws = pathlib.Path(args.workspace).resolve() if getattr(args, "workspace", None) else None
        target_path = gpath or default_global_config_path()

    if getattr(args, "diff", False):
        if target_path.exists():
            current_bytes = target_path.read_bytes()
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            existing_text = current_bytes.decode("utf-8")
            text = existing_text
        else:
            current_bytes = b""
            current_hash = hashlib.sha256(b"").hexdigest()
            existing_text = ""
            text = dump_toml(DEFAULT_GLOBAL_CONFIG) if args.scope == "global" else ""

        table_path = ["tools", args.tool, "profiles", args.profile]
        text = set_toml_value(text, table_path, "model", args.model)
        if args.variant is not None:
            text = set_toml_value(text, table_path, "variant", args.variant)
            text = set_toml_value(text, table_path, "effort", None)
        if args.effort is not None:
            text = set_toml_value(text, table_path, "effort", args.effort)
            text = set_toml_value(text, table_path, "variant", None)
        if args.basis is not None:
            text = set_toml_value(text, table_path, "basis", args.basis)

        diff_str = "".join(
            difflib.unified_diff(
                existing_text.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=format_diff_path(target_path, "a", ws),
                tofile=format_diff_path(target_path, "b", ws),
            )
        )
        changed = existing_text != text
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "path": str(target_path),
                        "diff": diff_str,
                        "hash": current_hash,
                        "changed": changed,
                    }
                )
            )
        else:
            if diff_str:
                sys.stdout.write(diff_str)
            else:
                print(f"[ok] no changes in {target_path}")
        return 0

    keys_changed = [f"tools.{args.tool}.profiles.{args.profile}.model"]
    if args.variant is not None:
        keys_changed.append(f"tools.{args.tool}.profiles.{args.profile}.variant")
    if args.effort is not None:
        keys_changed.append(f"tools.{args.tool}.profiles.{args.profile}.effort")
    if args.basis is not None:
        keys_changed.append(f"tools.{args.tool}.profiles.{args.profile}.basis")

    with config_lock(target_path):
        if target_path.exists():
            current_bytes = target_path.read_bytes()
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            existing_text = current_bytes.decode("utf-8")
            text = existing_text
        else:
            current_bytes = b""
            current_hash = hashlib.sha256(b"").hexdigest()
            existing_text = ""
            text = dump_toml(DEFAULT_GLOBAL_CONFIG) if args.scope == "global" else ""

        if getattr(args, "expect_hash", None) is not None:
            if current_hash.lower() != args.expect_hash.strip().lower():
                msg = f"hash mismatch for {target_path}: expected {args.expect_hash}, found {current_hash}"
                if getattr(args, "json", False):
                    print(
                        json.dumps(
                            {
                                "ok": False,
                                "error": msg,
                                "expected_hash": args.expect_hash,
                                "actual_hash": current_hash,
                                "path": str(target_path),
                            }
                        )
                    )
                else:
                    print(f"[FAIL] {msg}", file=sys.stderr)
                return 2

        table_path = ["tools", args.tool, "profiles", args.profile]
        text = set_toml_value(text, table_path, "model", args.model)
        if args.variant is not None:
            text = set_toml_value(text, table_path, "variant", args.variant)
            text = set_toml_value(text, table_path, "effort", None)
        if args.effort is not None:
            text = set_toml_value(text, table_path, "effort", args.effort)
            text = set_toml_value(text, table_path, "variant", None)
        if args.basis is not None:
            text = set_toml_value(text, table_path, "basis", args.basis)

        write_file_atomic(target_path, text)
        after_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        target_ws = ws if ws is not None else (pathlib.Path(".").resolve() if args.scope == "project" else None)
        _emit_config_changed(
            scope=args.scope,
            target_path=target_path,
            workspace=target_ws,
            keys_changed=keys_changed,
            before_hash=current_hash,
            after_hash=after_hash,
        )

    parsed = tomllib.loads(text) if tomllib is not None else {}
    entry = parsed.get("tools", {}).get(args.tool, {}).get("profiles", {}).get(args.profile, {})

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "ok": True,
                    "path": str(target_path),
                    "tool": args.tool,
                    "profile": args.profile,
                    "entry": entry,
                }
            )
        )
    else:
        print(f"[ok] updated [{args.tool}.profiles.{args.profile}] in {target_path}")
    return 0


def cmd_set_routing(args: argparse.Namespace) -> int:
    if not any([args.orchestrator, args.executor, args.default_profile, args.verification_mode]):
        msg = "at least one of --orchestrator, --executor, --default-profile, --verification-mode is required"
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 2

    ws = pathlib.Path(args.workspace).resolve() if getattr(args, "workspace", None) else None
    gpath = getattr(args, "global_config", None)
    merged, _ = resolve_config(gpath, ws)
    tools = merged.get("tools", {})
    enabled_tools = {
        name for name, t in tools.items() if isinstance(t, dict) and t.get("enabled", True)
    }

    if args.orchestrator is not None:
        if args.orchestrator not in enabled_tools:
            msg = f"tool {args.orchestrator!r} is unknown or disabled (enabled tools: {sorted(enabled_tools)})"
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "error": msg}))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2

    if args.executor is not None:
        if args.executor not in enabled_tools:
            msg = f"tool {args.executor!r} is unknown or disabled (enabled tools: {sorted(enabled_tools)})"
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "error": msg}))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2

    if args.default_profile is not None:
        if args.default_profile not in PROFILE_SET:
            msg = f"invalid profile {args.default_profile!r}; must be one of {sorted(PROFILES)}"
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "error": msg}))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2

    if args.verification_mode is not None:
        if args.verification_mode not in VERIFICATION_MODES:
            msg = f"invalid verification mode {args.verification_mode!r}; must be one of {sorted(VERIFICATION_MODES)}"
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "error": msg}))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2

    if args.scope == "project":
        project_ws = ws or pathlib.Path(".").resolve()
        target_path = find_project_config_path(project_ws, gpath, for_write=True)
    else:
        target_path = gpath or default_global_config_path()

    if getattr(args, "diff", False):
        if target_path.exists():
            current_bytes = target_path.read_bytes()
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            existing_text = current_bytes.decode("utf-8")
        else:
            current_bytes = b""
            current_hash = hashlib.sha256(b"").hexdigest()
            existing_text = ""

        text = existing_text
        if args.orchestrator is not None:
            text = set_toml_value(text, ["routing"], "default_orchestrator", args.orchestrator)
        if args.executor is not None:
            text = set_toml_value(text, ["routing"], "default_executor", args.executor)
        if args.default_profile is not None:
            text = set_toml_value(text, ["routing"], "default_profile", args.default_profile)
        if args.verification_mode is not None:
            text = set_toml_value(text, ["verification"], "default_mode", args.verification_mode)

        diff_str = "".join(
            difflib.unified_diff(
                existing_text.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=format_diff_path(target_path, "a", ws),
                tofile=format_diff_path(target_path, "b", ws),
            )
        )
        changed = existing_text != text
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "path": str(target_path),
                        "diff": diff_str,
                        "hash": current_hash,
                        "changed": changed,
                    }
                )
            )
        else:
            if diff_str:
                sys.stdout.write(diff_str)
            else:
                print(f"[ok] no changes in {target_path}")
        return 0

    keys_changed = []
    if args.orchestrator is not None:
        keys_changed.append("routing.default_orchestrator")
    if args.executor is not None:
        keys_changed.append("routing.default_executor")
    if args.default_profile is not None:
        keys_changed.append("routing.default_profile")
    if args.verification_mode is not None:
        keys_changed.append("verification.default_mode")

    with config_lock(target_path):
        if target_path.exists():
            current_bytes = target_path.read_bytes()
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            existing_text = current_bytes.decode("utf-8")
        else:
            current_bytes = b""
            current_hash = hashlib.sha256(b"").hexdigest()
            existing_text = ""

        if getattr(args, "expect_hash", None) is not None:
            if current_hash.lower() != args.expect_hash.strip().lower():
                msg = f"hash mismatch for {target_path}: expected {args.expect_hash}, found {current_hash}"
                if getattr(args, "json", False):
                    print(
                        json.dumps(
                            {
                                "ok": False,
                                "error": msg,
                                "expected_hash": args.expect_hash,
                                "actual_hash": current_hash,
                                "path": str(target_path),
                            }
                        )
                    )
                else:
                    print(f"[FAIL] {msg}", file=sys.stderr)
                return 2

        text = existing_text
        if args.orchestrator is not None:
            text = set_toml_value(text, ["routing"], "default_orchestrator", args.orchestrator)
        if args.executor is not None:
            text = set_toml_value(text, ["routing"], "default_executor", args.executor)
        if args.default_profile is not None:
            text = set_toml_value(text, ["routing"], "default_profile", args.default_profile)
        if args.verification_mode is not None:
            text = set_toml_value(text, ["verification"], "default_mode", args.verification_mode)

        write_file_atomic(target_path, text)
        after_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        target_ws = ws if ws is not None else (pathlib.Path(".").resolve() if args.scope == "project" else None)
        _emit_config_changed(
            scope=args.scope,
            target_path=target_path,
            workspace=target_ws,
            keys_changed=keys_changed,
            before_hash=current_hash,
            after_hash=after_hash,
        )

    updated_routing: dict[str, str] = {}
    if args.orchestrator is not None:
        updated_routing["default_orchestrator"] = args.orchestrator
    if args.executor is not None:
        updated_routing["default_executor"] = args.executor
    if args.default_profile is not None:
        updated_routing["default_profile"] = args.default_profile

    updated_verification: dict[str, str] = {}
    if args.verification_mode is not None:
        updated_verification["default_mode"] = args.verification_mode

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "ok": True,
                    "path": str(target_path),
                    "scope": args.scope,
                    "routing": updated_routing,
                    "verification": updated_verification,
                }
            )
        )
    else:
        print(f"[ok] updated routing in {target_path}")
    return 0


def cmd_init_project(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    ppath = find_project_config_path(ws, args.global_config, for_write=True)
    with config_lock(ppath):
        if ppath.exists() and not args.force:
            if args.json:
                print(json.dumps({"ok": False, "path": str(ppath), "message": "already exists"}))
            else:
                print(f"[skip] {ppath} already exists (pass --force to overwrite)")
            return 0

        before_bytes = ppath.read_bytes() if ppath.exists() else b""
        before_hash = hashlib.sha256(before_bytes).hexdigest()

        proj_data: dict[str, Any] = {
            "project": {
                "name": args.name or ws.name,
                "primary_orchestrator": args.orchestrator or "kilo",
                "isolation": {
                    "shared_databases": [],
                    "shared_ports": [],
                    "worker_port_range": [8766, 8779],
                    "conflict_prone_files": [],
                    "zero_conflict_registries": [],
                },
            },
            "routing": {
                "default_executor": args.executor or (args.orchestrator or "kilo"),
            },
            "verification": {
                "default_mode": args.verification_mode or "cross-agent",
            },
        }
        content = dump_toml(proj_data)
        write_file_atomic(ppath, content)
        after_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        _emit_config_changed(
            scope="project",
            target_path=ppath,
            workspace=ws,
            keys_changed=["project", "routing", "verification"],
            before_hash=before_hash,
            after_hash=after_hash,
        )
    if args.json:
        print(json.dumps({"ok": True, "path": str(ppath)}))
    else:
        print(f"[ok] wrote project config to {ppath}")
    return 0


def cmd_render_agents_md(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace or ".").resolve()
    gpath = getattr(args, "global_config", None)
    cfg, meta = resolve_config(gpath, ws)

    has_project_config = meta.get("project_config_exists", False)
    proj = cfg.get("project", {})
    routing = cfg.get("routing", {})
    ver = cfg.get("verification", {})
    tools = cfg.get("tools", {})

    orchestrator_id = proj.get("primary_orchestrator") or routing.get("default_orchestrator", "kilo")
    executor_id = routing.get("default_executor", orchestrator_id)
    v_mode = ver.get("default_mode", "cross-agent")
    routing_desc = f"orchestrator='{orchestrator_id}', executor='{executor_id}', verification_mode='{v_mode}'"

    warnings: list[str] = list(meta.get("warnings", []))
    if not has_project_config:
        routing_warning = (
            f"Workspace has no project config; using global routing ({routing_desc}). "
            "Run 'ai-orch config init-project' to configure."
        )
        warnings.append(routing_warning)

    # Active tools for model catalog checks
    active_tool_ids = get_active_tool_ids(cfg)

    unknown_models: list[tuple[str, str, str]] = []
    for tid in active_tool_ids:
        if tid == "kilo":
            kilo_models = get_kilo_models(timeout=20.0)
            if kilo_models is not None:
                kilo_profiles = tools.get("kilo", {}).get("profiles", {})
                for prof in PROFILES:
                    pentry = kilo_profiles.get(prof, {})
                    if isinstance(pentry, dict):
                        m = str(pentry.get("model", "")).strip()
                        if m and m not in kilo_models:
                            unknown_models.append(("kilo", prof, m))
                            warnings.append(
                                f"Unknown model id '{m}' for tool 'kilo' (profile '{prof}') not found in 'kilo models' catalog."
                            )
            else:
                warnings.append(
                    "Tool 'kilo' catalog check skipped: 'kilo models' command unavailable or timed out."
                )
        else:
            warnings.append(
                f"Skipping model catalog validation for '{tid}': no reliable CLI catalog command available."
            )

    block = render_agents_md_block(cfg, ws, gpath)
    agents_md_path = ws / "AGENTS.md"

    if agents_md_path.exists():
        current_bytes = agents_md_path.read_bytes()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        existing = current_bytes.decode("utf-8")
    else:
        current_bytes = b""
        current_hash = hashlib.sha256(b"").hexdigest()
        existing = ""

    updated = inject_or_replace_agents_block(existing, block)

    if getattr(args, "diff", False):
        diff_str = "".join(
            difflib.unified_diff(
                existing.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"a/{agents_md_path.name}",
                tofile=f"b/{agents_md_path.name}",
            )
        )
        changed = existing != updated
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "path": str(agents_md_path),
                        "diff": diff_str,
                        "hash": current_hash,
                        "changed": changed,
                        "warnings": warnings,
                    }
                )
            )
        else:
            for w in warnings:
                print(f"[WARN] {w}", file=sys.stderr)
            if diff_str:
                sys.stdout.write(diff_str)
            else:
                print(f"[ok] no changes in {agents_md_path}")
        return 0

    if getattr(args, "check", False):
        in_sync = existing == updated
        if getattr(args, "json", False):
            print(json.dumps({"ok": in_sync, "path": str(agents_md_path), "warnings": warnings}))
        elif not in_sync:
            for w in warnings:
                print(f"[WARN] {w}", file=sys.stderr)
            print(f"[FAIL] {agents_md_path} orchestration block is out of sync")
        else:
            print(f"[ok] {agents_md_path} orchestration block is in sync")
        return 0 if in_sync else 1

    if getattr(args, "expect_hash", None) is not None and not getattr(args, "apply", False):
        msg = "--expect-hash requires --apply"
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 2

    if getattr(args, "apply", False):
        with config_lock(agents_md_path):
            if getattr(args, "expect_hash", None) is not None:
                disk_bytes = agents_md_path.read_bytes() if agents_md_path.exists() else b""
                actual_hash = hashlib.sha256(disk_bytes).hexdigest()
                if actual_hash.lower() != args.expect_hash.strip().lower():
                    msg = f"hash mismatch for {agents_md_path}: expected {args.expect_hash}, found {actual_hash}"
                    if getattr(args, "json", False):
                        print(
                            json.dumps(
                                {
                                    "ok": False,
                                    "error": msg,
                                    "expected_hash": args.expect_hash,
                                    "actual_hash": actual_hash,
                                    "path": str(agents_md_path),
                                }
                            )
                        )
                    else:
                        print(f"[FAIL] {msg}", file=sys.stderr)
                    return 2

            if not has_project_config and not getattr(args, "allow_global_routing", False):
                msg = (
                    f"Refusing to apply: workspace has no project config (would use global routing: {routing_desc}). "
                    "Pass --allow-global-routing to proceed or run 'ai-orch config init-project' first."
                )
                if getattr(args, "json", False):
                    print(
                        json.dumps(
                            {
                                "ok": False,
                                "error": msg,
                                "path": str(agents_md_path),
                                "routing": {
                                    "primary_orchestrator": orchestrator_id,
                                    "default_executor": executor_id,
                                    "verification_mode": v_mode,
                                },
                                "warnings": warnings,
                            }
                        )
                    )
                else:
                    print(f"[FAIL] {msg}", file=sys.stderr)
                return 2

            if unknown_models and not getattr(args, "allow_unknown_models", False):
                unknown_strs = [f"{t}:{p}={m}" for t, p, m in unknown_models]
                msg = (
                    f"Refusing to apply: unknown model id(s) not found in tool catalog: {', '.join(unknown_strs)}. "
                    "Pass --allow-unknown-models to proceed."
                )
                if getattr(args, "json", False):
                    print(
                        json.dumps(
                            {
                                "ok": False,
                                "error": msg,
                                "path": str(agents_md_path),
                                "unknown_models": [
                                    {"tool": t, "profile": p, "model": m} for t, p, m in unknown_models
                                ],
                                "warnings": warnings,
                            }
                        )
                    )
                else:
                    print(f"[FAIL] {msg}", file=sys.stderr)
                return 2

            write_file_atomic(agents_md_path, updated)
        if getattr(args, "json", False):
            print(json.dumps({"ok": True, "applied": True, "path": str(agents_md_path), "warnings": warnings}))
        else:
            print(f"[ok] updated {agents_md_path}")
        return 0

    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "applied": False, "path": str(agents_md_path), "rendered_block": block, "warnings": warnings}))
    else:
        for w in warnings:
            print(f"[WARN] {w}", file=sys.stderr)
        sys.stdout.write(block)
    return 0


def detect_tool(name: str) -> dict[str, Any]:
    exe = shutil.which(name)
    if not exe:
        return {
            "installed": False,
            "path": None,
            "version": None,
            "auth_status": "not_installed",
            "models": [],
        }

    version = "unknown"
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5, check=False)
        out = (proc.stdout or proc.stderr).strip()
        if out:
            version = out.splitlines()[0]
    except Exception:
        pass

    auth_status = "configured"
    models: list[str] = []

    if name == "kilo":
        k_models = get_kilo_models(timeout=5.0)
        if k_models is not None and len(k_models) > 0:
            models = sorted(k_models)
            auth_status = "authenticated"
        else:
            kilo_cfg = pathlib.Path.home() / ".config" / "kilo"
            if kilo_cfg.exists() or os.environ.get("KILO_API_KEY"):
                auth_status = "configured"
            else:
                auth_status = "unauthenticated"
    elif name == "claude":
        claude_cfg = pathlib.Path.home() / ".claude"
        if claude_cfg.exists() or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY"):
            auth_status = "authenticated"
        else:
            auth_status = "configured"
        # The CLI accepts these aliases and resolves them to the current models.
        models = ["opus", "sonnet", "haiku"]
    elif name == "codex":
        codex_cfg = pathlib.Path.home() / ".codex"
        if codex_cfg.exists() or os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            auth_status = "authenticated"
        else:
            auth_status = "configured"
        models = ["gpt-5-codex", "gpt-5-codex-mini"]

    return {
        "installed": True,
        "path": exe,
        "version": version,
        "auth_status": auth_status,
        "models": models,
    }


def detect_environment(tool_names: list[str] | None = None) -> dict[str, Any]:
    names = tool_names or ["claude", "kilo", "codex"]
    return {t: detect_tool(t) for t in names}


def build_setup_plan(
    workspace: pathlib.Path | str,
    *,
    global_config: pathlib.Path | None = None,
    scope: str = "project",
    orchestrator: str | None = None,
    executor: str | None = None,
    verification_mode: str | None = None,
    executor_model: str | None = None,
    orchestrator_model: str | None = None,
) -> dict[str, Any]:
    ws = pathlib.Path(workspace).resolve()
    detection = detect_environment()

    # Step 2: Choose orchestrator and executor
    # Owner default (2026-10-17): Claude orchestrates, Kilo executes
    if orchestrator:
        orch_tool = orchestrator
    elif detection.get("claude", {}).get("installed"):
        orch_tool = "claude"
    elif detection.get("kilo", {}).get("installed"):
        orch_tool = "kilo"
    elif detection.get("codex", {}).get("installed"):
        orch_tool = "codex"
    else:
        orch_tool = "claude"

    if executor:
        exec_tool = executor
    elif detection.get("kilo", {}).get("installed"):
        exec_tool = "kilo"
    elif detection.get("claude", {}).get("installed") and orch_tool != "claude":
        exec_tool = "claude"
    else:
        exec_tool = "kilo"

    # Step 3: Choose verification mode & cross-agent order
    if verification_mode:
        v_mode = verification_mode
    elif orch_tool != exec_tool:
        v_mode = "cross-agent"
    else:
        v_mode = "independent-session"

    order = [f"{orch_tool}:deep-reasoning", f"{exec_tool}:deep-reasoning"]
    for rem in ("codex", "claude", "kilo"):
        cand = f"{rem}:deep-reasoning"
        if cand not in order and detection.get(rem, {}).get("installed"):
            order.append(cand)

    # Step 4: Choose models per profile
    # Default executor model: google/gemini-3.8-flash for kilo
    if executor_model:
        exec_m = executor_model
    elif exec_tool == "kilo":
        exec_m = "google/gemini-3.8-flash"
    elif exec_tool == "claude":
        exec_m = "sonnet"
    else:
        exec_m = "gpt-5-codex-mini"

    # Default orchestrator model: sonnet for claude
    if orchestrator_model:
        orch_m = orchestrator_model
    elif orch_tool == "claude":
        orch_m = "sonnet"
    elif orch_tool == "kilo":
        orch_m = "google/gemini-4-argon"
    else:
        orch_m = "gpt-5-codex"

    # Step 5: Scope
    gpath = global_config or default_global_config_path()
    if scope == "project-local":
        target_path = ws / ".ai-orchestration.local.toml"
    elif scope == "project":
        target_path = find_project_config_path(ws, gpath, for_write=True)
    else:
        target_path = gpath

    if target_path.exists():
        existing_bytes = target_path.read_bytes()
        existing_hash = hashlib.sha256(existing_bytes).hexdigest()
        existing_text = existing_bytes.decode("utf-8")
    else:
        existing_bytes = b""
        existing_hash = hashlib.sha256(b"").hexdigest()
        existing_text = ""

    # Build proposed content
    if scope == "global":
        if existing_text:
            new_text = set_toml_value(existing_text, ["routing"], "default_orchestrator", orch_tool)
            new_text = set_toml_value(new_text, ["routing"], "default_executor", exec_tool)
            new_text = set_toml_value(new_text, ["routing"], "default_profile", "bulk-execution")
            new_text = set_toml_value(new_text, ["verification"], "default_mode", v_mode)
            new_text = set_toml_value(new_text, ["tools", exec_tool, "profiles", "bulk-execution"], "model", exec_m)
            new_text = set_toml_value(new_text, ["tools", orch_tool, "profiles", "orchestration"], "model", orch_m)
        else:
            cfg_data = copy.deepcopy(DEFAULT_GLOBAL_CONFIG)
            cfg_data["routing"]["default_orchestrator"] = orch_tool
            cfg_data["routing"]["default_executor"] = exec_tool
            cfg_data["routing"]["default_profile"] = "bulk-execution"
            cfg_data["verification"]["default_mode"] = v_mode
            cfg_data["verification"]["cross_agent_order"] = order
            if exec_tool in cfg_data.get("tools", {}):
                cfg_data["tools"][exec_tool]["profiles"]["bulk-execution"]["model"] = exec_m
            if orch_tool in cfg_data.get("tools", {}):
                cfg_data["tools"][orch_tool]["profiles"]["orchestration"]["model"] = orch_m
            new_text = dump_toml(cfg_data)
    else:
        # project or project-local
        if existing_text:
            new_text = set_toml_value(existing_text, ["routing"], "default_orchestrator", orch_tool)
            new_text = set_toml_value(new_text, ["routing"], "default_executor", exec_tool)
            new_text = set_toml_value(new_text, ["routing"], "default_profile", "bulk-execution")
            new_text = set_toml_value(new_text, ["verification"], "default_mode", v_mode)
            new_text = set_toml_value(new_text, ["tools", exec_tool, "profiles", "bulk-execution"], "model", exec_m)
            new_text = set_toml_value(new_text, ["tools", orch_tool, "profiles", "orchestration"], "model", orch_m)
        else:
            proj_data = {
                "project": {
                    "name": ws.name,
                    "primary_orchestrator": orch_tool,
                    "isolation": {
                        "shared_databases": [],
                        "shared_ports": [],
                        "worker_port_range": [8766, 8779],
                        "conflict_prone_files": [],
                        "zero_conflict_registries": [],
                    },
                },
                "routing": {
                    "default_orchestrator": orch_tool,
                    "default_executor": exec_tool,
                    "default_profile": "bulk-execution",
                },
                "verification": {
                    "default_mode": v_mode,
                    "cross_agent_order": order,
                },
                "tools": {
                    exec_tool: {
                        "enabled": True,
                        "profiles": {
                            "bulk-execution": {
                                "model": exec_m,
                                "variant": "medium",
                                "basis": "template-default",
                            },
                        },
                    },
                    orch_tool: {
                        "enabled": True,
                        "profiles": {
                            "orchestration": {
                                "model": orch_m,
                                "variant": "medium",
                                "basis": "template-default",
                            },
                        },
                    },
                },
            }
            new_text = dump_toml(proj_data)

    diff_str = "".join(
        difflib.unified_diff(
            existing_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=format_diff_path(target_path, "a", ws),
            tofile=format_diff_path(target_path, "b", ws),
        )
    )

    plan_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()

    return {
        "ok": True,
        "applied": False,
        "detection": detection,
        "routing": {
            "default_orchestrator": orch_tool,
            "default_executor": exec_tool,
            "default_profile": "bulk-execution",
        },
        "verification": {
            "default_mode": v_mode,
            "cross_agent_order": order,
        },
        "profiles": {
            "orchestrator": {
                "tool": orch_tool,
                "profile": "orchestration",
                "model": orch_m,
            },
            "executor": {
                "tool": exec_tool,
                "profile": "bulk-execution",
                "model": exec_m,
            },
        },
        "permission_policy": {
            "description": "Q001 option A (per-mode allow-list: execute and verify get git/test runners/file tools, orchestrate also gets kilo-mcp)",
            "defaults": DEFAULT_CLAUDE_ALLOWED_TOOLS,
        },
        "scope": scope,
        "path": str(target_path),
        "existing_exists": target_path.exists(),
        "diff": diff_str,
        "plan_hash": plan_hash,
        "config_hash": existing_hash,
        "hash": plan_hash,
        "proposed_text": new_text,
    }


def cmd_setup(args: argparse.Namespace) -> int:
    ws = pathlib.Path(getattr(args, "workspace", ".") or ".").resolve()
    gpath = getattr(args, "global_config", None)
    scope = getattr(args, "scope", "project")
    apply_mode = getattr(args, "apply", False)
    expect_hash = getattr(args, "expect_hash", None) or getattr(args, "expect_plan_hash", None)

    plan = build_setup_plan(
        ws,
        global_config=gpath,
        scope=scope,
        orchestrator=getattr(args, "orchestrator", None),
        executor=getattr(args, "executor", None),
        verification_mode=getattr(args, "verification_mode", None),
        executor_model=getattr(args, "executor_model", None),
        orchestrator_model=getattr(args, "orchestrator_model", None),
    )

    target_path = pathlib.Path(plan["path"])
    plan_hash = plan["plan_hash"]
    existing_hash = plan["config_hash"]
    proposed_text = plan.pop("proposed_text")

    if not apply_mode:
        if getattr(args, "json", False):
            print(json.dumps(plan, indent=2))
            return 0

        # Formatted console output
        print("=" * 80)
        print("ai-orch setup — Orchestrator & Execution Configuration Wizard")
        print("=" * 80)
        print("\n1. Tool Detection:")
        for tname, tinfo in plan["detection"].items():
            if tinfo["installed"]:
                auth_str = f" [auth: {tinfo['auth_status']}]" if tinfo.get("auth_status") else ""
                models_str = f" (models: {', '.join(tinfo['models'])})" if tinfo.get("models") else ""
                print(f"   - {tname:<8}: installed ({tinfo.get('version')}){auth_str}{models_str}")
            else:
                print(f"   - {tname:<8}: not installed")

        print("\n2. Routing Defaults:")
        print(f"   - Default Orchestrator : {plan['routing']['default_orchestrator']}")
        print(f"   - Default Executor     : {plan['routing']['default_executor']}")
        print(f"   - Default Profile      : {plan['routing']['default_profile']}")

        print("\n3. Verification:")
        print(f"   - Default Mode         : {plan['verification']['default_mode']}")
        print(f"   - Cross-Agent Order    : {' -> '.join(plan['verification']['cross_agent_order'])}")

        print("\n4. Profiles:")
        print(f"   - Orchestrator : {plan['profiles']['orchestrator']['tool']} (profile: {plan['profiles']['orchestrator']['profile']}, model: {plan['profiles']['orchestrator']['model']})")
        print(f"   - Executor     : {plan['profiles']['executor']['tool']} (profile: {plan['profiles']['executor']['profile']}, model: {plan['profiles']['executor']['model']})")

        print(f"\n5. Scope:")
        print(f"   - Target Path : {plan['path']} (scope: {plan['scope']})")

        print("\n6. Permission Policy:")
        print(f"   - {plan['permission_policy']['description']}")

        print("\n7. Preview Diff:")
        if plan.get("diff"):
            sys.stdout.write(plan["diff"])
        else:
            print("   (no diff, identical configuration)")

        print(f"\nPlan hash: {plan_hash}")
        print("\nTo apply this configuration, run:")
        print(f"  ai-orch setup --apply --expect-hash {plan_hash} --scope {scope} --workspace {ws}")
        return 0

    # Apply mode
    if not expect_hash:
        msg = "--expect-hash <hash> is required when applying setup. Run 'ai-orch setup' first to preview and inspect the plan_hash."
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "applied": False, "error": msg, "plan_hash": plan_hash}))
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
        return 2

    norm_exp = expect_hash.strip().lower()

    # Re-read target and verify base hash INSIDE config_lock before writing (CAS)
    with config_lock(target_path):
        current_bytes = target_path.read_bytes() if target_path.exists() else b""
        current_disk_hash = hashlib.sha256(current_bytes).hexdigest()

        if current_disk_hash.lower() != existing_hash.lower() or norm_exp not in (plan_hash.lower(), existing_hash.lower()):
            msg = f"hash mismatch for {target_path}: expected {expect_hash}, computed plan hash {plan_hash}, disk hash {current_disk_hash}"
            if getattr(args, "json", False):
                print(json.dumps({
                    "ok": False,
                    "applied": False,
                    "error": msg,
                    "expected_hash": expect_hash,
                    "actual_hash": current_disk_hash,
                    "plan_hash": plan_hash,
                    "path": str(target_path),
                }))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2

        write_file_atomic(target_path, proposed_text)
        after_hash = hashlib.sha256(proposed_text.encode("utf-8")).hexdigest()
        _emit_config_changed(
            scope="global" if scope == "global" else "project",
            target_path=target_path,
            workspace=ws if scope != "global" else None,
            keys_changed=["routing", "verification", "tools"],
            before_hash=current_disk_hash,
            after_hash=after_hash,
        )

    orch_started = False
    if getattr(args, "start_orchestrator", False):
        try:
            from orchestration_orchestrator import start_orchestrator
            start_orchestrator(ws)
            orch_started = True
        except Exception as e:
            logger.warning(f"Could not start orchestrator: {e}")

    if getattr(args, "json", False):
        print(json.dumps({
            "ok": True,
            "applied": True,
            "scope": scope,
            "path": str(target_path),
            "plan_hash": plan_hash,
            "hash": after_hash,
            "orchestrator_started": orch_started,
        }))
    else:
        print(f"[ok] Applied configuration to {target_path}")
        if orch_started:
            print("[ok] Started orchestrator role session")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    ws_arg = getattr(args, "workspace", None) or getattr(args, "project", None) or "."
    ws = pathlib.Path(ws_arg).resolve()
    gpath = getattr(args, "global_config", None)
    cfg, _ = resolve_config(gpath, ws)
    res = run_project_preflight(cfg, workspace=ws)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if not res["configured"]:
            print(f"[ok] No [project.preflight] checks configured for {ws}")
        else:
            for c in res["checks"]:
                status_tag = "[ok]" if c["ok"] else "[FAIL]"
                print(f"{status_tag} {c['message']}", file=sys.stdout if c["ok"] else sys.stderr)
            if res["ok"]:
                print(f"[ok] All {len(res['checks'])} preflight check(s) passed.")
            else:
                print(f"[FAIL] {len(res['failures'])} preflight check(s) failed.", file=sys.stderr)
    return 0 if res["ok"] else 1


def cmd_verify_checks(args: argparse.Namespace) -> int:
    ws_arg = getattr(args, "workspace", None) or getattr(args, "project", None) or "."
    ws = pathlib.Path(ws_arg).resolve()
    gpath = getattr(args, "global_config", None)
    cfg, _ = resolve_config(gpath, ws)

    selected: list[str] = []
    if getattr(args, "check", None):
        selected.extend(args.check)
    if getattr(args, "checks", None):
        selected.extend(args.checks)

    res = run_verification_checks(
        cfg,
        workspace=ws,
        selected_checks=selected if selected else None,
        timeout_override=getattr(args, "timeout", None),
        fail_fast=bool(getattr(args, "fail_fast", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
    )

    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if not res["checks"] and res["ok"]:
            print(f"[ok] No [project.verification_checks] configured for {ws}")
        else:
            for chk in res["checks"]:
                tag = "[ok]" if chk["ok"] else "[FAIL]"
                desc_part = f" — {chk['description']}" if chk.get("description") else ""
                print(f"{tag} {chk['name']}{desc_part}")
                for cmd_out in chk.get("commands", []):
                    c_tag = "PASS" if cmd_out["ok"] else ("TIMEOUT" if cmd_out.get("timed_out") else "FAIL")
                    print(f"  [{c_tag}] {cmd_out['command']} (exit={cmd_out['exit_code']}, {cmd_out['duration_seconds']}s)")
                    if not cmd_out["ok"]:
                        err_text = cmd_out.get("stderr") or cmd_out.get("stdout")
                        if err_text:
                            print(f"    {err_text}", file=sys.stderr)
            for f_msg in res["failures"]:
                if not res["checks"]:
                    print(f"[FAIL] {f_msg}", file=sys.stderr)
            if res["ok"]:
                print(f"[ok] Verification checks passed ({res['passed_count']} passed, 0 failed).")
            else:
                print(
                    f"[FAIL] Verification checks failed ({res['passed_count']} passed, {res['failed_count']} failed).",
                    file=sys.stderr,
                )
    return 0 if res["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--global-config", type=pathlib.Path, default=None, help="Override path to global orchestration.toml")
    ap.add_argument("--json", action="store_true", help="Output structured JSON on stdout")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="Show merged Global + Project configuration")
    p_show.add_argument("--workspace", default=".", help="Project workspace root (default: current directory)")
    p_show.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_show.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_show.set_defaults(func=cmd_show)

    p_val = sub.add_parser("validate", help="Validate kit skill-requirements and orchestration.toml")
    p_val.add_argument("--workspace", default=None, help="Project workspace root")
    p_val.add_argument("--plugin-dir", action="append", default=[], type=pathlib.Path)
    p_val.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_val.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_val.set_defaults(func=cmd_validate)

    p_ig = sub.add_parser("init-global", help="Initialize ~/.config/ai-orchestration/orchestration.toml")
    p_ig.add_argument("--force", action="store_true")
    p_ig.add_argument("--workspace", default=None, help="Workspace root to emit config.changed event to")
    p_ig.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_ig.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_ig.set_defaults(func=cmd_init_global)

    p_sp = sub.add_parser("set-profile", help="Set model/variant/effort for a tool and role profile")
    p_sp.add_argument("tool", help="Tool id (e.g. kilo, claude, codex)")
    p_sp.add_argument("profile", help=f"Role profile ({', '.join(PROFILES)})")
    p_sp.add_argument("--model", required=True, help="Model identifier")
    p_sp.add_argument("--variant", default=None, help="Model reasoning variant (e.g. low, medium, high)")
    p_sp.add_argument("--effort", default=None, help="Model effort level (e.g. low, medium, high, max)")
    p_sp.add_argument("--basis", default=None, help=f"Ranking basis ({', '.join(sorted(BASIS_VALUES))})")
    p_sp.add_argument("--scope", choices=("global", "project"), default="global")
    p_sp.add_argument("--workspace", default=None)
    p_sp.add_argument("--diff", action="store_true", default=False, help="Preview changes as unified diff without writing")
    p_sp.add_argument("--expect-hash", default=None, help="Expected sha256 hash of target file before writing; refuse on mismatch")
    p_sp.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_sp.set_defaults(func=cmd_set_profile)

    p_sr = sub.add_parser(
        "set-routing",
        help="Set default orchestrator, executor, profile, and/or verification mode",
    )
    p_sr.add_argument("--orchestrator", default=None, help="Default orchestrator tool id")
    p_sr.add_argument("--executor", default=None, help="Default executor tool id")
    p_sr.add_argument("--default-profile", default=None, help=f"Default profile ({', '.join(PROFILES)})")
    p_sr.add_argument(
        "--verification-mode",
        default=None,
        help=f"Default verification mode ({', '.join(sorted(VERIFICATION_MODES))})",
    )
    p_sr.add_argument("--scope", choices=("global", "project"), required=True, help="Config scope (global or project)")
    p_sr.add_argument("--workspace", default=None, help="Workspace root for project scope")
    p_sr.add_argument("--diff", action="store_true", default=False, help="Preview changes as unified diff without writing")
    p_sr.add_argument("--expect-hash", default=None, help="Expected sha256 hash of target file before writing; refuse on mismatch")
    p_sr.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_sr.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_sr.set_defaults(func=cmd_set_routing)

    p_ip = sub.add_parser(
        "init-project",
        help=(
            "Initialize project orchestration.toml (<workspace>/.ai-orchestration.local.toml "
            "if present, gitignored, or ~/.config/ai-orchestration/projects/<workspace-name>/orchestration.toml)"
        ),
    )
    p_ip.add_argument("--workspace", default=".")
    p_ip.add_argument("--name", default=None)
    p_ip.add_argument("--orchestrator", default="kilo")
    p_ip.add_argument("--executor", default=None)
    p_ip.add_argument("--verification-mode", choices=sorted(VERIFICATION_MODES), default="cross-agent")
    p_ip.add_argument("--force", action="store_true")
    p_ip.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_ip.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_ip.set_defaults(func=cmd_init_project)

    p_ra = sub.add_parser("render-agents-md", help="Render or update the orchestration block in <workspace>/AGENTS.md")
    p_ra.add_argument("--workspace", default=".")
    p_ra.add_argument("--apply", action="store_true", help="Write/update <workspace>/AGENTS.md in-place")
    p_ra.add_argument("--check", action="store_true", help="Exit non-zero if <workspace>/AGENTS.md is out of sync")
    p_ra.add_argument("--diff", action="store_true", default=False, help="Preview changes as unified diff without writing")
    p_ra.add_argument("--expect-hash", default=None, help="Expected sha256 hash of target file before writing; refuse on mismatch")
    p_ra.add_argument("--allow-global-routing", action="store_true", default=False, help="Allow applying when workspace has no project config")
    p_ra.add_argument("--allow-unknown-models", action="store_true", default=False, help="Allow applying with unknown model IDs")
    p_ra.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_ra.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_ra.set_defaults(func=cmd_render_agents_md)

    p_setup = sub.add_parser(
        "setup",
        help="First-run setup engine: probe tools, propose defaults (Claude orch, Kilo exec with gemini-3.8-flash), preview diff with hash, and apply",
    )
    p_setup.add_argument("--workspace", default=".", help="Project workspace root")
    p_setup.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS, help="Override path to global config")
    p_setup.add_argument("--scope", choices=("global", "project", "project-local"), default="project", help="Config scope (default: project)")
    p_setup.add_argument("--orchestrator", default=None, help="Orchestrator tool ID")
    p_setup.add_argument("--executor", default=None, help="Default executor tool ID")
    p_setup.add_argument("--verification-mode", choices=sorted(VERIFICATION_MODES), default=None, help="Verification mode")
    p_setup.add_argument("--executor-model", default=None, help="Executor model (default: google/gemini-3.8-flash for kilo)")
    p_setup.add_argument("--orchestrator-model", default=None, help="Orchestrator model")
    p_setup.add_argument("--plan", action="store_true", default=False, help="Show setup plan without applying (default if --apply not passed)")
    p_setup.add_argument("--apply", action="store_true", default=False, help="Apply setup plan to target configuration")
    p_setup.add_argument("--expect-hash", default=None, help="Expected plan or config hash required to confirm and apply")
    p_setup.add_argument("--expect-plan-hash", default=None, help="Alias for --expect-hash")
    p_setup.add_argument("--start-orchestrator", action="store_true", default=False, help="Start orchestrator role after applying setup")
    p_setup.add_argument("--non-interactive", action="store_true", default=False, help="Never prompt for confirmation")
    p_setup.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_setup.set_defaults(func=cmd_setup)

    p_pf = sub.add_parser("preflight", help="Run [project.preflight] checks on the current host")
    p_pf.add_argument("--workspace", "--project", dest="workspace", default=".", help="Project workspace root")
    p_pf.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_pf.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_pf.set_defaults(func=cmd_preflight)

    p_vc = sub.add_parser("verify-checks", help="Execute [project.verification_checks] commands")
    p_vc.add_argument("checks", nargs="*", default=[], help="Optional subsystem check name(s) to run")
    p_vc.add_argument("--check", "--only", dest="check", action="append", default=[], help="Filter by subsystem check name")
    p_vc.add_argument("--workspace", "--project", dest="workspace", default=".", help="Project workspace root")
    p_vc.add_argument("--timeout", type=float, default=None, help="Override command timeout in seconds")
    p_vc.add_argument("--fail-fast", action="store_true", default=False, help="Stop on first failing command")
    p_vc.add_argument("--dry-run", action="store_true", default=False, help="List checks and commands without executing")
    p_vc.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_vc.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_vc.set_defaults(func=cmd_verify_checks)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
