# Spec: Control-plane safety (Doctor, index, UI backend)

- **Status:** ready (2026-10-16). Reviewed by Codex in the first draft of [`agent-runs-from-ui`](agent-runs-from-ui.md), where these items were first collected.
- **Drives:** initiative [06](../06-control-plane-safety/plan.md). It is a prerequisite of 07 (agent runs) and 08 (blocking questions).
- **Repos:** `ai-orchestration` (core), `ai-orchestration-ui`, `vscode-ai-orchestration`

## 0. Amendments after review 2 (normative; each overrides the section it names)

Codex reviewed the second round of specs on 2026-10-16 (4 blockers, 35 major, 3 minor across specs 06, 07, 08). The items for this spec:

- **A1 — §1 E3 corrected.** Kilo **merges** `config.json`, `kilo.json`, `kilo.jsonc`, `opencode.json` and `opencode.jsonc` (`references/kilocode/kilocode/packages/opencode/src/config/config.ts:366-372`).
  - `~/.config/kilo/kilo.json` is therefore a real config file, not a stray one, and the Kilo registration done by older versions works.
  - Only `~/.codex/config.json` is stray, because Codex reads only `config.toml`.
  - `env status` reports, for Kilo, the merged view with per-entry provenance (which file defines each server, and which entries override others).
- **A2 — §2.1 plan hash covers content.** Each plan entry carries `before_sha256` (the current target: a file hash or a canonical tree hash, or `null`) and `after_sha256` (the source content that will be written, or `null` for delete/trash). `plan_hash` is computed over these. The apply recomputes the plan **under an exclusive lock** (`fcntl.flock` on `<home>/.config/ai-orchestration/env.lock`) and refuses on any difference.
- **A3 — §2.1 coverage.**
  - Agent files installed by `install-skills` get the same inventory, preview, no-clobber and trash rules as skill directories.
  - `fetch-repos` and `register-mcp --provision-venv` are mutating, so they are part of the plan: clone/pull targets with the current `HEAD`, the venv path and the pip command. Both commands support `--dry-run` / `--expect-plan-hash`.
- **A4 — §2.1 provenance receipts.** Every install writes `<target>/.ai-orch-source.json` with `{repo, plugin, name, source_hash, installed_at, mode}`; in link mode, provenance comes from the symlink target. Classification:
  - a matching receipt with a matching hash → `up-to-date`;
  - a matching receipt with a different hash → `modified-or-outdated`;
  - no receipt and no hash match → `foreign`.
- **A5 — §2.1 plugin inventory (overrides "Plugin-aware inventory").**
  - Enablement comes from the effective Claude settings: `~/.claude/settings.json` `enabledPlugins`, then the project's `.claude/settings.json` and `.claude/settings.local.json` for project scope.
  - Install paths and scope come from `installed_plugins.json`. Local/project installs are filtered by the workspace.
  - Skills are reported as a **list** of `{name, origin, scope, path, enabled}` entries, not as a name-keyed map, so that a standalone copy and several plugin copies of the same name can coexist.
- **A6 — §2.1 MCP registration scopes (overrides "MCP registration through the real configs").**
  - Codex: `codex mcp add` has no scope option. It is used for **global** scope only; project scope for Codex is refused with an explanation.
  - Claude: `claude mcp add --scope user|project`. The file fallback maps user → `~/.claude.json` and project → `<workspace>/.mcp.json`.
  - Kilo: global → an atomic edit of `~/.config/kilo/kilo.json` (strict JSON, already merged by Kilo); `kilo.jsonc` is never edited.
- **A7 — §2.2 adoption.** `sync-index --adopt` alone is preview-only. Writing requires `--adopt --apply --expect-hash H`. Plain `--apply` on an unmarked index is refused.
- **A8 — §2.3 subprocess cleanup.** Every CLI child is started in a new session (`start_new_session=True`). On timeout or cancel, its whole process group gets TERM, then KILL after 5 s. Pipes are drained to avoid deadlocks. A test covers a grandchild process.
- **A9 — new §2.6, task writes are serialized** (needed once the backend calls the CLI concurrently).
  - Every mutating `tasks_engine` command (`transition`, `sync-index --apply`, and the `questions` writes of spec 08) takes an exclusive `fcntl.flock` on `<tasks_dir>/.ai-orch.lock` for its whole read-modify-write.
  - These commands accept `--expect-task-hash` (sha256 over the task bundle: every file of a folder task, or the single file) and refuse on mismatch.
  - They write atomically.
  - The backend maps refusals for a stale hash to HTTP 409.
  - **Platform:** the core targets macOS and Linux only, and says so in the README. On Windows, the `ai-orch` commands that need `fcntl` or process groups refuse with a clear error.
- **A10 — §2.4 config writes are previewed too.** `config set-routing` and `config set-profile` accept `--diff` (returns `{diff, hash}`) and `--expect-hash`. The Config tab uses preview → apply like every other mutating action.
- **A11 — §2.5 the extension builds standalone.** The `dist-webview` sync from the sibling `ai-orchestration-ui` checkout is a **development-only** script (`npm run sync-webview`). `dist-webview/` stays committed, so a clean standalone clone compiles without the sibling. `npm run compile` does **not** depend on the sibling.
- **A12 — UI content safety (all specs).**
  - Markdown from files or agents (task bodies, question context, run logs) is rendered with raw HTML escaped, and links limited to `http:`, `https:` and relative paths.
  - The backend sends `Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`.
  - XSS fixtures (an HTML/script payload inside a question context and inside a task title) are part of the frontend verification.

## 1. Why

The control plane can already destroy data or act on the user's behalf without their knowledge. No feature that lets it launch agents may land before this initiative is done. Findings (2026-10-16):

**Environment Doctor (`scripts/orchestration_env.py`)**

| Id | Severity | Finding |
| --- | --- | --- |
| E1 | critical, **fixed in `2ca3377`** | `remove-skill` joined the user-supplied name onto the skills dir and ran `rmtree` on it: `".."` wiped `~/.claude`, `"../.."` the home dir. Verified in a fake home; reachable unauthenticated through the web UI. |
| E2 | critical, **fixed in `2ca3377`** | `register-mcp` fell back to `{}` when a config failed to parse and rewrote the file. For `~/.claude.json` (all Claude Code state) that would drop everything. It now refuses, and writes atomically with a backup. |
| E3 | major | `register-mcp` writes the wrong files: Kilo's real config is `~/.config/kilo/kilo.jsonc` (JSONC), Codex reads `~/.codex/config.toml` (`[mcp_servers.*]`), but the tool writes `kilo.json` and `~/.codex/config.json`. `env status` reads the same wrong files, so for Codex it reports a registration that does not exist (`~/.codex/config.json`, written 2026-10-15 14:21, is ignored by Codex). It also rewrites `~/.claude.json` while Claude Code is running and rewriting that file itself. |
| E4 | major | `install-skills` runs `rmtree` on every same-named target with no check: it overwrites skills that are unmanaged, locally modified or come from another source (today: `kilo-mcp-executor-contract` on Kilo global; `kilo-mcp-conflict-resolver` and `kilo-mcp-metrics-analyst` on Claude global). It also silently deletes the `OBSOLETE_SKILL_RENAMES` directories. There is no dry-run and no backup. |
| E5 | major | The Doctor does not see plugin-installed skills. On this machine Claude loads the same skills as plugins: both `architect-side@ai-orchestration` and `architect-side@kilo-mcp` are in `~/.claude/plugins/installed_plugins.json`, giving `orchestration-workflow` and `kilo-mcp-orchestrator` twice. So the conflict report and the "resolve" action see only the `~/.claude/skills` copies, and installing there duplicates the plugin copies. |
| E6 | major | `resolve-conflicts` deletes immediately, with a hard-coded policy (Kilo keeps the generic skill, Claude and Codex keep the bound one), no dry-run and no confirmation. |
| E7 | minor | The source catalog is keyed by skill name across repos: a same-named skill from another source shows as `modified-or-outdated`, and an install overwrites it. |

**Task index (`tasks_engine.py sync-index`)**

| Id | Severity | Finding |
| --- | --- | --- |
| I1 | major | Every `Closed` date in the Done table is rewritten to today (`tasks_engine.py:1015-1019`), and hand-edited `Result` cells are replaced. |
| I2 | major | Whole sections are replaced: prose and hand-written rows inside `## Next up`, `## Decisions waiting`, `## Done` (for example the priority note and the recommendation texts in the workspace index) are lost. Blank lines are collapsed globally. |
| I3 | minor | Hard-coded project text: "architectural direction locked with owner on 2026-10-15 (see `docs/03`–`05`)". |
| I4 | minor | The file is written in place (not atomically) and with no precondition, so concurrent edits can be lost. |

**UI backend and frontend (`ai-orchestration-ui`)**

| Id | Severity | Finding |
| --- | --- | --- |
| U1 | critical | No auth and `CORS allow_origins=["*"]`: any web page can call every endpoint, including the ones that delete skills and rewrite `AGENTS.md`/`00-INDEX.md`. |
| U2 | major | Every transition silently runs `sync-index --apply` (see I1, I2). |
| U3 | major | Destructive actions have no confirmation or preview: resolve-conflicts, apply `AGENTS.md`, install (all assistants, global, by default). |
| U4 | major | There is no file watcher, although the README promises live updates. |
| U5 | major | The `async` handlers call blocking `subprocess.run` (`server.py:60-72`): one slow CLI call freezes every request and the WebSocket. |
| U6 | minor | The workspace argument of `start.sh` is ignored (`uvicorn server:app` skips `main()`). `/api/workspace/switch` changes the workspace in place without any consistency guarantee. The README says port 8765. |
| U7 | minor | Failures are silent (`Promise.allSettled`). The WebSocket indicator never turns off and never reconnects. Each action reloads all data twice. |

**VS Code extension (`vscode-ai-orchestration`)**

| Id | Severity | Finding |
| --- | --- | --- |
| V1 | major | `runJsonCommand` resolves a non-zero exit when stdout parses as JSON (`cli-client.ts:107-115`), so refusals look like successes. Several existing `api.ts` calls (install, register, remove, resolve, set-profile, render) have no handler in `dashboard-panel.ts`. |
| V2 | major | The extension prefers its own `dist-webview`, which no build step refreshes. Paths `/Users/Alfredo/...` are hard-coded. In a multi-root window the first folder is always used. |
| V3 | minor | `alert`/`confirm` may be blocked in webviews (to be verified live). |

## 2. Requirements

### 2.1 Doctor (core)

- **Every mutating `env` command** (`install-skills`, `remove-skill`, `resolve-conflicts`, `register-mcp`) supports `--dry-run`. With `--dry-run`:
  - it returns a plan: a list of `{action: create|replace|delete|edit, path, reason, current_state}`;
  - it returns `plan_hash`, the sha256 of the canonical plan JSON.

  Without `--dry-run`:
  - it accepts `--expect-plan-hash`; when the hash is given and the recomputed plan differs, it refuses;
  - the UI always uses preview-then-apply with the hash.
- **No clobbering.** `install-skills` never replaces a target whose state is `unmanaged`, `modified-or-outdated` or from a different source repo, unless `--overwrite <name>...` names it explicitly.
  - Every replaced or deleted directory is moved to `<skills_dir>/.ai-orch-trash/<timestamp>/<name>` instead of being removed.
  - Obsolete-rename cleanup is part of the plan, never implicit.
- **Plugin-aware inventory.** `env status` also reports skills that Claude plugins provide.
  - It reads `~/.claude/plugins/installed_plugins.json`: install paths and enabled state.
  - It reports Kilo marketplace skills, if Kilo exposes them on disk; the implementer verifies the real layout in `references/` or `~/.kilo`.
  - Each skill entry gets `origin: standalone|plugin:<plugin@marketplace>`.
  - Conflict detection runs over the union of all origins, per assistant and scope.
  - `resolve-conflicts` acts only on `standalone` copies. For plugin copies it reports which plugin to disable, and never edits plugin directories.
- **Resolve policy from config.** Which copy to keep comes from `orchestration.toml` (`[env.conflicts] keep = { kilo = "generic", claude = "bound", codex = "bound" }`). The current behaviour is the default.
- **MCP registration through the real configs:**
  - Claude: `claude mcp add --scope user|project ...` when the CLI exists. Otherwise an atomic edit of `~/.claude.json`, but only when no `claude` process is running.
  - Codex: `codex mcp add` when available, otherwise a surgical TOML edit of `~/.codex/config.toml` (`[mcp_servers.<name>]`).
  - Kilo: an edit of `kilo.jsonc`. If no JSONC-preserving edit is possible with the stdlib, the command emits the exact snippet to paste and changes nothing.
  - `env status` reads the same files the tools read. It reports stray files written by older versions (`~/.codex/config.json`, a `kilo.json` that shadows `kilo.jsonc`) as `stray`, without deleting them.
- **Source catalog** keyed by `(repo, plugin, name)`. A same-named skill from an unknown source is `foreign`, not `modified-or-outdated`.

### 2.2 Index (core)

- **Generated regions are explicit.** `sync-index --apply` rewrites only the content between `<!-- ai-orch:generated <section> -->` and `<!-- /ai-orch:generated <section> -->`.
  - In an index without markers, `sync-index` refuses `--apply`.
  - `sync-index --adopt` wraps only the existing generated *tables* (not prose) in markers. It shows the diff first, like any apply.
- **Row-level merge inside a region**, by id:
  - header-derived cells are updated;
  - `Closed` and `Result` cells of existing Done rows are preserved;
  - new Done rows get the date of the `git log` commit that moved the file into `done/`, falling back to today;
  - rows whose id no longer resolves are kept with `(missing)` appended to the title cell, never removed.
- **No project-specific text.** An empty Decisions table renders `| - | None. | - | - |`.
- **Safe writes.** Writes are atomic (temp file + rename). `--check` prints a unified diff. `--apply` accepts `--expect-hash <sha256 of the current file>` and refuses on mismatch.
- **Regression fixture.** A curated, committed copy of `ai-coding-tools/tasks/00-INDEX.md` plus minimal task stubs, with a provenance note. `sync-index --adopt` followed by `--apply` must lose no row, no cell of Done and no line of prose.

### 2.3 UI backend

- **Auth.**
  - A per-machine token is persisted in `~/.config/ai-orchestration/ui-token` (mode 0600, created on first start). A token that stays the same across restarts lets an open page reconnect.
  - The served `index.html` carries the token in `<meta name="ai-orch-token">`, with `Cache-Control: no-store`.
  - `/api/*` needs the header `X-AI-Orch-Token`; `/ws` needs `?token=`. A missing or invalid token → 401; the frontend reloads the page once.
  - Requests whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` → 400.
  - The CORS middleware is removed.
- **Non-blocking CLI calls.** All CLI calls go through `asyncio.create_subprocess_exec`, with a per-call timeout (default 60 s; 600 s for install and register).
- **Fixed workspace per process.**
  - `AI_ORCH_WORKSPACE` is canonicalized by `start.sh` before it changes directory; the default is the caller's current directory.
  - `/api/workspace/switch` is removed: to change workspace, start another server.
- **Watcher.** Watches `tasks/**/*.md` and the effective config files. It uses `watchfiles` if importable, otherwise a 1 s stdlib polling loop on mtimes. It debounces 300 ms and broadcasts `{type:"changed", areas:[...]}`.
- **Transitions no longer write the index.** The transition endpoint returns `index_in_sync`.
- **Preview/apply endpoints.**
  - `GET /api/tasks/sync-index/preview` → `{diff, hash}`; `POST /api/tasks/sync-index {expect_hash}`.
  - The same pattern for every mutating `env` command (`plan` + `plan_hash`).
  - The same pattern for `render-agents-md`, through a new core flag `--diff` that returns `{diff, hash}`.
- **README:** port 8780, the auth model, and how to open the UI.

### 2.4 Frontend

- **One in-app confirmation modal** shows the plan or diff before every mutating action and applies with the hash. It replaces every `alert`/`confirm`.
- **Installer:** no assistant preselected; scope must be chosen explicitly; the preview shows what would be replaced or trashed.
- **Doctor:** shows each skill's `origin`, plugin duplicates and stray config files. "Resolve" opens the preview.
- **Feedback:** per-panel error banners. A WebSocket `onclose` turns the indicator off and reconnects with exponential backoff. A reload refreshes only the areas named in the broadcast, once.

### 2.5 VS Code extension

- `cli-client.ts` rejects a non-zero exit even when stdout is JSON, passing the parsed error through.
- `dashboard-panel.ts` has one handler per `api.ts` method, covering all of them (a test enumerates `api.ts` method names against the handler map).
- The `dist-webview` refresh is a build step (`npm run sync-webview`, which copies from `../ai-orchestration-ui/frontend/dist`), and is part of `npm run compile`.
- No hard-coded user paths.
- A multi-root window asks which folder to bind the dashboard to.

## 3. Out of scope

- Editing plugin directories or Kilo marketplace installs: the Doctor reports, the user acts.
- Deleting the stray config files: the Doctor reports them; removal is the owner's decision.
