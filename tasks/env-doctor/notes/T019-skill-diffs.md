# T019: Per-Skill Diff and Canon Assessment for gcube-jenkins, gcube-security-audit, frontend-design

- Date: 2026-10-18
- Task: T019 (Apply Q005: per-skill diff of duplicated skills)
- Context: Q005 decision was **C (decide per skill)**. Follow-up to T016 Doctor report.
- Scope: Read-only inspection of disk locations; per-skill file-level diffs, origin analysis, and ready-to-file questions for the owner.

---

## Executive Summary

| Skill | Standalone Status | Active Plugin Status | Source Repo Status | Divergence Nature | Action Required | Recommended Choice |
| --- | --- | --- | --- | --- | --- | --- |
| **gcube-jenkins** | `~/.kilo/skills/gcube-jenkins` (v1.0.0, 7 files, 25 KB) | `gcube-developer-tools@gcube-ai-toolkit` 0.2.1 (5 files, 24.5 KB) | `gcube-ai-toolkit` branch `skills/security-audit-0.3-d4science-infra` (7 files) | Standalone has `references/env/` examples. In source repo, `references/env/` exists locally but was ignored by git due to `.gitignore:254:ENV/`. | Un-ignore `references/env/` in `gcube-ai-toolkit`, commit, bump plugin, retire standalone copy. | **A** (Plugin canonical, port extras) |
| **gcube-security-audit** | `~/.kilo/skills/gcube-security-audit` + symlink in `~/.claude/skills` (v0.3.0, 21 files, 176 KB) | `gcube-developer-tools@gcube-ai-toolkit` 0.2.1 (v0.1.4, 4 files, 57 KB) | `gcube-ai-toolkit` branch `skills/security-audit-0.3-d4science-infra` (v0.3.0, 21 files) | Massive: 2-level multi-agent audit methodology, 7 review templates (`assets/`), 7 reference guides (`references/`), 4 additional scripts, tightened rules in `rules.json` (v0.3.0). Plugin 0.2.1 has obsolete 0.1.4 scanner. | Merge source repo branch `skills/security-audit-0.3-d4science-infra` to `main`, bump plugin to 0.3.0, update Claude plugin, remove standalone/symlink. | **A** (Plugin canonical, merge branch & release) |
| **frontend-design** | `~/.kilo/skills/frontend-design` (5 files, 26 KB) | `third-party-skills@agentic-coding-kit` 0.1.0 (5 files, 26 KB) | `agentic-coding-kit` (5 files, byte-identical to standalone) | Zero semantic diff vs `agentic-coding-kit`. The diff vs plugin cache is only YAML multiline formatting of `description`. Note: official Anthropic plugin (`claude-plugins-official`) has an alternative, longer 180-line prompt (9.4 KB). | Declare `third-party-skills@agentic-coding-kit` canonical for this track; maintain standalone copy in `~/.kilo/skills` as an identical managed mirror. | **A** (agentic-coding-kit canonical) |

---

## 1. Skill: gcube-jenkins

### 1.1 Inventory of Copies Found

1. **Standalone (Kilo global):**
   - **Path:** `/Users/Alfredo/.kilo/skills/gcube-jenkins`
   - **Origin:** Standalone installation in `~/.kilo/skills`
   - **Version:** `1.0.0` (declared in `SKILL.md`)
   - **Mtime:** `2026-10-10 21:37:36`
   - **Files (7 files, ~25 KB):**
     - `SKILL.md` (8,106 bytes)
     - `index.json` (313 bytes)
     - `references/env/java17.env.example` (341 bytes)
     - `references/env/java8.env.example` (332 bytes)
     - `scripts/gcube_credentials_check.sh` (2,633 bytes, executable)
     - `scripts/gcube_doctor.sh` (10,330 bytes, executable)
     - `scripts/jenkins_api.sh` (3,134 bytes, executable)

2. **Claude Active Plugin Cache (0.2.1):**
   - **Path:** `/Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.1/skills/gcube-jenkins`
   - **Origin:** Plugin `gcube-developer-tools@gcube-ai-toolkit` version `0.2.1`
   - **Version:** `1.0.0` (in `SKILL.md`), plugin release `0.2.1`
   - **Mtime:** `2026-10-09 09:11:43`
   - **Files (5 files, ~24.5 KB):**
     - `SKILL.md` (8,107 bytes)
     - `index.json` (313 bytes)
     - `scripts/gcube_credentials_check.sh` (2,633 bytes)
     - `scripts/gcube_doctor.sh` (10,330 bytes)
     - `scripts/jenkins_api.sh` (3,134 bytes)
     - *(Note: `references/` directory is missing)*

3. **Claude Plugin Cache (0.2.0 - older):**
   - **Path:** `/Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.0/skills/gcube-jenkins`
   - **Origin:** Cached earlier plugin install
   - **Mtime:** `2026-10-08 21:26:00`
   - **Files:** Identical to 0.2.1 cache copy (5 files).

4. **Claude Marketplace Checkout:**
   - **Path:** `/Users/Alfredo/.claude/plugins/marketplaces/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-jenkins`
   - **Origin:** Local clone of marketplace `gcube-ai-toolkit`
   - **Mtime:** `2026-10-09 09:11:43`
   - **Files:** Identical to 0.2.1 cache copy (5 files).

5. **Source Repository Checkout:**
   - **Path:** `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-jenkins`
   - **Origin:** Source repo `gcube-ai-toolkit` (active branch `skills/security-audit-0.3-d4science-infra`)
   - **Commit:** `d3e2108d` (2026-10-08 21:24:11: "Skills: add gcube-jenkins...")
   - **Mtime:** `2026-10-08 20:00:00`
   - **Files (7 files):**
     - `SKILL.md` (8,107 bytes)
     - `index.json` (313 bytes)
     - `references/env/java17.env.example` (341 bytes) — *untracked / ignored by git*
     - `references/env/java8.env.example` (332 bytes) — *untracked / ignored by git*
     - `scripts/gcube_credentials_check.sh` (2,633 bytes)
     - `scripts/gcube_doctor.sh` (10,330 bytes)
     - `scripts/jenkins_api.sh` (3,134 bytes)

6. **Historical / Deleted Standalone Claude Copy:**
   - Path previously at `/Users/Alfredo/.claude/skills/gcube-jenkins`. Trashed to `~/.ai-swissknife/_deleted/skill/gcube-jenkins-2026-10-15T14-53-54-266Z` on 2026-10-15. Contained the same 7 files as the Kilo standalone copy.

---

### 1.2 Diff Analysis

#### Diff 1.1: Standalone vs Active Plugin (0.2.1)

```diff
diff -ru /Users/Alfredo/.kilo/skills/gcube-jenkins/SKILL.md /Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.1/skills/gcube-jenkins/SKILL.md
--- /Users/Alfredo/.kilo/skills/gcube-jenkins/SKILL.md 2026-10-10 21:37:36
+++ /Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.1/skills/gcube-jenkins/SKILL.md 2026-10-09 09:11:43
@@ -1,9 +1,9 @@
 ---
 name: gcube-jenkins
 description: "Work with the two gCube Jenkins servers (Java 8 line and Java 17 line): read jobs, builds and logs through the REST API, check or change the Gitea webhook of a repository, find which job builds which repository, and apply the conventions of the development lines. Use when a push, a release or a merge to master may trigger a build, when a library or portlet must be built or published to Nexus, when a job is missing or red, or before moving a repository from one Java line to the other."
-metadata: ""
-author: Alfredo Oliviero
-version: 1.0.0
+metadata:
+  author: Alfredo Oliviero
+  version: 1.0.0
 argument-hint: "<jobs|list|job|log|config|hooks|lines> [java8|java17] [name]"
 ---
 
Only in /Users/Alfredo/.kilo/skills/gcube-jenkins: references
Only in /Users/Alfredo/.kilo/skills/gcube-jenkins/references: env
Only in /Users/Alfredo/.kilo/skills/gcube-jenkins/references/env: java17.env.example
Only in /Users/Alfredo/.kilo/skills/gcube-jenkins/references/env: java8.env.example
```

- All three shell scripts (`gcube_credentials_check.sh`, `gcube_doctor.sh`, `jenkins_api.sh`) are **byte-identical**.
- `index.json` is **byte-identical**.
- `SKILL.md`: The only difference is frontmatter serialization (flattened `metadata: ""` vs nested map `metadata:\n  author: ...`).
- Extra files in standalone:
  - `references/env/java17.env.example`: template for Jenkins Java 17 credentials and endpoint URLs (`GCUBE_JENKINS_USER`, `GCUBE_JENKINS_TOKEN`, `GCUBE_JENKINS_URL`).
  - `references/env/java8.env.example`: template for Jenkins Java 8 credentials and endpoint URLs.

#### Diff 1.2: Standalone vs Source Repo Working Tree

```diff
diff -ru /Users/Alfredo/.kilo/skills/gcube-jenkins /Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-jenkins
--- /Users/Alfredo/.kilo/skills/gcube-jenkins/SKILL.md 2026-10-10 21:37:36
+++ /Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-jenkins/SKILL.md 2026-10-08 21:22:25
@@ -1,9 +1,9 @@
 ---
 name: gcube-jenkins
 description: "Work with the two gCube Jenkins servers (Java 8 line and Java 17 line): read jobs, builds and logs through the REST API, check or change the Gitea webhook of a repository, find which job builds which repository, and apply the conventions of the development lines. Use when a push, a release or a merge to master may trigger a build, when a library or portlet must be built or published to Nexus, when a job is missing or red, or before moving a repository from one Java line to the other."
-metadata: ""
-author: Alfredo Oliviero
-version: 1.0.0
+metadata:
+  author: Alfredo Oliviero
+  version: 1.0.0
 argument-hint: "<jobs|list|job|log|config|hooks|lines> [java8|java17] [name]"
 ---
```

- `references/env/` is **already present** in the source repo working tree and is **byte-identical** to the standalone copy.
- **Root cause discovered:** `git check-ignore -v plugins/gcube-developer-tools/skills/gcube-jenkins/references/env/java17.env.example` returns:
  `.gitignore:254:ENV/`
  Because macOS has a case-insensitive filesystem, the gitignore entry `ENV/` matched `references/env/`. Consequently, git ignored `references/` when committing `d3e2108d`, leaving it uncommitted. The plugin build/release never included `references/`.

---

### 1.3 Assessment & Porting Recommendation

- **Completeness & recency:** The standalone copy and the source repository working tree are more complete than the plugin release because they provide the example environment configuration files required by `gcube_credentials_check.sh`.
- **Is porting worth it?** Yes, absolutely. In fact, the files are already written in the source repository working tree; they were merely blocked from git tracking by `.gitignore:254:ENV/`.
- **Remediation steps:**
  1. In `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/.gitignore`, add an exception (e.g. `!plugins/**/references/env/`) or make the `ENV/` pattern more specific.
  2. Stage and commit `plugins/gcube-developer-tools/skills/gcube-jenkins/references/`.
  3. Bump `gcube-developer-tools` plugin version, update marketplace and Claude plugins.
  4. Retire the standalone copy.

---

### 1.4 Ready-to-File Question (gcube-jenkins)

```text
question: For gcube-jenkins, which copy should be canonical: the gcube-developer-tools plugin or the standalone copy?
context: The standalone copy in ~/.kilo/skills/gcube-jenkins includes references/env/{java17.env.example, java8.env.example} which are missing from the Claude plugin copy (gcube-developer-tools@gcube-ai-toolkit 0.2.1). In the source repo (gcube-ai-toolkit), these reference files exist in the working tree but were ignored by git because .gitignore contains 'ENV/' (which matches case-insensitively on macOS). The scripts and SKILL.md are otherwise identical.
options:
  A=Plugin canonical (port references and fix gitignore): Whitelist references/env in gcube-ai-toolkit/.gitignore, commit the references, bump plugin version to 0.2.2/0.3.0, update Claude plugin, and retire the standalone copy.
  B=Standalone canonical: Keep the standalone copy in ~/.kilo/skills and acknowledge the duplicate/divergence in Doctor.
  C=Plugin canonical without references: Declare plugin 0.2.1 canonical as-is, discard references/env, and remove standalone copy.
recommended: A
```

---

## 2. Skill: gcube-security-audit

### 2.1 Inventory of Copies Found

1. **Standalone (Kilo global):**
   - **Path:** `/Users/Alfredo/.kilo/skills/gcube-security-audit`
   - **Origin:** Standalone installation in `~/.kilo/skills`
   - **Version:** `0.3.0` (rules `0.3.0`, scanner script `0.2.0`)
   - **Mtime:** `2026-10-15 14:34:28`
   - **Files (21 files, ~176 KB):**
     - `SKILL.md` (13,223 bytes, 180 lines)
     - `index.json` (791 bytes)
     - `config/rules.json` (30,509 bytes)
     - `scripts/security_scan.py` (35,354 bytes)
     - `scripts/check_citations.py` (4,139 bytes)
     - `scripts/cite_audit.py` (3,635 bytes)
     - `scripts/discover_components.py` (9,950 bytes)
     - `scripts/make_sandboxes.py` (4,165 bytes)
     - `assets/BRIEF.template.md` (7,790 bytes)
     - `assets/BRIEF-system.template.md` (5,467 bytes)
     - `assets/BRIEF-round2.template.md` (3,235 bytes)
     - `assets/COMPARISON.template.md` (1,293 bytes)
     - `assets/REFUTATION-BRIEF.template.md` (3,261 bytes)
     - `assets/SYSTEM-MODEL.template.md` (2,491 bytes)
     - `assets/TEMPLATE-findings.md` (4,094 bytes)
     - `references/component-audit.md` (6,875 bytes)
     - `references/gcube-profile.md` (8,475 bytes)
     - `references/maintainer-rules.md` (7,373 bytes)
     - `references/model-evidence.md` (5,939 bytes)
     - `references/process-lessons.md` (5,056 bytes)
     - `references/rule-tuning-2026-10.md` (8,404 bytes)
     - `references/system-audit.md` (4,859 bytes)

2. **Standalone Symlink (Claude global):**
   - **Path:** `/Users/Alfredo/.claude/skills/gcube-security-audit`
   - **Origin:** Symlink created `2026-10-17 19:41` pointing directly to `/Users/Alfredo/.kilo/skills/gcube-security-audit`.
   - **Files:** Shares identical content with Copy 1.

3. **Claude Active Plugin Cache (0.2.1):**
   - **Path:** `/Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.1/skills/gcube-security-audit`
   - **Origin:** Plugin `gcube-developer-tools@gcube-ai-toolkit` version `0.2.1`
   - **Version:** `0.1.4` (in `SKILL.md`), rules `0.1.2`, scanner `0.1.5`
   - **Mtime:** `2026-10-09 09:11:43`
   - **Files (4 files, ~57 KB):**
     - `SKILL.md` (4,242 bytes, 72 lines)
     - `index.json` (181 bytes)
     - `config/rules.json` (23,161 bytes)
     - `scripts/security_scan.py` (29,814 bytes)

4. **Claude Plugin Cache (0.2.0 - older):**
   - **Path:** `/Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.0/skills/gcube-security-audit`
   - **Origin:** Plugin cache 0.2.0 (identical 4 files as 0.2.1).

5. **Claude Marketplace Checkout:**
   - **Path:** `/Users/Alfredo/.claude/plugins/marketplaces/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-security-audit`
   - **Origin:** Marketplace clone of `gcube-ai-toolkit` (identical 4 files as 0.2.1).

6. **Source Repository Checkout:**
   - **Path:** `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-security-audit`
   - **Origin:** Source repo `gcube-ai-toolkit`, branch `skills/security-audit-0.3-d4science-infra`
   - **Commit:** `cb01c9b` (2026-10-14 14:50:41: "gcube-security-audit: cite_audit fixed, model-evidence corrected")
   - **Files (21 files, ~176 KB):** Exactly matches the 21 files of the standalone copy.

---

### 2.2 Diff Analysis

#### Diff 2.1: Standalone (0.3.0) vs Active Plugin (0.2.1 / 0.1.4)

- **Directory structure:**
  - Standalone has 21 files across 4 subdirectories (`assets/`, `config/`, `references/`, `scripts/`).
  - Active plugin has only 4 files (`SKILL.md`, `index.json`, `config/rules.json`, `scripts/security_scan.py`).
  - Entire `assets/` directory (7 templates) and `references/` directory (7 guides) are completely missing in the plugin.
  - 4 scripts (`check_citations.py`, `cite_audit.py`, `discover_components.py`, `make_sandboxes.py`) are missing in the plugin.

- **`SKILL.md` (180 lines vs 72 lines):**
  - Standalone v0.3.0 defines the complete multi-agent 2-level security audit pipeline:
    - **Level 1 (Component):** Single repo pinned commit, 3 blind reviewer families, adversarial refutation verifier, citation verification.
    - **Level 2 (System):** Multi-repo composition, trust boundaries, token/identity flows, shared-library blast radius.
    - **Phases 0–6:** Scope & pin, deterministic pre-scan, tiering by exposure, level-1 reviews, system model (`SYSTEM-MODEL.md`), composition review, report & citation audit (`check_citations.py`).
  - Plugin v0.1.4 only describes Phase 1 deterministic pre-scan.

- **`config/rules.json` (v0.3.0 vs v0.1.2, +7.3 KB):**
  - Added 6 `AUTH-03` IAM/token audit rules:
    - `AUTH-03.keycloak-client-use`
    - `AUTH-03.oidc-library-use`
    - `AUTH-03.uma-use`
    - `AUTH-03.raw-token-endpoint`
    - `AUTH-03.manual-jwt-parse`
    - `AUTH-03.iam-deps-pom`
  - Added `SEC-01.default-credential` (weak passwords/secrets in config/props).
  - Rule tuning: Tightened the 6 noisiest rules based on 300 sampled hits (`LOG-01.secret-in-log`, `INJ-01.sql-concat`, `SEC-01.hardcoded-credential`, `INJ-02.path-from-input`, `SEC-01.key-material`, `SEC-01.properties-credential`).

- **`scripts/security_scan.py` (v0.2.0 vs v0.1.5, +5.5 KB):**
  - Added engine support for precision conditions:
    `exclude_context_pattern`, `exclude_match_pattern`, `truncate_balanced`, `post_strip`, `non_constant_operand`, `dedupe_by_match`, `max_hits_per_file`, `max_hit_line_length`.
  - Added AST/token-level helpers `concat_has_variable()`, `_balanced()`, `_skip_literal()`.

#### Diff 2.2: Standalone vs Source Repo Working Tree

- Standalone copy and source repo branch `skills/security-audit-0.3-d4science-infra` are **100% byte-identical across all 21 files**, except for the 3-line frontmatter formatting in `SKILL.md`:

  ```diff
  -metadata: ""
  -author: Alfredo Oliviero
  -version: 0.3.0
  +metadata:
  +  author: Alfredo Oliviero
  +  version: 0.3.0
  ```

---

### 2.3 Assessment & Porting Recommendation

- **Completeness & recency:** The standalone copy is vastly newer and more complete. It represents the production-ready 0.3.0 audit system used for major gCube platform audits in mid-October 2026.
- **Why is the plugin copy stale?** The work was committed to the branch `skills/security-audit-0.3-d4science-infra` in `gcube-ai-toolkit`, but:
  1. The branch was never merged into `main`.
  2. `plugins/gcube-developer-tools/.claude-plugin/plugin.json` was never bumped past `0.2.1`.
  3. No release was published to the marketplace.
- **Porting evaluation:** No porting code needs to be written because it already exists in the source repository! The required action is a release workflow: merge the branch, bump `plugin.json` to `0.3.0`, release to the marketplace, update the Claude plugin, and remove the standalone copy/symlink.
- Retiring the standalone copy without doing this release would destroy all of `gcube-security-audit` v0.3.0.

---

### 2.4 Ready-to-File Question (gcube-security-audit)

```text
question: For gcube-security-audit, which copy should be canonical: the gcube-developer-tools plugin or the standalone 0.3.0 copy?
context: The standalone copy in ~/.kilo/skills/gcube-security-audit (and ~/.claude symlink) is version 0.3.0 (21 files, 176 KB, including a 2-level audit methodology, 7 review templates in assets/, 7 reference guides, tightened rules in config/rules.json, and 4 new scripts). The active Claude plugin (gcube-developer-tools@gcube-ai-toolkit 0.2.1) has an obsolete version 0.1.4 (4 files, 57 KB). All 0.3.0 files are already committed in the source repository gcube-ai-toolkit on branch 'skills/security-audit-0.3-d4science-infra', but that branch was never merged to main and plugin.json was never bumped.
options:
  A=Plugin canonical (merge branch, release 0.3.0, update plugin): Merge skills/security-audit-0.3-d4science-infra to main in gcube-ai-toolkit, bump plugin to 0.3.0, update Claude plugin, and remove standalone copy / symlink.
  B=Standalone canonical: Keep the 0.3.0 standalone copy and symlink; leave the plugin at 0.1.4 and acknowledge the duplicate.
  C=Revert to plugin 0.1.4: Discard 0.3.0 methodology, assets, references, and scripts; keep only the 0.1.4 plugin pre-scanner.
recommended: A
```

---

## 3. Skill: frontend-design

### 3.1 Inventory of Copies Found

1. **Standalone (Kilo global):**
   - **Path:** `/Users/Alfredo/.kilo/skills/frontend-design`
   - **Origin:** Standalone installation in `~/.kilo/skills`
   - **Version:** Unversioned (corresponds to `agentic-coding-kit` third-party skill)
   - **Mtime:** `2026-08-14 14:06:49`
   - **Files (5 files, ~26 KB):**
     - `SKILL.md` (4,630 bytes, 85 lines)
     - `LICENSE` (10,174 bytes)
     - `LICENSE.txt` (10,174 bytes)
     - `index.json` (176 bytes)
     - `local.patch` (882 bytes)

2. **Standalone Backup (Kilo old):**
   - **Path:** `/Users/Alfredo/.kilo/old/skills/frontend-design`
   - **Origin:** Backup directory `~/.kilo/old/skills/`
   - **Mtime:** `2026-08-14 14:06:49`
   - **Files:** Identical to Copy 1 (SKILL.md has 13 bytes difference due to description quotation).

3. **Claude Active Plugin Cache (0.1.0):**
   - **Path:** `/Users/Alfredo/.claude/plugins/cache/agentic-coding-kit/third-party-skills/0.1.0/skills/frontend-design`
   - **Origin:** Plugin `third-party-skills@agentic-coding-kit` version `0.1.0`
   - **Mtime:** `2026-08-07 15:16:49`
   - **Files (5 files, ~26 KB):**
     - `SKILL.md` (4,643 bytes)
     - `LICENSE` (10,174 bytes)
     - `LICENSE.txt` (10,174 bytes)
     - `index.json` (176 bytes)
     - `local.patch` (882 bytes)

4. **Claude Marketplace Checkout (agentic-coding-kit):**
   - **Path:** `/Users/Alfredo/.claude/plugins/marketplaces/agentic-coding-kit/plugins/third-party/skills/frontend-design`
   - **Origin:** Marketplace clone of `agentic-coding-kit`
   - **Mtime:** `2026-10-17 14:35:00`
   - **Files:** 100% byte-identical to Standalone Copy 1.

5. **Source Repository Checkout (agentic-coding-kit):**
   - **Path:** `/Users/Alfredo/works/ai-coding-tools/agentic-coding-kit/plugins/third-party/skills/frontend-design`
   - **Origin:** Source repo `agentic-coding-kit`
   - **Commit:** `2485fa6`
   - **Mtime:** `2026-08-05` to `2026-08-13`
   - **Files:** 100% byte-identical to Standalone Copy 1.

6. **Anthropic Official Plugin Marketplace:**
   - **Path:** `/Users/Alfredo/.claude/plugins/marketplaces/claude-plugins-official/plugins/frontend-design/skills/frontend-design`
   - **Origin:** Anthropic official plugin repository (`claude-plugins-official`)
   - **Mtime:** `2026-10-16 15:35:00`
   - **Files (2 files, ~19.5 KB):**
     - `SKILL.md` (9,390 bytes, 180 lines)
     - `LICENSE.txt` (10,174 bytes)

7. **Historical / Deleted Standalone Claude Copy:**
   - Path previously at `/Users/Alfredo/.claude/skills/frontend-design`. Trashed to `~/.ai-swissknife/_deleted/skill/frontend-design-2026-10-15T14-54-39-599Z` on 2026-10-15. Contained the same files as Copy 3.

---

### 3.2 Diff Analysis

#### Diff 3.1: Standalone vs Active Plugin Cache (0.1.0)

```diff
diff -ru /Users/Alfredo/.kilo/skills/frontend-design/SKILL.md /Users/Alfredo/.claude/plugins/cache/agentic-coding-kit/third-party-skills/0.1.0/skills/frontend-design/SKILL.md
--- /Users/Alfredo/.kilo/skills/frontend-design/SKILL.md 2026-08-14 14:06:49
+++ /Users/Alfredo/.claude/plugins/cache/agentic-coding-kit/third-party-skills/0.1.0/skills/frontend-design/SKILL.md 2026-08-07 15:16:49
@@ -1,6 +1,12 @@
 ---
 name: frontend-design
-description: "Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications (examples include websites, landing pages, dashboards, React components, HTML/CSS layouts, or when styling/beautifying any web UI). Generates creative, polished code and UI design that avoids generic AI aesthetics."
+description: >-
+  Create distinctive, production-grade frontend interfaces with high design
+  quality. Use this skill when the user asks to build web components, pages,
+  artifacts, posters, or applications (examples include websites, landing pages,
+  dashboards, React components, HTML/CSS layouts, or when styling/beautifying
+  any web UI). Generates creative, polished code and UI design that avoids
+  generic AI aesthetics.
 license: Complete terms in LICENSE.txt
 metadata:
   category: development
```

- **Markdown body:** 100% byte-identical.
- **Supporting files:** `LICENSE`, `LICENSE.txt`, `index.json`, `local.patch` are 100% byte-identical.
- **The only diff:** YAML multiline folded string `>-` vs single-line quoted string in `description`.

#### Diff 3.2: Standalone vs Source Repo (`agentic-coding-kit`)

- `diff -ru` output is **completely empty** (0 bytes diff).
- The standalone copy in `~/.kilo/skills/frontend-design` is an exact byte-for-byte copy of `agentic-coding-kit/plugins/third-party/skills/frontend-design`.

#### Diff 3.3: `agentic-coding-kit` vs `claude-plugins-official` (Upstream Anthropic)

- `claude-plugins-official` contains Anthropic's full 180-line prompt (9.4 KB):
  - Focuses on the persona of a design studio design lead.
  - In-depth sections on design principles: typography scale, line lengths (<80 chars), avoiding generic default treatments (accenting single words, all-caps labels, arbitrary numbered markers `01/02/03`), subject matter grounding, and self-critique checklists.
- `agentic-coding-kit` contains a condensed 85-line prompt (4.6 KB):
  - Retains core aesthetic guidance (distinctiveness, font choices, animations, avoiding purple gradients/white cards clichés).
  - Includes `local.patch` making it model/agent-neutral:
    `-Remember: Claude is capable of extraordinary creative work.`
    `+Remember: The agent is capable of extraordinary creative work.`

---

### 3.3 Assessment & Porting Recommendation

- **Is there divergence between standalone and plugin?** No. Standalone in `~/.kilo/skills` and plugin in `agentic-coding-kit` are already identical. There are no standalone extras to port.
- **Why does Doctor report this?**
  Doctor's conflict detection flagged `frontend-design` because Claude loads `third-party-skills@agentic-coding-kit` while a standalone copy existed (and Kilo still loads `~/.kilo/skills/frontend-design`).
  Under Doctor rule P1-c (frontmatter normalization), the diff between standalone and plugin cache normalizes to zero.
- **Recommendation:**
  Keep `third-party-skills@agentic-coding-kit` as the canonical source. The copy in `~/.kilo/skills/` is simply Kilo's local copy of that exact skill.

---

### 3.4 Ready-to-File Question (frontend-design)

```text
question: For frontend-design, which copy should be canonical: third-party-skills@agentic-coding-kit or claude-plugins-official?
context: The standalone copy in ~/.kilo/skills/frontend-design is 100% byte-identical to the source repo and marketplace copy of third-party-skills@agentic-coding-kit (a condensed 85-line, 4.6 KB version patched with local.patch for general agents). The diff vs plugin cache 0.1.0 is only YAML description formatting. Standalone and agentic-coding-kit plugin copies have zero real divergence. However, Anthropic's official marketplace (claude-plugins-official) has a different, longer 180-line (9.4 KB) prompt emphasizing design studio identity and typography.
options:
  A=agentic-coding-kit canonical: Keep third-party-skills@agentic-coding-kit as the canonical source, keep ~/.kilo/skills copy in sync with it, and acknowledge or auto-resolve in Doctor.
  B=Switch to claude-plugins-official: Adopt Anthropic's full 180-line prompt in agentic-coding-kit (with agent patching), update plugin and standalone copies.
  C=Retire standalone: Remove ~/.kilo/skills copy and rely solely on Claude plugin (Kilo will not have it unless configured).
recommended: A
```

---

## 4. Synthesis and Cross-Cutting Findings

1. **Gitignore collision in `gcube-ai-toolkit`:**
   `.gitignore:254` has `ENV/`. On macOS (case-insensitive filesystem), this prevents `references/env/` from being tracked by git. This explains why `gcube-jenkins` lacked `references/` in its plugin release.
2. **Unmerged release branches:**
   The source code for `gcube-security-audit` v0.3.0 is complete and committed in `gcube-ai-toolkit` on branch `skills/security-audit-0.3-d4science-infra`, but has not been merged to `main`, and `plugin.json` was never bumped. Claude's plugin manager has therefore been running stale 0.1.4 code.
3. **YAML Serialization differences:**
   Standalone copies written by early installers flatten nested maps (e.g. `metadata: ""` followed by `author:`). Normalizing frontmatter YAML during Doctor conflict comparison resolves cosmetic differences for identical bodies.
4. **Different Assistant Ecosystems:**
   Claude uses plugin packages (`installed_plugins.json`), whereas Kilo directly scans `~/.kilo/skills/` and `~/.claude/skills/`. For Kilo to access skills without relying on Claude plugin cache paths, it requires standalone copies in `~/.kilo/skills/` (or symlinks).
