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
import json
import os
import pathlib
import re
import sys
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
        if not isinstance(tcfg, dict) or not tcfg.get("enabled", True):
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

    return errors, warnings


# ---------------------------------------------------------------------------
# AGENTS.md Renderer (modeled on ~/works/ricerca_auto/AGENTS.md)
# ---------------------------------------------------------------------------

def render_agents_md_block(cfg: dict[str, Any]) -> str:
    proj = cfg.get("project", {})
    routing = cfg.get("routing", {})
    ver = cfg.get("verification", {})
    tools = cfg.get("tools", {})

    orchestrator_id = proj.get("primary_orchestrator") or routing.get("default_orchestrator", "kilo")
    executor_id = routing.get("default_executor", orchestrator_id)
    orch_tool = tools.get(orchestrator_id, {})
    exec_tool = tools.get(executor_id, orch_tool)

    # Determine dispatch tools description:
    # - When orchestrator == executor (Single-Framework Native mode): only native mechanisms are shown by default
    #   unless external MCP is also explicitly enabled for cross-framework delegation.
    # - When orchestrator != executor (Cross-Framework MCP mode): MCP implement tool is primary.
    same_framework = orchestrator_id == executor_id
    worktree_mech = (
        orch_tool.get("native_worktree_tool")
        if same_framework
        else (exec_tool.get("mcp_implement_tool") or orch_tool.get("native_worktree_tool") or "worktree")
    )
    subagent_mech = orch_tool.get("native_subagent_tool", "task")
    local_mech = orch_tool.get("native_local_tool", "local session")
    mcp_impl = exec_tool.get("mcp_implement_tool")
    mcp_note = (
        f' (or `{mcp_impl}(isolation="worktree")` when delegating via MCP)'
        if mcp_impl and not same_framework
        else ""
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

    # Build Role-to-Model table for the active executor/orchestrator tools
    active_tool_ids = []
    for tid in (orchestrator_id, executor_id):
        if tid in tools and tid not in active_tool_ids:
            active_tool_ids.append(tid)
    for tid, tcfg in tools.items():
        if isinstance(tcfg, dict) and tcfg.get("enabled", True) and tid not in active_tool_ids:
            active_tool_ids.append(tid)

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

    return f"""{BEGIN_MARKER}
# Agent Orchestration & Development Guidelines (`AGENTS.md`)

> **Managed by `ai-orchestration` (`orchestration_config.py render-agents-md`).**
> Edit `tasks/orchestration.toml` (project) or `~/.config/ai-orchestration/orchestration.toml` (global) and re-run `render-agents-md --apply` to update.

This repository uses an **Architect / Executor** development workflow (`primary_orchestrator = "{orchestrator_id}"`, `default_executor = "{executor_id}"`, `verification_mode = "{v_mode}"`). The **main session** acts strictly as the **Architect & Orchestrator** (discovery, task specification, parallel dispatch, verification, and integration), delegating implementation and heavy exploration to isolated **Worktree sessions** and **Subagents**.

---

## 1. Required Skills

Load and follow these skills whenever planning, delegating, executing, or reviewing work:

- **`orchestration-workflow`** (or **`kilo-mcp-orchestrator`** when driving via MCP) — Core 6-phase Architect/Executor loop (Discovery → Isolation → Delegation → Monitoring → Verification → Closure & Merge).
- **`task-spec-authoring`** — Authoring unambiguous, grounded task specs (`focus_files`, caller tracing, negative-claim rule, disjoint parallel write scopes, one-task-one-commit, risk-calibrated verification).
- **`task-pipeline`** — Structuring multi-task initiatives, specs, and emergent mid-session tasks inside `tasks/` (`00-INDEX.md`, `CONTEXT.md`, `specs/`, `NN-<slug>/plan.md`, `T###-<slug>`).
- **`task-worktree-ops`** — Operational git/worktree mechanics for inspecting, fixing, and merging Executor worktrees safely without racing active sessions.
- **`executor-contract`** — Behavioral contract for all delegated Executor sessions (zero interactivity, strict scope adherence, real verification before reporting, structured `Final Report`).
- **`conflict-resolver`** — Resolving merge conflicts across parallel Executor branches while preserving the semantics of each feature.
- **`orchestration-setup`** — Mapping abstract role profiles (`deep-reasoning`, `orchestration`, `bulk-execution`, `exploration`) to concrete models and reasoning variants.{domain_skill_section}

---

## 2. Core Operating Rules

### Rule 1: Keep the Main Session Free (Orchestrate, Don't Implement)

- The main session exists to **analyze requirements, design task specs, orchestrate parallel execution, and evaluate/verify results** with the user.
- **Do not perform feature implementation or multi-file coding in the main session**, even when a change looks quick ("it's small, I'll just do it" is forbidden).
- **Only exception:** During Phase 5 (Verification), the Architect may apply a trivial 1–5 line fix (e.g., typo, missing import) directly in the Executor's worktree rather than doing a full round-trip. Any logic or multi-line change must be bounced back to the Executor session.
- **Capture emergent work immediately:** If a bug, follow-up, or side requirement surfaces mid-conversation and won't be finished in the current turn, record it in `tasks/` (`task-pipeline`) and update `tasks/00-INDEX.md` before continuing. Keep the main session's context lean.

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
| **Isolated Git Worktree** *(Default for parallel code changes)* | `{worktree_mech}`{mcp_note} | Parallel implementation tasks modifying tracked files; multi-file features or refactors; comparing alternative implementations; long-running implementation work while keeping the main session clean. |
| **Background / Foreground Subagent** *(Read-only or strictly disjoint single-file work)* | `{subagent_mech}` (`explore` or `general`) | Codebase discovery, caller tracing, architectural analysis, **independent blind review of a draft spec or delivered task**, or strictly isolated single-file creation when no other git writer is active. |
| **Local / Follow-up Session** | `{local_mech}` | Follow-up steering inside an already-created worktree or single sequential task when explicitly requested in the current checkout. |

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
3. **Monitor & Intervene:** Monitor progress (or await via `kilo_task_wait` / background completion watcher). If a session drifts off-spec or stalls, cancel/stop early and steer the same session.
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
        print(f"[FAIL] invalid profile {args.profile!r}; must be one of {sorted(PROFILES)}", file=sys.stderr)
        return 2
    if args.basis and args.basis not in BASIS_VALUES:
        print(f"[FAIL] invalid basis {args.basis!r}; must be one of {sorted(BASIS_VALUES)}", file=sys.stderr)
        return 2

    if args.scope == "project":
        ws = pathlib.Path(args.workspace or ".").resolve()
        target_path = find_project_config_path(ws, args.global_config)
        data = load_toml_file(target_path) if target_path.exists() else {}
    else:
        target_path = args.global_config or default_global_config_path()
        data = load_toml_file(target_path) if target_path.exists() else copy.deepcopy(DEFAULT_GLOBAL_CONFIG)

    tools = data.setdefault("tools", {})
    tcfg = tools.setdefault(args.tool, {"enabled": True})
    profiles = tcfg.setdefault("profiles", {})
    entry = profiles.setdefault(args.profile, {})
    entry["model"] = args.model
    if args.variant is not None:
        entry["variant"] = args.variant
        entry.pop("effort", None)
    if args.effort is not None:
        entry["effort"] = args.effort
        entry.pop("variant", None)
    if args.basis is not None:
        entry["basis"] = args.basis
    data["last_verified"] = datetime.date.today().isoformat()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(dump_toml(data), encoding="utf-8")
    if args.json:
        print(json.dumps({"ok": True, "path": str(target_path), "tool": args.tool, "profile": args.profile, "entry": entry}))
    else:
        print(f"[ok] updated [{args.tool}.profiles.{args.profile}] in {target_path}")
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
    cfg, _ = resolve_config(args.global_config, ws)
    block = render_agents_md_block(cfg)
    agents_md_path = ws / "AGENTS.md"

    existing = agents_md_path.read_text(encoding="utf-8") if agents_md_path.exists() else ""
    updated = inject_or_replace_agents_block(existing, block)

    if args.check:
        in_sync = existing == updated
        if args.json:
            print(json.dumps({"ok": in_sync, "path": str(agents_md_path)}))
        elif not in_sync:
            print(f"[FAIL] {agents_md_path} orchestration block is out of sync")
        else:
            print(f"[ok] {agents_md_path} orchestration block is in sync")
        return 0 if in_sync else 1

    if args.apply:
        agents_md_path.write_text(updated, encoding="utf-8")
        if args.json:
            print(json.dumps({"ok": True, "applied": True, "path": str(agents_md_path)}))
        else:
            print(f"[ok] updated {agents_md_path}")
        return 0

    if args.json:
        print(json.dumps({"ok": True, "applied": False, "path": str(agents_md_path), "rendered_block": block}))
    else:
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
    p_sp.add_argument("--global-config", type=pathlib.Path, default=argparse.SUPPRESS)
    p_sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_sp.set_defaults(func=cmd_set_profile)

    p_ip = sub.add_parser("init-project", help="Initialize <workspace>/tasks/orchestration.toml")
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
