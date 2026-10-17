# T016 report: are the Doctor's persistent findings real?

- Date: 2026-10-17. Machine: owner's Mac, real home, read-only (only `env status` and `--dry-run` runs).
- Code under study: `scripts/orchestration_env.py` (2694 lines at the time of the study), `../ai-orchestration-ui/frontend/src/components/EnvironmentDoctor.tsx`, `../ai-orchestration-ui/frontend/src/components/ConfirmDialog.tsx`, `../ai-orchestration-ui/frontend/src/components/SkillInstaller.tsx`, `../ai-orchestration-ui/backend/server.py`.
- Spec: `tasks/specs/control-plane-safety.md` (§0 A4–A6, §1 E3–E7, §2.1).

## TL;DR

The findings that "never resolve" fall into three groups:

1. **Things that are real but the Doctor cannot fix.** These are shown as red, fixable errors with a "Resolve…" button. The plan behind that button contains only `ADVISE` items, so applying it does nothing. Then the same red banners come back. This is the main cause of the owner's complaint: **all 12 Claude conflicts (24 banners, because the project scope repeats the global ones) sit in a no-op loop.**
2. **Wrong classifications.** 17 skills are labelled `foreign`. 14 of them are older copies of our own catalog (an exact blob match in the git history of the source repo) and 2 differ only in YAML quoting. 38 `unmanaged` skills (legitimate third-party and toolkit skills) get the same amber badge as real drift.
3. **Missing checks.** The Doctor misses the actual problems:
   - the Claude plugin copies are stale against the source repos (ai-orchestration plugin 69 commits behind, kilo-mcp plugin 7 behind) while their version strings are unchanged;
   - Kilo also loads `~/.claude/skills` and `~/.config/kilo/skills`, which gives 14 real cross-directory duplicates and one trigger conflict that the Doctor never shows.

What needs to change: the resolution logic, the classification rules **and** the UI presentation. Nothing here is "fine as is".

## Summary table

Counts are for `--workspace /Users/Alfredo/works/ai-coding-tools` unless marked (AO = `--workspace .../ai-orchestration`).

| # | Kind (as shown) | Count | Verdict | Root cause | Proposed change | Size |
|---|---|---|---|---|---|---|
| 1 | `duplicate-name`, standalone vs Claude plugin (red banner + "Resolve…") | 11 (Claude global), shown twice (global + project) = 22 banners | TRUE (Claude really loads both copies). Wrongly presented as fixable | `resolve_conflicts` trashes a standalone copy only if it is byte-identical, `up-to-date` or matches the catalog hash (`orchestration_env.py:1978-1982`). All 11 differ, so they become `advise` (`:2002-2019`). Apply runs only `conflict_items` (`:2081`), which is a no-op. The UI still shows red + "Resolve…" (`EnvironmentDoctor.tsx:317-358`) and Confirm stays enabled | (a) Resolve button and red colour only when the plan has ≥1 executable action. (b) Smarter equality: frontmatter-normalised, any cached version of the same plugin, git history of the catalog. This makes 5 of 11 auto-resolvable. (c) Advice-only items get "acknowledge" | S + M |
| 2 | `trigger-conflict` `orchestration-workflow` + `kilo-mcp-orchestrator` (Claude) | 1, shown twice | TRUE BUT NOT ACTIONABLE BY DOCTOR | Policy `claude=bound` removes the generic skill, which exists only as plugin `architect-side@ai-orchestration`, so the plan says ADVISE "disable plugin" (`:1926-1943`). That would also drop 5 unrelated skills. The UI shows it red with "Resolve…" because a standalone `kilo-mcp-orchestrator` is among the entries (`EnvironmentDoctor.tsx:284`) | Info severity + proportional advice text + acknowledge. Long term: the generic skill's description defers to the bound skill when both are present | S |
| 3 | state `foreign` (amber badge) | kilo 5, claude 7, codex 5 = 17 | Mostly FALSE as "foreign": 14 are older versions of our own skills, 2 differ only in YAML quoting, 1 is outdated + quoting | Spec A4 rule "no receipt and no hash match → foreign" (`:436-454`). None of the 3 home skill dirs has a single `.ai-orch-source.json`, because these were installed before receipts existed or by other tools. They cannot be cleared from the UI: `install-skills` SKIPs `foreign` unless `--overwrite` (`:1602-1610`), and `SkillInstaller.tsx:39,48` never passes `overwrite` | New state `outdated-legacy` (match against the git history of the catalog file, or frontmatter-normalised equality). A per-row "Update (overwrite)" action with diff preview | M |
| 4 | state `unmanaged` (amber badge) | kilo 21+2, claude 13+2 = 38 | FALSE as a warning | The catalog only covers `ai-orchestration`, `kilo-mcp`, `claude-mcp` (`:339`). Every other skill is `unmanaged`, and the UI paints every state other than up-to-date/plugin/obsolete amber (`EnvironmentDoctor.tsx:455-470`) | Neutral grey "external" badge, collapsed by default, no severity | S |
| 5 | Claude project scope repeats global conflicts and plugin rows | 12 banners + 34 plugin rows duplicated | FALSE (presentation duplication) | The project view is built as the union of global standalone + plugins (`:1138-1149`, `:1192-1195`). The UI renders it as a separate scope | Show in project scope only the conflicts that involve a project-scope entry. Show "inherited from global" as one line | S |
| 6 | `duplicate-name` standalone project vs standalone global (AO only) | 5 | TRUE (copies written today 11:13Z into `ai-orchestration/.claude/skills`, untracked in git) but the resolution path is missing | `resolve_conflicts` has branches only for standalone+plugin and plugin-only (`:1949`, `:2021`). Standalone-only duplicates produce **no plan item at all**, yet the UI shows red "Resolve…" | Add a branch: identical → trash the project copy (or follow a configurable rule); different → advise with diff | S |
| 7 | `stray` `~/.codex/config.json` (amber banner) | 1 | TRUE BUT NOT ACTIONABLE BY DOCTOR | Written 2026-10-15 14:21 by the old `register-mcp` (spec E3). Codex reads `config.toml`. By spec §2.1 it is reported "without deleting", and no action exists | "Move to trash" action with preview, showing whether each server in it is already in `config.toml` | S |
| 8 | MCP `Overrides:` (amber) on Kilo `playwright` | 1 | TRUE but benign (identical definitions) | `kilo.json` (written at the same second as #7) and `kilo.jsonc` both define `playwright` with the same command. `read_kilo_merged_mcps` flags any redefinition (`:793-799`) without comparing content | Compare configs: "redundant (identical)" = info, "conflicting" = warning. Offer to remove the entry from `kilo.json` | S |
| 9 | Agent `kilo-mcp-orchestrator-agent.md` `foreign` (Claude) | 1 (JSON only, not rendered) | FALSE (deliberate per-assistant adaptation) | The Claude copy drops the Kilo-only `mode`/`permission` frontmatter. The raw sha differs (`:457-522`). The UI has no agent table at all | Per-assistant agent transform at install time + hash of the transformed output. Render agents in the UI | M |
| 10 | (not reported) Claude plugin copies stale vs source | 2 plugins | MISSING CHECK (TRUE problem) | Plugin entries always get state `plugin` (`:1136`) with no drift check. Plugin cache `architect-side@ai-orchestration` = `30521e8a`, 69 commits behind HEAD. `architect-side@kilo-mcp` = `1a35cc0`, 7 behind. `plugin.json` versions unchanged (0.3.0 / 0.2.2), so Claude will not update them. Consequence: "keep plugin copy" keeps the **older** copy | Plugin drift state (`plugin-stale`) for plugins whose marketplace is a catalog repo. Advise "bump version and update plugin" | M |
| 11 | (not reported) Kilo cross-directory duplicates and Kilo trigger conflict | 14 dup names + 1 trigger | MISSING CHECK (TRUE problem) | Kilo loads `~/.claude/skills/**`, `~/.agents/skills/**`, `~/.config/kilo/{skill,skills}`, `~/.kilo/{skill,skills}`. The Doctor scans only `~/.kilo/skills` (`:259-274`) | Effective Kilo view over all roots Kilo reads | M |
| 12 | (plan, not a finding) `install-skills` creates new conflicts | 5 + 2 | TRUE design flaw (ping-pong) | The install plan ignores plugin coverage and the conflict policy (`:1583-1619`) | Skip names provided by an enabled plugin and names the policy would remove | S |
| 13 | (plan, not a finding) `register-mcp` not idempotent | 2 | TRUE (minor) | It plans `cli` even when `current_state: registered`, with a different launch command | No-op when registered with an equivalent command. Otherwise a `replace` item showing the old and new command | S |

## Evidence

### 0. Commands run

```sh
./bin/ai-orch env status --workspace /Users/Alfredo/works/ai-coding-tools --json      # rc=0
./bin/ai-orch env status --workspace /Users/Alfredo/works/ai-coding-tools/ai-orchestration --json   # rc=0
./bin/ai-orch env resolve-conflicts --dry-run --workspace /Users/Alfredo/works/ai-coding-tools      # rc=0
./bin/ai-orch env install-skills --dry-run --assistants all --scope global              # rc=0
./bin/ai-orch env register-mcp kilo-mcp --assistants all --scope global --dry-run [--json]   # rc=0
```

Inventory from `env status --json` (counts of `(origin, state)` in `skill_entries`):

```text
kilo   global  ~/.kilo/skills        unmanaged 21, up-to-date 7, foreign 5           structured: none
kilo   project ws/.kilo/skills       unmanaged 2                                       (AO: up-to-date 12)
claude global  ~/.claude/skills      unmanaged 13, foreign 7, up-to-date 1, plugin 33  structured: duplicate-name 11, trigger-conflict 1
claude project ws/.claude/skills     unmanaged 2, plugin 33 (repeated)                 structured: duplicate-name 11, trigger-conflict 1  (AO: 16 + 1)
codex  global  ~/.codex/skills       up-to-date 7, foreign 5                           structured: none
codex  project                       0                                                 (AO: up-to-date 12)
stray: ['/Users/Alfredo/.codex/config.json']
MCP: kilo global {codex-mcp, playwright(overrides kilo.json), redmine, sequentialthinking};
     claude global {codex, codex-mcp, kilo-mcp, playwright, redmine}; codex global {kilo-mcp, playwright, vscode-dap}
```

No `modified-or-outdated` and no `obsolete-renamed` entries exist on this machine. Receipts check:

```text
$ ls ~/.kilo/skills/*/.ai-orch-source.json ~/.claude/skills/*/.ai-orch-source.json ~/.codex/skills/*/.ai-orch-source.json
no matches (0 / 0 / 0)
```

`resolve-conflicts --dry-run` (the full plan has 12 items, all `ADVISE`, 0 `trash`):

```text
ADVISE ~/.claude/plugins/cache/ai-orchestration/architect-side/0.3.0/skills/orchestration-workflow
       (disable plugin architect-side@ai-orchestration in ~/.claude/settings.json (enabledPlugins) or uninstall it)
ADVISE ~/.claude/skills/framework-skillset-generator (standalone copy differs from plugin agent-tooling-meta@agentic-coding-kit ...)
ADVISE ~/.claude/skills/frontend-design | gcube-component-release | gcube-jenkins | gcube-liferay62-release-deploy |
       gcube-repo-standards | gcube-security-audit | kilo-mcp-conflict-resolver | kilo-mcp-orchestrator |
       liferay62-angular-portlet | task-pipeline   (same "differs ... review and remove one manually")
```

### 1. `duplicate-name`: standalone vs plugin (11). TRUE, stuck in a no-op loop

They are real: Claude Code exposes both copies. In this very session's skill list, `gcube-jenkins` and `gcube-developer-tools:gcube-jenkins` both appear, as do `task-pipeline` and `architect-side:task-pipeline`, and so on.

Content comparison against the **active** plugin install path (from `installed_plugins.json`), excluding `index.json`, `.DS_Store`, `__pycache__` and `.pytest_cache`:

| Skill | Diff lines vs active plugin | Byte-identical to a cached plugin version | Frontmatter-normalised equal to | Nature of the difference |
|---|---|---|---|---|
| framework-skillset-generator | 134 (vs 0.2.0) | **0.1.0** | 0.1.0 | Older plugin version. Safe to drop |
| gcube-component-release | 6 | none | **0.2.0, 0.2.1** | Frontmatter re-serialisation only |
| gcube-liferay62-release-deploy | 8 | none | **0.2.0, 0.2.1** | Frontmatter only |
| gcube-repo-standards | 6 | none | **0.2.1** | Frontmatter only |
| liferay62-angular-portlet | 6 | none | **0.2.0, 0.2.1** | Frontmatter only |
| gcube-jenkins | 6 + extra `references/` dir | none | none | Standalone has extra files. Real divergence |
| gcube-security-audit | 267 + extra `assets/`, `references/`, 3 scripts | none | none | Real divergence (standalone is richer) |
| frontend-design | 93; plugin has `LICENSE`, `local.patch` | none | none | Real divergence (plugin is patched) |
| task-pipeline | 241 | none | none | Ours. Standalone is **newer** than the plugin (see #10) |
| kilo-mcp-orchestrator | 88 | none | none | Ours. Standalone is newer than the plugin |
| kilo-mcp-conflict-resolver | 16 | none | none | Ours. Standalone is newer than the plugin |

The "frontmatter only" diff looks like this (standalone vs plugin):

```text
$ diff ~/.claude/skills/gcube-jenkins/SKILL.md ~/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.1/skills/gcube-jenkins/SKILL.md
4,6c4,6
< metadata: ""
< author: Alfredo Oliviero
< version: 1.0.0
---
> metadata:
>   author: Alfredo Oliviero
>   version: 1.0.0
```

The standalone copies were written by an installer that serialises frontmatter one line per key and flattens the nested `metadata` map. The pattern is consistent with `ai-swissknife/src/adapters/claude.ts:159-171` (`serializeSkillMarkdown`: ``fm += `${key}: ${serializeYamlValue(value)}\n` ``), but the writer was **not proven**. Either way this is a real, if small, corruption of the copy: `metadata` lost its children.

Why the finding persists:

- `orchestration_env.py:1978-1982`: a standalone copy is trashed only if `state == up-to-date`, or it is byte-identical to a current plugin copy, or its hash is in the catalog. These skills are `unmanaged` or `foreign`, and none is byte-identical to the **active** plugin version. Comparing against older cached versions or normalised content is not attempted.
- `:2002-2019`: otherwise `advise`, and nothing is added to `c_items`.
- `:2081-2097`: apply iterates `conflict_items` only, so it moves nothing, returns `ok: true, resolved_count: 0`, and the UI calls `onRefresh()` (`EnvironmentDoctor.tsx:56-58`). The same banners come back.
- UI: `hasResolvableConflicts` is true whenever any entry is standalone (`EnvironmentDoctor.tsx:30-41`). Each such banner is red with "Resolve…" (`:317-358`). `ConfirmDialog` supports `isApplyDisabled` (`ConfirmDialog.tsx:35,452`), but the Doctor never passes it (`EnvironmentDoctor.tsx:572-585`), so "Confirm & Apply" is enabled on an all-`advise` plan.

### 2. `trigger-conflict` (Claude). TRUE, not actionable by the Doctor

Entries: `plugin:architect-side@ai-orchestration` `orchestration-workflow`, standalone `~/.claude/skills/kilo-mcp-orchestrator` (`foreign`), and `plugin:architect-side@kilo-mcp` `kilo-mcp-orchestrator`. Both descriptions start with "Orchestrate an Executor agent / Orchestrate Kilo (the Executor) ..." and overlap almost word for word, so the trigger competition is real.

`load_conflict_policy` defaults to `claude = bound` (`:536-540`), so the generic skill must go. It exists only as a plugin, so the plan is `ADVISE disable plugin architect-side@ai-orchestration` (`:1926-1943`). That plugin also provides `task-pipeline`, `task-spec-authoring`, `task-worktree-ops`, `orchestration-metrics` and `conflict-resolver`, so following the advice would remove 5 skills the owner uses. The advice is disproportionate, and in practice the owner keeps both plugins enabled on purpose (`~/.claude/settings.json` `enabledPlugins`: all 7 true).

Because the standalone `kilo-mcp-orchestrator` is in `entries`, `isAllPlugin` is false (`EnvironmentDoctor.tsx:284`) and the banner is red with "Resolve…". It never resolves.

Two side observations:

- The trigger pair is hard-coded (`:1213-1215`). The analogous pair `executor-contract` / `kilo-mcp-executor-contract`, present in all three assistants, is not checked.
- For Codex and Kilo the hard-coded pair causes a ping-pong with `install-skills` (#12).

### 3. `foreign` (17). Mostly misclassified legacy installs

Method: `git hash-object` of the installed `SKILL.md` (or a script), then `git log --all --find-object=<blob>` on the source file in the catalog repo. Only the sampled file was blob-matched, not every file in the directory.

```text
~/.{kilo,claude,codex}/skills/task-pipeline/SKILL.md          -> ai-orchestration 2e5a6c2 2026-10-16
~/.{kilo,claude,codex}/skills/executor-contract/SKILL.md      -> ai-orchestration 927244a 2026-10-15
~/.{kilo,claude,codex}/skills/orchestration-setup/scripts/orchestration_config.py -> ai-orchestration 927244a 2026-10-15
~/.kilo/skills/orchestration-workflow/SKILL.md                -> ai-orchestration 55682fc 2026-10-15
~/.{claude,codex}/skills/kilo-mcp-executor-contract/SKILL.md  -> kilo-mcp ce7e380 2026-10-15
~/.{claude,codex}/skills/kilo-mcp-orchestrator/SKILL.md       -> kilo-mcp 7b674b8 2026-10-15
~/.claude/skills/kilo-mcp-conflict-resolver/SKILL.md          -> no match; diff vs source = 2 lines (description quoted vs unquoted)
~/.claude/skills/kilo-mcp-metrics-analyst/SKILL.md            -> no match; diff vs source = 2 lines (same quoting)
~/.kilo/skills/kilo-mcp-executor-contract/SKILL.md            -> no match; 27 diff lines (quoting + missing "Blocking questions" section = outdated)
```

So 14/17 are **outdated copies of our own catalog**, 2/17 are **semantically identical** (only YAML quoting differs), and 1/17 is outdated with a re-serialised frontmatter. None is foreign in the plain sense of "comes from another source".

The code conforms to spec A4 (`:436-454`, "no receipt and no hash match → foreign"). The rule itself mislabels pre-receipt installs. Spec E4 records that the old installer clobbered these very directories, so they are ours.

Why they persist:

- `install-skills --dry-run` shows `SKIP ... (Skip foreign skill '<name>': not in --overwrite list)` for 13 of them (`:1602-1610`).
- The UI installer never sends `overwrite` (`SkillInstaller.tsx:39`, `:48`, only `api.ts:287-319` has the parameter).
- The only UI path is per-row trash (`EnvironmentDoctor.tsx:476-492`) followed by a reinstall, which nobody discovers. The badge is amber with no explanation.

### 4. `unmanaged` (38). FALSE as a warning

`discover_available_skills` scans only `ai-orchestration`, `kilo-mcp`, `claude-mcp` (`:339`). Everything else is `unmanaged`: the gcube toolkit skills, third-party skills, `impeccable`, the `d4science-*` skills, the project `ai-debugger`, and so on. These are legitimate and not drift. The state badge colour falls through to amber (`#451a03`/`#fbbf24`) for any state that is not `up-to-date`, `plugin` or `obsolete*` (`EnvironmentDoctor.tsx:455-470`), the same colour as `foreign`. So 38 entries look like problems.

### 5. Claude project scope duplicates the global view. FALSE (presentation)

`inspect_environment` adds all `user`-scope plugin skills to the project entries (`:1138-1149`) and computes project conflicts over project entries + global standalone (`:1192-1195`). The project section therefore repeats the same 12 conflicts and 33 plugin rows (34 in the AO view). The owner sees 24 red banners for 12 problems.

### 6. Project vs global standalone duplicates (AO workspace, 5). TRUE, no resolution path

```text
duplicate-name executor-contract          [project up-to-date, global foreign]
duplicate-name kilo-mcp-executor-contract [project up-to-date, global foreign]
duplicate-name kilo-mcp-metrics-analyst   [project up-to-date, global foreign]
duplicate-name kilo-mcp-rag-explorer      [project up-to-date, global up-to-date]
duplicate-name orchestration-setup        [project up-to-date, global foreign]
```

- The project copies carry receipts with `installed_at: 2026-10-17T11:13:24Z`, so they came from an `install-skills --scope project` run today.
- `git status` shows `?? .claude/`, `?? .codex/`, `?? .kilo/skills/`, `?? .kilo/agents/`, `?? .kilo/kilo.json`: untracked, not ignored.
- `resolve_conflicts` handles `duplicate-name` only when `standalone_entries and plugin_entries` (`:1949`) or plugins only (`:2021`). Standalone-only duplicates get no plan item, while the UI shows them red with "Resolve…".
- Owner decision needed (not the Doctor's): keep these project copies (then add them to `.gitignore` or commit them) or remove them.

### 7. Stray `~/.codex/config.json`. TRUE, not actionable

- Modification time `Oct 15 14:21:38 2026`, identical to `~/.config/kilo/kilo.json`. This matches spec E3: the old `register-mcp` wrote it.
- Contents: `mcpServers: {kilo-mcp (.venv/bin/python server.py), codex-mcp}`.
- Codex reads `config.toml`, which has `kilo-mcp` (via `uv run`), `playwright`, `vscode-dap`. So the JSON's `codex-mcp` entry has never been active for Codex.
- The detection (`:1298-1301`) is correct. Spec §2.1 says "report ... without deleting them", so there is no action and the banner stays forever. The banner text ("ignored by the assistant's runtime", `EnvironmentDoctor.tsx:165-187`) is accurate but gives no next step.
- Separately, `ai-swissknife/src/adapters/codex.ts:243` also targets `~/.codex/config.json`. That is a second writer to fix in that repo, or the file will come back.

### 8. Kilo MCP override (`playwright`). TRUE but benign

`~/.config/kilo/kilo.json` and `kilo.jsonc` both define `playwright` as `["npx","-y","@playwright/mcp@0.0.38"]`, so the definitions are identical. The merge reader appends to `overrides` on any redefinition (`:793-799`) without comparing content, and the UI shows it in amber (`EnvironmentDoctor.tsx:540-544`). Kilo's own merge precedence makes `kilo.jsonc` win (spec A1), so nothing is broken.

### 9. Agent `kilo-mcp-orchestrator-agent.md` (Claude, `foreign`). FALSE, not rendered

```text
$ diff ~/.claude/agents/kilo-mcp-orchestrator-agent.md kilo-mcp/plugins/architect-side/agents/kilo-mcp-orchestrator-agent.md
3a4,9
> mode: subagent
> permission: {read, edit, bash, mcp: allow}
```

- The Claude copy is the Kilo agent minus the Kilo-only frontmatter, a deliberate adaptation.
- `install_skills` copies the same agent file verbatim to Claude and Kilo (`:1523-1580`), so a reinstall would put the Kilo fields into Claude.
- `EnvironmentDoctor.tsx` never renders `agents` (0 occurrences), so the owner never sees this.

### 10. Stale Claude plugin copies. Missing check

```text
installed_plugins.json: architect-side@ai-orchestration 0.3.0 gitCommitSha 30521e8a (2026-10-15 12:33) -> 69 commits behind ai-orchestration HEAD
                        architect-side@kilo-mcp        0.2.2 gitCommitSha 1a35cc0                    -> 7 commits behind kilo-mcp HEAD
plugin.json versions in the repos today: 0.3.0 and 0.2.2 (unchanged, so Claude has no reason to update)

diff lines vs source repo (excl. index.json, fixtures, caches):
  task-pipeline           standalone 7546 | plugin 7681
  kilo-mcp-orchestrator   standalone   19 | plugin  107
  kilo-mcp-conflict-res.  standalone    2 | plugin   14
```

In all three overlaps with our own skills, the standalone copy is closer to the source than the plugin copy. The resolve rule "plugin copy kept" (`:1988`) would therefore keep the staler copy. Plugin entries are always state `plugin` (`:1136`) with no drift check.

### 11. Kilo's effective skill set. Missing check

Kilo source (`references/kilocode/kilocode/packages/opencode/src`):

- `skill/index.ts:24-25,29-30`: external dirs `.claude`, `.agents` with pattern `skills/**/SKILL.md`; config dirs with `{skill,skills}/**/SKILL.md`.
- `skill/index.ts:240-246`: global scan of `~/.claude/skills` and `~/.agents/skills` unless `KILO_DISABLE_CLAUDE_CODE_SKILLS` / `KILO_DISABLE_EXTERNAL_SKILLS` is set. Neither is set, and the config does not disable it.
- `skill/index.ts:271-282` + `config/paths.ts:23-40`: config dirs = `~/.config/kilo` + `.kilo`/`.kilocode` found walking up from home and the project.

The Doctor scans only `~/.kilo/skills` (`assistant_skills_dir`, `:259-274`). Same-name skills Kilo sees from more than one root, excluding Claude-synced account skills:

```text
executor-contract, framework-skillset-generator, frontend-design, gcube-jenkins, gcube-liferay62-release-deploy,
gcube-repo-standards, gcube-security-audit, kilo-mcp-conflict-resolver, kilo-mcp-executor-contract,
kilo-mcp-metrics-analyst, kilo-mcp-rag-explorer, orchestration-setup, task-pipeline   (~/.kilo/skills + ~/.claude/skills)
toolkit-release-manager                                   (~/.config/kilo/skills + ~/.kilo/skills + ~/.claude/skills)
```

That is 14. In addition:

- Kilo sees `orchestration-workflow` (`~/.kilo/skills`) **and** `kilo-mcp-orchestrator` (`~/.claude/skills`): a real Kilo trigger conflict that the Doctor reports as "no conflicts".
- `~/.claude/skills/synced/**` (Claude account-synced skills, up to 4 copies each of `docx`, `pdf`, `pptx`, …) and `~/.claude/skills/.trash/**` (5 `SKILL.md`) are inside Kilo's `skills/**` glob with `dot: true`. This is probably loaded by Kilo too; not verified at runtime.

### 12. `install-skills` creates the conflicts that `resolve-conflicts` then reports

From `install-skills --dry-run --assistants all --scope global`:

```text
CREATE ~/.claude/skills/{conflict-resolver, orchestration-metrics, orchestration-workflow, task-spec-authoring, task-worktree-ops}
CREATE ~/.codex/skills/orchestration-workflow
```

- All 5 Claude names are already provided by the enabled plugin `architect-side@ai-orchestration`, so applying would add 5 new `duplicate-name` conflicts.
- `orchestration-workflow` in Claude/Codex is exactly what the `bound` policy removes. Install and resolve undo each other.
- The install plan (`:1583-1619`) looks at neither plugins nor the conflict policy.

### 13. `register-mcp` plan

```text
EDIT ~/.config/kilo/kilo.json   current_state unregistered   (adds kilo-mcp to Kilo itself)
CLI  claude mcp add --scope user kilo-mcp -- .../kilo-mcp/.venv/bin/python .../server.py   current_state: registered
CLI  codex mcp add kilo-mcp -- .../kilo-mcp/.venv/bin/python .../server.py                current_state: registered
```

- Both CLI items run although the server is registered. The existing registration uses `uv run --no-project --with mcp>=2 python .../server.py`, so the item would replace the owner's chosen launch command, or fail. What `claude mcp add` does with an existing name was not verified.
- Registering `kilo-mcp` inside Kilo means Kilo delegating to Kilo, which is questionable as a default for `--assistants all`.
- This is not a Doctor finding, but it is part of "the fixes don't work as I expect".

## Proposed changes (prioritised, each ready to become a task)

### P1-a. Stop the no-op "Resolve" loop (S)

- **Goal:** a conflict is shown as fixable only when the plan contains an executable action for it. An all-advise plan cannot be "applied".
- **Files:**
  - `scripts/orchestration_env.py`: in `inspect_environment`, attach to each `structured_conflicts` item `actionable: bool` and `advice: str`, computed by the same rules `resolve_conflicts` uses. Factor the per-conflict decision into one function shared by both.
  - `EnvironmentDoctor.tsx`: red + "Resolve…" only if `actionable`. `hasResolvableConflicts` uses `actionable`. Pass `isApplyDisabled` when the plan has no `trash`/`replace` items and change the button label to "Nothing to apply".
- **Verification:** on the current home, the Doctor shows no red "Resolve…" for the 12 Claude conflicts (they become info/advice). A test fixture with one byte-identical standalone+plugin pair still shows red and resolves. Unit test: a plan with only `advise` sets `isApplyDisabled`.

### P1-b. Severity model, de-duplication, acknowledge (M)

- **Goal:** the owner sees only what needs action. Anything known and accepted stays quiet until it changes.
- **Severity levels:**
  - `error`: actionable conflict.
  - `warning`: actionable drift (`outdated-legacy`, `modified-or-outdated`, `plugin-stale`, conflicting MCP override).
  - `info`: true but not actionable (plugin-only conflicts, trigger conflict with plugins, stray file, redundant MCP override).
  - `neutral`: `unmanaged`/external, `plugin`.
- **Grouping:** group by kind across assistants ("11 skills duplicated between ~/.claude/skills and Claude plugins"), expandable per item. In project scope show only conflicts that involve a project entry, plus one line "N conflicts inherited from global".
- **Acknowledge:** per finding, persisted in `~/.config/ai-orchestration/doctor-ack.json`, written only through a previewed CLI command (`env ack --dry-run/--expect-plan-hash`). The key is `(assistant, scope, kind, names, sorted content hashes of the entries)`, so an acknowledged finding comes back when any copy changes. A "show acknowledged" toggle.
- **Explanation text per kind:** what it means, why the Doctor cannot fix it, the exact manual step. Examples:
  - "Claude loads both copies; the plugin is managed by Claude's plugin manager. To remove the standalone copy use the trash icon; to remove the plugin copy disable `<id>` in enabledPlugins."
  - For the trigger conflict: "disabling `architect-side@ai-orchestration` also removes task-pipeline, task-spec-authoring, …".
- **Files:** `orchestration_env.py` (severity field, ack store + `env ack` command), `EnvironmentDoctor.tsx`, `server.py` (ack endpoints using preview/apply), types.
- **Verification:**
  - On the current home the top of the Doctor shows ≤ 5 groups.
  - Acknowledging the trigger conflict hides it, and it reappears after touching the standalone `SKILL.md` in a fake home.
  - The `unmanaged` rows are grey.

### P1-c. Smarter duplicate resolution: equality and history (M)

- **Goal:** auto-resolve standalone copies that are only older or re-serialised versions of what a plugin or the catalog provides.
- **Rules**, in order (a standalone entry is safe to trash, with the plugin kept, when any holds):
  1. byte-identical to the active plugin copy (today's rule);
  2. byte-identical to **any cached version** of the same plugin under `~/.claude/plugins/cache/<marketplace>/<plugin>/*/skills/<name>`;
  3. equal after frontmatter normalisation: YAML-parse, merge a flattened `metadata`, drop empty values, compare body + parsed keys;
  4. for our own skills, every file's blob is in the git history of the catalog source **and** the plugin copy is not older (see P1-d).

  Otherwise advise, with a diff link.
- **Expected on this machine:** 5/11 become auto-resolvable (framework-skillset-generator, gcube-component-release, gcube-liferay62-release-deploy, gcube-repo-standards, liferay62-angular-portlet). gcube-jenkins, gcube-security-audit and frontend-design stay as advice with a diff. task-pipeline, kilo-mcp-orchestrator and kilo-mcp-conflict-resolver wait for P1-d.
- **Files:** `orchestration_env.py` (`resolve_conflicts` `:1945-2044`, new helper `skill_equivalent(a, b)`), tests.
- **Verification:** a fixture home reproducing the gcube-jenkins frontmatter flattening resolves to `trash`. A fixture with an extra file stays `advise`. `resolve-conflicts --dry-run` on the real home lists exactly those 5 `trash` items.

### P1-d. Detect stale plugin copies (S/M)

- **Goal:** report when a Claude plugin from a catalog marketplace (`ai-orchestration`, `kilo-mcp`) is behind the source repo, and never "keep plugin copy" when the plugin is the older one.
- **How:**
  - compare `installed_plugins.json` `gitCommitSha` with the source repo `HEAD`, plus a content hash per skill against the catalog;
  - new entry state `plugin-stale`, severity warning;
  - advice "bump `plugin.json` version and run `/plugin update <id>`", or the marketplace update flow.
- **Files:** `orchestration_env.py` (`discover_claude_plugin_skills`, `inspect_environment`, `resolve_conflicts` keep-rule), UI badge.
- **Verification:** on the current home both architect-side plugins show `plugin-stale` (69 and 7 commits behind). A fixture where the plugin is current shows `plugin`.

### P2-a. History-aware classification of legacy installs (M)

- **Goal:** copies of our own skills installed before receipts existed are shown as `outdated-legacy` (or `up-to-date` when only frontmatter quoting differs), not `foreign`. The owner can update them from the UI.
- **How:**
  - in `detect_skill_state` (`:436-454`), before returning `foreign`, check whether every file's blob appears in `git log --all --find-object` of the matching catalog path (cache per run), or whether the content is frontmatter-equal to the catalog;
  - update spec A4 to add the state;
  - the UI gets an "Update…" row action calling `install-skills --overwrite <name>` with preview.
- **Files:** `orchestration_env.py`, `tasks/specs/control-plane-safety.md` (A4 amendment), `SkillInstaller.tsx`/`EnvironmentDoctor.tsx`, `server.py` (pass `overwrite`).
- **Verification:** on the current home, 0 `foreign` among the 17 (14 `outdated-legacy`, 2 `up-to-date`, 1 `outdated-legacy`). Dry-run "Update" of `~/.codex/skills/task-pipeline` shows `replace` with before/after hashes.

### P2-b. Kilo effective view (M)

- **Goal:** the Kilo section reflects what Kilo loads: `~/.kilo/{skill,skills}`, `~/.config/kilo/{skill,skills}`, `~/.claude/skills/**` (unless `KILO_DISABLE_CLAUDE_CODE_SKILLS`), `~/.agents/skills/**`, project `.kilo`/`.kilocode`/`.claude`/`.agents`, and `skills.paths` from the merged Kilo config.
- **How:** entries carry `origin: standalone:<root>`, and conflicts are computed over that union. `install`/`remove` keep targeting `~/.kilo/skills` only.
- **Files:** `orchestration_env.py` (`inspect_environment`, new `kilo_skill_roots()`), UI origin column.
- **Verification:** on the current home Kilo shows the 14 cross-root duplicates listed in evidence #11 and the trigger conflict. Setting `KILO_DISABLE_CLAUDE_CODE_SKILLS=1` in the CLI env removes the `~/.claude` ones.

### P2-c. Make install respect plugins and policy (S)

- **Goal:** `install-skills` no longer creates the conflicts `resolve-conflicts` reports.
- **Rules:**
  - Claude target: skip with reason "provided by enabled plugin `<id>`" when an enabled plugin provides the name;
  - skip names that `[env.conflicts] keep` would remove in that assistant (e.g. `orchestration-workflow` for Claude/Codex under `bound`);
  - `--force` overrides both.
- **Files:** `orchestration_env.py` (`install_skills` `:1583-1619`), tests.
- **Verification:** `install-skills --dry-run --assistants all --scope global` on the current home shows the 5 Claude `CREATE` items and the Codex `orchestration-workflow` item as `SKIP` with those reasons.

### P2-d. Standalone-only duplicates (S)

- **Goal:** project-vs-global standalone duplicates get a plan. Identical content → trash the project copy (default; the rule can be configured as `keep_scope = project|global`). Different content → advise with diff.
- **Files:** `orchestration_env.py` (`resolve_conflicts`).
- **Verification:** AO workspace dry-run lists `kilo-mcp-rag-explorer` (both up-to-date) as `trash` of one copy, and the other 4 per the chosen rule. No red banner without a plan item.

### P3-a. Stray file and redundant MCP actions (S)

- **Goal:** the stray banner and redundant MCP overrides can be cleared.
- **How:**
  - `env clean-stray --dry-run/--expect-plan-hash` moves `~/.codex/config.json` to the ai-orch trash. The preview lists each server in it and whether `config.toml` already has it.
  - `read_kilo_merged_mcps` marks an override `identical: true|false`. An identical override is info, with a previewed edit removing the entry from `kilo.json`.
  - Open a follow-up in `ai-swissknife` to stop writing `~/.codex/config.json` (`src/adapters/codex.ts:243`).
- **Verification:** in a fake home with both files, the dry-run plan lists one `trash` and one `edit`. After apply, `env status` shows no stray and no override.

### P3-b. `register-mcp` idempotency (S)

- **Goal:** no CLI call when the server is already registered with an equivalent command. Otherwise a `replace` item that shows the old and new command. `--assistants all` does not register `kilo-mcp` into Kilo unless asked explicitly.
- **Files:** `orchestration_env.py` (`register_mcp_server` `:2124-2427`).
- **Verification:** on the current home the dry-run shows `noop` for Claude and Codex (or `replace` showing `uv run …` → `.venv/bin/python …`), and nothing for Kilo by default.

### P3-c. Agents in the Doctor (M)

- **Goal:**
  - render agents (state, origin);
  - install agents through a per-assistant transform: drop Kilo-only `mode`/`permission` for Claude;
  - receipts hash the transformed output, so a correctly adapted agent is `up-to-date`.
- **Files:** `orchestration_env.py` (`install_skills` agent branch, `detect_agent_state`), `EnvironmentDoctor.tsx`.
- **Verification:** `~/.claude/agents/kilo-mcp-orchestrator-agent.md` classifies as `up-to-date` (or `outdated-legacy`) instead of `foreign`.

### P3-d. Trigger-conflict generalisation (S)

- **Goal:** the generic/bound pairs come from the bindings (`kilo-mcp/bindings/*.json`), not a hard-coded pair. That covers `executor-contract`/`kilo-mcp-executor-contract`, `conflict-resolver`/`kilo-mcp-conflict-resolver` and `orchestration-metrics`/`kilo-mcp-metrics-analyst`. Advice names every skill that would disappear with a plugin.
- **Files:** `orchestration_env.py` (`:1213-1236`, `resolve_conflicts`).
- **Verification:** the fixture with a plugin-only generic skill shows advice that lists the plugin's other skills.

## Owner decisions surfaced (not Doctor work)

1. Keep both `architect-side@ai-orchestration` and `architect-side@kilo-mcp` enabled in Claude (then acknowledge the trigger conflict), or change the Claude policy to `generic`.
2. Bump the plugin versions (`ai-orchestration` architect-side 0.3.0, `kilo-mcp` architect-side 0.2.2) and update the Claude plugins. Today Claude runs plugin copies 69 and 7 commits old.
3. The untracked `ai-orchestration/.claude/skills`, `.codex/skills`, `.kilo/skills`, `.kilo/agents`, `.kilo/kilo.json` written today at 11:13Z: keep (gitignore or commit) or remove.
4. `gcube-jenkins`, `gcube-security-audit` and `frontend-design` standalone copies carry real extra content vs the plugin. Decide which copy is canonical, and port the extras to `gcube-ai-toolkit` / `agentic-coding-kit` if they are wanted.

## Home-untouched check

A marker was created at the start (`tasks/env-doctor/notes/.marker`). The `find` output at the end is recorded in the session's hand-off message, not in this file.
