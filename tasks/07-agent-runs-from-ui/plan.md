# 07 - Agent runs from the control plane (choose who does the work)

> **Derived from:** [`../specs/agent-runs-from-ui.md`](../specs/agent-runs-from-ui.md) (v2). Read the spec first; this plan does not repeat it.
>
> **Requires:** initiative 06 for every UI task (07.7+). The core tasks (07.1–07.6) can start as soon as their file dependencies allow.

## Waves

| Wave | Tasks |
| --- | --- |
| A (can run alongside 06 wave 1) | 07.1 (`orchestration_config.py`; conflicts with 06.6, so it runs before or after it, never at the same time) |
| B | 07.2 (new `orchestration_runs.py`) |
| C | 07.3, then 07.4 (same file, sequential) |
| D | 07.5 (self, live) |
| E (after 06 is done) | 07.6 → 07.7 → 07.8 → 07.9 |

## Tasks (One Task = One Commit)

### 07.1 - `config set-routing`, surgical TOML updater, `[tools.<t>.headless]` schema, correct project-config path text

- **Status:** `open` · **Profile:** `deep-reasoning` · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py`, `.../scripts/test_orchestration_config.py`, `bin/ai-orch` (catalog text), `docs/05-orchestration-config-schema.md`
- **Goal:** Implement spec §9:
  - a surgical updater used by both `set-routing` and `set-profile`;
  - the headless schema, with placeholders `{cwd}`, `{model}`, `{variant}`, `{session_id}`, `{permission_mode}`, `{sandbox}`, `{prompt_file}`;
  - the real config path named in the `AGENTS.md` block, the `init-project` help and the catalog.
- **Verification:** Tests:
  - `set-routing` and `set-profile` on a temp config with comments, blank lines and unrelated tables: everything except the target values is byte-identical;
  - an invalid placeholder is rejected;
  - the rendered block names `find_project_config_path(...)`.

### 07.2 - Run engine A: registry, locking, records, request validation, prompts, `options`/`preview`/`list`/`show`

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 07.1 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py` (new), `scripts/test_orchestration_runs.py` (new), `bin/ai-orch`
- **Goal:** Spec §3 (resolution, modes, prompts, `T###`-only scope), §4 (`options`, `preview`, `list`, `show`), §5.1, §5.2 (lock, guards, monotonic records). No process spawning yet.
- **Verification:** Tests:
  - the resolution chain in all four layers;
  - every guard refuses with its reason (`NN.T`, wrong state, tool disabled or missing, same-task active, same-cwd active);
  - `preview` is side-effect free (tree hash of the workspace unchanged);
  - `.git/info/exclude` gets `.ai-orchestration/`, and launch is refused when it cannot be ignored;
  - `run_id` validation rejects traversal.

### 07.3 - Run engine B: supervisor, adapters (prompt via stdin/file), cancel and lost reconciliation with process-group kill

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 07.2 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`, `scripts/fixtures/runs/stub_agent.py` (new)
- **Goal:** Spec §4 (`start`, `logs`, `cancel`), §5.3, §5.7 (adapters, with the stub agent configured through `[tools.<t>.headless]`), and the task transition to `in progress` on a successful execute spawn (§3 "Task state ownership").
- **Verification:** Tests against the stub agent (which can sleep, spawn a grandchild, write events, and exit 0 or 1):
  - succeeded and failed outcomes are recorded;
  - cancel leaves no process of the group alive (check the grandchild too);
  - SIGKILL on the supervisor → next `list` marks `lost` **and** the agent group is gone;
  - a reused PID with a different start time is not killed (simulated);
  - the prompt never appears in `ps` argv;
  - concurrent `start` calls for the same task → exactly one wins.

### 07.4 - Run engine C: worktree isolation, verify target, verdict parsing and `apply-verdict`, continue invariants, `cleanup`

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 07.3 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`
- **Goal:** Spec §5.4, §5.5, §5.6, and `run cleanup`.
- **Verification:** Tests in temp git repos:
  - a dirty repo is refused (`--allow-dirty-base` warns);
  - multi-repo `paths` are refused;
  - the worktree and branch are created and `base_commit`/`final_commit` recorded;
  - verify runs in a detached throwaway worktree of `final_commit`;
  - the independence guard holds;
  - a verdict is parsed only from the final message;
  - `apply-verdict` is refused after the task file changed;
  - continue locks fields and refuses verify→execute and a missing worktree;
  - `cleanup` refuses an unmerged branch without `--discard`.

### 07.5 - Live capture with the real CLIs: session ids, Final Report, verdict, continue; flag table correction

- **Status:** `open` · **Profile:** `deep-reasoning` · **Executor:** `self` (orchestrator: needs the real CLIs and auth) · **Depends on:** 07.4 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/fixtures/runs/{claude,kilo,codex}-*.jsonl` (new), `scripts/test_orchestration_runs.py`, `tasks/specs/agent-runs-from-ui.md` (§5.7 table)
- **Goal:** In a scratch git repo with a one-step task, do per tool:
  - one `execute`, one `--continue` and one `verify`;
  - save the scrubbed streams as fixtures;
  - finalize the per-tool session-id / Final Report / verdict parsers;
  - correct §5.7 where the real flags differ.
- **Verification:** The fixture tests pass, and a live re-run per tool shows the session captured and the continuation landing in the same session.

### 07.6 - UI backend: run and config endpoints

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 07.4, 06.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Spec §6.
- **Verification:**
  - Tests through HTTP with the stub agent configured in a temp workspace config: options → preview → start → logs (incremental) → cancel → continue → apply-verdict.
  - Live with `curl` on a running server.

### 07.7 - Frontend: Run dialog with live preview, task runs panel, Runs tab

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 07.6, 06.8 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `frontend/dist/**`
- **Goal:** Spec §7, except the Config tab.
- **Verification:**
  - `npm run build` is clean.
  - Live with the Playwright MCP on a scratch workspace with the stub agent:
    - launch a run and see the log;
    - cancel it;
    - continue it;
    - apply a verdict;
    - see the refusal for the same tool in verify.

### 07.8 - Frontend: Config tab editing (routing and profile/model matrix)

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 07.6, 06.8 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/components/OrchestrationConfigurator.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/dist/**`
- **Goal:** Spec §7 "Config tab".
- **Verification:** Live: edit routing and one profile in project scope; the `.ai-orchestration.local.toml` diff shows only those values.

### 07.9 - VS Code: run handlers and run watcher

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 07.7, 07.8, 06.9 · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/extension.ts`, `dist-webview/**`
- **Goal:** Spec §8.
- **Verification:**
  - `npm run compile` is clean, and the handler-map test is green.
  - Live in an Extension Development Host: launch and cancel a stub run from the webview.

## Amendments after review 2 (2026-10-16)

The spec now opens with §0 "Amendments after review 2" (R1–R14). These changes to the tasks follow from it, and the lane order is in `../06-control-plane-safety/plan.md`:

- **07.1** also covers:
  - the `{effort}` placeholder (R3);
  - `--diff`/`--expect-hash` on `set-routing` and `set-profile` (spec 06 A10).

  It was dispatched before the review; the delta follows in the same Kilo session.
- **07.2** also covers:
  - R1: a binding `plan_hash` in `preview`;
  - R4: the allowed modes per state;
  - R8: the task bundle hash, reusing 06.10's hash function, **so 07.2 depends on 06.10**;
  - R10: the platform refusal;
  - R13: secret references and redaction.
- **07.3** also covers:
  - R2: separate process identities;
  - R9: log chunks with logical offsets;
  - R11: Claude refuses to launch without a configured `allowed_tools`.
- **07.4** also covers:
  - R5: the verification modes, including the panel;
  - R6: `run mark-delivered`;
  - R7: the artifact invariants, adding to the tests a branch that advances, a reset, and `target_run: none` with HEAD drift;
  - R12: cleanup over continuation chains.
- **07.5** must prove a real test-and-commit run under the permission policy the owner chooses (R11).
- **07.8** depends on **07.7** (shared `api.ts`, `types.ts`, `dist`).
- **07.9** focus files add `src/cli-client.ts` and its tests.

### 07.10 - Core: run supervisor files blocking questions (R14, spec 08 Q8)

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 07.4, 08.1 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`
- **Goal:**
  - At the end of a run, parse ` ```ai-orch-question ` blocks from the **final** assistant message.
  - File each one in the **main** workspace through the `questions ask` engine API. The supervisor sets `asked-by` and `origin-run` itself and forces `blocks` to the run's task.
  - Record the ids in `run.json` `questions`.
  - A malformed block → recorded as `question_errors`, never silently dropped.
- **Verification:** Tests with the stub agent emitting a valid block, a malformed block, and a block that names another task in `blocks` (forced to the run's task).

## Decisions waiting

| Key | Question | Blocks | Decider |
| --- | --- | --- | --- |
| R11 | Which Bash/MCP allow-list should headless Claude runs get by default, per mode (execute, orchestrate, verify)? To be converted into the first `Q###` question once 08.1 lands. | 07.3 default, 07.5 | owner |
