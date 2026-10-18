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
import datetime
import hashlib
import json
import logging
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
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
        find_project_config_path,
        config_lock,
        load_toml_file,
        dump_toml,
        set_toml_value,
        is_valid_workspace_slug,
        is_valid_project_slug,
        is_valid_uuid4,
    )
except ImportError:
    # Standalone fallbacks if orchestration_config cannot be imported directly
    def find_project_config_path(ws: pathlib.Path, global_path: pathlib.Path | None = None) -> pathlib.Path:
        local_dot = ws / ".ai-orchestration.local.toml"
        if local_dot.exists():
            return local_dot
        gpath = global_path or (get_global_config_dir() / "orchestration.toml")
        projects_root = gpath.parent / "projects"
        return projects_root / ws.resolve().name / "orchestration.toml"

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


@contextlib.contextmanager
def registry_lock(
    config_dir: pathlib.Path | str | None = None,
    timeout: float = 10.0,
) -> Iterator[pathlib.Path]:
    """Exclusive fcntl.flock with a deadline on <global config dir>/broker/registry.lock."""
    lock_file = get_lock_path(config_dir)
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

        yield lock_file
    finally:
        if acquired and fcntl is not None:
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
    """Initialize SQLite schema if not present."""
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
                last_seen TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                uuid TEXT PRIMARY KEY,
                workspace_uuid TEXT NOT NULL REFERENCES workspaces(uuid) ON DELETE CASCADE,
                slug TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                UNIQUE (workspace_uuid, slug),
                UNIQUE (workspace_uuid, rel_path)
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


def is_git_ignored(path: pathlib.Path, ws_path: pathlib.Path) -> bool:
    """Check whether `path` is ignored by git, asked of the repository that owns it.

    A workspace often groups nested repositories (each sub-project its own repo) under an outer repo whose
    .gitignore is an allowlist; the outer repo then "ignores" every nested repo. A nested repository root is
    therefore never ignored, and a path inside a nested repository is checked against that repository only.
    """
    try:
        if (path / ".git").exists():
            return False
        repo = _git_repo_root(path)
        if repo is None:
            return False
        rel = path.relative_to(repo)
        proc = subprocess.run(
            ["git", "check-ignore", "-q", str(rel)],
            cwd=str(repo),
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


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


def plan_workspace_register(
    path: str | pathlib.Path | None = None,
    slug: str | None = None,
    title: str | None = None,
    config_dir: pathlib.Path | str | None = None,
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

    # Inspect project config
    cfg_path = find_project_config_path(canonical)
    existing_cfg = load_toml_file(cfg_path) if cfg_path.exists() else {}
    ws_cfg = existing_cfg.get("workspace", {})

    ws_uuid = ws_cfg.get("uuid") or deterministic_uuid4(f"workspace:{canonical}")
    ws_slug = slug or ws_cfg.get("id") or sanitize_slug(canonical.name)
    ws_title = title if title is not None else ws_cfg.get("title")

    if not is_valid_workspace_slug(ws_slug):
        raise ValueError(
            f"Invalid workspace slug '{ws_slug}': must match ^[a-z0-9][a-z0-9-]{{1,47}}$"
        )
    if not is_valid_uuid4(ws_uuid):
        raise ValueError(f"Invalid workspace UUID '{ws_uuid}': must be a valid UUID4")

    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        # Check if uuid already registered
        row_by_uuid = conn.execute(
            "SELECT * FROM workspaces WHERE uuid = ?", (ws_uuid,)
        ).fetchone()

        # Check if slug taken by another uuid
        row_by_slug = conn.execute(
            "SELECT * FROM workspaces WHERE slug = ? AND uuid != ?",
            (ws_slug, ws_uuid),
        ).fetchone()
        if row_by_slug:
            raise ValueError(
                f"Slug '{ws_slug}' is already registered to workspace '{row_by_slug['uuid']}'"
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

        # 2. Update SQLite
        conn = get_connection(db_path)
        try:
            with conn:
                existing = conn.execute(
                    "SELECT registered_at FROM workspaces WHERE uuid = ?", (ws_uuid,)
                ).fetchone()
                reg_at = existing["registered_at"] if existing else now

                conn.execute(
                    """
                    INSERT INTO workspaces (uuid, slug, title, canonical_path, device, inode, registered_at, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uuid) DO UPDATE SET
                        slug = excluded.slug,
                        title = excluded.title,
                        canonical_path = excluded.canonical_path,
                        device = excluded.device,
                        inode = excluded.inode,
                        last_seen = excluded.last_seen;
                    """,
                    (ws_uuid, ws_slug, ws_title, str(canonical_path), dev, ino, reg_at, now),
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
                cfg = load_toml_file(cfg_path)
                ws_projects = cfg.get("workspace", {}).get("projects", [])
                for p in ws_projects:
                    conn.execute(
                        """
                        INSERT INTO projects (uuid, workspace_uuid, slug, rel_path)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(workspace_uuid, slug) DO UPDATE SET
                            uuid = excluded.uuid,
                            rel_path = excluded.rel_path;
                        """,
                        (p["uuid"], ws_uuid, p["id"], p["path"]),
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
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute("DELETE FROM workspaces WHERE uuid = ?", (ws_uuid,))

                # If outer workspace existed, re-sync outer workspace projects from its config
                if outer_ws:
                    outer_path = pathlib.Path(outer_ws["canonical_path"])
                    outer_cfg_path = find_project_config_path(outer_path)
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
    """List all registered workspaces with stale flags."""
    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM workspaces ORDER BY slug ASC").fetchall()
        items: list[dict[str, Any]] = []

        for r in rows:
            d = dict(r)
            cpath = pathlib.Path(d["canonical_path"])
            stale = False

            if not cpath.exists() or not cpath.is_dir():
                stale = True
            else:
                try:
                    cur_st = os.stat(cpath)
                    if cur_st.st_dev != d["device"] or cur_st.st_ino != d["inode"]:
                        stale = True
                    cfg_path = find_project_config_path(cpath)
                    if not cfg_path.exists():
                        stale = True
                    else:
                        cfg = load_toml_file(cfg_path)
                        if cfg.get("workspace", {}).get("uuid") != d["uuid"]:
                            stale = True
                except Exception:
                    stale = True

            d["stale"] = stale
            items.append(d)
        return items
    finally:
        conn.close()


def show_workspace(
    ws_id: str,
    config_dir: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Show details of one workspace with projects and sub-workspaces."""
    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE uuid = ? OR slug = ?", (ws_id, ws_id)
        ).fetchone()
        if not row:
            raise KeyError(f"Workspace not found: {ws_id}")

        ws_data = dict(row)
        cpath = pathlib.Path(ws_data["canonical_path"])
        stale = False

        if not cpath.exists() or not cpath.is_dir():
            stale = True
        else:
            try:
                cur_st = os.stat(cpath)
                if cur_st.st_dev != ws_data["device"] or cur_st.st_ino != ws_data["inode"]:
                    stale = True
                cfg_path = find_project_config_path(cpath)
                if not cfg_path.exists():
                    stale = True
                else:
                    cfg = load_toml_file(cfg_path)
                    if cfg.get("workspace", {}).get("uuid") != ws_data["uuid"]:
                        stale = True
            except Exception:
                stale = True

        ws_data["stale"] = stale

        # Fetch projects from SQLite
        proj_rows = conn.execute(
            "SELECT uuid, slug, rel_path FROM projects WHERE workspace_uuid = ? ORDER BY slug ASC",
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
    ws = find_workspace_for_arg(workspace_arg, config_dir=config_dir)
    ws_path = pathlib.Path(ws["canonical_path"]).resolve()

    db_path = get_db_path(config_dir)
    conn = get_connection(db_path)
    try:
        # Load inner registered workspaces under ws_path
        other_workspaces = conn.execute(
            "SELECT * FROM workspaces WHERE uuid != ?", (ws["uuid"],)
        ).fetchall()
        inner_workspaces: list[dict[str, Any]] = []
        inner_ws_paths: list[pathlib.Path] = []
        for ow in other_workspaces:
            ow_path = pathlib.Path(ow["canonical_path"]).resolve()
            if ws_path in ow_path.parents:
                inner_workspaces.append(dict(ow))
                inner_ws_paths.append(ow_path)

        # Existing config projects
        cfg_path = find_project_config_path(ws_path)
        existing_cfg = load_toml_file(cfg_path) if cfg_path.exists() else {}
        existing_projects = existing_cfg.get("workspace", {}).get("projects", [])
        existing_by_path: dict[str, dict[str, Any]] = {
            os.path.normpath(p.get("path", "")): p for p in existing_projects if isinstance(p, dict)
        }

        # Discover folders containing tasks/00-INDEX.md
        candidate_folders: list[pathlib.Path] = []

        # Check workspace root
        if (ws_path / "tasks" / "00-INDEX.md").is_file():
            candidate_folders.append(ws_path)

        for root, dirs, _ in os.walk(str(ws_path)):
            # Prune hidden dirs and excluded dirs in-place
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in EXCLUDE_DIR_NAMES
            ]

            for d in list(dirs):
                folder_p = (pathlib.Path(root) / d).resolve()

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

                index_file = folder_p / "tasks" / "00-INDEX.md"
                if index_file.is_file():
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
                rel_path = str(folder.relative_to(ws_path))
                raw_slug = sanitize_slug(folder.name)
                p_id = raw_slug
                suffix = 2
                while p_id in used_slugs:
                    p_id = f"{raw_slug}-{suffix}"
                    suffix += 1

            norm_rel = os.path.normpath(rel_path)
            if norm_rel in existing_by_path:
                # Preserve existing uuid and id from config
                ex = existing_by_path[norm_rel]
                p_uuid = ex.get("uuid") or deterministic_uuid4(f"project:{ws['uuid']}:{norm_rel}")
                p_id = ex.get("id") or p_id
            else:
                p_uuid = deterministic_uuid4(f"project:{ws['uuid']}:{norm_rel}")

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
            "workspace": ws["slug"],
            "workspace_uuid": ws["uuid"],
            "canonical_path": str(ws_path),
            "config_path": str(cfg_path),
            "proposed_projects": proposed_projects,
            "sub_workspaces": sub_ws_items,
        }
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
    proposed = plan["proposed_projects"]

    # 1. Update config file
    write_workspace_to_config(cfg_path, ws_uuid, ws_slug, projects=proposed)

    # 2. Update SQLite projects table
    db_path = get_db_path(config_dir)
    with registry_lock(config_dir):
        conn = get_connection(db_path)
        try:
            with conn:
                # Clear existing projects for this workspace and insert new ones
                conn.execute("DELETE FROM projects WHERE workspace_uuid = ?", (ws_uuid,))
                for p in proposed:
                    conn.execute(
                        """
                        INSERT INTO projects (uuid, workspace_uuid, slug, rel_path)
                        VALUES (?, ?, ?, ?);
                        """,
                        (p["uuid"], ws_uuid, p["id"], p["path"]),
                    )
        finally:
            conn.close()

    return {
        "ok": True,
        "applied": True,
        "plan_hash": plan_hash,
        "projects": proposed,
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
        # Load inner registered workspaces
        other_workspaces = conn.execute(
            "SELECT * FROM workspaces WHERE uuid != ?", (ws["uuid"],)
        ).fetchall()
        inner_ws: list[dict[str, Any]] = []
        for ow in other_workspaces:
            ow_path = pathlib.Path(ow["canonical_path"]).resolve()
            if ws_path in ow_path.parents:
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
# CLI Commands
# ---------------------------------------------------------------------------


def cli_workspace_register(args: argparse.Namespace) -> int:
    try:
        plan = plan_workspace_register(
            path=args.path,
            slug=args.id,
            title=args.title,
            config_dir=args.config_dir,
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
            print(f"\nTo apply: ai-orch workspace register {plan['workspace']['canonical_path']} --apply --expect-hash {plan['plan_hash']}")
        return 0

    try:
        res = apply_workspace_register(plan, expect_hash=args.expect_hash, config_dir=args.config_dir)
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
        if args.json:
            print(json.dumps({"ok": True, "items": items}, indent=2))
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
    try:
        plan = plan_projects_discover(args.workspace, config_dir=args.config_dir)
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
            print(f"Workspace : {plan['workspace']} ({plan['workspace_uuid']})")
            print(f"Config    : {plan['config_path']}")
            print(f"\nProposed Projects ({len(plan['proposed_projects'])}):")
            for p in plan["proposed_projects"]:
                print(f"  - {p['id']:<18} path={p['path']:<20} uuid={p['uuid']}")
            if plan["sub_workspaces"]:
                print(f"\nDetected Sub-Workspaces ({len(plan['sub_workspaces'])}):")
                for sw in plan["sub_workspaces"]:
                    print(f"  - {sw['slug']:<18} path={sw['path']:<20} (sub_workspace, read-only)")
            print(f"\nPlan hash : {plan['plan_hash']}")
            target_ws = args.workspace or ""
            print(f"\nTo apply: ai-orch projects discover {target_ws} --apply --expect-hash {plan['plan_hash']}")
        return 0

    try:
        res = apply_projects_discover(plan, expect_hash=args.expect_hash, config_dir=args.config_dir)
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
    try:
        res = list_projects(args.workspace, config_dir=args.config_dir)
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


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv if argv is not None else sys.argv[1:])

    # Support shorthand invocation:
    # "ai-orch workspace <subcmd>" or "orchestration_registry.py workspace <subcmd>"
    # or "orchestration_registry.py register" -> "workspace register"
    if raw_args and raw_args[0] in ("workspace", "workspaces"):
        raw_args = raw_args[1:]
        is_workspace_group = True
        is_projects_group = False
    elif raw_args and raw_args[0] in ("projects", "project"):
        raw_args = raw_args[1:]
        is_workspace_group = False
        is_projects_group = True
    else:
        is_workspace_group = False
        is_projects_group = False

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    # workspace register
    p_reg = subparsers.add_parser("register", help="Register a workspace")
    p_reg.add_argument("path", nargs="?", default=".", help="Workspace path (default: .)")
    p_reg.add_argument("--id", dest="id", default=None, help="Workspace slug ID")
    p_reg.add_argument("--title", default=None, help="Workspace title")
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

    # projects discover
    p_disc = subparsers.add_parser("discover", help="Discover projects in a workspace")
    p_disc.add_argument("workspace", nargs="?", default=None, help="Workspace slug, UUID, or path")
    p_disc.add_argument("--apply", action="store_true", help="Apply discovery proposal")
    p_disc.add_argument("--expect-hash", dest="expect_hash", default=None, help="Expected plan hash")
    p_disc.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_disc.add_argument("--json", action="store_true", help="Output JSON")

    # projects list
    p_plist = subparsers.add_parser("projects-list", help="List projects in a workspace")
    p_plist.add_argument("workspace", nargs="?", default=None, help="Workspace slug, UUID, or path")
    p_plist.add_argument("--config-dir", dest="config_dir", default=None, help="Override global config dir")
    p_plist.add_argument("--json", action="store_true", help="Output JSON")

    # If dispatched as "projects list", map "list" to "projects-list"
    if is_projects_group and raw_args and raw_args[0] == "list":
        raw_args[0] = "projects-list"

    if not raw_args or raw_args[0] in ("-h", "--help"):
        parser.print_help()
        return 0

    args = parser.parse_args(raw_args)

    if args.command == "register":
        return cli_workspace_register(args)
    elif args.command == "unregister":
        return cli_workspace_unregister(args)
    elif args.command == "list":
        return cli_workspace_list(args)
    elif args.command == "show":
        return cli_workspace_show(args)
    elif args.command == "discover":
        return cli_projects_discover(args)
    elif args.command == "projects-list":
        return cli_projects_list(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
