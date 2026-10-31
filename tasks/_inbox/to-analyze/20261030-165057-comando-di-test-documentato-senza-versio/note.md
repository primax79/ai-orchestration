# N087 Comando di test documentato senza versione di Python: su Mac uvx sceglie 3.10 e 194 test falliscono

- id: N087
- title: Comando di test documentato senza versione di Python: su Mac uvx sceglie 3.10 e 194 test falliscono
- kind: bug
- status: ready
- created: 2026-10-30T16:50:57.876371+00:00
- author: ai-coding-tools
- about: -
- produced: -
- processed-by: -
- short: Comando test documentato senza

2026-10-30: 'uvx --quiet pytest -q -p no:cacheprovider ./scripts ./plugins' (comando usato da executor, chain e brief) sul Mac risolve Python 3.10.16; il codice richiede 3.11+ (tomllib) e la suite da' 194 failed / 1 error tutti per RuntimeError 'Python 3.11+ (stdlib tomllib) is required'. Sull'hub uvx usa un Python piu' recente e la suite e' verde (754 passed). Proposta: fissare la versione minima nel comando documentato (uvx --python 3.12 ...) in CONTEXT.md, nel brief degli executor e nella chain, e/o dichiarare requires-python >= 3.11 in un pyproject/pytest.ini cosi' che uvx la rispetti; far fallire subito conftest con un messaggio chiaro se Python < 3.11.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (2965604)
- Date: 2026-10-30 16:50:57 UTC
