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
import pytest

REAL_HOME = pathlib.Path(os.environ.get("HOME", str(pathlib.Path.home()))).resolve()
REAL_CONFIG_DIR = REAL_HOME / ".config" / "ai-orchestration"
REAL_WORKS_DIR = REAL_HOME / "works"
REPO_ROOT = pathlib.Path(__file__).resolve().parent
# Exclude the ai-coding-tools repository family where this worktree and parallel executors live
REPO_FAMILY = REAL_WORKS_DIR / "ai-coding-tools"


def _snapshot_host_dir(root: pathlib.Path, exclude: pathlib.Path | None = None) -> dict[str, tuple[int, int]]:
    snap: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return snap
    ex_str = str(exclude.resolve()) if exclude else None

    def _walk(top: str) -> None:
        try:
            with os.scandir(top) as it:
                for entry in it:
                    p = entry.path
                    if ex_str and (p == ex_str or p.startswith(ex_str + os.sep)):
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                        snap[p] = (st.st_mtime_ns, st.st_size)
                    except OSError:
                        pass
                    if entry.is_dir(follow_symlinks=False):
                        _walk(p)
        except OSError:
            pass

    _walk(str(root.resolve()))
    return snap


@pytest.fixture(scope="session", autouse=True)
def _session_guard_unpolluted_host():
    """Session guard proving nothing under the real ~/.config/ai-orchestration or ~/works is created/modified."""
    before_cfg = _snapshot_host_dir(REAL_CONFIG_DIR)
    before_works = _snapshot_host_dir(REAL_WORKS_DIR, exclude=REPO_FAMILY)
    yield
    after_cfg = _snapshot_host_dir(REAL_CONFIG_DIR)
    after_works = _snapshot_host_dir(REAL_WORKS_DIR, exclude=REPO_FAMILY)

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

    # Check ~/works (excluding current repo / worktree)
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

