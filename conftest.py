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

import pytest

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
    saved = {k: os.environ.get(k) for k in ("AI_ORCHESTRATION_CONFIG", "AI_ORCH_BROKER_CHILD")}
    cfg_dir = tmp_path_factory.mktemp("global-config")
    (cfg_dir / "orchestration.toml").write_text(_TEST_GLOBAL_CONFIG, encoding="utf-8")
    os.environ["AI_ORCHESTRATION_CONFIG"] = str(cfg_dir)
    os.environ.pop("AI_ORCH_BROKER_CHILD", None)
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
