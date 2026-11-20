# N097 kilo_implement: Kilo writes into the server's PWD, not working_directory

- id: N097
- title: kilo_implement: Kilo writes into the server's PWD, not working_directory
- kind: bug
- status: ready
- created: 2026-11-20T10:27:28.097018+00:00
- author: ai-coding-tools session (Claude Opus 5.5)
- about: kilo-mcp, server.py _run_kilo, kilo_implement
- produced: -
- processed-by: -
- short: kilo_implement ignores cwd

Found 2026-11-20 during the live check of the new `variant` parameter (kilo-mcp branch models/gemini-4-policy).

Repro: start the server code from directory A (here the kilo-mcp worktree), call `kilo_implement(working_directory=B, background=False, model="google/gemini-4-hydrogen", variant="low", task_instructions="Create b.txt containing ok")`. B is a separate git repo. Result: the Final Report says success, the task record says `working_directory: B`, but the Kilo log shows `Write A/b.txt`; B has no b.txt.

Likely cause: the subprocess gets `cwd=B` but inherits `PWD=A` in `env`; Kilo (Bun) resolves its project directory from `PWD` (server.py never sets `PWD`). Not caused by the variant change (pre-existing).

Impact: any dispatch where the server process PWD differs from working_directory, including worktree isolation, may edit the wrong tree. Check whether the MCP launch normally leaves PWD unset (which would explain why it has not shown up), and whether the background path is affected too.

Fix to evaluate: set `env["PWD"] = cwd` for every `kilo run` spawn (foreground, background, queue runner), or pass Kilo its directory explicitly if `kilo run` has such a flag; add a test that asserts the env PWD equals the working directory.
