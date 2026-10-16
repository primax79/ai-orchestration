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
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore
from typing import Any, Callable

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
    """Deterministic SHA-256 over all files in a skill directory (ignoring index.json, .ai-orch-source.json, and hidden files)."""
    h = hashlib.sha256()
    if not dir_path.is_dir():
        return ""
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for fname in sorted(files):
            if fname.startswith(".") or fname.endswith(".pyc") or fname in ("index.json", ".ai-orch-source.json"):
                continue
            fpath = pathlib.Path(root) / fname
            rel = fpath.relative_to(dir_path).as_posix()
            h.update(rel.encode("utf-8") + b"\0")
            h.update(fpath.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def compute_target_hash(target_path: pathlib.Path) -> str | None:
    """Return content hash for a file (sha256) or directory (hash_directory).
    For symlinks: hash of target if resolvable, or hash of symlink dest if broken.
    Return None if target does not exist.
    """
    if not (target_path.exists() or target_path.is_symlink()):
        return None
    try:
        if target_path.is_symlink():
            resolved = target_path.resolve()
            if resolved.is_dir():
                return hash_directory(resolved)
            elif resolved.is_file():
                return hashlib.sha256(resolved.read_bytes()).hexdigest()
            else:
                return hashlib.sha256(os.readlink(target_path).encode("utf-8")).hexdigest()
        elif target_path.is_dir():
            return hash_directory(target_path)
        elif target_path.is_file():
            return hashlib.sha256(target_path.read_bytes()).hexdigest()
    except Exception:
        return None
    return None


def get_home_dir() -> pathlib.Path:
    env_home = os.environ.get("AI_ORCH_HOME")
    if env_home:
        return pathlib.Path(env_home).expanduser().resolve()
    return pathlib.Path.home()


def get_env_lock_path(home: pathlib.Path | None = None) -> pathlib.Path:
    h = home or get_home_dir()
    return h / ".config" / "ai-orchestration" / "env.lock"


@contextlib.contextmanager
def env_lock(home: pathlib.Path | None = None):
    """Exclusive flock on <home>/.config/ai-orchestration/env.lock."""
    lock_file = get_env_lock_path(home)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def get_repos_cache_dir(home: pathlib.Path | None = None) -> pathlib.Path:
    h = home or get_home_dir()
    return h / ".ai-orchestration" / "repos"


def resolve_source_repo(repo_name: str, home: pathlib.Path | None = None) -> pathlib.Path | None:
    """Find `ai-orchestration`, `kilo-mcp`, or `claude-mcp` locally (sibling checkout) or in ~/.ai-orchestration/repos/."""
    if home is not None:
        cached = get_repos_cache_dir(home) / repo_name
        if cached.is_dir():
            return cached

    if repo_name == "ai-orchestration" and (REPO_ROOT / "plugins").is_dir():
        return REPO_ROOT
    roots_to_check = [REPO_ROOT]
    # If in a git worktree, also check relative to the main repository
    git_file = REPO_ROOT / ".git"
    if git_file.is_file():
        try:
            content = git_file.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                gdir = pathlib.Path(content.split(":", 1)[1].strip())
                if ".git" in gdir.parts:
                    idx = gdir.parts.index(".git")
                    roots_to_check.append(pathlib.Path(*gdir.parts[:idx]))
        except Exception:
            pass

    for root in roots_to_check:
        sibling = root.parent / repo_name
        if sibling.is_dir() and ((sibling / "plugins").is_dir() or (sibling / "server.py").is_file()):
            return sibling
        for parent in list(root.parents)[:4]:
            cand = parent / repo_name
            if cand.is_dir() and ((cand / "plugins").is_dir() or (cand / "server.py").is_file()):
                return cand
    cached = get_repos_cache_dir(home) / repo_name
    if cached.is_dir():
        return cached
    return None


def trash_path(
    path: pathlib.Path,
    assistant: str | None = None,
    scope: str = "global",
    kind: str | None = None,
    reason: str = "",
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    timestamp: str | None = None,
) -> pathlib.Path:
    """Move a file, directory, or symlink into
    <home>/.config/ai-orchestration/trash/<assistant>/<scope-segment>/<UTC ts>/<kind>/<name>
    and write manifest.json in the <ts> dir.
    """
    if not (path.exists() or path.is_symlink()):
        return path
    h = home or get_home_dir()
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if not assistant:
        if ".kilo" in path.parts:
            assistant = "kilo"
        elif ".claude" in path.parts:
            assistant = "claude"
        elif ".codex" in path.parts:
            assistant = "codex"
        else:
            assistant = "general"

    if not kind:
        if "agents" in path.parts or path.suffix == ".md":
            kind = "agents"
        else:
            kind = "skills"

    if scope == "global" or not workspace:
        scope_segment = "global"
    else:
        ws_abs = str(workspace.resolve())
        ws_hash = hashlib.sha256(ws_abs.encode("utf-8")).hexdigest()[:8]
        scope_segment = f"project-{workspace.resolve().name}-{ws_hash}"

    ts_dir = h / ".config" / "ai-orchestration" / "trash" / assistant / scope_segment / ts
    kind_dir = ts_dir / kind
    kind_dir.mkdir(parents=True, exist_ok=True)

    dest = kind_dir / path.name
    counter = 1
    while dest.exists() or dest.is_symlink():
        dest = kind_dir / f"{path.name}_{counter}"
        counter += 1

    orig_str = str(path)
    shutil.move(str(path), str(dest))

    manifest_file = ts_dir / "manifest.json"
    manifest: list[dict[str, str]] = []
    if manifest_file.is_file():
        try:
            loaded = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                manifest = loaded
        except Exception:
            manifest = []

    manifest.append({
        "original_path": orig_str,
        "trashed_path": str(dest),
        "reason": reason,
    })
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
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
        return (h / ".codex" / "config.toml") if scope == "global" else (ws / ".codex" / "config.toml")
    raise ValueError(f"Unknown assistant: {assistant}")


def assistant_agents_dir(
    assistant: str,
    scope: str,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
) -> pathlib.Path:
    h = home or get_home_dir()
    ws = workspace or pathlib.Path.cwd()
    if assistant == "kilo":
        return (h / ".config" / "kilo" / "agents") if scope == "global" else (ws / ".kilo" / "agents")
    elif assistant == "claude":
        return (h / ".claude" / "agents") if scope == "global" else (ws / ".claude" / "agents")
    elif assistant == "codex":
        return (h / ".codex" / "agents") if scope == "global" else (ws / ".codex" / "agents")
    raise ValueError(f"Unknown assistant: {assistant}")


def read_agent_receipts(agents_dir: pathlib.Path) -> dict[str, dict[str, Any]]:
    rfile = agents_dir / ".ai-orch-receipts.json"
    if not rfile.is_file():
        return {}
    try:
        data = json.loads(rfile.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def write_agent_receipt(agents_dir: pathlib.Path, filename: str, receipt: dict[str, Any]) -> None:
    agents_dir.mkdir(parents=True, exist_ok=True)
    rfile = agents_dir / ".ai-orch-receipts.json"
    data = read_agent_receipts(agents_dir)
    data[filename] = receipt
    rfile.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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


def discover_available_agents(home: pathlib.Path | None = None) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Return map of (repo, plugin, agent_filename) -> {name, repo, plugin, path, hash} across repos."""
    catalog: dict[tuple[str, str, str], dict[str, Any]] = {}
    for repo_name in ("ai-orchestration", "kilo-mcp", "claude-mcp"):
        rpath = resolve_source_repo(repo_name, home)
        if not rpath or not (rpath / "plugins").is_dir():
            continue
        for agent_md in sorted((rpath / "plugins").glob("*/agents/*.md")):
            pdir = agent_md.parent.parent
            aname = agent_md.name
            try:
                ahash = hashlib.sha256(agent_md.read_bytes()).hexdigest()
            except Exception:
                ahash = ""
            catalog[(repo_name, pdir.name, aname)] = {
                "name": aname,
                "repo": repo_name,
                "plugin": pdir.name,
                "path": str(agent_md),
                "hash": ahash,
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

    # Check up-to-date by direct symlink to catalog source
    if child.is_symlink():
        try:
            resolved = child.resolve()
            for entry in matching_entries:
                if resolved == pathlib.Path(entry["path"]).resolve():
                    return ("up-to-date", entry["repo"], entry["hash"])
        except Exception:
            pass

    # Check receipt file .ai-orch-source.json
    marker = child / ".ai-orch-source.json"
    if marker.is_file():
        try:
            mdata = json.loads(marker.read_text(encoding="utf-8"))
            mrepo = mdata.get("repo")
            mhash = mdata.get("source_hash") or mdata.get("hash")
            mplugin = mdata.get("plugin")
            cat_entry = catalog.get((mrepo, mplugin, sname)) if mrepo and mplugin else None
            if not cat_entry and matching_entries:
                cat_entry = matching_entries[0]
            cat_hash = cat_entry["hash"] if cat_entry else None

            if inst_hash and inst_hash == mhash and (not cat_hash or inst_hash == cat_hash):
                return ("up-to-date", mrepo, cat_hash or mhash)
            else:
                return ("modified-or-outdated", mrepo, cat_hash or mhash)
        except Exception:
            return ("modified-or-outdated", None, None)

    # No receipt: check if hash matches any catalog entry (legacy copies)
    for entry in matching_entries:
        if inst_hash and inst_hash == entry["hash"]:
            return ("up-to-date", entry["repo"], entry["hash"])

    # Link mode into known source repo
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

    # Neither marker nor symlink to known repo and no catalog hash match
    return ("foreign", None, None)


def detect_agent_state(
    child: pathlib.Path,
    catalog_agents: dict[tuple[str, str, str], dict[str, Any]],
    receipts: dict[str, dict[str, Any]],
    home: pathlib.Path | None = None,
) -> tuple[str, str | None, str | None]:
    """Determine state, source_repo, and source_hash for an installed agent file/symlink."""
    aname = child.name
    if aname in OBSOLETE_AGENT_RENAMES:
        return (f"obsolete-renamed->{OBSOLETE_AGENT_RENAMES[aname]}", None, None)

    matching_entries = [entry for entry in catalog_agents.values() if entry["name"] == aname]
    if not matching_entries:
        return ("unmanaged", None, None)

    inst_hash = ""
    if child.is_file() or child.is_symlink():
        try:
            resolved = child.resolve()
            if resolved.is_file():
                inst_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
        except Exception:
            pass

    # Check up-to-date by direct symlink to catalog source
    if child.is_symlink():
        try:
            resolved = child.resolve()
            for entry in matching_entries:
                if resolved == pathlib.Path(entry["path"]).resolve():
                    return ("up-to-date", entry["repo"], entry["hash"])
        except Exception:
            pass

    receipt = receipts.get(aname)
    if receipt:
        r_repo = receipt.get("repo")
        r_hash = receipt.get("source_hash") or receipt.get("hash")
        r_plugin = receipt.get("plugin")
        cat_entry = catalog_agents.get((r_repo, r_plugin, aname)) if r_repo and r_plugin else None
        if not cat_entry and matching_entries:
            cat_entry = matching_entries[0]
        cat_hash = cat_entry["hash"] if cat_entry else None

        if inst_hash and inst_hash == r_hash and (not cat_hash or inst_hash == cat_hash):
            return ("up-to-date", r_repo, cat_hash or r_hash)
        else:
            return ("modified-or-outdated", r_repo, cat_hash or r_hash)

    # No receipt: check if hash matches any catalog entry (legacy copies)
    for entry in matching_entries:
        if inst_hash and inst_hash == entry["hash"]:
            return ("up-to-date", entry["repo"], entry["hash"])

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


# ---------------------------------------------------------------------------
# JSONC Stripper & Process / TOML Helpers
# ---------------------------------------------------------------------------

def strip_jsonc_comments(text: str) -> str:
    """Strip // line comments and /* */ block comments outside string literals."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False

    while i < n:
        c = text[i]

        if in_string:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue

        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue

        if c == "/" and i + 1 < n:
            next_c = text[i + 1]
            if next_c == "/":
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            elif next_c == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue

        out.append(c)
        i += 1

    return "".join(out)


def strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before ']' or '}' outside string literals."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False

    while i < n:
        c = text[i]

        if in_string:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue

        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue

        if c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "]}":
                i += 1
                continue

        out.append(c)
        i += 1

    return "".join(out)


def parse_jsonc(text: str) -> Any:
    """Parse JSONC text by stripping comments and trailing commas."""
    cleaned = strip_trailing_commas(strip_jsonc_comments(text))
    return json.loads(cleaned)


_claude_process_detector: Any = None


def is_claude_running() -> bool:
    """Detect if a claude process is running via pgrep or ps."""
    if callable(_claude_process_detector):
        return bool(_claude_process_detector())
    try:
        res = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, check=False)
        if res.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass
    try:
        res = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, check=False)
        lines = [line.strip().rsplit("/", 1)[-1] for line in res.stdout.splitlines()]
        return "claude" in lines
    except Exception:
        pass
    return False


def format_toml_server_entry(name: str, command: str, args: list[str]) -> str:
    """Format a surgical [mcp_servers.<name>] TOML table block."""
    key = name if re.match(r"^[A-Za-z0-9_-]+$", name) else json.dumps(name)
    lines = [f"[mcp_servers.{key}]"]
    lines.append(f"command = {json.dumps(command)}")
    lines.append(f"args = {json.dumps(args)}")
    return "\n".join(lines) + "\n"


def read_registered_mcps(config_path: pathlib.Path, assistant: str) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        if config_path.suffix == ".toml":
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
            return data.get("mcp_servers", {}) if isinstance(data, dict) else {}
        elif config_path.suffix == ".jsonc":
            data = parse_jsonc(config_path.read_text(encoding="utf-8"))
        else:
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                data = parse_jsonc(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    if assistant == "kilo":
        return data.get("mcp", data.get("mcpServers", {}))
    return data.get("mcpServers", data.get("mcp_servers", {}))


def read_kilo_merged_mcps(
    scope: str,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Read Kilo MCP servers in Kilo's merge precedence order with provenance and overrides."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    servers: dict[str, dict[str, Any]] = {}

    if scope == "global":
        cfg_dir = h / ".config" / "kilo"
        # Precedence order from references/kilocode/kilocode/packages/opencode/src/config/config.ts:366-372
        candidates = [
            cfg_dir / "config.json",
            cfg_dir / "kilo.json",
            cfg_dir / "kilo.jsonc",
            cfg_dir / "opencode.json",
            cfg_dir / "opencode.jsonc",
        ]
    else:
        if ws is None:
            return {}
        candidates = [
            ws / "config.json",
            ws / "kilo.json",
            ws / "kilo.jsonc",
            ws / ".kilo" / "config.json",
            ws / ".kilo" / "kilo.json",
            ws / ".kilo" / "kilo.jsonc",
            ws / "opencode.json",
            ws / "opencode.jsonc",
            ws / ".kilo" / "opencode.json",
            ws / ".kilo" / "opencode.jsonc",
        ]

    for cand in candidates:
        if not cand.is_file():
            continue
        try:
            raw_text = cand.read_text(encoding="utf-8")
            data = parse_jsonc(raw_text)
            if not isinstance(data, dict):
                continue
            file_mcps = data.get("mcp") or data.get("mcpServers") or {}
            if not isinstance(file_mcps, dict):
                continue
            for sname, scfg in file_mcps.items():
                if sname in servers:
                    servers[sname]["overrides"].append(servers[sname]["provenance"])
                    servers[sname]["provenance"] = str(cand)
                    servers[sname]["config"] = scfg
                    servers[sname]["command"] = scfg.get("command") if isinstance(scfg, dict) else None
                    servers[sname]["args"] = scfg.get("args") if isinstance(scfg, dict) else None
                else:
                    servers[sname] = {
                        "name": sname,
                        "scope": scope,
                        "provenance": str(cand),
                        "overrides": [],
                        "config": scfg,
                        "command": scfg.get("command") if isinstance(scfg, dict) else None,
                        "args": scfg.get("args") if isinstance(scfg, dict) else None,
                    }
        except Exception:
            continue

    return servers


def read_claude_mcps(
    scope: str,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Read Claude MCP servers for user, project, or local scope."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    servers: dict[str, dict[str, Any]] = {}

    if scope == "global":
        cfg = h / ".claude.json"
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    raw_mcps = data.get("mcpServers", {})
                    if isinstance(raw_mcps, dict):
                        for name, s_cfg in raw_mcps.items():
                            servers[name] = {
                                "name": name,
                                "scope": "user",
                                "provenance": str(cfg),
                                "config": s_cfg,
                                "command": s_cfg.get("command") if isinstance(s_cfg, dict) else None,
                                "args": s_cfg.get("args") if isinstance(s_cfg, dict) else None,
                            }
            except Exception:
                pass
    elif scope == "project" and ws is not None:
        proj_cfg = ws / ".mcp.json"
        if proj_cfg.is_file():
            try:
                p_data = json.loads(proj_cfg.read_text(encoding="utf-8"))
                if isinstance(p_data, dict):
                    raw_mcps = p_data.get("mcpServers", {})
                    if isinstance(raw_mcps, dict):
                        for name, s_cfg in raw_mcps.items():
                            servers[name] = {
                                "name": name,
                                "scope": "project",
                                "provenance": str(proj_cfg),
                                "config": s_cfg,
                                "command": s_cfg.get("command") if isinstance(s_cfg, dict) else None,
                                "args": s_cfg.get("args") if isinstance(s_cfg, dict) else None,
                            }
            except Exception:
                pass

        user_cfg = h / ".claude.json"
        if user_cfg.is_file():
            try:
                u_data = json.loads(user_cfg.read_text(encoding="utf-8"))
                if isinstance(u_data, dict):
                    projects = u_data.get("projects", {})
                    if isinstance(projects, dict):
                        for p_key, p_val in projects.items():
                            try:
                                if pathlib.Path(p_key).resolve() == ws and isinstance(p_val, dict):
                                    loc_mcps = p_val.get("mcpServers", {})
                                    if isinstance(loc_mcps, dict):
                                        for name, s_cfg in loc_mcps.items():
                                            servers[name] = {
                                                "name": name,
                                                "scope": "local",
                                                "provenance": f"{user_cfg} (projects[{p_key}])",
                                                "config": s_cfg,
                                                "command": s_cfg.get("command") if isinstance(s_cfg, dict) else None,
                                                "args": s_cfg.get("args") if isinstance(s_cfg, dict) else None,
                                            }
                            except Exception:
                                pass
            except Exception:
                pass

    return servers


def read_codex_mcps(
    scope: str,
    home: pathlib.Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Read Codex MCP servers from ~/.codex/config.toml (global only)."""
    h = home or get_home_dir()
    servers: dict[str, dict[str, Any]] = {}
    if scope == "global":
        cfg = h / ".codex" / "config.toml"
        if cfg.is_file():
            try:
                data = tomllib.loads(cfg.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    raw_mcps = data.get("mcp_servers", {})
                    if isinstance(raw_mcps, dict):
                        for name, s_cfg in raw_mcps.items():
                            servers[name] = {
                                "name": name,
                                "scope": "global",
                                "provenance": str(cfg),
                                "config": s_cfg,
                                "command": s_cfg.get("command") if isinstance(s_cfg, dict) else None,
                                "args": s_cfg.get("args") if isinstance(s_cfg, dict) else None,
                            }
            except Exception:
                pass
    return servers


# ---------------------------------------------------------------------------
# Claude Plugin Discovery & Settings
# ---------------------------------------------------------------------------

def load_claude_plugin_settings(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
) -> tuple[dict[str, bool], dict[str, bool]]:
    """Load Claude plugin enablement maps.
    Returns:
        (global_enabled, project_enabled)
    where each is a dict of plugin_id -> bool.
    Project settings (<ws>/.claude/settings.json and <ws>/.claude/settings.local.json)
    override user settings (~/.claude/settings.json).
    Missing entries default to True when evaluated.
    """
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None

    global_enabled: dict[str, bool] = {}
    user_settings_path = h / ".claude" / "settings.json"
    if user_settings_path.is_file():
        try:
            udata = json.loads(user_settings_path.read_text(encoding="utf-8"))
            if isinstance(udata, dict) and isinstance(udata.get("enabledPlugins"), dict):
                for k, v in udata["enabledPlugins"].items():
                    global_enabled[k] = bool(v)
        except Exception:
            pass

    project_enabled = dict(global_enabled)
    if ws is not None:
        for fname in ("settings.json", "settings.local.json"):
            ps_path = ws / ".claude" / fname
            if ps_path.is_file():
                try:
                    pdata = json.loads(ps_path.read_text(encoding="utf-8"))
                    if isinstance(pdata, dict) and isinstance(pdata.get("enabledPlugins"), dict):
                        for k, v in pdata["enabledPlugins"].items():
                            project_enabled[k] = bool(v)
                except Exception:
                    pass

    return global_enabled, project_enabled


def discover_claude_plugin_skills(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
) -> list[dict[str, Any]]:
    """Inspect ~/.claude/plugins/installed_plugins.json and discover installed plugin skills.
    Returns list of dicts with keys:
        plugin_id: str (e.g. 'architect-side@ai-orchestration')
        scope: str ('user', 'project', 'local')
        project_path: str | None
        skill_name: str
        path: str (path to skill directory)
        origin: str ('plugin:<plugin_id>')
    """
    h = home or get_home_dir()
    reg_path = h / ".claude" / "plugins" / "installed_plugins.json"
    if not reg_path.is_file():
        return []

    try:
        data = json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    plugins_map = data.get("plugins", {})
    if not isinstance(plugins_map, dict):
        return []

    results: list[dict[str, Any]] = []

    for plugin_id, installs in sorted(plugins_map.items()):
        if isinstance(installs, dict):
            installs_list = [installs]
        elif isinstance(installs, list):
            installs_list = installs
        else:
            continue

        for install in installs_list:
            if not isinstance(install, dict):
                continue
            iscope = install.get("scope", "user")
            project_path = install.get("projectPath")
            ip_str = install.get("installPath")
            if not ip_str:
                continue
            ip = pathlib.Path(ip_str).expanduser()
            if not ip.is_dir():
                continue

            # Check skills layout: <installPath>/skills/<name>/SKILL.md
            skills_dir = ip / "skills"
            if skills_dir.is_dir():
                for child in sorted(skills_dir.iterdir()):
                    if child.name.startswith(".") or not child.is_dir():
                        continue
                    if (child / "SKILL.md").is_file():
                        results.append({
                            "plugin_id": plugin_id,
                            "scope": iscope,
                            "project_path": project_path,
                            "skill_name": child.name,
                            "path": str(child),
                            "origin": f"plugin:{plugin_id}",
                        })
            elif (ip / "SKILL.md").is_file():
                # Single skill in installPath root
                skill_name = plugin_id.split("@", 1)[0]
                try:
                    content = (ip / "SKILL.md").read_text(encoding="utf-8")
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            for line in parts[1].splitlines():
                                line_s = line.strip()
                                if line_s.startswith("name:"):
                                    parsed = line_s.split(":", 1)[1].strip().strip("\"'")
                                    if parsed:
                                        skill_name = parsed
                                        break
                except Exception:
                    pass
                results.append({
                    "plugin_id": plugin_id,
                    "scope": iscope,
                    "project_path": project_path,
                    "skill_name": skill_name,
                    "path": str(ip),
                    "origin": f"plugin:{plugin_id}",
                })

    return results


def inspect_environment(
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
) -> dict[str, Any]:
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    catalog = discover_available_skills(h)
    catalog_agents = discover_available_agents(h)

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
    global_plugin_enabled, project_plugin_enabled = load_claude_plugin_settings(h, ws)
    claude_plugins = discover_claude_plugin_skills(h, ws)

    for assistant in ASSISTANTS:
        environments[assistant] = {}
        for scope in scopes_to_check:
            sdir = assistant_skills_dir(assistant, scope, ws, h)
            installed_skills: dict[str, Any] = {}
            if sdir.is_dir():
                for child in sorted(sdir.iterdir()):
                    if child.name.startswith("."):
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

            # Build list-shaped skill_entries
            skill_entries: list[dict[str, Any]] = []
            for sname, sdata in installed_skills.items():
                child_path = sdir / sname
                skill_entries.append({
                    "name": sname,
                    "origin": "standalone",
                    "scope": scope,
                    "path": str(child_path),
                    "enabled": True,
                    "state": sdata["state"],
                })

            if assistant == "claude":
                if scope == "global":
                    for ps in claude_plugins:
                        if ps["scope"] == "user":
                            en = global_plugin_enabled.get(ps["plugin_id"], True)
                            skill_entries.append({
                                "name": ps["skill_name"],
                                "origin": ps["origin"],
                                "scope": "user",
                                "path": ps["path"],
                                "enabled": en,
                                "state": "plugin",
                            })
                elif scope == "project" and ws is not None:
                    for ps in claude_plugins:
                        if ps["scope"] == "user":
                            en = project_plugin_enabled.get(ps["plugin_id"], True)
                            skill_entries.append({
                                "name": ps["skill_name"],
                                "origin": ps["origin"],
                                "scope": "user",
                                "path": ps["path"],
                                "enabled": en,
                                "state": "plugin",
                            })
                        elif ps["scope"] in ("project", "local"):
                            p_path = ps.get("project_path")
                            if p_path and pathlib.Path(p_path).resolve() == ws:
                                en = project_plugin_enabled.get(ps["plugin_id"], True)
                                skill_entries.append({
                                    "name": ps["skill_name"],
                                    "origin": ps["origin"],
                                    "scope": ps["scope"],
                                    "path": ps["path"],
                                    "enabled": en,
                                    "state": "plugin",
                                })

            # Inspect agents
            adir = assistant_agents_dir(assistant, scope, ws, h)
            installed_agents: dict[str, Any] = {}
            if adir.is_dir():
                agent_receipts = read_agent_receipts(adir)
                for child in sorted(adir.iterdir()):
                    if child.name.startswith(".") or not child.name.endswith(".md"):
                        continue
                    if not (child.is_file() or child.is_symlink()):
                        continue
                    aname = child.name
                    state, src_repo, src_hash = detect_agent_state(child, catalog_agents, agent_receipts, h)
                    inst_hash = ""
                    try:
                        resolved = child.resolve()
                        if resolved.is_file():
                            inst_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
                    except Exception:
                        pass
                    installed_agents[aname] = {
                        "state": state,
                        "is_symlink": child.is_symlink(),
                        "installed_hash": inst_hash,
                        "source_repo": src_repo,
                        "source_hash": src_hash,
                    }

            # Conflicts computed over the UNION of enabled entries:
            # per assistant+scope view; for Claude project view = standalone global + standalone project + enabled plugins
            if assistant == "claude" and scope == "project":
                global_entries = environments["claude"].get("global", {}).get("skill_entries", [])
                standalone_global = [e for e in global_entries if e["origin"] == "standalone" and e["enabled"]]
                enabled_for_conflicts = [e for e in skill_entries if e["enabled"]] + standalone_global
            else:
                enabled_for_conflicts = [e for e in skill_entries if e["enabled"]]

            seen_conflict_paths: set[str] = set()
            unique_enabled: list[dict[str, Any]] = []
            for e in enabled_for_conflicts:
                ep = e.get("path")
                if ep and ep in seen_conflict_paths:
                    continue
                if ep:
                    seen_conflict_paths.add(ep)
                unique_enabled.append(e)
            enabled_for_conflicts = unique_enabled

            conflicts: list[str] = []
            structured_conflicts_map: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}

            # 1. Trigger conflict: orchestration-workflow + kilo-mcp-orchestrator
            generic_entries = [e for e in enabled_for_conflicts if e["name"] == "orchestration-workflow"]
            bound_entries = [e for e in enabled_for_conflicts if e["name"] == "kilo-mcp-orchestrator"]
            if generic_entries and bound_entries:
                names = ["orchestration-workflow", "kilo-mcp-orchestrator"]
                key = ("trigger-conflict", tuple(sorted(names)))
                combined_entries: list[dict[str, Any]] = []
                seen_entry_paths: set[str] = set()
                for e in generic_entries + bound_entries:
                    ep = e.get("path")
                    if ep and ep in seen_entry_paths:
                        continue
                    if ep:
                        seen_entry_paths.add(ep)
                    combined_entries.append(e)

                structured_conflicts_map[key] = {
                    "kind": "trigger-conflict",
                    "names": names,
                    "entries": combined_entries,
                }
                conflicts.append(
                    "Both generic 'orchestration-workflow' and bound 'kilo-mcp-orchestrator' are installed in the same scope; they compete for the same trigger."
                )

            # 2. Duplicate name conflict across origins
            by_name: dict[str, list[dict[str, Any]]] = {}
            for e in enabled_for_conflicts:
                by_name.setdefault(e["name"], []).append(e)

            for name, entries_for_name in sorted(by_name.items()):
                unique_entries: list[dict[str, Any]] = []
                seen_entry_paths = set()
                for e in entries_for_name:
                    ep = e.get("path")
                    if ep and ep in seen_entry_paths:
                        continue
                    if ep:
                        seen_entry_paths.add(ep)
                    unique_entries.append(e)

                if len(unique_entries) > 1:
                    names = [name]
                    key = ("duplicate-name", tuple(sorted(names)))
                    structured_conflicts_map[key] = {
                        "kind": "duplicate-name",
                        "names": names,
                        "entries": unique_entries,
                    }
                    origins_str = ", ".join(sorted({e["origin"] for e in unique_entries}))
                    conflicts.append(f"Duplicate skill '{name}' found across origins: {origins_str}")

            structured_conflicts = list(structured_conflicts_map.values())

            if assistant == "kilo":
                mcp_servers = read_kilo_merged_mcps(scope, ws, h)
                mcp_cfg_path = assistant_mcp_config_path(assistant, scope, ws, h)
                registered_mcps = sorted(mcp_servers.keys())
            elif assistant == "claude":
                mcp_servers = read_claude_mcps(scope, ws, h)
                mcp_cfg_path = assistant_mcp_config_path(assistant, scope, ws, h)
                registered_mcps = sorted(mcp_servers.keys())
            elif assistant == "codex":
                mcp_servers = read_codex_mcps(scope, h)
                mcp_cfg_path = assistant_mcp_config_path(assistant, scope, ws, h) if scope == "global" else None
                registered_mcps = sorted(mcp_servers.keys())
            else:
                mcp_servers = {}
                mcp_cfg_path = assistant_mcp_config_path(assistant, scope, ws, h)
                registered_mcps = []

            environments[assistant][scope] = {
                "skills_dir": str(sdir),
                "installed_count": len(installed_skills),
                "skills": installed_skills,
                "skill_entries": skill_entries,
                "agents_dir": str(adir),
                "agents": installed_agents,
                "conflicts": conflicts,
                "structured_conflicts": structured_conflicts,
                "mcp_config_path": str(mcp_cfg_path) if mcp_cfg_path else None,
                "registered_mcps": registered_mcps,
                "mcp_servers": mcp_servers,
            }

    stray: list[str] = []
    codex_json = h / ".codex" / "config.json"
    if codex_json.is_file():
        stray.append(str(codex_json))

    return {
        "clis": clis,
        "source_repos": repos_status,
        "available_catalog_count": len(catalog),
        "environments": environments,
        "stray": stray,
    }


# ---------------------------------------------------------------------------
# Installation Actions: Clone/Pull, Install Skills, Register MCP (Macro-Task 2)
# ---------------------------------------------------------------------------

def clone_or_update_repos(
    repos: list[str],
    home: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    h = home or get_home_dir()
    cache_dir = get_repos_cache_dir(h)

    def _build_plan() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        p: list[dict[str, Any]] = []
        ops: list[dict[str, Any]] = []
        for rname in repos:
            existing = resolve_source_repo(rname, h)
            if existing and existing.parent != cache_dir:
                head_sha = None
                try:
                    res = subprocess.run(
                        ["git", "-C", str(existing), "rev-parse", "HEAD"],
                        capture_output=True, text=True, check=False,
                    )
                    if res.returncode == 0:
                        head_sha = res.stdout.strip()
                except Exception:
                    pass
                p_item = {
                    "action": "skip",
                    "path": str(existing),
                    "reason": f"Using existing local checkout of {rname}",
                    "current_state": "local-checkout",
                    "before_sha256": head_sha,
                    "after_sha256": None,
                }
                p.append(p_item)
                ops.append({"type": "local", "repo": rname, "path": existing, "plan_item": p_item})
                continue

            target = cache_dir / rname
            url = REMOTE_REPOS.get(rname)
            if not url:
                p_item = {
                    "action": "skip",
                    "path": str(target),
                    "reason": f"No remote URL configured for {rname}",
                    "current_state": "missing",
                    "before_sha256": None,
                    "after_sha256": None,
                }
                p.append(p_item)
                ops.append({"type": "no_remote", "repo": rname, "path": target, "plan_item": p_item})
                continue

            if (target / ".git").is_dir():
                head_sha = None
                try:
                    res = subprocess.run(
                        ["git", "-C", str(target), "rev-parse", "HEAD"],
                        capture_output=True, text=True, check=False,
                    )
                    if res.returncode == 0:
                        head_sha = res.stdout.strip()
                except Exception:
                    pass
                p_item = {
                    "action": "git-pull",
                    "path": str(target),
                    "reason": f"Update {rname} via git pull --ff-only",
                    "current_state": "cloned",
                    "before_sha256": head_sha,
                    "after_sha256": None,
                }
                p.append(p_item)
                ops.append({"type": "pull", "repo": rname, "path": target, "plan_item": p_item})
            else:
                p_item = {
                    "action": "git-clone",
                    "path": str(target),
                    "reason": f"Clone {rname} from {url}",
                    "current_state": "missing",
                    "before_sha256": None,
                    "after_sha256": None,
                }
                p.append(p_item)
                ops.append({"type": "clone", "repo": rname, "path": target, "url": url, "plan_item": p_item})
        return p, ops

    plan, planned_ops = _build_plan()
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

    with env_lock(h):
        plan, planned_ops = _build_plan()
        plan_hash = compute_plan_hash(plan)
        if expect_plan_hash is not None and expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
                "plan": plan,
                "plan_hash": plan_hash,
            }

        cache_dir.mkdir(parents=True, exist_ok=True)
        results: dict[str, Any] = {}
        for op in planned_ops:
            rname = op["repo"]
            if op["type"] == "local":
                results[rname] = {"action": "using-local-checkout", "path": str(op["path"]), "ok": True}
            elif op["type"] == "no_remote":
                results[rname] = {"action": "skipped-no-remote", "path": None, "ok": False}
            elif op["type"] == "pull":
                res = subprocess.run(["git", "-C", str(op["path"]), "pull", "--ff-only"], capture_output=True, text=True, check=False)
                results[rname] = {"action": "updated", "path": str(op["path"]), "ok": res.returncode == 0}
            elif op["type"] == "clone":
                res = subprocess.run(["git", "clone", op["url"], str(op["path"])], capture_output=True, text=True, check=False)
                results[rname] = {"action": "cloned", "path": str(op["path"]), "ok": res.returncode == 0}

        return {
            "ok": all(v.get("ok", False) for v in results.values()),
            "results": results,
            "plan": plan,
            "plan_hash": plan_hash,
        }


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
    overwrite_set = set(overwrite or [])
    overwrite_all = "all" in overwrite_set

    def _build_plan() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        catalog = discover_available_skills(h)
        catalog_agents = discover_available_agents(h)
        p: list[dict[str, Any]] = []
        ops: list[dict[str, Any]] = []

        for assistant in assistants:
            dest_skills_dir = assistant_skills_dir(assistant, scope, ws, h)
            dest_agents_dir = assistant_agents_dir(assistant, scope, ws, h)

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
                        "before_sha256": compute_target_hash(old_dir),
                        "after_sha256": None,
                    }
                    p.append(p_item)
                    ops.append({"type": "obsolete_skill", "assistant": assistant, "scope": scope, "path": old_dir, "plan_item": p_item})

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
                            "before_sha256": compute_target_hash(old_a_path),
                            "after_sha256": None,
                        }
                        p.append(p_item)
                        ops.append({"type": "obsolete_agent", "assistant": assistant, "scope": scope, "path": old_a_path, "plan_item": p_item})

            # 3. Agent files to install
            for p_name in selected_plugins:
                src_agents_root = rpath / "plugins" / p_name / "agents"
                if src_agents_root.is_dir() and assistant in ("claude", "kilo"):
                    agent_receipts = read_agent_receipts(dest_agents_dir)
                    for agent_md in sorted(src_agents_root.glob("*.md")):
                        aname = agent_md.name
                        target_agent = dest_agents_dir / aname
                        src_hash = hashlib.sha256(agent_md.read_bytes()).hexdigest()
                        is_existing = target_agent.exists() or target_agent.is_symlink()
                        if not is_existing:
                            action = "create"
                            cur_state = "missing"
                            reason = f"Install agent '{aname}' from {repo_name}/{p_name}"
                            before_sha256 = None
                            after_sha256 = src_hash
                        else:
                            cur_state, s_repo, s_hash = detect_agent_state(target_agent, catalog_agents, agent_receipts, h)
                            before_sha256 = compute_target_hash(target_agent)
                            if cur_state in ("unmanaged", "modified-or-outdated", "foreign"):
                                if overwrite_all or aname in overwrite_set:
                                    action = "replace"
                                    reason = f"Replace {cur_state} agent '{aname}' with {repo_name}/{p_name} (--overwrite)"
                                    after_sha256 = src_hash
                                else:
                                    action = "skip"
                                    reason = f"Skip {cur_state} agent '{aname}': not in --overwrite list"
                                    after_sha256 = None
                            elif before_sha256 == compute_target_hash(agent_md):
                                # Identical content: nothing to do (avoids trashing/copying on every install)
                                action = "noop"
                                reason = f"Agent '{aname}' already up to date"
                                after_sha256 = None
                            else:
                                action = "replace"
                                reason = f"Update agent '{aname}' from {repo_name}/{p_name}"
                                after_sha256 = src_hash

                        p_item = {
                            "action": action,
                            "path": str(target_agent),
                            "reason": reason,
                            "current_state": cur_state,
                            "before_sha256": before_sha256,
                            "after_sha256": after_sha256,
                        }
                        p.append(p_item)
                        ops.append({
                            "type": "agent",
                            "action": action,
                            "assistant": assistant,
                            "scope": scope,
                            "agent": aname,
                            "plugin": p_name,
                            "repo": repo_name,
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
                    src_hash = hash_directory(src_dir)
                    is_existing = target_dir.exists() or target_dir.is_symlink()
                    if not is_existing:
                        action = "create"
                        cur_state = "missing"
                        reason = f"Install skill '{sname}' from {repo_name}/{p_name}"
                        before_sha256 = None
                        after_sha256 = src_hash
                    else:
                        cur_state, s_repo, s_hash = detect_skill_state(target_dir, catalog, h)
                        before_sha256 = compute_target_hash(target_dir)
                        if cur_state in ("unmanaged", "modified-or-outdated", "foreign"):
                            if overwrite_all or sname in overwrite_set:
                                action = "replace"
                                reason = f"Replace {cur_state} skill '{sname}' with {repo_name}/{p_name} (--overwrite)"
                                after_sha256 = src_hash
                            else:
                                action = "skip"
                                reason = f"Skip {cur_state} skill '{sname}': not in --overwrite list"
                                after_sha256 = None
                        elif before_sha256 == src_hash and not target_dir.is_symlink() and not link:
                            # Identical copy: nothing to do (avoids trashing/copying on every install)
                            action = "noop"
                            reason = f"Skill '{sname}' already up to date"
                            after_sha256 = None
                        else:
                            action = "replace"
                            reason = f"Update skill '{sname}' from {repo_name}/{p_name}"
                            after_sha256 = src_hash

                    p_item = {
                        "action": action,
                        "path": str(target_dir),
                        "reason": reason,
                        "current_state": cur_state,
                        "before_sha256": before_sha256,
                        "after_sha256": after_sha256,
                    }
                    p.append(p_item)
                    ops.append({
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

        return p, ops

    plan, planned_ops = _build_plan()
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

    with env_lock(h):
        plan, planned_ops = _build_plan()
        plan_hash = compute_plan_hash(plan)
        if expect_plan_hash is not None and expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
                "plan": plan,
                "plan_hash": plan_hash,
            }

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        installed: list[dict[str, str]] = []
        removed_obsolete: list[str] = []

        for op in planned_ops:
            action = op.get("action", "trash")
            if action in ("skip", "noop"):
                continue
            if op["type"] in ("obsolete_skill", "obsolete_agent"):
                kind = "skills" if op["type"] == "obsolete_skill" else "agents"
                trash_path(
                    op["path"],
                    assistant=op["assistant"],
                    scope=op["scope"],
                    kind=kind,
                    reason=op["plan_item"]["reason"],
                    workspace=ws,
                    home=h,
                    timestamp=ts,
                )
                removed_obsolete.append(str(op["path"]))
            elif op["type"] == "agent":
                op["dest_dir"].mkdir(parents=True, exist_ok=True)
                if action == "replace":
                    trash_path(
                        op["target"],
                        assistant=op["assistant"],
                        scope=op["scope"],
                        kind="agents",
                        reason=op["plan_item"]["reason"],
                        workspace=ws,
                        home=h,
                        timestamp=ts,
                    )
                if op["link"]:
                    op["target"].symlink_to(op["src"])
                else:
                    shutil.copy2(op["src"], op["target"])
                receipt_data = {
                    "repo": op["repo"],
                    "plugin": op["plugin"],
                    "name": op["agent"],
                    "source_hash": hashlib.sha256(op["src"].read_bytes()).hexdigest(),
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "symlink" if op["link"] else "copy",
                }
                write_agent_receipt(op["dest_dir"], op["agent"], receipt_data)
            elif op["type"] == "skill":
                op["dest_dir"].mkdir(parents=True, exist_ok=True)
                if action == "replace":
                    trash_path(
                        op["target"],
                        assistant=op["assistant"],
                        scope=op["scope"],
                        kind="skills",
                        reason=op["plan_item"]["reason"],
                        workspace=ws,
                        home=h,
                        timestamp=ts,
                    )
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
                        "source_hash": hash_directory(op["src"]),
                        "installed_at": datetime.now(timezone.utc).isoformat(),
                        "mode": "copy",
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
    skills_dir = assistant_skills_dir(assistant, scope, ws, h)
    dest_dir = skills_dir / skill_name
    # Defence in depth: the target must be a direct child of the skills dir (no traversal, no symlinked parent tricks)
    if dest_dir.parent.resolve() != skills_dir.resolve():
        return {"ok": False, "message": f"Refusing to remove {dest_dir}: not a direct child of {skills_dir}", "plan": [], "plan_hash": compute_plan_hash([])}
    if not (dest_dir.exists() or dest_dir.is_symlink()):
        return {"ok": False, "message": f"Skill '{skill_name}' not found in {dest_dir.parent}", "plan": [], "plan_hash": compute_plan_hash([])}

    def _build_plan() -> list[dict[str, Any]]:
        catalog = discover_available_skills(h)
        cur_state, _, _ = detect_skill_state(dest_dir, catalog, h)
        return [{
            "action": "trash",
            "path": str(dest_dir),
            "reason": f"Remove skill '{skill_name}' from {assistant} ({scope})",
            "current_state": cur_state,
            "before_sha256": compute_target_hash(dest_dir),
            "after_sha256": None,
        }]

    plan = _build_plan()
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

    with env_lock(h):
        plan = _build_plan()
        plan_hash = compute_plan_hash(plan)
        if expect_plan_hash is not None and expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
                "plan": plan,
                "plan_hash": plan_hash,
            }

        trash_path(
            dest_dir,
            assistant=assistant,
            scope=scope,
            kind="skills",
            reason=plan[0]["reason"],
            workspace=ws,
            home=h,
        )
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

    def _build_plan() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        p: list[dict[str, Any]] = []
        c_items: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        catalog = discover_available_skills(h)
        env_report = inspect_environment(ws, h)

        for assistant in ASSISTANTS:
            for scope in scopes_to_check:
                sinfo = env_report["environments"][assistant].get(scope, {})
                for sc in sinfo.get("structured_conflicts", []):
                    kind = sc.get("kind")
                    entries = sc.get("entries", [])
                    if kind == "trigger-conflict":
                        keep_target = policy.get(assistant, "generic" if assistant == "kilo" else "bound")
                        if keep_target == "generic":
                            to_remove_name = "kilo-mcp-orchestrator"
                            to_keep_name = "orchestration-workflow"
                        else:
                            to_remove_name = "orchestration-workflow"
                            to_keep_name = "kilo-mcp-orchestrator"

                        to_remove_entries = [e for e in entries if e.get("name") == to_remove_name]
                        standalone_to_remove = [e for e in to_remove_entries if not e.get("origin", "").startswith("plugin:")]
                        plugin_to_remove = [e for e in to_remove_entries if e.get("origin", "").startswith("plugin:")]

                        if standalone_to_remove:
                            for e in standalone_to_remove:
                                e_path = e.get("path")
                                if not e_path or e_path in seen_paths:
                                    continue
                                seen_paths.add(e_path)
                                target_path = pathlib.Path(e_path)
                                p_item = {
                                    "action": "trash",
                                    "path": str(target_path),
                                    "reason": f"Resolve conflict in {assistant} ({scope}): keep '{to_keep_name}', trash '{to_remove_name}' per policy",
                                    "current_state": "conflict",
                                    "before_sha256": compute_target_hash(target_path),
                                    "after_sha256": None,
                                }
                                p.append(p_item)
                                c_items.append({
                                    "assistant": assistant,
                                    "scope": e.get("scope", scope),
                                    "removed": to_remove_name,
                                    "kept": to_keep_name,
                                    "path": target_path,
                                    "reason": p_item["reason"],
                                })
                        elif plugin_to_remove:
                            for e in plugin_to_remove:
                                e_path = e.get("path")
                                if not e_path or e_path in seen_paths:
                                    continue
                                seen_paths.add(e_path)
                                origin = e.get("origin", "")
                                plugin_id = origin.split("plugin:", 1)[1] if origin.startswith("plugin:") else ""
                                target_path = pathlib.Path(e_path)
                                p_item = {
                                    "action": "advise",
                                    "path": str(target_path),
                                    "reason": f"disable plugin {plugin_id} in ~/.claude/settings.json (enabledPlugins) or uninstall it",
                                    "current_state": "conflict",
                                    "before_sha256": compute_target_hash(target_path),
                                    "after_sha256": None,
                                }
                                p.append(p_item)

                    elif kind == "duplicate-name":
                        standalone_entries = [e for e in entries if not e.get("origin", "").startswith("plugin:")]
                        plugin_entries = [e for e in entries if e.get("origin", "").startswith("plugin:")]

                        if standalone_entries and plugin_entries:
                            plugin_hashes: dict[str, str] = {}
                            for pe in plugin_entries:
                                pp = pe.get("path")
                                if pp:
                                    ph = compute_target_hash(pathlib.Path(pp))
                                    if ph:
                                        plugin_hashes[pp] = ph

                            skill_name = sc.get("names", [""])[0] or (standalone_entries[0].get("name", ""))
                            cat_hashes = [
                                entry["hash"]
                                for entry in catalog.values()
                                if entry.get("name") == skill_name and entry.get("hash")
                            ]

                            for se in standalone_entries:
                                sp_str = se.get("path")
                                if not sp_str or sp_str in seen_paths:
                                    continue
                                seen_paths.add(sp_str)
                                sp = pathlib.Path(sp_str)
                                s_hash = compute_target_hash(sp)

                                matching_plugin = next(
                                    (pe for pe in plugin_entries if plugin_hashes.get(pe.get("path")) == s_hash),
                                    None,
                                )

                                is_up_to_date = se.get("state") == "up-to-date"
                                is_byte_identical = matching_plugin is not None
                                matches_cat = bool(s_hash and s_hash in cat_hashes)

                                if is_up_to_date or is_byte_identical or matches_cat:
                                    target_plugin = matching_plugin or plugin_entries[0]
                                    target_plugin_id = target_plugin.get("origin", "").split("plugin:", 1)[1]
                                    p_item = {
                                        "action": "trash",
                                        "path": str(sp),
                                        "reason": f"duplicate of plugin {target_plugin_id}; plugin copy kept",
                                        "current_state": "conflict",
                                        "before_sha256": s_hash,
                                        "after_sha256": None,
                                    }
                                    p.append(p_item)
                                    c_items.append({
                                        "assistant": assistant,
                                        "scope": se.get("scope", scope),
                                        "removed": se.get("name", skill_name),
                                        "kept": f"plugin:{target_plugin_id}",
                                        "path": sp,
                                        "reason": p_item["reason"],
                                    })
                                else:
                                    if len(plugin_entries) == 1:
                                        target_plugin_id = plugin_entries[0].get("origin", "").split("plugin:", 1)[1]
                                    else:
                                        target_plugin_id = ", ".join(sorted({
                                            pe.get("origin", "").split("plugin:", 1)[1]
                                            for pe in plugin_entries
                                            if pe.get("origin", "").startswith("plugin:")
                                        }))
                                    p_item = {
                                        "action": "advise",
                                        "path": str(sp),
                                        "reason": f"standalone copy differs from plugin {target_plugin_id}: review and remove one manually",
                                        "current_state": "conflict",
                                        "before_sha256": s_hash,
                                        "after_sha256": None,
                                    }
                                    p.append(p_item)

                        elif len(plugin_entries) >= 2 and not standalone_entries:
                            p_paths = [pe.get("path") for pe in plugin_entries if pe.get("path")]
                            if any(pp in seen_paths for pp in p_paths):
                                continue
                            for pp in p_paths:
                                seen_paths.add(pp)

                            plugin_ids = sorted({
                                pe.get("origin", "").split("plugin:", 1)[1]
                                for pe in plugin_entries
                                if pe.get("origin", "").startswith("plugin:")
                            })
                            plugins_str = ", ".join(plugin_ids)
                            target_path_str = p_paths[0]
                            target_path = pathlib.Path(target_path_str)
                            p_item = {
                                "action": "advise",
                                "path": target_path_str,
                                "reason": f"same skill name provided by plugins {plugins_str}: disable one in enabledPlugins",
                                "current_state": "conflict",
                                "before_sha256": compute_target_hash(target_path),
                                "after_sha256": None,
                            }
                            p.append(p_item)
        return p, c_items

    plan, conflict_items = _build_plan()
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

    with env_lock(h):
        plan, conflict_items = _build_plan()
        plan_hash = compute_plan_hash(plan)
        if expect_plan_hash is not None and expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
                "plan": plan,
                "plan_hash": plan_hash,
            }

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        resolved: list[dict[str, str]] = []
        for item in conflict_items:
            trash_path(
                item["path"],
                assistant=item["assistant"],
                scope=item["scope"],
                kind="skills",
                reason=item["reason"],
                workspace=ws,
                home=h,
                timestamp=ts,
            )
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
    claude_running_detector: Any = None,
) -> dict[str, Any]:
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else pathlib.Path.cwd()

    if "codex" in assistants and scope != "global":
        raise ValueError("Codex does not support project-scoped MCP registration. Only global scope is supported.")

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

    def _build_plan():
        p: list[dict[str, Any]] = []
        cli_ops: list[dict[str, Any]] = []
        file_updates: list[dict[str, Any]] = []
        needs_venv = False

        if server_repo != "codex-mcp" and provision_venv:
            rpath_v = resolve_source_repo(server_repo, h)
            if rpath_v:
                v_dir = rpath_v / ".venv"
                v_py = v_dir / "bin" / "python"
                if not v_py.is_file():
                    needs_venv = True
                    p.append({
                        "action": "venv-create",
                        "path": str(v_dir),
                        "command": f"{sys.executable} -m venv {v_dir}",
                        "reason": f"Create virtualenv for {server_repo}",
                        "current_state": "missing",
                        "before_sha256": None,
                        "after_sha256": None,
                    })
                    p.append({
                        "action": "pip-install",
                        "path": str(v_dir),
                        "command": f"{v_py} -m pip install -q -e {rpath_v}",
                        "reason": f"Install {server_repo} in editable mode",
                        "current_state": "uninstalled",
                        "before_sha256": None,
                        "after_sha256": None,
                    })

        effective_cmd = str(rpath / ".venv" / "bin" / "python") if (provision_venv and server_repo != "codex-mcp") else cmd

        for assistant in assistants:
            if assistant == "claude":
                claude_bin = shutil.which("claude")
                scope_flag = "user" if scope == "global" else "project"
                cfg_path = assistant_mcp_config_path("claude", scope, ws, h)

                if cfg_path.exists():
                    try:
                        existing_data = json.loads(cfg_path.read_text(encoding="utf-8"))
                        if not isinstance(existing_data, dict):
                            raise ValueError(f"Refusing to modify {cfg_path}: top-level JSON value is not an object.")
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Refusing to modify {cfg_path}: it is not valid JSON ({exc}). Fix or register the server manually.") from exc

                if claude_bin is not None:
                    argv = ["claude", "mcp", "add", "--transport", "stdio", "--scope", scope_flag, server_repo, "--", effective_cmd, *cmd_args]
                    mcps = read_claude_mcps(scope, ws, h)
                    cur_state = "registered" if server_repo in mcps else "unregistered"
                    p.append({
                        "action": "cli",
                        "assistant": "claude",
                        "scope": scope,
                        "path": "claude",
                        "command": " ".join(shlex.quote(a) for a in argv),
                        "argv": argv,
                        "reason": f"Register MCP server '{server_repo}' in claude ({scope}) via CLI",
                        "current_state": cur_state,
                        "before_sha256": None,
                        "after_sha256": None,
                    })
                    cli_ops.append({
                        "assistant": "claude",
                        "argv": argv,
                        "cfg_path": cfg_path,
                        "cwd": str(ws) if scope == "project" else None,
                    })
                else:
                    detector = claude_running_detector or _claude_process_detector or is_claude_running
                    if callable(detector) and detector():
                        raise ValueError("Refusing to modify Claude config: a claude process is running. Exit Claude Code or install the claude CLI to register MCP servers safely.")

                    data: dict[str, Any] = {}
                    if cfg_path.exists():
                        data = json.loads(cfg_path.read_text(encoding="utf-8"))
                        cur_state = "registered" if server_repo in data.get("mcpServers", {}) else "unregistered"
                    else:
                        cur_state = "missing"

                    new_data = json.loads(json.dumps(data))
                    new_data.setdefault("mcpServers", {})[server_repo] = {
                        "type": "stdio",
                        "command": effective_cmd,
                        "args": cmd_args,
                    }
                    new_json_str = json.dumps(new_data, indent=2) + "\n"
                    p.append({
                        "action": "edit",
                        "path": str(cfg_path),
                        "reason": f"Register MCP server '{server_repo}' in claude ({scope})",
                        "current_state": cur_state,
                        "before_sha256": compute_target_hash(cfg_path),
                        "after_sha256": hashlib.sha256(new_json_str.encode("utf-8")).hexdigest(),
                    })
                    file_updates.append({
                        "assistant": "claude",
                        "cfg_path": cfg_path,
                        "content": new_json_str,
                    })

            elif assistant == "codex":
                codex_bin = shutil.which("codex")
                cfg_path = assistant_mcp_config_path("codex", "global", ws, h)

                if codex_bin is not None:
                    argv = ["codex", "mcp", "add", server_repo, "--", effective_cmd, *cmd_args]
                    mcps = read_codex_mcps("global", h)
                    cur_state = "registered" if server_repo in mcps else "unregistered"
                    p.append({
                        "action": "cli",
                        "assistant": "codex",
                        "scope": "global",
                        "path": "codex",
                        "command": " ".join(shlex.quote(a) for a in argv),
                        "argv": argv,
                        "reason": f"Register MCP server '{server_repo}' in codex (global) via CLI",
                        "current_state": cur_state,
                        "before_sha256": None,
                        "after_sha256": None,
                    })
                    cli_ops.append({
                        "assistant": "codex",
                        "argv": argv,
                        "cfg_path": cfg_path,
                        "cwd": None,
                    })
                else:
                    if cfg_path.is_file():
                        raw_toml = cfg_path.read_text(encoding="utf-8")
                        try:
                            parsed = tomllib.loads(raw_toml)
                        except Exception as exc:
                            raise ValueError(f"Refusing to modify {cfg_path}: it is not valid TOML ({exc}).") from exc
                        if server_repo in parsed.get("mcp_servers", {}):
                            raise ValueError(f"Refusing to append to {cfg_path}: table [mcp_servers.{server_repo}] already exists. Edit config.toml manually or use `codex mcp add`.")
                        cur_state = "unregistered"
                        existing = raw_toml
                    else:
                        existing = ""
                        cur_state = "missing"

                    entry_toml = format_toml_server_entry(server_repo, effective_cmd, cmd_args)
                    sep = ""
                    if existing:
                        sep = "\n" if existing.endswith("\n\n") else ("\n\n" if not existing.endswith("\n") else "\n")
                    new_toml = existing + sep + entry_toml
                    p.append({
                        "action": "edit",
                        "path": str(cfg_path),
                        "reason": f"Register MCP server '{server_repo}' in codex (global) via config.toml append",
                        "current_state": cur_state,
                        "before_sha256": compute_target_hash(cfg_path),
                        "after_sha256": hashlib.sha256(new_toml.encode("utf-8")).hexdigest(),
                    })
                    file_updates.append({
                        "assistant": "codex",
                        "cfg_path": cfg_path,
                        "content": new_toml,
                    })

            elif assistant == "kilo":
                cfg_path = assistant_mcp_config_path("kilo", scope, ws, h)
                data = {}
                if cfg_path.exists():
                    try:
                        data = json.loads(cfg_path.read_text(encoding="utf-8"))
                        if not isinstance(data, dict):
                            raise ValueError(f"Refusing to modify {cfg_path}: top-level JSON value is not an object.")
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Refusing to modify {cfg_path}: it is not valid JSON ({exc}). Fix or register the server manually.") from exc
                    cur_state = "registered" if server_repo in data.get("mcp", {}) else "unregistered"
                else:
                    data = {"$schema": "https://app.kilo.ai/config.json"}
                    cur_state = "missing"

                new_data = json.loads(json.dumps(data))
                new_data.setdefault("mcp", {})[server_repo] = {
                    "type": "local",
                    "command": [effective_cmd, *cmd_args],
                    "enabled": True,
                }
                new_json_str = json.dumps(new_data, indent=2) + "\n"
                p.append({
                    "action": "edit",
                    "path": str(cfg_path),
                    "reason": f"Register MCP server '{server_repo}' in kilo ({scope})",
                    "current_state": cur_state,
                    "before_sha256": compute_target_hash(cfg_path),
                    "after_sha256": hashlib.sha256(new_json_str.encode("utf-8")).hexdigest(),
                })
                file_updates.append({
                    "assistant": "kilo",
                    "cfg_path": cfg_path,
                    "content": new_json_str,
                })

        return p, cli_ops, file_updates, needs_venv

    plan, cli_ops, file_updates, needs_venv = _build_plan()
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

    with env_lock(h):
        plan, cli_ops, file_updates, needs_venv = _build_plan()
        plan_hash = compute_plan_hash(plan)
        if expect_plan_hash is not None and expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
                "plan": plan,
                "plan_hash": plan_hash,
            }

        if needs_venv and server_repo != "codex-mcp":
            rpath = resolve_source_repo(server_repo, h)
            assert rpath is not None
            venv_py = rpath / ".venv" / "bin" / "python"
            subprocess.run([sys.executable, "-m", "venv", str(rpath / ".venv")], check=True)
            subprocess.run([str(venv_py), "-m", "pip", "install", "-q", "-e", str(rpath)], check=True)
            cmd = str(venv_py)

        updated_configs: list[str] = []

        for op in cli_ops:
            cfg_p = op["cfg_path"]
            if cfg_p.exists():
                shutil.copy2(cfg_p, cfg_p.with_name(cfg_p.name + ".ai-orch.bak"))
            run_env = {**os.environ, "HOME": str(h)}
            res = subprocess.run(op["argv"], capture_output=True, text=True, timeout=60, check=False, env=run_env, cwd=op.get("cwd"))
            if res.returncode != 0:
                err_msg = (res.stderr or res.stdout or f"exit code {res.returncode}").strip()
                raise RuntimeError(f"Command '{' '.join(op['argv'])}' failed: {err_msg}")
            updated_configs.append(str(cfg_p))

        for fup in file_updates:
            cfg_p = fup["cfg_path"]
            cfg_p.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_with_backup(cfg_p, fup["content"])
            updated_configs.append(str(cfg_p))

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
            for entry in sinfo.get("skill_entries", []):
                if entry.get("origin") != "standalone":
                    en_str = "enabled" if entry.get("enabled") else "disabled"
                    print(f"  - {entry['name']:<30} [{entry['state']}] ({entry['origin']}, {en_str})")
            if sinfo.get("mcp_servers"):
                for mname, mdata in sinfo["mcp_servers"].items():
                    prov = mdata.get("provenance", "")
                    overrides = mdata.get("overrides", [])
                    ov_str = f" (overrides: {', '.join(overrides)})" if overrides else ""
                    mscope = mdata.get("scope", scope)
                    print(f"  * [mcp] {mname:<25} [scope: {mscope}] (source: {prov}){ov_str}")
            for c in sinfo["conflicts"]:
                print(f"  ! CONFLICT: {c}")

    if report.get("stray"):
        print("\n=== Stray Config Files ===")
        for s in report["stray"]:
            print(f"  ! STRAY: {s} (not read by tool)")
    return 0


def cmd_fetch_repos(args: argparse.Namespace) -> int:
    res = clone_or_update_repos(
        repos=args.repos,
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
                print(f"  {item['action'].upper():<10} {item['path']} ({item['reason']})")
        else:
            for r, info in res.get("results", {}).items():
                print(f"[{ 'ok' if info.get('ok') else 'FAIL' }] {r}: {info.get('action')} ({info.get('path')})")
    return 0 if res.get("ok") else 1


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
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
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
    p_fr.add_argument("--dry-run", action="store_true", default=False, help="Compute and output execution plan without modifying disk")
    p_fr.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
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
