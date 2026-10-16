#!/usr/bin/env python3
"""orchestration_env.py — From-Scratch Installer, Skill Manager & Environment Doctor
for `ai-orchestration`, `kilo-mcp`, `claude-mcp`, and `codex`.

Powers:
  1. From-scratch CLI installation (`./install.sh` or `./bin/ai-orch env ...`)
  2. Macro-Task 2 of the Orchestration Extension (Install skills & MCPs across Kilo, Claude, Codex)
  3. Macro-Task 3 of the Orchestration Extension (Verify status/drift of skills, agents & MCPs)

Supports 3 first-class assistant environments (`kilo`, `claude`, `codex`) and 2 scopes (`global`, `project`).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import pathlib
import re
import shutil
import tempfile
import subprocess
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSISTANTS = ("kilo", "claude", "codex")
SCOPES = ("global", "project")

REMOTE_REPOS = {
    "ai-orchestration": "https://github.com/primax79/ai-orchestration.git",
    "kilo-mcp": "https://github.com/primax79/kilo-mcp.git",
}

OBSOLETE_SKILL_RENAMES = {
    "interactive-role-setup": "orchestration-setup",
    "orchestration-methodology": "orchestration-workflow",
    "delegation-roi-analysis": "orchestration-metrics",
    "macroplan-authoring": "task-pipeline",
    "task-delegation": "task-worktree-ops",
    "headless-executor-contract": "executor-contract",
    "mcp-metrics-analyst": "kilo-mcp-metrics-analyst",
    "kilo-mcp-headless-executor": "kilo-mcp-executor-contract",
    "mcp-orchestrator": "kilo-mcp-orchestrator",
}

OBSOLETE_AGENT_RENAMES = {
    "mcp-orchestrator-agent.md": "kilo-mcp-orchestrator-agent.md",
}

# A skill name is a single directory name: no separators, no "." / ".." components.
SKILL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


# ---------------------------------------------------------------------------
# Helpers: Hashing, Paths & Repo Discovery
# ---------------------------------------------------------------------------

def hash_directory(dir_path: pathlib.Path) -> str:
    """Deterministic SHA-256 over all files in a skill directory (ignoring index.json and hidden files)."""
    h = hashlib.sha256()
    if not dir_path.is_dir():
        return ""
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for fname in sorted(files):
            if fname.startswith(".") or fname.endswith(".pyc") or fname == "index.json":
                continue
            fpath = pathlib.Path(root) / fname
            rel = fpath.relative_to(dir_path).as_posix()
            h.update(rel.encode("utf-8") + b"\0")
            h.update(fpath.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def get_home_dir() -> pathlib.Path:
    env_home = os.environ.get("AI_ORCH_HOME")
    if env_home:
        return pathlib.Path(env_home).expanduser().resolve()
    return pathlib.Path.home()


def get_repos_cache_dir(home: pathlib.Path | None = None) -> pathlib.Path:
    h = home or get_home_dir()
    return h / ".ai-orchestration" / "repos"


def resolve_source_repo(repo_name: str, home: pathlib.Path | None = None) -> pathlib.Path | None:
    """Find `ai-orchestration`, `kilo-mcp`, or `claude-mcp` locally (sibling checkout) or in ~/.ai-orchestration/repos/."""
    if repo_name == "ai-orchestration" and (REPO_ROOT / "plugins").is_dir():
        return REPO_ROOT
    sibling = REPO_ROOT.parent / repo_name
    if sibling.is_dir():
        return sibling
    for parent in REPO_ROOT.parents:
        cand = parent / repo_name
        if cand.is_dir():
            return cand
    cached = get_repos_cache_dir(home) / repo_name
    if cached.is_dir():
        return cached
    return None


def trash_path(path: pathlib.Path, timestamp: str | None = None) -> pathlib.Path:
    """Move a file, directory, or symlink into .ai-orch-trash/<timestamp>/<name> instead of deleting."""
    if not (path.exists() or path.is_symlink()):
        return path
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trash_dir = path.parent / ".ai-orch-trash" / ts
    trash_dir.mkdir(parents=True, exist_ok=True)
    dest = trash_dir / path.name
    counter = 1
    while dest.exists() or dest.is_symlink():
        dest = trash_dir / f"{path.name}_{counter}"
        counter += 1
    shutil.move(str(path), str(dest))
    return dest


def compute_plan_hash(plan: list[dict[str, Any]]) -> str:
    """SHA-256 over canonical JSON representation of plan (sort_keys=True, separators=(',', ':'))."""
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def assistant_skills_dir(
    assistant: str,
    scope: str,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
) -> pathlib.Path:
    h = home or get_home_dir()
    ws = workspace or pathlib.Path.cwd()
    folder_map = {
        "kilo": ".kilo",
        "claude": ".claude",
        "codex": ".codex",
    }
    dot_folder = folder_map[assistant]
    base = h if scope == "global" else ws
    return base / dot_folder / "skills"


def assistant_mcp_config_path(
    assistant: str,
    scope: str,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
) -> pathlib.Path:
    h = home or get_home_dir()
    ws = workspace or pathlib.Path.cwd()
    if assistant == "claude":
        return (h / ".claude.json") if scope == "global" else (ws / ".mcp.json")
    if assistant == "kilo":
        return (h / ".config" / "kilo" / "kilo.json") if scope == "global" else (ws / ".kilo" / "kilo.json")
    if assistant == "codex":
        return (h / ".codex" / "config.json") if scope == "global" else (ws / ".codex" / "config.json")
    raise ValueError(f"Unknown assistant: {assistant}")


# ---------------------------------------------------------------------------
# Catalog Discovery from Local / Cloned Source Repos
# ---------------------------------------------------------------------------

def discover_available_skills(home: pathlib.Path | None = None) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Return map of (repo, plugin, skill_name) -> {name, repo, plugin, path, hash} across ai-orchestration and kilo-mcp."""
    catalog: dict[tuple[str, str, str], dict[str, Any]] = {}
    for repo_name in ("ai-orchestration", "kilo-mcp", "claude-mcp"):
        rpath = resolve_source_repo(repo_name, home)
        if not rpath or not (rpath / "plugins").is_dir():
            continue
        for skill_md in sorted((rpath / "plugins").glob("*/skills/*/SKILL.md")):
            sdir = skill_md.parent
            pdir = sdir.parent.parent
            sname = sdir.name
            catalog[(repo_name, pdir.name, sname)] = {
                "name": sname,
                "repo": repo_name,
                "plugin": pdir.name,
                "path": str(sdir),
                "hash": hash_directory(sdir),
            }
    return catalog


def detect_skill_state(
    child: pathlib.Path,
    catalog: dict[tuple[str, str, str], dict[str, Any]],
    home: pathlib.Path | None = None,
) -> tuple[str, str | None, str | None]:
    """Determine state, source_repo, and source_hash for an installed skill directory/symlink.

    States:
      - 'obsolete-renamed-><target>': skill name is in OBSOLETE_SKILL_RENAMES
      - 'unmanaged': skill name does not match any skill in catalog
      - 'up-to-date': matches a catalog skill by content hash or symlink target
      - 'modified-or-outdated': name in catalog, content differs or not symlink to catalog,
                                but was installed by this tool (.ai-orch-source.json or symlink into known repo)
      - 'foreign': name in catalog, but content differs/not catalog symlink AND not installed by this tool
    """
    sname = child.name
    if sname in OBSOLETE_SKILL_RENAMES:
        return (f"obsolete-renamed->{OBSOLETE_SKILL_RENAMES[sname]}", None, None)

    matching_entries = [entry for entry in catalog.values() if entry["name"] == sname]
    if not matching_entries:
        return ("unmanaged", None, None)

    inst_hash = hash_directory(child) if (child.is_dir() and not child.is_symlink()) or (child.is_symlink() and child.resolve().is_dir()) else ""

    # Check up-to-date by content hash
    for entry in matching_entries:
        if inst_hash and inst_hash == entry["hash"]:
            return ("up-to-date", entry["repo"], entry["hash"])

    # Check up-to-date by direct symlink to catalog source
    if child.is_symlink():
        try:
            resolved = child.resolve()
            for entry in matching_entries:
                if resolved == pathlib.Path(entry["path"]).resolve():
                    return ("up-to-date", entry["repo"], entry["hash"])
        except Exception:
            pass

    # Content matches no catalog entry and not a symlink to catalog entry.
    # Check if installed by this tool:
    # 1. Copy mode: marker file .ai-orch-source.json
    marker = child / ".ai-orch-source.json"
    if marker.is_file():
        try:
            mdata = json.loads(marker.read_text(encoding="utf-8"))
            mrepo = mdata.get("repo")
            mhash = mdata.get("hash")
            mplugin = mdata.get("plugin")
            if (mrepo, mplugin, sname) in catalog:
                mhash = catalog[(mrepo, mplugin, sname)]["hash"]
            return ("modified-or-outdated", mrepo, mhash)
        except Exception:
            return ("modified-or-outdated", None, None)

    # 2. Link mode: symlink target into known source repo
    if child.is_symlink():
        try:
            resolved = child.resolve()
            for rname in ("ai-orchestration", "kilo-mcp", "claude-mcp"):
                rpath = resolve_source_repo(rname, home)
                if rpath and (resolved == rpath or rpath in resolved.parents):
                    cat_entry = next((e for e in matching_entries if e["repo"] == rname), None)
                    return ("modified-or-outdated", rname, cat_entry["hash"] if cat_entry else None)
        except Exception:
            pass

    # Neither marker nor symlink to known repo
    return ("foreign", None, None)


def load_conflict_policy(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
) -> dict[str, str]:
    """Read conflict resolution policy from config [env.conflicts] keep = { kilo = ..., claude = ..., codex = ... }.

    Defaults:
      kilo = generic
      claude = bound
      codex = bound
    """
    default_policy = {
        "kilo": "generic",
        "claude": "bound",
        "codex": "bound",
    }
    h = home or get_home_dir()
    gpath = h / ".config" / "ai-orchestration" / "orchestration.toml"

    cfg: dict[str, Any] = {}
    try:
        setup_scripts = REPO_ROOT / "plugins" / "shared" / "skills" / "orchestration-setup" / "scripts"
        if setup_scripts.is_dir() and str(setup_scripts) not in sys.path:
            sys.path.insert(0, str(setup_scripts))
        import orchestration_config  # type: ignore
        merged, _ = orchestration_config.resolve_config(
            global_path=gpath if gpath.exists() else None,
            workspace=workspace,
        )
        cfg = merged
    except Exception:
        try:
            import tomllib  # Python 3.11+
            if gpath.is_file():
                cfg = tomllib.loads(gpath.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    keep_cfg = cfg.get("env", {}).get("conflicts", {}).get("keep", {})
    if not isinstance(keep_cfg, dict):
        keep_cfg = {}

    return {
        "kilo": keep_cfg.get("kilo", default_policy["kilo"]),
        "claude": keep_cfg.get("claude", default_policy["claude"]),
        "codex": keep_cfg.get("codex", default_policy["codex"]),
    }


# ---------------------------------------------------------------------------
# Environment Status & Drift Check (Macro-Task 3)
# ---------------------------------------------------------------------------

def check_cli_binary(cmd: str) -> dict[str, Any]:
    exe = shutil.which(cmd)
    if not exe:
        return {"installed": False, "path": None, "version": None}
    try:
        res = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5, check=False)
        ver = (res.stdout or res.stderr).strip().splitlines()[0] if (res.stdout or res.stderr) else "unknown"
    except Exception:
        ver = "unknown"
    return {"installed": True, "path": exe, "version": ver}


def read_registered_mcps(config_path: pathlib.Path, assistant: str) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if assistant == "kilo":
        return data.get("mcp", data.get("mcpServers", {})) if isinstance(data, dict) else {}
    return data.get("mcpServers", data.get("mcp_servers", {})) if isinstance(data, dict) else {}


def inspect_environment(
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
) -> dict[str, Any]:
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    catalog = discover_available_skills(h)

    clis = {tool: check_cli_binary(tool) for tool in ASSISTANTS}
    repos_status = {}
    for rname in ("ai-orchestration", "kilo-mcp", "claude-mcp"):
        rpath = resolve_source_repo(rname, h)
        repos_status[rname] = {
            "available": rpath is not None,
            "path": str(rpath) if rpath else None,
            "has_server_py": bool(rpath and (rpath / "server.py").is_file()),
            "has_venv": bool(rpath and (rpath / ".venv" / "bin" / "python").is_file()),
        }

    environments: dict[str, Any] = {}
    scopes_to_check = ["global"] + (["project"] if ws else [])

    for assistant in ASSISTANTS:
        environments[assistant] = {}
        for scope in scopes_to_check:
            sdir = assistant_skills_dir(assistant, scope, ws, h)
            installed_skills: dict[str, Any] = {}
            if sdir.is_dir():
                for child in sorted(sdir.iterdir()):
                    if child.name == ".ai-orch-trash" or child.name.startswith("."):
                        continue
                    if not (child.is_dir() or child.is_symlink()):
                        continue
                    skill_md = child / "SKILL.md"
                    if not skill_md.is_file():
                        continue
                    sname = child.name
                    inst_hash = hash_directory(child)
                    state, src_repo, src_hash = detect_skill_state(child, catalog, h)
                    installed_skills[sname] = {
                        "state": state,
                        "is_symlink": child.is_symlink(),
                        "installed_hash": inst_hash,
                        "source_repo": src_repo,
                        "source_hash": src_hash,
                    }

            # Detect conflict: generic orchestration-workflow + bound kilo-mcp-orchestrator both installed
            conflicts = []
            if "orchestration-workflow" in installed_skills and "kilo-mcp-orchestrator" in installed_skills:
                conflicts.append(
                    "Both generic 'orchestration-workflow' and bound 'kilo-mcp-orchestrator' are installed in the same scope; they compete for the same trigger."
                )

            mcp_cfg_path = assistant_mcp_config_path(assistant, scope, ws, h)
            mcps = read_registered_mcps(mcp_cfg_path, assistant)

            environments[assistant][scope] = {
                "skills_dir": str(sdir),
                "installed_count": len(installed_skills),
                "skills": installed_skills,
                "conflicts": conflicts,
                "mcp_config_path": str(mcp_cfg_path),
                "registered_mcps": sorted(mcps.keys()),
            }

    return {
        "clis": clis,
        "source_repos": repos_status,
        "available_catalog_count": len(catalog),
        "environments": environments,
    }


# ---------------------------------------------------------------------------
# Installation Actions: Clone/Pull, Install Skills, Register MCP (Macro-Task 2)
# ---------------------------------------------------------------------------

def clone_or_update_repos(
    repos: list[str],
    home: pathlib.Path | None = None,
) -> dict[str, Any]:
    cache_dir = get_repos_cache_dir(home)
    cache_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}

    for rname in repos:
        existing = resolve_source_repo(rname, home)
        if existing and existing.parent != cache_dir:
            results[rname] = {"action": "using-local-checkout", "path": str(existing), "ok": True}
            continue
        target = cache_dir / rname
        url = REMOTE_REPOS.get(rname)
        if not url:
            results[rname] = {"action": "skipped-no-remote", "path": None, "ok": False}
            continue
        if (target / ".git").is_dir():
            res = subprocess.run(["git", "-C", str(target), "pull", "--ff-only"], capture_output=True, text=True, check=False)
            results[rname] = {"action": "updated", "path": str(target), "ok": res.returncode == 0}
        else:
            res = subprocess.run(["git", "clone", url, str(target)], capture_output=True, text=True, check=False)
            results[rname] = {"action": "cloned", "path": str(target), "ok": res.returncode == 0}
    return results


def install_skills(
    assistants: list[str],
    scope: str,
    repo_name: str = "ai-orchestration",
    plugins: list[str] | None = None,
    link: bool = False,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
    overwrite: list[str] | None = None,
) -> dict[str, Any]:
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else pathlib.Path.cwd()
    rpath = resolve_source_repo(repo_name, h)
    if not rpath or not (rpath / "plugins").is_dir():
        raise FileNotFoundError(f"Source repository {repo_name!r} not found locally. Run `fetch-repos` first.")

    selected_plugins = plugins or ["architect-side", "executor-side", "shared"]
    catalog = discover_available_skills(h)
    overwrite_set = set(overwrite or [])
    overwrite_all = "all" in overwrite_set

    plan: list[dict[str, Any]] = []
    planned_ops: list[dict[str, Any]] = []

    for assistant in assistants:
        dest_skills_dir = assistant_skills_dir(assistant, scope, ws, h)
        dest_agents_dir = (
            (h / ".config" / "kilo" / "agents")
            if (assistant == "kilo" and scope == "global")
            else (dest_skills_dir.parent / "agents")
        )

        # 1. Obsolete skills
        for old_name in sorted(OBSOLETE_SKILL_RENAMES):
            old_dir = dest_skills_dir / old_name
            if old_dir.exists() or old_dir.is_symlink():
                new_target = OBSOLETE_SKILL_RENAMES[old_name]
                p_item = {
                    "action": "trash",
                    "path": str(old_dir),
                    "reason": f"obsolete pre-rename name of {new_target}",
                    "current_state": f"obsolete-renamed->{new_target}",
                }
                plan.append(p_item)
                planned_ops.append({"type": "obsolete_skill", "path": old_dir, "plan_item": p_item})

        # 2. Obsolete agents
        if dest_agents_dir.is_dir():
            for old_agent in sorted(OBSOLETE_AGENT_RENAMES):
                old_a_path = dest_agents_dir / old_agent
                if old_a_path.exists() or old_a_path.is_symlink():
                    new_agent = OBSOLETE_AGENT_RENAMES[old_agent]
                    p_item = {
                        "action": "trash",
                        "path": str(old_a_path),
                        "reason": f"obsolete pre-rename name of {new_agent}",
                        "current_state": f"obsolete-renamed->{new_agent}",
                    }
                    plan.append(p_item)
                    planned_ops.append({"type": "obsolete_agent", "path": old_a_path, "plan_item": p_item})

        # 3. Agent files to install
        for p_name in selected_plugins:
            src_agents_root = rpath / "plugins" / p_name / "agents"
            if src_agents_root.is_dir() and assistant in ("claude", "kilo"):
                for agent_md in sorted(src_agents_root.glob("*.md")):
                    target_agent = dest_agents_dir / agent_md.name
                    is_existing = target_agent.exists() or target_agent.is_symlink()
                    action = "replace" if is_existing else "create"
                    cur_state = "installed" if is_existing else "missing"
                    p_item = {
                        "action": action,
                        "path": str(target_agent),
                        "reason": f"Install agent '{agent_md.name}' from {repo_name}/{p_name}",
                        "current_state": cur_state,
                    }
                    plan.append(p_item)
                    planned_ops.append({
                        "type": "agent",
                        "action": action,
                        "src": agent_md,
                        "target": target_agent,
                        "dest_dir": dest_agents_dir,
                        "link": link,
                        "plan_item": p_item,
                    })

        # 4. Skills to install
        for p_name in selected_plugins:
            src_skills_root = rpath / "plugins" / p_name / "skills"
            if not src_skills_root.is_dir():
                continue
            for skill_md in sorted(src_skills_root.glob("*/SKILL.md")):
                src_dir = skill_md.parent
                sname = src_dir.name
                target_dir = dest_skills_dir / sname
                is_existing = target_dir.exists() or target_dir.is_symlink()
                if not is_existing:
                    action = "create"
                    cur_state = "missing"
                    reason = f"Install skill '{sname}' from {repo_name}/{p_name}"
                else:
                    cur_state, s_repo, s_hash = detect_skill_state(target_dir, catalog, h)
                    if cur_state in ("unmanaged", "modified-or-outdated", "foreign"):
                        if overwrite_all or sname in overwrite_set:
                            action = "replace"
                            reason = f"Replace {cur_state} skill '{sname}' with {repo_name}/{p_name} (--overwrite)"
                        else:
                            action = "skip"
                            reason = f"Skip {cur_state} skill '{sname}': not in --overwrite list"
                    else:
                        action = "replace"
                        reason = f"Update skill '{sname}' from {repo_name}/{p_name}"

                p_item = {
                    "action": action,
                    "path": str(target_dir),
                    "reason": reason,
                    "current_state": cur_state,
                }
                plan.append(p_item)
                planned_ops.append({
                    "type": "skill",
                    "action": action,
                    "assistant": assistant,
                    "scope": scope,
                    "skill": sname,
                    "plugin": p_name,
                    "repo": repo_name,
                    "src": src_dir,
                    "target": target_dir,
                    "dest_dir": dest_skills_dir,
                    "link": link,
                    "plan_item": p_item,
                })

    plan_hash = compute_plan_hash(plan)
    if expect_plan_hash is not None and expect_plan_hash != plan_hash:
        return {
            "ok": False,
            "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
            "plan": plan,
            "plan_hash": plan_hash,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "plan": plan,
            "plan_hash": plan_hash,
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    installed: list[dict[str, str]] = []
    removed_obsolete: list[str] = []

    for op in planned_ops:
        action = op.get("action", "trash")
        if action == "skip":
            continue
        if op["type"] in ("obsolete_skill", "obsolete_agent"):
            trash_path(op["path"], timestamp=ts)
            removed_obsolete.append(str(op["path"]))
        elif op["type"] == "agent":
            op["dest_dir"].mkdir(parents=True, exist_ok=True)
            if action == "replace":
                trash_path(op["target"], timestamp=ts)
            if op["link"]:
                op["target"].symlink_to(op["src"])
            else:
                shutil.copy2(op["src"], op["target"])
        elif op["type"] == "skill":
            op["dest_dir"].mkdir(parents=True, exist_ok=True)
            if action == "replace":
                trash_path(op["target"], timestamp=ts)
            if op["link"]:
                op["target"].symlink_to(op["src"])
            else:
                shutil.copytree(
                    op["src"],
                    op["target"],
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
                )
                marker_data = {
                    "repo": op["repo"],
                    "plugin": op["plugin"],
                    "name": op["skill"],
                    "hash": hash_directory(op["src"]),
                }
                (op["target"] / ".ai-orch-source.json").write_text(
                    json.dumps(marker_data, indent=2) + "\n",
                    encoding="utf-8",
                )
            installed.append({
                "assistant": op["assistant"],
                "scope": op["scope"],
                "skill": op["skill"],
                "plugin": op["plugin"],
                "repo": op["repo"],
                "target": str(op["target"]),
                "mode": "symlink" if op["link"] else "copy",
            })

    return {
        "ok": True,
        "installed_count": len(installed),
        "installed": installed,
        "removed_obsolete": removed_obsolete,
        "plan": plan,
        "plan_hash": plan_hash,
    }


def remove_skill(
    assistant: str,
    scope: str,
    skill_name: str,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else pathlib.Path.cwd()
    if not SKILL_NAME_RE.fullmatch(skill_name or ""):
        return {"ok": False, "message": f"Invalid skill name {skill_name!r}: expected a single directory name ([A-Za-z0-9][A-Za-z0-9._-]*)", "plan": [], "plan_hash": compute_plan_hash([])}
    if skill_name == ".ai-orch-trash":
        return {"ok": False, "message": "Cannot remove .ai-orch-trash", "plan": [], "plan_hash": compute_plan_hash([])}
    skills_dir = assistant_skills_dir(assistant, scope, ws, h)
    dest_dir = skills_dir / skill_name
    # Defence in depth: the target must be a direct child of the skills dir (no traversal, no symlinked parent tricks)
    if dest_dir.parent.resolve() != skills_dir.resolve():
        return {"ok": False, "message": f"Refusing to remove {dest_dir}: not a direct child of {skills_dir}", "plan": [], "plan_hash": compute_plan_hash([])}
    if not (dest_dir.exists() or dest_dir.is_symlink()):
        return {"ok": False, "message": f"Skill '{skill_name}' not found in {dest_dir.parent}", "plan": [], "plan_hash": compute_plan_hash([])}

    catalog = discover_available_skills(h)
    cur_state, _, _ = detect_skill_state(dest_dir, catalog, h)
    plan = [{
        "action": "trash",
        "path": str(dest_dir),
        "reason": f"Remove skill '{skill_name}' from {assistant} ({scope})",
        "current_state": cur_state,
    }]
    plan_hash = compute_plan_hash(plan)

    if expect_plan_hash is not None and expect_plan_hash != plan_hash:
        return {
            "ok": False,
            "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
            "plan": plan,
            "plan_hash": plan_hash,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "plan": plan,
            "plan_hash": plan_hash,
        }

    trash_path(dest_dir)
    return {
        "ok": True,
        "removed": str(dest_dir),
        "assistant": assistant,
        "scope": scope,
        "skill": skill_name,
        "plan": plan,
        "plan_hash": plan_hash,
    }


def resolve_conflicts(
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Auto-resolve trigger conflicts across assistant environments using configured policy:
      - default: Kilo keeps generic, Claude & Codex keep bound.
      - or as specified in [env.conflicts] keep = { kilo = ..., claude = ..., codex = ... }
    """
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    scopes_to_check = ["global"] + (["project"] if ws else [])
    policy = load_conflict_policy(h, ws)

    plan: list[dict[str, Any]] = []
    conflict_items: list[dict[str, Any]] = []

    for assistant in ASSISTANTS:
        for scope in scopes_to_check:
            sdir = assistant_skills_dir(assistant, scope, ws, h)
            has_generic = (sdir / "orchestration-workflow").exists()
            has_bound = (sdir / "kilo-mcp-orchestrator").exists()
            if has_generic and has_bound:
                keep_target = policy.get(assistant, "generic" if assistant == "kilo" else "bound")
                if keep_target == "generic":
                    to_remove = "kilo-mcp-orchestrator"
                    to_keep = "orchestration-workflow"
                else:
                    to_remove = "orchestration-workflow"
                    to_keep = "kilo-mcp-orchestrator"
                target_path = sdir / to_remove
                p_item = {
                    "action": "trash",
                    "path": str(target_path),
                    "reason": f"Resolve conflict in {assistant} ({scope}): keep '{to_keep}', trash '{to_remove}' per policy",
                    "current_state": "conflict",
                }
                plan.append(p_item)
                conflict_items.append({
                    "assistant": assistant,
                    "scope": scope,
                    "removed": to_remove,
                    "kept": to_keep,
                    "path": target_path,
                })

    plan_hash = compute_plan_hash(plan)
    if expect_plan_hash is not None and expect_plan_hash != plan_hash:
        return {
            "ok": False,
            "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
            "plan": plan,
            "plan_hash": plan_hash,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "resolved_count": len(plan),
            "resolved": [],
            "plan": plan,
            "plan_hash": plan_hash,
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    resolved: list[dict[str, str]] = []
    for item in conflict_items:
        trash_path(item["path"], timestamp=ts)
        resolved.append({
            "assistant": item["assistant"],
            "scope": item["scope"],
            "removed": item["removed"],
            "kept": item["kept"],
        })

    return {
        "ok": True,
        "resolved_count": len(resolved),
        "resolved": resolved,
        "plan": plan,
        "plan_hash": plan_hash,
    }


def _atomic_write_with_backup(path: pathlib.Path, content: str) -> None:
    """Write `content` to `path` atomically, keeping the previous version as `<name>.ai-orch.bak`."""
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".ai-orch.bak"))
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def register_mcp_server(
    server_repo: str,
    assistants: list[str],
    scope: str = "global",
    provision_venv: bool = False,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else pathlib.Path.cwd()

    if server_repo == "codex-mcp":
        codex_exe = shutil.which("codex") or "codex"
        cmd = codex_exe
        cmd_args = ["mcp-server"]
    else:
        rpath = resolve_source_repo(server_repo, h)
        if not rpath or not (rpath / "server.py").is_file():
            raise FileNotFoundError(f"MCP repository {server_repo!r} with server.py not found.")
        venv_py = rpath / ".venv" / "bin" / "python"
        cmd = str(venv_py) if venv_py.is_file() else sys.executable
        cmd_args = [str(rpath / "server.py")]

    plan: list[dict[str, Any]] = []
    configs_to_update: list[tuple[str, pathlib.Path, dict[str, Any]]] = []

    for assistant in assistants:
        cfg_path = assistant_mcp_config_path(assistant, scope, ws, h)
        data: dict[str, Any] = {}
        if cfg_path.exists():
            # Never fall back to {} on a parse error: that would overwrite the whole file
            # (e.g. ~/.claude.json holds all of Claude Code's state) with a single key.
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"Refusing to modify {cfg_path}: it is not valid JSON ({exc}). Fix or register the server manually.") from exc
            if not isinstance(data, dict):
                raise ValueError(f"Refusing to modify {cfg_path}: top-level JSON value is not an object.")
            mcps = read_registered_mcps(cfg_path, assistant)
            cur_state = "registered" if server_repo in mcps else "unregistered"
        else:
            cur_state = "missing"

        plan.append({
            "action": "edit",
            "path": str(cfg_path),
            "reason": f"Register MCP server '{server_repo}' in {assistant} ({scope})",
            "current_state": cur_state,
        })
        configs_to_update.append((assistant, cfg_path, data))

    plan_hash = compute_plan_hash(plan)
    if expect_plan_hash is not None and expect_plan_hash != plan_hash:
        return {
            "ok": False,
            "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
            "plan": plan,
            "plan_hash": plan_hash,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "server": server_repo,
            "command": cmd,
            "args": cmd_args,
            "plan": plan,
            "plan_hash": plan_hash,
        }

    if server_repo != "codex-mcp" and provision_venv:
        rpath = resolve_source_repo(server_repo, h)
        assert rpath is not None
        venv_py = rpath / ".venv" / "bin" / "python"
        if not venv_py.is_file():
            subprocess.run([sys.executable, "-m", "venv", str(rpath / ".venv")], check=True)
            subprocess.run([str(venv_py), "-m", "pip", "install", "-q", "-e", str(rpath)], check=True)
            cmd = str(venv_py)

    updated_configs: list[str] = []
    for assistant, cfg_path, data in configs_to_update:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        if assistant == "kilo":
            mcp_block = data.setdefault("mcp", {})
            mcp_block[server_repo] = {
                "type": "local",
                "command": [cmd, *cmd_args],
                "enabled": True,
            }
        else:
            mcp_block = data.setdefault("mcpServers", {})
            mcp_block[server_repo] = {
                "type": "stdio",
                "command": cmd,
                "args": cmd_args,
            }

        _atomic_write_with_backup(cfg_path, json.dumps(data, indent=2) + "\n")
        updated_configs.append(str(cfg_path))

    return {
        "ok": True,
        "server": server_repo,
        "command": cmd,
        "args": cmd_args,
        "updated_configs": updated_configs,
        "plan": plan,
        "plan_hash": plan_hash,
    }


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    report = inspect_environment(ws, args.home)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("=== CLI Binaries ===")
    for tool, info in report["clis"].items():
        status = f"OK ({info['version']}) at {info['path']}" if info["installed"] else "MISSING"
        print(f"  {tool:<10}: {status}")

    print("\n=== Source Repositories ===")
    for rname, rinfo in report["source_repos"].items():
        status = f"OK ({rinfo['path']}, venv={rinfo['has_venv']})" if rinfo["available"] else "NOT CLONED"
        print(f"  {rname:<18}: {status}")

    print("\n=== Environments (Skills & Registered MCPs) ===")
    for assistant, scopes in report["environments"].items():
        for scope, sinfo in scopes.items():
            print(f"\n[{assistant} — {scope}] ({sinfo['installed_count']} skill(s), MCPs: {', '.join(sinfo['registered_mcps']) or 'none'})")
            for sname, sdata in sinfo["skills"].items():
                print(f"  - {sname:<30} [{sdata['state']}] (source: {sdata['source_repo'] or 'local'})")
            for c in sinfo["conflicts"]:
                print(f"  ! CONFLICT: {c}")
    return 0


def cmd_fetch_repos(args: argparse.Namespace) -> int:
    res = clone_or_update_repos(args.repos, args.home)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        for r, info in res.items():
            print(f"[{ 'ok' if info['ok'] else 'FAIL' }] {r}: {info['action']} ({info['path']})")
    return 0 if all(v["ok"] for v in res.values()) else 1


def cmd_install_skills(args: argparse.Namespace) -> int:
    assistants = list(ASSISTANTS) if "all" in args.assistants else args.assistants
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    try:
        res = install_skills(
            assistants=assistants,
            scope=args.scope,
            repo_name=args.repo,
            plugins=args.plugins,
            link=args.link,
            workspace=ws,
            home=args.home,
            dry_run=args.dry_run,
            expect_plan_hash=args.expect_plan_hash,
            overwrite=args.overwrite,
        )
    except FileNotFoundError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"[error] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if not res.get("ok"):
            print(f"[error] {res.get('error', 'Execution refused')}", file=sys.stderr)
        elif res.get("dry_run"):
            print(f"[dry-run] Plan ({len(res['plan'])} action(s), hash: {res['plan_hash']}):")
            for item in res["plan"]:
                print(f"  {item['action'].upper():<8} {item['path']} ({item['reason']})")
        else:
            print(f"[ok] Installed {res['installed_count']} skill(s) from {args.repo} into {', '.join(assistants)} ({args.scope}). Plan hash: {res['plan_hash']}.")
    return 0 if res.get("ok") else 1


def cmd_register_mcp(args: argparse.Namespace) -> int:
    assistants = list(ASSISTANTS) if "all" in args.assistants else args.assistants
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    try:
        res = register_mcp_server(
            server_repo=args.server,
            assistants=assistants,
            scope=args.scope,
            provision_venv=args.provision_venv,
            workspace=ws,
            home=args.home,
            dry_run=args.dry_run,
            expect_plan_hash=args.expect_plan_hash,
        )
    except (ValueError, FileNotFoundError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"[error] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if not res.get("ok"):
            print(f"[error] {res.get('error', 'Execution refused')}", file=sys.stderr)
        elif res.get("dry_run"):
            print(f"[dry-run] Plan ({len(res['plan'])} action(s), hash: {res['plan_hash']}):")
            for item in res["plan"]:
                print(f"  {item['action'].upper():<8} {item['path']} ({item['reason']})")
        else:
            print(f"[ok] Registered MCP server '{args.server}' in: {', '.join(res['updated_configs'])}. Plan hash: {res['plan_hash']}.")
    return 0 if res.get("ok") else 1


def cmd_remove_skill(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    res = remove_skill(
        assistant=args.assistant,
        scope=args.scope,
        skill_name=args.skill,
        workspace=ws,
        home=args.home,
        dry_run=args.dry_run,
        expect_plan_hash=args.expect_plan_hash,
    )
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if not res.get("ok"):
            print(f"[error] {res.get('error') or res.get('message')}", file=sys.stderr)
        elif res.get("dry_run"):
            print(f"[dry-run] Plan ({len(res['plan'])} action(s), hash: {res['plan_hash']}):")
            for item in res["plan"]:
                print(f"  {item['action'].upper():<8} {item['path']} ({item['reason']})")
        else:
            print(f"[ok] Removed skill '{args.skill}' from {args.assistant} ({args.scope}). Plan hash: {res['plan_hash']}.")
    return 0 if res.get("ok") else 1


def cmd_resolve_conflicts(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    res = resolve_conflicts(
        workspace=ws,
        home=args.home,
        dry_run=args.dry_run,
        expect_plan_hash=args.expect_plan_hash,
    )
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if not res.get("ok"):
            print(f"[error] {res.get('error', 'Execution refused')}", file=sys.stderr)
        elif res.get("dry_run"):
            print(f"[dry-run] Plan ({len(res['plan'])} action(s), hash: {res['plan_hash']}):")
            for item in res["plan"]:
                print(f"  {item['action'].upper():<8} {item['path']} ({item['reason']})")
        else:
            if res["resolved_count"] > 0:
                for r in res["resolved"]:
                    print(f"[ok] Resolved conflict in {r['assistant']} ({r['scope']}): removed '{r['removed']}', kept '{r['kept']}'.")
            else:
                print("[ok] No trigger conflicts found.")
    return 0 if res.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", type=pathlib.Path, default=None, help="Override home directory (for testing/sandboxing)")
    ap.add_argument("--json", dest="parent_json", action="store_true", default=False, help="Output structured JSON on stdout")
    ap.add_argument("--dry-run", dest="parent_dry_run", action="store_true", default=False, help="Compute and output execution plan without modifying disk")
    ap.add_argument("--expect-plan-hash", dest="parent_expect_plan_hash", default=None, help="Refuse execution if recomputed plan hash does not match")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser("status", help="Verify status & drift of CLIs, skills, and MCP servers across Kilo, Claude, and Codex")
    p_st.add_argument("--workspace", default=None, help="Optional project workspace to inspect project-scope installs")
    p_st.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_st.set_defaults(func=cmd_status)

    p_fr = sub.add_parser("fetch-repos", help="Clone or update ai-orchestration / kilo-mcp in ~/.ai-orchestration/repos/")
    p_fr.add_argument("--repos", nargs="+", default=["ai-orchestration", "kilo-mcp"])
    p_fr.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_fr.set_defaults(func=cmd_fetch_repos)

    p_is = sub.add_parser("install-skills", help="Install orchestration skills into Kilo, Claude, and/or Codex")
    p_is.add_argument("--assistants", nargs="+", choices=[*ASSISTANTS, "all"], default=["all"])
    p_is.add_argument("--scope", choices=SCOPES, default="global")
    p_is.add_argument("--repo", choices=("ai-orchestration", "kilo-mcp", "claude-mcp"), default="ai-orchestration")
    p_is.add_argument("--plugins", nargs="+", default=None, help="Plugins to install (default: architect-side executor-side shared)")
    p_is.add_argument("--link", action="store_true", help="Symlink skill folders instead of copying")
    p_is.add_argument("--workspace", default=None)
    p_is.add_argument("--dry-run", action="store_true", default=False, help="Compute and output execution plan without modifying disk")
    p_is.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_is.add_argument("--overwrite", nargs="*", default=None, help="Skill names to overwrite even if unmanaged, modified-or-outdated, or foreign")
    p_is.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_is.set_defaults(func=cmd_install_skills)

    p_rm = sub.add_parser("register-mcp", help="Provision and register kilo-mcp, claude-mcp, or codex-mcp across assistants")
    p_rm.add_argument("server", choices=("kilo-mcp", "claude-mcp", "codex-mcp"))
    p_rm.add_argument("--assistants", nargs="+", choices=[*ASSISTANTS, "all"], default=["claude", "codex"])
    p_rm.add_argument("--scope", choices=SCOPES, default="global")
    p_rm.add_argument("--provision-venv", action="store_true", help="Create .venv and pip install -e if missing")
    p_rm.add_argument("--workspace", default=None)
    p_rm.add_argument("--dry-run", action="store_true", default=False, help="Compute and output execution plan without modifying disk")
    p_rm.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_rm.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_rm.set_defaults(func=cmd_register_mcp)

    p_rs = sub.add_parser("remove-skill", help="Remove an installed skill from an assistant environment")
    p_rs.add_argument("skill", help="Name of the skill directory to remove")
    p_rs.add_argument("--assistant", choices=ASSISTANTS, required=True)
    p_rs.add_argument("--scope", choices=SCOPES, default="global")
    p_rs.add_argument("--workspace", default=None)
    p_rs.add_argument("--dry-run", action="store_true", default=False, help="Compute and output execution plan without modifying disk")
    p_rs.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_rs.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_rs.set_defaults(func=cmd_remove_skill)

    p_rc = sub.add_parser("resolve-conflicts", help="Auto-resolve trigger conflicts across Kilo, Claude, and Codex")
    p_rc.add_argument("--workspace", default=None)
    p_rc.add_argument("--dry-run", action="store_true", default=False, help="Compute and output execution plan without modifying disk")
    p_rc.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_rc.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_rc.set_defaults(func=cmd_resolve_conflicts)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    args.json = bool(getattr(args, "parent_json", False) or getattr(args, "sub_json", False))
    args.dry_run = bool(getattr(args, "parent_dry_run", False) or getattr(args, "dry_run", False))
    if not getattr(args, "expect_plan_hash", None) and getattr(args, "parent_expect_plan_hash", None):
        args.expect_plan_hash = args.parent_expect_plan_hash
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
