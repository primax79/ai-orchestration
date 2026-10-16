# 06 - Control-plane safety (Doctor, index, UI backend, VS Code bridge)

> **Derived from:** [`../specs/control-plane-safety.md`](../specs/control-plane-safety.md). Read the spec first; this plan does not repeat it. Finding ids (E*, I*, U*, V*) refer to its §1.

E1 and E2 (path traversal in `remove-skill`, wholesale overwrite of unparseable MCP configs) were fixed inline in `ai-orchestration@2ca3377`, with regression tests.

## Waves

| Wave | Tasks (parallel, disjoint files) |
| --- | --- |
| 1 | 06.1 (`tasks_engine.py`), 06.2 (`orchestration_env.py`), 06.5 (UI backend) |
| 2 | 06.3 (`orchestration_env.py`, after 06.2), 06.6 (`orchestration_config.py`) |
| 3 | 06.4 (`orchestration_env.py`, after 06.3), 06.7 (UI backend, after 06.1, 06.2, 06.5, 06.6) |
| 4 | 06.8 (frontend, after 06.7) |
| 5 | 06.9 (VS Code, after 06.8) |

## Tasks (One Task = One Commit)

### 06.1 - Lossless `sync-index` with generated-region markers (I1–I4)

- **Status:** `open` · **Profile:** `deep-reasoning` · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../scripts/test_tasks_engine.py`, `.../scripts/fixtures/index-regression/` (new), `tasks/00-INDEX.md` (adopt markers)
- **Goal:** Implement spec §2.2 completely:
  - markers, plus `--adopt`;
  - row-level merge preserving Done `Closed`/`Result`;
  - `(missing)` rows;
  - generic empty Decisions row;
  - atomic write, `--check` diff, `--expect-hash`.

  Then run `--adopt` on this repo's own `tasks/00-INDEX.md` and commit the result.
- **Verification:**
  - Fixture tests on a curated copy of the workspace index (with a provenance note in the fixture README):
    - `--adopt` then `--apply` loses no row, no Done cell and no prose line;
    - a second `--apply` is a no-op;
    - `--expect-hash` mismatch → refused, file unchanged;
    - an index without markers + `--apply` → refused.
  - The engine's full test suite passes.
  - `./bin/ai-orch tasks sync-index --tasks-dir ./tasks --check` exits 0 after adoption.

### 06.2 - Doctor: `--dry-run` plans with hash, no-clobber install, trash instead of delete, explicit obsolete cleanup (E4, E6, E7)

- **Status:** `open` · **Profile:** `deep-reasoning` · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_env.py`, `scripts/test_orchestration_env.py`
- **Goal:** Implement spec §2.1:
  - the "Every mutating `env` command" and "No clobbering" bullets: `--dry-run` with `plan` + `plan_hash`, `--expect-plan-hash`, `--overwrite`, `.ai-orch-trash/`;
  - the source catalog keyed by `(repo, plugin, name)` with the `foreign` state;
  - the resolve policy from `[env.conflicts]`.

  Not plugin awareness (06.3), not MCP registration (06.4).
- **Verification:**
  - Tests in a fake home:
    - install over an `unmanaged`, a locally modified and a `foreign` skill → refused without `--overwrite`;
    - with `--overwrite`, the old copy ends up in `.ai-orch-trash/`;
    - `--dry-run` changes nothing on disk (compare a tree hash before and after);
    - a stale `--expect-plan-hash` → refused;
    - obsolete dirs appear in the plan and are removed only on apply.
  - Live: `env install-skills --dry-run --assistants all --scope global` on the real home returns a plan and changes nothing (`find ~/.claude/skills ~/.kilo/skills ~/.codex/skills -newer <marker>` is empty).

### 06.3 - Doctor: plugin-aware inventory and conflicts (E5)

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 06.2 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_env.py`, `scripts/test_orchestration_env.py`
- **Goal:** Implement spec §2.1 "Plugin-aware inventory":
  - Claude plugin skills from `~/.claude/plugins/installed_plugins.json`;
  - Kilo marketplace skills, if they live on disk (verify the real layout under `~/.kilo` / `../references/` first; if they don't, report that in the Final Report and skip);
  - an `origin` field on every skill;
  - conflicts computed over the union of origins;
  - `resolve-conflicts` touching only `standalone` copies and reporting which plugin to disable for plugin copies.
- **Verification:**
  - Tests with a fake `installed_plugins.json`.
  - Live: `env status --json` on this machine lists the `architect-side@ai-orchestration` and `architect-side@kilo-mcp` plugin copies of `orchestration-workflow` / `kilo-mcp-orchestrator` and reports the conflict; `resolve-conflicts --dry-run` proposes no plugin edits.

### 06.4 - Doctor: MCP registration and status through the real config files (E3)

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 06.3 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_env.py`, `scripts/test_orchestration_env.py`
- **Goal:** Implement spec §2.1 "MCP registration through the real configs":
  - Claude via `claude mcp add`;
  - Codex via `codex mcp add` or a surgical `config.toml` edit;
  - Kilo `kilo.jsonc` edit, or the snippet to paste;
  - status reading the real files;
  - `stray` reporting.

  Verify each CLI's `mcp add` syntax with `--help` before using it.
- **Verification:**
  - Tests with a fake home and stub `claude`/`codex` executables on `PATH` that record their argv.
  - Live, read-only: `env status --json` reports `~/.codex/config.json` as `stray` and lists the MCP servers actually in `~/.codex/config.toml` (`kilo-mcp`, `playwright`, `vscode-dap`).
  - Live, write: `register-mcp --dry-run` only. No real registration.

### 06.5 - UI backend: auth, non-blocking CLI calls, fixed workspace, watcher (U1, U4, U5, U6)

- **Status:** `open` · **Profile:** `bulk-execution` · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`, `start.sh`, `README.md`, `frontend/src/api.ts`, `frontend/index.html`
- **Goal:** Implement spec §2.3:
  - "Auth" (persisted token, meta injection with `no-store`, header and WS query checks, Host allowlist, CORS removed);
  - "Non-blocking CLI calls";
  - "Fixed workspace per process" (with `/api/workspace/switch` removed);
  - "Watcher";
  - the README.

  `api.ts` reads the meta token, sends it, and reloads once on 401; its VS Code path is unchanged.
- **Verification:**
  - Tests:
    - `/api/*` without the token or with a wrong one → 401; a bad `Host` → 400; WS without the token refused;
    - a slow stub CLI does not block a concurrent `/api/workspace` request;
    - touching a file under `tasks/` broadcasts `changed` within 2 s;
    - `AI_ORCH_WORKSPACE` is honoured, including a relative path given to `start.sh`.
  - Live: `npm run build` first. Then start on a scratch copy of the workspace and open the UI with the Playwright MCP: data loads. A `fetch` to the API from another origin (`about:blank` page) is refused.

### 06.6 - Core: `render-agents-md --diff` with hash precondition

- **Status:** `open` · **Profile:** `bulk-execution` · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py`, `.../scripts/test_orchestration_config.py`
- **Goal:** `render-agents-md --diff` returns `{diff, hash}` (hash of the current `AGENTS.md`, or of empty when the file is missing). `--apply --expect-hash H` refuses on mismatch. The write is atomic.
- **Verification:** Tests: a diff for a missing block, a present block and an up-to-date block; a hash mismatch is refused and the file is unchanged.

### 06.7 - UI backend: preview/apply endpoints; transitions no longer write the index (U2, U3)

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 06.1, 06.2, 06.5, 06.6 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Implement spec §2.3:
  - "Transitions no longer write the index";
  - "Preview/apply endpoints" for sync-index, every mutating `env` command, and `render-agents-md`.
- **Verification:**
  - Tests: a transition leaves `00-INDEX.md` byte-identical; each preview → apply round-trip works; a stale hash → 409.
  - Live with `curl` against a running server on a scratch workspace.

### 06.8 - Frontend: confirmation modal with previews, safer installer defaults, Doctor origins, error banners, WS reconnect (U3, U7, V3)

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 06.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `frontend/dist/**`
- **Goal:** Implement spec §2.4; rebuild `dist/`.
- **Verification:**
  - `npm run build` is clean.
  - Live with the Playwright MCP on a scratch workspace and a fake home (`HOME` override for the backend):
    - every mutating action shows a preview and does nothing on Cancel;
    - an apply after an external change shows the stale-plan error;
    - stopping the server turns the indicator off; restarting it reconnects without a reload;
    - no `alert`/`confirm` call remains (`grep`).

### 06.9 - VS Code bridge: complete handler map, non-zero rejection, `dist-webview` sync, no hard-coded paths, multi-root choice (V1, V2)

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 06.8 · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/cli-client.ts`, `src/views/dashboard-panel.ts`, `src/extension.ts`, `package.json`, `esbuild.config.mjs`, `dist-webview/**`
- **Goal:** Implement spec §2.5.
- **Verification:**
  - `npm run compile` is clean (it now includes `sync-webview`).
  - A unit test checks that every `api.ts` method has a handler.
  - Live in an Extension Development Host:
    - open the dashboard, trigger one preview and one refused action, and see the error;
    - record whether native `confirm()` is blocked (V3) in the spec.
