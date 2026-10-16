# T011 render-agents-md: render rules that match the actual orchestrator/executor topology

- id: T011
- title: render-agents-md: render rules that match the actual orchestrator/executor topology
- category: methodology
- priority: P1
- priority-reason: An applied block steers every future session; a wrong block (wrong orchestrator, foreign tools, contradicting model rules) silently misleads agents
- next-up: yes
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: ../../status/agents-md-generated-block-2026-10-16.md in the ai-coding-tools workspace (block found applied without explanation on 2026-10-16, reviewed and removed)
- paths: plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py
- handoff: Read tasks/methodology/T011-render-agents-md-topology.md, do the open steps, run the Verification, update the task and tasks/00-INDEX.md.

## Goal

The block that `render-agents-md` writes into a workspace `AGENTS.md` matches the workspace's real topology. It never prescribes tools or models that the orchestrating session cannot use.

A block applied to `ai-coding-tools/AGENTS.md` on 2026-10-16 had four problems:

- It declared `primary_orchestrator = "kilo"` taken from the global defaults, although the workspace has no project config and is in fact orchestrated by Claude delegating to Kilo over MCP.
- Its Rule 3 prescribed Kilo-native tools (`agent_manager`, `task`).
- Its Rule 4 listed Kilo models (`google/gemini-4-argon`) that the owner's rule (Kilo always `google/gemini-3.8-flash`) contradicts and that kilo-mcp does not offer.
- It introduced a strict "no implementation in the main session" rule that the owner never approved.

## Steps

1. **Topology-aware rendering.** The isolation and delegation tools depend on the pair (orchestrator, executor).
   - Same framework: the orchestrator's native tools.
   - Different frameworks: the MCP binding's tools (for example `kilo_implement(isolation="worktree")` when Claude orchestrates and Kilo executes; `claude-mcp` tools in the opposite direction).
   - The tool names come from the tool tables in config (`native_*_tool`, `mcp_server`, `mcp_implement_tool`), never from hard-coded Kilo text.
2. **No silent defaults.** When the workspace has no project config, `--apply` refuses and names the routing it would use; `--allow-global-routing` forces it. `--diff` shows the same warning.
3. **Models only from the effective config.** Before rendering, validate each listed model id against the tool's catalog when that tool can list one (for example `kilo models`). Unknown ids produce a warning in `--diff` and a refusal on `--apply`, unless `--allow-unknown-models` is given.
4. **Opinionated rules are opt-in.** Rule 1 ("keep the main session free") is rendered only when the config sets `[agents_md] strict_main_session = true`. The default is a softer wording.

## Verification

- Unit tests render the block for three pairs: claude→kilo, kilo→kilo, codex→kilo.
  - The claude→kilo rendering names `kilo_implement`, not `agent_manager`.
  - The kilo→kilo rendering names `agent_manager`/`task`.
- `--apply` refuses on a workspace with no project config.
- `--diff` on `/Users/Alfredo/works/ai-coding-tools` (read-only) shows the routing warning.
- Nothing is applied to any real workspace.

## Result

Delivered implementation of Steps 1–4 in `orchestration_config.py` with accompanying tests:
- **Topology-aware rendering:** Pair mechanisms and skills are derived dynamically from effective config tool tables (`native_*_tool`, `mcp_server`, `mcp_implement_tool`, `mcp_wait_tool`). Tested for claude→kilo, kilo→kilo, and codex→kilo pairs.
- **No silent defaults:** Workspaces lacking project config cause `--apply` to refuse and state the fallback routing unless `--allow-global-routing` is passed; `--diff` includes the routing warning in `warnings`.
- **Model catalog validation:** Listed model IDs for Kilo are verified against `kilo models` (with a 20 s timeout and in-memory caching), refusing on `--apply` unless `--allow-unknown-models` is provided; skipped validation for Claude and Codex is surfaced in warnings.
- **Opt-in strict rules:** Rule 1 defaults to a softer architectural focus and only renders the strict prohibition on main-session implementation when `strict_main_session = true` is explicitly configured.
