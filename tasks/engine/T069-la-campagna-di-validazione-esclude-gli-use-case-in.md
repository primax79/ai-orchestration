# T069 La campagna di validazione esclude gli use case in bozza

- id: T069
- title: La campagna di validazione esclude gli use case in bozza
- category: engine
- priority: P2
- priority-reason: Una campagna ha segnato 39/41 use case come failing in git-code-rag, letto dal proprietario come prodotto rotto
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-144044-use-cases-campaign-validates-draft-use-c/note.md
- paths: -
- handoff: Read tasks/engine/T069-la-campagna-di-validazione-esclude-gli-use-case-in.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: ai-coding-tools
- short: Campagna senza bozze

## Goal

run_validation_campaign (tasks_engine.py ~7265) says 'Execute all active use cases' but iterates every discovered use case, drafts included; record_use_case_validation then sets status failing on a fail. In git-code-rag (2026-10-25 17:00 UTC) a campaign turned 10 post-v0 draft use cases (deliberately unimplemented, probe exits 1) into 'failing', and ran probes of v0 use cases before their tests existed: 39/41 failing, which the owner read as a broken product. Expected: the campaign skips status draft (or reports them as 'not in scope' without changing status), and reports UNTESTED rather than FAIL when the probe's files do not exist yet would also help. Also consider not running a campaign automatically while linked tasks are still open.

## Steps

- [ ] run_validation_campaign esegue solo gli use case active; le bozze compaiono nel report come 'fuori ambito' senza cambiare stato
- [ ] Un probe che non può girare (test non ancora esistenti) è UNTESTED, non failing

## Verification

- Test: campagna su 2 active + 2 draft: solo le active cambiano last-verdict; report con sezione 'fuori ambito'
