# T019: Diff per singola skill e valutazione della copia canonica per gcube-jenkins, gcube-security-audit, frontend-design

- Data: 2026-10-18
- Task: T019 (Applicare Q005: diff per singola skill delle skill duplicate)
- Contesto: La decisione di Q005 è stata **C (decidere per singola skill)**. Follow-up del report T016 sul Doctor.
- Ambito: Ispezione in sola lettura delle posizioni su disco; diff a livello di file per ogni skill, analisi dell'origine e domande pronte da registrare per l'owner.

---

## Riepilogo esecutivo

| Skill | Stato standalone | Stato plugin attivo | Stato repository sorgente | Natura della divergenza | Azione richiesta | Scelta raccomandata |
| --- | --- | --- | --- | --- | --- | --- |
| **gcube-jenkins** | `~/.kilo/skills/gcube-jenkins` (v1.0.0, 7 file, 25 KB) | `gcube-developer-tools@gcube-ai-toolkit` 0.2.1 (5 file, 24.5 KB) | `gcube-ai-toolkit` branch `skills/security-audit-0.3-d4science-infra` (7 file) | La standalone ha gli esempi in `references/env/`. Nel repository sorgente, `references/env/` esiste localmente ma è stata ignorata da git a causa di `.gitignore:254:ENV/`. | Rimuovere l'esclusione di `references/env/` in `gcube-ai-toolkit`, fare commit, incrementare la versione del plugin, ritirare la copia standalone. | **A** (Plugin canonico, portare i file extra) |
| **gcube-security-audit** | `~/.kilo/skills/gcube-security-audit` + symlink in `~/.claude/skills` (v0.3.0, 21 file, 176 KB) | `gcube-developer-tools@gcube-ai-toolkit` 0.2.1 (v0.1.4, 4 file, 57 KB) | `gcube-ai-toolkit` branch `skills/security-audit-0.3-d4science-infra` (v0.3.0, 21 file) | Ampia: metodologia di audit multi-agente a 2 livelli, 7 template di revisione (`assets/`), 7 guide di riferimento (`references/`), 4 script aggiuntivi, regole affinate in `rules.json` (v0.3.0). Il plugin 0.2.1 contiene lo scanner obsoleto 0.1.4. | Fare merge del branch `skills/security-audit-0.3-d4science-infra` del repository sorgente in `main`, portare il plugin alla 0.3.0, aggiornare il plugin di Claude, rimuovere standalone/symlink. | **A** (Plugin canonico, unire il branch e rilasciare) |
| **frontend-design** | `~/.kilo/skills/frontend-design` (5 file, 26 KB) | `third-party-skills@agentic-coding-kit` 0.1.0 (5 file, 26 KB) | `agentic-coding-kit` (5 file, identici byte per byte alla standalone) | Nessuna differenza semantica rispetto ad `agentic-coding-kit`. Il diff rispetto alla cache del plugin riguarda solo la formattazione YAML multilinea di `description`. Nota: il plugin ufficiale Anthropic (`claude-plugins-official`) ha un prompt alternativo più lungo di 180 righe (9.4 KB). | Dichiarare `third-party-skills@agentic-coding-kit` canonico per questo ramo; mantenere la copia standalone in `~/.kilo/skills` come mirror gestito identico. | **A** (agentic-coding-kit canonico) |

---

## 1. Skill: gcube-jenkins

### 1.1 Inventario delle copie trovate

1. **Standalone (Kilo globale):**
   - **Percorso:** `/Users/Alfredo/.kilo/skills/gcube-jenkins`
   - **Origine:** Installazione standalone in `~/.kilo/skills`
   - **Versione:** `1.0.0` (dichiarata in `SKILL.md`)
   - **Mtime:** `2026-10-10 21:37:36`
   - **File (7 file, ~25 KB):**
     - `SKILL.md` (8,106 byte)
     - `index.json` (313 byte)
     - `references/env/java17.env.example` (341 byte)
     - `references/env/java8.env.example` (332 byte)
     - `scripts/gcube_credentials_check.sh` (2,633 byte, eseguibile)
     - `scripts/gcube_doctor.sh` (10,330 byte, eseguibile)
     - `scripts/jenkins_api.sh` (3,134 byte, eseguibile)

2. **Cache del plugin attivo di Claude (0.2.1):**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.1/skills/gcube-jenkins`
   - **Origine:** Plugin `gcube-developer-tools@gcube-ai-toolkit` versione `0.2.1`
   - **Versione:** `1.0.0` (in `SKILL.md`), release del plugin `0.2.1`
   - **Mtime:** `2026-10-09 09:11:43`
   - **File (5 file, ~24.5 KB):**
     - `SKILL.md` (8,107 byte)
     - `index.json` (313 byte)
     - `scripts/gcube_credentials_check.sh` (2,633 byte)
     - `scripts/gcube_doctor.sh` (10,330 byte)
     - `scripts/jenkins_api.sh` (3,134 byte)
     - *(Nota: la directory `references/` è assente)*

3. **Cache del plugin di Claude (0.2.0 - precedente):**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.0/skills/gcube-jenkins`
   - **Origine:** Installazione precedente del plugin in cache
   - **Mtime:** `2026-10-08 21:26:00`
   - **File:** Identica alla copia in cache 0.2.1 (5 file).

4. **Checkout del marketplace di Claude:**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/marketplaces/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-jenkins`
   - **Origine:** Clone locale del marketplace `gcube-ai-toolkit`
   - **Mtime:** `2026-10-09 09:11:43`
   - **File:** Identica alla copia in cache 0.2.1 (5 file).

5. **Checkout del repository sorgente:**
   - **Percorso:** `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-jenkins`
   - **Origine:** Repository sorgente `gcube-ai-toolkit` (branch attivo `skills/security-audit-0.3-d4science-infra`)
   - **Commit:** `d3e2108d` (2026-10-08 21:24:11: "Skills: add gcube-jenkins...")
   - **Mtime:** `2026-10-08 20:00:00`
   - **File (7 file):**
     - `SKILL.md` (8,107 byte)
     - `index.json` (313 byte)
     - `references/env/java17.env.example` (341 byte) — *non tracciato / ignorato da git*
     - `references/env/java8.env.example` (332 byte) — *non tracciato / ignorato da git*
     - `scripts/gcube_credentials_check.sh` (2,633 byte)
     - `scripts/gcube_doctor.sh` (10,330 byte)
     - `scripts/jenkins_api.sh` (3,134 byte)

6. **Copia standalone di Claude storica / eliminata:**
   - Precedentemente in `/Users/Alfredo/.claude/skills/gcube-jenkins`. Spostata nel cestino in `~/.ai-swissknife/_deleted/skill/gcube-jenkins-2026-10-15T14-53-54-266Z` il 2026-10-15. Conteneva gli stessi 7 file della copia standalone di Kilo.

---

### 1.2 Analisi dei diff

#### Diff 1.1: Standalone vs plugin attivo (0.2.1)

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

- Tutti e tre gli script shell (`gcube_credentials_check.sh`, `gcube_doctor.sh`, `jenkins_api.sh`) sono **identici byte per byte**.
- `index.json` è **identico byte per byte**.
- `SKILL.md`: L'unica differenza è la serializzazione del frontmatter (`metadata: ""` appiattito rispetto alla mappa annidata `metadata:\n  author: ...`).
- File aggiuntivi nella standalone:
  - `references/env/java17.env.example`: template per le credenziali e gli URL degli endpoint di Jenkins Java 17 (`GCUBE_JENKINS_USER`, `GCUBE_JENKINS_TOKEN`, `GCUBE_JENKINS_URL`).
  - `references/env/java8.env.example`: template per le credenziali e gli URL degli endpoint di Jenkins Java 8.

#### Diff 1.2: Standalone vs working tree del repository sorgente

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

- `references/env/` è **già presente** nel working tree del repository sorgente ed è **identica byte per byte** alla copia standalone.
- **Causa radice individuata:** `git check-ignore -v plugins/gcube-developer-tools/skills/gcube-jenkins/references/env/java17.env.example` restituisce:
  `.gitignore:254:ENV/`
  Poiché macOS utilizza un filesystem case-insensitive, la voce `ENV/` del gitignore ha intercettato `references/env/`. Di conseguenza, git ha ignorato `references/` al momento del commit `d3e2108d`, lasciandola non committata. La build e il rilascio del plugin non hanno mai incluso `references/`.

---

### 1.3 Valutazione e raccomandazione di porting

- **Completezza e aggiornamento:** La copia standalone e il working tree del repository sorgente sono più completi rispetto alla release del plugin perché forniscono i file di esempio della configurazione d'ambiente richiesti da `gcube_credentials_check.sh`.
- **Vale la pena fare il porting?** Sì, assolutamente. Di fatto i file sono già scritti nel working tree del repository sorgente; sono stati semplicemente esclusi dal tracciamento git da `.gitignore:254:ENV/`.
- **Passaggi di risoluzione:**
  1. In `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/.gitignore`, aggiungere un'eccezione (ad es. `!plugins/**/references/env/`) o rendere più specifico il pattern `ENV/`.
  2. Mettere in stage e fare commit di `plugins/gcube-developer-tools/skills/gcube-jenkins/references/`.
  3. Incrementare la versione del plugin `gcube-developer-tools`, aggiornare il marketplace e i plugin di Claude.
  4. Ritirare la copia standalone.

---

### 1.4 Domanda pronta da registrare (gcube-jenkins)

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

### 2.1 Inventario delle copie trovate

1. **Standalone (Kilo globale):**
   - **Percorso:** `/Users/Alfredo/.kilo/skills/gcube-security-audit`
   - **Origine:** Installazione standalone in `~/.kilo/skills`
   - **Versione:** `0.3.0` (regole `0.3.0`, script scanner `0.2.0`)
   - **Mtime:** `2026-10-15 14:34:28`
   - **File (21 file, ~176 KB):**
     - `SKILL.md` (13,223 byte, 180 righe)
     - `index.json` (791 byte)
     - `config/rules.json` (30,509 byte)
     - `scripts/security_scan.py` (35,354 byte)
     - `scripts/check_citations.py` (4,139 byte)
     - `scripts/cite_audit.py` (3,635 byte)
     - `scripts/discover_components.py` (9,950 byte)
     - `scripts/make_sandboxes.py` (4,165 byte)
     - `assets/BRIEF.template.md` (7,790 byte)
     - `assets/BRIEF-system.template.md` (5,467 byte)
     - `assets/BRIEF-round2.template.md` (3,235 byte)
     - `assets/COMPARISON.template.md` (1,293 byte)
     - `assets/REFUTATION-BRIEF.template.md` (3,261 byte)
     - `assets/SYSTEM-MODEL.template.md` (2,491 byte)
     - `assets/TEMPLATE-findings.md` (4,094 byte)
     - `references/component-audit.md` (6,875 byte)
     - `references/gcube-profile.md` (8,475 byte)
     - `references/maintainer-rules.md` (7,373 byte)
     - `references/model-evidence.md` (5,939 byte)
     - `references/process-lessons.md` (5,056 byte)
     - `references/rule-tuning-2026-10.md` (8,404 byte)
     - `references/system-audit.md` (4,859 byte)

2. **Symlink standalone (Claude globale):**
   - **Percorso:** `/Users/Alfredo/.claude/skills/gcube-security-audit`
   - **Origine:** Symlink creato il `2026-10-17 19:41` che punta direttamente a `/Users/Alfredo/.kilo/skills/gcube-security-audit`.
   - **File:** Condivide lo stesso identico contenuto della Copia 1.

3. **Cache del plugin attivo di Claude (0.2.1):**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.1/skills/gcube-security-audit`
   - **Origine:** Plugin `gcube-developer-tools@gcube-ai-toolkit` versione `0.2.1`
   - **Versione:** `0.1.4` (in `SKILL.md`), regole `0.1.2`, scanner `0.1.5`
   - **Mtime:** `2026-10-09 09:11:43`
   - **File (4 file, ~57 KB):**
     - `SKILL.md` (4,242 byte, 72 righe)
     - `index.json` (181 byte)
     - `config/rules.json` (23,161 byte)
     - `scripts/security_scan.py` (29,814 byte)

4. **Cache del plugin di Claude (0.2.0 - precedente):**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/cache/gcube-ai-toolkit/gcube-developer-tools/0.2.0/skills/gcube-security-audit`
   - **Origine:** Cache del plugin 0.2.0 (4 file identici alla 0.2.1).

5. **Checkout del marketplace di Claude:**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/marketplaces/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-security-audit`
   - **Origine:** Clone del marketplace di `gcube-ai-toolkit` (4 file identici alla 0.2.1).

6. **Checkout del repository sorgente:**
   - **Percorso:** `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/gcube-developer-tools/skills/gcube-security-audit`
   - **Origine:** Repository sorgente `gcube-ai-toolkit`, branch `skills/security-audit-0.3-d4science-infra`
   - **Commit:** `cb01c9b` (2026-10-14 14:50:41: "gcube-security-audit: cite_audit fixed, model-evidence corrected")
   - **File (21 file, ~176 KB):** Corrisponde esattamente ai 21 file della copia standalone.

---

### 2.2 Analisi dei diff

#### Diff 2.1: Standalone (0.3.0) vs plugin attivo (0.2.1 / 0.1.4)

- **Struttura delle directory:**
  - La standalone ha 21 file distribuiti in 4 sottodirectory (`assets/`, `config/`, `references/`, `scripts/`).
  - Il plugin attivo ha solo 4 file (`SKILL.md`, `index.json`, `config/rules.json`, `scripts/security_scan.py`).
  - L'intera directory `assets/` (7 template) e la directory `references/` (7 guide) sono completamente assenti nel plugin.
  - 4 script (`check_citations.py`, `cite_audit.py`, `discover_components.py`, `make_sandboxes.py`) sono assenti nel plugin.

- **`SKILL.md` (180 righe vs 72 righe):**
  - La standalone v0.3.0 definisce la pipeline completa di audit di sicurezza multi-agente a 2 livelli:
    - **Livello 1 (Componente):** Singolo repository su commit fissato, 3 famiglie di revisori alla cieca, verificatore di confutazione avversaria, verifica delle citazioni.
    - **Livello 2 (Sistema):** Composizione multi-repository, confini di fiducia, flussi di token/identità, raggio d'impatto delle librerie condivise.
    - **Fasi 0–6:** Ambito e pin, pre-scansione deterministica, classificazione per esposizione, revisioni di livello 1, modello di sistema (`SYSTEM-MODEL.md`), revisione di composizione, report e audit delle citazioni (`check_citations.py`).
  - Il plugin v0.1.4 descrive soltanto la pre-scansione deterministica di Fase 1.

- **`config/rules.json` (v0.3.0 vs v0.1.2, +7.3 KB):**
  - Aggiunte 6 regole `AUTH-03` di audit su IAM/token:
    - `AUTH-03.keycloak-client-use`
    - `AUTH-03.oidc-library-use`
    - `AUTH-03.uma-use`
    - `AUTH-03.raw-token-endpoint`
    - `AUTH-03.manual-jwt-parse`
    - `AUTH-03.iam-deps-pom`
  - Aggiunta `SEC-01.default-credential` (password/segreti deboli in file di configurazione/properties).
  - Affinamento delle regole: rese più selettive le 6 regole più rumorose sulla base di 300 occorrenze campionate (`LOG-01.secret-in-log`, `INJ-01.sql-concat`, `SEC-01.hardcoded-credential`, `INJ-02.path-from-input`, `SEC-01.key-material`, `SEC-01.properties-credential`).

- **`scripts/security_scan.py` (v0.2.0 vs v0.1.5, +5.5 KB):**
  - Aggiunto nel motore il supporto per condizioni di precisione:
    `exclude_context_pattern`, `exclude_match_pattern`, `truncate_balanced`, `post_strip`, `non_constant_operand`, `dedupe_by_match`, `max_hits_per_file`, `max_hit_line_length`.
  - Aggiunti gli helper a livello di AST/token `concat_has_variable()`, `_balanced()`, `_skip_literal()`.

#### Diff 2.2: Standalone vs working tree del repository sorgente

- La copia standalone e il branch `skills/security-audit-0.3-d4science-infra` del repository sorgente sono **identici al 100% byte per byte su tutti i 21 file**, ad eccezione delle 3 righe di formattazione del frontmatter in `SKILL.md`:

  ```diff
  -metadata: ""
  -author: Alfredo Oliviero
  -version: 0.3.0
  +metadata:
  +  author: Alfredo Oliviero
  +  version: 0.3.0
  ```

---

### 2.3 Valutazione e raccomandazione di porting

- **Completezza e aggiornamento:** La copia standalone è nettamente più recente e completa. Rappresenta il sistema di audit 0.3.0 pronto per la produzione utilizzato per i principali audit della piattaforma gCube a metà ottobre 2026.
- **Perché la copia del plugin è obsoleta?** Il lavoro è stato committato sul branch `skills/security-audit-0.3-d4science-infra` in `gcube-ai-toolkit`, ma:
  1. Il branch non è mai stato unito in `main`.
  2. `plugins/gcube-developer-tools/.claude-plugin/plugin.json` non è mai stato incrementato oltre la `0.2.1`.
  3. Non è stata pubblicata alcuna release sul marketplace.
- **Valutazione del porting:** Non occorre scrivere alcun codice di porting poiché esiste già nel repository sorgente! L'azione richiesta è un flusso di rilascio: unire il branch, portare `plugin.json` alla `0.3.0`, rilasciare sul marketplace, aggiornare il plugin di Claude e rimuovere la copia standalone/symlink.
- Ritirare la copia standalone senza effettuare questo rilascio distruggerebbe l'intera versione 0.3.0 di `gcube-security-audit`.

---

### 2.4 Domanda pronta da registrare (gcube-security-audit)

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

### 3.1 Inventario delle copie trovate

1. **Standalone (Kilo globale):**
   - **Percorso:** `/Users/Alfredo/.kilo/skills/frontend-design`
   - **Origine:** Installazione standalone in `~/.kilo/skills`
   - **Versione:** Senza versione (corrisponde alla skill di terze parti di `agentic-coding-kit`)
   - **Mtime:** `2026-08-14 14:06:49`
   - **File (5 file, ~26 KB):**
     - `SKILL.md` (4,630 byte, 85 righe)
     - `LICENSE` (10,174 byte)
     - `LICENSE.txt` (10,174 byte)
     - `index.json` (176 byte)
     - `local.patch` (882 byte)

2. **Backup standalone (Kilo old):**
   - **Percorso:** `/Users/Alfredo/.kilo/old/skills/frontend-design`
   - **Origine:** Directory di backup `~/.kilo/old/skills/`
   - **Mtime:** `2026-08-14 14:06:49`
   - **File:** Identica alla Copia 1 (SKILL.md ha 13 byte di differenza dovuti alla quotatura della descrizione).

3. **Cache del plugin attivo di Claude (0.1.0):**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/cache/agentic-coding-kit/third-party-skills/0.1.0/skills/frontend-design`
   - **Origine:** Plugin `third-party-skills@agentic-coding-kit` versione `0.1.0`
   - **Mtime:** `2026-08-07 15:16:49`
   - **File (5 file, ~26 KB):**
     - `SKILL.md` (4,643 byte)
     - `LICENSE` (10,174 byte)
     - `LICENSE.txt` (10,174 byte)
     - `index.json` (176 byte)
     - `local.patch` (882 byte)

4. **Checkout del marketplace di Claude (agentic-coding-kit):**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/marketplaces/agentic-coding-kit/plugins/third-party/skills/frontend-design`
   - **Origine:** Clone del marketplace di `agentic-coding-kit`
   - **Mtime:** `2026-10-17 14:35:00`
   - **File:** Identica al 100% byte per byte alla Copia standalone 1.

5. **Checkout del repository sorgente (agentic-coding-kit):**
   - **Percorso:** `/Users/Alfredo/works/ai-coding-tools/agentic-coding-kit/plugins/third-party/skills/frontend-design`
   - **Origine:** Repository sorgente `agentic-coding-kit`
   - **Commit:** `2485fa6`
   - **Mtime:** dal `2026-08-05` al `2026-08-13`
   - **File:** Identica al 100% byte per byte alla Copia standalone 1.

6. **Marketplace dei plugin ufficiali Anthropic:**
   - **Percorso:** `/Users/Alfredo/.claude/plugins/marketplaces/claude-plugins-official/plugins/frontend-design/skills/frontend-design`
   - **Origine:** Repository dei plugin ufficiali Anthropic (`claude-plugins-official`)
   - **Mtime:** `2026-10-16 15:35:00`
   - **File (2 file, ~19.5 KB):**
     - `SKILL.md` (9,390 byte, 180 righe)
     - `LICENSE.txt` (10,174 byte)

7. **Copia standalone di Claude storica / eliminata:**
   - Precedentemente in `/Users/Alfredo/.claude/skills/frontend-design`. Spostata nel cestino in `~/.ai-swissknife/_deleted/skill/frontend-design-2026-10-15T14-54-39-599Z` il 2026-10-15. Conteneva gli stessi file della Copia 3.

---

### 3.2 Analisi dei diff

#### Diff 3.1: Standalone vs cache del plugin attivo (0.1.0)

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

- **Corpo Markdown:** Identico al 100% byte per byte.
- **File di supporto:** `LICENSE`, `LICENSE.txt`, `index.json`, `local.patch` sono identici al 100% byte per byte.
- **L'unica differenza:** Stringa YAML multilinea ripiegata `>-` rispetto alla stringa su singola riga tra virgolette in `description`.

#### Diff 3.2: Standalone vs repository sorgente (`agentic-coding-kit`)

- L'output di `diff -ru` è **completamente vuoto** (0 byte di differenza).
- La copia standalone in `~/.kilo/skills/frontend-design` è una copia esatta byte per byte di `agentic-coding-kit/plugins/third-party/skills/frontend-design`.

#### Diff 3.3: `agentic-coding-kit` vs `claude-plugins-official` (Anthropic upstream)

- `claude-plugins-official` contiene il prompt completo di Anthropic di 180 righe (9.4 KB):
  - Si concentra sulla figura di un design lead di uno studio di progettazione.
  - Sezioni approfondite sui principi di design: scala tipografica, lunghezza delle righe (<80 caratteri), evitare i trattamenti predefiniti generici (accento su singole parole, etichette tutte in maiuscolo, indicatori numerati arbitrari `01/02/03`), aderenza al dominio tematico e checklist di autovalutazione.
- `agentic-coding-kit` contiene un prompt condensato di 85 righe (4.6 KB):
  - Mantiene le indicazioni estetiche fondamentali (distintività, scelte dei font, animazioni, evitare i cliché dei gradienti viola su schede bianche).
  - Include `local.patch` che lo rende neutrale rispetto al modello/agente:
    `-Remember: Claude is capable of extraordinary creative work.`
    `+Remember: The agent is capable of extraordinary creative work.`

---

### 3.3 Valutazione e raccomandazione di porting

- **C'è divergenza tra standalone e plugin?** No. La copia standalone in `~/.kilo/skills` e il plugin in `agentic-coding-kit` sono già identici. Non ci sono contenuti extra nella standalone da portare.
- **Perché il Doctor la segnala?**
  Il rilevamento dei conflitti del Doctor ha segnalato `frontend-design` perché Claude carica `third-party-skills@agentic-coding-kit` mentre esisteva una copia standalone (e Kilo carica tuttora `~/.kilo/skills/frontend-design`).
  Secondo la regola P1-c del Doctor (normalizzazione del frontmatter), il diff tra la standalone e la cache del plugin si normalizza a zero.
- **Raccomandazione:**
  Mantenere `third-party-skills@agentic-coding-kit` come sorgente canonica. La copia in `~/.kilo/skills/` è semplicemente la copia locale per Kilo di quella stessa identica skill.

---

### 3.4 Domanda pronta da registrare (frontend-design)

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

## 4. Sintesi e risultati trasversali

1. **Collisione del gitignore in `gcube-ai-toolkit`:**
   `.gitignore:254` contiene `ENV/`. Su macOS (filesystem case-insensitive), questo impedisce a `references/env/` di essere tracciata da git. Ciò spiega perché a `gcube-jenkins` mancasse `references/` nella release del plugin.
2. **Branch di rilascio non uniti:**
   Il codice sorgente di `gcube-security-audit` v0.3.0 è completo e committato in `gcube-ai-toolkit` sul branch `skills/security-audit-0.3-d4science-infra`, ma non è stato unito in `main` e `plugin.json` non è mai stato incrementato di versione. Il gestore dei plugin di Claude ha quindi continuato a eseguire il codice obsoleto della 0.1.4.
3. **Differenze di serializzazione YAML:**
   Le copie standalone scritte dai primi installer appiattiscono le mappe annidate (ad es. `metadata: ""` seguito da `author:`). Normalizzare lo YAML del frontmatter durante il confronto dei conflitti nel Doctor risolve le differenze puramente formali a parità di corpo.
4. **Ecosistemi di assistenti differenti:**
   Claude utilizza pacchetti di plugin (`installed_plugins.json`), mentre Kilo scansiona direttamente `~/.kilo/skills/` e `~/.claude/skills/`. Affinché Kilo possa accedere alle skill senza dipendere dai percorsi della cache dei plugin di Claude, sono necessarie copie standalone in `~/.kilo/skills/` (o symlink).
