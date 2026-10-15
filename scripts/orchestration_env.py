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
import hashlib
import json
import os
import pathlib
import shutil
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
    cached = get_repos_cache_dir(home) / repo_name
    if cached.is_dir():
        return cached
    return None


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

def discover_available_skills(home: pathlib.Path | None = None) -> dict[str, dict[str, Any]]:
    """Return map of skill_name -> {repo, plugin, path, hash} across ai-orchestration and kilo-mcp."""
    catalog: dict[str, dict[str, Any]] = {}
    for repo_name in ("ai-orchestration", "kilo-mcp", "claude-mcp"):
        rpath = resolve_source_repo(repo_name, home)
        if not rpath or not (rpath / "plugins").is_dir():
            continue
        for skill_md in sorted((rpath / "plugins").glob("*/skills/*/SKILL.md")):
            sdir = skill_md.parent
            pdir = sdir.parent.parent
            sname = sdir.name
            catalog[sname] = {
                "name": sname,
                "repo": repo_name,
                "plugin": pdir.name,
                "path": str(sdir),
                "hash": hash_directory(sdir),
            }
    return catalog


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
                    if not (child.is_dir() or child.is_symlink()):
                        continue
                    skill_md = child / "SKILL.md"
                    if not skill_md.is_file():
                        continue
                    sname = child.name
                    inst_hash = hash_directory(child)
                    src = catalog.get(sname)
                    if sname in OBSOLETE_SKILL_RENAMES:
                        state = f"obsolete-renamed->{OBSOLETE_SKILL_RENAMES[sname]}"
                    elif src is None:
                        state = "unmanaged"
                    elif inst_hash == src["hash"]:
                        state = "up-to-date"
                    else:
                        state = "modified-or-outdated"
                    installed_skills[sname] = {
                        "state": state,
                        "is_symlink": child.is_symlink(),
                        "installed_hash": inst_hash,
                        "source_repo": src["repo"] if src else None,
                        "source_hash": src["hash"] if src else None,
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
) -> dict[str, Any]:
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else pathlib.Path.cwd()
    rpath = resolve_source_repo(repo_name, h)
    if not rpath or not (rpath / "plugins").is_dir():
        raise FileNotFoundError(f"Source repository {repo_name!r} not found locally. Run `fetch-repos` first.")

    selected_plugins = plugins or ["architect-side", "executor-side", "shared"]
    installed: list[dict[str, str]] = []
    removed_obsolete: list[str] = []

    for assistant in assistants:
        dest_skills_dir = assistant_skills_dir(assistant, scope, ws, h)
        dest_skills_dir.mkdir(parents=True, exist_ok=True)

        # Clean up obsolete pre-rename skill directories in this target
        for old_name in OBSOLETE_SKILL_RENAMES:
            old_dir = dest_skills_dir / old_name
            if old_dir.is_symlink() or old_dir.is_file():
                old_dir.unlink()
                removed_obsolete.append(str(old_dir))
            elif old_dir.is_dir():
                shutil.rmtree(old_dir)
                removed_obsolete.append(str(old_dir))

        # Clean up obsolete pre-rename agent files and install any plugin agents
        dest_agents_dir = dest_skills_dir.parent / "agents"
        if dest_agents_dir.is_dir():
            for old_agent in OBSOLETE_AGENT_RENAMES:
                old_a_path = dest_agents_dir / old_agent
                if old_a_path.exists() or old_a_path.is_symlink():
                    old_a_path.unlink()
                    removed_obsolete.append(str(old_a_path))

        for p_name in selected_plugins:
            src_agents_root = rpath / "plugins" / p_name / "agents"
            if src_agents_root.is_dir() and assistant in ("claude", "kilo"):
                dest_agents_dir.mkdir(parents=True, exist_ok=True)
                for agent_md in sorted(src_agents_root.glob("*.md")):
                    target_agent = dest_agents_dir / agent_md.name
                    if target_agent.is_symlink() or target_agent.exists():
                        target_agent.unlink()
                    if link:
                        target_agent.symlink_to(agent_md)
                    else:
                        shutil.copy2(agent_md, target_agent)

            src_skills_root = rpath / "plugins" / p_name / "skills"
            if not src_skills_root.is_dir():
                continue
            for skill_md in sorted(src_skills_root.glob("*/SKILL.md")):
                src_dir = skill_md.parent
                sname = src_dir.name
                target_dir = dest_skills_dir / sname
                if target_dir.is_symlink() or target_dir.is_file():
                    target_dir.unlink()
                elif target_dir.is_dir():
                    shutil.rmtree(target_dir)

                if link:
                    target_dir.symlink_to(src_dir)
                else:
                    shutil.copytree(
                        src_dir,
                        target_dir,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
                    )
                installed.append(
                    {
                        "assistant": assistant,
                        "scope": scope,
                        "skill": sname,
                        "plugin": p_name,
                        "repo": repo_name,
                        "target": str(target_dir),
                        "mode": "symlink" if link else "copy",
                    }
                )
    return {
        "ok": True,
        "installed_count": len(installed),
        "installed": installed,
        "removed_obsolete": removed_obsolete,
    }


def register_mcp_server(
    server_repo: str,
    assistants: list[str],
    scope: str = "global",
    provision_venv: bool = False,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
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
        if provision_venv and not venv_py.is_file():
            subprocess.run([sys.executable, "-m", "venv", str(rpath / ".venv")], check=True)
            subprocess.run([str(venv_py), "-m", "pip", "install", "-q", "-e", str(rpath)], check=True)
        cmd = str(venv_py) if venv_py.is_file() else sys.executable
        cmd_args = [str(rpath / "server.py")]

    updated_configs: list[str] = []
    for assistant in assistants:
        cfg_path = assistant_mcp_config_path(assistant, scope, ws, h)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

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

        cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        updated_configs.append(str(cfg_path))

    return {
        "ok": True,
        "server": server_repo,
        "command": cmd,
        "args": cmd_args,
        "updated_configs": updated_configs,
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
    res = install_skills(
        assistants=assistants,
        scope=args.scope,
        repo_name=args.repo,
        plugins=args.plugins,
        link=args.link,
        workspace=ws,
        home=args.home,
    )
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"[ok] Installed {res['installed_count']} skill(s) from {args.repo} into {', '.join(assistants)} ({args.scope}).")
    return 0


def cmd_register_mcp(args: argparse.Namespace) -> int:
    assistants = list(ASSISTANTS) if "all" in args.assistants else args.assistants
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    res = register_mcp_server(
        server_repo=args.server,
        assistants=assistants,
        scope=args.scope,
        provision_venv=args.provision_venv,
        workspace=ws,
        home=args.home,
    )
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"[ok] Registered MCP server '{args.server}' in: {', '.join(res['updated_configs'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", type=pathlib.Path, default=None, help="Override home directory (for testing/sandboxing)")
    ap.add_argument("--json", action="store_true", help="Output structured JSON on stdout")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser("status", help="Verify status & drift of CLIs, skills, and MCP servers across Kilo, Claude, and Codex")
    p_st.add_argument("--workspace", default=None, help="Optional project workspace to inspect project-scope installs")
    p_st.add_argument("--json", action="store_true", help="Output structured JSON on stdout")
    p_st.set_defaults(func=cmd_status)

    p_fr = sub.add_parser("fetch-repos", help="Clone or update ai-orchestration / kilo-mcp in ~/.ai-orchestration/repos/")
    p_fr.add_argument("--repos", nargs="+", default=["ai-orchestration", "kilo-mcp"])
    p_fr.add_argument("--json", action="store_true", help="Output structured JSON on stdout")
    p_fr.set_defaults(func=cmd_fetch_repos)

    p_is = sub.add_parser("install-skills", help="Install orchestration skills into Kilo, Claude, and/or Codex")
    p_is.add_argument("--assistants", nargs="+", choices=[*ASSISTANTS, "all"], default=["all"])
    p_is.add_argument("--scope", choices=SCOPES, default="global")
    p_is.add_argument("--repo", choices=("ai-orchestration", "kilo-mcp", "claude-mcp"), default="ai-orchestration")
    p_is.add_argument("--plugins", nargs="+", default=None, help="Plugins to install (default: architect-side executor-side shared)")
    p_is.add_argument("--link", action="store_true", help="Symlink skill folders instead of copying")
    p_is.add_argument("--workspace", default=None)
    p_is.add_argument("--json", action="store_true", help="Output structured JSON on stdout")
    p_is.set_defaults(func=cmd_install_skills)

    p_rm = sub.add_parser("register-mcp", help="Provision and register kilo-mcp, claude-mcp, or codex-mcp across assistants")
    p_rm.add_argument("server", choices=("kilo-mcp", "claude-mcp", "codex-mcp"))
    p_rm.add_argument("--assistants", nargs="+", choices=[*ASSISTANTS, "all"], default=["claude", "codex"])
    p_rm.add_argument("--scope", choices=SCOPES, default="global")
    p_rm.add_argument("--provision-venv", action="store_true", help="Create .venv and pip install -e if missing")
    p_rm.add_argument("--workspace", default=None)
    p_rm.add_argument("--json", action="store_true", help="Output structured JSON on stdout")
    p_rm.set_defaults(func=cmd_register_mcp)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
