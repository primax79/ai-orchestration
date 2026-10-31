"""Test-session isolation from the user's real global config.

The engine reads the global config dir (`$AI_ORCHESTRATION_CONFIG`, else
`~/.config/ai-orchestration`) for `broker.lock`, the registry and the model
mapping. Without isolation, a real broker started on demand by another session
makes mutating commands fail with `broker-owns-writes`, and run tests silently
depend on the operator's model mapping. Every test session gets a temporary
global config seeded with the fixed mapping below; tests that need another
config dir still override it with monkeypatch.
"""

import os
import pathlib
import stat
import subprocess
import pytest

REAL_HOME = pathlib.Path(os.environ.get("HOME", str(pathlib.Path.home()))).resolve()
REAL_CONFIG_DIR = REAL_HOME / ".config" / "ai-orchestration"
REAL_WORKS_DIR = REAL_HOME / "works"
REPO_ROOT = pathlib.Path(__file__).resolve().parent

# Under ~/works, guard ONLY the orchestration config files and .ai-orchestration/ directory
_WORKS_GUARDED_FILENAMES = frozenset(
    {
        ".ai-orchestration.local.toml",
        "orchestration.toml",
        ".ai-orchestration.toml",
    }
)
_WORKS_SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "target",
        "build",
        "dist",
        "repos",
        "repos_jdk8",
        "repos_jdk17",
    }
)


def _resolve_excluded_repo_and_worktrees(rootdir: pathlib.Path) -> set[str]:
    """Resolve the repository under test (from rootdir) and all its git worktrees.

    Never excludes the parent workspace (e.g. ~/works/ai-coding-tools); only the
    specific repository checkout and its linked worktrees are excluded.
    """
    resolved_root = rootdir.resolve()
    excluded: set[str] = {str(resolved_root)}
    try:
        res = subprocess.run(
            ["git", "-C", str(resolved_root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.startswith("worktree "):
                    wt_raw = line[len("worktree ") :].strip()
                    if wt_raw:
                        wt_path = pathlib.Path(wt_raw).resolve()
                        excluded.add(str(wt_path))
                        # Also exclude the per-repo worktree container .worktrees/<repo-name>
                        if wt_path.parent.parent.name == ".worktrees":
                            excluded.add(str(wt_path.parent))
    except OSError:
        pass
    return excluded


def _is_path_excluded(path_str: str, excluded_prefixes: set[str]) -> bool:
    for ex in excluded_prefixes:
        if path_str == ex or path_str.startswith(ex + os.sep):
            return True
    return False


def _is_runtime_state_entry(path_str: str, is_dir: bool = False, mode: int | None = None) -> bool:
    """Return True if an entry under ~/.config/ai-orchestration is live runtime state
    (SQLite DB/WAL/SHM/journal, lock files, or broker sockets/PIDs) rather than configuration."""
    if mode is not None and (stat.S_ISSOCK(mode) or stat.S_ISFIFO(mode)):
        return True
    name = os.path.basename(path_str)
    if is_dir:
        return name == "broker"
    if (
        name.endswith((".sqlite", ".sqlite3", "-wal", "-shm", "-journal", ".lock", ".pid", ".sock", ".socket"))
        or ".sqlite-" in name
        or ".sqlite3-" in name
    ):
        return True
    parts = pathlib.Path(path_str).parts
    if "broker" in parts and not name.endswith((".toml", ".json")):
        return True
    if name == "broker.json" or name.startswith("broker.json.tmp."):
        return True
    return False


def _snapshot_host_dir(
    root: pathlib.Path, exclude: pathlib.Path | set[str] | None = None
) -> dict[str, tuple[int, int]]:
    """Recursively snapshot configuration entries under `root` (used for ~/.config/ai-orchestration),
    ignoring live broker/SQLite runtime state."""
    snap: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return snap
    if isinstance(exclude, pathlib.Path):
        excluded_prefixes = {str(exclude.resolve())}
    elif exclude is not None:
        excluded_prefixes = {str(pathlib.Path(p).resolve()) for p in exclude}
    else:
        excluded_prefixes = set()

    def _walk(top: str) -> None:
        if _is_path_excluded(top, excluded_prefixes):
            return
        try:
            with os.scandir(top) as it:
                for entry in it:
                    p = entry.path
                    if _is_path_excluded(p, excluded_prefixes):
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        st = entry.stat(follow_symlinks=False)
                        if not _is_runtime_state_entry(p, is_dir=is_dir, mode=st.st_mode):
                            snap[p] = (0, 0) if is_dir else (st.st_mtime_ns, st.st_size)
                    except OSError:
                        is_dir = False
                    if is_dir:
                        _walk(p)
        except OSError:
            pass

    _walk(str(root.resolve()))
    return snap


def _snapshot_works_orchestration_configs(
    works_root: pathlib.Path, excluded_prefixes: set[str] | None = None
) -> dict[str, tuple[int, int]]:
    """Snapshot ONLY orchestration config files and `.ai-orchestration/` directories under `works_root`.

    Guarded targets per project under `~/works`:
    - `.ai-orchestration.local.toml`
    - `orchestration.toml`
    - `tasks/orchestration.toml`
    - `.ai-orchestration.toml`
    - `.ai-orchestration/` (directory and all its contents)
    """
    snap: dict[str, tuple[int, int]] = {}
    if not works_root.exists():
        return snap
    ex_set = {str(pathlib.Path(p).resolve()) for p in (excluded_prefixes or set())}

    def _stat_into(path_str: str) -> None:
        try:
            st = os.lstat(path_str)
            snap[path_str] = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass

    def _is_ancestor_of_excluded(dir_path: str) -> bool:
        norm = dir_path.rstrip(os.sep) + os.sep
        return any(ex.startswith(norm) for ex in ex_set)

    def _walk_full_dir(top: str, skip_runtime_subdirs: bool = False) -> None:
        if not skip_runtime_subdirs:
            _stat_into(top)
        try:
            with os.scandir(top) as it:
                for entry in it:
                    if skip_runtime_subdirs and entry.name in ("events", "runs", "sessions"):
                        continue
                    p = entry.path
                    _stat_into(p)
                    if entry.is_dir(follow_symlinks=False):
                        _walk_full_dir(p, skip_runtime_subdirs=False)
        except OSError:
            pass

    def _walk_projects(top: str, depth: int = 0, max_depth: int = 4) -> None:
        if _is_path_excluded(top, ex_set):
            return
        try:
            with os.scandir(top) as it:
                for entry in it:
                    p = entry.path
                    if _is_path_excluded(p, ex_set):
                        continue
                    name = entry.name
                    if name in _WORKS_GUARDED_FILENAMES:
                        _stat_into(p)
                    elif name == ".ai-orchestration":
                        if entry.is_dir(follow_symlinks=False):
                            _walk_full_dir(p, skip_runtime_subdirs=_is_ancestor_of_excluded(top))
                        else:
                            _stat_into(p)
                    elif name == "tasks" and entry.is_dir(follow_symlinks=False):
                        tasks_cfg = os.path.join(p, "orchestration.toml")
                        if os.path.lexists(tasks_cfg) and not _is_path_excluded(tasks_cfg, ex_set):
                            _stat_into(tasks_cfg)
                        if depth < max_depth:
                            _walk_projects(p, depth + 1, max_depth)
                    elif (
                        depth < max_depth
                        and entry.is_dir(follow_symlinks=False)
                        and name not in _WORKS_SKIP_DIRS
                        and not (name.startswith(".") and name != ".worktrees")
                    ):
                        _walk_projects(p, depth + 1, max_depth)
        except OSError:
            pass

    _walk_projects(str(works_root.resolve()))
    return snap


@pytest.fixture(scope="session", autouse=True)
def _session_guard_unpolluted_host(request: pytest.FixtureRequest):
    """Session guard proving nothing under the real ~/.config/ai-orchestration or
    orchestration config files in ~/works is created/modified."""
    rootdir = pathlib.Path(str(request.config.rootpath)).resolve()
    excluded_repo = _resolve_excluded_repo_and_worktrees(rootdir)

    before_cfg = _snapshot_host_dir(REAL_CONFIG_DIR)
    before_works = _snapshot_works_orchestration_configs(REAL_WORKS_DIR, excluded_prefixes=excluded_repo)
    yield
    after_cfg = _snapshot_host_dir(REAL_CONFIG_DIR)
    after_works = _snapshot_works_orchestration_configs(REAL_WORKS_DIR, excluded_prefixes=excluded_repo)

    violations: list[str] = []
    # Check ~/.config/ai-orchestration
    for p, meta in after_cfg.items():
        if p not in before_cfg:
            violations.append(f"CREATED in ~/.config/ai-orchestration: {p}")
        elif meta != before_cfg[p]:
            violations.append(f"MODIFIED in ~/.config/ai-orchestration: {p}")
    for p in before_cfg:
        if p not in after_cfg:
            violations.append(f"DELETED in ~/.config/ai-orchestration: {p}")

    # Check ~/works orchestration config files (excluding repository under test and its worktrees)
    for p, meta in after_works.items():
        if p not in before_works:
            violations.append(f"CREATED in ~/works: {p}")
        elif meta != before_works[p]:
            violations.append(f"MODIFIED in ~/works: {p}")
    for p in before_works:
        if p not in after_works:
            violations.append(f"DELETED in ~/works: {p}")

    assert not violations, (
        "Session guard failure: real host directory was created/modified during test run:\n"
        + "\n".join(violations)
    )


@pytest.fixture(autouse=True)
def _isolate_test_environment(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Autouse fixture isolating HOME, AI_ORCHESTRATION_CONFIG, AI_ORCH_CONFIG_DIR,
    XDG_CONFIG_HOME, and the kilo-mcp data dir under tmp_path for every test.
    """
    home_dir = tmp_path / "_isolated_home"
    home_dir.mkdir(parents=True, exist_ok=True)

    config_dir = home_dir / ".config" / "ai-orchestration"
    config_dir.mkdir(parents=True, exist_ok=True)
    global_cfg = config_dir / "orchestration.toml"
    global_cfg.write_text(_TEST_GLOBAL_CONFIG, encoding="utf-8")

    kilo_mcp_dir = home_dir / ".local" / "share" / "kilo-mcp"
    kilo_mcp_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("AI_ORCHESTRATION_CONFIG", str(config_dir))
    monkeypatch.setenv("AI_ORCH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home_dir / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home_dir / ".local" / "share"))
    monkeypatch.setenv("KILO_MCP_DATA_DIR", str(kilo_mcp_dir))
    monkeypatch.setenv(
        "AI_ORCH_TEST_CLI_VERSIONS",
        "kilo=0.0.0-test-fake,claude=0.0.0-test-fake,codex=0.0.0-test-fake",
    )
    monkeypatch.delenv("AI_ORCH_BROKER_CHILD", raising=False)

_TEST_GLOBAL_CONFIG = """\
schema_version = 1

[routing]
default_orchestrator = "claude"
default_executor = "kilo"
default_profile = "bulk-execution"

[verification]
default_mode = "independent-session"
cross_agent_order = ["claude:deep-reasoning", "kilo:deep-reasoning", "codex:deep-reasoning"]
panel_reviewers = ["kilo:deep-reasoning", "claude:deep-reasoning", "codex:deep-reasoning"]
panel_require_blind = true

[tools.kilo]
enabled = true
cli_command = "kilo"

[tools.kilo.profiles.deep-reasoning]
model = "google/gemini-4-argon"
variant = "high"

[tools.kilo.profiles.orchestration]
model = "google/gemini-4-argon"
variant = "medium"

[tools.kilo.profiles.bulk-execution]
model = "google/gemini-3.8-flash"
variant = "medium"

[tools.kilo.profiles.exploration]
model = "google/gemini-3.8-flash"
variant = "low"

[tools.claude]
enabled = true
cli_command = "claude"

[tools.claude.profiles.deep-reasoning]
model = "opus"
effort = "high"

[tools.claude.profiles.orchestration]
model = "sonnet"
effort = "medium"

[tools.claude.profiles.bulk-execution]
model = "sonnet"
effort = "medium"

[tools.claude.profiles.exploration]
model = "haiku"
effort = "low"

[tools.codex]
enabled = true
cli_command = "codex"

[tools.codex.profiles.deep-reasoning]
model = "gpt-5-codex"
effort = "high"

[tools.codex.profiles.orchestration]
model = "gpt-5-codex"
effort = "medium"

[tools.codex.profiles.bulk-execution]
model = "gpt-5-codex-mini"
effort = "medium"

[tools.codex.profiles.exploration]
model = "gpt-5-codex-mini"
effort = "low"
"""


@pytest.fixture(scope="session", autouse=True)
def _isolated_global_config(tmp_path_factory: pytest.TempPathFactory):
    saved = {
        k: os.environ.get(k)
        for k in ("AI_ORCHESTRATION_CONFIG", "AI_ORCH_BROKER_CHILD", "AI_ORCH_TEST_CLI_VERSIONS")
    }
    cfg_dir = tmp_path_factory.mktemp("global-config")
    (cfg_dir / "orchestration.toml").write_text(_TEST_GLOBAL_CONFIG, encoding="utf-8")
    os.environ["AI_ORCHESTRATION_CONFIG"] = str(cfg_dir)
    os.environ.pop("AI_ORCH_BROKER_CHILD", None)
    # Stub CLI version probes across all tests (in-process and subprocesses) so tests
    # never spawn real kilo/claude/codex binaries for version checks.
    os.environ["AI_ORCH_TEST_CLI_VERSIONS"] = "kilo=0.0.0-test-fake,claude=0.0.0-test-fake,codex=0.0.0-test-fake"
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

