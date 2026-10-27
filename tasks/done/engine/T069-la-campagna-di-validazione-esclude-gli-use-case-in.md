# T069 La campagna di validazione esclude gli use case in bozza

- id: T069
- title: La campagna di validazione esclude gli use case in bozza
- category: engine
- priority: P2
- priority-reason: Una campagna ha segnato 39/41 use case come failing in git-code-rag, letto dal proprietario come prodotto rotto
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-144044-use-cases-campaign-validates-draft-use-c/note.md
- paths: -
- handoff: Read tasks/engine/T069-la-campagna-di-validazione-esclude-gli-use-case-in.md, do the open steps, run the Verification, update the task and the registry.
- verifier: claude:ai-coding-tools
- verify-by: ai-coding-tools
- short: Campagna senza bozze

## Goal

run_validation_campaign (tasks_engine.py ~7265) says 'Execute all active use cases' but iterates every discovered use case, drafts included; record_use_case_validation then sets status failing on a fail. In git-code-rag (2026-10-25 17:00 UTC) a campaign turned 10 post-v0 draft use cases (deliberately unimplemented, probe exits 1) into 'failing', and ran probes of v0 use cases before their tests existed: 39/41 failing, which the owner read as a broken product. Expected: the campaign skips status draft (or reports them as 'not in scope' without changing status), and reports UNTESTED rather than FAIL when the probe's files do not exist yet would also help. Also consider not running a campaign automatically while linked tasks are still open.

## Steps

- [x] run_validation_campaign esegue solo gli use case active (e verified/failing/partial, cioè non draft o deprecated); le bozze compaiono nel report sotto 'Out of scope (draft)' senza che stato e last-verdict vengano toccati
- [x] Un probe che non può girare per cause esterne al prodotto (exit 127 command not found, file o directory di test inesistenti, timeout) è registrato come UNTESTED con la motivazione, e NON imposta lo stato a failing

## Verification

- Test specifici T069 eseguiti con successo in `test_tasks_engine.py`:
  - `test_t069_campaign_skips_drafts_and_untested_is_not_failing`: campagna con 2 active (1 pass, 1 fail) + 2 draft + 1 active con comando inesistente (`nonexistent-cmd`). Risultato: solo le active vengono eseguite (totale testati 3, 1 pass, 1 fail, 1 untested, 2 out of scope). Lo use case con comando inesistente rimane con status `active` e `last-verdict: untested`. I due draft rimangono con status `draft` e last-verdict invariato; compaiono nel report sotto la sezione 'Out of scope (draft)'.
  - `test_t069_probe_missing_test_file_and_timeout_recorded_as_untested`: verifica diretta che probe con file di test mancante (es. pytest su file inesistente) o probe andato in timeout vengano registrati con verdetto `untested` mantenendo lo stato `active` (senza passare a `failing`).
- Test suite completa passata: `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/` (243 superati su 243).

## Log

- 2026-10-27, claude:ai-coding-tools: state `verified` -> `done` — verified by ai-coding-tools
- 2026-10-27, claude:ai-coding-tools: state `delivered` -> `verified` — OK on a scratch clone of git-code-rag with architect-side 0.8.3, campaign --timeout 15: the 9 draft use cases listed under 'Out of scope (draft)' and their files untouched (git diff empty); missing test file (UC005) and timeout (UC006, plus 5 slow pytest probes over 15 s) recorded as untested with status unchanged; a real failure (UC007 'false') recorded as fail/failing and as a regression; report and summary count Passed 24, Failed 1, Untested 7, Out of scope 9
- 2026-10-27, kilo: state `open` -> `delivered` — la campagna esclude gli use case draft e deprecated; i probe falliti per cause esterne registrano untested senza impostare failing
