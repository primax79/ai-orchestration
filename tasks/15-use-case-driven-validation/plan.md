# 15 - Use-Case Driven Specification, Task Definition & Product Validation

> **Derived from spec:** [`../specs/use-case-management-and-ai-validation.md`](../specs/use-case-management-and-ai-validation.md)  
> **Status:** `open` (2026-10-17)  
> **Owner Requirement:** Integrate Use Cases as the foundational driver for task specifications, acceptance criteria, and autonomous AI product validation campaigns.

## Goal

Provide end-to-end support for **Use Cases (`tasks/use-cases/UC###-<slug>.md`)**:
1. Top-down: Use Cases drive task `## Goal` and `## Verification` acceptance criteria.
2. Bottom-up: Implemented tasks link back to Use Cases (`- linked-tasks: ...`).
3. Autonomous AI Validation: The operator can trigger AI testing of single Use Cases or run **Product Validation Campaigns** across the whole system, with automatic regression detection, audit logging, and 1-click emergent task generation from detected gaps.
4. Visual Management: Web UI and VS Code Extension view for managing Use Cases, inspecting product readiness scores, and launching validations.

## Non-Goals

- Replacing low-level unit test frameworks (pytest, vitest). Use Cases test end-to-end scenarios and user journeys.
- Storing test runs in external proprietary databases; all Use Cases and audit logs live in Git Markdown files.

---

## Tasks (One Task = One Commit)

### 15.1 - Engine & Data Model (`tasks/use-cases/`, Parser, Validator, `- use-cases:` Task Header)
- **Status:** open
- **Profile:** `deep-reasoning`
- **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `tasks/specs/task-and-state-model.md`
- **Goal:**
  - Add `use-cases` to `RESERVED_DIRS`.
  - Add `use-cases` to `OPTIONAL_EXTENSION_FIELDS` in task headers (`- use-cases: UC001, UC003`).
  - Implement `discover_use_cases(tasks_dir)` parsing `UC###` files (id, title, actor, status, priority, linked_tasks, verification_type, last_tested, last_verdict, scenario, verification_command, acceptance_criteria, validation_log).
  - Implement `create_or_update_use_case` and `record_use_case_validation`.
  - Expose `./bin/ai-orch use-cases list | show | create | record-audit`.
  - Write unit tests in `test_tasks_engine.py`.
- **Verification:** `pytest test_tasks_engine.py` passes 100%.

### 15.2 - Top-Down Skill Integration (`task-spec-authoring` & `task-pipeline`)
- **Status:** open
- **Profile:** `deep-reasoning`
- **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-spec-authoring/SKILL.md`, `plugins/architect-side/skills/task-pipeline/SKILL.md`, `plugins/architect-side/skills/task-pipeline/references/template.md`
- **Goal:**
  - Instruct the Architect in `task-spec-authoring` to anchor task specifications and `## Verification` acceptance criteria directly to the project's Use Cases (`tasks/use-cases/UC*.md`).
  - Update `task-pipeline` skill to document the bidirectional flow: Use Cases ⇄ Specs ⇄ Tasks ⇄ Validation.
  - Update templates and regenerate generic & bound skills.
- **Verification:** `python3 scripts/regenerate_generic_skills.py --check` and `python3 scripts/generate_skill_indices.py` pass.

### 15.3 - Autonomous AI Validation Runner (`ai-orch use-cases validate UC###`)
- **Status:** open
- **Profile:** `deep-reasoning`
- **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`
- **Goal:**
  - Add run mode `validate-use-case`: assembles the prompt containing the Use Case scenario, acceptance criteria, and codebase routes/tools.
  - Instructs the AI agent to execute the verification command (or inspect routes) and emit an ````ai-orch-validation```` block.
  - Parses the verdict (`PASS` | `PARTIAL` | `FAIL`), updates `last-tested` and `last-verdict` on the Use Case file, and appends the structured report to `## AI Validation Log`.
- **Verification:** Unit tests with stub agent executing validation on a sample Use Case.

### 15.4 - Product-Level Validation Campaign Runner (`ai-orch use-cases campaign`)
- **Status:** open
- **Profile:** `deep-reasoning`
- **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `bin/ai-orch`
- **Goal:**
  - Implement campaign runner that iterates through all active Use Cases (or a filtered actor/tag subset).
  - Detects regressions: flags Use Cases that previously passed and now fail.
  - Generates a timestamped Product Validation Report in `tasks/reports/validation-campaign-<timestamp>.md` with overall readiness score (% verified).
- **Verification:** CLI test running a campaign on sample Use Cases fixture.

### 15.5 - Backend REST & WebSocket API Endpoints
- **Status:** open
- **Profile:** `bulk-execution`
- **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:**
  - Expose `GET /api/use-cases`, `POST /api/use-cases`, `GET /api/use-cases/{id}`, `PUT /api/use-cases/{id}`, `POST /api/use-cases/{id}/validate`, `POST /api/use-cases/campaign`.
  - Push live WebSocket events (`use_case_updated`, `validation_completed`).
- **Verification:** Unit tests in `backend/test_server.py` covering all Use Case endpoints.

### 15.6 - Web UI & VS Code Webview: Use Cases Dashboard & AI Runner (Tab: `Use Cases & Validation`)
- **Status:** open
- **Profile:** `bulk-execution`
- **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/components/Navbar.tsx`, `frontend/src/components/UseCasesManager.tsx`, `frontend/src/components/UseCaseDetailModal.tsx`
- **Goal:**
  - Add top-level Tab in Navbar: **`Use Cases & Validation`**.
  - KPI summary: Total Use Cases, Product Readiness Score (% verified), Failing, Draft.
  - Filterable Grid / Table of Use Cases with live status badges.
  - "New Use Case" modal.
  - "Validate with AI" button on each card and "Run Full Product Campaign" button.
  - Use Case Detail Modal: displays scenario steps, linked tasks with live states, verification command, expandable AI Validation History, and 1-click "Create Task from Gap" when failing/partial.
- **Verification:** `npm run build` succeeds and renders cleanly in browser.

### 15.7 - VS Code Sidebar TreeView (`aiOrchestration.useCasesView`)
- **Status:** open
- **Profile:** `bulk-execution`
- **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `package.json`, `src/views/use-cases-tree-provider.ts`, `src/extension.ts`
- **Goal:**
  - Add `aiOrchestration.useCasesView` in the VS Code sidebar under the AI Orchestration container.
  - Displays Use Cases grouped by actor/status with pass/fail/draft icons.
  - Click opens the Use Case Markdown file; inline button triggers "Validate with AI".
  - Bundle updated `dist-webview/` and package VSIX.
- **Verification:** `npm run compile` and VSIX package pass.
