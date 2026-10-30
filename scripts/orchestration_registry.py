#!/usr/bin/env python3
"""orchestration_registry.py — Workspace identity, explicit projects, nesting & registry.

Stdlib-only implementation of:
  - Spec §1-§2: Workspace identity ([workspace] uuid, id, title; [[workspace.projects]])
  - SQLite registry (<global config dir>/broker/registry.sqlite) in WAL mode
  - Preview-by-default plans with plan_hash and --apply --expect-hash verification
  - Move detection, symlink & device/inode re-check verification
  - Project discovery with exclusions (hidden, git-ignored, build/venv dirs, inner workspaces)
  - Nesting rule: nearest registered workspace owns task trees; inner workspaces appear as sub_workspaces
  - resolve_workspace_for_path(path) resolution helper
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime
import hashlib
import json
import logging
import os
import pathlib
import concurrent.futures
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Iterator

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore

# ---------------------------------------------------------------------------
# Path resolution to companion modules
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ORCH_CONFIG_DIR = (
    REPO_ROOT
    / "plugins"
    / "shared"
    / "skills"
    / "orchestration-setup"
    / "scripts"
)
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent

if str(ORCH_CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_CONFIG_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from orchestration_broker_lock import get_global_config_dir
except ImportError:
    def get_global_config_dir(env_var: str = "AI_ORCHESTRATION_CONFIG") -> pathlib.Path:
        env_val = os.environ.get(env_var)
        if env_val:
            p = pathlib.Path(env_val).expanduser().resolve()
            if p.is_file() or p.suffix == ".toml" or p.name.endswith(".toml"):
                return p.parent
            return p
        return pathlib.Path.home() / ".config" / "ai-orchestration"

try:
    from orchestration_config import (
        inspect_project_config,
        find_project_config_path,
        config_lock,
        load_toml_file,
        dump_toml,
        set_toml_value,
        is_valid_workspace_slug,
        is_valid_project_slug,
        is_valid_uuid4,
        resolve_host_id,
        resolve_hosts_table,
        normalize_host_id,
    )
except ImportError:
    # Standalone fallbacks if orchestration_config cannot be imported directly
    def normalize_host_id(raw: str | None = None) -> str:
        if raw is None:
            try:
                raw = socket.gethostname()
            except Exception:
                raw = "localhost"
        s = str(raw or "").strip()
        if "." in s:
            s = s.split(".", 1)[0]
        s = re.sub(r"[^a-z0-9_-]+", "-", s.lower())
        s = re.sub(r"-{2,}", "-", s)
        s = re.sub(r"^[^a-z0-9]+", "", s).rstrip("_-")
        return s[:63].rstrip("_-") if s else "localhost"

    def resolve_host_id(
        cfg: dict[str, Any] | None = None,
        global_path: pathlib.Path | None = None,
        hostname: str | None = None,
        workspace: pathlib.Path | str | None = None,
    ) -> str:
        if isinstance(cfg, dict):
            hid = cfg.get("host", {}).get("id")
            if isinstance(hid, str) and hid.strip():
                return hid.strip()
        env_hid = os.environ.get("AI_ORCH_HOST_ID")
        if hostname is None and env_hid and env_hid.strip():
            return normalize_host_id(env_hid.strip())
        return normalize_host_id(hostname)

    def resolve_hosts_table(
        cfg: dict[str, Any] | None = None,
        global_path: pathlib.Path | None = None,
        workspace: pathlib.Path | str | None = None,
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(cfg, dict):
            return {}
        raw_hosts = cfg.get("hosts")
        if not isinstance(raw_hosts, dict):
            return {}
        return {str(k): dict(v) for k, v in raw_hosts.items() if isinstance(v, dict)}

    def inspect_project_config(
        ws: pathlib.Path | str,
        global_path: pathlib.Path | str | None = None,
    ) -> dict[str, Any]:
        ws_p = pathlib.Path(ws)
        local_dot = ws_p / ".ai-orchestration.local.toml"
        gpath = pathlib.Path(global_path) if global_path else (get_global_config_dir() / "orchestration.toml")
        if gpath.is_dir():
            gpath = gpath / "orchestration.toml"
        ext_path = gpath.parent / "projects" / ws_p.resolve().name / "orchestration.toml"
        write_path = local_dot if local_dot.is_file() else ext_path
        cands = [
            (local_dot, ".ai-orchestration.local.toml", False),
            (ext_path, f"~/.config/ai-orchestration/projects/{ws_p.resolve().name}/orchestration.toml", False),
            (ws_p / "orchestration.toml", "orchestration.toml", True),
            (ws_p / ".ai-orchestration" / "orchestration.toml", ".ai-orchestration/orchestration.toml", True),
            (ws_p / "tasks" / "orchestration.toml", "tasks/orchestration.toml", True),
            (ws_p / ".ai-orchestration.toml", ".ai-orchestration.toml", True),
        ]
        existing = [
            {"path": p, "label": lbl, "is_legacy": is_leg}
            for p, lbl, is_leg in cands
            if p.is_file()
        ]
        if existing:
            act = existing[0]
            return {
                "path": act["path"],
                "write_path": write_path,
                "exists": True,
                "is_legacy": bool(act["is_legacy"]),
                "label": act["label"],
                "candidates": existing,
                "legacy_paths": [c["path"] for c in existing if c["is_legacy"]],
                "warnings": [],
            }
        return {
            "path": ext_path,
            "write_path": write_path,
            "exists": False,
            "is_legacy": False,
            "label": cands[1][1],
            "candidates": [],
            "legacy_paths": [],
            "warnings": [],
        }

    def find_project_config_path(
        ws: pathlib.Path,
        global_path: pathlib.Path | None = None,
        *,
        for_write: bool = False,
    ) -> pathlib.Path:
        info = inspect_project_config(ws, global_path)
        return info["write_path"] if for_write else info["path"]

    @contextlib.contextmanager
    def config_lock(target_path: pathlib.Path | str) -> Iterator[pathlib.Path]:
        target = pathlib.Path(target_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_file = target.parent / f"{target.name}.lock"
        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield lock_file
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)

    def load_toml_file(path: pathlib.Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        if tomllib is not None:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        raise RuntimeError("tomllib required")

    def dump_toml(data: dict[str, Any]) -> str:
        lines: list[str] = []
        for k, v in data.items():
            if isinstance(v, dict):
                lines.append(f"[{k}]")
                for sk, sv in v.items():
                    if isinstance(sv, list) and sv and all(isinstance(x, dict) for x in sv):
                        for item in sv:
                            lines.append(f"\n[[{k}.{sk}]]")
                            for ik, iv in item.items():
                                lines.append(f'{ik} = "{iv}"')
                    elif isinstance(sv, str):
                        lines.append(f'{sk} = "{sv}"')
                    elif isinstance(sv, bool):
                        lines.append(f'{sk} = {"true" if sv else "false"}')
                    elif isinstance(sv, (int, float)):
                        lines.append(f"{sk} = {sv}")
        return "\n".join(lines) + "\n"

    def set_toml_value(text: str, table_path: list[str], key: str, value: Any) -> str:
        raise NotImplementedError("set_toml_value fallback")

    def is_valid_workspace_slug(slug: Any) -> bool:
        return isinstance(slug, str) and bool(re.match(r"^[a-z0-9][a-z0-9-]{1,47}$", slug))

    def is_valid_project_slug(slug: Any) -> bool:
        return isinstance(slug, str) and (slug == "_workspace" or bool(re.match(r"^[a-z0-9][a-z0-9-]{1,47}$", slug)))

    def is_valid_uuid4(val: Any) -> bool:
        if not isinstance(val, str):
            return False
        try:
            u = uuid.UUID(val)
            return u.version == 4
        except Exception:
            return False

logger = logging.getLogger("orchestration_registry")

EXCLUDE_DIR_NAMES = {
    "node_modules",
    "build",
    "dist",
    "target",
    "venv",
    ".venv",
    "scratch",
    "fixtures",
    "references",
}

# ---------------------------------------------------------------------------
# Database & Locking
# ---------------------------------------------------------------------------


def get_db_path(config_dir: pathlib.Path | str | None = None) -> pathlib.Path:
    cdir = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    broker_dir = cdir / "broker"
    broker_dir.mkdir(parents=True, exist_ok=True)
    return broker_dir / "registry.sqlite"


def get_lock_path(config_dir: pathlib.Path | str | None = None) -> pathlib.Path:
    cdir = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    broker_dir = cdir / "broker"
    broker_dir.mkdir(parents=True, exist_ok=True)
    return broker_dir / "registry.lock"


def get_hub_registry_path(config_dir: pathlib.Path | str | None = None) -> pathlib.Path:
    """Return path to the portable hub project registry JSON (`<config_dir>/broker/hub_registry.json`)."""
    env_hub = os.environ.get("AI_ORCH_HUB_REGISTRY")
    if env_hub and env_hub.strip() and config_dir is None:
        return pathlib.Path(env_hub.strip()).expanduser().resolve()
    cdir = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    broker_dir = cdir / "broker"
    broker_dir.mkdir(parents=True, exist_ok=True)
    return broker_dir / "hub_registry.json"


def _resolve_current_host_id(
    config_dir: pathlib.Path | str | None = None,
    workspace: pathlib.Path | str | None = None,
    host_override: str | None = None,
) -> str:
    if host_override and str(host_override).strip():
        return normalize_host_id(str(host_override).strip())
    gpath = (pathlib.Path(config_dir).resolve() / "orchestration.toml") if config_dir is not None else None
    try:
        return resolve_host_id(global_path=gpath, workspace=workspace)
    except Exception:
        return normalize_host_id(None)


def _read_workspace_convention_version(ws_path: pathlib.Path) -> str | None:
    """Read `tasks/convention_version` (or legacy `.convention-version` / `.convention_version`) if present."""
    tasks_dir = ws_path / "tasks"
    if not tasks_dir.is_dir():
        return None
    for fname in ("convention_version", ".convention-version", ".convention_version"):
        cfile = tasks_dir / fname
        if cfile.is_file() and not cfile.is_symlink():
            try:
                raw = cfile.read_text(encoding="utf-8", errors="replace").strip()
                if raw:
                    first = raw.splitlines()[0].strip()
                    if first:
                        return first
            except Exception:
                pass
    return None


_REGISTRY_LOCK_STATE = threading.local()


@contextlib.contextmanager
def registry_lock(
    config_dir: pathlib.Path | str | None = None,
    timeout: float = 10.0,
) -> Iterator[pathlib.Path]:
    """Exclusive fcntl.flock with a deadline on <global config dir>/broker/registry.lock.
    Re-entrant for the current thread.
    """
    lock_file = get_lock_path(config_dir).resolve()
    held = getattr(_REGISTRY_LOCK_STATE, "held_locks", None)
    if held is None:
        held = {}
        _REGISTRY_LOCK_STATE.held_locks = held

    lock_key = str(lock_file)
    if lock_key in held and held[lock_key] > 0:
        held[lock_key] += 1
        try:
            yield lock_file
        finally:
            held[lock_key] -= 1
            if held[lock_key] == 0:
                del held[lock_key]
        return

    lock_file.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.time() + timeout
    acquired = False

    try:
        while time.time() < deadline:
            if fcntl is None:
                acquired = True
                break
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                time.sleep(0.05)

        if not acquired:
            raise TimeoutError(f"Could not acquire registry lock on {lock_file} within {timeout}s")

        held[lock_key] = 1
        yield lock_file
    finally:
        if acquired:
            if lock_key in held:
                held[lock_key] -= 1
                if held[lock_key] == 0:
                    del held[lock_key]
            if fcntl is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        try:
            os.close(fd)
        except OSError:
            pass


def get_connection(db_path: pathlib.Path) -> sqlite3.Connection:
    """Open SQLite connection with WAL mode and foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize SQLite schema if not present and apply additive column migrations."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                uuid TEXT PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                title TEXT,
                canonical_path TEXT NOT NULL UNIQUE,
                device INTEGER NOT NULL,
                inode INTEGER NOT NULL,
                registered_at TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                primary_host TEXT,
                reference_repo TEXT,
                mirror_repo TEXT,
                convention_version TEXT,
                paths_json TEXT NOT NULL DEFAULT '{}',
                registry_source TEXT NOT NULL DEFAULT 'local'
            );
            """
        )
        # Additive migration for existing databases
        ws_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(workspaces);").fetchall()
        }
        for col_name, col_def in (
            ("primary_host", "TEXT"),
            ("reference_repo", "TEXT"),
            ("mirror_repo", "TEXT"),
            ("convention_version", "TEXT"),
            ("paths_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("registry_source", "TEXT NOT NULL DEFAULT 'local'"),
        ):
            if col_name not in ws_cols:
                conn.execute(f"ALTER TABLE workspaces ADD COLUMN {col_name} {col_def};")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                uuid TEXT PRIMARY KEY,
                workspace_uuid TEXT NOT NULL REFERENCES workspaces(uuid) ON DELETE CASCADE,
                slug TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                primary_host TEXT,
                reference_repo TEXT,
                mirror_repo TEXT,
                convention_version TEXT,
                UNIQUE (workspace_uuid, slug),
                UNIQUE (workspace_uuid, rel_path)
            );
            """
        )
        proj_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(projects);").fetchall()
        }
        for col_name, col_def in (
            ("primary_host", "TEXT"),
            ("reference_repo", "TEXT"),
            ("mirror_repo", "TEXT"),
            ("convention_version", "TEXT"),
        ):
            if col_name not in proj_cols:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {col_name} {col_def};")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_host_paths (
                workspace_uuid TEXT NOT NULL REFERENCES workspaces(uuid) ON DELETE CASCADE,
                host TEXT NOT NULL,
                path TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (workspace_uuid, host)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_ws ON projects(workspace_uuid);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspaces_path ON workspaces(canonical_path);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspaces_slug ON workspaces(slug);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ws_host_paths_host ON workspace_host_paths(host);"
        )


# ---------------------------------------------------------------------------
# Portable Hub Registry (`hub_registry.json`) & SQLite Cache Sync
# ---------------------------------------------------------------------------


def load_hub_registry(config_dir: pathlib.Path | str | None = None) -> dict[str, Any]:
    """Load the portable hub project registry JSON document."""
    hub_path = get_hub_registry_path(config_dir)
    if not hub_path.is_file():
        return {
            "schema_version": 1,
            "snapshot_version": 0,
            "updated_at": None,
            "projects": [],
        }
    try:
        data = json.loads(hub_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            projs = data.get("projects")
            if not isinstance(projs, list):
                projs = []
            return {
                "schema_version": int(data.get("schema_version", 1)),
                "snapshot_version": int(data.get("snapshot_version", 1 if projs else 0)),
                "updated_at": data.get("updated_at"),
                "projects": [dict(p) for p in projs if isinstance(p, dict)],
            }
    except Exception:
        pass
    return {
        "schema_version": 1,
        "snapshot_version": 0,
        "updated_at": None,
        "projects": [],
    }


def save_hub_registry(
    doc: dict[str, Any],
    config_dir: pathlib.Path | str | None = None,
) -> pathlib.Path:
    """Atomically write the portable hub project registry JSON document."""
    hub_path = get_hub_registry_path(config_dir)
    hub_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    projs = [dict(p) for p in doc.get("projects", []) if isinstance(p, dict)]
    projs.sort(key=lambda item: (str(item.get("slug") or item.get("id") or ""), str(item.get("uuid") or "")))
    snap_ver = doc.get("snapshot_version")
    if not isinstance(snap_ver, int) or snap_ver <= 0:
        prev = load_hub_registry(config_dir)
        snap_ver = int(prev.get("snapshot_version", 0)) + 1
    payload = {
        "schema_version": int(doc.get("schema_version", 1)),
        "snapshot_version": snap_ver,
        "updated_at": doc.get("updated_at") or now,
        "projects": projs,
    }
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    tmp_file = hub_path.parent / f"{hub_path.name}.tmp.{os.getpid()}"
    tmp_file.write_text(text, encoding="utf-8")
    os.replace(str(tmp_file), str(hub_path))
    return hub_path


def find_hub_project_entry(
    doc: dict[str, Any],
    *,
    ws_uuid: str | None = None,
) -> dict[str, Any] | None:
    """Find a matching project/workspace entry in the portable hub registry strictly by `uuid`.

    An existing hub entry may be adopted only through an explicit UUID link (same UUID already
    in the project's config, or an explicit `--link <uuid>`). Never matches by slug or path.
    """
    if not ws_uuid or not isinstance(ws_uuid, str):
        return None
    target_uuid = ws_uuid.strip()
    if not is_valid_uuid4(target_uuid):
        return None
    projs = doc.get("projects", [])
    if not isinstance(projs, list):
        return None
    for p in projs:
        if isinstance(p, dict) and p.get("uuid") == target_uuid:
            return p
    return None


def upsert_hub_project_entry(
    config_dir: pathlib.Path | str | None,
    *,
    ws_uuid: str,
    ws_slug: str,
    ws_title: str | None = None,
    host_id: str | None = None,
    host_path: str | None = None,
    paths: dict[str, str] | None = None,
    primary_host: str | None = None,
    reference_repo: str | None = None,
    mirror_repo: str | None = None,
    convention_version: str | None = None,
    subprojects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Insert or update an entry in `hub_registry.json` keyed strictly by `ws_uuid`.

    Never merges two different projects just because they share a display slug; if another
    UUID already uses `ws_slug`, raises `ValueError` unless it is the same `ws_uuid`.
    """
    if not is_valid_uuid4(ws_uuid):
        raise ValueError(f"Invalid workspace UUID '{ws_uuid}': must be a valid UUID4")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc = load_hub_registry(config_dir)
    projs = list(doc.get("projects", []))
    target_idx: int | None = None
    for idx, p in enumerate(projs):
        if p.get("uuid") == ws_uuid:
            target_idx = idx
            break
        if (p.get("slug") == ws_slug or p.get("id") == ws_slug) and p.get("uuid") != ws_uuid:
            raise ValueError(
                f"Slug '{ws_slug}' is already registered in hub registry to UUID '{p.get('uuid')}' (cannot merge with '{ws_uuid}')"
            )

    existing = dict(projs[target_idx]) if target_idx is not None else {}
    merged_paths: dict[str, str] = {}
    if isinstance(existing.get("paths"), dict):
        for hk, hv in existing["paths"].items():
            if isinstance(hk, str) and isinstance(hv, str) and hv.strip():
                merged_paths[hk] = hv.strip()
    if isinstance(paths, dict):
        for hk, hv in paths.items():
            if isinstance(hk, str) and isinstance(hv, str) and hv.strip():
                merged_paths[normalize_host_id(hk)] = hv.strip()
    if host_id and host_path:
        merged_paths[normalize_host_id(host_id)] = str(host_path).strip()

    eff_title = ws_title if ws_title is not None else existing.get("title")
    eff_primary = primary_host if primary_host is not None else existing.get("primary_host")
    if not eff_primary and host_id:
        eff_primary = normalize_host_id(host_id)
    eff_ref = reference_repo if reference_repo is not None else existing.get("reference_repo")
    eff_mirror = (
        mirror_repo
        if mirror_repo is not None
        else (existing.get("mirror_repo") or existing.get("mirror"))
    )
    eff_conv = convention_version if convention_version is not None else existing.get("convention_version")

    if subprojects is not None:
        norm_subs: list[dict[str, Any]] = []
        for sp in subprojects:
            if not isinstance(sp, dict):
                continue
            sp_slug = str(sp.get("slug") or sp.get("id") or "_workspace")
            sp_rel = str(sp.get("rel_path") or sp.get("path") or ".")
            sp_uuid = str(sp.get("uuid") or portable_project_uuid(ws_uuid, sp_rel))
            norm_subs.append({
                "uuid": sp_uuid,
                "id": sp_slug,
                "slug": sp_slug,
                "path": sp_rel,
                "rel_path": sp_rel,
                "convention_version": sp.get("convention_version") or eff_conv,
            })
    else:
        norm_subs = list(existing.get("subprojects", []))

    entry: dict[str, Any] = {
        "uuid": ws_uuid,
        "id": ws_slug,
        "slug": ws_slug,
        "title": eff_title,
        "primary_host": eff_primary,
        "paths": merged_paths,
        "reference_repo": eff_ref,
        "mirror_repo": eff_mirror,
        "mirror": eff_mirror,
        "convention_version": eff_conv,
        "subprojects": norm_subs,
        "registered_at": existing.get("registered_at") or now,
        "updated_at": now,
    }
    if target_idx is not None:
        projs[target_idx] = entry
    else:
        projs.append(entry)
    doc["projects"] = projs
    doc["snapshot_version"] = int(doc.get("snapshot_version", 0)) + 1
    doc["updated_at"] = now
    save_hub_registry(doc, config_dir)
    return entry


def remove_hub_project_entry(
    ws_uuid_or_slug: str,
    config_dir: pathlib.Path | str | None = None,
) -> bool:
    """Remove an entry from `hub_registry.json` by UUID or slug."""
    doc = load_hub_registry(config_dir)
    projs = list(doc.get("projects", []))
    filtered = [
        p
        for p in projs
        if p.get("uuid") != ws_uuid_or_slug
        and p.get("slug") != ws_uuid_or_slug
        and p.get("id") != ws_uuid_or_slug
    ]
    if len(filtered) == len(projs):
        return False
    doc["projects"] = filtered
    doc["snapshot_version"] = int(doc.get("snapshot_version", 0)) + 1
    doc["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_hub_registry(doc, config_dir)
    return True


def sync_hub_entry_to_sqlite_conn(
    conn: sqlite3.Connection,
    entry: dict[str, Any],
    *,
    current_host: str,
    registry_source: str = "hub",
) -> None:
    """Sync one portable hub registry entry into the local SQLite cache."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ws_uuid = str(entry["uuid"])
    ws_slug = str(entry.get("slug") or entry.get("id"))
    ws_title = entry.get("title")
    paths = entry.get("paths") if isinstance(entry.get("paths"), dict) else {}
    primary_host = entry.get("primary_host")
    ref_repo = entry.get("reference_repo")
    mirror_repo = entry.get("mirror_repo") or entry.get("mirror")
    conv_ver = entry.get("convention_version")

    existing = conn.execute(
        "SELECT * FROM workspaces WHERE uuid = ?", (ws_uuid,)
    ).fetchone()

    host_own_path = paths.get(current_host)
    local_path_str = host_own_path
    if not local_path_str and existing is not None:
        local_path_str = existing["canonical_path"]
    if not local_path_str and primary_host and paths.get(primary_host):
        local_path_str = paths[primary_host]
    if not local_path_str and paths:
        local_path_str = next(iter(paths.values()))
    if not local_path_str:
        local_path_str = f"/unmapped/{ws_slug}"

    dev = int(existing["device"]) if existing is not None else 0
    ino = int(existing["inode"]) if existing is not None else 0
    if host_own_path:
        lp = pathlib.Path(host_own_path).expanduser()
        if lp.exists() and lp.is_dir() and not lp.is_symlink():
            try:
                resolved_lp = lp.resolve()
                local_path_str = str(resolved_lp)
                paths = dict(paths)
                paths[current_host] = local_path_str
                if existing is None or (dev == 0 and ino == 0):
                    st = os.stat(resolved_lp)
                    dev, ino = st.st_dev, st.st_ino
            except OSError:
                pass

    reg_at = (
        existing["registered_at"]
        if existing is not None
        else (entry.get("registered_at") or now)
    )
    eff_source = registry_source
    if (
        existing is not None
        and "registry_source" in existing.keys()
        and existing["registry_source"] == "local"
        and entry.get("registry_source") != "hub"
    ):
        eff_source = "local"
    paths_json = json.dumps(paths, sort_keys=True)

    conn.execute(
        """
        INSERT INTO workspaces (
            uuid, slug, title, canonical_path, device, inode,
            registered_at, last_seen, primary_host, reference_repo,
            mirror_repo, convention_version, paths_json, registry_source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uuid) DO UPDATE SET
            slug = excluded.slug,
            title = excluded.title,
            canonical_path = excluded.canonical_path,
            device = excluded.device,
            inode = excluded.inode,
            last_seen = excluded.last_seen,
            primary_host = excluded.primary_host,
            reference_repo = excluded.reference_repo,
            mirror_repo = excluded.mirror_repo,
            convention_version = excluded.convention_version,
            paths_json = excluded.paths_json,
            registry_source = excluded.registry_source;
        """,
        (
            ws_uuid,
            ws_slug,
            ws_title,
            local_path_str,
            dev,
            ino,
            reg_at,
            now,
            primary_host,
            ref_repo,
            mirror_repo,
            conv_ver,
            paths_json,
            eff_source,
        ),
    )

    conn.execute("DELETE FROM workspace_host_paths WHERE workspace_uuid = ?", (ws_uuid,))
    for hk, hv in sorted(paths.items()):
        if isinstance(hk, str) and isinstance(hv, str) and hv.strip():
            conn.execute(
                """
                INSERT INTO workspace_host_paths (workspace_uuid, host, path, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_uuid, host) DO UPDATE SET
                    path = excluded.path,
                    updated_at = excluded.updated_at;
                """,
                (ws_uuid, hk, hv.strip(), now),
            )

    subprojects = entry.get("subprojects")
    if isinstance(subprojects, list) and subprojects:
        keep_sp_uuids: list[str] = []
        for sp in subprojects:
            if not isinstance(sp, dict):
                continue
            sp_slug = str(sp.get("slug") or sp.get("id") or "_workspace")
            sp_rel = str(sp.get("rel_path") or sp.get("path") or ".")
            sp_uuid = str(sp.get("uuid") or portable_project_uuid(ws_uuid, sp_rel))
            sp_conv = sp.get("convention_version") or conv_ver
            keep_sp_uuids.append(sp_uuid)
            conn.execute(
                """
                INSERT INTO projects (
                    uuid, workspace_uuid, slug, rel_path,
                    primary_host, reference_repo, mirror_repo, convention_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_uuid, slug) DO UPDATE SET
                    uuid = excluded.uuid,
                    rel_path = excluded.rel_path,
                    primary_host = excluded.primary_host,
                    reference_repo = excluded.reference_repo,
                    mirror_repo = excluded.mirror_repo,
                    convention_version = excluded.convention_version;
                """,
                (
                    sp_uuid,
                    ws_uuid,
                    sp_slug,
                    sp_rel,
                    primary_host,
                    ref_repo,
                    mirror_repo,
                    sp_conv,
                ),
            )
        if keep_sp_uuids:
            placeholders = ",".join("?" for _ in keep_sp_uuids)
            conn.execute(
                f"DELETE FROM projects WHERE workspace_uuid = ? AND uuid NOT IN ({placeholders})",
                (ws_uuid, *keep_sp_uuids),
            )


def sync_hub_registry_to_sqlite(
    config_dir: pathlib.Path | str | None = None,
    *,
    host_id: str | None = None,
    prune_missing: bool = False,
) -> int:
    """Ensure all entries in `hub_registry.json` are reflected in the local SQLite cache.

    When `prune_missing=True` (or when `hub_registry.json` exists and has a snapshot_version > 0),
    any SQLite workspace row with `registry_source = 'hub'` whose UUID is no longer present in
    `hub_registry.json` is atomically pruned from the cache.
    """
    hub_path = get_hub_registry_path(config_dir)
    if not hub_path.is_file():
        return 0
    doc = load_hub_registry(config_dir)
    projs = doc.get("projects", [])
    cur_host = _resolve_current_host_id(config_dir, host_override=host_id)
    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        with conn:
            active_uuids: list[str] = []
            for entry in projs:
                if isinstance(entry, dict) and entry.get("uuid") and (entry.get("slug") or entry.get("id")):
                    active_uuids.append(str(entry["uuid"]))
                    sync_hub_entry_to_sqlite_conn(conn, entry, current_host=cur_host, registry_source="hub")
            if prune_missing or int(doc.get("snapshot_version", 0)) > 0:
                if active_uuids:
                    placeholders = ",".join("?" for _ in active_uuids)
                    conn.execute(
                        f"DELETE FROM workspaces WHERE registry_source = 'hub' AND uuid NOT IN ({placeholders})",
                        tuple(active_uuids),
                    )
                else:
                    conn.execute("DELETE FROM workspaces WHERE registry_source = 'hub'")
        return len(projs)
    finally:
        conn.close()


def replace_hub_snapshot_cache(
    config_dir: pathlib.Path | str | None,
    remote_items: list[dict[str, Any]],
    *,
    host_id: str | None = None,
    snapshot_version: int | None = None,
) -> dict[str, Any]:
    """Atomically replace the local hub snapshot (`hub_registry.json`) and prune removed hub rows from `registry.sqlite`."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cur_host = _resolve_current_host_id(config_dir, host_override=host_id)
    prev_doc = load_hub_registry(config_dir)
    next_snap_ver = (
        int(snapshot_version)
        if isinstance(snapshot_version, int) and snapshot_version > 0
        else int(prev_doc.get("snapshot_version", 0)) + 1
    )

    norm_entries: list[dict[str, Any]] = []
    for item in remote_items:
        if not isinstance(item, dict):
            continue
        raw_uuid = item.get("uuid")
        raw_slug = item.get("slug") or item.get("id")
        if not raw_uuid or not raw_slug or not is_valid_uuid4(str(raw_uuid)):
            continue
        ws_uuid = str(raw_uuid)
        ws_slug = str(raw_slug)
        raw_paths = item.get("paths") if isinstance(item.get("paths"), dict) else {}
        clean_paths = {
            normalize_host_id(str(hk)): str(hv).strip()
            for hk, hv in raw_paths.items()
            if isinstance(hk, str) and isinstance(hv, str) and str(hv).strip()
        }
        raw_subs = item.get("projects") or item.get("subprojects") or []
        norm_subs: list[dict[str, Any]] = []
        if isinstance(raw_subs, list):
            for sp in raw_subs:
                if not isinstance(sp, dict):
                    continue
                sp_slug = str(sp.get("slug") or sp.get("id") or "_workspace")
                sp_rel = str(sp.get("rel_path") or sp.get("path") or ".")
                sp_uuid = str(sp.get("uuid") or portable_project_uuid(ws_uuid, sp_rel))
                norm_subs.append({
                    "uuid": sp_uuid,
                    "id": sp_slug,
                    "slug": sp_slug,
                    "path": sp_rel,
                    "rel_path": sp_rel,
                    "convention_version": sp.get("convention_version") or item.get("convention_version"),
                })
        norm_entries.append({
            "uuid": ws_uuid,
            "id": ws_slug,
            "slug": ws_slug,
            "title": item.get("title"),
            "primary_host": item.get("primary_host"),
            "paths": clean_paths,
            "reference_repo": item.get("reference_repo"),
            "mirror_repo": item.get("mirror_repo") or item.get("mirror"),
            "mirror": item.get("mirror_repo") or item.get("mirror"),
            "convention_version": item.get("convention_version"),
            "subprojects": norm_subs,
            "registry_source": "hub",
            "registered_at": item.get("registered_at") or now,
            "updated_at": item.get("updated_at") or now,
        })

    # Preserve locally registered entries in hub_registry.json alongside the refreshed hub snapshot
    hub_uuids = {e["uuid"] for e in norm_entries}
    db_path = get_db_path(config_dir)
    if db_path.is_file():
        conn = get_connection(db_path)
        try:
            local_rows = conn.execute(
                "SELECT uuid FROM workspaces WHERE registry_source = 'local'"
            ).fetchall()
            local_uuids = {str(r["uuid"]) for r in local_rows}
        finally:
            conn.close()
        for prev_e in prev_doc.get("projects", []):
            if isinstance(prev_e, dict) and str(prev_e.get("uuid") or "") in local_uuids and str(prev_e.get("uuid") or "") not in hub_uuids:
                kept = copy.deepcopy(prev_e)
                kept["registry_source"] = "local"
                norm_entries.append(kept)

    new_doc = {
        "schema_version": 1,
        "snapshot_version": next_snap_ver,
        "updated_at": now,
        "projects": norm_entries,
    }
    save_hub_registry(new_doc, config_dir)
    sync_hub_registry_to_sqlite(config_dir, host_id=cur_host, prune_missing=True)
    return new_doc



# ---------------------------------------------------------------------------
# Validation & Path Verification Helpers
# ---------------------------------------------------------------------------


def sanitize_slug(name: str) -> str:
    """Derive a valid slug matching ^[a-z0-9][a-z0-9-]{1,47}$."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        slug = "workspace"
    elif len(slug) == 1:
        slug = f"{slug}-1"
    if not re.match(r"^[a-z0-9]", slug):
        slug = f"ws-{slug}"
    if len(slug) > 48:
        slug = slug[:48].rstrip("-")
    if len(slug) < 2:
        slug = f"{slug}0"
    return slug


def deterministic_uuid4(seed: str) -> str:
    """Generate a reproducible, valid RFC 4122 UUID4 from a deterministic seed."""
    h = bytearray(hashlib.sha256(seed.encode("utf-8")).digest()[:16])
    h[6] = (h[6] & 0x0F) | 0x40  # version 4
    h[8] = (h[8] & 0x3F) | 0x80  # variant RFC 4122
    return str(uuid.UUID(bytes=bytes(h)))


def allocate_workspace_uuid() -> str:
    """Allocate a fresh random RFC 4122 UUID4 for a new workspace."""
    return str(uuid.uuid4())


def portable_project_uuid(ws_uuid: str, rel_path: str) -> str:
    """Generate a portable, host-independent UUID4 for a subproject within a workspace (`ws_uuid` + `rel_path`)."""
    norm_rel = os.path.normpath(rel_path or ".").replace("\\", "/")
    return deterministic_uuid4(f"project:{ws_uuid}:{norm_rel}")


def check_symlinked_components(ws_path: pathlib.Path) -> None:
    """Refuse registration if the workspace path itself or any .ai-orchestration component is a symlink."""
    if ws_path.is_symlink():
        raise ValueError(f"Workspace path cannot be a symlink: {ws_path}")

    # Check .ai-orchestration directory
    dot_dir = ws_path / ".ai-orchestration"
    if dot_dir.is_symlink():
        raise ValueError(f"Refusing registration: symlinked .ai-orchestration directory: {dot_dir}")

    if dot_dir.is_dir():
        for root, dirs, files in os.walk(str(dot_dir), followlinks=False):
            for d in dirs:
                p = pathlib.Path(root) / d
                if p.is_symlink():
                    raise ValueError(f"Refusing registration: symlinked .ai-orchestration component detected at {p}")
            for f in files:
                p = pathlib.Path(root) / f
                if p.is_symlink():
                    raise ValueError(f"Refusing registration: symlinked .ai-orchestration component detected at {p}")

    # Check .ai-orchestration.local.toml
    dot_local = ws_path / ".ai-orchestration.local.toml"
    if dot_local.is_symlink():
        raise ValueError(f"Refusing registration: symlinked .ai-orchestration component detected at {dot_local}")


def check_device_inode(path: pathlib.Path) -> tuple[int, int]:
    """Verify path stat against canonical stat, refusing if device or inode do not match."""
    st1 = os.stat(path)
    canonical = path.resolve()
    st2 = os.stat(canonical)
    st3 = os.stat(str(path))
    if st1.st_dev != st2.st_dev or st1.st_ino != st2.st_ino or st1.st_dev != st3.st_dev or st1.st_ino != st3.st_ino:
        raise ValueError(
            f"Device/inode mismatch during re-check: ({st1.st_dev}, {st1.st_ino}) != ({st2.st_dev}, {st2.st_ino})"
        )
    return st1.st_dev, st1.st_ino


def _git_repo_root(path: pathlib.Path) -> pathlib.Path | None:
    """Nearest enclosing git repository root of `path` (the folder itself included), or None."""
    for cand in [path, *path.parents]:
        if (cand / ".git").exists():
            return cand
    return None


def _check_git_ignore_in_repo(repo: pathlib.Path, target: pathlib.Path, is_nested_repo: bool) -> bool:
    """Ask `repo` whether `target` is git-ignored.

    If `target` is itself a nested git repository (`is_nested_repo=True`), it is only
    considered ignored by `repo` when `repo`'s matching ignore rule is NOT a blanket
    root wildcard (`*` or `/*` used in allowlist wrapper workspaces like ai-coding-tools).
    """
    try:
        rel = target.relative_to(repo)
    except ValueError:
        return False
    if str(rel) in ("", "."):
        return False
    if not is_nested_repo:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", str(rel)],
            cwd=str(repo),
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    proc = subprocess.run(
        ["git", "check-ignore", "-v", str(rel)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False
    # Output format: <source>:<linenum>:<pattern>\t<pathname>
    for line in (proc.stdout or "").splitlines():
        tab_part = line.split("\t", 1)[0]
        parts = tab_part.split(":", 2)
        if len(parts) == 3:
            pattern = parts[2].strip()
            if pattern in ("*", "/*"):
                return False
    return True


def is_git_ignored(path: pathlib.Path, ws_path: pathlib.Path) -> bool:
    """Check whether `path` is ignored by git, asked of the workspace repo and enclosing repo.

    A workspace may group nested repositories under an outer allowlist `.gitignore` (`/*`),
    or it may contain git-ignored reference clones/directories (e.g. `security_audit/`,
    `/ansible-playbooks/`, `/liferay62/`) that happen to contain their own `.git`.
    Named ignore rules in the workspace or parent repo always win, even when `path/.git` exists.
    """
    try:
        has_own_git = (path / ".git").exists()
        ws_repo = _git_repo_root(ws_path)
        parent_repo = _git_repo_root(path.parent) if has_own_git else _git_repo_root(path)

        repos_to_check: list[pathlib.Path] = []
        if ws_repo is not None:
            repos_to_check.append(ws_repo)
        if parent_repo is not None and parent_repo not in repos_to_check:
            repos_to_check.append(parent_repo)

        for repo in repos_to_check:
            if _check_git_ignore_in_repo(repo, path, is_nested_repo=(has_own_git and repo != path)):
                return True
        return False
    except Exception:
        return False


def _match_ignore_pattern(rel_posix: str, name: str, slug: str, raw_pat: str) -> bool:
    """Match a single gitignore-style pattern against a workspace-relative path, folder name, or slug."""
    import fnmatch

    pat = raw_pat.strip()
    if not pat:
        return False
    while pat.startswith("./"):
        pat = pat[2:]
    anchored = pat.startswith("/")
    if anchored:
        pat = pat.lstrip("/")
    dir_only = pat.endswith("/")
    if dir_only:
        pat = pat.rstrip("/")
    if not pat:
        return False

    rel_norm = rel_posix.strip("/")
    if not rel_norm or rel_norm == ".":
        return False

    has_slash = "/" in pat
    if has_slash or anchored or dir_only:
        if rel_norm == pat or rel_norm.startswith(pat + "/"):
            return True
        if fnmatch.fnmatchcase(rel_norm, pat) or fnmatch.fnmatchcase(rel_norm, pat + "/*"):
            return True
        parts = rel_norm.split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            if fnmatch.fnmatchcase(prefix, pat):
                return True
        return False

    # Bare name/slug pattern (no slash, not anchored): matches folder name, project slug, or any path segment
    if fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(slug, pat):
        return True
    for part in rel_norm.split("/"):
        if fnmatch.fnmatchcase(part, pat) or fnmatch.fnmatchcase(sanitize_slug(part), pat):
            return True
    return False


class WorkspaceDiscoveryFilter:
    """Evaluates `[workspace.discovery]` include/exclude globs and `.ai-orchestration/projects-ignore`."""

    def __init__(
        self,
        include_patterns: list[str] | None = None,
        ignore_rules: list[tuple[str, bool]] | None = None,
    ) -> None:
        self.include_patterns: list[str] = [p.strip() for p in (include_patterns or []) if p and p.strip()]
        # Each rule is (pattern, is_negated)
        self.ignore_rules: list[tuple[str, bool]] = ignore_rules or []
        self.has_negations: bool = any(neg for _, neg in self.ignore_rules)

    def is_excluded(self, rel_posix: str, name: str, slug: str) -> bool:
        excluded = False
        for pat, is_negated in self.ignore_rules:
            if _match_ignore_pattern(rel_posix, name, slug, pat):
                excluded = not is_negated
        return excluded

    def can_prune_dir(self, rel_posix: str, dir_name: str) -> bool:
        """Return True if a directory can be skipped during tree walk without descending."""
        if self.has_negations:
            return False
        slug = sanitize_slug(dir_name)
        return self.is_excluded(rel_posix, dir_name, slug)

    def allows_project(self, rel_posix: str, name: str, slug: str) -> bool:
        if rel_posix in (".", ""):
            return not self.is_excluded(rel_posix, "_workspace", "_workspace")
        if self.is_excluded(rel_posix, name, slug):
            return False
        if self.include_patterns:
            return any(_match_ignore_pattern(rel_posix, name, slug, inc) for inc in self.include_patterns)
        return True


def load_workspace_discovery_filter(
    ws_path: pathlib.Path,
    config_dir: pathlib.Path | str | None = None,
) -> WorkspaceDiscoveryFilter:
    """Load discovery include/exclude rules from the active project `orchestration.toml` and `.ai-orchestration/projects-ignore`."""
    include_patterns: list[str] = []
    ignore_rules: list[tuple[str, bool]] = []

    _gpath = (pathlib.Path(config_dir).resolve() / "orchestration.toml") if config_dir is not None else None
    proj_info = inspect_project_config(ws_path, _gpath)
    cfg_cand = proj_info.get("path")
    if (
        proj_info.get("exists")
        and isinstance(cfg_cand, pathlib.Path)
        and cfg_cand.is_file()
        and not cfg_cand.is_symlink()
    ):
        try:
            data = load_toml_file(cfg_cand)
            ws_sec = data.get("workspace")
            if isinstance(ws_sec, dict):
                disc = ws_sec.get("discovery")
                if isinstance(disc, dict):
                    inc = disc.get("include")
                    if isinstance(inc, list):
                        include_patterns.extend(str(x) for x in inc if x)
                    for key in ("exclude", "ignore"):
                        exc = disc.get(key)
                        if isinstance(exc, list):
                            for item in exc:
                                s = str(item).strip()
                                if not s or s.startswith("#"):
                                    continue
                                if s.startswith("!"):
                                    ignore_rules.append((s[1:].strip(), True))
                                else:
                                    ignore_rules.append((s, False))
        except Exception:
            pass

    for ign_file in (
        ws_path / ".ai-orchestration" / "projects-ignore",
        ws_path / ".ai-orchignore",
    ):
        if ign_file.is_file() and not ign_file.is_symlink():
            try:
                for raw_line in ign_file.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("!"):
                        pat = line[1:].strip()
                        if pat:
                            ignore_rules.append((pat, True))
                    else:
                        ignore_rules.append((line, False))
            except Exception:
                pass

    return WorkspaceDiscoveryFilter(include_patterns=include_patterns, ignore_rules=ignore_rules)


def compute_plan_hash(payload: dict[str, Any]) -> str:
    """Compute sha256 hash of deterministic JSON payload (excluding existing plan_hash)."""
    data = {k: v for k, v in payload.items() if k != "plan_hash"}
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# Workspace Config Update Helpers
# ---------------------------------------------------------------------------


def write_workspace_to_config(
    cfg_path: pathlib.Path,
    ws_uuid: str,
    ws_slug: str,
    ws_title: str | None = None,
    projects: list[dict[str, Any]] | None = None,
) -> None:
    """Write or update [workspace] and [[workspace.projects]] in project config."""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with config_lock(cfg_path):
        if cfg_path.exists():
            existing_text = cfg_path.read_text(encoding="utf-8")
            # Update scalars
            new_text = set_toml_value(existing_text, ["workspace"], "uuid", ws_uuid)
            new_text = set_toml_value(new_text, ["workspace"], "id", ws_slug)
            if ws_title is not None:
                new_text = set_toml_value(new_text, ["workspace"], "title", ws_title)

            # Update projects array if provided
            if projects is not None:
                new_text = replace_projects_in_toml_text(new_text, projects)
        else:
            data: dict[str, Any] = {
                "workspace": {
                    "uuid": ws_uuid,
                    "id": ws_slug,
                }
            }
            if ws_title:
                data["workspace"]["title"] = ws_title
            if projects:
                data["workspace"]["projects"] = projects
            new_text = dump_toml(data)

        # Atomic write
        tmp_file = cfg_path.parent / f"{cfg_path.name}.tmp.{os.getpid()}"
        tmp_file.write_text(new_text, encoding="utf-8")
        os.replace(str(tmp_file), str(cfg_path))


def replace_projects_in_toml_text(text: str, projects: list[dict[str, Any]]) -> str:
    """Replace all [[workspace.projects]] blocks in TOML text."""
    lines = text.splitlines(keepends=True)
    filtered_lines: list[str] = []
    in_projects_block = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[[workspace.projects]]"):
            in_projects_block = True
            continue
        elif in_projects_block:
            if stripped.startswith("[") or stripped.startswith("[["):
                in_projects_block = False
                filtered_lines.append(line)
            # Skip lines inside the project block
            continue
        else:
            filtered_lines.append(line)

    clean_text = "".join(filtered_lines).rstrip()

    # Append new projects
    proj_lines: list[str] = []
    for p in projects:
        proj_lines.append("\n[[workspace.projects]]")
        proj_lines.append(f'uuid = "{p["uuid"]}"')
        proj_lines.append(f'id = "{p["id"]}"')
        proj_lines.append(f'path = "{p["path"]}"')

    result = clean_text + ("\n" + "\n".join(proj_lines) if proj_lines else "") + "\n"
    if tomllib is not None:
        tomllib.loads(result)
    return result


# ---------------------------------------------------------------------------
# Workspace Operations
# ---------------------------------------------------------------------------


def _get_or_allocate_pending_uuid(
    config_dir: pathlib.Path | str | None,
    pending_key: str,
) -> str:
    """Return a cached pending random UUID4 for `pending_key`, or allocate and persist a new one."""
    cdir_pending = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    pending_file = cdir_pending / "broker" / "pending_uuids.json"
    pending_map: dict[str, str] = {}
    if pending_file.is_file():
        try:
            loaded_pm = json.loads(pending_file.read_text(encoding="utf-8"))
            if isinstance(loaded_pm, dict):
                pending_map = {str(k): str(v) for k, v in loaded_pm.items() if is_valid_uuid4(v)}
        except Exception:
            pending_map = {}
    cand = pending_map.get(pending_key)
    if cand and is_valid_uuid4(cand):
        return cand
    allocated = allocate_workspace_uuid()
    pending_map[pending_key] = allocated
    try:
        pending_file.parent.mkdir(parents=True, exist_ok=True)
        pending_file.write_text(json.dumps(pending_map, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    return allocated


def _clear_pending_uuid(
    config_dir: pathlib.Path | str | None,
    *pending_keys: str,
) -> None:
    """Remove one or more keys from `pending_uuids.json` after registration/import is applied."""
    cdir_pending = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    pending_file = cdir_pending / "broker" / "pending_uuids.json"
    if not pending_file.is_file():
        return
    try:
        loaded_pm = json.loads(pending_file.read_text(encoding="utf-8"))
        if isinstance(loaded_pm, dict):
            removed = False
            for k in pending_keys:
                if k in loaded_pm:
                    del loaded_pm[k]
                    removed = True
            if removed:
                pending_file.write_text(json.dumps(loaded_pm, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _load_checkout_own_config(
    canonical: pathlib.Path,
    config_dir: pathlib.Path | str | None,
    *,
    cur_host: str,
    hub_doc: dict[str, Any],
    explicit_link_uuid: str | None = None,
) -> tuple[pathlib.Path, dict[str, Any]]:
    """Load the project config for `canonical` and return `(write_cfg_path, existing_cfg)`.

    An external config at `<config_dir>/projects/<canonical.name>/orchestration.toml` is keyed by
    directory basename (slug), so it is only treated as belonging to `canonical` when its
    `[workspace] uuid` matches `explicit_link_uuid` or is already mapped to `(cur_host, canonical)`
    in `hub_doc` or SQLite. Otherwise it belongs to another checkout that shares the same folder
    name and must not be adopted or overwritten by `canonical`.
    """
    _gpath = (pathlib.Path(config_dir).resolve() / "orchestration.toml") if config_dir is not None else None
    read_cfg_path = find_project_config_path(canonical, _gpath)
    write_cfg_path = find_project_config_path(canonical, _gpath, for_write=True)
    if not read_cfg_path.exists():
        return write_cfg_path, {}

    loaded = load_toml_file(read_cfg_path)
    try:
        is_in_tree = canonical.resolve() in read_cfg_path.resolve().parents
    except Exception:
        is_in_tree = False

    if is_in_tree:
        return write_cfg_path, loaded

    # External config under `<config_dir>/projects/<canonical.name>/orchestration.toml`
    raw_ext_uuid = loaded.get("workspace", {}).get("uuid")
    ext_uuid = raw_ext_uuid.strip() if isinstance(raw_ext_uuid, str) and raw_ext_uuid.strip() else None
    if not ext_uuid:
        return write_cfg_path, loaded

    if explicit_link_uuid and ext_uuid == explicit_link_uuid:
        return write_cfg_path, loaded

    hub_entry = find_hub_project_entry(hub_doc, ws_uuid=ext_uuid)
    if hub_entry and isinstance(hub_entry.get("paths"), dict):
        if hub_entry["paths"].get(cur_host) == str(canonical):
            return write_cfg_path, loaded
        return canonical / ".ai-orchestration.local.toml", {}

    db_p = get_db_path(config_dir)
    if db_p.exists():
        conn_c = get_connection(db_p)
        try:
            row_c = conn_c.execute(
                "SELECT canonical_path FROM workspaces WHERE uuid = ?",
                (ext_uuid,),
            ).fetchone()
            if row_c and row_c["canonical_path"] == str(canonical):
                return write_cfg_path, loaded
        finally:
            conn_c.close()

    return canonical / ".ai-orchestration.local.toml", {}


def plan_workspace_register(
    path: str | pathlib.Path | None = None,
    slug: str | None = None,
    title: str | None = None,
    config_dir: pathlib.Path | str | None = None,
    *,
    host: str | None = None,
    primary_host: str | None = None,
    reference_repo: str | None = None,
    mirror_repo: str | None = None,
    convention_version: str | None = None,
    link_uuid: str | None = None,
) -> dict[str, Any]:
    """Build a preview plan for registering a workspace."""
    raw_path = pathlib.Path(path or ".").expanduser()
    if not raw_path.exists():
        raise FileNotFoundError(f"Path does not exist: {raw_path}")

    check_symlinked_components(raw_path)
    canonical = raw_path.resolve()
    if not canonical.is_dir():
        raise NotADirectoryError(f"Workspace path is not a directory: {canonical}")

    dev, ino = check_device_inode(raw_path)

    explicit_link = link_uuid.strip() if isinstance(link_uuid, str) and link_uuid.strip() else None
    if explicit_link is not None and not is_valid_uuid4(explicit_link):
        raise ValueError(f"Invalid --link UUID '{explicit_link}': must be a valid UUID4")

    cur_host = _resolve_current_host_id(config_dir, workspace=canonical, host_override=host)
    hub_doc = load_hub_registry(config_dir)

    # Inspect project config belonging to this checkout
    cfg_path, existing_cfg = _load_checkout_own_config(
        canonical,
        config_dir,
        cur_host=cur_host,
        hub_doc=hub_doc,
        explicit_link_uuid=explicit_link,
    )
    ws_cfg = existing_cfg.get("workspace", {})

    raw_cfg_uuid = ws_cfg.get("uuid")
    cfg_uuid = raw_cfg_uuid.strip() if isinstance(raw_cfg_uuid, str) and raw_cfg_uuid.strip() else None
    if cfg_uuid is not None and not is_valid_uuid4(cfg_uuid):
        raise ValueError(f"Invalid workspace UUID '{cfg_uuid}': must be a valid UUID4")

    if explicit_link is not None and cfg_uuid is not None and cfg_uuid != explicit_link:
        raise ValueError(
            f"Conflicting workspace UUIDs: project config has '{cfg_uuid}', but --link specified '{explicit_link}'"
        )

    # An existing entry may be adopted ONLY through an explicit link:
    # (1) same UUID already in the project's config (`cfg_uuid`), or
    # (2) an explicit `--link <uuid>` (`explicit_link`).
    linked_uuid = explicit_link or cfg_uuid
    hub_entry = find_hub_project_entry(hub_doc, ws_uuid=linked_uuid) if linked_uuid else None

    if explicit_link and hub_entry and slug and slug != hub_entry.get("slug"):
        raise ValueError(
            f"Cannot link to UUID '{explicit_link}' with conflicting slug '{slug}': "
            f"hub entry has slug '{hub_entry.get('slug')}'"
        )

    ws_slug = (
        slug
        or ws_cfg.get("id")
        or (hub_entry.get("slug") if hub_entry else None)
        or sanitize_slug(canonical.name)
    )
    if not is_valid_workspace_slug(ws_slug):
        raise ValueError(
            f"Invalid workspace slug '{ws_slug}': must match ^[a-z0-9][a-z0-9-]{{1,47}}$"
        )

    if linked_uuid:
        ws_uuid = linked_uuid
    else:
        ws_uuid = _get_or_allocate_pending_uuid(config_dir, f"{cur_host}:{canonical}")

    ws_title = (
        title
        if title is not None
        else (ws_cfg.get("title") or (hub_entry.get("title") if hub_entry else None))
    )

    if not is_valid_uuid4(ws_uuid):
        raise ValueError(f"Invalid workspace UUID '{ws_uuid}': must be a valid UUID4")
    eff_primary = (
        normalize_host_id(primary_host)
        if primary_host
        else (ws_cfg.get("primary_host") or (hub_entry.get("primary_host") if hub_entry else None) or cur_host)
    )
    eff_ref = (
        reference_repo
        if reference_repo is not None
        else (ws_cfg.get("reference_repo") or (hub_entry.get("reference_repo") if hub_entry else None))
    )
    eff_mirror = (
        mirror_repo
        if mirror_repo is not None
        else (
            ws_cfg.get("mirror_repo")
            or ws_cfg.get("mirror")
            or (hub_entry.get("mirror_repo") or hub_entry.get("mirror") if hub_entry else None)
        )
    )
    eff_conv = (
        convention_version
        if convention_version is not None
        else (
            _read_workspace_convention_version(canonical)
            or ws_cfg.get("convention_version")
            or (hub_entry.get("convention_version") if hub_entry else None)
        )
    )

    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        # Check if uuid already registered
        row_by_uuid = conn.execute(
            "SELECT * FROM workspaces WHERE uuid = ?", (ws_uuid,)
        ).fetchone()

        if explicit_link is not None and hub_entry is None and row_by_uuid is None:
            raise ValueError(
                f"Cannot link workspace: UUID '{explicit_link}' not found in hub registry"
            )

        # Refuse if slug is already registered to a different UUID in hub_registry.json or SQLite
        for hp in hub_doc.get("projects", []):
            if (
                isinstance(hp, dict)
                and (hp.get("slug") == ws_slug or hp.get("id") == ws_slug)
                and hp.get("uuid") != ws_uuid
            ):
                raise ValueError(
                    f"Slug '{ws_slug}' is already registered in hub registry to workspace '{hp.get('uuid')}' "
                    f"(use --link {hp.get('uuid')} to link the same project, or --id <slug> for a distinct project)"
                )

        row_by_slug = conn.execute(
            "SELECT * FROM workspaces WHERE slug = ? AND uuid != ?",
            (ws_slug, ws_uuid),
        ).fetchone()
        if row_by_slug:
            raise ValueError(
                f"Slug '{ws_slug}' is already registered to workspace '{row_by_slug['uuid']}' "
                f"(use --link {row_by_slug['uuid']} to link the same project, or --id <slug> for a distinct project)"
            )

        # Check if canonical_path registered by another uuid
        row_by_path = conn.execute(
            "SELECT * FROM workspaces WHERE canonical_path = ? AND uuid != ?",
            (str(canonical), ws_uuid),
        ).fetchone()

        action = "register"
        moved_from: str | None = None

        if row_by_uuid:
            old_path = row_by_uuid["canonical_path"]
            if old_path != str(canonical):
                action = "move"
                moved_from = old_path
            else:
                action = "update"

        # Check nesting: is canonical inside an outer registered workspace?
        rows = conn.execute("SELECT * FROM workspaces WHERE uuid != ?", (ws_uuid,)).fetchall()
        outer_ws_info: dict[str, Any] | None = None
        projects_leaving: list[dict[str, Any]] = []

        for r in rows:
            r_path = pathlib.Path(r["canonical_path"]).resolve()
            if r_path in canonical.parents:
                # canonical is inside r_path -> r is outer workspace
                # Check which projects registered to r are within canonical
                p_rows = conn.execute(
                    "SELECT * FROM projects WHERE workspace_uuid = ?", (r["uuid"],)
                ).fetchall()
                for pr in p_rows:
                    p_full = (r_path / pr["rel_path"]).resolve()
                    if p_full == canonical or canonical in p_full.parents:
                        projects_leaving.append({
                            "uuid": pr["uuid"],
                            "slug": pr["slug"],
                            "rel_path": pr["rel_path"],
                        })
                outer_ws_info = {
                    "uuid": r["uuid"],
                    "slug": r["slug"],
                    "canonical_path": r["canonical_path"],
                }
                break

        existing_paths = dict(hub_entry.get("paths", {})) if (hub_entry and isinstance(hub_entry.get("paths"), dict)) else {}
        existing_paths[cur_host] = str(canonical)

        plan: dict[str, Any] = {
            "action": action,
            "workspace": {
                "uuid": ws_uuid,
                "slug": ws_slug,
                "title": ws_title,
                "canonical_path": str(canonical),
                "config_path": str(cfg_path),
                "device": dev,
                "inode": ino,
                "host": cur_host,
                "primary_host": eff_primary,
                "reference_repo": eff_ref,
                "mirror_repo": eff_mirror,
                "convention_version": eff_conv,
                "paths": existing_paths,
            },
        }
        if moved_from:
            plan["moved_from"] = moved_from
            plan["message"] = f"moved from {moved_from}"
        if outer_ws_info:
            plan["outer_workspace"] = outer_ws_info
            plan["projects_leaving"] = projects_leaving

        plan["plan_hash"] = compute_plan_hash(plan)
        return plan
    finally:
        conn.close()


def apply_workspace_register(
    plan: dict[str, Any],
    expect_hash: str | None = None,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Apply a workspace registration plan."""
    plan_hash = plan.get("plan_hash")
    if not expect_hash:
        raise ValueError(
            f"--expect-hash is required when applying. Computed plan_hash is: {plan_hash}"
        )
    if expect_hash != plan_hash:
        raise ValueError(
            f"Hash mismatch: expected {expect_hash}, computed plan_hash {plan_hash}"
        )

    ws_data = plan["workspace"]
    ws_uuid = ws_data["uuid"]
    ws_slug = ws_data["slug"]
    ws_title = ws_data.get("title")
    canonical_path = pathlib.Path(ws_data["canonical_path"])
    cfg_path = pathlib.Path(ws_data["config_path"])
    dev = ws_data["device"]
    ino = ws_data["inode"]
    cur_host = ws_data.get("host") or _resolve_current_host_id(config_dir, workspace=canonical_path)
    primary_host = ws_data.get("primary_host") or cur_host
    ref_repo = ws_data.get("reference_repo")
    mirror_repo = ws_data.get("mirror_repo")
    conv_ver = ws_data.get("convention_version") or _read_workspace_convention_version(canonical_path)
    paths_map = dict(ws_data.get("paths") or {})
    paths_map[cur_host] = str(canonical_path)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Re-verify device/inode and symlinks at apply time
    check_symlinked_components(canonical_path)
    cur_dev, cur_ino = check_device_inode(canonical_path)
    if cur_dev != dev or cur_ino != ino:
        raise ValueError(f"Device/inode changed between plan and apply: ({dev},{ino}) vs ({cur_dev},{cur_ino})")

    db_path = get_db_path(config_dir)
    with registry_lock(config_dir):
        # 1. Update config file
        write_workspace_to_config(cfg_path, ws_uuid, ws_slug, ws_title)

        # Clean up any pending_uuids.json entry for this canonical_path
        _clear_pending_uuid(config_dir, f"{cur_host}:{canonical_path}", str(canonical_path))

        # 2. Update hub registry JSON
        cfg = load_toml_file(cfg_path)
        ws_projects = cfg.get("workspace", {}).get("projects", [])
        hub_entry = upsert_hub_project_entry(
            config_dir,
            ws_uuid=ws_uuid,
            ws_slug=ws_slug,
            ws_title=ws_title,
            host_id=cur_host,
            host_path=str(canonical_path),
            paths=paths_map,
            primary_host=primary_host,
            reference_repo=ref_repo,
            mirror_repo=mirror_repo,
            convention_version=conv_ver,
            subprojects=ws_projects if ws_projects else None,
        )

        # 3. Update SQLite cache
        conn = get_connection(db_path)
        try:
            with conn:
                existing = conn.execute(
                    "SELECT registered_at FROM workspaces WHERE uuid = ?", (ws_uuid,)
                ).fetchone()
                reg_at = existing["registered_at"] if existing else now
                merged_paths = dict(hub_entry.get("paths") or paths_map)
                paths_json = json.dumps(merged_paths, sort_keys=True)

                conn.execute(
                    """
                    INSERT INTO workspaces (
                        uuid, slug, title, canonical_path, device, inode,
                        registered_at, last_seen, primary_host, reference_repo,
                        mirror_repo, convention_version, paths_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uuid) DO UPDATE SET
                        slug = excluded.slug,
                        title = excluded.title,
                        canonical_path = excluded.canonical_path,
                        device = excluded.device,
                        inode = excluded.inode,
                        last_seen = excluded.last_seen,
                        primary_host = excluded.primary_host,
                        reference_repo = excluded.reference_repo,
                        mirror_repo = excluded.mirror_repo,
                        convention_version = excluded.convention_version,
                        paths_json = excluded.paths_json;
                    """,
                    (
                        ws_uuid,
                        ws_slug,
                        ws_title,
                        str(canonical_path),
                        dev,
                        ino,
                        reg_at,
                        now,
                        primary_host,
                        ref_repo,
                        mirror_repo,
                        conv_ver,
                        paths_json,
                    ),
                )

                for hk, hv in sorted(merged_paths.items()):
                    if isinstance(hk, str) and isinstance(hv, str) and hv.strip():
                        conn.execute(
                            """
                            INSERT INTO workspace_host_paths (workspace_uuid, host, path, updated_at)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(workspace_uuid, host) DO UPDATE SET
                                path = excluded.path,
                                updated_at = excluded.updated_at;
                            """,
                            (ws_uuid, hk, hv.strip(), now),
                        )

                # If inner workspace, remove leaving projects from outer workspace in SQLite
                projects_leaving = plan.get("projects_leaving", [])
                outer_ws = plan.get("outer_workspace")
                if outer_ws and projects_leaving:
                    for pl in projects_leaving:
                        conn.execute(
                            "DELETE FROM projects WHERE workspace_uuid = ? AND uuid = ?",
                            (outer_ws["uuid"], pl["uuid"]),
                        )

                # Sync any existing projects in this workspace's config to SQLite
                for p in ws_projects:
                    conn.execute(
                        """
                        INSERT INTO projects (
                            uuid, workspace_uuid, slug, rel_path,
                            primary_host, reference_repo, mirror_repo, convention_version
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(workspace_uuid, slug) DO UPDATE SET
                            uuid = excluded.uuid,
                            rel_path = excluded.rel_path,
                            primary_host = excluded.primary_host,
                            reference_repo = excluded.reference_repo,
                            mirror_repo = excluded.mirror_repo,
                            convention_version = excluded.convention_version;
                        """,
                        (
                            p["uuid"],
                            ws_uuid,
                            p["id"],
                            p["path"],
                            primary_host,
                            ref_repo,
                            mirror_repo,
                            conv_ver,
                        ),
                    )
        finally:
            conn.close()

    return {
        "ok": True,
        "applied": True,
        "plan_hash": plan_hash,
        "workspace": {
            "uuid": ws_uuid,
            "slug": ws_slug,
            "canonical_path": str(canonical_path),
            "title": ws_title,
            "host": cur_host,
            "primary_host": primary_host,
            "reference_repo": ref_repo,
            "mirror_repo": mirror_repo,
            "convention_version": conv_ver,
            "paths": dict(hub_entry.get("paths") or paths_map),
        },
    }


def plan_workspace_unregister(
    ws_id: str,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Build a preview plan for unregistering a workspace."""
    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE uuid = ? OR slug = ?", (ws_id, ws_id)
        ).fetchone()
        if not row:
            raise KeyError(f"Workspace not found: {ws_id}")

        ws_data = dict(row)
        ws_path = pathlib.Path(ws_data["canonical_path"])

        # Check if this was an inner workspace of an outer workspace
        rows = conn.execute("SELECT * FROM workspaces WHERE uuid != ?", (ws_data["uuid"],)).fetchall()
        outer_ws_info: dict[str, Any] | None = None
        for r in rows:
            r_path = pathlib.Path(r["canonical_path"]).resolve()
            if r_path in ws_path.parents:
                outer_ws_info = {"uuid": r["uuid"], "slug": r["slug"], "canonical_path": r["canonical_path"]}
                break

        plan = {
            "action": "unregister",
            "workspace": ws_data,
        }
        if outer_ws_info:
            plan["outer_workspace"] = outer_ws_info
            plan["message"] = f"Unregistering will restore ownership of subtrees to outer workspace '{outer_ws_info['slug']}'"

        plan["plan_hash"] = compute_plan_hash(plan)
        return plan
    finally:
        conn.close()


def _evaluate_workspace_liveness_and_paths(
    conn: sqlite3.Connection,
    row_dict: dict[str, Any],
    *,
    config_dir: pathlib.Path | str | None = None,
    hub_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate stale state and merge host paths for a workspace row."""
    d = dict(row_dict)
    ws_uuid = d["uuid"]
    cpath = pathlib.Path(d["canonical_path"])
    stale = False

    paths: dict[str, str] = {}
    raw_paths_json = d.get("paths_json")
    if isinstance(raw_paths_json, str) and raw_paths_json.strip():
        try:
            loaded_p = json.loads(raw_paths_json)
            if isinstance(loaded_p, dict):
                for hk, hv in loaded_p.items():
                    if isinstance(hk, str) and isinstance(hv, str) and hv.strip():
                        paths[hk] = hv.strip()
        except Exception:
            pass
    try:
        hp_rows = conn.execute(
            "SELECT host, path FROM workspace_host_paths WHERE workspace_uuid = ?",
            (ws_uuid,),
        ).fetchall()
        for hpr in hp_rows:
            paths[str(hpr["host"])] = str(hpr["path"])
    except Exception:
        pass

    hub_entry = (
        find_hub_project_entry(hub_doc, ws_uuid=ws_uuid)
        if hub_doc is not None
        else None
    )
    if hub_entry and isinstance(hub_entry.get("paths"), dict):
        for hk, hv in hub_entry["paths"].items():
            if isinstance(hk, str) and isinstance(hv, str) and hv.strip():
                paths.setdefault(hk, hv.strip())

    cur_host = _resolve_current_host_id(config_dir)
    if str(cpath) and not str(cpath).startswith("/unmapped/"):
        if not paths or cur_host in paths or d.get("registry_source") == "local":
            paths.setdefault(cur_host, str(cpath))

    if not cpath.exists() or not cpath.is_dir():
        stale = True
    else:
        try:
            cur_st = os.stat(cpath)
            inode_matches = (cur_st.st_ino == d["inode"]) or (d["inode"] == 0)
            dev_matches = (cur_st.st_dev == d["device"]) or (d["device"] == 0)
            _gpath = (pathlib.Path(config_dir).resolve() / "orchestration.toml") if config_dir is not None else None
            cfg_path = find_project_config_path(cpath, _gpath)
            uuid_matches = False
            if cfg_path.exists():
                cfg = load_toml_file(cfg_path)
                uuid_matches = (cfg.get("workspace", {}).get("uuid") == ws_uuid)
            elif hub_entry is not None and hub_entry.get("uuid") == ws_uuid:
                uuid_matches = True

            if not inode_matches or not dev_matches or not uuid_matches:
                stale = True
        except Exception:
            stale = True

    d["stale"] = stale
    d["paths"] = paths
    d["primary_host"] = d.get("primary_host") or (hub_entry.get("primary_host") if hub_entry else None) or cur_host
    d["reference_repo"] = d.get("reference_repo") or (hub_entry.get("reference_repo") if hub_entry else None)
    d["mirror_repo"] = (
        d.get("mirror_repo")
        or (hub_entry.get("mirror_repo") or hub_entry.get("mirror") if hub_entry else None)
    )
    d["mirror"] = d["mirror_repo"]
    conv_v = (
        d.get("convention_version")
        or (_read_workspace_convention_version(cpath) if cpath.is_dir() else None)
        or (hub_entry.get("convention_version") if hub_entry else None)
    )
    d["convention_version"] = conv_v
    return d


def apply_workspace_unregister(
    plan: dict[str, Any],
    expect_hash: str | None = None,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Apply workspace unregistration."""
    plan_hash = plan.get("plan_hash")
    if not expect_hash:
        raise ValueError(
            f"--expect-hash is required when applying. Computed plan_hash is: {plan_hash}"
        )
    if expect_hash != plan_hash:
        raise ValueError(
            f"Hash mismatch: expected {expect_hash}, computed plan_hash {plan_hash}"
        )

    ws_uuid = plan["workspace"]["uuid"]
    outer_ws = plan.get("outer_workspace")

    db_path = get_db_path(config_dir)
    with registry_lock(config_dir):
        remove_hub_project_entry(ws_uuid, config_dir=config_dir)
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute("DELETE FROM workspaces WHERE uuid = ?", (ws_uuid,))

                # If outer workspace existed, re-sync outer workspace projects from its config
                if outer_ws:
                    outer_path = pathlib.Path(outer_ws["canonical_path"])
                    _gpath = (pathlib.Path(config_dir).resolve() / "orchestration.toml") if config_dir is not None else None
                    outer_cfg_path = find_project_config_path(outer_path, _gpath)
                    if outer_cfg_path.exists():
                        cfg = load_toml_file(outer_cfg_path)
                        for p in cfg.get("workspace", {}).get("projects", []):
                            conn.execute(
                                """
                                INSERT INTO projects (uuid, workspace_uuid, slug, rel_path)
                                VALUES (?, ?, ?, ?)
                                ON CONFLICT(workspace_uuid, slug) DO UPDATE SET
                                    uuid = excluded.uuid,
                                    rel_path = excluded.rel_path;
                                """,
                                (p["uuid"], outer_ws["uuid"], p["id"], p["path"]),
                            )
        finally:
            conn.close()

    return {
        "ok": True,
        "applied": True,
        "plan_hash": plan_hash,
        "unregistered": ws_uuid,
    }


def list_workspaces(config_dir: pathlib.Path | str | None = None) -> list[dict[str, Any]]:
    """List all registered workspaces with stale flags and portable hub metadata."""
    sync_hub_registry_to_sqlite(config_dir)
    hub_doc = load_hub_registry(config_dir)
    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM workspaces ORDER BY slug ASC").fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            items.append(
                _evaluate_workspace_liveness_and_paths(
                    conn,
                    dict(r),
                    config_dir=config_dir,
                    hub_doc=hub_doc,
                )
            )
        return items
    finally:
        conn.close()


def show_workspace(
    ws_id: str,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Show details of one workspace with projects and sub-workspaces."""
    sync_hub_registry_to_sqlite(config_dir)
    hub_doc = load_hub_registry(config_dir)
    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE uuid = ? OR slug = ?", (ws_id, ws_id)
        ).fetchone()
        if not row:
            raise KeyError(f"Workspace not found: {ws_id}")

        ws_data = _evaluate_workspace_liveness_and_paths(
            conn,
            dict(row),
            config_dir=config_dir,
            hub_doc=hub_doc,
        )
        cpath = pathlib.Path(ws_data["canonical_path"])

        # Fetch projects from SQLite
        proj_rows = conn.execute(
            "SELECT uuid, slug, rel_path, primary_host, reference_repo, mirror_repo, convention_version FROM projects WHERE workspace_uuid = ? ORDER BY slug ASC",
            (ws_data["uuid"],),
        ).fetchall()
        ws_data["projects"] = [dict(pr) for pr in proj_rows]

        # Find sub-workspaces (other registered workspaces inside cpath)
        all_ws = conn.execute(
            "SELECT uuid, slug, canonical_path FROM workspaces WHERE uuid != ?",
            (ws_data["uuid"],),
        ).fetchall()
        sub_workspaces: list[dict[str, Any]] = []
        for other in all_ws:
            other_p = pathlib.Path(other["canonical_path"]).resolve()
            if cpath in other_p.parents:
                sub_workspaces.append({
                    "uuid": other["uuid"],
                    "slug": other["slug"],
                    "canonical_path": other["canonical_path"],
                })
        ws_data["sub_workspaces"] = sub_workspaces
        return ws_data
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Project Discovery & Listing
# ---------------------------------------------------------------------------


def find_workspace_for_arg(
    ws_arg: str | None = None,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Resolve a workspace by slug, uuid, directory path, or cwd."""
    sync_hub_registry_to_sqlite(config_dir)
    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        if ws_arg:
            # 1. Try slug or uuid
            row = conn.execute(
                "SELECT * FROM workspaces WHERE slug = ? OR uuid = ?",
                (ws_arg, ws_arg),
            ).fetchone()
            if row:
                return dict(row)

            # 2. Try as path
            p = pathlib.Path(ws_arg).expanduser().resolve()
            row = conn.execute(
                "SELECT * FROM workspaces WHERE canonical_path = ?",
                (str(p),),
            ).fetchone()
            if row:
                return dict(row)

            # 3. Try nearest workspace for path
            ws, _ = resolve_workspace_for_path(p, config_dir=config_dir)
            if ws:
                return ws
            raise KeyError(f"Workspace not found for argument '{ws_arg}'")

        # No arg -> resolve for cwd
        cwd = pathlib.Path.cwd().resolve()
        ws, _ = resolve_workspace_for_path(cwd, config_dir=config_dir)
        if ws:
            return ws

        # Fallback: check if exactly one workspace is registered
        all_rows = conn.execute("SELECT * FROM workspaces").fetchall()
        if len(all_rows) == 1:
            return dict(all_rows[0])

        raise KeyError(
            "No workspace specified and current directory is not within any registered workspace"
        )
    finally:
        conn.close()


def plan_projects_discover(
    workspace_arg: str | None = None,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Scan workspace for candidate projects with tasks/00-INDEX.md and propose entries."""
    sync_hub_registry_to_sqlite(config_dir)
    hub_doc = load_hub_registry(config_dir)
    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        ws: dict[str, Any] | None = None
        is_registered = False
        ws_path: pathlib.Path

        if workspace_arg:
            # 1. Try slug or uuid in SQLite
            row = conn.execute(
                "SELECT * FROM workspaces WHERE slug = ? OR uuid = ?",
                (workspace_arg, workspace_arg),
            ).fetchone()
            if row:
                ws = dict(row)
                is_registered = True
                ws_path = pathlib.Path(ws["canonical_path"]).resolve()
            else:
                p = pathlib.Path(workspace_arg).expanduser().resolve()
                row = conn.execute(
                    "SELECT * FROM workspaces WHERE canonical_path = ?",
                    (str(p),),
                ).fetchone()
                if row:
                    ws = dict(row)
                    is_registered = True
                    ws_path = pathlib.Path(ws["canonical_path"]).resolve()
                elif p.is_dir():
                    # Unregistered directory passed as argument
                    ws = None
                    is_registered = False
                    ws_path = p
                else:
                    # Try nearest workspace for path
                    near_ws, _ = resolve_workspace_for_path(p, config_dir=config_dir)
                    if near_ws:
                        ws = near_ws
                        is_registered = True
                        ws_path = pathlib.Path(ws["canonical_path"]).resolve()
                    else:
                        raise KeyError(f"Workspace not found for argument '{workspace_arg}'")
        else:
            cwd = pathlib.Path.cwd().resolve()
            near_ws, _ = resolve_workspace_for_path(cwd, config_dir=config_dir)
            if near_ws:
                ws = near_ws
                is_registered = True
                ws_path = pathlib.Path(ws["canonical_path"]).resolve()
            else:
                all_rows = conn.execute("SELECT * FROM workspaces").fetchall()
                if len(all_rows) == 1:
                    ws = dict(all_rows[0])
                    is_registered = True
                    ws_path = pathlib.Path(ws["canonical_path"]).resolve()
                else:
                    ws = None
                    is_registered = False
                    ws_path = cwd

        _gpath = (pathlib.Path(config_dir).resolve() / "orchestration.toml") if config_dir is not None else None
        read_cfg_path = find_project_config_path(ws_path, _gpath)
        cfg_path = find_project_config_path(ws_path, _gpath, for_write=True)
        existing_cfg = load_toml_file(read_cfg_path) if read_cfg_path.exists() else {}
        ws_cfg = existing_cfg.get("workspace", {})

        if is_registered and ws is not None:
            ws_uuid = ws["uuid"]
            ws_slug = ws["slug"]
            ws_title = ws.get("title")
        else:
            ws_slug = ws_cfg.get("id") or sanitize_slug(ws_path.name)
            hub_entry = find_hub_project_entry(
                hub_doc,
                ws_uuid=ws_cfg.get("uuid"),
            )
            ws_uuid = (
                ws_cfg.get("uuid")
                or (hub_entry.get("uuid") if hub_entry else None)
                or deterministic_uuid4(f"unregistered-workspace:{ws_path}")
            )
            ws_title = ws_cfg.get("title") or (hub_entry.get("title") if hub_entry else None)

        # Load inner registered workspaces under ws_path
        if is_registered and ws is not None:
            other_workspaces = conn.execute(
                "SELECT * FROM workspaces WHERE uuid != ?", (ws["uuid"],)
            ).fetchall()
        else:
            other_workspaces = conn.execute("SELECT * FROM workspaces").fetchall()

        inner_workspaces: list[dict[str, Any]] = []
        inner_ws_paths: list[pathlib.Path] = []
        for ow in other_workspaces:
            ow_path = pathlib.Path(ow["canonical_path"]).resolve()
            if ws_path in ow_path.parents:
                inner_workspaces.append(dict(ow))
                inner_ws_paths.append(ow_path)

        # Existing config projects
        existing_projects = ws_cfg.get("projects", [])
        existing_by_path: dict[str, dict[str, Any]] = {
            os.path.normpath(p.get("path", "")): p for p in existing_projects if isinstance(p, dict)
        }

        # Discover folders containing tasks/00-INDEX.md
        candidate_folders: list[pathlib.Path] = []
        disc_filter = load_workspace_discovery_filter(ws_path, config_dir=config_dir)

        # Check workspace root
        root_tasks_dir = ws_path / "tasks"
        root_index = root_tasks_dir / "00-INDEX.md"
        if (
            not root_tasks_dir.is_symlink()
            and not root_index.is_symlink()
            and root_index.is_file()
            and disc_filter.allows_project(".", "_workspace", "_workspace")
        ):
            candidate_folders.append(ws_path)

        for root, dirs, _ in os.walk(str(ws_path), followlinks=False):
            # Prune hidden dirs and excluded dirs in-place
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in EXCLUDE_DIR_NAMES
            ]

            for d in list(dirs):
                raw_p = pathlib.Path(root) / d
                if raw_p.is_symlink():
                    dirs.remove(d)
                    continue

                folder_p = raw_p.resolve()
                try:
                    rel_posix = folder_p.relative_to(ws_path).as_posix()
                except ValueError:
                    dirs.remove(d)
                    continue

                # Check if folder or any parent is an inner workspace
                is_inner = any(
                    folder_p == iw or iw in folder_p.parents for iw in inner_ws_paths
                )
                if is_inner:
                    # Do not descend into inner workspaces
                    dirs.remove(d)
                    continue

                if is_git_ignored(folder_p, ws_path):
                    dirs.remove(d)
                    continue

                if disc_filter.can_prune_dir(rel_posix, d):
                    dirs.remove(d)
                    continue

                tasks_dir = folder_p / "tasks"
                index_file = tasks_dir / "00-INDEX.md"
                if (
                    not tasks_dir.is_symlink()
                    and not index_file.is_symlink()
                    and index_file.is_file()
                ):
                    candidate_folders.append(folder_p)

        # Build proposed projects list
        proposed_projects: list[dict[str, Any]] = []
        used_slugs: set[str] = set()

        # Sort candidates deterministically: root first, then by path
        candidate_folders.sort(key=lambda p: (0 if p == ws_path else 1, str(p)))

        for folder in candidate_folders:
            if folder == ws_path:
                rel_path = "."
                p_id = "_workspace"
            else:
                rel_path = folder.relative_to(ws_path).as_posix()
                raw_slug = sanitize_slug(folder.name)
                if not disc_filter.allows_project(rel_path, folder.name, raw_slug):
                    continue
                p_id = raw_slug
                suffix = 2
                while p_id in used_slugs:
                    p_id = f"{raw_slug}-{suffix}"
                    suffix += 1

            norm_rel = os.path.normpath(rel_path)
            if norm_rel in existing_by_path:
                # Preserve existing uuid and id from config
                ex = existing_by_path[norm_rel]
                p_uuid = ex.get("uuid") or deterministic_uuid4(f"project:{ws_uuid}:{norm_rel}")
                p_id = ex.get("id") or p_id
            else:
                p_uuid = deterministic_uuid4(f"project:{ws_uuid}:{norm_rel}")

            used_slugs.add(p_id)
            proposed_projects.append({
                "uuid": p_uuid,
                "id": p_id,
                "path": rel_path,
            })

        sub_ws_items = [
            {
                "uuid": iw["uuid"],
                "slug": iw["slug"],
                "path": str(pathlib.Path(iw["canonical_path"]).resolve().relative_to(ws_path)),
            }
            for iw in inner_workspaces
        ]

        plan = {
            "ok": True,
            "workspace_registered": is_registered,
            "workspace_path": str(ws_path),
            "discovered": proposed_projects,
            "workspace": ws_slug,
            "workspace_uuid": ws_uuid,
            "canonical_path": str(ws_path),
            "config_path": str(cfg_path),
            "proposed_projects": proposed_projects,
            "sub_workspaces": sub_ws_items,
        }
        if ws_title:
            plan["title"] = ws_title
        plan["plan_hash"] = compute_plan_hash(plan)
        return plan
    finally:
        conn.close()


def apply_projects_discover(
    plan: dict[str, Any],
    expect_hash: str | None = None,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Apply project discovery proposal to workspace config and registry."""
    plan_hash = plan.get("plan_hash")
    if not expect_hash:
        raise ValueError(
            f"--expect-hash is required when applying. Computed plan_hash is: {plan_hash}"
        )
    if expect_hash != plan_hash:
        raise ValueError(
            f"Hash mismatch: expected {expect_hash}, computed plan_hash {plan_hash}"
        )

    ws_uuid = plan["workspace_uuid"]
    ws_slug = plan["workspace"]
    cfg_path = pathlib.Path(plan["config_path"])
    ws_path = pathlib.Path(plan.get("canonical_path", plan.get("workspace_path"))).resolve()
    ws_title = plan.get("title")
    proposed = plan["proposed_projects"]
    cur_host = _resolve_current_host_id(config_dir, workspace=ws_path)
    conv_ver = _read_workspace_convention_version(ws_path)

    # 1. Update config file
    write_workspace_to_config(cfg_path, ws_uuid, ws_slug, ws_title=ws_title, projects=proposed)

    # 2. Update hub registry and SQLite projects table
    db_path = get_db_path(config_dir)
    with registry_lock(config_dir):
        upsert_hub_project_entry(
            config_dir,
            ws_uuid=ws_uuid,
            ws_slug=ws_slug,
            ws_title=ws_title,
            host_id=cur_host,
            host_path=str(ws_path),
            convention_version=conv_ver,
            subprojects=proposed,
        )
        conn = get_connection(db_path)
        try:
            with conn:
                # Ensure workspace is registered in workspaces table
                existing = conn.execute(
                    "SELECT * FROM workspaces WHERE uuid = ?", (ws_uuid,)
                ).fetchone()
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                if not existing:
                    check_symlinked_components(ws_path)
                    dev, ino = check_device_inode(ws_path)
                    paths_json = json.dumps({cur_host: str(ws_path)}, sort_keys=True)
                    conn.execute(
                        """
                        INSERT INTO workspaces (
                            uuid, slug, title, canonical_path, device, inode,
                            registered_at, last_seen, primary_host, convention_version, paths_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(uuid) DO UPDATE SET
                            slug = excluded.slug,
                            title = excluded.title,
                            canonical_path = excluded.canonical_path,
                            device = excluded.device,
                            inode = excluded.inode,
                            last_seen = excluded.last_seen,
                            convention_version = COALESCE(excluded.convention_version, workspaces.convention_version);
                        """,
                        (ws_uuid, ws_slug, ws_title, str(ws_path), dev, ino, now, now, cur_host, conv_ver, paths_json),
                    )
                    conn.execute(
                        """
                        INSERT INTO workspace_host_paths (workspace_uuid, host, path, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(workspace_uuid, host) DO UPDATE SET
                            path = excluded.path,
                            updated_at = excluded.updated_at;
                        """,
                        (ws_uuid, cur_host, str(ws_path), now),
                    )

                # Clear existing projects for this workspace and insert new ones
                conn.execute("DELETE FROM projects WHERE workspace_uuid = ?", (ws_uuid,))
                for p in proposed:
                    p_folder = (ws_path / p["path"]).resolve() if p.get("path") not in (".", "") else ws_path
                    p_conv = _read_workspace_convention_version(p_folder) or conv_ver
                    conn.execute(
                        """
                        INSERT INTO projects (uuid, workspace_uuid, slug, rel_path, convention_version)
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        (p["uuid"], ws_uuid, p["id"], p["path"], p_conv),
                    )
        finally:
            conn.close()

    return {
        "ok": True,
        "applied": True,
        "workspace_registered": True,
        "plan_hash": plan_hash,
        "projects": proposed,
        "discovered": proposed,
    }


def list_projects(
    workspace_arg: str | None = None,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """List all projects for a workspace, marking sub-workspaces as read-only."""
    ws = find_workspace_for_arg(workspace_arg, config_dir=config_dir)
    ws_path = pathlib.Path(ws["canonical_path"]).resolve()

    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        disc_filter = load_workspace_discovery_filter(ws_path, config_dir=config_dir)

        # Load inner registered workspaces
        other_workspaces = conn.execute(
            "SELECT * FROM workspaces WHERE uuid != ?", (ws["uuid"],)
        ).fetchall()
        inner_ws: list[dict[str, Any]] = []
        for ow in other_workspaces:
            ow_path = pathlib.Path(ow["canonical_path"]).resolve()
            if ws_path in ow_path.parents:
                rel_ow = ow_path.relative_to(ws_path).as_posix()
                if not disc_filter.allows_project(rel_ow, ow_path.name, ow["slug"]):
                    continue
                inner_ws.append({
                    "uuid": ow["uuid"],
                    "slug": ow["slug"],
                    "path": str(ow_path.relative_to(ws_path)),
                    "kind": "sub_workspace",
                })

        # Fetch projects from SQLite
        proj_rows = conn.execute(
            "SELECT uuid, slug, rel_path FROM projects WHERE workspace_uuid = ? ORDER BY slug ASC",
            (ws["uuid"],),
        ).fetchall()

        items: list[dict[str, Any]] = []
        for pr in proj_rows:
            rel_p = str(pr["rel_path"]).replace("\\", "/")
            name_p = "_workspace" if pr["slug"] == "_workspace" else pathlib.PurePosixPath(rel_p).name
            if not disc_filter.allows_project(rel_p, name_p, pr["slug"]):
                continue
            kind = "_workspace" if pr["slug"] == "_workspace" else "project"
            items.append({
                "uuid": pr["uuid"],
                "slug": pr["slug"],
                "path": pr["rel_path"],
                "kind": kind,
            })

        # Append sub-workspaces
        items.extend(inner_ws)

        return {
            "ok": True,
            "workspace": ws["slug"],
            "workspace_uuid": ws["uuid"],
            "items": items,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Path Resolution Helper
# ---------------------------------------------------------------------------


def resolve_workspace_for_path(
    path: str | pathlib.Path,
    config_dir: pathlib.Path | str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve nearest registered workspace and containing project for a path."""
    target = pathlib.Path(path).expanduser().resolve()
    hub_path = get_hub_registry_path(config_dir)
    if hub_path.is_file():
        sync_hub_registry_to_sqlite(config_dir)
    db_path = get_db_path(config_dir)
    if not db_path.exists():
        return None, None

    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM workspaces").fetchall()
        matching_workspaces: list[tuple[pathlib.Path, dict[str, Any]]] = []

        for r in rows:
            cpath = pathlib.Path(r["canonical_path"]).resolve()
            if target == cpath or cpath in target.parents:
                matching_workspaces.append((cpath, dict(r)))

        if not matching_workspaces:
            return None, None

        # Nearest workspace: deepest directory (most path components)
        matching_workspaces.sort(key=lambda item: len(item[0].parts), reverse=True)
        nearest_path, nearest_ws = matching_workspaces[0]

        # Find matching project within nearest workspace
        proj_rows = conn.execute(
            "SELECT * FROM projects WHERE workspace_uuid = ?",
            (nearest_ws["uuid"],),
        ).fetchall()

        matching_projects: list[tuple[pathlib.Path, dict[str, Any]]] = []
        for pr in proj_rows:
            p_rel = pr["rel_path"]
            p_abs = (nearest_path / p_rel).resolve()
            if target == p_abs or p_abs in target.parents:
                matching_projects.append((p_abs, dict(pr)))

        if matching_projects:
            # Nearest project: deepest directory
            matching_projects.sort(key=lambda item: len(item[0].parts), reverse=True)
            return nearest_ws, matching_projects[0][1]

        return nearest_ws, None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration Registry Importer (`MIGRATION_REGISTRY.json`) and Console Status
# ---------------------------------------------------------------------------


def _extract_migration_configured_roots(
    raw_data: Any,
    config_dir: pathlib.Path | str | None = None,
) -> list[pathlib.Path]:
    """Extract configured workspace roots from the migration registry (`hosts.<host>.root`, `workspace_roots`, `roots`)
    and from the global `orchestration.toml` (`[workspace] roots` / `[hosts.<h>] root`)."""
    roots: list[pathlib.Path] = []
    seen: set[str] = set()

    def _add(val: Any) -> None:
        if isinstance(val, (str, pathlib.Path)) and str(val).strip():
            s = str(val).strip()
            if "{{" in s or "}}" in s:
                return
            try:
                rp = pathlib.Path(s).expanduser().resolve()
                if str(rp) not in seen:
                    seen.add(str(rp))
                    roots.append(rp)
            except Exception:
                pass

    if isinstance(raw_data, dict):
        hosts_sec = raw_data.get("hosts")
        if isinstance(hosts_sec, dict):
            for hinfo in hosts_sec.values():
                if isinstance(hinfo, dict):
                    _add(hinfo.get("root"))
                    _add(hinfo.get("workspace_root"))
        for rkey in ("workspace_roots", "roots", "allowed_roots"):
            rlist = raw_data.get(rkey)
            if isinstance(rlist, list):
                for item in rlist:
                    _add(item)

    if config_dir is not None:
        cdir = pathlib.Path(config_dir).expanduser().resolve()
        _add(cdir)
        gpath = cdir / "orchestration.toml"
        if gpath.is_file():
            try:
                gcfg = load_toml_file(gpath)
                ws_sec = gcfg.get("workspace") if isinstance(gcfg.get("workspace"), dict) else {}
                for rkey in ("roots", "workspace_roots", "allowed_roots"):
                    rlist = ws_sec.get(rkey)
                    if isinstance(rlist, list):
                        for item in rlist:
                            _add(item)
                hosts_tbl = gcfg.get("hosts") if isinstance(gcfg.get("hosts"), dict) else {}
                for hinfo in hosts_tbl.values():
                    if isinstance(hinfo, dict):
                        _add(hinfo.get("root"))
            except Exception:
                pass
    return roots


def _verify_path_within_allowed_roots(
    target_path: pathlib.Path,
    allowed_roots: list[pathlib.Path],
    *,
    context_label: str = "write",
) -> pathlib.Path:
    """Refuse to write outside configured roots when `allowed_roots` is non-empty."""
    resolved = target_path.expanduser().resolve()
    if not allowed_roots:
        return resolved
    for root in allowed_roots:
        r_res = root.expanduser().resolve()
        if resolved == r_res or r_res in resolved.parents:
            return resolved
    roots_str = ", ".join(str(r) for r in allowed_roots)
    raise ValueError(
        f"Refusing {context_label} to '{resolved}': path is outside configured roots ({roots_str})"
    )


def _normalize_migration_record(
    raw_item: dict[str, Any],
    *,
    default_slug_hint: str | None = None,
    default_primary_host: str | None = None,
    existing_hub_doc: dict[str, Any] | None = None,
    cur_host: str = "localhost",
    config_dir: pathlib.Path | str | None = None,
    pending_key_prefix: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Normalize a single entry from `MIGRATION_REGISTRY.json` into canonical hub registry schema.

    Returns `(normalized_entry, generated_new_uuid)` where `generated_new_uuid` is True when
    `raw_item` had no explicit valid UUID (in the migration record or in the local checkout's
    project config), so a new random UUID4 was allocated and should be persisted back into the
    migration registry file on apply. Never adopts an existing hub entry by slug alone.
    """
    raw_slug = (
        raw_item.get("slug")
        or raw_item.get("id")
        or raw_item.get("name")
        or default_slug_hint
        or ""
    )
    if not raw_slug:
        for pkey in ("mac_path", "hub_path", "server_path", "alf_ubuntu_path", "path"):
            pv = raw_item.get(pkey)
            if isinstance(pv, str) and pv.strip():
                raw_slug = pathlib.PurePosixPath(pv.strip().rstrip("/")).name
                break
        if not raw_slug and isinstance(raw_item.get("paths"), dict):
            for pv in raw_item["paths"].values():
                if isinstance(pv, str) and pv.strip():
                    raw_slug = pathlib.PurePosixPath(pv.strip().rstrip("/")).name
                    break
    ws_slug = sanitize_slug(str(raw_slug or "workspace"))

    item_paths: dict[str, str] = {}
    for dict_key in ("paths", "hosts", "machines", "locations"):
        sub_map = raw_item.get(dict_key)
        if isinstance(sub_map, dict):
            for hk, hv in sub_map.items():
                norm_hk = normalize_host_id(str(hk))
                if isinstance(hv, str) and hv.strip():
                    item_paths[norm_hk] = hv.strip()
                elif isinstance(hv, dict):
                    p_str = hv.get("path") or hv.get("canonical_path") or hv.get("dir")
                    if isinstance(p_str, str) and p_str.strip():
                        item_paths[norm_hk] = p_str.strip()

    shorthand_hosts = (
        ("mac_path", "mac"),
        ("path_mac", "mac"),
        ("alf_ubuntu_path", "alf_ubuntu"),
        ("path_alf_ubuntu", "alf_ubuntu"),
        ("hub_path", "alf_ubuntu"),
        ("server_path", "alf_ubuntu"),
        ("ubuntu_path", "alf_ubuntu"),
    )
    for field_name, target_host in shorthand_hosts:
        fval = raw_item.get(field_name)
        if isinstance(fval, str) and fval.strip():
            item_paths[normalize_host_id(target_host)] = fval.strip()

    if isinstance(raw_item.get("path"), str) and raw_item["path"].strip():
        p_single = raw_item["path"].strip()
        if not item_paths:
            item_paths[cur_host] = p_single
        else:
            item_paths.setdefault(cur_host, p_single)

    for hk, hv in item_paths.items():
        if "{{" in hv or "}}" in hv:
            raise ValueError(
                f"Unexpanded template placeholder in path for project '{ws_slug}' on host '{hk}': {hv}"
            )

    # Resolve explicit UUID link ONLY from:
    # (1) `raw_item["uuid"]` (or `link` / `link_uuid`), or
    # (2) `[workspace] uuid` already present in the local checkout's project config.
    explicit_uuid: str | None = None
    raw_uuid = raw_item.get("uuid") or raw_item.get("link") or raw_item.get("link_uuid")
    if raw_uuid is not None:
        if not (isinstance(raw_uuid, str) and is_valid_uuid4(raw_uuid.strip())):
            raise ValueError(
                f"Invalid UUID '{raw_uuid}' in migration record for project '{ws_slug}': must be a valid UUID4"
            )
        explicit_uuid = raw_uuid.strip()
    else:
        local_cand_init = item_paths.get(cur_host)
        if local_cand_init:
            lp_init = pathlib.Path(local_cand_init).expanduser()
            if lp_init.is_dir() and not lp_init.is_symlink():
                _, cfg_d = _load_checkout_own_config(
                    lp_init.resolve(),
                    config_dir,
                    cur_host=cur_host,
                    hub_doc=existing_hub_doc or {"projects": []},
                )
                u_cfg = cfg_d.get("workspace", {}).get("uuid")
                if isinstance(u_cfg, str) and is_valid_uuid4(u_cfg.strip()):
                    explicit_uuid = u_cfg.strip()

    hub_existing = (
        find_hub_project_entry(existing_hub_doc, ws_uuid=explicit_uuid)
        if (existing_hub_doc is not None and explicit_uuid is not None)
        else None
    )

    generated_new_uuid = False
    if explicit_uuid is not None:
        ws_uuid = explicit_uuid
    else:
        if pending_key_prefix:
            ws_uuid = _get_or_allocate_pending_uuid(config_dir, f"{pending_key_prefix}:{ws_slug}")
        else:
            ws_uuid = allocate_workspace_uuid()
        generated_new_uuid = True

    ws_title = (
        raw_item.get("title")
        or raw_item.get("description")
        or (hub_existing.get("title") if hub_existing else None)
    )

    paths: dict[str, str] = {}
    if hub_existing and isinstance(hub_existing.get("paths"), dict):
        for hk, hv in hub_existing["paths"].items():
            if isinstance(hk, str) and isinstance(hv, str) and hv.strip():
                paths[normalize_host_id(hk)] = hv.strip()
    paths.update(item_paths)

    raw_primary = (
        raw_item.get("primary_host")
        or raw_item.get("primary")
        or raw_item.get("primary_machine")
        or raw_item.get("owner_host")
        or raw_item.get("active_host")
        or (hub_existing.get("primary_host") if hub_existing else None)
        or default_primary_host
        or ("alf_ubuntu" if "alf_ubuntu" in paths else (next(iter(paths.keys())) if paths else cur_host))
    )
    primary_host = normalize_host_id(str(raw_primary)) if raw_primary else cur_host

    ref_repo: str | None = None
    for rkey in ("reference_repo", "bare_repo", "hub_repo", "origin", "git_repo", "repo"):
        rv = raw_item.get(rkey)
        if isinstance(rv, str) and rv.strip():
            ref_repo = rv.strip()
            break
    if ref_repo is None and isinstance(raw_item.get("remote"), dict):
        rv = raw_item["remote"].get("reference") or raw_item["remote"].get("bare") or raw_item["remote"].get("origin")
        if isinstance(rv, str) and rv.strip():
            ref_repo = rv.strip()
    if ref_repo is None and hub_existing:
        ref_repo = hub_existing.get("reference_repo")

    mirror_repo: str | None = None
    for mkey in ("mirror_repo", "mirror", "gitea_mirror", "gitea", "backup_repo", "offsite_mirror"):
        mv = raw_item.get(mkey)
        if isinstance(mv, str) and mv.strip():
            mirror_repo = mv.strip()
            break
    if mirror_repo is None and isinstance(raw_item.get("remote"), dict):
        mv = raw_item["remote"].get("mirror") or raw_item["remote"].get("gitea")
        if isinstance(mv, str) and mv.strip():
            mirror_repo = mv.strip()
    if mirror_repo is None and hub_existing:
        mirror_repo = hub_existing.get("mirror_repo") or hub_existing.get("mirror")

    conv_ver: str | None = None
    for ckey in ("convention_version", "schema_version", "version"):
        cv = raw_item.get(ckey)
        if isinstance(cv, (str, int, float)) and not isinstance(cv, bool) and str(cv).strip():
            conv_ver = str(cv).strip()
            break

    # Check if local path exists and has tasks/convention_version
    local_cand = paths.get(cur_host)
    if local_cand:
        lp = pathlib.Path(local_cand).expanduser()
        if lp.is_dir() and not conv_ver:
            conv_ver = _read_workspace_convention_version(lp)

    if not conv_ver and hub_existing:
        conv_ver = hub_existing.get("convention_version")

    raw_subs = raw_item.get("subprojects") or raw_item.get("projects") or []
    subprojects: list[dict[str, Any]] = []
    if isinstance(raw_subs, list) and raw_subs:
        for sp in raw_subs:
            if isinstance(sp, str) and sp.strip():
                sp_slug = "_workspace" if sp.strip() in (".", "_workspace") else sanitize_slug(pathlib.PurePosixPath(sp.strip()).name)
                sp_rel = "." if sp_slug == "_workspace" else sp.strip()
                subprojects.append({
                    "uuid": portable_project_uuid(ws_uuid, sp_rel),
                    "id": sp_slug,
                    "slug": sp_slug,
                    "path": sp_rel,
                    "rel_path": sp_rel,
                    "convention_version": conv_ver,
                })
            elif isinstance(sp, dict):
                sp_rel = str(sp.get("path") or sp.get("rel_path") or ".")
                raw_sp_id = sp.get("id") or sp.get("slug")
                if raw_sp_id:
                    sp_slug = "_workspace" if raw_sp_id == "_workspace" else sanitize_slug(str(raw_sp_id))
                else:
                    sp_slug = "_workspace" if sp_rel in (".", "") else sanitize_slug(pathlib.PurePosixPath(sp_rel).name)
                sp_uuid = (
                    str(sp["uuid"]).strip()
                    if isinstance(sp.get("uuid"), str) and is_valid_uuid4(str(sp["uuid"]).strip())
                    else portable_project_uuid(ws_uuid, sp_rel)
                )
                subprojects.append({
                    "uuid": sp_uuid,
                    "id": sp_slug,
                    "slug": sp_slug,
                    "path": sp_rel,
                    "rel_path": sp_rel,
                    "convention_version": sp.get("convention_version") or conv_ver,
                })
    elif hub_existing and isinstance(hub_existing.get("subprojects"), list) and hub_existing["subprojects"]:
        subprojects = copy.deepcopy(hub_existing["subprojects"])
    else:
        subprojects = [{
            "uuid": portable_project_uuid(ws_uuid, "."),
            "id": "_workspace",
            "slug": "_workspace",
            "path": ".",
            "rel_path": ".",
            "convention_version": conv_ver,
        }]

    return {
        "uuid": ws_uuid,
        "id": ws_slug,
        "slug": ws_slug,
        "title": ws_title,
        "primary_host": primary_host,
        "paths": dict(sorted(paths.items())),
        "reference_repo": ref_repo,
        "mirror_repo": mirror_repo,
        "mirror": mirror_repo,
        "convention_version": conv_ver,
        "subprojects": subprojects,
    }, generated_new_uuid


def _persist_generated_uuids_to_migration_data(
    raw_data: Any,
    uuid_by_slug: dict[str, str],
) -> bool:
    """Inject allocated UUIDs into `raw_data` in-place for records that lacked an explicit `uuid`."""
    changed = False
    if isinstance(raw_data, list):
        for item in raw_data:
            if isinstance(item, dict) and not (isinstance(item.get("uuid"), str) and is_valid_uuid4(item["uuid"].strip())):
                raw_s = item.get("slug") or item.get("id") or item.get("name") or ""
                s = sanitize_slug(str(raw_s)) if raw_s else ""
                if s in uuid_by_slug:
                    item["uuid"] = uuid_by_slug[s]
                    changed = True
    elif isinstance(raw_data, dict):
        list_cand = (
            raw_data.get("projects")
            if "projects" in raw_data
            else (
                raw_data.get("workspaces")
                if "workspaces" in raw_data
                else raw_data.get("entries")
            )
        )
        if isinstance(list_cand, list):
            for item in list_cand:
                if isinstance(item, dict) and not (isinstance(item.get("uuid"), str) and is_valid_uuid4(item["uuid"].strip())):
                    raw_s = item.get("slug") or item.get("id") or item.get("name") or ""
                    s = sanitize_slug(str(raw_s)) if raw_s else ""
                    if s in uuid_by_slug:
                        item["uuid"] = uuid_by_slug[s]
                        changed = True
        elif isinstance(list_cand, dict):
            for k, item in list_cand.items():
                if isinstance(item, dict) and not (isinstance(item.get("uuid"), str) and is_valid_uuid4(item["uuid"].strip())):
                    raw_s = item.get("slug") or item.get("id") or item.get("name") or k
                    s = sanitize_slug(str(raw_s))
                    if s in uuid_by_slug:
                        item["uuid"] = uuid_by_slug[s]
                        changed = True
    return changed


def plan_import_migration_registry(
    migration_file: str | pathlib.Path,
    config_dir: pathlib.Path | str | None = None,
    *,
    host: str | None = None,
    allowed_roots: list[str | pathlib.Path] | None = None,
) -> dict[str, Any]:
    """Build a preview plan for importing `MIGRATION_REGISTRY.json` into the hub registry and SQLite cache."""
    mpath = pathlib.Path(migration_file).expanduser().resolve()
    if not mpath.is_file():
        raise FileNotFoundError(f"Migration registry file not found: {mpath}")

    raw_text = mpath.read_text(encoding="utf-8")
    source_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    raw_data = json.loads(raw_text)

    cur_host = _resolve_current_host_id(config_dir, host_override=host)
    existing_hub_doc = load_hub_registry(config_dir)

    effective_roots = _extract_migration_configured_roots(raw_data, config_dir)
    if allowed_roots:
        for ar in allowed_roots:
            rp = pathlib.Path(ar).expanduser().resolve()
            if rp not in effective_roots:
                effective_roots.append(rp)

    default_primary: str | None = None
    raw_items: list[tuple[str | None, dict[str, Any]]] = []

    if isinstance(raw_data, list):
        for item in raw_data:
            if isinstance(item, dict):
                raw_items.append((None, item))
    elif isinstance(raw_data, dict):
        if isinstance(raw_data.get("primary_host"), str):
            default_primary = raw_data["primary_host"]
        list_cand = (
            raw_data.get("projects")
            if "projects" in raw_data
            else (
                raw_data.get("workspaces")
                if "workspaces" in raw_data
                else raw_data.get("entries")
            )
        )
        if isinstance(list_cand, list):
            for item in list_cand:
                if isinstance(item, dict):
                    raw_items.append((None, item))
        elif isinstance(list_cand, dict):
            for k, v in list_cand.items():
                if isinstance(v, dict):
                    raw_items.append((str(k), v))
        else:
            reserved = {"schema_version", "version", "updated_at", "generated_at", "hosts", "machines", "primary_host", "defaults"}
            for k, v in raw_data.items():
                if k not in reserved and isinstance(v, dict):
                    raw_items.append((str(k), v))
    else:
        raise ValueError(f"Unsupported migration registry JSON structure in {mpath}")

    imported_entries: list[dict[str, Any]] = []
    generated_uuids: dict[str, str] = {}
    seen_slugs: set[str] = set()
    pending_prefix = f"migration:{mpath}:{source_sha256}:{cur_host}"
    db_p_chk = get_db_path(config_dir)
    for slug_hint, raw_item in raw_items:
        norm, is_new_uuid = _normalize_migration_record(
            raw_item,
            default_slug_hint=slug_hint,
            default_primary_host=default_primary,
            existing_hub_doc=existing_hub_doc,
            cur_host=cur_host,
            config_dir=config_dir,
            pending_key_prefix=pending_prefix,
        )
        if norm["slug"] in seen_slugs:
            raise ValueError(f"Duplicate project slug '{norm['slug']}' in migration registry {mpath}")
        seen_slugs.add(norm["slug"])

        for hp in existing_hub_doc.get("projects", []):
            if (
                isinstance(hp, dict)
                and (hp.get("slug") == norm["slug"] or hp.get("id") == norm["slug"])
                and hp.get("uuid") != norm["uuid"]
            ):
                raise ValueError(
                    f"Slug '{norm['slug']}' is already registered in hub registry to UUID '{hp.get('uuid')}' "
                    f"(cannot merge migration record without explicit UUID link '{hp.get('uuid')}')"
                )
        if db_p_chk.exists():
            conn_chk = get_connection(db_p_chk)
            try:
                row_slug = conn_chk.execute(
                    "SELECT uuid FROM workspaces WHERE slug = ? AND uuid != ?",
                    (norm["slug"], norm["uuid"]),
                ).fetchone()
                if row_slug:
                    raise ValueError(
                        f"Slug '{norm['slug']}' is already registered to workspace '{row_slug['uuid']}' "
                        f"(cannot merge migration record without explicit UUID link '{row_slug['uuid']}')"
                    )
            finally:
                conn_chk.close()

        if is_new_uuid:
            generated_uuids[norm["slug"]] = norm["uuid"]

        # Verify all host paths stay within configured roots if roots are configured
        if effective_roots:
            for hk, hv in (norm.get("paths") or {}).items():
                _verify_path_within_allowed_roots(
                    pathlib.Path(hv),
                    effective_roots,
                    context_label=f"migration path ({norm['slug']}@{hk})",
                )
        imported_entries.append(norm)

    imported_entries.sort(key=lambda e: e["slug"])
    hub_registry_path = get_hub_registry_path(config_dir)

    after_payload = json.dumps(imported_entries, sort_keys=True, separators=(",", ":"))
    after_hash = hashlib.sha256(after_payload.encode("utf-8")).hexdigest()

    plan: dict[str, Any] = {
        "ok": True,
        "action": "import-migration-registry",
        "source_path": str(mpath),
        "source_sha256": source_sha256,
        "hub_registry_path": str(hub_registry_path),
        "host": cur_host,
        "allowed_roots": [str(r) for r in effective_roots],
        "generated_uuids": generated_uuids,
        "imported_count": len(imported_entries),
        "projects": imported_entries,
        "after_hash": after_hash,
    }
    plan["plan_hash"] = compute_plan_hash(plan)
    return plan


def apply_import_migration_registry(
    plan: dict[str, Any],
    expect_hash: str | None = None,
    config_dir: pathlib.Path | str | None = None,
    *,
    allowed_roots: list[str | pathlib.Path] | None = None,
) -> dict[str, Any]:
    """Apply a migration registry import plan to `hub_registry.json`, local SQLite cache, and local workspace configs."""
    plan_hash = plan.get("plan_hash")
    if not expect_hash:
        raise ValueError(
            f"--expect-hash is required when applying. Computed plan_hash is: {plan_hash}"
        )
    if expect_hash != plan_hash:
        raise ValueError(
            f"Hash mismatch: expected {expect_hash}, computed plan_hash {plan_hash}"
        )

    source_path = pathlib.Path(plan["source_path"])
    raw_source_data: Any = None
    if source_path.is_file():
        raw_bytes = source_path.read_bytes()
        cur_sha = hashlib.sha256(raw_bytes).hexdigest()
        if cur_sha != plan.get("source_sha256"):
            raise ValueError(
                f"Source migration file {source_path} changed between preview and apply "
                f"(expected sha256 {plan.get('source_sha256')}, got {cur_sha})"
            )
        try:
            raw_source_data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            raw_source_data = None

    cur_host = plan.get("host") or _resolve_current_host_id(config_dir)
    entries = plan.get("projects", [])
    db_path = get_db_path(config_dir)
    cdir_resolved = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir().resolve()
    _gpath = cdir_resolved / "orchestration.toml"

    effective_roots: list[pathlib.Path] = [cdir_resolved]
    for r_str in (plan.get("allowed_roots") or []):
        rp = pathlib.Path(r_str).expanduser().resolve()
        if rp not in effective_roots:
            effective_roots.append(rp)
    if allowed_roots:
        for ar in allowed_roots:
            rp = pathlib.Path(ar).expanduser().resolve()
            if rp not in effective_roots:
                effective_roots.append(rp)
    for r_extra in _extract_migration_configured_roots(raw_source_data, cdir_resolved):
        if r_extra not in effective_roots:
            effective_roots.append(r_extra)

    with registry_lock(config_dir):
        for entry in entries:
            # Verify all paths in entry against configured roots
            for hk, hv in (entry.get("paths") or {}).items():
                _verify_path_within_allowed_roots(
                    pathlib.Path(hv),
                    effective_roots,
                    context_label=f"migration path ({entry['slug']}@{hk})",
                )

            upsert_hub_project_entry(
                config_dir,
                ws_uuid=entry["uuid"],
                ws_slug=entry["slug"],
                ws_title=entry.get("title"),
                paths=entry.get("paths"),
                primary_host=entry.get("primary_host"),
                reference_repo=entry.get("reference_repo"),
                mirror_repo=entry.get("mirror_repo"),
                convention_version=entry.get("convention_version"),
                subprojects=entry.get("subprojects"),
            )

            # If the current host's checkout path exists on disk, also align its project config (inside allowed roots)
            local_p_str = (entry.get("paths") or {}).get(cur_host)
            if local_p_str:
                lp = pathlib.Path(local_p_str).expanduser()
                if lp.is_dir() and not lp.is_symlink():
                    resolved_lp = _verify_path_within_allowed_roots(
                        lp,
                        effective_roots,
                        context_label=f"workspace checkout ({entry['slug']})",
                    )
                    cfg_wpath = find_project_config_path(resolved_lp, _gpath, for_write=True)
                    _verify_path_within_allowed_roots(
                        cfg_wpath,
                        effective_roots,
                        context_label=f"workspace config write ({entry['slug']})",
                    )
                    subs_for_cfg = [
                        {"uuid": sp["uuid"], "id": sp["id"], "path": sp["path"]}
                        for sp in (entry.get("subprojects") or [])
                        if isinstance(sp, dict) and sp.get("uuid") and sp.get("id") and sp.get("path")
                    ]
                    write_workspace_to_config(
                        cfg_wpath,
                        entry["uuid"],
                        entry["slug"],
                        ws_title=entry.get("title"),
                        projects=subs_for_cfg if subs_for_cfg else None,
                    )

        # Persist any newly generated random UUIDs back into the migration file so subsequent hosts reuse the exact UUIDs
        uuid_by_slug = {e["slug"]: e["uuid"] for e in entries if e.get("slug") and e.get("uuid")}
        if source_path.is_file() and raw_source_data is not None and _persist_generated_uuids_to_migration_data(raw_source_data, uuid_by_slug):
            tmp_src = source_path.parent / f"{source_path.name}.tmp.{os.getpid()}"
            tmp_src.write_text(json.dumps(raw_source_data, indent=2) + "\n", encoding="utf-8")
            os.replace(str(tmp_src), str(source_path))

        pending_prefix = f"migration:{source_path.resolve()}:{plan.get('source_sha256')}:{cur_host}"
        _clear_pending_uuid(config_dir, *[f"{pending_prefix}:{e['slug']}" for e in entries if e.get("slug")])

        conn = get_connection(db_path)
        try:
            with conn:
                for entry in entries:
                    sync_hub_entry_to_sqlite_conn(conn, entry, current_host=cur_host, registry_source="hub")
        finally:
            conn.close()

    return {
        "ok": True,
        "applied": True,
        "plan_hash": plan_hash,
        "hub_registry_path": str(get_hub_registry_path(config_dir)),
        "host": cur_host,
        "imported_count": len(entries),
        "projects": entries,
    }


SAFE_ATTACH_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
SAFE_HOST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
SAFE_SSH_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*(@[A-Za-z0-9][A-Za-z0-9._:-]*)?$")
SAFE_SCREEN_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_AGENT_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,62}$")
SAFE_RUN_DIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _load_runs_module() -> Any:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import orchestration_runs

    return orchestration_runs


def _load_tasks_engine_module() -> Any:
    te_dir = REPO_ROOT / "plugins" / "architect-side" / "skills" / "task-pipeline" / "scripts"
    if str(te_dir) not in sys.path:
        sys.path.insert(0, str(te_dir))
    import tasks_engine

    return tasks_engine


def _compute_iso_age_sec(ts_str: str | None) -> float | None:
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        clean_ts = ts_str.strip().replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(clean_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return max(0.0, round((now - dt).total_seconds(), 3))
    except Exception:
        return None


def _extract_heartbeat_from_run(record: dict[str, Any]) -> str | None:
    for k in ("last_heartbeat", "heartbeat_at", "heartbeat", "last_seen"):
        val = record.get(k)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            sub = val.get("at") or val.get("timestamp") or val.get("last_heartbeat")
            if isinstance(sub, str) and sub.strip():
                return sub.strip()
    sup = record.get("supervisor")
    if isinstance(sup, dict):
        for k in ("last_heartbeat", "heartbeat_at", "heartbeat"):
            val = sup.get(k)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                sub = val.get("at") or val.get("timestamp")
                if isinstance(sub, str) and sub.strip():
                    return sub.strip()
    return None


def _normalize_console_run_record(
    record: dict[str, Any],
    *,
    default_host: str,
    default_project: str | None = None,
    default_workspace: str | None = None,
) -> dict[str, Any]:
    out = dict(record)
    run_id = str(out.get("run_id") or "").strip()
    raw_host = out.get("host")
    run_host = str(raw_host).strip() if isinstance(raw_host, str) and raw_host.strip() else default_host
    task_id = out.get("task_id") or out.get("task") or out.get("note_id")
    status = out.get("status") or out.get("state") or "unknown"
    state = out.get("state") or status
    proj_slug = out.get("project") or default_project or ""
    ws_str = out.get("workspace") or default_workspace or ""
    if not proj_slug and ws_str:
        proj_slug = sanitize_slug(pathlib.Path(ws_str).name)

    scr_sess = (
        out.get("screen_session")
        or out.get("session_name")
        or (out.get("screen") or {}).get("session_name")
    )
    if not scr_sess and out.get("backend") == "screen" and task_id:
        try:
            runs_mod = _load_runs_module()
            scr_sess = runs_mod.build_screen_session_name(
                str(out.get("mode") or "execute"),
                proj_slug or "project",
                str(task_id),
            )
        except Exception:
            scr_sess = f"agent-{proj_slug or 'project'}-{task_id}"

    started_at = out.get("started_at")
    age_sec = out.get("age_sec") if isinstance(out.get("age_sec"), (int, float)) else _compute_iso_age_sec(started_at)
    last_hb = _extract_heartbeat_from_run(out)
    hb_age_sec = (
        out.get("heartbeat_age_sec")
        if isinstance(out.get("heartbeat_age_sec"), (int, float))
        else _compute_iso_age_sec(last_hb)
    )

    out["run_id"] = run_id
    out["host"] = run_host
    out["task_id"] = task_id
    out["task"] = task_id
    out["status"] = status
    out["state"] = state
    out["project"] = proj_slug
    if ws_str:
        out["workspace"] = ws_str
    out["screen_session"] = scr_sess
    out["session_name"] = scr_sess
    out["age_sec"] = age_sec
    out["age"] = age_sec
    out["last_heartbeat"] = last_hb
    out["heartbeat_age_sec"] = hb_age_sec
    out["heartbeat_age"] = hb_age_sec
    return out


def _collect_runs_for_dir(
    proj_dir: pathlib.Path,
    proj_slug: str,
    cur_host: str,
    *,
    reconcile_local: bool = True,
) -> list[dict[str, Any]]:
    runs_dir = proj_dir / ".ai-orchestration" / "runs"
    if not runs_dir.is_dir():
        return []
    runs_mod = None
    try:
        runs_mod = _load_runs_module()
    except Exception:
        runs_mod = None

    results: list[dict[str, Any]] = []
    for entry in runs_dir.iterdir():
        if not entry.is_dir() or entry.name.startswith(".") or entry.name.startswith("-"):
            continue
        if not SAFE_RUN_DIR_RE.match(entry.name):
            continue
        run_file = entry / "run.json"
        if not run_file.is_file():
            continue
        try:
            data = json.loads(run_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
        except Exception:
            continue

        if not data.get("run_id"):
            data["run_id"] = entry.name

        if reconcile_local and runs_mod is not None:
            try:
                is_loc = runs_mod.is_local_run(data, workspace=proj_dir, current_host=cur_host)
                has_pid_or_status = bool(
                    (isinstance(data.get("supervisor"), dict) and data["supervisor"].get("pid") is not None)
                    or (isinstance(data.get("screen"), dict) and data["screen"].get("pid") is not None)
                    or (entry / "status.json").is_file()
                )
                if not is_loc or has_pid_or_status:
                    data = runs_mod.reconcile(data, workspace=proj_dir, current_host=cur_host)
            except Exception:
                pass

        results.append(
            _normalize_console_run_record(
                data,
                default_host=cur_host,
                default_project=proj_slug,
                default_workspace=str(proj_dir),
            )
        )

    results.sort(key=lambda r: str(r.get("run_id") or ""), reverse=True)
    return results


def _collect_tasks_questions_deliveries_for_dir(
    proj_dir: pathlib.Path,
    proj_slug: str,
    cur_host: str,
    runs_for_proj: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tasks_dir = proj_dir / "tasks"
    if not tasks_dir.is_dir():
        return [], [], []
    try:
        te = _load_tasks_engine_module()
    except Exception:
        return [], [], []

    run_by_task: dict[str, dict[str, Any]] = {}
    for r in runs_for_proj:
        tid = r.get("task_id")
        if not tid:
            continue
        existing = run_by_task.get(str(tid))
        if existing is None or (
            r.get("status") in ("running", "starting")
            and existing.get("status") not in ("running", "starting")
        ):
            run_by_task[str(tid)] = r

    tasks_out: list[dict[str, Any]] = []
    deliveries_out: list[dict[str, Any]] = []
    questions_out: list[dict[str, Any]] = []

    try:
        tree = te.discover_task_tree(tasks_dir)
        emergent = te.discover_emergent_tasks(tasks_dir)
        initiatives = te.discover_initiatives(tasks_dir, tree)
        tree_dicts = {nid: node.to_dict() for nid, node in tree.items()}
        raw_tasks = te._build_tasks_list(tasks_dir, tree, emergent, initiatives, tree_dicts)

        for t in raw_tasks:
            if t.get("in_done"):
                continue
            if t.get("kind") == "initiative" and str(t.get("id", "")).startswith("INIT-"):
                continue
            tid = str(t.get("id") or "")
            if not tid:
                continue
            node = tree.get(tid)
            if node is not None and not node.is_leaf:
                continue

            cstate = (
                t.get("canonical_state")
                or (node.canonical_state if node is not None else None)
                or te.normalize_state(str(t.get("state") or "open"))
            )
            raw_thost = (
                t.get("host")
                or (node.host if node is not None else None)
                or (t.get("headers") or {}).get("host")
                or (t.get("own_fields") or {}).get("host")
            )
            clean_thost = (
                str(raw_thost).strip()
                if isinstance(raw_thost, str) and raw_thost.strip() and raw_thost.strip() != "-"
                else None
            )
            matched_r = run_by_task.get(tid)
            eff_host = clean_thost or (matched_r.get("host") if matched_r else None) or cur_host
            run_id_val = (
                t.get("run_id")
                or (t.get("headers") or {}).get("run-id")
                or (node.own_fields.get("run-id") if node is not None else None)
                or (matched_r.get("run_id") if matched_r else None)
            )
            if isinstance(run_id_val, str) and run_id_val.strip() == "-":
                run_id_val = matched_r.get("run_id") if matched_r else None

            qid = f"{proj_slug}/{tid}" if proj_slug else tid
            t_entry = {
                "id": tid,
                "qualified_id": qid,
                "project": proj_slug,
                "workspace": str(proj_dir),
                "title": t.get("title", ""),
                "short_title": t.get("short_title") or t.get("title", ""),
                "state": cstate,
                "canonical_state": cstate,
                "priority": t.get("priority", "P2"),
                "executor": t.get("executor") or "-",
                "host": eff_host,
                "explicit_host": clean_thost,
                "run_id": run_id_val,
            }
            tasks_out.append(t_entry)

            if cstate == "delivered":
                vb = (
                    t.get("verify_by")
                    or t.get("verify-by")
                    or (t.get("headers") or {}).get("verify-by")
                    or (node.own_fields.get("verify-by") if node is not None else None)
                    or t.get("verifier")
                    or "-"
                )
                deliveries_out.append({
                    "id": tid,
                    "qualified_id": qid,
                    "project": proj_slug,
                    "workspace": str(proj_dir),
                    "title": t.get("title", ""),
                    "short_title": t.get("short_title") or t.get("title", ""),
                    "state": "delivered",
                    "verify_by": vb,
                    "executor": t.get("executor") or "-",
                    "host": eff_host,
                    "run_id": run_id_val,
                })
    except Exception:
        pass

    try:
        _, q_res = te.list_questions(tasks_dir, status="open")
        for q in q_res.get("questions", []):
            qid_str = str(q.get("id") or "")
            questions_out.append({
                **q,
                "id": qid_str,
                "qualified_id": f"{proj_slug}/{qid_str}" if proj_slug else qid_str,
                "project": proj_slug,
                "workspace": str(proj_dir),
                "host": cur_host,
            })
    except Exception:
        pass

    return tasks_out, questions_out, deliveries_out


def _discover_local_project_dirs(
    cur_host: str,
    local_workspaces: list[dict[str, Any]],
    workspace: pathlib.Path | str | None = None,
) -> list[tuple[str, str | None, pathlib.Path]]:
    seen_dirs: set[str] = set()
    result: list[tuple[str, str | None, pathlib.Path]] = []

    def _add_dir(slug: str, ws_uuid: str | None, p: pathlib.Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            return
        if not rp.is_dir():
            return
        key = str(rp)
        if key in seen_dirs:
            return
        seen_dirs.add(key)
        result.append((slug, ws_uuid, rp))

    if workspace is not None:
        ws_p = pathlib.Path(workspace).expanduser()
        _add_dir(sanitize_slug(ws_p.resolve().name if ws_p.exists() else ws_p.name), None, ws_p)

    for w in local_workspaces:
        w_slug = str(w.get("slug") or "")
        w_uuid = w.get("uuid")
        paths_map = w.get("paths") if isinstance(w.get("paths"), dict) else {}
        cand_path_str = paths_map.get(cur_host) or w.get("canonical_path")
        if cand_path_str:
            cand_p = pathlib.Path(cand_path_str)
            if cand_p.is_dir():
                _add_dir(w_slug, w_uuid, cand_p)
                for sp in w.get("projects", []) if isinstance(w.get("projects"), list) else []:
                    rel_p = sp.get("rel_path") or sp.get("path")
                    if rel_p and rel_p not in (".", ""):
                        sp_dir = cand_p / rel_p
                        if sp_dir.is_dir():
                            _add_dir(str(sp.get("slug") or sp_dir.name), sp.get("uuid"), sp_dir)

    if not result and workspace is None and not local_workspaces:
        cwd_p = pathlib.Path.cwd().resolve()
        if cwd_p != REPO_ROOT and ((cwd_p / "tasks").is_dir() or (cwd_p / ".ai-orchestration" / "runs").is_dir()):
            _add_dir(sanitize_slug(cwd_p.name), None, cwd_p)

    return result


def _resolve_merged_hosts_table(
    cdir: pathlib.Path,
    gcfg: dict[str, Any],
    gpath: pathlib.Path,
    workspace: pathlib.Path | str | None = None,
) -> dict[str, dict[str, Any]]:
    hosts_table = resolve_hosts_table(gcfg, gpath)
    raw_g_hosts = gcfg.get("hosts") if isinstance(gcfg.get("hosts"), dict) else {}
    for hid, hcfg in hosts_table.items():
        raw_entry = raw_g_hosts.get(hid) if isinstance(raw_g_hosts.get(hid), dict) else {}
        hcfg["_explicit_agent_user"] = raw_entry.get("agent_user") or raw_entry.get("agents_user")
        hcfg["_explicit_user"] = raw_entry.get("user")
    cand_ws: list[pathlib.Path] = []
    if workspace is not None:
        cand_ws.append(pathlib.Path(workspace).expanduser().resolve())
    else:
        cwd_p = pathlib.Path.cwd().resolve()
        if cwd_p != REPO_ROOT:
            cand_ws.append(cwd_p)
    for ws_p in cand_ws:
        try:
            pinfo = inspect_project_config(ws_p, gpath)
            if pinfo.get("exists") and pinfo["path"].is_file():
                pcfg = load_toml_file(pinfo["path"])
                p_hosts = resolve_hosts_table(pcfg, gpath)
                raw_p_hosts = pcfg.get("hosts") if isinstance(pcfg.get("hosts"), dict) else {}
                for hid, hcfg in p_hosts.items():
                    raw_p_entry = raw_p_hosts.get(hid) if isinstance(raw_p_hosts.get(hid), dict) else {}
                    p_exp_agent = raw_p_entry.get("agent_user") or raw_p_entry.get("agents_user")
                    p_exp_user = raw_p_entry.get("user")
                    if hid not in hosts_table:
                        hcfg["_explicit_agent_user"] = p_exp_agent
                        hcfg["_explicit_user"] = p_exp_user
                        hosts_table[hid] = hcfg
                    else:
                        merged = dict(hosts_table[hid])
                        merged.update({k: v for k, v in hcfg.items() if v is not None})
                        if p_exp_agent is not None:
                            merged["_explicit_agent_user"] = p_exp_agent
                        if p_exp_user is not None:
                            merged["_explicit_user"] = p_exp_user
                        hosts_table[hid] = merged
        except Exception:
            pass
    return hosts_table


def _resolve_effective_host_timeout(
    hcfg: dict[str, Any],
    default_timeout: float,
    explicit_timeout: bool = False,
) -> float:
    if not explicit_timeout:
        raw_t = hcfg.get("timeout") if hcfg.get("timeout") is not None else hcfg.get("timeout_sec")
        if isinstance(raw_t, (int, float)) and not isinstance(raw_t, bool) and raw_t > 0:
            return float(raw_t)
    return max(0.1, float(default_timeout))


def _query_remote_host_console_status(
    hid: str,
    hcfg: dict[str, Any],
    timeout_sec: float,
) -> tuple[bool, dict[str, Any] | None, str | None, bool]:
    ssh_target = str(
        hcfg.get("ssh_target")
        or hcfg.get("ssh")
        or hcfg.get("target")
        or hcfg.get("hostname")
        or hid
    ).strip()
    if not ssh_target or ssh_target.startswith("-") or not SAFE_SSH_TARGET_RE.match(ssh_target):
        return False, None, f"Invalid ssh_target {ssh_target!r} for host {hid!r}", False

    conn_timeout = max(1, int(round(timeout_sec)))
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={conn_timeout}"]
    if isinstance(hcfg.get("port"), int) and not isinstance(hcfg.get("port"), bool):
        ssh_cmd.extend(["-p", str(hcfg["port"])])
    id_file = hcfg.get("identity_file") or hcfg.get("ssh_key")
    if isinstance(id_file, str) and id_file.strip() and not id_file.strip().startswith("-"):
        ssh_cmd.extend(["-i", id_file.strip()])
    remote_cmd = shlex.join(["ai-orch", "console", "status", "--local", "--json"])
    ssh_cmd.extend([ssh_target, remote_cmd])

    try:
        proc = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            if isinstance(data, dict):
                return True, data, None, False
            return False, None, "Invalid JSON object from remote host", False
        if proc.returncode == 0 and not proc.stdout.strip():
            return True, {"ok": True, "host": hid, "items": [], "projects": [], "tasks": [], "runs": []}, None, False
        err_msg = (proc.stderr or proc.stdout or f"ssh exited with code {proc.returncode}").strip()
        return False, None, err_msg, False
    except subprocess.TimeoutExpired:
        return False, None, f"ssh timed out after {timeout_sec}s", True
    except Exception as exc:
        return False, None, str(exc), False


def get_console_status_projects(
    config_dir: pathlib.Path | str | None = None,
    *,
    all_hosts: bool = False,
    ssh_timeout: float = 5.0,
    workspace: pathlib.Path | str | None = None,
    local_only: bool = False,
    explicit_timeout: bool = False,
) -> dict[str, Any]:
    """Aggregate multi-host console status: projects, tasks by state and host, runs, open questions, and deliveries to verify.

    Default mode (`all_hosts=False`): queries the local host and the declared remote hub host (if any).
    All-hosts mode (`all_hosts=True`): queries all declared remote hosts concurrently, each with its own timeout,
    and merges the results deterministically in declaration order.
    """
    cdir = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    gpath = cdir / "orchestration.toml"
    gcfg = load_toml_file(gpath) if gpath.is_file() else {}
    cur_host = _resolve_current_host_id(cdir)
    hosts_table = _resolve_merged_hosts_table(cdir, gcfg, gpath, workspace=workspace)

    hub_host_id: str | None = None
    hub_host_cfg: dict[str, Any] | None = None
    if isinstance(gcfg.get("host"), dict) and gcfg["host"].get("role") == "hub":
        hub_host_id = cur_host
        hub_host_cfg = gcfg["host"]
    for hid, hcfg in hosts_table.items():
        if isinstance(hcfg, dict) and hcfg.get("role") == "hub":
            hub_host_id = hid
            hub_host_cfg = hcfg
            break

    hub_reachable = True
    registry_source = "hub"
    hub_error: str | None = None
    snapshot_version: int = 0
    remote_payloads: dict[str, dict[str, Any]] = {}

    hosts_status: dict[str, dict[str, Any]] = {
        cur_host: {
            "host": cur_host,
            "reachable": True,
            "local": True,
            "role": "hub" if hub_host_id == cur_host else (hosts_table.get(cur_host, {}).get("role") or "client"),
        }
    }

    # 1. Determine which remote hosts to query:
    #    - local_only=True: none
    #    - all_hosts=False (default): only the remote hub host (if declared and distinct from cur_host)
    #    - all_hosts=True: the remote hub host + all other enabled hosts in [hosts.<id>], queried concurrently
    hosts_to_query: list[tuple[str, dict[str, Any], float, str]] = []
    if not local_only:
        seen_query_hosts: set[str] = {cur_host}
        if hub_host_id and hub_host_id != cur_host and hub_host_cfg is not None and hub_host_cfg.get("enabled", True) is not False:
            hub_t = _resolve_effective_host_timeout(hub_host_cfg, ssh_timeout, explicit_timeout=explicit_timeout)
            hosts_to_query.append((hub_host_id, hub_host_cfg, hub_t, "hub"))
            seen_query_hosts.add(hub_host_id)
        if all_hosts:
            for hid, hcfg in hosts_table.items():
                if hid in seen_query_hosts or hcfg.get("enabled", True) is False:
                    continue
                host_t = _resolve_effective_host_timeout(hcfg, ssh_timeout, explicit_timeout=explicit_timeout)
                h_role = str(hcfg.get("role") or "client")
                hosts_to_query.append((hid, hcfg, host_t, h_role))
                seen_query_hosts.add(hid)

    # 2. Query remote hosts concurrently (each with its own timeout) and merge deterministically in order
    query_results: dict[str, tuple[bool, dict[str, Any] | None, str | None, bool]] = {}
    if len(hosts_to_query) == 1:
        q_hid, q_cfg, q_t, _ = hosts_to_query[0]
        query_results[q_hid] = _query_remote_host_console_status(q_hid, q_cfg, q_t)
    elif len(hosts_to_query) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(hosts_to_query)) as pool:
            fut_map = {
                q_hid: pool.submit(_query_remote_host_console_status, q_hid, q_cfg, q_t)
                for q_hid, q_cfg, q_t, _ in hosts_to_query
            }
            for q_hid, _, q_t, _ in hosts_to_query:
                try:
                    query_results[q_hid] = fut_map[q_hid].result()
                except Exception as exc:
                    query_results[q_hid] = (False, None, str(exc), False)

    for q_hid, q_cfg, q_t, q_role in hosts_to_query:
        ok_h, r_data, err_h, timed_out_h = query_results[q_hid]
        if q_hid == hub_host_id:
            if ok_h and r_data is not None:
                remote_items = (
                    r_data.get("items")
                    if "items" in r_data
                    else r_data.get("projects")
                )
                if isinstance(remote_items, list):
                    remote_snap_ver = r_data.get("snapshot_version")
                    with registry_lock(cdir):
                        snap_doc = replace_hub_snapshot_cache(
                            cdir,
                            remote_items,
                            host_id=cur_host,
                            snapshot_version=int(remote_snap_ver) if isinstance(remote_snap_ver, int) else None,
                        )
                        snapshot_version = int(snap_doc.get("snapshot_version", 1))
                    remote_payloads[hub_host_id] = r_data
                else:
                    hub_reachable = False
                    registry_source = "local_cache"
                    hub_error = "Invalid hub workspace list JSON response"
            else:
                hub_reachable = False
                registry_source = "local_cache"
                hub_error = err_h

            hosts_status[hub_host_id] = {
                "host": hub_host_id,
                "reachable": hub_reachable,
                "local": False,
                "role": "hub",
                "timeout_sec": q_t,
                "timed_out": timed_out_h if not hub_reachable else False,
                "error": hub_error,
            }
        else:
            if ok_h and r_data is not None:
                remote_payloads[q_hid] = r_data
                hosts_status[q_hid] = {
                    "host": q_hid,
                    "reachable": True,
                    "local": False,
                    "role": q_role,
                    "timeout_sec": q_t,
                }
            else:
                hosts_status[q_hid] = {
                    "host": q_hid,
                    "reachable": False,
                    "local": False,
                    "role": q_role,
                    "timeout_sec": q_t,
                    "timed_out": timed_out_h,
                    "error": err_h,
                }

    # 3. Load local workspaces and hub registry metadata
    local_workspaces = list_workspaces(cdir)
    hub_doc = load_hub_registry(cdir)
    if not snapshot_version:
        snapshot_version = int(hub_doc.get("snapshot_version", 0))
    if (
        not hub_doc.get("projects")
        and local_workspaces
        and registry_source == "hub"
        and not (hub_host_id and hub_host_id != cur_host)
    ):
        registry_source = "local_cache"

    projects_out: list[dict[str, Any]] = [copy.deepcopy(w) for w in local_workspaces]
    proj_by_uuid: dict[str, dict[str, Any]] = {
        str(p["uuid"]): p for p in projects_out if p.get("uuid")
    }
    proj_by_slug: dict[str, dict[str, Any]] = {
        str(p["slug"]): p for p in projects_out if p.get("slug")
    }

    # Merge projects from non-hub remote payloads if any
    for hid, r_data in remote_payloads.items():
        if hid == hub_host_id:
            continue
        r_projs = r_data.get("projects") if isinstance(r_data.get("projects"), list) else r_data.get("items")
        if not isinstance(r_projs, list):
            continue
        for rp in r_projs:
            if not isinstance(rp, dict):
                continue
            r_uuid = str(rp.get("uuid") or "")
            r_slug = str(rp.get("slug") or rp.get("id") or "")
            existing_p = proj_by_uuid.get(r_uuid) if r_uuid else None
            if existing_p is not None:
                if isinstance(rp.get("paths"), dict):
                    existing_p.setdefault("paths", {}).update(rp["paths"])
                elif rp.get("canonical_path"):
                    existing_p.setdefault("paths", {})[hid] = rp["canonical_path"]
            elif r_slug:
                new_p = copy.deepcopy(rp)
                new_p.setdefault("slug", r_slug)
                if not isinstance(new_p.get("paths"), dict):
                    new_p["paths"] = {hid: new_p["canonical_path"]} if new_p.get("canonical_path") else {}
                projects_out.append(new_p)
                if r_uuid:
                    proj_by_uuid[r_uuid] = new_p
                proj_by_slug[r_slug] = new_p

    # 4. Collect local runs, tasks, open questions, and deliveries to verify
    local_proj_dirs = _discover_local_project_dirs(cur_host, local_workspaces, workspace=workspace)
    all_runs: list[dict[str, Any]] = []
    seen_run_ids: dict[str, dict[str, Any]] = {}
    all_tasks: list[dict[str, Any]] = []
    seen_task_keys: dict[tuple[str, str], dict[str, Any]] = {}
    all_open_questions: list[dict[str, Any]] = []
    seen_question_keys: set[tuple[str, str]] = set()
    all_deliveries: list[dict[str, Any]] = []
    seen_delivery_keys: set[tuple[str, str]] = set()

    for p_slug, _, p_dir in local_proj_dirs:
        p_runs = _collect_runs_for_dir(p_dir, p_slug, cur_host, reconcile_local=True)
        for r in p_runs:
            rid = str(r.get("run_id") or "")
            if rid and rid not in seen_run_ids:
                seen_run_ids[rid] = r
                all_runs.append(r)
        p_tasks, p_questions, p_deliveries = _collect_tasks_questions_deliveries_for_dir(
            p_dir, p_slug, cur_host, p_runs
        )
        for t in p_tasks:
            tkey = (str(t.get("project") or ""), str(t.get("id") or ""))
            if tkey not in seen_task_keys:
                seen_task_keys[tkey] = t
                all_tasks.append(t)
        for q in p_questions:
            qkey = (str(q.get("project") or ""), str(q.get("id") or ""))
            if qkey not in seen_question_keys:
                seen_question_keys.add(qkey)
                all_open_questions.append(q)
        for d in p_deliveries:
            dkey = (str(d.get("project") or ""), str(d.get("id") or ""))
            if dkey not in seen_delivery_keys:
                seen_delivery_keys.add(dkey)
                all_deliveries.append(d)

    # 5. Merge runs, tasks, questions, and deliveries from reachable remote hosts
    extra_state_counts: dict[str, int] = {}
    extra_host_counts: dict[str, int] = {}

    for hid, r_data in remote_payloads.items():
        r_runs = r_data.get("runs")
        if isinstance(r_runs, list):
            for raw_r in r_runs:
                if not isinstance(raw_r, dict):
                    continue
                norm_r = _normalize_console_run_record(raw_r, default_host=hid)
                rid = str(norm_r.get("run_id") or "")
                if not rid:
                    continue
                if rid not in seen_run_ids:
                    seen_run_ids[rid] = norm_r
                    all_runs.append(norm_r)
                elif norm_r.get("host") == hid:
                    # Authoritative live state comes from the host that owns the run
                    idx = all_runs.index(seen_run_ids[rid])
                    all_runs[idx] = norm_r
                    seen_run_ids[rid] = norm_r

        r_tasks = r_data.get("tasks") if isinstance(r_data.get("tasks"), list) else r_data.get("all_tasks")
        if isinstance(r_tasks, list) and r_tasks:
            for raw_t in r_tasks:
                if not isinstance(raw_t, dict):
                    continue
                tid = str(raw_t.get("id") or "")
                if not tid:
                    continue
                t_proj = str(raw_t.get("project") or "")
                cstate = str(raw_t.get("canonical_state") or raw_t.get("state") or "open").strip().lower()
                raw_thost = raw_t.get("host")
                eff_thost = (
                    str(raw_thost).strip()
                    if isinstance(raw_thost, str) and raw_thost.strip() and raw_thost.strip() != "-"
                    else hid
                )
                qid = raw_t.get("qualified_id") or (f"{t_proj}/{tid}" if t_proj else tid)
                t_entry = {
                    **raw_t,
                    "id": tid,
                    "qualified_id": qid,
                    "project": t_proj,
                    "state": cstate,
                    "canonical_state": cstate,
                    "host": eff_thost,
                }
                tkey = (t_proj, tid)
                if tkey not in seen_task_keys:
                    seen_task_keys[tkey] = t_entry
                    all_tasks.append(t_entry)
                elif hid == hub_host_id or (
                    not seen_task_keys[tkey].get("explicit_host") and raw_thost not in (None, "", "-")
                ):
                    idx = all_tasks.index(seen_task_keys[tkey])
                    all_tasks[idx] = t_entry
                    seen_task_keys[tkey] = t_entry
        else:
            r_by_state = r_data.get("tasks_by_state")
            if isinstance(r_by_state, dict):
                for st_k, st_v in r_by_state.items():
                    if isinstance(st_v, int):
                        extra_state_counts[str(st_k)] = extra_state_counts.get(str(st_k), 0) + st_v
                        extra_host_counts[hid] = extra_host_counts.get(hid, 0) + st_v

        r_questions = (
            r_data.get("open_questions")
            if isinstance(r_data.get("open_questions"), list)
            else r_data.get("questions")
        )
        if isinstance(r_questions, list):
            for raw_q in r_questions:
                if not isinstance(raw_q, dict):
                    continue
                if raw_q.get("status") and str(raw_q.get("status")).lower() != "open":
                    continue
                qid_str = str(raw_q.get("id") or "")
                q_proj = str(raw_q.get("project") or "")
                qkey = (q_proj, qid_str)
                if qid_str and qkey not in seen_question_keys:
                    seen_question_keys.add(qkey)
                    all_open_questions.append({
                        **raw_q,
                        "id": qid_str,
                        "qualified_id": raw_q.get("qualified_id") or (f"{q_proj}/{qid_str}" if q_proj else qid_str),
                        "project": q_proj,
                        "host": raw_q.get("host") or hid,
                    })

        r_deliv = (
            r_data.get("deliveries_to_verify")
            if "deliveries_to_verify" in r_data
            else r_data.get("verification_queue")
        )
        if isinstance(r_deliv, dict) and isinstance(r_deliv.get("items"), list):
            r_deliv = r_deliv["items"]
        if isinstance(r_deliv, list):
            for raw_d in r_deliv:
                if not isinstance(raw_d, dict):
                    continue
                did_str = str(raw_d.get("id") or "")
                d_proj = str(raw_d.get("project") or "")
                dkey = (d_proj, did_str)
                if did_str and dkey not in seen_delivery_keys:
                    seen_delivery_keys.add(dkey)
                    all_deliveries.append({
                        **raw_d,
                        "id": did_str,
                        "qualified_id": raw_d.get("qualified_id") or (f"{d_proj}/{did_str}" if d_proj else did_str),
                        "project": d_proj,
                        "state": "delivered",
                        "host": raw_d.get("host") or hid,
                    })

    # Ensure any task in all_tasks with state == 'delivered' is also present in all_deliveries,
    # and propagate run host onto tasks that didn't have an explicit host
    run_host_by_task: dict[str, str] = {}
    for r in all_runs:
        tid = str(r.get("task_id") or "")
        rhost = str(r.get("host") or "")
        if tid and rhost and (tid not in run_host_by_task or r.get("status") in ("running", "starting")):
            run_host_by_task[tid] = rhost

    for t in all_tasks:
        tid = str(t.get("id") or "")
        t_proj = str(t.get("project") or "")
        if not t.get("explicit_host") and tid in run_host_by_task:
            t["host"] = run_host_by_task[tid]
        if t.get("state") == "delivered":
            dkey = (t_proj, tid)
            if dkey not in seen_delivery_keys:
                seen_delivery_keys.add(dkey)
                all_deliveries.append({
                    "id": tid,
                    "qualified_id": t.get("qualified_id") or (f"{t_proj}/{tid}" if t_proj else tid),
                    "project": t_proj,
                    "workspace": t.get("workspace", ""),
                    "title": t.get("title", ""),
                    "short_title": t.get("short_title") or t.get("title", ""),
                    "state": "delivered",
                    "verify_by": t.get("verify_by") or t.get("verifier") or "-",
                    "executor": t.get("executor") or "-",
                    "host": t.get("host") or cur_host,
                    "run_id": t.get("run_id"),
                })

    tasks_by_state: dict[str, int] = dict(extra_state_counts)
    tasks_by_host: dict[str, int] = dict(extra_host_counts)
    tasks_by_state_and_host: dict[str, dict[str, int]] = {}

    for t in all_tasks:
        st = str(t.get("state") or "open")
        th = str(t.get("host") or "unassigned")
        tasks_by_state[st] = tasks_by_state.get(st, 0) + 1
        tasks_by_host[th] = tasks_by_host.get(th, 0) + 1
        st_map = tasks_by_state_and_host.setdefault(st, {})
        st_map[th] = st_map.get(th, 0) + 1

    all_runs.sort(key=lambda r: str(r.get("run_id") or ""), reverse=True)

    for hid, hinfo in hosts_status.items():
        h_runs = [r for r in all_runs if r.get("host") == hid]
        hinfo["runs_count"] = len(h_runs)
        hinfo["active_runs_count"] = sum(1 for r in h_runs if r.get("status") in ("running", "starting"))
        hinfo["tasks_count"] = tasks_by_host.get(hid, 0)

    return {
        "ok": True,
        "host": cur_host,
        "hub_host": hub_host_id or cur_host,
        "hub_reachable": hub_reachable,
        "all_hosts": bool(all_hosts),
        "registry_source": registry_source,
        "snapshot_version": snapshot_version,
        "hub_error": hub_error,
        "hosts": hosts_status,
        "items": projects_out,
        "projects": projects_out,
        "workspaces": projects_out,
        "tasks": all_tasks,
        "tasks_by_state": tasks_by_state,
        "tasks_by_host": tasks_by_host,
        "tasks_by_state_and_host": tasks_by_state_and_host,
        "tasks_summary": {
            "total": sum(tasks_by_state.values()),
            "by_state": tasks_by_state,
            "by_host": tasks_by_host,
            "by_state_and_host": tasks_by_state_and_host,
        },
        "runs": all_runs,
        "open_questions": all_open_questions,
        "questions": all_open_questions,
        "deliveries_to_verify": all_deliveries,
        "verification_queue": all_deliveries,
    }


get_console_status = get_console_status_projects


def _find_matching_run_for_attach(
    runs: list[dict[str, Any]],
    target: str,
) -> dict[str, Any] | None:
    # 1. Exact run_id match
    for r in runs:
        if str(r.get("run_id") or "") == target:
            return r
    # 2. Task ID or qualified <project>/<task_id> match
    candidates: list[dict[str, Any]] = []
    for r in runs:
        tid = str(r.get("task_id") or r.get("task") or r.get("note_id") or "")
        proj = str(r.get("project") or "")
        qid = f"{proj}/{tid}" if proj and tid else tid
        if tid == target or qid == target:
            candidates.append(r)
        elif r.get("is_batch") and isinstance(r.get("batch_members"), list) and target in r["batch_members"]:
            candidates.append(r)
    if not candidates:
        return None
    candidates.sort(
        key=lambda r: (
            0 if r.get("status") in ("running", "starting") else 1,
            str(r.get("run_id") or ""),
        ),
    )
    # Sort active first, and among same activity level pick newest run_id
    active_cands = [r for r in candidates if r.get("status") in ("running", "starting")]
    if active_cands:
        active_cands.sort(key=lambda r: str(r.get("run_id") or ""), reverse=True)
        return active_cands[0]
    candidates.sort(key=lambda r: str(r.get("run_id") or ""), reverse=True)
    return candidates[0]


def resolve_console_attach(
    target: str,
    config_dir: pathlib.Path | str | None = None,
    *,
    workspace: pathlib.Path | str | None = None,
    ssh_timeout: float = 5.0,
) -> dict[str, Any]:
    """Resolve host, agent user, and screen session name from a run or task ID without shell interpolation."""
    if not isinstance(target, str):
        raise ValueError("Attach target must be a string")
    clean_target = target.strip()
    if (
        not clean_target
        or clean_target.startswith("-")
        or ".." in clean_target
        or not SAFE_ATTACH_TARGET_RE.match(clean_target)
    ):
        raise ValueError(
            f"Invalid run or task identifier {target!r}: must match ^[A-Za-z0-9][A-Za-z0-9._/-]{{0,127}}$"
        )

    cdir = pathlib.Path(config_dir).resolve() if config_dir is not None else get_global_config_dir()
    gpath = cdir / "orchestration.toml"
    gcfg = load_toml_file(gpath) if gpath.is_file() else {}
    cur_host = _resolve_current_host_id(cdir)
    hosts_table = _resolve_merged_hosts_table(cdir, gcfg, gpath, workspace=workspace)

    hub_host_id: str | None = None
    if isinstance(gcfg.get("host"), dict) and gcfg["host"].get("role") == "hub":
        hub_host_id = cur_host
    for hid, hcfg in hosts_table.items():
        if isinstance(hcfg, dict) and hcfg.get("role") == "hub":
            hub_host_id = hid
            break

    # 1. Search local runs first (read-only, without marking mock/cross-user screen runs lost)
    local_workspaces = list_workspaces(cdir)
    local_proj_dirs = _discover_local_project_dirs(cur_host, local_workspaces, workspace=workspace)
    cwd_p = pathlib.Path.cwd().resolve()
    if (cwd_p / ".ai-orchestration" / "runs").is_dir() and all(d != cwd_p for _, _, d in local_proj_dirs):
        local_proj_dirs.insert(0, (sanitize_slug(cwd_p.name), None, cwd_p))

    local_runs: list[dict[str, Any]] = []
    for p_slug, _, p_dir in local_proj_dirs:
        local_runs.extend(_collect_runs_for_dir(p_dir, p_slug, cur_host, reconcile_local=False))

    matched_run = _find_matching_run_for_attach(local_runs, clean_target)

    # 2. If not found locally (or local match is not active), query remote hosts via console status
    if matched_run is None or matched_run.get("status") not in ("running", "starting"):
        status_res = get_console_status_projects(
            config_dir=cdir,
            all_hosts=True,
            ssh_timeout=ssh_timeout,
            workspace=workspace,
            local_only=False,
        )
        remote_match = _find_matching_run_for_attach(status_res.get("runs", []), clean_target)
        if remote_match is not None and (
            matched_run is None or remote_match.get("status") in ("running", "starting")
        ):
            matched_run = remote_match

    if matched_run is None:
        raise ValueError(f"No run found for {clean_target!r}")

    # Merge hosts table from matched_run's workspace if local
    run_ws = matched_run.get("workspace")
    if isinstance(run_ws, str) and run_ws.strip():
        run_ws_p = pathlib.Path(run_ws)
        if run_ws_p.is_dir():
            hosts_table = _resolve_merged_hosts_table(cdir, gcfg, gpath, workspace=run_ws_p)
            for hid, hcfg in hosts_table.items():
                if isinstance(hcfg, dict) and hcfg.get("role") == "hub":
                    hub_host_id = hid
                    break

    run_host = str(matched_run.get("host") or cur_host).strip()
    if not SAFE_HOST_ID_RE.match(run_host):
        raise ValueError(f"Invalid host id {run_host!r} in run record")
    if run_host != cur_host and run_host not in hosts_table:
        raise ValueError(f"Run host {run_host!r} is not declared in [hosts] configuration")

    hcfg = (
        hosts_table.get(run_host)
        or (gcfg.get("host") if isinstance(gcfg.get("host"), dict) and run_host == cur_host else {})
        or {}
    )
    role = str(hcfg.get("role") or ("hub" if run_host == hub_host_id else "client"))
    base_target = str(
        hcfg.get("ssh_target")
        or hcfg.get("ssh")
        or hcfg.get("target")
        or hcfg.get("hostname")
        or run_host
    ).strip()
    if not base_target or base_target.startswith("-") or not SAFE_SSH_TARGET_RE.match(base_target):
        raise ValueError(f"Invalid SSH target {base_target!r} for host {run_host!r}")

    if role == "hub":
        # Review §10.6 (B2): hub agents run as a dedicated user (default `kilo`).
        # Generic `user` must not override `agent_user` / `kilo` fallback on the hub.
        explicit_agent_user = (
            hcfg.get("_explicit_agent_user")
            if "_explicit_agent_user" in hcfg
            else (hcfg.get("agent_user") or hcfg.get("agents_user"))
        )
        agent_user = str(explicit_agent_user).strip() if explicit_agent_user else "kilo"
    else:
        raw_user = (
            hcfg.get("_explicit_agent_user")
            if "_explicit_agent_user" in hcfg and hcfg.get("_explicit_agent_user")
            else (hcfg.get("agent_user") or hcfg.get("user") or hcfg.get("agents_user"))
        )
        agent_user = str(raw_user).strip() if raw_user is not None and str(raw_user).strip() else None

    if agent_user is not None:
        if not agent_user or agent_user.startswith("-") or not SAFE_AGENT_USER_RE.match(agent_user):
            raise ValueError(f"Invalid agent_user {agent_user!r} for host {run_host!r}")

    if "@" in base_target:
        target_user, target_host = base_target.split("@", 1)
        if not target_host or target_host.startswith("-"):
            raise ValueError(f"Invalid SSH target {base_target!r} for host {run_host!r}")
        if role == "hub":
            # Strip any conflicting username (e.g. `owner@hub`) so hub attach always uses `agent_user` (`kilo@hub`)
            attach_target = f"{agent_user}@{target_host}"
        elif agent_user and target_user != agent_user:
            attach_target = f"{agent_user}@{target_host}"
        else:
            attach_target = base_target
    elif agent_user:
        attach_target = f"{agent_user}@{base_target}"
    else:
        attach_target = base_target

    if attach_target.startswith("-") or not SAFE_SSH_TARGET_RE.match(attach_target):
        raise ValueError(f"Invalid resolved SSH attach target {attach_target!r}")

    screen_session = (
        matched_run.get("screen_session")
        or matched_run.get("session_name")
        or (matched_run.get("screen") or {}).get("session_name")
    )
    if not screen_session:
        raise ValueError(
            f"Run {matched_run.get('run_id')!r} does not have a screen session "
            f"(backend={matched_run.get('backend', 'setsid')!r})"
        )
    screen_session = str(screen_session).strip()
    if screen_session.startswith("-") or not SAFE_SCREEN_SESSION_RE.match(screen_session):
        raise ValueError(f"Invalid screen session name {screen_session!r}")

    ssh_cmd = ["ssh", "-t"]
    if isinstance(hcfg.get("port"), int) and not isinstance(hcfg.get("port"), bool):
        ssh_cmd.extend(["-p", str(hcfg["port"])])
    id_file = hcfg.get("identity_file") or hcfg.get("ssh_key")
    if isinstance(id_file, str) and id_file.strip():
        clean_id = id_file.strip()
        if clean_id.startswith("-"):
            raise ValueError(f"Invalid identity_file {clean_id!r}")
        ssh_cmd.extend(["-i", clean_id])
    remote_attach_cmd = shlex.join(["screen", "-x", screen_session])
    ssh_cmd.extend([attach_target, remote_attach_cmd])

    return {
        "ok": True,
        "target_query": clean_target,
        "run_id": matched_run.get("run_id"),
        "task_id": matched_run.get("task_id"),
        "project": matched_run.get("project"),
        "workspace": matched_run.get("workspace"),
        "host": run_host,
        "role": role,
        "ssh_target": attach_target,
        "target": attach_target,
        "agent_user": agent_user,
        "screen_session": screen_session,
        "session_name": screen_session,
        "command": ssh_cmd,
        "actor": f"owner (via console@{cur_host})",
    }



# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------


def _join_positional(val: Any, default: str | None = None) -> str | None:
    if isinstance(val, list):
        joined = " ".join(str(x) for x in val if x is not None).strip()
        return joined if joined else default
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


def cli_workspace_register(args: argparse.Namespace) -> int:
    target_path = _join_positional(args.path, ".") or "."
    try:
        plan = plan_workspace_register(
            path=target_path,
            slug=args.id,
            title=args.title,
            config_dir=args.config_dir,
            host=getattr(args, "host", None),
            primary_host=getattr(args, "primary_host", None),
            reference_repo=getattr(args, "reference_repo", None),
            mirror_repo=getattr(args, "mirror_repo", None),
            convention_version=getattr(args, "convention_version", None),
            link_uuid=getattr(args, "link_uuid", None),
        )
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if not args.apply:
        if args.json:
            print(json.dumps(plan, indent=2))
        else:
            print("=" * 70)
            print("Workspace Registration Plan Preview")
            print("=" * 70)
            print(f"Action        : {plan['action']}")
            print(f"Slug          : {plan['workspace']['slug']}")
            print(f"UUID          : {plan['workspace']['uuid']}")
            print(f"Path          : {plan['workspace']['canonical_path']}")
            if plan.get("moved_from"):
                print(f"Note          : moved from {plan['moved_from']}")
            if plan.get("outer_workspace"):
                outer = plan["outer_workspace"]
                leaving = plan.get("projects_leaving", [])
                print(f"Outer WS      : {outer['slug']} ({outer['uuid']})")
                print(f"Projects left : {len(leaving)} will leave outer workspace")
            print(f"\nPlan hash     : {plan['plan_hash']}")
            cpath = plan["workspace"]["canonical_path"]
            quoted_cpath = f'"{cpath}"' if " " in cpath else cpath
            link_flag = f" --link {args.link_uuid}" if getattr(args, "link_uuid", None) else ""
            print(f"\nTo apply: ai-orch workspace register {quoted_cpath}{link_flag} --apply --expect-hash {plan['plan_hash']}")
        return 0

    try:
        expect_h = args.expect_hash or plan.get("plan_hash")
        res = apply_workspace_register(plan, expect_hash=expect_h, config_dir=args.config_dir)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"[OK] Workspace registered: {res['workspace']['slug']} ({res['workspace']['uuid']})")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] Failed to apply registration: {e}", file=sys.stderr)
        return 2


def cli_workspace_unregister(args: argparse.Namespace) -> int:
    try:
        plan = plan_workspace_unregister(args.id, config_dir=args.config_dir)
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if not args.apply:
        if args.json:
            print(json.dumps(plan, indent=2))
        else:
            print("=" * 70)
            print("Workspace Unregistration Plan Preview")
            print("=" * 70)
            print(f"Slug      : {plan['workspace']['slug']}")
            print(f"UUID      : {plan['workspace']['uuid']}")
            print(f"Path      : {plan['workspace']['canonical_path']}")
            if plan.get("message"):
                print(f"Note      : {plan['message']}")
            print(f"\nPlan hash : {plan['plan_hash']}")
            print(f"\nTo apply: ai-orch workspace unregister {args.id} --apply --expect-hash {plan['plan_hash']}")
        return 0

    try:
        res = apply_workspace_unregister(plan, expect_hash=args.expect_hash, config_dir=args.config_dir)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"[OK] Workspace unregistered: {res['unregistered']}")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] Failed to unregister: {e}", file=sys.stderr)
        return 2


def cli_workspace_list(args: argparse.Namespace) -> int:
    try:
        items = list_workspaces(config_dir=args.config_dir)
        hub_doc = load_hub_registry(args.config_dir)
        snap_ver = int(hub_doc.get("snapshot_version", 0))
        if args.json:
            print(json.dumps({"ok": True, "snapshot_version": snap_ver, "items": items}, indent=2))
        else:
            if not items:
                print("No registered workspaces.")
                return 0
            print(f"{'SLUG':<20} {'UUID':<38} {'STATUS':<8} {'PATH'}")
            print("-" * 80)
            for it in items:
                status = "stale" if it.get("stale") else "active"
                print(f"{it['slug']:<20} {it['uuid']:<38} {status:<8} {it['canonical_path']}")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2


def cli_workspace_show(args: argparse.Namespace) -> int:
    try:
        ws = show_workspace(args.id, config_dir=args.config_dir)
        if args.json:
            print(json.dumps({"ok": True, "workspace": ws}, indent=2))
        else:
            print(f"Workspace : {ws['slug']}")
            print(f"UUID      : {ws['uuid']}")
            print(f"Title     : {ws.get('title') or '(none)'}")
            print(f"Path      : {ws['canonical_path']}")
            print(f"Status    : {'stale' if ws.get('stale') else 'active'}")
            print(f"Projects  : {len(ws.get('projects', []))}")
            for p in ws.get("projects", []):
                print(f"  - {p['slug']:<15} {p['uuid']} ({p['rel_path']})")
            if ws.get("sub_workspaces"):
                print(f"Sub-Workspaces : {len(ws['sub_workspaces'])}")
                for sw in ws["sub_workspaces"]:
                    print(f"  - {sw['slug']:<15} {sw['uuid']} ({sw['canonical_path']})")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2


def cli_projects_discover(args: argparse.Namespace) -> int:
    target_ws = _join_positional(args.workspace, None)
    try:
        plan = plan_projects_discover(target_ws, config_dir=args.config_dir)
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if not args.apply:
        if args.json:
            print(json.dumps(plan, indent=2))
        else:
            print("=" * 70)
            print("Projects Discovery Plan Preview")
            print("=" * 70)
            status_str = "" if plan.get("workspace_registered", True) else " [unregistered]"
            print(f"Workspace : {plan['workspace']} ({plan['workspace_uuid']}){status_str}")
            print(f"Path      : {plan.get('canonical_path', plan.get('workspace_path'))}")
            print(f"Config    : {plan['config_path']}")
            print(f"\nProposed Projects ({len(plan['proposed_projects'])}):")
            for p in plan["proposed_projects"]:
                print(f"  - {p['id']:<18} path={p['path']:<20} uuid={p['uuid']}")
            if plan["sub_workspaces"]:
                print(f"\nDetected Sub-Workspaces ({len(plan['sub_workspaces'])}):")
                for sw in plan["sub_workspaces"]:
                    print(f"  - {sw['slug']:<18} path={sw['path']:<20} (sub_workspace, read-only)")
            print(f"\nPlan hash : {plan['plan_hash']}")
            raw_ws = target_ws or ""
            quoted_ws = f'"{raw_ws}"' if " " in raw_ws else raw_ws
            print(f"\nTo apply: ai-orch projects discover {quoted_ws} --apply --expect-hash {plan['plan_hash']}")
        return 0

    try:
        expect_h = args.expect_hash or plan.get("plan_hash")
        res = apply_projects_discover(plan, expect_hash=expect_h, config_dir=args.config_dir)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"[OK] Applied {len(res['projects'])} projects to {plan['config_path']}")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] Failed to apply project discovery: {e}", file=sys.stderr)
        return 2


def cli_projects_list(args: argparse.Namespace) -> int:
    target_ws = _join_positional(args.workspace, None)
    try:
        res = list_projects(target_ws, config_dir=args.config_dir)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"Projects in workspace '{res['workspace']}':")
            print(f"{'ID':<20} {'KIND':<16} {'PATH':<25} {'UUID'}")
            print("-" * 80)
            for it in res["items"]:
                print(f"{it['slug']:<20} {it['kind']:<16} {it['path']:<25} {it['uuid']}")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2


def cli_workspace_next(args: argparse.Namespace) -> int:
    ws_target = getattr(args, "root", None) or _join_positional(getattr(args, "workspace", None), None)
    engine_script = (
        REPO_ROOT
        / "plugins"
        / "architect-side"
        / "skills"
        / "task-pipeline"
        / "scripts"
        / "tasks_engine.py"
    )
    cmd = [sys.executable, str(engine_script), "next", "--all-projects"]
    if ws_target:
        cmd.extend(["--workspace", ws_target])
    if getattr(args, "limit", None) is not None:
        cmd.extend(["--limit", str(args.limit)])
    if getattr(args, "json", False):
        cmd.append("--json")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def cli_workspace_import_migration(args: argparse.Namespace) -> int:
    target_file = _join_positional(args.file, None) or str(pathlib.Path.home() / "works" / "MIGRATION_REGISTRY.json")
    try:
        plan = plan_import_migration_registry(
            target_file,
            config_dir=args.config_dir,
            host=getattr(args, "host", None),
        )
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if not args.apply:
        if args.json:
            print(json.dumps(plan, indent=2))
        else:
            print("=" * 70)
            print("Migration Registry Import Plan Preview")
            print("=" * 70)
            print(f"Source        : {plan['source_path']}")
            print(f"Hub Registry  : {plan['hub_registry_path']}")
            print(f"Host          : {plan['host']}")
            print(f"Projects      : {plan['imported_count']}")
            for p in plan["projects"]:
                print(f"  - {p['slug']:<22} {p['uuid']} (primary={p['primary_host']})")
            print(f"\nPlan hash     : {plan['plan_hash']}")
            quoted = f'"{target_file}"' if " " in target_file else target_file
            print(f"\nTo apply: ai-orch workspace import-migration {quoted} --apply --expect-hash {plan['plan_hash']}")
        return 0

    try:
        res = apply_import_migration_registry(plan, expect_hash=args.expect_hash, config_dir=args.config_dir)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"[OK] Imported {res['imported_count']} project(s) into {res['hub_registry_path']}")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] Failed to import migration registry: {e}", file=sys.stderr)
        return 2


def cli_console_status(args: argparse.Namespace) -> int:
    try:
        raw_timeout = getattr(args, "timeout", None)
        explicit_timeout = raw_timeout is not None
        ssh_timeout = float(raw_timeout) if raw_timeout is not None else 5.0
        res = get_console_status_projects(
            config_dir=args.config_dir,
            all_hosts=bool(getattr(args, "all_hosts", False)),
            ssh_timeout=ssh_timeout,
            workspace=getattr(args, "workspace", None),
            local_only=bool(getattr(args, "local_only", False)),
            explicit_timeout=explicit_timeout,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            hub_str = "reachable" if res["hub_reachable"] else f"UNREACHABLE ({res['registry_source']})"
            print(f"Host: {res['host']} | Hub ({res['hub_host']}): {hub_str} | Source: {res['registry_source']}")
            print("\nHosts:")
            for hid, hinfo in res.get("hosts", {}).items():
                st_lbl = "reachable" if hinfo.get("reachable") else f"UNREACHABLE ({hinfo.get('error') or 'down'})"
                loc_lbl = " [local]" if hinfo.get("local") else ""
                print(
                    f"  - {hid:<16} role={hinfo.get('role', 'client'):<8} status={st_lbl}{loc_lbl} "
                    f"(runs={hinfo.get('runs_count', 0)}, tasks={hinfo.get('tasks_count', 0)})"
                )
            print(f"\nProjects ({len(res.get('projects', []))}):")
            print(f"{'SLUG':<22} {'UUID':<38} {'PRIMARY':<12} {'CONV':<8} {'PATH'}")
            print("-" * 100)
            for p in res.get("projects", []):
                conv = p.get("convention_version") or "-"
                prim = p.get("primary_host") or "-"
                cpath = p.get("canonical_path") or "-"
                print(f"{p['slug']:<22} {str(p.get('uuid') or '-'):<38} {prim:<12} {conv:<8} {cpath}")

            by_st = res.get("tasks_by_state", {})
            by_h = res.get("tasks_by_host", {})
            st_summary = ", ".join(f"{k}: {v}" for k, v in sorted(by_st.items())) or "none"
            h_summary = ", ".join(f"{k}: {v}" for k, v in sorted(by_h.items())) or "none"
            print(f"\nTasks by state: {st_summary}")
            print(f"Tasks by host : {h_summary}")

            runs = res.get("runs", [])
            print(f"\nRuns ({len(runs)}):")
            if runs:
                print(
                    f"{'RUN ID':<36} {'HOST':<14} {'TASK':<10} {'STATE':<11} "
                    f"{'SESSION':<26} {'AGE(s)':<9} {'LAST HEARTBEAT'}"
                )
                print("-" * 125)
                for r in runs:
                    age_s = f"{r['age_sec']:.1f}" if isinstance(r.get("age_sec"), (int, float)) else "-"
                    hb_s = str(r.get("last_heartbeat") or "-")
                    sess_s = str(r.get("screen_session") or "-")
                    print(
                        f"{str(r.get('run_id') or '-'):<36} {str(r.get('host') or '-'):<14} "
                        f"{str(r.get('task_id') or '-'):<10} {str(r.get('status') or '-'):<11} "
                        f"{sess_s:<26} {age_s:<9} {hb_s}"
                    )

            oqs = res.get("open_questions", [])
            print(f"\nOpen Questions ({len(oqs)}):")
            for q in oqs:
                print(f"  - [{q.get('qualified_id') or q.get('id')}] {q.get('question') or q.get('title') or ''} (blocks: {q.get('blocks', '-')})")

            delivs = res.get("deliveries_to_verify", [])
            print(f"\nDeliveries to Verify ({len(delivs)}):")
            for d in delivs:
                print(
                    f"  - [{d.get('qualified_id') or d.get('id')}] {d.get('title') or ''} "
                    f"(host={d.get('host', '-')}, verify-by={d.get('verify_by', '-')})"
                )
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2


def cli_console_attach(args: argparse.Namespace) -> int:
    try:
        res = resolve_console_attach(
            target=args.target,
            config_dir=args.config_dir,
            workspace=getattr(args, "workspace", None),
            ssh_timeout=float(getattr(args, "timeout", 5.0) or 5.0),
        )
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if getattr(args, "dry_run", False):
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(" ".join(res["command"]))
        return 0

    ssh_cmd = res["command"]
    try:
        if args.json:
            proc = subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
            out_payload = {
                **res,
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
            print(json.dumps(out_payload, indent=2))
            return proc.returncode
        proc = subprocess.run(ssh_cmd, check=False)
        return proc.returncode
    except Exception as e:
        if args.json:
            print(json.dumps({**res, "ok": False, "error": str(e)}))
        else:
            print(f"[ERROR] Failed to execute ssh attach: {e}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])

    # Support shorthand invocation:
    # "ai-orch workspace <subcmd>" or "orchestration_registry.py workspace <subcmd>"
    # or "orchestration_registry.py register" -> "workspace register"
    is_console_group = False
    if raw_args and raw_args[0] in ("workspace", "workspaces"):
        raw_args = raw_args[1:]
        is_workspace_group = True
        is_projects_group = False
    elif raw_args and raw_args[0] in ("projects", "project"):
        raw_args = raw_args[1:]
        is_workspace_group = False
        is_projects_group = True
    elif raw_args and raw_args[0] == "console":
        raw_args = raw_args[1:]
        is_workspace_group = False
        is_projects_group = False
        is_console_group = True
    else:
        is_workspace_group = False
        is_projects_group = False

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    # workspace register
    p_reg = subparsers.add_parser("register", help="Register a workspace")
    p_reg.add_argument("path", nargs="*", default=["."], help="Workspace path (default: .)")
    p_reg.add_argument("--id", dest="id", default=None, help="Workspace slug ID")
    p_reg.add_argument("--title", default=None, help="Workspace title")
    p_reg.add_argument("--host", default=None, help="Host ID for this checkout")
    p_reg.add_argument("--primary-host", dest="primary_host", default=None, help="Primary development host ID")
    p_reg.add_argument("--reference-repo", dest="reference_repo", default=None, help="Reference repository URL/path on hub")
    p_reg.add_argument("--mirror-repo", "--mirror", dest="mirror_repo", default=None, help="Off-site mirror repository URL")
    p_reg.add_argument("--convention-version", dest="convention_version", default=None, help="Project convention_version")
    p_reg.add_argument("--link", dest="link_uuid", default=None, help="Explicitly link this checkout to an existing workspace UUID in the hub registry")
    p_reg.add_argument("--apply", action="store_true", help="Apply registration")
    p_reg.add_argument("--expect-hash", dest="expect_hash", default=None, help="Expected plan hash")
    p_reg.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_reg.add_argument("--json", action="store_true", help="Output JSON")

    # workspace unregister
    p_unreg = subparsers.add_parser("unregister", help="Unregister a workspace")
    p_unreg.add_argument("id", help="Workspace ID or UUID")
    p_unreg.add_argument("--apply", action="store_true", help="Apply unregistration")
    p_unreg.add_argument("--expect-hash", dest="expect_hash", default=None, help="Expected plan hash")
    p_unreg.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_unreg.add_argument("--json", action="store_true", help="Output JSON")

    # workspace list
    p_wlist = subparsers.add_parser("list", help="List workspaces")
    p_wlist.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_wlist.add_argument("--json", action="store_true", help="Output JSON")

    # workspace show
    p_show = subparsers.add_parser("show", help="Show workspace details")
    p_show.add_argument("id", help="Workspace ID or UUID")
    p_show.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_show.add_argument("--json", action="store_true", help="Output JSON")

    # workspace next
    p_wnext = subparsers.add_parser("next", help="Show ready queue across all projects in workspace")
    p_wnext.add_argument("workspace", nargs="*", default=None, help="Workspace slug, UUID, or path")
    p_wnext.add_argument("--root", dest="root", default=None, help="Workspace root path")
    p_wnext.add_argument("--limit", type=int, default=None, help="Maximum number of tasks to return")
    p_wnext.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_wnext.add_argument("--json", action="store_true", help="Output JSON")

    # workspace import-migration
    p_imp = subparsers.add_parser("import-migration", help="Import MIGRATION_REGISTRY.json into the hub registry")
    p_imp.add_argument("file", nargs="*", default=None, help="Path to MIGRATION_REGISTRY.json")
    p_imp.add_argument("--host", default=None, help="Override current host ID")
    p_imp.add_argument("--apply", action="store_true", help="Apply migration import")
    p_imp.add_argument("--expect-hash", dest="expect_hash", default=None, help="Expected plan hash")
    p_imp.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_imp.add_argument("--json", action="store_true", help="Output JSON")

    # console status
    p_cstat = subparsers.add_parser("console-status", help="Aggregate multi-host projects, tasks, runs, open questions, and deliveries")
    p_cstat.add_argument("--all-hosts", dest="all_hosts", action="store_true", help="Query all declared hosts")
    p_cstat.add_argument("--local", "--local-only", dest="local_only", action="store_true", help="Collect local host status only without SSH")
    p_cstat.add_argument("--timeout", type=float, default=None, help="SSH timeout in seconds")
    p_cstat.add_argument("--project", "--workspace", dest="workspace", default=None, help="Optional project/workspace path")
    p_cstat.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_cstat.add_argument("--json", action="store_true", help="Output JSON")

    # console attach
    p_cattach = subparsers.add_parser("console-attach", help="Resolve host and screen session from run/task and open ssh -t <target> screen -x <session>")
    p_cattach.add_argument("target", help="Run ID or Task ID to attach to")
    p_cattach.add_argument("--project", "--workspace", dest="workspace", default=None, help="Optional project/workspace path")
    p_cattach.add_argument("--timeout", type=float, default=5.0, help="SSH timeout in seconds for remote run lookup")
    p_cattach.add_argument("--dry-run", dest="dry_run", action="store_true", help="Resolve and print attach command without running ssh")
    p_cattach.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_cattach.add_argument("--json", action="store_true", help="Output JSON")

    # projects discover
    p_disc = subparsers.add_parser("discover", help="Discover projects in a workspace")
    p_disc.add_argument("workspace", nargs="*", default=None, help="Workspace slug, UUID, or path")
    p_disc.add_argument("--apply", action="store_true", help="Apply discovery proposal")
    p_disc.add_argument("--expect-hash", dest="expect_hash", default=None, help="Expected plan hash")
    p_disc.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_disc.add_argument("--json", action="store_true", help="Output JSON")

    # projects list
    p_plist = subparsers.add_parser("projects-list", help="List projects in a workspace")
    p_plist.add_argument("workspace", nargs="*", default=None, help="Workspace slug, UUID, or path")
    p_plist.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_plist.add_argument("--json", action="store_true", help="Output JSON")

    # If dispatched as "projects list", map "list" to "projects-list"
    if is_projects_group and raw_args and raw_args[0] == "list":
        raw_args[0] = "projects-list"
    elif is_projects_group and raw_args and raw_args[0] in ("import-migration", "import-migration-registry"):
        raw_args[0] = "import-migration"
    elif is_console_group and (not raw_args or raw_args[0] == "status"):
        raw_args = ["console-status"] + (raw_args[1:] if raw_args else [])
    elif is_console_group and raw_args and raw_args[0] == "attach":
        raw_args = ["console-attach"] + raw_args[1:]
    elif raw_args and raw_args[0] == "import-migration-registry":
        raw_args[0] = "import-migration"

    if not raw_args or raw_args[0] in ("-h", "--help"):
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(raw_args)
    except SystemExit as e:
        code = int(e.code) if isinstance(e.code, int) else 2
        if "--json" in raw_args and code != 0:
            print(json.dumps({"ok": False, "error": "Invalid or unrecognized CLI arguments"}))
        return code

    if args.command == "register":
        return cli_workspace_register(args)
    elif args.command == "unregister":
        return cli_workspace_unregister(args)
    elif args.command == "list":
        return cli_workspace_list(args)
    elif args.command == "show":
        return cli_workspace_show(args)
    elif args.command == "next":
        return cli_workspace_next(args)
    elif args.command == "import-migration":
        return cli_workspace_import_migration(args)
    elif args.command == "console-status":
        return cli_console_status(args)
    elif args.command == "console-attach":
        return cli_console_attach(args)
    elif args.command == "discover":
        return cli_projects_discover(args)
    elif args.command == "projects-list":
        return cli_projects_list(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
