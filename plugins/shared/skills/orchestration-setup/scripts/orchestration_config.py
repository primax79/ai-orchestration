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
import copy
import datetime
import difflib
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import uuid
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore

PROFILES = ("deep-reasoning", "orchestration", "bulk-execution", "exploration")
PROFILE_SET = set(PROFILES)
BASIS_VALUES = {
    "host-metadata",
    "provider-tier-naming",
    "model-self-knowledge",
    "operator-stated",
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
        "default_orchestrator": "kilo",
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
                    "basis": "operator-stated",
                },
                "orchestration": {
                    "model": "google/gemini-4-argon",
                    "variant": "medium",
                    "basis": "operator-stated",
                },
                "bulk-execution": {
                    "model": "google/gemini-3.8-flash",
                    "variant": "medium",
                    "basis": "operator-stated",
                },
                "exploration": {
                    "model": "google/gemini-3.8-flash",
                    "variant": "low",
                    "basis": "operator-stated",
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
                    "basis": "operator-stated",
                },
                "orchestration": {
                    "model": "sonnet",
                    "effort": "medium",
                    "basis": "operator-stated",
                },
                "bulk-execution": {
                    "model": "sonnet",
                    "effort": "medium",
                    "basis": "operator-stated",
                },
                "exploration": {
                    "model": "haiku",
                    "effort": "low",
                    "basis": "operator-stated",
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
                    "basis": "operator-stated",
                },
                "orchestration": {
                    "model": "gpt-5-codex",
                    "effort": "medium",
                    "basis": "operator-stated",
                },
                "bulk-execution": {
                    "model": "gpt-5-codex-mini",
                    "effort": "medium",
                    "basis": "operator-stated",
                },
                "exploration": {
                    "model": "gpt-5-codex-mini",
                    "effort": "low",
                    "basis": "operator-stated",
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
    if env_path:
        return pathlib.Path(env_path).expanduser().resolve()
    return pathlib.Path.home() / ".config" / "ai-orchestration" / "orchestration.toml"


def find_project_config_path(
    workspace: pathlib.Path,
    global_path: pathlib.Path | None = None,
) -> pathlib.Path:
    """Return the UNVERSIONED local project agent configuration path.

    Agent/model/tool choices are local to the developer's machine and must NOT
    be committed to the repository's versioned `tasks/` tree.
    Precedence:
      1. `<workspace>/.ai-orchestration.local.toml` (if already present locally, gitignored)
      2. `~/.config/ai-orchestration/projects/<workspace-name>/orchestration.toml` (outside repo)
    """
    local_dot = workspace / ".ai-orchestration.local.toml"
    if local_dot.exists():
        return local_dot
    gpath = global_path or default_global_config_path()
    projects_root = gpath.parent / "projects"
    return projects_root / workspace.resolve().name / "orchestration.toml"


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
    if workspace is not None:
        ppath = find_project_config_path(workspace, gpath)
        if ppath.exists():
            project_cfg = load_toml_file(ppath)

    merged = deep_merge(DEFAULT_GLOBAL_CONFIG, global_cfg)
    if project_cfg:
        merged = deep_merge(merged, project_cfg)

    meta = {
        "global_config_path": str(gpath),
        "global_config_exists": gpath.exists(),
        "project_config_path": str(ppath) if ppath else None,
        "project_config_exists": bool(ppath and ppath.exists()),
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

    return errors, warnings


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
    proj_cfg_path = find_project_config_path(ws, global_path)
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
            "Keep the main session's context lean."
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
            "Keep the main session's context lean."
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


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_show(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    cfg, meta = resolve_config(args.global_config, ws)
    errors, warnings = validate_config(cfg)
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
    errors, warnings = validate_config(cfg)
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
    if gpath.exists() and not args.force:
        msg = f"{gpath} already exists (pass --force to overwrite)."
        if args.json:
            print(json.dumps({"ok": False, "path": str(gpath), "message": msg}))
        else:
            print(f"[skip] {msg}")
        return 0
    gpath.parent.mkdir(parents=True, exist_ok=True)
    content = dump_toml(DEFAULT_GLOBAL_CONFIG)
    gpath.write_text(content, encoding="utf-8")
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
        target_path = find_project_config_path(ws, gpath)
        if target_path.exists():
            current_bytes = target_path.read_bytes()
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            existing_text = current_bytes.decode("utf-8")
        else:
            current_bytes = b""
            current_hash = hashlib.sha256(b"").hexdigest()
            existing_text = ""
        text = existing_text
    else:
        target_path = gpath or default_global_config_path()
        if target_path.exists():
            current_bytes = target_path.read_bytes()
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            existing_text = current_bytes.decode("utf-8")
            text = existing_text
        else:
            current_bytes = b""
            current_hash = hashlib.sha256(b"").hexdigest()
            existing_text = ""
            text = dump_toml(DEFAULT_GLOBAL_CONFIG)

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

    if getattr(args, "diff", False):
        diff_str = "".join(
            difflib.unified_diff(
                existing_text.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=f"a/{target_path.name}",
                tofile=f"b/{target_path.name}",
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

    if getattr(args, "expect_hash", None) is not None:
        disk_bytes = target_path.read_bytes() if target_path.exists() else b""
        actual_hash = hashlib.sha256(disk_bytes).hexdigest()
        if actual_hash.lower() != args.expect_hash.strip().lower():
            msg = f"hash mismatch for {target_path}: expected {args.expect_hash}, found {actual_hash}"
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": msg,
                            "expected_hash": args.expect_hash,
                            "actual_hash": actual_hash,
                            "path": str(target_path),
                        }
                    )
                )
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2

    write_file_atomic(target_path, text)

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
        target_path = find_project_config_path(project_ws, gpath)
    else:
        target_path = gpath or default_global_config_path()

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

    if getattr(args, "diff", False):
        diff_str = "".join(
            difflib.unified_diff(
                existing_text.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=f"a/{target_path.name}",
                tofile=f"b/{target_path.name}",
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

    if getattr(args, "expect_hash", None) is not None:
        disk_bytes = target_path.read_bytes() if target_path.exists() else b""
        actual_hash = hashlib.sha256(disk_bytes).hexdigest()
        if actual_hash.lower() != args.expect_hash.strip().lower():
            msg = f"hash mismatch for {target_path}: expected {args.expect_hash}, found {actual_hash}"
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": msg,
                            "expected_hash": args.expect_hash,
                            "actual_hash": actual_hash,
                            "path": str(target_path),
                        }
                    )
                )
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2

    write_file_atomic(target_path, text)

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
    ppath = find_project_config_path(ws, args.global_config)
    if ppath.exists() and not args.force:
        if args.json:
            print(json.dumps({"ok": False, "path": str(ppath), "message": "already exists"}))
        else:
            print(f"[skip] {ppath} already exists (pass --force to overwrite)")
        return 0

    proj_data: dict[str, Any] = {
        "project": {
            "name": args.name or ws.name,
            "primary_orchestrator": args.orchestrator or "kilo",
        },
        "routing": {
            "default_executor": args.executor or (args.orchestrator or "kilo"),
        },
        "verification": {
            "default_mode": args.verification_mode or "cross-agent",
        },
        "project_isolation": {},
    }
    # Use nested [project.isolation]
    proj_data.pop("project_isolation", None)
    proj_data["project"]["isolation"] = {
        "shared_databases": [],
        "shared_ports": [],
        "worker_port_range": [8766, 8779],
        "conflict_prone_files": [],
        "zero_conflict_registries": [],
    }
    ppath.parent.mkdir(parents=True, exist_ok=True)
    ppath.write_text(dump_toml(proj_data), encoding="utf-8")
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

    warnings: list[str] = []
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

        if not getattr(args, "apply", False):
            msg = "--expect-hash requires --apply"
            if getattr(args, "json", False):
                print(json.dumps({"ok": False, "error": msg}))
            else:
                print(f"[FAIL] {msg}", file=sys.stderr)
            return 2

    if getattr(args, "apply", False):
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--global-config", type=pathlib.Path, default=None, help="Override path to global orchestration.toml")
    ap.add_argument("--json", action="store_true", help="Output structured JSON on stdout")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="Show merged Global + Project configuration")
    p_show.add_argument("--workspace", default=None, help="Project workspace root")
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

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
