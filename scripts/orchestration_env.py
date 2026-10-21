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
import io
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore
try:
    import yaml
except ImportError:
    yaml = None
from typing import Any, Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSISTANTS = ("kilo", "claude", "codex")
SCOPES = ("global", "project")
DOCTOR_ACK_FILENAME = "doctor-ack.json"
SEVERITY_LEVELS = ("error", "warning", "info", "neutral")

REMOTE_REPOS = {
    "ai-orchestration": "https://github.com/primax79/ai-orchestration.git",
    "kilo-mcp": "https://github.com/primax79/kilo-mcp.git",
    "claude-mcp": "https://github.com/primax79/claude-mcp.git",
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

OPEN_DUPLICATE_QUESTIONS: dict[str, str] = {
    "gcube-jenkins": "Q006",
    "gcube-security-audit": "Q007",
    "frontend-design": "Q008",
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


# In-memory caches for git history lookups across skill directories and agent files per run
_SKILL_HISTORY_CACHE: dict[tuple[str, str], dict[str, str]] = {}
_SKILL_COMMITS_CACHE: dict[tuple[str, str], list[str]] = {}
_AGENT_HISTORY_CACHE: dict[tuple[str, str, str], dict[str, str]] = {}
_AGENT_COMMITS_CACHE: dict[tuple[str, str], list[str]] = {}


def clear_skill_history_cache() -> None:
    """Clear in-memory git history hash caches (useful between test runs)."""
    _SKILL_HISTORY_CACHE.clear()
    _SKILL_COMMITS_CACHE.clear()
    _AGENT_HISTORY_CACHE.clear()
    _AGENT_COMMITS_CACHE.clear()


def get_git_repo_root(path: pathlib.Path) -> pathlib.Path | None:
    """Find the root git repository directory containing `path`."""
    try:
        res = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return pathlib.Path(res.stdout.strip()).resolve()
    except Exception:
        pass
    for p in [path] + list(path.parents):
        if (p / ".git").exists():
            return p.resolve()
    return None


def compute_git_skill_hash(repo_root: pathlib.Path, commit_sha: str, rel_skill_dir: str) -> str | None:
    """Deterministic SHA-256 over files in a skill directory at a specific git commit.

    Uses `git archive` to reconstruct the exact directory tree without touching disk.
    Matches hash_directory() exactly:
      - Ignores .ai-orch-source.json, index.json, *.pyc, and hidden files/dirs
      - Preserves directory-first traversal order
      - Returns first 16 hex chars of sha256
    """
    res = subprocess.run(
        ["git", "-C", str(repo_root), "archive", "--format=tar", f"{commit_sha}:{rel_skill_dir}"],
        capture_output=True,
        check=False,
    )
    if res.returncode != 0 or not res.stdout:
        return None
    try:
        tar = tarfile.open(fileobj=io.BytesIO(res.stdout))
    except Exception:
        return None

    dir_files: dict[str, list[tuple[str, tarfile.TarInfo, str]]] = {}
    dir_subdirs: dict[str, set[str]] = {}

    for m in tar.getmembers():
        if not m.isfile():
            continue
        path = m.name
        path_parts = path.split("/")
        if any(p.startswith(".") or p == "__pycache__" for p in path_parts[:-1]):
            continue
        fname = path_parts[-1]
        if fname.startswith(".") or fname.endswith(".pyc") or fname in ("index.json", ".ai-orch-source.json"):
            continue
        d = "/".join(path_parts[:-1])
        dir_files.setdefault(d, []).append((fname, m, path))
        for i in range(len(path_parts) - 1):
            parent = "/".join(path_parts[:i])
            sub = path_parts[i]
            if not sub.startswith(".") and sub != "__pycache__":
                dir_subdirs.setdefault(parent, set()).add(sub)

    ordered_files: list[tuple[str, tarfile.TarInfo]] = []

    def walk_dir(d: str) -> None:
        for fname, m, rel in sorted(dir_files.get(d, []), key=lambda x: x[0]):
            ordered_files.append((rel, m))
        for sub in sorted(dir_subdirs.get(d, set())):
            walk_dir(f"{d}/{sub}" if d else sub)

    walk_dir("")

    h = hashlib.sha256()
    for path, m in ordered_files:
        f = tar.extractfile(m)
        content = f.read() if f else b""
        h.update(path.encode("utf-8") + b"\0")
        h.update(content + b"\0")

    return h.hexdigest()[:16]


def find_historical_skill_match(
    inst_hash: str,
    matching_entries: list[dict[str, Any]],
    home: pathlib.Path | None = None,
    max_commits: int = 200,
) -> tuple[str, str] | None:
    """Check if inst_hash matches any earlier commit of the skill in its source repository.

    Returns (repo_name, catalog_hash) or None.
    Caches historical commit hashes per run.
    """
    if not inst_hash:
        return None

    for entry in matching_entries:
        skill_dir = pathlib.Path(entry["path"]).resolve()
        repo_root = get_git_repo_root(skill_dir)
        if not repo_root:
            continue
        try:
            rel_skill_dir = skill_dir.relative_to(repo_root).as_posix()
        except ValueError:
            continue

        cache_key = (str(repo_root), rel_skill_dir)
        if cache_key not in _SKILL_COMMITS_CACHE:
            try:
                res = subprocess.run(
                    ["git", "-C", str(repo_root), "log", "-n", str(max_commits), "--format=%H", "--", rel_skill_dir],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    _SKILL_COMMITS_CACHE[cache_key] = [c for c in res.stdout.strip().split() if c]
                else:
                    _SKILL_COMMITS_CACHE[cache_key] = []
            except Exception:
                _SKILL_COMMITS_CACHE[cache_key] = []
            _SKILL_HISTORY_CACHE[cache_key] = {}

        # Check already computed hashes for this skill directory
        if inst_hash in _SKILL_HISTORY_CACHE[cache_key].values():
            return (entry["repo"], entry["hash"])

        # Compute hashes on-demand for remaining commits
        commits = _SKILL_COMMITS_CACHE[cache_key]
        for commit_sha in commits:
            if commit_sha in _SKILL_HISTORY_CACHE[cache_key]:
                continue
            ch = compute_git_skill_hash(repo_root, commit_sha, rel_skill_dir)
            if ch:
                _SKILL_HISTORY_CACHE[cache_key][commit_sha] = ch
                if ch == inst_hash:
                    return (entry["repo"], entry["hash"])

    return None


def transform_agent_for_assistant(content: str, assistant: str) -> str:
    """Transform agent markdown for target assistant.
    For Claude: drop Kilo-only frontmatter keys (mode, permission).
    """
    if assistant != "claude":
        return content
    content = content.lstrip("\ufeff")
    m = re.match(r"^(\s*---\r?\n)(.*?)(---\r?\n)(.*)$", content, re.DOTALL)
    if not m:
        return content
    header_start, fm_text, header_end, body = m.groups()
    new_fm_lines: list[str] = []
    skip_indent = False
    for line in fm_text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            skip_indent = False
            new_fm_lines.append(line)
            continue
        if not line.startswith(" ") and not line.startswith("\t") and ":" in line:
            key = line.split(":", 1)[0].strip()
            if key in ("mode", "permission"):
                skip_indent = True
                continue
            else:
                skip_indent = False
                new_fm_lines.append(line)
        elif skip_indent and (line.startswith(" ") or line.startswith("\t")):
            continue
        else:
            skip_indent = False
            new_fm_lines.append(line)
    return header_start + "".join(new_fm_lines) + header_end + body


def compute_git_agent_hash(
    repo_root: pathlib.Path,
    commit_sha: str,
    rel_agent_file: str,
    assistant: str = "kilo",
) -> str | None:
    res = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{commit_sha}:{rel_agent_file}"],
        capture_output=True,
        check=False,
    )
    if res.returncode != 0 or not res.stdout:
        return None
    try:
        content = res.stdout.decode("utf-8")
    except Exception:
        content = res.stdout.decode("utf-8", errors="replace")
    transformed = transform_agent_for_assistant(content, assistant)
    return hashlib.sha256(transformed.encode("utf-8")).hexdigest()


def find_historical_agent_match(
    inst_hash: str,
    matching_entries: list[dict[str, Any]],
    assistant: str = "kilo",
    home: pathlib.Path | None = None,
    max_commits: int = 200,
) -> tuple[str, str] | None:
    if not inst_hash:
        return None
    for entry in matching_entries:
        agent_file = pathlib.Path(entry["path"]).resolve()
        repo_root = get_git_repo_root(agent_file)
        if not repo_root:
            continue
        try:
            rel_agent_file = agent_file.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        cache_key = (str(repo_root), rel_agent_file, assistant)
        commits_key = (str(repo_root), rel_agent_file)
        if commits_key not in _AGENT_COMMITS_CACHE:
            try:
                res = subprocess.run(
                    ["git", "-C", str(repo_root), "log", "-n", str(max_commits), "--format=%H", "--", rel_agent_file],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    _AGENT_COMMITS_CACHE[commits_key] = [c for c in res.stdout.strip().split() if c]
                else:
                    _AGENT_COMMITS_CACHE[commits_key] = []
            except Exception:
                _AGENT_COMMITS_CACHE[commits_key] = []

        if cache_key in _AGENT_HISTORY_CACHE and inst_hash in _AGENT_HISTORY_CACHE[cache_key].values():
            return (entry["repo"], entry["hash"])

        commits = _AGENT_COMMITS_CACHE.get(commits_key, [])
        if cache_key not in _AGENT_HISTORY_CACHE:
            _AGENT_HISTORY_CACHE[cache_key] = {}
        for commit_sha in commits:
            if commit_sha in _AGENT_HISTORY_CACHE[cache_key]:
                continue
            ch = compute_git_agent_hash(repo_root, commit_sha, rel_agent_file, assistant)
            if ch:
                _AGENT_HISTORY_CACHE[cache_key][commit_sha] = ch
                if ch == inst_hash:
                    return (entry["repo"], entry["hash"])
    return None


def get_home_dir() -> pathlib.Path:
    env_home = os.environ.get("AI_ORCH_HOME")
    if env_home:
        return pathlib.Path(env_home).expanduser().resolve()
    return pathlib.Path.home()


def get_config_dir(home: pathlib.Path | None = None) -> pathlib.Path:
    if home is not None:
        return home / ".config" / "ai-orchestration"
    env_cfg = os.environ.get("AI_ORCHESTRATION_CONFIG")
    if env_cfg and env_cfg.strip():
        p = pathlib.Path(env_cfg).expanduser().resolve()
        if p.is_file() or p.suffix.lower() == ".toml":
            return p.parent
        return p
    env_dir = os.environ.get("AI_ORCH_CONFIG_DIR")
    if env_dir and env_dir.strip():
        return pathlib.Path(env_dir).expanduser().resolve()
    h = get_home_dir()
    return h / ".config" / "ai-orchestration"


def get_doctor_ack_path(home: pathlib.Path | None = None) -> pathlib.Path:
    return get_config_dir(home) / DOCTOR_ACK_FILENAME


def get_env_lock_path(home: pathlib.Path | None = None) -> pathlib.Path:
    return get_config_dir(home) / "env.lock"


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


def load_doctor_acks(home: pathlib.Path | None = None) -> dict[str, Any]:
    """Load persistent doctor acknowledgments from <config dir>/doctor-ack.json."""
    ack_path = get_doctor_ack_path(home)
    if not ack_path.is_file():
        return {}
    try:
        data = json.loads(ack_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("acknowledgments", data)
    except Exception:
        pass
    return {}


def save_doctor_acks(acks: dict[str, Any], home: pathlib.Path | None = None) -> None:
    """Save persistent doctor acknowledgments to <config dir>/doctor-ack.json atomically."""
    ack_path = get_doctor_ack_path(home)
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "acknowledgments": acks}
    temp_path = ack_path.with_suffix(f".tmp.{os.getpid()}")
    try:
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(ack_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def compute_entries_content_hashes(entries: list[dict[str, Any]]) -> list[str]:
    """Compute sorted content hashes for all unique involved entries in a finding."""
    hashes: list[str] = []
    seen_paths: set[str] = set()
    for e in entries:
        ep = e.get("path")
        if not ep or ep in seen_paths:
            continue
        seen_paths.add(ep)
        h = compute_target_hash(pathlib.Path(ep))
        if h:
            hashes.append(h)
    return sorted(hashes)


def make_ack_storage_key(kind: str, names: list[str], content_hashes: list[str]) -> str:
    """Generate canonical key for doctor-ack.json based on kind and content hashes."""
    names_str = ",".join(sorted(names))
    hashes_str = ",".join(content_hashes)
    return f"{kind}:{names_str}:{hashes_str}"


def is_finding_acknowledged(
    kind: str,
    names: list[str],
    entries: list[dict[str, Any]],
    acks: dict[str, Any],
    group_key: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Check if a finding matches an active acknowledgment in doctor-ack.json.
    Returns (is_acked, ack_record).
    Lapses when any involved copy's content hash changes.
    """
    if not acks:
        return False, None

    current_hashes = compute_entries_content_hashes(entries)
    sorted_names = sorted(names)

    for ack_id, ack in acks.items():
        if not isinstance(ack, dict):
            continue
        ack_kind = ack.get("kind")
        ack_names = sorted(ack.get("names", []))
        ack_hashes = ack.get("content_hashes", [])
        ack_group_key = ack.get("group_key")

        # Match kind and names (or group_key)
        kind_matches = (ack_kind == kind)
        names_match = (ack_names == sorted_names) or (bool(group_key) and ack_group_key == group_key)

        if kind_matches and names_match:
            # Check content hashes: ack is valid only if hashes match current hashes
            if ack_hashes == current_hashes and len(current_hashes) > 0:
                return True, ack
            elif not current_hashes and not ack_hashes:
                return True, ack

    return False, None


def skill_has_precedence_section(skill_path: pathlib.Path | str) -> bool:
    """Check if a skill directory (or SKILL.md file) contains a Precedence section."""
    if not skill_path:
        return False
    p = pathlib.Path(skill_path)
    skill_md = p / "SKILL.md" if p.is_dir() else p
    if not skill_md.is_file():
        return False
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        return bool(re.search(r"^#{1,4}\s+.*Precedence", text, re.MULTILINE) or "Precedence" in text)
    except Exception:
        return False


def parse_frontmatter_and_body(content: str) -> tuple[dict[str, Any] | None, str]:
    """Parse YAML-ish frontmatter and body from a Markdown document (e.g. SKILL.md)."""
    content = content.lstrip("\ufeff")
    m = re.match(r"^\s*---\r?\n(.*?)\r?\n(?:---|\.\.\.)(?:\r?\n(.*))?$", content, re.DOTALL)
    if not m:
        return None, content
    fm_raw = m.group(1)
    body = m.group(2) or ""
    try:
        if yaml is not None:
            data = yaml.safe_load(fm_raw)
            if isinstance(data, dict):
                return data, body
            return None, body
    except Exception:
        pass
    parsed: dict[str, Any] = {}
    current_key: str | None = None
    for line in fm_raw.splitlines():
        line_s = line.strip()
        if not line_s or line_s.startswith("#"):
            continue
        if ":" in line_s and not line.startswith(" ") and not line.startswith("\t"):
            k, v = line_s.split(":", 1)
            current_key = k.strip()
            parsed[current_key] = v.strip().strip("\"'")
        elif current_key and (line.startswith(" ") or line.startswith("\t")):
            if isinstance(parsed[current_key], str):
                parsed[current_key] += " " + line_s
    return parsed, body


def normalize_frontmatter(fm: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize frontmatter dictionary:
    - Merges flattened vs nested `metadata` maps
    - Drops empty values (None, empty string, empty dict/list)
    - Normalizes string whitespace (including multiline/folded description)
    - Normalizes scalar representations
    """
    if not isinstance(fm, dict):
        return {}

    result: dict[str, Any] = {}
    meta = fm.get("metadata")
    meta_dict = meta if isinstance(meta, dict) else {}

    def _is_empty(val: Any) -> bool:
        return val is None or val == "" or val == {} or val == []

    def _clean_val(key: str, val: Any) -> Any:
        if isinstance(val, str):
            val_s = val.strip()
            if key == "description":
                val_s = re.sub(r"\s+", " ", val_s)
            return val_s
        elif isinstance(val, (int, float, bool)):
            return str(val)
        elif isinstance(val, dict):
            res = {}
            for sub_k, sub_v in val.items():
                if not _is_empty(sub_v):
                    res[sub_k] = _clean_val(sub_k, sub_v)
            return res
        elif isinstance(val, list):
            res = []
            for item in val:
                if not _is_empty(item):
                    res.append(_clean_val(key, item))
            return res
        return val

    # 1. Process top-level keys (skipping metadata key itself)
    for k, v in fm.items():
        if k == "metadata" or _is_empty(v):
            continue
        result[k] = _clean_val(k, v)

    # 2. Merge metadata subkeys into top-level
    for k, v in meta_dict.items():
        if _is_empty(v):
            continue
        if k not in result or _is_empty(result[k]):
            result[k] = _clean_val(k, v)

    return {k: v for k, v in result.items() if not _is_empty(v)}


def normalize_body(body: str) -> str:
    """Normalize markdown body by standardizing line endings and trailing whitespace."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in body.split("\n")]
    return "\n".join(lines).strip()


def compare_skill_md(text_a: str, text_b: str) -> tuple[bool, list[str], bool]:
    """Compare two SKILL.md contents using normalized frontmatter and normalized body.
    Returns (is_equal, changed_fm_keys, body_differs).
    """
    fm_a_raw, body_a = parse_frontmatter_and_body(text_a)
    fm_b_raw, body_b = parse_frontmatter_and_body(text_b)

    norm_fm_a = normalize_frontmatter(fm_a_raw)
    norm_fm_b = normalize_frontmatter(fm_b_raw)

    changed_fm_keys = sorted(
        k for k in (set(norm_fm_a.keys()) | set(norm_fm_b.keys()))
        if norm_fm_a.get(k) != norm_fm_b.get(k)
    )

    norm_body_a = normalize_body(body_a)
    norm_body_b = normalize_body(body_b)
    body_differs = (norm_body_a != norm_body_b)

    is_equal = (len(changed_fm_keys) == 0 and not body_differs)
    return is_equal, changed_fm_keys, body_differs


def compare_skill_dirs(dir_a: pathlib.Path, dir_b: pathlib.Path) -> dict[str, Any]:
    """Compare two skill directories with normalized frontmatter/body.
    Returns:
        {
            "equivalent": bool,
            "diff_files": list[str],
            "changed_fm_keys": list[str],
            "body_differs": bool,
        }
    """
    if not (dir_a.exists() or dir_a.is_symlink()) or not (dir_b.exists() or dir_b.is_symlink()):
        return {
            "equivalent": False,
            "diff_files": ["<missing-path>"],
            "changed_fm_keys": [],
            "body_differs": False,
        }

    p_a = dir_a.resolve() if dir_a.is_symlink() else dir_a
    p_b = dir_b.resolve() if dir_b.is_symlink() else dir_b

    def _collect_files(d: pathlib.Path) -> dict[str, pathlib.Path]:
        res: dict[str, pathlib.Path] = {}
        if d.is_file():
            res[d.name] = d
            return res
        for root, dirs, files in os.walk(d):
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != "__pycache__")
            for fname in sorted(files):
                if fname.startswith(".") or fname.endswith(".pyc") or fname in ("index.json", ".ai-orch-source.json"):
                    continue
                fpath = pathlib.Path(root) / fname
                rel = fpath.relative_to(d).as_posix()
                res[rel] = fpath
        return res

    files_a = _collect_files(p_a)
    files_b = _collect_files(p_b)

    set_a = set(files_a.keys())
    set_b = set(files_b.keys())

    only_in_a = sorted(set_a - set_b)
    only_in_b = sorted(set_b - set_a)
    common = sorted(set_a & set_b)

    diff_files = list(only_in_a + only_in_b)
    changed_fm_keys: list[str] = []
    body_differs = False

    for rel in common:
        path_a = files_a[rel]
        path_b = files_b[rel]
        if rel == "SKILL.md":
            try:
                text_a = path_a.read_text(encoding="utf-8", errors="replace")
                text_b = path_b.read_text(encoding="utf-8", errors="replace")
                is_eq, fm_keys, b_diff = compare_skill_md(text_a, text_b)
                if not is_eq:
                    diff_files.append(rel)
                    changed_fm_keys = fm_keys
                    body_differs = b_diff
            except Exception:
                diff_files.append(rel)
        else:
            try:
                bytes_a = path_a.read_bytes()
                bytes_b = path_b.read_bytes()
                if bytes_a != bytes_b:
                    text_eq = False
                    try:
                        t_a = bytes_a.decode("utf-8").replace("\r\n", "\n")
                        t_b = bytes_b.decode("utf-8").replace("\r\n", "\n")
                        if t_a == t_b:
                            text_eq = True
                    except Exception:
                        pass
                    if not text_eq:
                        diff_files.append(rel)
            except Exception:
                diff_files.append(rel)

    diff_files = sorted(set(diff_files))
    equivalent = (len(diff_files) == 0 and len(changed_fm_keys) == 0 and not body_differs)

    return {
        "equivalent": equivalent,
        "diff_files": diff_files,
        "changed_fm_keys": changed_fm_keys,
        "body_differs": body_differs,
    }


def skill_equivalent(path_a: pathlib.Path, path_b: pathlib.Path) -> bool:
    """Check if two skill paths are equivalent (identical or normalized equal)."""
    if not (path_a.exists() or path_a.is_symlink()) or not (path_b.exists() or path_b.is_symlink()):
        return False
    h_a = compute_target_hash(path_a)
    h_b = compute_target_hash(path_b)
    if h_a and h_b and h_a == h_b:
        return True
    return compare_skill_dirs(path_a, path_b)["equivalent"]


def agent_equivalent(agent_path: pathlib.Path, catalog_agent_path: pathlib.Path, assistant: str = "kilo") -> bool:
    """Check if an installed agent file is equivalent to a catalog agent (with per-assistant transform)."""
    try:
        inst_text = agent_path.read_text(encoding="utf-8")
        cat_text = catalog_agent_path.read_text(encoding="utf-8")
        trans_cat = transform_agent_for_assistant(cat_text, assistant)
        if inst_text == trans_cat:
            return True
        is_eq, _, _ = compare_skill_md(inst_text, trans_cat)
        return is_eq
    except Exception:
        return False


def format_diff_summary(diff_info: dict[str, Any]) -> str:
    """Generate a short diff summary string describing differences between two skills."""
    parts = []
    diff_files = diff_info.get("diff_files", [])
    if diff_files:
        files_str = ", ".join(diff_files[:5])
        if len(diff_files) > 5:
            files_str += f" (+{len(diff_files) - 5} more)"
        parts.append(f"files: {files_str}")
    changed_fm_keys = diff_info.get("changed_fm_keys", [])
    if changed_fm_keys:
        parts.append(f"frontmatter keys: {', '.join(changed_fm_keys)}")
    elif diff_info.get("body_differs"):
        parts.append("body differs")
    return "; ".join(parts) if parts else "differing contents"


def find_matching_cached_plugin_skill(
    skill_name: str,
    standalone_path: pathlib.Path,
    plugin_id: str = "",
    home: pathlib.Path | None = None,
) -> tuple[pathlib.Path | None, bool]:
    """Search ~/.claude/plugins/cache for any cached version of the plugin/skill that matches standalone_path."""
    h = home or get_home_dir()
    cache_dir = h / ".claude" / "plugins" / "cache"
    if not cache_dir.is_dir():
        return None, False

    pname, mname = "", ""
    if plugin_id:
        if "@" in plugin_id:
            pname, mname = plugin_id.split("@", 1)
        else:
            pname = plugin_id

    cand_paths: list[pathlib.Path] = []
    if mname and pname:
        cand_paths.extend(cache_dir.glob(f"{mname}/{pname}/*/skills/{skill_name}"))
        cand_paths.extend(cache_dir.glob(f"{mname}/{pname}/*"))
    elif pname:
        cand_paths.extend(cache_dir.glob(f"*/{pname}/*/skills/{skill_name}"))
        cand_paths.extend(cache_dir.glob(f"*/{pname}/*"))
    else:
        cand_paths.extend(cache_dir.glob(f"*/*/*/skills/{skill_name}"))

    all_cands = set(cand_paths)
    for p in cache_dir.glob(f"*/*/*/skills/{skill_name}"):
        all_cands.add(p)

    for cand in sorted(all_cands):
        if not cand.is_dir() or not (cand / "SKILL.md").is_file():
            continue
        if skill_equivalent(standalone_path, cand):
            return cand, True

    return None, False


def find_matching_marketplace_plugin_skill(
    skill_name: str,
    standalone_path: pathlib.Path,
    plugin_id: str = "",
    home: pathlib.Path | None = None,
) -> tuple[pathlib.Path | None, bool]:
    """Check marketplace clone for matching skill copy."""
    h = home or get_home_dir()
    mname, pname = "", ""
    if "@" in plugin_id:
        pname, mname = plugin_id.split("@", 1)
    else:
        pname = plugin_id

    mkt_names = [mname] if mname else ["ai-orchestration", "kilo-mcp", "claude-mcp", "gcube-ai-toolkit", "agentic-coding-kit"]

    for m in mkt_names:
        clone = find_marketplace_clone(m, h)
        if not clone or not clone.is_dir():
            continue
        s_pdir = find_plugin_source_dir(clone, pname) if pname else None
        cands = []
        if s_pdir and s_pdir.is_dir():
            cands.append(s_pdir / "skills" / skill_name)
            cands.append(s_pdir)
        cands.extend(clone.glob(f"*/skills/{skill_name}"))
        cands.extend(clone.glob(f"plugins/*/skills/{skill_name}"))

        for cand in cands:
            if cand.is_dir() and (cand / "SKILL.md").is_file():
                if skill_equivalent(standalone_path, cand):
                    return cand, True

    return None, False


def compute_group_key(kind: str, names: list[str], entries: list[dict[str, Any]] | None = None) -> str:
    sorted_names = sorted(names)
    names_str = ",".join(sorted_names)
    if kind == "trigger-conflict":
        return f"trigger-conflict:{names_str}"
    elif kind == "duplicate-name":
        return f"duplicate-name:{names_str}"
    elif kind == "stale-plugin-copy":
        return f"stale-plugin-copy:{names_str}"
    elif kind == "stray":
        return f"stray:{names_str}"
    else:
        return f"{kind}:{names_str}"


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
        for parent in list(root.parents)[:8]:
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
      - 'up-to-date': matches a catalog skill by content hash or symlink target (with receipt or direct catalog symlink)
      - 'up-to-date-legacy': matches current catalog source by content hash, but has no receipt
      - 'outdated-legacy': matches an earlier commit in source git history, but has no receipt
      - 'modified-or-outdated': name in catalog, content differs or not symlink to catalog,
                                but was installed by this tool (.ai-orch-source.json or symlink into known repo)
      - 'foreign': name in catalog, but content differs/not catalog symlink AND not in source git history
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

    # No receipt: check if hash matches any catalog entry (legacy copies matching current source)
    for entry in matching_entries:
        if (inst_hash and inst_hash == entry["hash"]) or skill_equivalent(child, pathlib.Path(entry["path"])):
            return ("up-to-date-legacy", entry["repo"], entry["hash"])

    # No receipt: check if hash matches any earlier commit in source git history
    hist_match = find_historical_skill_match(inst_hash, matching_entries, home=home)
    if hist_match:
        hist_repo, hist_cat_hash = hist_match
        return ("outdated-legacy", hist_repo, hist_cat_hash)

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

    # Neither marker nor symlink to known repo and no catalog or historical hash match
    return ("foreign", None, None)


def detect_agent_state(
    child: pathlib.Path,
    catalog_agents: dict[tuple[str, str, str], dict[str, Any]],
    receipts: dict[str, dict[str, Any]],
    home: pathlib.Path | None = None,
    assistant: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Determine state, source_repo, and source_hash for an installed agent file/symlink."""
    aname = child.name
    if aname in OBSOLETE_AGENT_RENAMES:
        return (f"obsolete-renamed->{OBSOLETE_AGENT_RENAMES[aname]}", None, None)

    asst = assistant
    if not asst:
        parts = child.resolve().parts if child.is_symlink() else child.parts
        if ".claude" in child.parts or ".claude" in parts:
            asst = "claude"
        elif ".kilo" in child.parts or ".config/kilo" in child.parts or ".kilo" in parts:
            asst = "kilo"
        elif ".codex" in child.parts or ".codex" in parts:
            asst = "codex"
        else:
            asst = "kilo"

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
        cat_trans_hash = cat_hash
        if cat_entry:
            try:
                raw_c = pathlib.Path(cat_entry["path"]).read_text(encoding="utf-8")
                cat_trans_hash = hashlib.sha256(transform_agent_for_assistant(raw_c, asst).encode("utf-8")).hexdigest()
            except Exception:
                pass

        if inst_hash and inst_hash == r_hash and (not cat_trans_hash or inst_hash == cat_trans_hash):
            return ("up-to-date", r_repo, cat_hash or r_hash)
        else:
            return ("modified-or-outdated", r_repo, cat_hash or r_hash)

    # No receipt: check if hash matches any catalog entry (legacy copies)
    for entry in matching_entries:
        try:
            raw_c = pathlib.Path(entry["path"]).read_text(encoding="utf-8")
            trans_h = hashlib.sha256(transform_agent_for_assistant(raw_c, asst).encode("utf-8")).hexdigest()
        except Exception:
            trans_h = entry["hash"]
        if (inst_hash and inst_hash == trans_h) or agent_equivalent(child, pathlib.Path(entry["path"]), asst):
            return ("up-to-date-legacy", entry["repo"], entry["hash"])

    # No receipt: check if hash matches any earlier commit in source git history
    hist_match = find_historical_agent_match(inst_hash, matching_entries, assistant=asst, home=home)
    if hist_match:
        hist_repo, hist_cat_hash = hist_match
        return ("outdated-legacy", hist_repo, hist_cat_hash)

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


DEFAULT_GENERIC_BOUND_PAIRS: list[tuple[str, str]] = [
    ("orchestration-workflow", "kilo-mcp-orchestrator"),
    ("executor-contract", "kilo-mcp-executor-contract"),
    ("conflict-resolver", "kilo-mcp-conflict-resolver"),
    ("orchestration-metrics", "kilo-mcp-metrics-analyst"),
]


def get_generic_bound_pairs(home: pathlib.Path | None = None) -> list[tuple[str, str]]:
    """Return generic/bound skill pairs from kilo-mcp bindings or defaults."""
    h = home or get_home_dir()
    pairs = list(DEFAULT_GENERIC_BOUND_PAIRS)
    seen_generic = {p[0] for p in pairs}
    rpath = resolve_source_repo("kilo-mcp", h)
    if rpath and (rpath / "bindings").is_dir():
        for bfile in sorted((rpath / "bindings").glob("*.json")):
            generic_name = bfile.stem
            try:
                bdata = json.loads(bfile.read_text(encoding="utf-8"))
                bound_name = bdata.get("name")
                if bound_name:
                    if generic_name in seen_generic:
                        pairs = [(g, bound_name) if g == generic_name else (g, b) for g, b in pairs]
                    else:
                        pairs.append((generic_name, bound_name))
                        seen_generic.add(generic_name)
            except Exception:
                pass
    return pairs


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
        "keep_scope": str(cfg.get("env", {}).get("conflicts", {}).get("keep_scope", "global")),
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


def format_toml_server_entry(
    name: str,
    command: str,
    args: list[str],
    extra_fields: dict[str, Any] | None = None,
) -> str:
    """Format a surgical [mcp_servers.<name>] TOML table block."""
    key = name if re.match(r"^[A-Za-z0-9_-]+$", name) else json.dumps(name)
    lines = [f"[mcp_servers.{key}]"]
    lines.append(f"command = {json.dumps(command)}")
    lines.append(f"args = {json.dumps(args)}")
    if extra_fields:
        for fk, fv in extra_fields.items():
            if fv is None:
                continue
            lines.append(f"{fk} = {json.dumps(fv)}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Version-Free Launcher & Broker MCP Registration (Task 16.6)
# ---------------------------------------------------------------------------

LAUNCHER_MARKER = "# ai-orchestration-launcher-v1"
BROKER_MCP_SERVER_NAME = "ai-orchestration"
BROKER_MCP_NAMES = ("ai-orchestration", "orchestration-broker", "ai-orchestration-broker")
VERSIONED_PATH_RE = re.compile(r"(/plugins/cache/|/v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?/)")


def _strip_nulls(obj: Any) -> Any:
    """Recursively drop None values from dicts and lists (Claude Code rejects null fields)."""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(v) for v in obj if v is not None]
    return obj


def _has_null_values(obj: Any) -> bool:
    """Return True if obj or any nested dict value / list item is None."""
    if obj is None:
        return True
    if isinstance(obj, dict):
        return any(_has_null_values(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_null_values(x) for x in obj)
    return False


def _is_versioned_path(path_str: str) -> bool:
    """Return True if path_str contains a plugin-cache or semver directory segment."""
    if not path_str:
        return False
    norm = str(path_str).replace("\\", "/")
    return bool(VERSIONED_PATH_RE.search(norm))


def get_launcher_path(
    home: pathlib.Path | None = None,
    custom_path: pathlib.Path | str | None = None,
) -> pathlib.Path:
    """Return the version-free launcher path (default: <home>/.local/bin/ai-orch)."""
    if custom_path is not None:
        return pathlib.Path(custom_path).expanduser().resolve()
    h = home or get_home_dir()
    return h / ".local" / "bin" / "ai-orch"


def is_our_launcher(path: pathlib.Path) -> bool:
    """Return True if `path` is a launcher script managed by ai-orchestration."""
    if path.is_symlink():
        try:
            target_raw = os.readlink(path)
            if "ai-orchestration" in target_raw and target_raw.endswith("ai-orch"):
                return True
            resolved = path.resolve()
            if resolved.is_file():
                head = resolved.read_text(encoding="utf-8", errors="replace")[:4096]
                return LAUNCHER_MARKER in head
        except Exception:
            return False
        return False
    if not path.is_file():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
        return LAUNCHER_MARKER in head
    except Exception:
        return False


def render_launcher_script(fallback_repo_root: pathlib.Path | None = None) -> str:
    """Render the executable version-free launcher script content."""
    default_repo = str((fallback_repo_root or REPO_ROOT).resolve())
    template = '''#!/usr/bin/env python3
__LAUNCHER_MARKER__
"""Version-free launcher for ai-orchestration (execs newest installed copy)."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

DEFAULT_SOURCE_REPO = __DEFAULT_SOURCE_REPO__


def _get_home_dir() -> pathlib.Path:
    raw = os.environ.get("AI_ORCH_HOME")
    if raw and raw.strip():
        return pathlib.Path(raw).expanduser().resolve()
    return pathlib.Path.home().resolve()


def _get_config_dir(home: pathlib.Path) -> pathlib.Path:
    raw = os.environ.get("AI_ORCHESTRATION_CONFIG")
    if raw and raw.strip():
        p = pathlib.Path(raw).expanduser().resolve()
        if p.is_file() or p.suffix.lower() == ".toml":
            return p.parent
        return p
    raw_dir = os.environ.get("AI_ORCH_CONFIG_DIR")
    if raw_dir and raw_dir.strip():
        return pathlib.Path(raw_dir).expanduser().resolve()
    return home / ".config" / "ai-orchestration"


def _parse_semver(v_str: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\\d+", str(v_str))]
    return tuple(nums) if nums else (0, 0, 0)


def _read_version_for_bin(bin_path: pathlib.Path) -> tuple[int, ...]:
    root = bin_path.parent.parent
    best: tuple[int, ...] = (0, 0, 0)
    if re.match(r"^v?\\d+\\.\\d+\\.\\d+", root.name):
        best = max(best, _parse_semver(root.name))
    for rel in (
        ".claude-plugin/plugin.json",
        "plugin.json",
        "plugins/architect-side/.claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        "marketplace.json",
    ):
        cand = root / rel
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if "version" in data and data["version"]:
                        best = max(best, _parse_semver(str(data["version"])))
                    for p in data.get("plugins", []):
                        if isinstance(p, dict) and p.get("version"):
                            best = max(best, _parse_semver(str(p["version"])))
            except Exception:
                pass
    return best


def _configured_checkout_from_toml(cfg_dir: pathlib.Path) -> pathlib.Path | None:
    toml_file = cfg_dir / "orchestration.toml"
    if not toml_file.is_file():
        return None
    raw = toml_file.read_text(encoding="utf-8", errors="replace")
    data = None
    if tomllib is not None:
        try:
            data = tomllib.loads(raw)
        except Exception:
            data = None
    if isinstance(data, dict):
        for k in ("source_checkout", "source_repo", "ai_orchestration_root"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return pathlib.Path(v).expanduser().resolve()
        for sec in ("launcher", "paths", "repos"):
            sub = data.get(sec)
            if isinstance(sub, dict):
                for k in ("source_checkout", "source_repo", "source_path", "repo_path", "path", "ai_orchestration", "ai-orchestration"):
                    v = sub.get(k)
                    if isinstance(v, str) and v.strip():
                        return pathlib.Path(v).expanduser().resolve()
    m = re.search(r'(?:source_checkout|source_repo|source_path|ai_orchestration)\\s*=\\s*"([^"]+)"', raw)
    if m:
        return pathlib.Path(m.group(1)).expanduser().resolve()
    return None


def resolve_ai_orch_bin() -> pathlib.Path:
    env_root = os.environ.get("AI_ORCH_SOURCE_ROOT")
    if env_root and env_root.strip():
        cand = pathlib.Path(env_root).expanduser().resolve() / "bin" / "ai-orch"
        if cand.is_file():
            return cand

    home = _get_home_dir()
    cfg_dir = _get_config_dir(home)

    candidates: list[tuple[tuple[int, ...], int, float, pathlib.Path]] = []
    seen: set[str] = set()

    def _add(bin_p: pathlib.Path, is_configured: int = 0, explicit_ver: str | None = None) -> None:
        if not bin_p.is_file():
            return
        key = str(bin_p.resolve())
        if key in seen:
            return
        seen.add(key)
        ver = _parse_semver(explicit_ver) if explicit_ver else _read_version_for_bin(bin_p)
        if is_configured and ver == (0, 0, 0):
            ver = (9999, 0, 0)
        try:
            mtime = bin_p.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((ver, is_configured, mtime, bin_p))

    cfg_checkout = _configured_checkout_from_toml(cfg_dir)
    if cfg_checkout is not None:
        _add(cfg_checkout / "bin" / "ai-orch", is_configured=1)

    reg_file = home / ".claude" / "plugins" / "installed_plugins.json"
    if reg_file.is_file():
        try:
            reg_data = json.loads(reg_file.read_text(encoding="utf-8"))
            plugins_map = reg_data.get("plugins", dict()) if isinstance(reg_data, dict) else dict()
            if isinstance(plugins_map, dict):
                for pid, entries in plugins_map.items():
                    if "ai-orchestration" not in str(pid) or not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        ip = entry.get("installPath")
                        ver_str = str(entry.get("version") or "")
                        if ip:
                            ip_path = pathlib.Path(str(ip))
                            _add(ip_path / "bin" / "ai-orch", explicit_ver=ver_str or None)
                            _add(ip_path.parent.parent / "bin" / "ai-orch", explicit_ver=ver_str or None)
        except Exception:
            pass

    cache_root = home / ".claude" / "plugins" / "cache" / "ai-orchestration"
    if cache_root.is_dir():
        for b in cache_root.glob("*/*/bin/ai-orch"):
            _add(b, explicit_ver=b.parent.parent.name)
        for b in cache_root.glob("*/bin/ai-orch"):
            _add(b, explicit_ver=b.parent.parent.name)

    mkt_bin = home / ".claude" / "plugins" / "marketplaces" / "ai-orchestration" / "bin" / "ai-orch"
    _add(mkt_bin)

    repos_bin = home / ".ai-orchestration" / "repos" / "ai-orchestration" / "bin" / "ai-orch"
    _add(repos_bin)

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return candidates[0][3]

    fallback_bin = pathlib.Path(DEFAULT_SOURCE_REPO) / "bin" / "ai-orch"
    return fallback_bin


def main() -> None:
    target = resolve_ai_orch_bin()
    if not target.is_file():
        sys.stderr.write(f"ai-orch launcher error: target binary not found at {target}\\n")
        sys.exit(1)
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])


if __name__ == "__main__":
    main()
'''
    return (
        template
        .replace("__LAUNCHER_MARKER__", LAUNCHER_MARKER)
        .replace("__DEFAULT_SOURCE_REPO__", json.dumps(default_repo))
    )


def install_launcher(
    home: pathlib.Path | None = None,
    target_path: pathlib.Path | str | None = None,
    source_repo: pathlib.Path | None = None,
    dry_run: bool = False,
    apply: bool = False,
    expect_hash: str | None = None,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Preview or install the version-free `ai-orch` launcher executable.

    Follows the preview -> `--apply --expect-hash` flow:
    - Never overwrites an unrelated (foreign) file.
    - Updates an existing launcher of ours in place.
    """
    h = home or get_home_dir()
    launcher_path = get_launcher_path(h, target_path)
    expected = expect_hash if expect_hash is not None else expect_plan_hash
    effective_dry_run = bool(dry_run) or not (bool(apply) or expected is not None)
    new_content = render_launcher_script(source_repo or REPO_ROOT)
    after_sha = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

    def _build_plan() -> tuple[list[dict[str, Any]], str, bool]:
        before_sha = compute_target_hash(launcher_path)
        exists = launcher_path.exists() or launcher_path.is_symlink()
        if exists:
            if (launcher_path.is_dir() and not launcher_path.is_symlink()) or not is_our_launcher(launcher_path):
                p_item = {
                    "action": "refuse",
                    "path": str(launcher_path),
                    "reason": f"Refusing to overwrite unrelated file at {launcher_path}",
                    "current_state": "foreign",
                    "before_sha256": before_sha,
                    "after_sha256": None,
                }
                return [p_item], "foreign", True
            try:
                cur_text = launcher_path.read_text(encoding="utf-8")
            except Exception:
                cur_text = ""
            is_exec = os.access(launcher_path, os.X_OK)
            if cur_text == new_content and is_exec:
                p_item = {
                    "action": "noop",
                    "path": str(launcher_path),
                    "reason": "Version-free launcher already up to date",
                    "current_state": "up-to-date",
                    "before_sha256": before_sha,
                    "after_sha256": after_sha,
                }
                return [p_item], "up-to-date", False
            p_item = {
                "action": "update",
                "path": str(launcher_path),
                "reason": "Update existing ai-orchestration launcher in place",
                "current_state": "outdated",
                "before_sha256": before_sha,
                "after_sha256": after_sha,
            }
            return [p_item], "outdated", False
        else:
            p_item = {
                "action": "create",
                "path": str(launcher_path),
                "reason": "Install version-free ai-orch launcher",
                "current_state": "missing",
                "before_sha256": None,
                "after_sha256": after_sha,
            }
            return [p_item], "missing", False

    plan, cur_state, is_foreign = _build_plan()
    plan_hash = compute_plan_hash(plan)

    if is_foreign:
        return {
            "ok": False,
            "error": f"Refusing to overwrite unrelated file at {launcher_path}",
            "dry_run": effective_dry_run,
            "applied": False,
            "path": str(launcher_path),
            "current_state": cur_state,
            "plan": plan,
            "plan_hash": plan_hash,
            "hash": plan_hash,
            "expect_hash": plan_hash,
        }

    valid_hashes = {plan_hash, after_sha}
    if plan[0].get("before_sha256"):
        valid_hashes.add(plan[0]["before_sha256"])

    if expected is not None and expected not in valid_hashes:
        return {
            "ok": False,
            "error": f"Plan hash mismatch: expected {expected}, but recomputed plan hash is {plan_hash}",
            "dry_run": effective_dry_run,
            "applied": False,
            "path": str(launcher_path),
            "current_state": cur_state,
            "plan": plan,
            "plan_hash": plan_hash,
            "hash": plan_hash,
            "expect_hash": plan_hash,
        }

    if effective_dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "applied": False,
            "action": plan[0]["action"],
            "path": str(launcher_path),
            "current_state": cur_state,
            "content": new_content,
            "plan": plan,
            "plan_hash": plan_hash,
            "hash": plan_hash,
            "expect_hash": plan_hash,
        }

    with env_lock(h):
        plan, cur_state, is_foreign = _build_plan()
        plan_hash = compute_plan_hash(plan)
        if is_foreign:
            return {
                "ok": False,
                "error": f"Refusing to overwrite unrelated file at {launcher_path}",
                "dry_run": False,
                "applied": False,
                "path": str(launcher_path),
                "current_state": cur_state,
                "plan": plan,
                "plan_hash": plan_hash,
                "hash": plan_hash,
                "expect_hash": plan_hash,
            }
        valid_hashes = {plan_hash, after_sha}
        if plan[0].get("before_sha256"):
            valid_hashes.add(plan[0]["before_sha256"])
        if expected is not None and expected not in valid_hashes:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expected}, but recomputed plan hash is {plan_hash}",
                "dry_run": False,
                "applied": False,
                "path": str(launcher_path),
                "current_state": cur_state,
                "plan": plan,
                "plan_hash": plan_hash,
                "hash": plan_hash,
                "expect_hash": plan_hash,
            }

        launcher_path.parent.mkdir(parents=True, exist_ok=True)
        if launcher_path.is_symlink():
            launcher_path.unlink()
        _atomic_write_with_backup(launcher_path, new_content)
        launcher_path.chmod(0o755)
        new_sha = compute_target_hash(launcher_path) or after_sha

        return {
            "ok": True,
            "dry_run": False,
            "applied": True,
            "action": plan[0]["action"],
            "path": str(launcher_path),
            "current_state": cur_state,
            "plan": plan,
            "plan_hash": plan_hash,
            "hash": new_sha,
            "expect_hash": plan_hash,
        }


def _looks_like_broker_entry(name: str, cfg: Any) -> bool:
    """Return True if an MCP server entry is the orchestration broker shim."""
    if name in BROKER_MCP_NAMES:
        return True
    if not isinstance(cfg, dict):
        return False
    cmd_str, args_list, _ = normalize_mcp_config(cfg)
    tokens = ([cmd_str] if cmd_str else []) + list(args_list)
    joined = " ".join(str(t) for t in tokens if t)
    if "ai-orch" in joined and "mcp" in tokens:
        return True
    if "backend.broker" in joined or "ai-orch-broker" in joined:
        return True
    if any(str(t).endswith("broker/shim.py") for t in tokens):
        return True
    return False


def build_client_broker_mcp_config(
    assistant: str,
    launcher_path: pathlib.Path | str,
) -> dict[str, Any]:
    """Build normative broker MCP configuration for a client per spec §3a."""
    l_str = str(launcher_path)
    if assistant == "claude":
        # Spec §3a: Claude Code rejects null fields
        return _strip_nulls({
            "type": "stdio",
            "command": l_str,
            "args": ["mcp"],
        })
    if assistant == "kilo":
        # Spec §3a: Kilo uses "mcp": {"<name>": {"type": "local", "command": [...], "environment": {...}}}
        return _strip_nulls({
            "type": "local",
            "command": [l_str, "mcp"],
            "environment": {},
            "enabled": True,
        })
    if assistant == "codex":
        # Spec §3a: Codex needs per-server default_tools_approval_mode = "approve"
        return _strip_nulls({
            "command": l_str,
            "args": ["mcp"],
            "default_tools_approval_mode": "approve",
        })
    raise ValueError(f"Unknown assistant: {assistant}")


def _upsert_codex_toml_server(
    raw_toml: str,
    server_name: str,
    command: str,
    args: list[str],
    approval_mode: str = "approve",
) -> str:
    """Insert or replace [mcp_servers.<server_name>] in Codex config.toml with default_tools_approval_mode."""
    if raw_toml.strip():
        try:
            parsed = tomllib.loads(raw_toml)
            if not isinstance(parsed, dict):
                raise ValueError("Top-level TOML is not a table")
        except Exception as exc:
            raise ValueError(f"Invalid TOML ({exc})") from exc

    cleaned = raw_toml
    for prefix in ("mcp_servers", "mcp.servers"):
        pat = rf'(?ms)^\[{re.escape(prefix)}\.(?:{re.escape(server_name)}|"{re.escape(server_name)}")\]\s*\n.*?(?=^\[|\Z)'
        cleaned = re.sub(pat, "", cleaned)

    entry_block = format_toml_server_entry(
        server_name,
        command,
        args,
        extra_fields={"default_tools_approval_mode": approval_mode},
    )
    cleaned = cleaned.rstrip()
    if cleaned:
        new_toml = cleaned + "\n\n" + entry_block
    else:
        new_toml = entry_block

    # Validate generated TOML
    tomllib.loads(new_toml)
    return new_toml


def _resolve_client_broker_config_path(
    assistant: str,
    scope: str,
    workspace: pathlib.Path | None,
    home: pathlib.Path,
) -> pathlib.Path:
    """Resolve the config file path to inspect/update for broker MCP registration."""
    ws = workspace.resolve() if workspace else pathlib.Path.cwd()
    if assistant == "claude":
        if scope == "global":
            claude_json = home / ".claude.json"
            settings_json = home / ".claude" / "settings.json"
            if claude_json.is_file():
                return claude_json
            if settings_json.is_file():
                try:
                    sdata = json.loads(settings_json.read_text(encoding="utf-8"))
                    if isinstance(sdata, dict) and ("mcpServers" in sdata or "mcp_servers" in sdata):
                        return settings_json
                except Exception:
                    pass
            return claude_json
        return ws / ".mcp.json"
    if assistant == "kilo":
        if scope == "global":
            candidates = [
                home / ".config" / "kilo" / "kilo.jsonc",
                home / ".config" / "kilo" / "kilo.json",
                home / ".config" / "kilo" / "config.json",
                home / ".kilo" / "kilo.jsonc",
                home / ".kilo" / "kilo.json",
            ]
            # Prefer a file that already defines mcp/mcpServers
            for cand in candidates:
                if cand.is_file():
                    try:
                        d = parse_jsonc(cand.read_text(encoding="utf-8"))
                        if isinstance(d, dict) and ("mcp" in d or "mcpServers" in d):
                            return cand
                    except Exception:
                        return cand
            for cand in candidates:
                if cand.is_file():
                    return cand
            return home / ".config" / "kilo" / "kilo.json"
        for cand in (ws / ".kilo" / "kilo.jsonc", ws / ".kilo" / "kilo.json", ws / "kilo.jsonc", ws / "kilo.json"):
            if cand.is_file():
                return cand
        return ws / ".kilo" / "kilo.json"
    if assistant == "codex":
        return (home / ".codex" / "config.toml") if scope == "global" else (ws / ".codex" / "config.toml")
    raise ValueError(f"Unknown assistant: {assistant}")


def inspect_broker_mcp_client(
    assistant: str,
    scope: str = "global",
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    launcher_path: pathlib.Path | None = None,
    preferred_server_name: str | None = None,
) -> dict[str, Any]:
    """Inspect a client's config for the broker MCP registration and build a registration/repair plan item."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    l_path = launcher_path or get_launcher_path(h)
    expected_cmd = str(l_path)
    expected_args = ["mcp"]
    cfg_path = _resolve_client_broker_config_path(assistant, scope, ws, h)
    target_server_cfg = build_client_broker_mcp_config(assistant, l_path)

    found_name: str | None = None
    found_cfg: Any = None
    found_container: str | None = None
    parse_error: str | None = None
    raw_text = ""
    parsed_doc: dict[str, Any] = {}

    if cfg_path.is_file():
        try:
            raw_text = cfg_path.read_text(encoding="utf-8")
            if assistant == "codex":
                parsed_doc = tomllib.loads(raw_text) if raw_text.strip() else {}
                if not isinstance(parsed_doc, dict):
                    parse_error = "Top-level TOML is not a table"
                else:
                    mcp_tbl = parsed_doc.get("mcp_servers")
                    if isinstance(mcp_tbl, dict):
                        for k, v in mcp_tbl.items():
                            if _looks_like_broker_entry(k, v):
                                found_name, found_cfg, found_container = k, v, "mcp_servers"
                                break
                    if found_name is None:
                        mcp_sub = parsed_doc.get("mcp", {})
                        if isinstance(mcp_sub, dict) and isinstance(mcp_sub.get("servers"), dict):
                            for k, v in mcp_sub["servers"].items():
                                if _looks_like_broker_entry(k, v):
                                    found_name, found_cfg, found_container = k, v, "mcp.servers"
                                    break
            elif assistant == "claude":
                parsed_doc = json.loads(raw_text) if raw_text.strip() else {}
                if not isinstance(parsed_doc, dict):
                    parse_error = "Top-level JSON is not an object"
                else:
                    for container_key in ("mcpServers", "mcp_servers"):
                        sub = parsed_doc.get(container_key)
                        if isinstance(sub, dict):
                            for k, v in sub.items():
                                if _looks_like_broker_entry(k, v):
                                    found_name, found_cfg, found_container = k, v, container_key
                                    break
                        if found_name is not None:
                            break
            elif assistant == "kilo":
                parsed_doc = parse_jsonc(raw_text) if raw_text.strip() else {}
                if not isinstance(parsed_doc, dict):
                    parse_error = "Top-level JSON/JSONC is not an object"
                else:
                    for container_key in ("mcp", "mcpServers"):
                        sub = parsed_doc.get(container_key)
                        if isinstance(sub, dict):
                            for k, v in sub.items():
                                if _looks_like_broker_entry(k, v):
                                    found_name, found_cfg, found_container = k, v, container_key
                                    break
                        if found_name is not None:
                            break
        except Exception as exc:
            parse_error = str(exc)

    server_name = preferred_server_name or found_name or BROKER_MCP_SERVER_NAME
    reasons: list[str] = []
    cur_cmd: Any = None
    cur_args: list[str] = []

    if parse_error:
        state = "stale"
        reasons.append(f"unparseable config ({parse_error})")
    elif found_name is None:
        state = "missing"
        reasons.append("not registered")
    else:
        if not isinstance(found_cfg, dict):
            reasons.append("server entry is not an object/table")
        else:
            cur_cmd, cur_args, _ = normalize_mcp_config(found_cfg)
            all_tokens = ([cur_cmd] if cur_cmd else []) + list(cur_args)
            if any(_is_versioned_path(str(t)) for t in all_tokens if t):
                reasons.append(f"versioned path ({' '.join(str(t) for t in all_tokens if t)})")

            if assistant == "claude":
                if found_container != "mcpServers":
                    reasons.append(f"wrong top-level key '{found_container}' (expected 'mcpServers')")
                if _has_null_values(found_cfg):
                    reasons.append("contains null fields rejected by Claude Code")
                raw_c = found_cfg.get("command")
                raw_a = found_cfg.get("args")
                if not isinstance(raw_c, str) or raw_c != expected_cmd or raw_a != expected_args:
                    if not any("versioned path" in r for r in reasons):
                        reasons.append(f"wrong command ({raw_c!r} {raw_a!r}, expected {expected_cmd!r} {expected_args!r})")
                if found_cfg.get("type") not in (None, "stdio"):
                    reasons.append(f"unexpected transport type {found_cfg.get('type')!r} (expected 'stdio')")

            elif assistant == "codex":
                if found_container != "mcp_servers":
                    reasons.append(f"wrong TOML table '[{found_container}.{found_name}]' (expected '[mcp_servers.{found_name}]')")
                if _has_null_values(found_cfg):
                    reasons.append("contains null fields")
                raw_c = found_cfg.get("command")
                raw_a = found_cfg.get("args")
                if not isinstance(raw_c, str) or raw_c != expected_cmd or raw_a != expected_args:
                    if not any("versioned path" in r for r in reasons):
                        reasons.append(f"wrong command ({raw_c!r} {raw_a!r}, expected {expected_cmd!r} {expected_args!r})")
                approval = found_cfg.get("default_tools_approval_mode")
                if approval != "approve":
                    reasons.append(f"missing or wrong default_tools_approval_mode ({approval!r}, expected 'approve')")

            elif assistant == "kilo":
                if found_container != "mcp":
                    reasons.append(f"wrong top-level key '{found_container}' (Kilo uses 'mcp')")
                if _has_null_values(found_cfg):
                    reasons.append("contains null fields")
                if found_cfg.get("type") != "local":
                    reasons.append(f"missing or wrong type ({found_cfg.get('type')!r}, expected 'local')")
                raw_c = found_cfg.get("command")
                if raw_c != [expected_cmd, *expected_args]:
                    if not any("versioned path" in r for r in reasons):
                        reasons.append(f"wrong command ({raw_c!r}, expected {[expected_cmd, *expected_args]!r})")
                if not isinstance(found_cfg.get("environment"), dict):
                    reasons.append("missing 'environment' object in Kilo MCP config")
                if found_cfg.get("enabled") is False:
                    reasons.append("server is disabled (enabled: false)")

        state = "stale" if reasons else "registered"

    # Build new file content and plan item
    before_sha = compute_target_hash(cfg_path)
    if parse_error:
        plan_item: dict[str, Any] = {
            "action": "refuse",
            "assistant": assistant,
            "scope": scope,
            "server": server_name,
            "path": str(cfg_path),
            "command": expected_cmd,
            "args": expected_args,
            "server_config": target_server_cfg,
            "content": None,
            "reason": f"Refusing to modify unparseable {cfg_path.name}: {parse_error}",
            "current_state": state,
            "before_sha256": before_sha,
            "after_sha256": None,
        }
    elif state == "registered":
        plan_item = {
            "action": "noop",
            "assistant": assistant,
            "scope": scope,
            "server": server_name,
            "path": str(cfg_path),
            "command": expected_cmd,
            "args": expected_args,
            "server_config": target_server_cfg,
            "content": raw_text,
            "reason": f"Broker MCP '{server_name}' already registered in {assistant} ({scope})",
            "current_state": "registered",
            "before_sha256": before_sha,
            "after_sha256": before_sha,
        }
    else:
        if assistant == "claude":
            new_doc = _strip_nulls(json.loads(json.dumps(parsed_doc))) if parsed_doc else {}
            if "mcp_servers" in new_doc and isinstance(new_doc["mcp_servers"], dict) and found_name in new_doc["mcp_servers"]:
                del new_doc["mcp_servers"][found_name]
                if not new_doc["mcp_servers"]:
                    del new_doc["mcp_servers"]
            mcp_srvs = new_doc.setdefault("mcpServers", {})
            if found_name and found_name != server_name and found_name in mcp_srvs:
                del mcp_srvs[found_name]
            mcp_srvs[server_name] = target_server_cfg
            new_doc = _strip_nulls(new_doc)
            new_content = json.dumps(new_doc, indent=2) + "\n"
        elif assistant == "kilo":
            new_doc = _strip_nulls(json.loads(json.dumps(parsed_doc))) if parsed_doc else {"$schema": "https://app.kilo.ai/config.json"}
            if "mcpServers" in new_doc and isinstance(new_doc["mcpServers"], dict) and found_name in new_doc["mcpServers"]:
                del new_doc["mcpServers"][found_name]
                if not new_doc["mcpServers"]:
                    del new_doc["mcpServers"]
            mcp_map = new_doc.setdefault("mcp", {})
            if found_name and found_name != server_name and found_name in mcp_map:
                del mcp_map[found_name]
            mcp_map[server_name] = target_server_cfg
            new_doc = _strip_nulls(new_doc)
            new_content = json.dumps(new_doc, indent=2) + "\n"
        elif assistant == "codex":
            new_content = _upsert_codex_toml_server(
                raw_text,
                server_name,
                expected_cmd,
                expected_args,
                approval_mode="approve",
            )
        else:
            raise ValueError(f"Unknown assistant: {assistant}")

        after_sha = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        act = "replace" if state == "stale" else ("edit" if cfg_path.exists() else "create")
        if state == "stale":
            reason_str = f"Repair stale broker MCP '{server_name}' in {assistant} ({scope}): {'; '.join(reasons)}"
        else:
            reason_str = f"Register broker MCP '{server_name}' in {assistant} ({scope}) with {expected_cmd} mcp"

        plan_item = {
            "action": act,
            "assistant": assistant,
            "scope": scope,
            "server": server_name,
            "path": str(cfg_path),
            "command": expected_cmd,
            "args": expected_args,
            "server_config": target_server_cfg,
            "content": new_content,
            "reason": reason_str,
            "current_state": state,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
        }

    return {
        "assistant": assistant,
        "scope": scope,
        "state": state,
        "server_name": server_name,
        "config_path": str(cfg_path),
        "command": cur_cmd,
        "args": cur_args,
        "expected_command": expected_cmd,
        "expected_args": expected_args,
        "reasons": reasons,
        "server_config": target_server_cfg,
        "plan_item": plan_item,
    }


def inspect_broker_mcp_registrations(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
    scope: str = "global",
) -> dict[str, Any]:
    """Inspect Claude Code, Kilo, and Codex for broker MCP registration and return findings + repair plan."""
    h = home or get_home_dir()
    l_info = install_launcher(home=h, dry_run=True)
    l_path = pathlib.Path(l_info["path"])

    clients: dict[str, dict[str, Any]] = {}
    plan: list[dict[str, Any]] = []
    for asst in ("claude", "kilo", "codex"):
        c_info = inspect_broker_mcp_client(asst, scope=scope, workspace=workspace, home=h, launcher_path=l_path)
        clients[asst] = c_info
        plan.append(c_info["plan_item"])

    plan_hash = compute_plan_hash(plan)
    return {
        "launcher": {
            "path": str(l_path),
            "state": l_info["current_state"],
            "exists": l_path.exists() or l_path.is_symlink(),
            "plan": l_info["plan"],
            "plan_hash": l_info["plan_hash"],
        },
        "clients": clients,
        "plan": plan,
        "plan_hash": plan_hash,
        "hash": plan_hash,
        "expect_hash": plan_hash,
    }


def register_broker_mcp(
    assistants: list[str] | None = None,
    scope: str = "global",
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    server_name: str | None = None,
    dry_run: bool = False,
    apply: bool = False,
    expect_hash: str | None = None,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Preview or apply broker MCP registration/repair across Claude Code, Kilo, and Codex."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    broker_order = ("claude", "kilo", "codex")
    if not assistants or "all" in assistants or set(assistants) == set(broker_order):
        target_assistants = list(broker_order)
    else:
        target_assistants = list(assistants)
    if "codex" in target_assistants and scope != "global":
        raise ValueError("Codex does not support project-scoped MCP registration. Only global scope is supported.")

    expected = expect_hash if expect_hash is not None else expect_plan_hash
    effective_dry_run = bool(dry_run) or not (bool(apply) or expected is not None)
    l_path = get_launcher_path(h)

    def _build() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        p: list[dict[str, Any]] = []
        inspections: list[dict[str, Any]] = []
        for asst in target_assistants:
            c_info = inspect_broker_mcp_client(
                asst,
                scope=scope,
                workspace=ws,
                home=h,
                launcher_path=l_path,
                preferred_server_name=server_name,
            )
            inspections.append(c_info)
            p.append(c_info["plan_item"])
        return p, inspections

    plan, inspections = _build()
    plan_hash = compute_plan_hash(plan)

    refused = [it for it in plan if it["action"] == "refuse"]
    if refused:
        return {
            "ok": False,
            "error": refused[0]["reason"],
            "dry_run": effective_dry_run,
            "applied": 0,
            "server": server_name or BROKER_MCP_SERVER_NAME,
            "command": str(l_path),
            "args": ["mcp"],
            "updated_configs": [],
            "plan": plan,
            "plan_hash": plan_hash,
            "hash": plan_hash,
            "expect_hash": plan_hash,
        }

    if expected is not None and expected != plan_hash:
        return {
            "ok": False,
            "error": f"Plan hash mismatch: expected {expected}, but recomputed plan hash is {plan_hash}",
            "dry_run": effective_dry_run,
            "applied": 0,
            "server": server_name or BROKER_MCP_SERVER_NAME,
            "command": str(l_path),
            "args": ["mcp"],
            "updated_configs": [],
            "plan": plan,
            "plan_hash": plan_hash,
            "hash": plan_hash,
            "expect_hash": plan_hash,
        }

    if effective_dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "applied": 0,
            "server": server_name or BROKER_MCP_SERVER_NAME,
            "command": str(l_path),
            "args": ["mcp"],
            "updated_configs": [],
            "plan": plan,
            "plan_hash": plan_hash,
            "hash": plan_hash,
            "expect_hash": plan_hash,
        }

    with env_lock(h):
        plan, inspections = _build()
        plan_hash = compute_plan_hash(plan)
        refused = [it for it in plan if it["action"] == "refuse"]
        if refused:
            return {
                "ok": False,
                "error": refused[0]["reason"],
                "dry_run": False,
                "applied": 0,
                "server": server_name or BROKER_MCP_SERVER_NAME,
                "command": str(l_path),
                "args": ["mcp"],
                "updated_configs": [],
                "plan": plan,
                "plan_hash": plan_hash,
                "hash": plan_hash,
                "expect_hash": plan_hash,
            }
        if expected is not None and expected != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expected}, but recomputed plan hash is {plan_hash}",
                "dry_run": False,
                "applied": 0,
                "server": server_name or BROKER_MCP_SERVER_NAME,
                "command": str(l_path),
                "args": ["mcp"],
                "updated_configs": [],
                "plan": plan,
                "plan_hash": plan_hash,
                "hash": plan_hash,
                "expect_hash": plan_hash,
            }

        updated_configs: list[str] = []
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for item in plan:
            if item["action"] in ("create", "edit", "replace") and item.get("content") is not None:
                cfg_p = pathlib.Path(item["path"])
                cfg_p.parent.mkdir(parents=True, exist_ok=True)
                if cfg_p.exists():
                    # Back up a copy into centralized Doctor trash as well as .ai-orch.bak
                    bak_copy = cfg_p.with_name(cfg_p.name + ". doctor-tmp-bak")
                    shutil.copy2(cfg_p, bak_copy)
                    trash_path(
                        bak_copy,
                        assistant=item["assistant"],
                        scope=item["scope"],
                        kind="mcp",
                        reason=item["reason"],
                        workspace=ws,
                        home=h,
                        timestamp=ts,
                    )
                _atomic_write_with_backup(cfg_p, item["content"])
                updated_configs.append(str(cfg_p))

        return {
            "ok": True,
            "dry_run": False,
            "applied": len(updated_configs),
            "server": server_name or BROKER_MCP_SERVER_NAME,
            "command": str(l_path),
            "args": ["mcp"],
            "updated_configs": updated_configs,
            "plan": plan,
            "plan_hash": plan_hash,
            "hash": plan_hash,
            "expect_hash": plan_hash,
        }


def normalize_mcp_config(cfg: Any) -> tuple[str | None, list[str], dict[str, str]]:
    """Normalize MCP server configuration into (command, args, env)."""
    if not isinstance(cfg, dict):
        return None, [], {}
    cmd = cfg.get("command")
    args = cfg.get("args") or []
    if isinstance(cmd, list):
        if cmd:
            cmd_str = str(cmd[0])
            args_list = [str(x) for x in cmd[1:]] + [str(x) for x in args]
        else:
            cmd_str = ""
            args_list = [str(x) for x in args]
    elif cmd is not None:
        cmd_str = str(cmd)
        args_list = [str(x) for x in args]
    else:
        cmd_str = None
        args_list = [str(x) for x in args]
    env = cfg.get("env") or {}
    env_dict = {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}
    return cmd_str, args_list, env_dict


def are_mcp_configs_equivalent(cfg_a: Any, cfg_b: Any) -> bool:
    """Check if two MCP configurations are functionally equivalent."""
    if cfg_a == cfg_b:
        return True
    return normalize_mcp_config(cfg_a) == normalize_mcp_config(cfg_b)


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
                    is_identical = are_mcp_configs_equivalent(servers[sname]["config"], scfg)
                    servers[sname]["overrides"].append(servers[sname]["provenance"])
                    if "override_details" not in servers[sname]:
                        servers[sname]["override_details"] = []
                    servers[sname]["override_details"].append({
                        "provenance": servers[sname]["provenance"],
                        "config": servers[sname]["config"],
                        "identical": is_identical,
                    })
                    servers[sname]["provenance"] = str(cand)
                    servers[sname]["config"] = scfg
                    servers[sname]["command"] = scfg.get("command") if isinstance(scfg, dict) else None
                    servers[sname]["args"] = scfg.get("args") if isinstance(scfg, dict) else None
                    servers[sname]["identical"] = all(d.get("identical", False) for d in servers[sname]["override_details"])
                else:
                    servers[sname] = {
                        "name": sname,
                        "scope": scope,
                        "provenance": str(cand),
                        "overrides": [],
                        "override_details": [],
                        "config": scfg,
                        "command": scfg.get("command") if isinstance(scfg, dict) else None,
                        "args": scfg.get("args") if isinstance(scfg, dict) else None,
                        "identical": True,
                    }
        except Exception:
            continue

    return servers


def read_kilo_skill_paths(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
) -> list[pathlib.Path]:
    """Read custom skill paths declared in Kilo config files (skills.paths)."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    paths: list[pathlib.Path] = []

    cfg_dir = h / ".config" / "kilo"
    candidates = [
        cfg_dir / "config.json",
        cfg_dir / "kilo.json",
        cfg_dir / "kilo.jsonc",
        cfg_dir / "opencode.json",
        cfg_dir / "opencode.jsonc",
    ]
    if ws is not None:
        candidates.extend([
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
        ])

    for cand in candidates:
        if not cand.is_file():
            continue
        try:
            raw_text = cand.read_text(encoding="utf-8")
            data = parse_jsonc(raw_text)
            if not isinstance(data, dict):
                continue
            skills_cfg = data.get("skills", {})
            if not isinstance(skills_cfg, dict):
                continue
            sp_list = skills_cfg.get("paths", [])
            if not isinstance(sp_list, list):
                continue
            for item in sp_list:
                if isinstance(item, str):
                    if item.startswith("~/"):
                        p = h / item[2:]
                    elif pathlib.Path(item).is_absolute():
                        p = pathlib.Path(item)
                    elif ws is not None:
                        p = ws / item
                    else:
                        p = h / item
                    if p not in paths:
                        paths.append(p)
        except Exception:
            continue
    return paths


def kilo_skill_roots(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
    scope: str | None = None,
) -> list[tuple[pathlib.Path, str, str]]:
    """Return all roots Kilo reads for skills in ascending precedence order (lowest first, highest last).

    Returns list of tuples: (root_path, scope, root_tag)
    where root_tag is e.g. '~/.kilo/skills', '~/.claude/skills', '.kilo/skills'.
    """
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None

    disable_claude = (
        os.environ.get("KILO_DISABLE_CLAUDE_CODE_SKILLS") in ("1", "true", "yes")
        or os.environ.get("KILO_DISABLE_CLAUDE_CODE") in ("1", "true", "yes")
    )
    disable_external = os.environ.get("KILO_DISABLE_EXTERNAL_SKILLS") in ("1", "true", "yes")
    disable_project = os.environ.get("KILO_DISABLE_PROJECT_CONFIG") in ("1", "true", "yes")

    raw_roots: list[tuple[pathlib.Path, str, str]] = []

    # 1. Global external roots (lowest precedence)
    if not disable_external:
        raw_roots.append((h / ".agents" / "skills", "global", "~/.agents/skills"))
        if not disable_claude:
            raw_roots.append((h / ".claude" / "skills", "global", "~/.claude/skills"))

    # 2. Global config roots
    raw_roots.append((h / ".config" / "kilo" / "skills", "global", "~/.config/kilo/skills"))
    raw_roots.append((h / ".config" / "kilo" / "skill", "global", "~/.config/kilo/skill"))
    raw_roots.append((h / ".kilocode" / "skills", "global", "~/.kilocode/skills"))
    raw_roots.append((h / ".kilocode" / "skill", "global", "~/.kilocode/skill"))
    raw_roots.append((h / ".kilo" / "skills", "global", "~/.kilo/skills"))
    raw_roots.append((h / ".kilo" / "skill", "global", "~/.kilo/skill"))

    # 3. Project external roots (if workspace)
    if ws is not None and not disable_external:
        raw_roots.append((ws / ".agents" / "skills", "project", ".agents/skills"))
        if not disable_claude:
            raw_roots.append((ws / ".claude" / "skills", "project", ".claude/skills"))

    # 4. Project config roots (if workspace)
    if ws is not None and not disable_project:
        raw_roots.append((ws / ".kilocode" / "skills", "project", ".kilocode/skills"))
        raw_roots.append((ws / ".kilocode" / "skill", "project", ".kilocode/skill"))
        raw_roots.append((ws / ".kilo" / "skills", "project", ".kilo/skills"))
        raw_roots.append((ws / ".kilo" / "skill", "project", ".kilo/skill"))

    # 5. KILO_CONFIG_DIR override (if set)
    kilo_cfg_env = os.environ.get("KILO_CONFIG_DIR")
    if kilo_cfg_env:
        cfg_d = pathlib.Path(kilo_cfg_env).expanduser()
        raw_roots.append((cfg_d / "skills", "global", f"{cfg_d.name}/skills"))
        raw_roots.append((cfg_d / "skill", "global", f"{cfg_d.name}/skill"))

    # 6. Custom skills.paths from merged Kilo config
    custom_paths = read_kilo_skill_paths(h, ws)
    for p in custom_paths:
        p_scope = "project" if ws is not None and (p == ws or p.is_relative_to(ws)) else "global"
        tag = f"~/{p.relative_to(h)}" if p.is_relative_to(h) else (f"./{p.relative_to(ws)}" if ws and p.is_relative_to(ws) else str(p))
        raw_roots.append((p, p_scope, tag))

    # Filter by scope if requested
    if scope == "global":
        filtered = [r for r in raw_roots if r[1] == "global"]
    elif scope == "project":
        filtered = [r for r in raw_roots if r[1] == "project"]
    else:
        filtered = raw_roots

    # Deduplicate while preserving order (last occurrence wins in precedence)
    seen_paths: set[pathlib.Path] = set()
    deduped_reversed: list[tuple[pathlib.Path, str, str]] = []
    for item in reversed(filtered):
        p_resolved = item[0].resolve()
        if p_resolved not in seen_paths:
            seen_paths.add(p_resolved)
            deduped_reversed.append(item)
    return list(reversed(deduped_reversed))


def kilo_agent_roots(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
    scope: str | None = None,
) -> list[tuple[pathlib.Path, str, str]]:
    """Return all roots Kilo reads for agents in ascending precedence order (lowest first, highest last)."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None

    disable_claude = (
        os.environ.get("KILO_DISABLE_CLAUDE_CODE") in ("1", "true", "yes")
    )
    disable_external = os.environ.get("KILO_DISABLE_EXTERNAL_AGENTS") in ("1", "true", "yes")
    disable_project = os.environ.get("KILO_DISABLE_PROJECT_CONFIG") in ("1", "true", "yes")

    raw_roots: list[tuple[pathlib.Path, str, str]] = []

    # 1. Global external roots
    if not disable_external and not disable_claude:
        raw_roots.append((h / ".claude" / "agents", "global", "~/.claude/agents"))

    # 2. Global config roots
    raw_roots.append((h / ".config" / "kilo" / "agents", "global", "~/.config/kilo/agents"))
    raw_roots.append((h / ".config" / "kilo" / "agent", "global", "~/.config/kilo/agent"))
    raw_roots.append((h / ".kilocode" / "agents", "global", "~/.kilocode/agents"))
    raw_roots.append((h / ".kilocode" / "agent", "global", "~/.kilocode/agent"))
    raw_roots.append((h / ".kilo" / "agents", "global", "~/.kilo/agents"))
    raw_roots.append((h / ".kilo" / "agent", "global", "~/.kilo/agent"))

    # 3. Project external roots
    if ws is not None and not disable_external and not disable_claude:
        raw_roots.append((ws / ".claude" / "agents", "project", ".claude/agents"))

    # 4. Project config roots
    if ws is not None and not disable_project:
        raw_roots.append((ws / ".kilocode" / "agents", "project", ".kilocode/agents"))
        raw_roots.append((ws / ".kilocode" / "agent", "project", ".kilocode/agent"))
        raw_roots.append((ws / ".kilo" / "agents", "project", ".kilo/agents"))
        raw_roots.append((ws / ".kilo" / "agent", "project", ".kilo/agent"))

    if scope == "global":
        filtered = [r for r in raw_roots if r[1] == "global"]
    elif scope == "project":
        filtered = [r for r in raw_roots if r[1] == "project"]
    else:
        filtered = raw_roots

    seen_paths: set[pathlib.Path] = set()
    deduped_reversed: list[tuple[pathlib.Path, str, str]] = []
    for item in reversed(filtered):
        p_resolved = item[0].resolve()
        if p_resolved not in seen_paths:
            seen_paths.add(p_resolved)
            deduped_reversed.append(item)
    return list(reversed(deduped_reversed))


def compute_kilo_effective(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute Kilo effective skills across all roots Kilo reads, resolving shadowing by precedence."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    roots = kilo_skill_roots(h, ws, scope=None)

    skills_by_name: dict[str, list[dict[str, Any]]] = {}

    for rdir, rscope, rtag in roots:
        if not rdir.is_dir():
            continue
        for child in sorted(rdir.iterdir()):
            if child.name.startswith("."):
                continue
            if not (child.is_dir() or child.is_symlink()):
                continue
            if not (child / "SKILL.md").is_file():
                continue
            sname = child.name
            try:
                fm, _ = parse_frontmatter_and_body((child / "SKILL.md").read_text(encoding="utf-8"))
                if fm and isinstance(fm, dict) and fm.get("name"):
                    sname = str(fm["name"])
            except Exception:
                pass

            skills_by_name.setdefault(sname, []).append({
                "path": child,
                "root_dir": rdir,
                "root_scope": rscope,
                "root_tag": rtag,
            })

    effective: dict[str, dict[str, Any]] = {}
    for sname in sorted(skills_by_name.keys()):
        locs = skills_by_name[sname]
        winner = locs[-1]
        shadowed = locs[:-1]
        effective[sname] = {
            "winning": str(winner["path"]),
            "winning_path": str(winner["path"]),
            "path": str(winner["path"]),
            "shadowed": [str(loc["path"]) for loc in shadowed],
            "shadowed_paths": [str(loc["path"]) for loc in shadowed],
        }
    return effective


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


def discover_claude_plugin_agents(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
) -> list[dict[str, Any]]:
    """Inspect ~/.claude/plugins/installed_plugins.json and discover installed plugin agents.
    Returns list of dicts with keys:
        plugin_id: str
        scope: str
        project_path: str | None
        agent_name: str
        path: str (path to agent markdown file)
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

            agents_dir = ip / "agents"
            if agents_dir.is_dir():
                for child in sorted(agents_dir.glob("*.md")):
                    if child.name.startswith(".") or not child.is_file():
                        continue
                    results.append({
                        "plugin_id": plugin_id,
                        "scope": iscope,
                        "project_path": project_path,
                        "agent_name": child.name,
                        "path": str(child),
                        "origin": f"plugin:{plugin_id}",
                    })
    return results


def hash_plugin_directory(dir_path: pathlib.Path) -> str:
    """Deterministic SHA-256 over files in a plugin directory (ignoring volatile files/dirs, but including .claude-plugin/plugin.json)."""
    h = hashlib.sha256()
    if not dir_path.is_dir():
        return ""
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = sorted(
            d for d in dirs
            if (not d.startswith(".") or d == ".claude-plugin")
            and d not in ("__pycache__", ".in_use", ".git", ".pytest_cache", ".venv", ".mypy_cache")
        )
        for fname in sorted(files):
            if (fname.startswith(".") and fname != ".claude-plugin") or fname.endswith(".pyc") or fname in ("index.json", ".ai-orch-source.json", ".DS_Store"):
                continue
            fpath = pathlib.Path(root) / fname
            try:
                rel = fpath.relative_to(dir_path).as_posix()
                h.update(rel.encode("utf-8") + b"\0")
                h.update(fpath.read_bytes() + b"\0")
            except Exception:
                pass
    return h.hexdigest()[:16]


def read_plugin_json_version(plugin_dir: pathlib.Path) -> str | None:
    """Read version string from .claude-plugin/plugin.json or plugin.json in plugin_dir."""
    for cand in [plugin_dir / ".claude-plugin" / "plugin.json", plugin_dir / "plugin.json"]:
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "version" in data and data["version"] is not None:
                    return str(data["version"])
            except Exception:
                pass
    return None


def find_marketplace_clone(marketplace_name: str, home: pathlib.Path | None = None) -> pathlib.Path | None:
    """Locate the marketplace clone or source repo for a marketplace."""
    if not marketplace_name:
        return None
    h = home or get_home_dir()
    clone_cand = h / ".claude" / "plugins" / "marketplaces" / marketplace_name
    if clone_cand.is_dir():
        return clone_cand

    if home is not None:
        cached = get_repos_cache_dir(home) / marketplace_name
        if cached.is_dir():
            return cached
    else:
        sr = resolve_source_repo(marketplace_name, None)
        if sr and sr.is_dir():
            return sr
    return None


def find_plugin_source_dir(clone_dir: pathlib.Path, plugin_name: str) -> pathlib.Path | None:
    """Find the directory containing the plugin within a marketplace clone / source repo."""
    if not clone_dir or not clone_dir.is_dir():
        return None

    # 1. Try reading marketplace.json
    for mjson in [clone_dir / ".claude-plugin" / "marketplace.json", clone_dir / "marketplace.json"]:
        if mjson.is_file():
            try:
                mdata = json.loads(mjson.read_text(encoding="utf-8"))
                for p in mdata.get("plugins", []):
                    if isinstance(p, dict) and p.get("name") == plugin_name:
                        src = p.get("source")
                        if isinstance(src, str):
                            rel = src.lstrip("./") if src.startswith("./") else src
                            cand = clone_dir / rel
                            if cand.is_dir():
                                return cand
                        elif isinstance(src, dict) and src.get("path"):
                            cand = clone_dir / src.get("path")
                            if cand.is_dir():
                                return cand
            except Exception:
                pass

    # 2. Standard subdirectory layouts
    for cand in [clone_dir / "plugins" / plugin_name, clone_dir / plugin_name]:
        if cand.is_dir():
            return cand

    # 3. Check if clone_dir itself is the plugin root
    if (clone_dir / ".claude-plugin" / "plugin.json").is_file() or (clone_dir / "plugin.json").is_file() or (clone_dir / "SKILL.md").is_file():
        return clone_dir

    return None


def compute_plugin_commit_distance(
    repo_dir: pathlib.Path,
    plugin_dir: pathlib.Path,
    git_commit_sha: str | None,
    marketplace_name: str = "",
    home: pathlib.Path | None = None,
) -> int | str:
    """Compute commit distance: number of commits touching the plugin dir after git_commit_sha.
    Degrades to 'unknown' on any git failure.
    """
    if not git_commit_sha:
        return "unknown"
    sha = str(git_commit_sha).strip()
    if not sha or not all(c in "0123456789abcdefABCDEF" for c in sha):
        return "unknown"

    try:
        rel_path = plugin_dir.relative_to(repo_dir).as_posix()
    except ValueError:
        rel_path = "."

    repos_to_check: list[tuple[pathlib.Path, str]] = [(repo_dir, rel_path)]

    if marketplace_name:
        sr = resolve_source_repo(marketplace_name, home)
        if sr and sr.is_dir() and sr != repo_dir and (sr / ".git").exists():
            try:
                rel_sr = plugin_dir.relative_to(sr).as_posix()
            except ValueError:
                rel_sr = f"plugins/{plugin_dir.name}" if (sr / "plugins" / plugin_dir.name).is_dir() else (plugin_dir.name if (sr / plugin_dir.name).is_dir() else ".")
            repos_to_check.append((sr, rel_sr))

    for r_dir, r_rel in repos_to_check:
        try:
            chk = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
                cwd=r_dir,
                timeout=10,
                capture_output=True,
                text=True,
            )
            if chk.returncode == 0:
                pargs = ["--", r_rel] if r_rel != "." else []
                r = subprocess.run(
                    ["git", "rev-list", "--count", f"{sha}..HEAD"] + pargs,
                    cwd=r_dir,
                    timeout=10,
                    capture_output=True,
                    text=True,
                )
                if r.returncode == 0:
                    try:
                        return int(r.stdout.strip())
                    except ValueError:
                        pass
        except Exception:
            pass

    return "unknown"


def discover_stale_claude_plugins(
    home: pathlib.Path | None = None,
    workspace: pathlib.Path | None = None,
    scope: str = "global",
) -> list[dict[str, Any]]:
    """Inspect enabled Claude plugins and report those that are stale vs their marketplace clone / source repo."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None

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

    global_enabled, project_enabled = load_claude_plugin_settings(h, ws)
    enabled_map = global_enabled if scope == "global" else project_enabled

    stale_list: list[dict[str, Any]] = []

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

            if scope == "global":
                if iscope != "user":
                    continue
            elif scope == "project":
                if ws is None:
                    continue
                if iscope == "user":
                    pass
                elif iscope in ("project", "local"):
                    if not project_path:
                        continue
                    try:
                        if pathlib.Path(project_path).resolve() != ws:
                            continue
                    except Exception:
                        continue
                else:
                    continue

            if not enabled_map.get(plugin_id, True):
                continue

            ip_str = install.get("installPath")
            if not ip_str:
                continue
            ip = pathlib.Path(ip_str).expanduser()
            if not ip.is_dir():
                continue

            cached_ver = install.get("version")
            if not cached_ver:
                cached_ver = read_plugin_json_version(ip)

            sha = install.get("gitCommitSha")

            if "@" in plugin_id:
                pname, mname = plugin_id.split("@", 1)
            else:
                pname, mname = plugin_id, ""

            clone = find_marketplace_clone(mname, home)
            if not clone or not clone.is_dir():
                continue

            s_pdir = find_plugin_source_dir(clone, pname)
            if not s_pdir or not s_pdir.is_dir():
                continue

            s_ver = read_plugin_json_version(s_pdir)
            eq = (cached_ver is not None and s_ver is not None and str(cached_ver) == str(s_ver))

            dist = compute_plugin_commit_distance(clone, s_pdir, sha, mname, home)
            differs = (hash_plugin_directory(ip) != hash_plugin_directory(s_pdir))

            is_stale = False
            if isinstance(dist, int):
                if dist > 0:
                    is_stale = True
                elif not eq:
                    is_stale = True
                elif differs:
                    is_stale = True
            else:
                if differs or not eq:
                    is_stale = True

            if is_stale:
                if eq:
                    mkt = mname or "marketplace"
                    adv = (
                        f"bump the plugin version in its repo, push, then "
                        f"`claude plugin marketplace update {mkt}` and `claude plugin update {plugin_id}`"
                    )
                else:
                    adv = f"run `claude plugin update {plugin_id}`"

                stale_list.append({
                    "plugin_id": plugin_id,
                    "scope": iscope,
                    "cached_version": str(cached_ver) if cached_ver is not None else None,
                    "source_version": str(s_ver) if s_ver is not None else None,
                    "versions_equal": eq,
                    "commit_distance": dist,
                    "content_differs": differs,
                    "advice": adv,
                    "install_path": str(ip),
                    "source_path": str(s_pdir),
                })

    return stale_list


def is_project_entry(entry: dict[str, Any], ws: pathlib.Path | None) -> bool:
    """Return True if the entry belongs to project workspace scope."""
    if ws is None:
        return False
    if entry.get("scope") in ("project", "local"):
        return True
    ep = entry.get("path")
    if ep:
        p = pathlib.Path(ep)
        try:
            if p.is_relative_to(ws):
                return True
        except (ValueError, Exception):
            pass
        try:
            if p.resolve().is_relative_to(ws.resolve()):
                return True
        except (ValueError, Exception):
            pass
    return False


def plan_for_conflict(
    sc: dict[str, Any],
    assistant: str,
    scope: str,
    policy: dict[str, str],
    catalog: dict[str, Any],
    seen_paths: set[str] | None = None,
    home: pathlib.Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute resolution plan and executable actions for a single conflict finding.

    Returns:
        (plan_items, conflict_items)
        plan_items: list of plan dicts (action: trash, advise, etc.)
        conflict_items: list of executable action dicts (consumed by trash_path during apply)
    """
    h = home or get_home_dir()
    seen = seen_paths if seen_paths is not None else set()
    p_items: list[dict[str, Any]] = []
    c_items: list[dict[str, Any]] = []
    kind = sc.get("kind")
    entries = sc.get("entries", [])

    if kind == "trigger-conflict":
        names = sc.get("names", [])
        gb_pairs = get_generic_bound_pairs(h)
        matched_pair = next(((g, b) for g, b in gb_pairs if set(names) == {g, b}), None)
        if matched_pair:
            generic_name, bound_name = matched_pair
        else:
            generic_name = names[0] if names else "orchestration-workflow"
            bound_name = names[1] if len(names) > 1 else "kilo-mcp-orchestrator"

        keep_target = policy.get(assistant, "generic" if assistant == "kilo" else "bound")
        if keep_target == "generic":
            to_remove_name = bound_name
            to_keep_name = generic_name
        else:
            to_remove_name = generic_name
            to_keep_name = bound_name

        to_remove_entries = [e for e in entries if e.get("name") == to_remove_name]
        standalone_to_remove = [e for e in to_remove_entries if not e.get("origin", "").startswith("plugin:")]
        if assistant == "kilo":
            standalone_to_remove = [
                e for e in standalone_to_remove
                if not (".claude" in e.get("origin", "") or ".agents" in e.get("origin", ""))
            ]
        plugin_to_remove = [e for e in to_remove_entries if e.get("origin", "").startswith("plugin:")]

        if standalone_to_remove:
            for e in standalone_to_remove:
                e_path = e.get("path")
                if not e_path or e_path in seen:
                    continue
                seen.add(e_path)
                target_path = pathlib.Path(e_path)
                p_item = {
                    "action": "trash",
                    "path": str(target_path),
                    "reason": f"Resolve conflict in {assistant} ({scope}): keep '{to_keep_name}', trash '{to_remove_name}' per policy",
                    "current_state": "conflict",
                    "before_sha256": compute_target_hash(target_path),
                    "after_sha256": None,
                }
                p_items.append(p_item)
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
                if not e_path or e_path in seen:
                    continue
                seen.add(e_path)
                origin = e.get("origin", "")
                plugin_id = origin.split("plugin:", 1)[1] if origin.startswith("plugin:") else ""
                target_path = pathlib.Path(e_path)

                claude_plugins = discover_claude_plugin_skills(h)
                plugin_skills = sorted(set(ps["skill_name"] for ps in claude_plugins if ps["plugin_id"] == plugin_id))
                other_skills = [s for s in plugin_skills if s != to_remove_name]

                if plugin_id == "architect-side@ai-orchestration":
                    reason = (
                        "architect-side@ai-orchestration provides 5 essential orchestration skills "
                        "(task-pipeline, task-spec-authoring, task-worktree-ops, conflict-resolver, "
                        "orchestration-metrics); keep both plugins with reciprocal Precedence or acknowledge finding"
                    )
                elif other_skills:
                    skills_str = ", ".join(other_skills)
                    reason = (
                        f"{plugin_id} provides {len(other_skills)} other skills ({skills_str}); "
                        f"keep both plugins with reciprocal Precedence or acknowledge finding"
                    )
                else:
                    reason = f"disable plugin {plugin_id} in ~/.claude/settings.json (enabledPlugins) or uninstall it"
                p_item = {
                    "action": "advise",
                    "path": str(target_path),
                    "reason": reason,
                    "current_state": "conflict",
                    "before_sha256": compute_target_hash(target_path),
                    "after_sha256": None,
                }
                p_items.append(p_item)

    elif kind == "duplicate-name":
        standalone_entries = [e for e in entries if not e.get("origin", "").startswith("plugin:")]
        plugin_entries = [e for e in entries if e.get("origin", "").startswith("plugin:")]

        skill_name = sc.get("names", [""])[0] or (
            standalone_entries[0].get("name", "") if standalone_entries else (
                plugin_entries[0].get("name", "") if plugin_entries else ""
            )
        )

        qid = OPEN_DUPLICATE_QUESTIONS.get(skill_name)
        if qid:
            for se in standalone_entries:
                sp_str = se.get("path")
                if not sp_str or sp_str in seen:
                    continue
                seen.add(sp_str)
                sp = pathlib.Path(sp_str)
                s_hash = compute_target_hash(sp)

                diff_summary = ""
                if plugin_entries and plugin_entries[0].get("path"):
                    diff_info = compare_skill_dirs(sp, pathlib.Path(plugin_entries[0]["path"]))
                    diff_summary = format_diff_summary(diff_info)
                elif len(standalone_entries) >= 2:
                    other_sp = next((pathlib.Path(o["path"]) for o in standalone_entries if o.get("path") != sp_str), None)
                    if other_sp:
                        diff_info = compare_skill_dirs(sp, other_sp)
                        diff_summary = format_diff_summary(diff_info)

                reason = f"canonical choice for '{skill_name}' is open ({qid}): review question before resolving"
                p_item = {
                    "action": "advise",
                    "path": str(sp),
                    "reason": reason,
                    "current_state": "conflict",
                    "before_sha256": s_hash,
                    "after_sha256": None,
                    "diff_summary": diff_summary,
                }
                p_items.append(p_item)

        elif standalone_entries and plugin_entries:
            plugin_hashes: dict[str, str] = {}
            for pe in plugin_entries:
                pp = pe.get("path")
                if pp:
                    ph = compute_target_hash(pathlib.Path(pp))
                    if ph:
                        plugin_hashes[pp] = ph

            cat_entries = [
                entry for entry in catalog.values()
                if entry.get("name") == skill_name
            ]
            cat_hashes = [entry["hash"] for entry in cat_entries if entry.get("hash")]

            stale_plugins = discover_stale_claude_plugins(home=h, scope=scope)
            stale_plugin_ids = {sp["plugin_id"] for sp in stale_plugins}

            for se in standalone_entries:
                sp_str = se.get("path")
                if not sp_str or sp_str in seen:
                    continue
                seen.add(sp_str)
                sp = pathlib.Path(sp_str)
                s_hash = compute_target_hash(sp)

                matching_plugin = next(
                    (pe for pe in plugin_entries if plugin_hashes.get(pe.get("path")) == s_hash),
                    None,
                )

                is_up_to_date = se.get("state") == "up-to-date"
                is_byte_identical = matching_plugin is not None
                matches_cat = bool(s_hash and s_hash in cat_hashes)

                # Normalized equality against active plugin copies
                matching_norm_plugin = next(
                    (pe for pe in plugin_entries if pe.get("path") and compare_skill_dirs(sp, pathlib.Path(pe["path"]))["equivalent"]),
                    None,
                )
                is_norm_identical_plugin = matching_norm_plugin is not None

                # Normalized equality against current catalog source
                matching_norm_cat = next(
                    (ce for ce in cat_entries if ce.get("path") and compare_skill_dirs(sp, pathlib.Path(ce["path"]))["equivalent"]),
                    None,
                )
                is_norm_identical_cat = matching_norm_cat is not None

                target_plugin = matching_plugin or matching_norm_plugin or plugin_entries[0]
                target_plugin_id = target_plugin.get("origin", "").split("plugin:", 1)[1] if target_plugin.get("origin", "").startswith("plugin:") else target_plugin.get("origin", "")
                is_target_plugin_stale = target_plugin_id in stale_plugin_ids

                # Check cached plugin versions
                matching_cached_path, is_cached_match = find_matching_cached_plugin_skill(
                    skill_name, sp, plugin_id=target_plugin_id, home=h
                )

                # Check marketplace clone
                matching_mkt_path, is_mkt_match = find_matching_marketplace_plugin_skill(
                    skill_name, sp, plugin_id=target_plugin_id, home=h
                )

                # Check git history of source repos
                cand_git_entries = list(cat_entries)
                for pe in plugin_entries:
                    pp = pe.get("path")
                    if pp and pathlib.Path(pp).is_dir():
                        cand_git_entries.append({
                            "name": skill_name,
                            "repo": pe.get("origin", ""),
                            "plugin": pe.get("origin", ""),
                            "path": pp,
                            "hash": compute_target_hash(pathlib.Path(pp)),
                        })
                hist_match = find_historical_skill_match(s_hash, cand_git_entries, home=h)
                is_historical_match = hist_match is not None

                is_older_copy = (is_cached_match or is_historical_match or is_mkt_match) and not is_target_plugin_stale
                is_reserialized_copy = is_norm_identical_plugin or (is_norm_identical_cat and not is_target_plugin_stale)

                if is_up_to_date or is_byte_identical or matches_cat or is_reserialized_copy or is_older_copy:
                    p_item = {
                        "action": "trash",
                        "path": str(sp),
                        "reason": f"duplicate of plugin {target_plugin_id}; plugin copy kept",
                        "current_state": "conflict",
                        "before_sha256": s_hash,
                        "after_sha256": None,
                    }
                    p_items.append(p_item)
                    c_items.append({
                        "assistant": assistant,
                        "scope": se.get("scope", scope),
                        "removed": se.get("name", skill_name),
                        "kept": f"plugin:{target_plugin_id}",
                        "path": sp,
                        "reason": p_item["reason"],
                    })
                else:
                    target_plugin_path = pathlib.Path(target_plugin.get("path")) if target_plugin.get("path") else None
                    if target_plugin_path and target_plugin_path.exists():
                        diff_info = compare_skill_dirs(sp, target_plugin_path)
                    elif cat_entries and pathlib.Path(cat_entries[0]["path"]).exists():
                        diff_info = compare_skill_dirs(sp, pathlib.Path(cat_entries[0]["path"]))
                    else:
                        diff_info = {"diff_files": ["SKILL.md"], "changed_fm_keys": [], "body_differs": True}
                    diff_summary = format_diff_summary(diff_info)

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
                        "diff_summary": diff_summary,
                    }
                    p_items.append(p_item)

        elif len(plugin_entries) >= 2 and not standalone_entries:
            p_paths = [pe.get("path") for pe in plugin_entries if pe.get("path")]
            if not any(pp in seen for pp in p_paths):
                for pp in p_paths:
                    seen.add(pp)
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
                p_items.append(p_item)

        elif len(standalone_entries) >= 2 and not plugin_entries:
            skill_name = sc.get("names", [""])[0] or (standalone_entries[0].get("name", ""))
            cat_entries = [entry for entry in catalog.values() if entry.get("name") == skill_name]
            cat_hashes = [e["hash"] for e in cat_entries if e.get("hash")]

            qid = OPEN_DUPLICATE_QUESTIONS.get(skill_name)
            if qid:
                for se in standalone_entries:
                    sp_str = se.get("path")
                    if not sp_str or sp_str in seen:
                        continue
                    seen.add(sp_str)
                    sp = pathlib.Path(sp_str)
                    s_hash = compute_target_hash(sp)
                    other_sp = next((pathlib.Path(o["path"]) for o in standalone_entries if o.get("path") != sp_str), None)
                    diff_summary = ""
                    if other_sp:
                        diff_info = compare_skill_dirs(sp, other_sp)
                        diff_summary = format_diff_summary(diff_info)
                    reason = f"canonical choice for '{skill_name}' is open ({qid}): review question before resolving"
                    p_item = {
                        "action": "advise",
                        "path": str(sp),
                        "reason": reason,
                        "current_state": "conflict",
                        "before_sha256": s_hash,
                        "after_sha256": None,
                        "diff_summary": diff_summary,
                    }
                    p_items.append(p_item)
            else:
                entry_info: list[dict[str, Any]] = []
                for se in standalone_entries:
                    sp_str = se.get("path")
                    if not sp_str:
                        continue
                    sp = pathlib.Path(sp_str)
                    s_hash = compute_target_hash(sp)
                    s_state = se.get("state")
                    is_norm_cat = any(compare_skill_dirs(sp, pathlib.Path(ce["path"]))["equivalent"] for ce in cat_entries if ce.get("path"))
                    is_current = s_state in ("up-to-date", "up-to-date-legacy") or bool(s_hash and s_hash in cat_hashes) or is_norm_cat
                    is_outdated_legacy = s_state == "outdated-legacy" or (find_historical_skill_match(s_hash, cat_entries, home=h) is not None)
                    entry_info.append({
                        "entry": se,
                        "path": sp,
                        "path_str": sp_str,
                        "hash": s_hash,
                        "state": s_state,
                        "is_current": is_current,
                        "is_outdated_legacy": is_outdated_legacy,
                        "scope": se.get("scope", scope),
                    })

                current_items = [item for item in entry_info if item["is_current"]]
                other_items = [item for item in entry_info if not item["is_current"]]

                all_identical = (
                    len(entry_info) >= 2
                    and (
                        len(set(it["hash"] for it in entry_info if it["hash"])) == 1
                        or all(skill_equivalent(entry_info[0]["path"], it["path"]) for it in entry_info[1:])
                    )
                )
                has_current_and_legacy_or_identical = (
                    len(current_items) >= 1
                    and all(
                        item["is_outdated_legacy"]
                        or (item["hash"] and item["hash"] in cat_hashes)
                        or any(item["hash"] == c["hash"] or skill_equivalent(item["path"], c["path"]) for c in current_items)
                        for item in other_items
                    )
                )

                has_project_and_global = any(it["scope"] == "project" for it in entry_info) and any(it["scope"] == "global" for it in entry_info)
                is_fixable_p2d = (has_current_and_legacy_or_identical or all_identical) and has_project_and_global

                if is_fixable_p2d:
                    keep_scope = policy.get("keep_scope", "global")
                    if len(current_items) == 1:
                        keeper = current_items[0]
                        to_trash = other_items
                    elif len(current_items) > 1:
                        if keep_scope == "project":
                            keeper = next((it for it in current_items if it["scope"] == "project"), current_items[0])
                        else:
                            keeper = next((it for it in current_items if it["scope"] == "global"), current_items[0])
                        to_trash = [it for it in current_items if it is not keeper] + other_items
                    else:
                        if keep_scope == "project":
                            keeper = next((it for it in entry_info if it["scope"] == "project"), entry_info[0])
                        else:
                            keeper = next((it for it in entry_info if it["scope"] == "global"), entry_info[0])
                        to_trash = [it for it in entry_info if it is not keeper]

                    for item in to_trash:
                        if item["path_str"] not in seen:
                            seen.add(item["path_str"])
                            keep_desc = "current" if keeper in current_items else "identical"
                            p_item = {
                                "action": "trash",
                                "path": item["path_str"],
                                "reason": f"duplicate standalone skill '{skill_name}': keep {keep_desc} copy in {keeper['scope']}, trash {item['scope']} copy",
                                "current_state": "conflict",
                                "before_sha256": item["hash"],
                                "after_sha256": None,
                            }
                            p_items.append(p_item)
                            c_items.append({
                                "action": "trash",
                                "assistant": assistant,
                                "scope": item["scope"],
                                "removed": skill_name,
                                "kept": f"{keeper['scope']} copy",
                                "path": item["path"],
                                "reason": p_item["reason"],
                            })
                else:
                    target_item = (
                        next((it for it in entry_info if ".kilo" in it.get("entry", {}).get("origin", "")), entry_info[0])
                        if assistant == "kilo" and entry_info else (entry_info[0] if entry_info else None)
                    )
                    target_path_str = target_item["path_str"] if target_item else ""
                    if target_path_str:
                        target_path = pathlib.Path(target_path_str)
                        diff_info = compare_skill_dirs(entry_info[0]["path"], entry_info[1]["path"]) if len(entry_info) >= 2 else {"diff_files": ["SKILL.md"], "changed_fm_keys": [], "body_differs": True}
                        diff_summary = format_diff_summary(diff_info)
                        if has_project_and_global:
                            reason = f"duplicate standalone skill '{skill_name}' across scopes with differing contents: review and remove one manually"
                        else:
                            origins_list = sorted({e.get("origin", "") for e in entries if e.get("origin")})
                            origins_display = ", ".join(origins_list) if origins_list else "roots"
                            reason = f"duplicate standalone skill '{skill_name}' across origins ({origins_display}): review and remove one manually"
                        p_item = {
                            "action": "advise",
                            "path": target_path_str,
                            "reason": reason,
                            "current_state": "conflict",
                            "before_sha256": compute_target_hash(target_path),
                            "after_sha256": None,
                            "diff_summary": diff_summary,
                        }
                        p_items.append(p_item)

    elif kind == "outdated-legacy":
        entry = entries[0] if entries else {}
        sp_str = entry.get("path")
        if sp_str and sp_str not in seen:
            seen.add(sp_str)
            target_path = pathlib.Path(sp_str)
            sname = sc.get("names", [""])[0] or target_path.name
            cat_entry = next((e for e in catalog.values() if e.get("name") == sname), None)
            src_dir = pathlib.Path(cat_entry["path"]) if cat_entry else None
            repo_name = cat_entry.get("repo", "catalog") if cat_entry else "catalog"
            plugin_name = cat_entry.get("plugin", "") if cat_entry else ""
            cat_hash = cat_entry.get("hash") if cat_entry else None
            inst_hash = compute_target_hash(target_path)
            p_item = {
                "action": "update",
                "path": sp_str,
                "reason": f"Update outdated legacy skill '{sname}' to current version from {repo_name}",
                "current_state": "outdated-legacy",
                "before_sha256": inst_hash,
                "after_sha256": cat_hash,
            }
            p_items.append(p_item)
            if src_dir and src_dir.is_dir():
                c_items.append({
                    "action": "update",
                    "assistant": assistant,
                    "scope": entry.get("scope", scope),
                    "skill": sname,
                    "repo": repo_name,
                    "plugin": plugin_name,
                    "src": src_dir,
                    "path": target_path,
                    "reason": p_item["reason"],
                })

    elif kind == "up-to-date-legacy":
        entry = entries[0] if entries else {}
        sp_str = entry.get("path")
        if sp_str and sp_str not in seen:
            seen.add(sp_str)
            target_path = pathlib.Path(sp_str)
            sname = sc.get("names", [""])[0] or target_path.name
            cat_entry = next((e for e in catalog.values() if e.get("name") == sname), None)
            src_dir = pathlib.Path(cat_entry["path"]) if cat_entry else None
            repo_name = cat_entry.get("repo", "catalog") if cat_entry else "catalog"
            plugin_name = cat_entry.get("plugin", "") if cat_entry else ""
            cat_hash = cat_entry.get("hash") if cat_entry else None
            inst_hash = compute_target_hash(target_path)
            p_item = {
                "action": "adopt",
                "path": sp_str,
                "reason": f"Adopt up-to-date legacy skill '{sname}' matching current source and write receipt",
                "current_state": "up-to-date-legacy",
                "before_sha256": inst_hash,
                "after_sha256": cat_hash or inst_hash,
            }
            p_items.append(p_item)
            c_items.append({
                "action": "adopt",
                "assistant": assistant,
                "scope": entry.get("scope", scope),
                "skill": sname,
                "repo": repo_name,
                "plugin": plugin_name,
                "src": src_dir or target_path,
                "path": target_path,
                "reason": p_item["reason"],
            })

    elif kind == "foreign":
        entry = entries[0] if entries else {}
        sp_str = entry.get("path")
        if sp_str and sp_str not in seen:
            seen.add(sp_str)
            target_path = pathlib.Path(sp_str)
            sname = sc.get("names", [""])[0] or target_path.name
            inst_hash = compute_target_hash(target_path)
            p_item = {
                "action": "advise",
                "path": sp_str,
                "reason": f"Foreign skill '{sname}' does not match any source repository history: review or remove manually",
                "current_state": "foreign",
                "before_sha256": inst_hash,
                "after_sha256": None,
            }
            p_items.append(p_item)

    elif kind == "stale-plugin-copy":
        target_path_str = sc.get("install_path") or (sc.get("entries", [{}])[0].get("path") if sc.get("entries") else "")
        target_path = pathlib.Path(target_path_str) if target_path_str else None
        advice_list = sc.get("advice", [])
        advice_text = advice_list[0] if advice_list else (sc.get("advice") if isinstance(sc.get("advice"), str) else "")
        if target_path_str and target_path_str not in seen:
            seen.add(target_path_str)
            p_item = {
                "action": "advise",
                "path": target_path_str,
                "reason": advice_text,
                "current_state": "conflict",
                "before_sha256": compute_target_hash(target_path) if target_path else None,
                "after_sha256": None,
            }
            p_items.append(p_item)

    return p_items, c_items


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
    policy = load_conflict_policy(h, ws)
    global_conflict_keys: dict[str, set[tuple[str, tuple[str, ...]]]] = {}

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
            if assistant == "kilo":
                seen_entry_paths: set[str] = set()
                k_roots = kilo_skill_roots(h, ws, scope=scope)
                for rdir, rscope, rtag in k_roots:
                    if not rdir.is_dir():
                        continue
                    for child in sorted(rdir.iterdir()):
                        if child.name.startswith("."):
                            continue
                        if not (child.is_dir() or child.is_symlink()):
                            continue
                        skill_md = child / "SKILL.md"
                        if not skill_md.is_file():
                            continue
                        cp_str = str(child)
                        if cp_str in seen_entry_paths:
                            continue
                        seen_entry_paths.add(cp_str)
                        sname = child.name
                        try:
                            fm, _ = parse_frontmatter_and_body(skill_md.read_text(encoding="utf-8"))
                            if fm and isinstance(fm, dict) and fm.get("name"):
                                sname = str(fm["name"])
                        except Exception:
                            pass
                        s_state, _, _ = detect_skill_state(child, catalog, h)
                        if s_state == "unmanaged":
                            s_sev = "info"
                        elif s_state in ("up-to-date", "plugin"):
                            s_sev = "neutral"
                        elif s_state in ("outdated-legacy", "up-to-date-legacy", "modified-or-outdated", "foreign") or s_state.startswith("obsolete-"):
                            s_sev = "warning"
                        else:
                            s_sev = "info"
                        skill_entries.append({
                            "name": sname,
                            "origin": f"standalone:{rtag}",
                            "scope": scope,
                            "path": cp_str,
                            "enabled": True,
                            "state": s_state,
                            "severity": s_sev,
                        })
            else:
                for sname, sdata in installed_skills.items():
                    child_path = sdir / sname
                    s_state = sdata["state"]
                    if s_state == "unmanaged":
                        s_sev = "info"
                    elif s_state in ("up-to-date", "plugin"):
                        s_sev = "neutral"
                    elif s_state in ("outdated-legacy", "up-to-date-legacy", "modified-or-outdated", "foreign") or s_state.startswith("obsolete-"):
                        s_sev = "warning"
                    else:
                        s_sev = "info"
                    skill_entries.append({
                        "name": sname,
                        "origin": "standalone",
                        "scope": scope,
                        "path": str(child_path),
                        "enabled": True,
                        "state": s_state,
                        "severity": s_sev,
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
                                "severity": "neutral",
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
                                "severity": "neutral",
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
                                    "severity": "neutral",
                                })

            # Inspect agents
            adir = assistant_agents_dir(assistant, scope, ws, h)
            installed_agents: dict[str, Any] = {}
            agent_entries: list[dict[str, Any]] = []

            if assistant == "kilo":
                k_agent_roots = kilo_agent_roots(h, ws, scope)
                for rdir, rscope, rtag in k_agent_roots:
                    if not rdir.is_dir():
                        continue
                    r_receipts = read_agent_receipts(rdir)
                    for child in sorted(rdir.glob("*.md")):
                        if child.name.startswith(".") or not (child.is_file() or child.is_symlink()):
                            continue
                        aname = child.name
                        state, src_repo, src_hash = detect_agent_state(child, catalog_agents, r_receipts, h, assistant="kilo")
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
                        agent_entries.append({
                            "name": aname,
                            "origin": f"standalone:{rtag}" if rtag != "~/.kilo/agents" else "standalone",
                            "scope": rscope,
                            "path": str(child),
                            "enabled": True,
                            "state": state,
                            "source_repo": src_repo,
                            "source_hash": src_hash,
                        })
            else:
                if adir.is_dir():
                    agent_receipts = read_agent_receipts(adir)
                    for child in sorted(adir.glob("*.md")):
                        if child.name.startswith(".") or not (child.is_file() or child.is_symlink()):
                            continue
                        aname = child.name
                        state, src_repo, src_hash = detect_agent_state(child, catalog_agents, agent_receipts, h, assistant=assistant)
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
                        agent_entries.append({
                            "name": aname,
                            "origin": "standalone",
                            "scope": scope,
                            "path": str(child),
                            "enabled": True,
                            "state": state,
                            "source_repo": src_repo,
                            "source_hash": src_hash,
                        })

                if assistant == "claude":
                    claude_plugin_agents = discover_claude_plugin_agents(h, ws)
                    for pa in claude_plugin_agents:
                        pa_scope = "project" if pa["scope"] in ("project", "local") else "global"
                        if pa_scope == scope or (scope == "project" and pa_scope == "global"):
                            en = global_plugin_enabled.get(pa["plugin_id"], True)
                            if pa_scope == "project" and pa["plugin_id"] in project_plugin_enabled:
                                en = project_plugin_enabled[pa["plugin_id"]]
                            agent_entries.append({
                                "name": pa["agent_name"],
                                "origin": pa["origin"],
                                "scope": pa["scope"],
                                "path": pa["path"],
                                "enabled": en,
                                "state": "plugin",
                                "source_repo": pa["plugin_id"].split("@", 1)[1] if "@" in pa["plugin_id"] else None,
                            })

            # Conflicts computed over the UNION of enabled entries:
            # per assistant+scope view; project view = standalone global + standalone project + enabled plugins
            if scope == "project":
                global_entries = environments[assistant].get("global", {}).get("skill_entries", [])
                standalone_global = [e for e in global_entries if e.get("origin", "").startswith("standalone") and e["enabled"]]
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

            # 1. Trigger conflicts across generic/bound pairs
            gb_pairs = get_generic_bound_pairs(h)
            for generic_name, bound_name in gb_pairs:
                generic_entries = [e for e in enabled_for_conflicts if e["name"] == generic_name]
                bound_entries = [e for e in enabled_for_conflicts if e["name"] == bound_name]
                if generic_entries and bound_entries:
                    names = [generic_name, bound_name]
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

                    is_global_location = not any(is_project_entry(e, ws) for e in combined_entries)
                    already_in_global = key in global_conflict_keys.get(assistant, set())

                    if not (scope == "project" and is_global_location and already_in_global):
                        p_items, _ = plan_for_conflict(
                            sc={
                                "kind": "trigger-conflict",
                                "names": names,
                                "entries": combined_entries,
                                "scope": scope,
                            },
                            assistant=assistant,
                            scope=scope,
                            policy=policy,
                            catalog=catalog,
                            home=h,
                        )
                        actions = [item for item in p_items if item["action"] != "advise"]
                        advice: list[str] = []
                        for item in p_items:
                            if item["action"] == "advise":
                                r = item.get("reason", "")
                                if r and r not in advice:
                                    advice.append(r)
                        is_fixable = len(actions) > 0

                        has_prec_generic = any(skill_has_precedence_section(e.get("path", "")) for e in generic_entries)
                        has_prec_bound = any(skill_has_precedence_section(e.get("path", "")) for e in bound_entries)
                        if has_prec_generic and has_prec_bound and not actions:
                            if set(names) == {"orchestration-workflow", "kilo-mcp-orchestrator"}:
                                advice = ["Generic and bound orchestration skills declare reciprocal Precedence; kilo-mcp-orchestrator specializes kilo-mcp tool calls while orchestration-workflow governs architecture."]
                            else:
                                advice = [f"Generic and bound skills declare reciprocal Precedence; {bound_name} specializes tools while {generic_name} governs architecture."]

                        structured_conflicts_map[key] = {
                            "kind": "trigger-conflict",
                            "names": names,
                            "entries": combined_entries,
                            "scope": scope,
                            "fixable": is_fixable,
                            "actionable": is_fixable,
                            "actions": actions,
                            "advice": advice,
                        }
                        if scope == "global":
                            global_conflict_keys.setdefault(assistant, set()).add(key)
                        conflicts.append(
                            f"Both generic '{generic_name}' and bound '{bound_name}' are installed in the same scope; they compete for the same trigger."
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

                    is_global_location = not any(is_project_entry(e, ws) for e in unique_entries)
                    already_in_global = key in global_conflict_keys.get(assistant, set())

                    if not (scope == "project" and is_global_location and already_in_global):
                        p_items, _ = plan_for_conflict(
                            sc={
                                "kind": "duplicate-name",
                                "names": names,
                                "entries": unique_entries,
                                "scope": scope,
                            },
                            assistant=assistant,
                            scope=scope,
                            policy=policy,
                            catalog=catalog,
                            home=h,
                        )
                        actions = [item for item in p_items if item["action"] != "advise"]
                        advice: list[str] = []
                        diff_summaries = [item.get("diff_summary") for item in p_items if item.get("diff_summary")]
                        diff_summary = "; ".join(dict.fromkeys(diff_summaries)) if diff_summaries else None
                        for item in p_items:
                            if item["action"] == "advise":
                                r = item.get("reason", "")
                                if r and r not in advice:
                                    advice.append(r)
                        is_fixable = len(actions) > 0

                        structured_conflicts_map[key] = {
                            "kind": "duplicate-name",
                            "names": names,
                            "entries": unique_entries,
                            "scope": scope,
                            "fixable": is_fixable,
                            "actionable": is_fixable,
                            "actions": actions,
                            "advice": advice,
                            "diff_summary": diff_summary,
                        }
                        if scope == "global":
                            global_conflict_keys.setdefault(assistant, set()).add(key)
                        origins_str = ", ".join(sorted({e["origin"] for e in unique_entries}))
                        conflicts.append(f"Duplicate skill '{name}' found across origins: {origins_str}")

                elif len(unique_entries) == 1:
                    e = unique_entries[0]
                    e_state = e.get("state")
                    if e.get("origin", "").startswith("standalone") and e_state in ("outdated-legacy", "up-to-date-legacy", "foreign"):
                        # For Kilo: only report single-entry legacy/foreign conflicts for skills in Kilo's own roots,
                        # not for external roots like ~/.claude/skills which belong to Claude!
                        if assistant == "kilo":
                            orig = e.get("origin", "")
                            if ".claude" in orig or ".agents" in orig:
                                continue
                        # If a project workspace is active and we are inspecting global scope,
                        # do not treat as an isolated skill if it also exists in project scope (cross-scope duplicate)
                        if scope == "global" and ws is not None:
                            p_dir = assistant_skills_dir(assistant, "project", ws, h) / name
                            if (p_dir / "SKILL.md").is_file():
                                continue

                        names = [name]
                        key = (e_state, tuple(sorted(names)))

                        is_global_location = not is_project_entry(e, ws)
                        already_in_global = key in global_conflict_keys.get(assistant, set())

                        if not (scope == "project" and is_global_location and already_in_global):
                            p_items, _ = plan_for_conflict(
                                sc={
                                    "kind": e_state,
                                    "names": names,
                                    "entries": unique_entries,
                                    "scope": scope,
                                },
                                assistant=assistant,
                                scope=scope,
                                policy=policy,
                                catalog=catalog,
                                home=h,
                            )
                            actions = [item for item in p_items if item["action"] != "advise"]
                            advice: list[str] = []
                            for item in p_items:
                                if item["action"] == "advise":
                                    r = item.get("reason", "")
                                    if r and r not in advice:
                                        advice.append(r)
                            is_fixable = len(actions) > 0

                            structured_conflicts_map[key] = {
                                "kind": e_state,
                                "names": names,
                                "entries": unique_entries,
                                "scope": scope,
                                "fixable": is_fixable,
                                "actionable": is_fixable,
                                "actions": actions,
                                "advice": advice,
                            }
                            if scope == "global":
                                global_conflict_keys.setdefault(assistant, set()).add(key)

            if assistant == "claude":
                stale_plugins = discover_stale_claude_plugins(h, ws, scope=scope)
                for sp in stale_plugins:
                    key = ("stale-plugin-copy", (sp["plugin_id"],))
                    already_in_global = key in global_conflict_keys.get(assistant, set())
                    is_user_scope = sp.get("scope") == "user"
                    if not (scope == "project" and is_user_scope and already_in_global):
                        sc_item = {
                            "kind": "stale-plugin-copy",
                            "names": [sp["plugin_id"]],
                            "plugin_id": sp["plugin_id"],
                            "scope": scope,
                            "install_path": sp["install_path"],
                            "entries": [
                                {
                                    "name": sp["plugin_id"],
                                    "origin": f"plugin:{sp['plugin_id']}",
                                    "scope": sp.get("scope", scope),
                                    "path": sp["install_path"],
                                    "enabled": True,
                                    "state": "plugin",
                                }
                            ],
                            "cached_version": sp["cached_version"],
                            "source_version": sp["source_version"],
                            "versions_equal": sp["versions_equal"],
                            "commit_distance": sp["commit_distance"],
                            "content_differs": sp["content_differs"],
                            "fixable": False,
                            "actionable": False,
                            "actions": [],
                            "advice": [sp["advice"]],
                        }
                        structured_conflicts_map[key] = sc_item
                        if scope == "global":
                            global_conflict_keys.setdefault(assistant, set()).add(key)
            else:
                stale_plugins = []

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
                "agent_entries": agent_entries,
                "conflicts": conflicts,
                "structured_conflicts": structured_conflicts,
                "stale_plugins": stale_plugins,
                "mcp_config_path": str(mcp_cfg_path) if mcp_cfg_path else None,
                "registered_mcps": registered_mcps,
                "mcp_servers": mcp_servers,
            }

    stray: list[str] = []
    codex_json = h / ".codex" / "config.json"
    if codex_json.is_file():
        stray.append(str(codex_json))

    acks = load_doctor_acks(h)

    # Cross-assistant and cross-scope grouping of structured_conflicts
    all_conflicts: list[tuple[str, str, dict[str, Any]]] = []
    for asst in ASSISTANTS:
        for scp in scopes_to_check:
            if scp in environments.get(asst, {}):
                for c in environments[asst][scp].get("structured_conflicts", []):
                    all_conflicts.append((asst, scp, c))

    groups_map: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for asst, scp, c in all_conflicts:
        gkey = compute_group_key(c["kind"], c["names"], c.get("entries"))
        groups_map.setdefault(gkey, []).append((asst, scp, c))

    finding_groups: list[dict[str, Any]] = []
    for gkey, items_with_loc in groups_map.items():
        first_c = items_with_loc[0][2]
        kind = first_c["kind"]
        names = first_c["names"]

        # Deduplicate locations preserving deterministic order
        loc_tuples: list[tuple[str, str]] = []
        for a, s, _ in items_with_loc:
            t = (a, s)
            if t not in loc_tuples:
                loc_tuples.append(t)
        locations = [{"assistant": a, "scope": s} for a, s in sorted(loc_tuples, key=lambda x: (x[0], x[1]))]

        # Aggregate unique entries
        seen_paths: set[str] = set()
        group_entries: list[dict[str, Any]] = []
        for _, _, c in items_with_loc:
            for e in c.get("entries", []):
                ep = e.get("path")
                if ep and ep not in seen_paths:
                    seen_paths.add(ep)
                    group_entries.append(e)
                elif not ep and e not in group_entries:
                    group_entries.append(e)

        # Check acknowledgment (persistent or precedence)
        is_acked, _ = is_finding_acknowledged(kind, names, group_entries, acks, group_key=gkey)
        if not is_acked and kind == "trigger-conflict":
            gb_pairs = get_generic_bound_pairs(h)
            gen_entries = [e for e in group_entries if any(e.get("name") == g for g, _ in gb_pairs)]
            bnd_entries = [e for e in group_entries if any(e.get("name") == b for _, b in gb_pairs)]
            if gen_entries and bnd_entries:
                has_prec_gen = any(skill_has_precedence_section(e.get("path", "")) for e in gen_entries)
                has_prec_bnd = any(skill_has_precedence_section(e.get("path", "")) for e in bnd_entries)
                if has_prec_gen and has_prec_bnd:
                    is_acked = True

        # Determine severity
        if is_acked:
            group_severity = "info"
        elif kind == "trigger-conflict":
            group_severity = "warning"
        elif kind == "duplicate-name":
            is_any_actionable = any(c.get("actionable") for _, _, c in items_with_loc)
            group_severity = "error" if is_any_actionable else "info"
        elif kind in ("outdated-legacy", "up-to-date-legacy", "foreign", "modified-or-outdated", "stale-plugin-copy"):
            group_severity = "warning"
        else:
            group_severity = "info"

        # Update each structured conflict item in-place
        for _, _, c in items_with_loc:
            c["severity"] = group_severity
            c["group_key"] = gkey
            c["locations"] = locations
            c["acknowledged"] = is_acked

        # Aggregate unique actions & advice
        all_actions = []
        seen_actions: set[tuple[str, str]] = set()
        for _, _, c in items_with_loc:
            for act in c.get("actions", []):
                k_act = (act.get("action", ""), act.get("path", ""))
                if k_act not in seen_actions:
                    seen_actions.add(k_act)
                    all_actions.append(act)

        all_advice = []
        for _, _, c in items_with_loc:
            for adv in c.get("advice", []):
                if adv and adv not in all_advice:
                    all_advice.append(adv)

        diff_summaries = [c.get("diff_summary") for _, _, c in items_with_loc if c.get("diff_summary")]
        group_diff_summary = "; ".join(dict.fromkeys(diff_summaries)) if diff_summaries else None

        finding_groups.append({
            "group_key": gkey,
            "kind": kind,
            "names": sorted(names),
            "severity": group_severity,
            "acknowledged": is_acked,
            "locations": locations,
            "entries": group_entries,
            "fixable": any(c.get("fixable") for _, _, c in items_with_loc),
            "actionable": any(c.get("actionable") for _, _, c in items_with_loc),
            "actions": all_actions,
            "advice": all_advice,
            "diff_summary": group_diff_summary,
            "count": len(locations),
        })

    # Add stray config files to finding_groups
    for s in stray:
        sp = pathlib.Path(s)
        s_gkey = f"stray:{sp.name}"
        s_entries = [{
            "name": sp.name,
            "path": str(sp),
            "origin": "stray",
            "scope": "global",
            "enabled": False,
            "state": "stray",
        }]
        s_acked, _ = is_finding_acknowledged("stray", [sp.name], s_entries, acks, group_key=s_gkey)
        can_parse = False
        server_preview = ""
        try:
            raw = sp.read_text(encoding="utf-8")
            data = json.loads(raw) if sp.suffix == ".json" else parse_jsonc(raw)
            if isinstance(data, dict):
                can_parse = True
                raw_mcps = data.get("mcpServers") or data.get("mcp_servers") or {}
                if isinstance(raw_mcps, dict):
                    c_toml = read_codex_mcps("global", h)
                    server_preview = ", ".join(f"{sn} (in config.toml: {sn in c_toml})" for sn in raw_mcps.keys())
        except Exception:
            can_parse = False

        if can_parse:
            adv_text = f"Stray configuration file '{s}' is ignored by Codex (reads config.toml)."
            if server_preview:
                adv_text += f" Servers in file: {server_preview}"
            s_actions = [{
                "action": "trash",
                "path": str(sp),
                "reason": f"Move stray configuration file '{sp.name}' to trash",
            }]
            s_fixable = True
        else:
            adv_text = f"Stray configuration file '{s}' cannot be parsed; refusing to touch."
            s_actions = []
            s_fixable = False

        finding_groups.append({
            "group_key": s_gkey,
            "kind": "stray",
            "names": [sp.name],
            "severity": "info",
            "acknowledged": s_acked,
            "locations": [{"assistant": "codex", "scope": "global"}],
            "entries": s_entries,
            "fixable": s_fixable,
            "actionable": s_fixable,
            "actions": s_actions,
            "advice": [adv_text],
            "count": 1,
        })

    # Add redundant/conflicting MCP findings to finding_groups
    for asst in ASSISTANTS:
        for scp in scopes_to_check:
            sinfo = environments.get(asst, {}).get(scp, {})
            mcp_srvs = sinfo.get("mcp_servers", {})
            for sname, sdata in mcp_srvs.items():
                override_details = sdata.get("override_details", [])
                for det in override_details:
                    prov_str = det.get("provenance", "")
                    is_id = det.get("identical", False)
                    m_gkey = f"redundant-mcp:{sname}"
                    m_entries = [{
                        "name": sname,
                        "path": prov_str,
                        "origin": "mcp",
                        "scope": scp,
                        "enabled": True,
                        "state": "redundant" if is_id else "conflicting",
                    }]
                    m_acked, _ = is_finding_acknowledged("redundant-mcp", [sname], m_entries, acks, group_key=m_gkey)
                    if is_id:
                        m_sev = "info"
                        m_fixable = True
                        m_actions = [{
                            "action": "edit",
                            "path": prov_str,
                            "server": sname,
                            "reason": f"Remove redundant MCP server '{sname}' from {pathlib.Path(prov_str).name}",
                        }]
                        m_advice = [f"MCP server '{sname}' is redundantly defined in {pathlib.Path(prov_str).name} (identical to higher-precedence configuration in {pathlib.Path(sdata['provenance']).name})"]
                    else:
                        m_sev = "info" if m_acked else "warning"
                        m_fixable = False
                        m_actions = []
                        m_advice = [f"MCP server '{sname}' defined in multiple files with conflicting configurations: {prov_str} vs {sdata['provenance']}"]

                    finding_groups.append({
                        "group_key": m_gkey,
                        "kind": "redundant-mcp",
                        "names": [sname],
                        "severity": m_sev,
                        "acknowledged": m_acked,
                        "locations": [{"assistant": asst, "scope": scp}],
                        "entries": m_entries,
                        "fixable": m_fixable,
                        "actionable": m_fixable,
                        "actions": m_actions,
                        "advice": m_advice,
                        "count": 1,
                    })

    if ws is not None:
        for asst in ASSISTANTS:
            p_mcps = environments.get(asst, {}).get("project", {}).get("mcp_servers", {})
            g_mcps = environments.get(asst, {}).get("global", {}).get("mcp_servers", {})
            for sname, p_data in p_mcps.items():
                if sname in g_mcps:
                    g_data = g_mcps[sname]
                    is_equiv = are_mcp_configs_equivalent(p_data.get("config"), g_data.get("config"))
                    p_prov = p_data.get("provenance", "")
                    m_gkey = f"redundant-mcp:{sname}:project"
                    m_entries = [{
                        "name": sname,
                        "path": p_prov,
                        "origin": "mcp",
                        "scope": "project",
                        "enabled": True,
                        "state": "redundant" if is_equiv else "conflicting",
                    }]
                    m_acked, _ = is_finding_acknowledged("redundant-mcp", [sname], m_entries, acks, group_key=m_gkey)
                    if is_equiv:
                        finding_groups.append({
                            "group_key": m_gkey,
                            "kind": "redundant-mcp",
                            "names": [sname],
                            "severity": "info",
                            "acknowledged": m_acked,
                            "locations": [{"assistant": asst, "scope": "project"}],
                            "entries": m_entries,
                            "fixable": True,
                            "actionable": True,
                            "actions": [{
                                "action": "edit",
                                "path": p_prov,
                                "server": sname,
                                "reason": f"Remove redundant project MCP server '{sname}' from {pathlib.Path(p_prov).name}",
                            }],
                            "advice": [f"MCP server '{sname}' registered in project scope is identical to global registration"],
                            "count": 1,
                        })
                    else:
                        finding_groups.append({
                            "group_key": m_gkey,
                            "kind": "redundant-mcp",
                            "names": [sname],
                            "severity": "info" if m_acked else "warning",
                            "acknowledged": m_acked,
                            "locations": [{"assistant": asst, "scope": "project"}],
                            "entries": m_entries,
                            "fixable": False,
                            "actionable": False,
                            "actions": [],
                            "advice": [f"MCP server '{sname}' registered in project scope differs from global registration"],
                            "count": 1,
                        })

    # Inspect version-free launcher and broker MCP registrations across Claude, Kilo, and Codex
    broker_mcp_report = inspect_broker_mcp_registrations(home=h, workspace=ws, scope="global")

    # 1. Launcher finding (missing -> info, outdated -> warning, foreign -> error, up-to-date -> none)
    l_info = broker_mcp_report["launcher"]
    l_state = l_info["state"]
    l_path = l_info["path"]
    if l_state in ("missing", "outdated", "foreign"):
        l_kind = f"{l_state}-launcher"
        l_gkey = f"{l_kind}:ai-orch"
        l_entries = [{
            "name": "ai-orch",
            "path": l_path,
            "origin": "launcher",
            "scope": "global",
            "enabled": l_state != "missing",
            "state": l_state,
        }]
        l_acked, _ = is_finding_acknowledged(l_kind, ["ai-orch"], l_entries, acks, group_key=l_gkey)
        l_plan_items = [dict(it) for it in l_info.get("plan", [])]
        l_fix_cmd = "ai-orch install-launcher"
        l_apply_cmd = f"ai-orch install-launcher --apply --expect-hash {l_info.get('plan_hash', '<hash>')}"
        for it in l_plan_items:
            it["command"] = l_fix_cmd
            it["fix"] = l_fix_cmd
            it["fix_command"] = l_fix_cmd
            it["apply_command"] = l_apply_cmd

        if l_state == "missing":
            l_sev = "info"
            l_fixable = True
            l_msg = (
                f"Version-free launcher is missing at {l_path}. "
                f"Fix: `{l_fix_cmd}` (preview, then `{l_apply_cmd}`)."
            )
        elif l_state == "outdated":
            l_sev = "info" if l_acked else "warning"
            l_fixable = True
            l_msg = (
                f"Version-free launcher at {l_path} is outdated. "
                f"Fix: `{l_fix_cmd}` (preview, then `{l_apply_cmd}`)."
            )
        else:
            l_sev = "info" if l_acked else "error"
            l_fixable = False
            l_msg = (
                f"Launcher path {l_path} is occupied by an unrelated file; "
                f"`{l_fix_cmd}` refuses to overwrite it."
            )

        finding_groups.append({
            "id": l_gkey,
            "group_key": l_gkey,
            "group": "Launcher",
            "title": "Version-free launcher",
            "kind": l_kind,
            "names": ["ai-orch"],
            "path": l_path,
            "config_path": l_path,
            "state": l_state,
            "severity": l_sev,
            "acknowledged": l_acked,
            "message": l_msg,
            "fix": l_fix_cmd,
            "fix_command": l_fix_cmd,
            "locations": [{"assistant": "launcher", "scope": "global"}],
            "entries": l_entries,
            "fixable": l_fixable,
            "actionable": l_fixable,
            "actions": l_plan_items if l_fixable else [],
            "advice": [l_msg],
            "count": 1,
        })

    # 2. Per-client broker MCP registration findings (missing -> warning, stale -> error, registered -> none)
    for asst, b_info in broker_mcp_report["clients"].items():
        if asst in environments and "global" in environments[asst]:
            environments[asst]["global"]["broker_mcp"] = b_info
        b_state = b_info["state"]
        if b_state in ("missing", "stale"):
            b_kind = "missing-broker-mcp" if b_state == "missing" else "stale-broker-mcp"
            b_gkey = f"{b_kind}:{asst}"
            b_sname = b_info["server_name"]
            b_cfg_path = b_info["config_path"]
            b_entries = [{
                "name": asst,
                "server": b_sname,
                "path": b_cfg_path,
                "origin": "mcp",
                "scope": "global",
                "enabled": True,
                "state": b_state,
            }]
            b_acked, _ = is_finding_acknowledged(b_kind, [asst], b_entries, acks, group_key=b_gkey)
            b_plan_item = dict(b_info["plan_item"])
            b_fixable = b_plan_item["action"] != "refuse"
            b_fix_cmd = f"ai-orch env register-broker --assistants {asst}"
            b_apply_cmd = f"ai-orch env register-broker --assistants {asst} --apply --expect-hash <hash>"
            b_plan_item["fix"] = b_fix_cmd
            b_plan_item["fix_command"] = b_fix_cmd
            b_plan_item["apply_command"] = b_apply_cmd

            if b_state == "missing":
                b_raw_sev = "warning"
                b_msg = (
                    f"Broker MCP registration for {asst} is missing in {b_cfg_path}. "
                    f"Fix: `{b_fix_cmd}` (preview, then `{b_apply_cmd}`)."
                )
            else:
                b_raw_sev = "error"
                b_msg = (
                    f"Broker MCP registration '{b_sname}' for {asst} in {b_cfg_path} is stale ({'; '.join(b_info['reasons'])}). "
                    f"Fix: `{b_fix_cmd}` (preview, then `{b_apply_cmd}`)."
                )

            finding_groups.append({
                "id": b_gkey,
                "group_key": b_gkey,
                "group": "Broker MCP registration",
                "title": "Broker MCP registration",
                "kind": b_kind,
                "client": asst,
                "assistant": asst,
                "config_path": b_cfg_path,
                "path": b_cfg_path,
                "state": b_state,
                "names": [asst],
                "server_name": b_sname,
                "severity": "info" if b_acked else b_raw_sev,
                "acknowledged": b_acked,
                "message": b_msg,
                "fix": b_fix_cmd,
                "fix_command": b_fix_cmd,
                "locations": [{"assistant": asst, "scope": "global"}],
                "entries": b_entries,
                "fixable": b_fixable,
                "actionable": b_fixable,
                "actions": [b_plan_item] if b_fixable else [],
                "advice": [b_msg],
                "count": 1,
            })

    sev_rank = {"error": 0, "warning": 1, "info": 2, "neutral": 3}
    finding_groups.sort(key=lambda g: (sev_rank.get(g["severity"], 9), g["group_key"]))

    summary = {
        "error": sum(1 for g in finding_groups if g["severity"] == "error"),
        "warning": sum(1 for g in finding_groups if g["severity"] == "warning"),
        "info": sum(1 for g in finding_groups if g["severity"] == "info"),
        "neutral": sum(1 for g in finding_groups if g["severity"] == "neutral"),
        "acknowledged": sum(1 for g in finding_groups if g["acknowledged"]),
        "total_groups": len(finding_groups),
    }

    kilo_effective = compute_kilo_effective(h, ws)
    if "kilo" in environments:
        environments["kilo"]["kilo_effective"] = kilo_effective

    return {
        "clis": clis,
        "source_repos": repos_status,
        "available_catalog_count": len(catalog),
        "environments": environments,
        "stray": stray,
        "finding_groups": finding_groups,
        "groups": finding_groups,
        "summary": summary,
        "severity_counts": summary,
        "kilo_effective": kilo_effective,
        "launcher": broker_mcp_report["launcher"],
        "broker_mcp": broker_mcp_report,
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
    force: bool = False,
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
        claude_plugins = discover_claude_plugin_skills(h, ws)
        global_plugin_enabled, project_plugin_enabled = load_claude_plugin_settings(h, ws)
        policy = load_conflict_policy(h, ws)
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
                        src_text = agent_md.read_text(encoding="utf-8")
                        transformed_text = transform_agent_for_assistant(src_text, assistant)
                        src_hash = hashlib.sha256(transformed_text.encode("utf-8")).hexdigest()
                        is_existing = target_agent.exists() or target_agent.is_symlink()
                        if not is_existing:
                            action = "create"
                            cur_state = "missing"
                            reason = f"Install agent '{aname}' from {repo_name}/{p_name}"
                            before_sha256 = None
                            after_sha256 = src_hash
                        else:
                            cur_state, s_repo, s_hash = detect_agent_state(target_agent, catalog_agents, agent_receipts, h, assistant=assistant)
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
                            elif before_sha256 == src_hash:
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
                            "content": transformed_text,
                            "source_hash": src_hash,
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
                    cur_state = "missing"
                    before_sha256 = None
                    if is_existing:
                        cur_state, s_repo, s_hash = detect_skill_state(target_dir, catalog, h)
                        before_sha256 = compute_target_hash(target_dir)

                    skip_due_to_plugin = False
                    plugin_skip_reason = ""
                    skip_due_to_policy = False
                    policy_skip_reason = ""

                    if not force and not (sname in overwrite_set or overwrite_all):
                        # Check 1: Claude target provided by enabled plugin
                        if assistant == "claude":
                            for ps in claude_plugins:
                                if ps.get("skill_name") == sname:
                                    pid = ps.get("plugin_id", "")
                                    if scope == "global" and ps.get("scope") == "user":
                                        if global_plugin_enabled.get(pid, True):
                                            skip_due_to_plugin = True
                                            plugin_skip_reason = f"provided by enabled plugin '{pid}'"
                                            break
                                    elif scope == "project" and ws is not None:
                                        if ps.get("scope") == "user" and project_plugin_enabled.get(pid, True):
                                            skip_due_to_plugin = True
                                            plugin_skip_reason = f"provided by enabled plugin '{pid}'"
                                            break
                                        elif ps.get("scope") in ("project", "local"):
                                            p_path = ps.get("project_path")
                                            if p_path and pathlib.Path(p_path).resolve() == ws and project_plugin_enabled.get(pid, True):
                                                skip_due_to_plugin = True
                                                plugin_skip_reason = f"provided by enabled plugin '{pid}'"
                                                break

                        # Check 2: Skip names that conflict policy would remove
                        asst_policy = policy.get(assistant, "generic" if assistant == "kilo" else "bound")
                        gb_pairs = get_generic_bound_pairs(h)
                        bound_for_generic = {g: b for g, b in gb_pairs}
                        generic_for_bound = {b: g for g, b in gb_pairs}
                        if asst_policy == "bound":
                            if sname == "orchestration-workflow":
                                skip_due_to_policy = True
                                policy_skip_reason = f"removed by conflict policy ('{asst_policy}')"
                            elif sname in bound_for_generic:
                                bound_name = bound_for_generic[sname]
                                if (dest_skills_dir / bound_name).is_dir() or (dest_skills_dir / bound_name).is_symlink():
                                    skip_due_to_policy = True
                                    policy_skip_reason = f"removed by conflict policy ('{asst_policy}')"
                        elif asst_policy == "generic":
                            if sname == "kilo-mcp-orchestrator":
                                skip_due_to_policy = True
                                policy_skip_reason = f"removed by conflict policy ('{asst_policy}')"
                            elif sname in generic_for_bound:
                                generic_name = generic_for_bound[sname]
                                if (dest_skills_dir / generic_name).is_dir() or (dest_skills_dir / generic_name).is_symlink():
                                    skip_due_to_policy = True
                                    policy_skip_reason = f"removed by conflict policy ('{asst_policy}')"

                    if skip_due_to_plugin:
                        action = "skip"
                        reason = plugin_skip_reason
                        after_sha256 = None
                    elif skip_due_to_policy:
                        action = "skip"
                        reason = policy_skip_reason
                        after_sha256 = None
                    elif not is_existing:
                        action = "create"
                        cur_state = "missing"
                        reason = f"Install skill '{sname}' from {repo_name}/{p_name}"
                        before_sha256 = None
                        after_sha256 = src_hash
                    else:
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
                    op["target"].write_text(op["content"], encoding="utf-8")
                receipt_data = {
                    "repo": op["repo"],
                    "plugin": op["plugin"],
                    "name": op["agent"],
                    "source_hash": op["source_hash"],
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
    scopes_to_check = (["project"] if ws else []) + ["global"]
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
                    plan_items, conflict_items = plan_for_conflict(
                        sc=sc,
                        assistant=assistant,
                        scope=scope,
                        policy=policy,
                        catalog=catalog,
                        seen_paths=seen_paths,
                        home=h,
                    )
                    p.extend(plan_items)
                    c_items.extend(conflict_items)
        return p, c_items

    plan, conflict_items = _build_plan()
    plan_hash = compute_plan_hash(plan)
    actions = [item for item in plan if item["action"] != "advise"]
    advice: list[str] = []
    for item in plan:
        if item["action"] == "advise":
            r = item.get("reason", "")
            if r and r not in advice:
                advice.append(r)

    if expect_plan_hash is not None and expect_plan_hash != plan_hash:
        return {
            "ok": False,
            "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
            "plan": plan,
            "actions": actions,
            "advice": advice,
            "plan_hash": plan_hash,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "applied": 0,
            "resolved_count": len(actions),
            "resolved": [],
            "plan": plan,
            "actions": actions,
            "advice": advice,
            "plan_hash": plan_hash,
        }

    with env_lock(h):
        plan, conflict_items = _build_plan()
        plan_hash = compute_plan_hash(plan)
        actions = [item for item in plan if item["action"] != "advise"]
        advice = []
        for item in plan:
            if item["action"] == "advise":
                r = item.get("reason", "")
                if r and r not in advice:
                    advice.append(r)

        if expect_plan_hash is not None and expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
                "plan": plan,
                "actions": actions,
                "advice": advice,
                "plan_hash": plan_hash,
            }

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        resolved: list[dict[str, Any]] = []
        for item in conflict_items:
            action = item.get("action", "trash")
            if action == "trash":
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
                    "removed": item.get("removed", item.get("skill", "")),
                    "kept": item.get("kept", ""),
                    "action": "trash",
                })
            elif action == "adopt":
                target_dir = pathlib.Path(item["path"])
                src_dir = pathlib.Path(item["src"]) if item.get("src") else target_dir
                src_hash = hash_directory(src_dir) if src_dir.is_dir() else None
                marker_data = {
                    "repo": item["repo"],
                    "plugin": item["plugin"],
                    "name": item["skill"],
                    "source_hash": src_hash or compute_target_hash(target_dir),
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "copy",
                }
                (target_dir / ".ai-orch-source.json").write_text(
                    json.dumps(marker_data, indent=2) + "\n",
                    encoding="utf-8",
                )
                resolved.append({
                    "assistant": item["assistant"],
                    "scope": item["scope"],
                    "skill": item["skill"],
                    "action": "adopt",
                })
            elif action == "update":
                target_dir = pathlib.Path(item["path"])
                src_dir = pathlib.Path(item["src"])
                trash_path(
                    target_dir,
                    assistant=item["assistant"],
                    scope=item["scope"],
                    kind="skills",
                    reason=item["reason"],
                    workspace=ws,
                    home=h,
                    timestamp=ts,
                )
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    src_dir,
                    target_dir,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
                )
                marker_data = {
                    "repo": item["repo"],
                    "plugin": item["plugin"],
                    "name": item["skill"],
                    "source_hash": hash_directory(src_dir),
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "copy",
                }
                (target_dir / ".ai-orch-source.json").write_text(
                    json.dumps(marker_data, indent=2) + "\n",
                    encoding="utf-8",
                )
                resolved.append({
                    "assistant": item["assistant"],
                    "scope": item["scope"],
                    "skill": item["skill"],
                    "action": "update",
                })

        return {
            "ok": True,
            "applied": len(resolved),
            "resolved_count": len(resolved),
            "resolved": resolved,
            "plan": plan,
            "actions": actions,
            "advice": advice,
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


def remove_mcp_from_config(config_path: pathlib.Path, server_name: str) -> tuple[bool, str, str]:
    """Safely remove an MCP server from a JSON/JSONC/TOML config file.
    Never modifies an unparseable config file.
    Returns (ok, new_content, error_message).
    """
    if not config_path.is_file():
        return False, "", "File not found"
    try:
        raw = config_path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, "", f"Cannot read file: {exc}"

    if config_path.suffix == ".toml":
        try:
            parsed = tomllib.loads(raw)
            if not isinstance(parsed, dict):
                return False, "", "Top-level TOML is not a table"
        except Exception as exc:
            return False, "", f"Unparseable TOML ({exc})"
        pattern = rf'\[mcp_servers\.("?{re.escape(server_name)}"?)\].*?(?=\n\[|\Z)'
        new_raw = re.sub(pattern, "", raw, flags=re.DOTALL)
        return True, new_raw.strip() + "\n", ""

    # JSON or JSONC
    try:
        data = json.loads(raw)
    except Exception:
        try:
            data = parse_jsonc(raw)
        except Exception as exc:
            return False, "", f"Unparseable JSON/JSONC ({exc})"

    if not isinstance(data, dict):
        return False, "", "Top-level JSON is not an object"

    modified = False
    if "mcp" in data and isinstance(data["mcp"], dict):
        if server_name in data["mcp"]:
            del data["mcp"][server_name]
            modified = True
    if "mcpServers" in data and isinstance(data["mcpServers"], dict):
        if server_name in data["mcpServers"]:
            del data["mcpServers"][server_name]
            modified = True

    if not modified:
        return False, "", f"Server '{server_name}' not found in {config_path.name}"

    new_raw = json.dumps(data, indent=2) + "\n"
    return True, new_raw, ""


def clean_stray(
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Clean stray configuration files and redundant MCP overrides.
    Returns:
        {ok, dry_run, applied, plan, plan_hash}
    """
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None

    def _build_plan() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        p: list[dict[str, Any]] = []
        ops: list[dict[str, Any]] = []

        # 1. Stray config files
        codex_json = h / ".codex" / "config.json"
        if codex_json.is_file():
            raw = codex_json.read_text(encoding="utf-8")
            can_parse = False
            servers_in_json: list[str] = []
            try:
                data = json.loads(raw)
                can_parse = isinstance(data, dict)
            except Exception:
                try:
                    data = parse_jsonc(raw)
                    can_parse = isinstance(data, dict)
                except Exception:
                    can_parse = False
            if can_parse:
                mcps = data.get("mcpServers") or data.get("mcp_servers") or {}
                if isinstance(mcps, dict):
                    servers_in_json = list(mcps.keys())
                codex_toml_mcps = read_codex_mcps("global", h)
                server_preview_parts = [
                    f"{s} (in config.toml: {s in codex_toml_mcps})"
                    for s in servers_in_json
                ]
                preview_str = f"Servers in file: {', '.join(server_preview_parts)}" if server_preview_parts else "No servers in file"
                reason = f"Move stray config file '{codex_json.name}' to trash ({preview_str})"
                p_item = {
                    "action": "trash",
                    "path": str(codex_json),
                    "reason": reason,
                    "current_state": "stray",
                    "before_sha256": compute_target_hash(codex_json),
                    "after_sha256": None,
                }
                p.append(p_item)
                ops.append({
                    "type": "trash",
                    "path": codex_json,
                    "assistant": "codex",
                    "scope": "global",
                    "kind": "stray",
                    "plan_item": p_item,
                })
            else:
                p.append({
                    "action": "advise",
                    "path": str(codex_json),
                    "reason": f"Stray config file '{codex_json}' cannot be parsed; refusing to touch",
                    "current_state": "stray",
                    "before_sha256": compute_target_hash(codex_json),
                    "after_sha256": None,
                })

        # 2. Redundant MCP overrides in Kilo (global and project)
        for scp in (["global", "project"] if ws else ["global"]):
            kilo_mcps = read_kilo_merged_mcps(scp, ws, h)
            for sname, sdata in kilo_mcps.items():
                override_details = sdata.get("override_details", [])
                for det in override_details:
                    prov_path = pathlib.Path(det["provenance"])
                    is_id = det.get("identical", False)
                    if is_id:
                        ok, new_content, err = remove_mcp_from_config(prov_path, sname)
                        if ok:
                            p_item = {
                                "action": "edit",
                                "path": str(prov_path),
                                "server": sname,
                                "reason": f"Remove redundant MCP server '{sname}' from {prov_path.name} (identical to {pathlib.Path(sdata['provenance']).name})",
                                "current_state": "redundant",
                                "before_sha256": compute_target_hash(prov_path),
                                "after_sha256": hashlib.sha256(new_content.encode("utf-8")).hexdigest(),
                            }
                            p.append(p_item)
                            ops.append({
                                "type": "edit",
                                "path": prov_path,
                                "content": new_content,
                                "plan_item": p_item,
                            })
                        else:
                            p.append({
                                "action": "advise",
                                "path": str(prov_path),
                                "server": sname,
                                "reason": f"Cannot remove redundant MCP server '{sname}' from {prov_path.name}: {err}",
                                "current_state": "redundant",
                                "before_sha256": compute_target_hash(prov_path),
                                "after_sha256": None,
                            })

        # 3. Two-scope redundancy (project identical to global)
        if ws is not None:
            for asst in ASSISTANTS:
                if asst == "kilo":
                    p_mcps = read_kilo_merged_mcps("project", ws, h)
                    g_mcps = read_kilo_merged_mcps("global", ws, h)
                elif asst == "claude":
                    p_mcps = read_claude_mcps("project", ws, h)
                    g_mcps = read_claude_mcps("global", ws, h)
                else:
                    p_mcps = {}
                    g_mcps = read_codex_mcps("global", h)
                for sname, p_data in p_mcps.items():
                    if sname in g_mcps:
                        g_data = g_mcps[sname]
                        if are_mcp_configs_equivalent(p_data.get("config"), g_data.get("config")):
                            p_prov = pathlib.Path(p_data["provenance"])
                            ok, new_content, err = remove_mcp_from_config(p_prov, sname)
                            if ok:
                                p_item = {
                                    "action": "edit",
                                    "path": str(p_prov),
                                    "server": sname,
                                    "reason": f"Remove redundant project MCP server '{sname}' from {p_prov.name} (identical to global registration)",
                                    "current_state": "redundant",
                                    "before_sha256": compute_target_hash(p_prov),
                                    "after_sha256": hashlib.sha256(new_content.encode("utf-8")).hexdigest(),
                                }
                                p.append(p_item)
                                ops.append({
                                    "type": "edit",
                                    "path": p_prov,
                                    "content": new_content,
                                    "plan_item": p_item,
                                })

        return p, ops

    plan, ops = _build_plan()
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
            "applied": 0,
            "plan": plan,
            "plan_hash": plan_hash,
        }

    with env_lock(h):
        plan, ops = _build_plan()
        plan_hash = compute_plan_hash(plan)
        if expect_plan_hash is not None and expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, but recomputed plan hash is {plan_hash}",
                "plan": plan,
                "plan_hash": plan_hash,
            }

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for op in ops:
            if op["type"] == "trash":
                trash_path(
                    op["path"],
                    assistant=op["assistant"],
                    scope=op["scope"],
                    kind=op["kind"],
                    reason=op["plan_item"]["reason"],
                    workspace=ws,
                    home=h,
                    timestamp=ts,
                )
            elif op["type"] == "edit":
                _atomic_write_with_backup(op["path"], op["content"])

        return {
            "ok": True,
            "applied": len(ops),
            "plan": plan,
            "plan_hash": plan_hash,
        }


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
    apply: bool = False,
    expect_hash: str | None = None,
) -> dict[str, Any]:
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else pathlib.Path.cwd()

    if server_repo in (*BROKER_MCP_NAMES, "broker"):
        target_name = BROKER_MCP_SERVER_NAME if server_repo == "broker" else server_repo
        return register_broker_mcp(
            assistants=assistants,
            scope=scope,
            workspace=workspace,
            home=h,
            server_name=target_name,
            dry_run=dry_run,
            apply=apply,
            expect_hash=expect_hash,
            expect_plan_hash=expect_plan_hash,
        )

    if "all" in assistants:
        assistants = [a for a in ASSISTANTS if not (a == "kilo" and server_repo == "kilo-mcp")]

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

                target_cfg = {"command": effective_cmd, "args": cmd_args}
                mcps = read_claude_mcps(scope, ws, h)
                existing = mcps.get(server_repo)
                cur_state = "registered" if existing else "unregistered"
                is_equiv = existing and are_mcp_configs_equivalent(existing.get("config"), target_cfg)

                if is_equiv:
                    p.append({
                        "action": "noop",
                        "assistant": "claude",
                        "scope": scope,
                        "path": "claude" if claude_bin else str(cfg_path),
                        "command": f"{effective_cmd} {' '.join(shlex.quote(a) for a in cmd_args)}",
                        "reason": f"MCP server '{server_repo}' already registered in claude ({scope}) with equivalent command",
                        "current_state": "registered",
                        "before_sha256": compute_target_hash(cfg_path) if cfg_path.exists() else None,
                        "after_sha256": None,
                    })
                elif claude_bin is not None:
                    argv = ["claude", "mcp", "add", "--transport", "stdio", "--scope", scope_flag, server_repo, "--", effective_cmd, *cmd_args]
                    act = "replace" if existing else "cli"
                    old_c, old_a, _ = normalize_mcp_config(existing.get("config")) if existing else (None, [], {})
                    old_str = f"{old_c} {' '.join(shlex.quote(a) for a in old_a)}" if old_c else ""
                    new_str = f"{effective_cmd} {' '.join(shlex.quote(a) for a in cmd_args)}"
                    reason = f"Register MCP server '{server_repo}' in claude ({scope}) via CLI" if not existing else f"Update registration of '{server_repo}' in claude ({scope}): {old_str} -> {new_str}"
                    p_item = {
                        "action": act,
                        "assistant": "claude",
                        "scope": scope,
                        "path": "claude",
                        "command": " ".join(shlex.quote(a) for a in argv),
                        "argv": argv,
                        "reason": reason,
                        "current_state": cur_state,
                        "before_sha256": None,
                        "after_sha256": None,
                    }
                    if existing:
                        p_item["old_command"] = old_str
                        p_item["new_command"] = new_str
                        p_item["diff"] = f"{old_str} -> {new_str}"
                    p.append(p_item)
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
                    act = "replace" if existing else "edit"
                    p_item = {
                        "action": act,
                        "assistant": "claude",
                        "scope": scope,
                        "path": str(cfg_path),
                        "reason": f"Register MCP server '{server_repo}' in claude ({scope})" if not existing else f"Update registration of '{server_repo}' in claude ({scope})",
                        "current_state": cur_state,
                        "before_sha256": compute_target_hash(cfg_path),
                        "after_sha256": hashlib.sha256(new_json_str.encode("utf-8")).hexdigest(),
                    }
                    if existing:
                        old_c, old_a, _ = normalize_mcp_config(existing.get("config"))
                        old_str = f"{old_c} {' '.join(shlex.quote(a) for a in old_a)}" if old_c else ""
                        new_str = f"{effective_cmd} {' '.join(shlex.quote(a) for a in cmd_args)}"
                        p_item["old_command"] = old_str
                        p_item["new_command"] = new_str
                        p_item["diff"] = f"{old_str} -> {new_str}"
                    p.append(p_item)
                    file_updates.append({
                        "assistant": "claude",
                        "cfg_path": cfg_path,
                        "content": new_json_str,
                    })

            elif assistant == "codex":
                codex_bin = shutil.which("codex")
                cfg_path = assistant_mcp_config_path("codex", "global", ws, h)
                mcps = read_codex_mcps("global", h)
                existing = mcps.get(server_repo)
                cur_state = "registered" if existing else "unregistered"
                target_cfg = {"command": effective_cmd, "args": cmd_args}
                is_equiv = existing and are_mcp_configs_equivalent(existing.get("config"), target_cfg)

                if is_equiv:
                    p.append({
                        "action": "noop",
                        "assistant": "codex",
                        "scope": "global",
                        "path": "codex" if codex_bin else str(cfg_path),
                        "command": f"{effective_cmd} {' '.join(shlex.quote(a) for a in cmd_args)}",
                        "reason": f"MCP server '{server_repo}' already registered in codex (global) with equivalent command",
                        "current_state": "registered",
                        "before_sha256": compute_target_hash(cfg_path) if cfg_path.exists() else None,
                        "after_sha256": None,
                    })
                elif codex_bin is not None:
                    argv = ["codex", "mcp", "add", server_repo, "--", effective_cmd, *cmd_args]
                    act = "replace" if existing else "cli"
                    old_c, old_a, _ = normalize_mcp_config(existing.get("config")) if existing else (None, [], {})
                    old_str = f"{old_c} {' '.join(shlex.quote(a) for a in old_a)}" if old_c else ""
                    new_str = f"{effective_cmd} {' '.join(shlex.quote(a) for a in cmd_args)}"
                    reason = f"Register MCP server '{server_repo}' in codex (global) via CLI" if not existing else f"Update registration of '{server_repo}' in codex (global): {old_str} -> {new_str}"
                    p_item = {
                        "action": act,
                        "assistant": "codex",
                        "scope": "global",
                        "path": "codex",
                        "command": " ".join(shlex.quote(a) for a in argv),
                        "argv": argv,
                        "reason": reason,
                        "current_state": cur_state,
                        "before_sha256": None,
                        "after_sha256": None,
                    }
                    if existing:
                        p_item["old_command"] = old_str
                        p_item["new_command"] = new_str
                        p_item["diff"] = f"{old_str} -> {new_str}"
                    p.append(p_item)
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

                target_cfg = {
                    "type": "local",
                    "command": [effective_cmd, *cmd_args],
                    "enabled": True,
                }
                existing_kilo_cfg = data.get("mcp", {}).get(server_repo)
                is_equiv = existing_kilo_cfg and are_mcp_configs_equivalent(existing_kilo_cfg, target_cfg)

                if is_equiv:
                    p.append({
                        "action": "noop",
                        "assistant": "kilo",
                        "scope": scope,
                        "path": str(cfg_path),
                        "reason": f"MCP server '{server_repo}' already registered in kilo ({scope}) with equivalent command",
                        "current_state": "registered",
                        "before_sha256": compute_target_hash(cfg_path),
                        "after_sha256": None,
                    })
                else:
                    new_data = json.loads(json.dumps(data))
                    new_data.setdefault("mcp", {})[server_repo] = target_cfg
                    new_json_str = json.dumps(new_data, indent=2) + "\n"
                    act = "replace" if existing_kilo_cfg else "edit"
                    p_item = {
                        "action": act,
                        "path": str(cfg_path),
                        "reason": f"Register MCP server '{server_repo}' in kilo ({scope})" if not existing_kilo_cfg else f"Update registration of '{server_repo}' in kilo ({scope})",
                        "current_state": cur_state,
                        "before_sha256": compute_target_hash(cfg_path),
                        "after_sha256": hashlib.sha256(new_json_str.encode("utf-8")).hexdigest(),
                    }
                    if existing_kilo_cfg:
                        old_c, old_a, _ = normalize_mcp_config(existing_kilo_cfg)
                        old_str = f"{old_c} {' '.join(shlex.quote(a) for a in old_a)}" if old_c else ""
                        new_str = f"{effective_cmd} {' '.join(shlex.quote(a) for a in cmd_args)}"
                        p_item["assistant"] = "kilo"
                        p_item["old_command"] = old_str
                        p_item["new_command"] = new_str
                        p_item["diff"] = f"{old_str} -> {new_str}"
                    p.append(p_item)
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

    if report.get("summary"):
        sm = report["summary"]
        print("\n=== Doctor Summary (Groups) ===")
        print(f"  Errors: {sm.get('error', 0)}, Warnings: {sm.get('warning', 0)}, Info: {sm.get('info', 0)}, Neutral: {sm.get('neutral', 0)} (Acknowledged: {sm.get('acknowledged', 0)}, Total: {sm.get('total_groups', 0)})")

    print("\n=== Source Repositories ===")
    for rname, rinfo in report["source_repos"].items():
        status = f"OK ({rinfo['path']}, venv={rinfo['has_venv']})" if rinfo["available"] else "NOT CLONED"
        print(f"  {rname:<18}: {status}")

    print("\n=== Environments (Skills & Registered MCPs) ===")
    for assistant, scopes in report["environments"].items():
        for scope, sinfo in scopes.items():
            if scope not in SCOPES or not isinstance(sinfo, dict):
                continue
            print(f"\n[{assistant} — {scope}] ({sinfo['installed_count']} skill(s), MCPs: {', '.join(sinfo['registered_mcps']) or 'none'})")
            for sname, sdata in sinfo["skills"].items():
                print(f"  - {sname:<30} [{sdata['state']}] (source: {sdata['source_repo'] or 'local'})")
            for entry in sinfo.get("skill_entries", []):
                if entry.get("origin") not in ("standalone", "standalone:~/.kilo/skills", "standalone:.kilo/skills"):
                    en_str = "enabled" if entry.get("enabled") else "disabled"
                    print(f"  - {entry['name']:<30} [{entry['state']}] ({entry['origin']}, {en_str})")
            if sinfo.get("agents"):
                for aname, adata in sinfo["agents"].items():
                    print(f"  @ [agent] {aname:<25} [{adata['state']}] (source: {adata.get('source_repo') or 'local'})")
            for entry in sinfo.get("agent_entries", []):
                if entry.get("origin") not in ("standalone", "standalone:~/.kilo/agents", "standalone:.kilo/agents"):
                    en_str = "enabled" if entry.get("enabled") else "disabled"
                    print(f"  @ [agent] {entry['name']:<25} [{entry['state']}] ({entry['origin']}, {en_str})")
            if sinfo.get("mcp_servers"):
                for mname, mdata in sinfo["mcp_servers"].items():
                    prov = mdata.get("provenance", "")
                    overrides = mdata.get("overrides", [])
                    ov_str = f" (overrides: {', '.join(overrides)})" if overrides else ""
                    mscope = mdata.get("scope", scope)
                    print(f"  * [mcp] {mname:<25} [scope: {mscope}] (source: {prov}){ov_str}")
            for c in sinfo["conflicts"]:
                print(f"  ! CONFLICT: {c}")
            for sp in sinfo.get("stale_plugins", []):
                dist_str = f"{sp['commit_distance']} commit(s) behind" if sp['commit_distance'] != "unknown" else "distance unknown"
                print(f"  ! STALE PLUGIN: {sp['plugin_id']} (cached: {sp['cached_version']}, source: {sp['source_version']}, {dist_str})")
                print(f"    Advice: {sp['advice']}")

    if report.get("stray"):
        print("\n=== Stray Config Files ===")
        for s in report["stray"]:
            print(f"  ! STRAY: {s} (not read by tool)")

    if report.get("broker_mcp"):
        bm = report["broker_mcp"]
        linfo = bm.get("launcher", {})
        print(f"\n=== Launcher & Broker MCP Registration (plan hash: {bm.get('plan_hash', '')}) ===")
        print(f"  launcher          : [{linfo.get('state')}] {linfo.get('path')}")
        for asst, cinfo in bm.get("clients", {}).items():
            rs = f" ({'; '.join(cinfo.get('reasons', []))})" if cinfo.get("reasons") and cinfo.get("state") != "registered" else ""
            print(f"  {asst:<18}: [{cinfo.get('state')}] {cinfo.get('config_path')}{rs}")
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
            force=getattr(args, "force", False),
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
    raw_assistants = args.assistants
    if raw_assistants is None:
        raw_assistants = ["all"] if args.server in (*BROKER_MCP_NAMES, "broker") else ["claude", "codex"]
    if "all" in raw_assistants:
        assistants = [a for a in ASSISTANTS if not (a == "kilo" and args.server == "kilo-mcp")]
    else:
        assistants = raw_assistants
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
            apply=getattr(args, "apply", False),
            expect_hash=getattr(args, "expect_hash", None),
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


def cmd_install_launcher(args: argparse.Namespace) -> int:
    src_repo = pathlib.Path(args.source_repo).resolve() if getattr(args, "source_repo", None) else None
    res = install_launcher(
        home=args.home,
        target_path=getattr(args, "path", None),
        source_repo=src_repo,
        dry_run=args.dry_run,
        apply=getattr(args, "apply", False),
        expect_hash=getattr(args, "expect_hash", None),
        expect_plan_hash=args.expect_plan_hash,
    )
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if not res.get("ok"):
            print(f"[error] {res.get('error', 'Execution refused')}", file=sys.stderr)
        elif res.get("dry_run"):
            print(f"[preview] Launcher plan (hash: {res['plan_hash']}):")
            for item in res["plan"]:
                print(f"  {item['action'].upper():<8} {item['path']} ({item['reason']})")
            print(f"To apply: ai-orch install-launcher --apply --expect-hash {res['plan_hash']}")
        else:
            print(f"[ok] Launcher {res.get('action', 'installed')} at {res['path']} (hash: {res['plan_hash']}).")
    return 0 if res.get("ok") else 1


def cmd_register_broker(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    res = register_broker_mcp(
        assistants=args.assistants,
        scope=args.scope,
        workspace=ws,
        home=args.home,
        server_name=getattr(args, "server_name", None),
        dry_run=args.dry_run,
        apply=getattr(args, "apply", False),
        expect_hash=getattr(args, "expect_hash", None),
        expect_plan_hash=args.expect_plan_hash,
    )
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if not res.get("ok"):
            print(f"[error] {res.get('error', 'Execution refused')}", file=sys.stderr)
        elif res.get("dry_run"):
            print(f"[preview] Broker MCP registration plan ({len(res['plan'])} client(s), hash: {res['plan_hash']}):")
            for item in res["plan"]:
                print(f"  {item['action'].upper():<8} [{item.get('assistant', '')}] {item['path']} ({item['reason']})")
            print(f"To apply: ai-orch env register-broker --apply --expect-hash {res['plan_hash']}")
        else:
            print(f"[ok] Registered broker MCP in: {', '.join(res['updated_configs']) or 'already up to date'}. Plan hash: {res['plan_hash']}.")
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
    dry_run = args.dry_run
    if getattr(args, "apply", False) and not args.dry_run:
        dry_run = False
    res = resolve_conflicts(
        workspace=ws,
        home=args.home,
        dry_run=dry_run,
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
            if res.get("applied", 0) > 0:
                for r in res["resolved"]:
                    if r.get("action") == "update":
                        print(f"[ok] Updated legacy skill '{r['skill']}' in {r['assistant']} ({r['scope']}).")
                    elif r.get("action") == "adopt":
                        print(f"[ok] Adopted legacy skill '{r['skill']}' in {r['assistant']} ({r['scope']}) (wrote receipt).")
                    else:
                        print(f"[ok] Resolved conflict in {r['assistant']} ({r['scope']}): removed '{r.get('removed', '')}', kept '{r.get('kept', '')}'.")
            elif res.get("advice"):
                print("[ok] No actionable conflicts to resolve (advice only):")
                for adv in res["advice"]:
                    print(f"  ADVISE: {adv}")
            else:
                print("[ok] No trigger conflicts found.")
    return 0 if res.get("ok") else 1


def cmd_clean_stray(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    res = clean_stray(
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
            print(f"[ok] Cleaned {res.get('applied', 0)} item(s). Plan hash: {res['plan_hash']}.")
    return 0 if res.get("ok") else 1


def acknowledge_finding(
    finding_key: str,
    note: str = "",
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Acknowledge a doctor finding until any involved copy's content changes."""
    h = home or get_home_dir()
    ws = workspace.resolve() if workspace else None
    report = inspect_environment(ws, h)
    groups = report.get("finding_groups", [])

    matched_group = None
    exact_matches = [g for g in groups if g["group_key"] == finding_key]
    if exact_matches:
        matched_group = exact_matches[0]
    else:
        partial_matches = [
            g for g in groups
            if finding_key in g.get("names", [])
            or g.get("kind") == finding_key
            or finding_key in g.get("group_key", "")
        ]
        if len(partial_matches) == 1:
            matched_group = partial_matches[0]
        elif len(partial_matches) > 1:
            candidates = [g["group_key"] for g in partial_matches]
            return {
                "ok": False,
                "error": f"Ambiguous finding key '{finding_key}': matches multiple groups: {candidates}",
            }

    if not matched_group:
        return {
            "ok": False,
            "error": f"Finding '{finding_key}' not found among active findings in environment",
        }

    content_hashes = compute_entries_content_hashes(matched_group.get("entries", []))
    storage_key = make_ack_storage_key(matched_group["kind"], matched_group["names"], content_hashes)

    plan_item = {
        "action": "ack",
        "group_key": matched_group["group_key"],
        "kind": matched_group["kind"],
        "names": matched_group["names"],
        "content_hashes": content_hashes,
        "note": note,
    }
    plan_hash = hashlib.sha256(json.dumps([plan_item], sort_keys=True).encode("utf-8")).hexdigest()[:16]

    if expect_plan_hash and expect_plan_hash != plan_hash:
        return {
            "ok": False,
            "error": f"Plan hash mismatch: expected {expect_plan_hash}, computed {plan_hash}",
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "plan": [plan_item],
            "plan_hash": plan_hash,
            "group_key": matched_group["group_key"],
            "storage_key": storage_key,
        }

    with env_lock(h):
        acks = load_doctor_acks(h)
        # Prune any previous acks for the exact same group_key
        for old_k in list(acks.keys()):
            old_v = acks[old_k]
            if isinstance(old_v, dict) and old_v.get("group_key") == matched_group["group_key"]:
                del acks[old_k]
        acks[storage_key] = {
            "group_key": matched_group["group_key"],
            "kind": matched_group["kind"],
            "names": matched_group["names"],
            "content_hashes": content_hashes,
            "note": note,
            "acknowledged_at": datetime.now(timezone.utc).isoformat(),
        }
        save_doctor_acks(acks, h)

    return {
        "ok": True,
        "dry_run": False,
        "group_key": matched_group["group_key"],
        "storage_key": storage_key,
        "acknowledged": True,
        "plan_hash": plan_hash,
    }


def unacknowledge_finding(
    finding_key: str,
    workspace: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    dry_run: bool = False,
    expect_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Remove persistent acknowledgment for a doctor finding."""
    h = home or get_home_dir()
    with env_lock(h):
        acks = load_doctor_acks(h)
        matched_storage_keys = []
        for k, v in acks.items():
            if k == finding_key:
                matched_storage_keys.append(k)
            elif isinstance(v, dict):
                if v.get("group_key") == finding_key:
                    matched_storage_keys.append(k)
                elif finding_key in v.get("names", []):
                    matched_storage_keys.append(k)
                elif v.get("kind") == finding_key:
                    matched_storage_keys.append(k)
                elif finding_key in k:
                    matched_storage_keys.append(k)

        if not matched_storage_keys:
            return {
                "ok": False,
                "error": f"Finding '{finding_key}' is not acknowledged in doctor-ack.json",
            }
        # If multiple match, check if they all share the same group_key or if there is an exact group_key match
        exact = [k for k in matched_storage_keys if k == finding_key or (isinstance(acks[k], dict) and acks[k].get("group_key") == finding_key)]
        if exact:
            matched_storage_keys = exact

        matched_group_keys = set(acks[k].get("group_key", k) for k in matched_storage_keys if isinstance(acks[k], dict))
        if len(matched_group_keys) > 1:
            return {
                "ok": False,
                "error": f"Ambiguous finding key '{finding_key}': matches multiple acknowledgments across groups: {list(matched_group_keys)}",
            }

        target_key = matched_storage_keys[0]
        group_key = acks[target_key].get("group_key", target_key) if isinstance(acks[target_key], dict) else target_key

        plan_item = {
            "action": "unack",
            "group_key": group_key,
            "storage_keys": matched_storage_keys,
        }
        plan_hash = hashlib.sha256(json.dumps([plan_item], sort_keys=True).encode("utf-8")).hexdigest()[:16]

        if expect_plan_hash and expect_plan_hash != plan_hash:
            return {
                "ok": False,
                "error": f"Plan hash mismatch: expected {expect_plan_hash}, computed {plan_hash}",
            }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "plan": [plan_item],
                "plan_hash": plan_hash,
                "group_key": group_key,
            }

        for k in matched_storage_keys:
            if k in acks:
                del acks[k]
        save_doctor_acks(acks, h)

    return {
        "ok": True,
        "dry_run": False,
        "group_key": group_key,
        "unacknowledged": True,
        "plan_hash": plan_hash,
    }


def cmd_ack(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    res = acknowledge_finding(
        finding_key=args.finding_key,
        note=args.note,
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
                print(f"  ACK {item['group_key']} (note: {item.get('note') or 'none'})")
        else:
            print(f"[ok] Acknowledged finding '{res['group_key']}'. Plan hash: {res['plan_hash']}.")
    return 0 if res.get("ok") else 1


def cmd_unack(args: argparse.Namespace) -> int:
    ws = pathlib.Path(args.workspace).resolve() if args.workspace else None
    res = unacknowledge_finding(
        finding_key=args.finding_key,
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
                print(f"  UNACK {item['group_key']}")
        else:
            print(f"[ok] Removed acknowledgment for finding '{res['group_key']}'. Plan hash: {res['plan_hash']}.")
    return 0 if res.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", type=pathlib.Path, default=None, help="Override home directory (for testing/sandboxing)")
    ap.add_argument("--json", dest="parent_json", action="store_true", default=False, help="Output structured JSON on stdout")
    ap.add_argument("--dry-run", dest="parent_dry_run", action="store_true", default=False, help="Compute and output execution plan without modifying disk")
    ap.add_argument("--expect-plan-hash", dest="parent_expect_plan_hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    ap.add_argument("--expect-hash", dest="parent_expect_hash", default=None, help="Alias for --expect-plan-hash")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser("status", help="Verify status & drift of CLIs, skills, and MCP servers across Kilo, Claude, and Codex")
    p_st.add_argument("--workspace", default=None, help="Optional project workspace to inspect project-scope installs")
    p_st.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_st.set_defaults(func=cmd_status)

    p_il = sub.add_parser("install-launcher", help="Preview or install the version-free ~/.local/bin/ai-orch launcher")
    p_il.add_argument("--path", default=None, help="Custom launcher destination path (default: <home>/.local/bin/ai-orch)")
    p_il.add_argument("--source-repo", default=None, help="Fallback source repo root baked into launcher")
    p_il.add_argument("--dry-run", action="store_true", default=False, help="Preview plan without modifying disk (default when --apply is omitted)")
    p_il.add_argument("--apply", action="store_true", default=False, help="Write launcher executable")
    p_il.add_argument("--expect-hash", default=None, help="Refuse execution if plan/content hash does not match")
    p_il.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_il.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_il.set_defaults(func=cmd_install_launcher)

    p_rb = sub.add_parser("register-broker", help="Preview or apply broker MCP shim registration across Claude Code, Kilo, and Codex")
    p_rb.add_argument("--assistants", nargs="+", choices=[*ASSISTANTS, "all"], default=["all"])
    p_rb.add_argument("--scope", choices=SCOPES, default="global")
    p_rb.add_argument("--server-name", default=None, help="Override MCP server name (default: ai-orchestration)")
    p_rb.add_argument("--workspace", default=None)
    p_rb.add_argument("--dry-run", action="store_true", default=False, help="Preview plan without modifying disk (default when --apply is omitted)")
    p_rb.add_argument("--apply", action="store_true", default=False, help="Write client MCP config registrations")
    p_rb.add_argument("--expect-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_rb.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_rb.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_rb.set_defaults(func=cmd_register_broker)

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
    p_is.add_argument("--force", action="store_true", default=False, help="Force install even if provided by plugin or removed by conflict policy")
    p_is.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_is.set_defaults(func=cmd_install_skills)

    p_rm = sub.add_parser("register-mcp", help="Provision and register ai-orchestration broker, kilo-mcp, claude-mcp, or codex-mcp across assistants")
    p_rm.add_argument("server", choices=("kilo-mcp", "claude-mcp", "codex-mcp", *BROKER_MCP_NAMES, "broker"))
    p_rm.add_argument("--assistants", nargs="+", choices=[*ASSISTANTS, "all"], default=None)
    p_rm.add_argument("--scope", choices=SCOPES, default="global")
    p_rm.add_argument("--provision-venv", action="store_true", help="Create .venv and pip install -e if missing")
    p_rm.add_argument("--workspace", default=None)
    p_rm.add_argument("--dry-run", action="store_true", default=False, help="Compute and output execution plan without modifying disk")
    p_rm.add_argument("--apply", action="store_true", default=False, help="Apply registration plan")
    p_rm.add_argument("--expect-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
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
    p_rc.add_argument("--dry-run", action="store_true", default=False, help="Compute and display resolution plan without executing")
    p_rc.add_argument("--apply", action="store_true", default=False, help="Apply resolution plan (default if not dry-run)")
    p_rc.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_rc.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_rc.set_defaults(func=cmd_resolve_conflicts)

    p_cs = sub.add_parser("clean-stray", help="Clean stray configuration files and redundant MCP overrides")
    p_cs.add_argument("--workspace", default=None)
    p_cs.add_argument("--dry-run", action="store_true", default=False, help="Compute and display clean plan without executing")
    p_cs.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_cs.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_cs.set_defaults(func=cmd_clean_stray)

    p_ack = sub.add_parser("ack", help="Acknowledge a doctor finding until its content changes")
    p_ack.add_argument("finding_key", help="Finding key or group key to acknowledge")
    p_ack.add_argument("--note", default="", help="Optional note explaining why the finding is acknowledged")
    p_ack.add_argument("--workspace", default=None)
    p_ack.add_argument("--dry-run", action="store_true", default=False, help="Compute and display acknowledge plan without executing")
    p_ack.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_ack.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_ack.set_defaults(func=cmd_ack)

    p_unack = sub.add_parser("unack", help="Remove persistent acknowledgment for a doctor finding")
    p_unack.add_argument("finding_key", help="Finding key or group key to un-acknowledge")
    p_unack.add_argument("--workspace", default=None)
    p_unack.add_argument("--dry-run", action="store_true", default=False, help="Compute and display unacknowledge plan without executing")
    p_unack.add_argument("--expect-plan-hash", default=None, help="Refuse execution if recomputed plan hash does not match")
    p_unack.add_argument("--json", dest="sub_json", action="store_true", default=False, help="Output structured JSON on stdout")
    p_unack.set_defaults(func=cmd_unack)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    args.json = bool(getattr(args, "parent_json", False) or getattr(args, "sub_json", False))
    args.dry_run = bool(getattr(args, "parent_dry_run", False) or getattr(args, "dry_run", False))
    if not getattr(args, "expect_plan_hash", None) and getattr(args, "parent_expect_plan_hash", None):
        args.expect_plan_hash = args.parent_expect_plan_hash
    if not getattr(args, "expect_hash", None) and getattr(args, "parent_expect_hash", None):
        args.expect_hash = args.parent_expect_hash
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
