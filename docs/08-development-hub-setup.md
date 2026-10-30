# Development hub: setup and daily use

How to run AI-agent development on an always-on Linux machine (the **hub**), with workstations (Mac, laptops) used as clients. This is the manual pattern in production use while the automated version (initiative 19: host identity, screen run backend, hub registry, CLI console) lands in `ai-orch`.

- **Audience:** developers who want the same setup.
- **Background:** spec `tasks/specs/multi-machine-development-architecture.md` and its review (`…review-2026-10-29.md`, §10 holds the decisions).
- **Scripts:** [`contrib/hub/`](../contrib/hub/).

## 1. Roles of the machines

- **The hub** runs everything that develops code: agent executors, builds, test suites, integration merges and commits. It stays on, so work continues while workstations are off. Shared services (knowledge/RAG servers, `ai-orch` UI) run once, there.
- **A workstation** is for writing specifications, interactive development, and as a console. It reaches the hub's services over an ssh tunnel (`LocalForward`). Nothing in the flow depends on the workstation being on.
- **Constraint:** the setup must never slow project work. Every piece is opt-in, the manual flow (plain `screen` + `kilo run`) keeps working, and a blocked migration step means "keep working as before and report it".

## 2. One-time hub setup

### 2.1 Host hardening (owner, sudo)

- **Firewall:** default deny inbound; allow only ssh. **Docker-published ports bypass ufw**, so filter them in the `DOCKER-USER` chain. Everything agent- or console-related binds to `127.0.0.1`.
- **Check from outside:** `nc -z <hub-ip> <port>` for every port you care about. Only 22 should answer.
- **Shell:** keep the distribution default (bash). Agents must never change the login shell or install system packages.
- **Record the state** in a host record. Ours is `status/alf_ubuntu-host.md` in the owner's workspace. Every change to the host gets a line in it: date, what, who, and how it was verified.

### 2.2 Agents user (owner, sudo)

Agents run with `--auto`, so they execute commands without asking. They must not run as your user if your user is in `docker` (which is root-equivalent) or can read production secrets.

1. Read [`contrib/hub/setup-agent-user.sh`](../contrib/hub/setup-agent-user.sh), then run it **on the hub**. From a workstation, use the hub's absolute path, because `~` would be expanded by the workstation's shell:
   ```sh
   ssh -t <hub> sudo EXPECTED_HOST=<hub hostname> bash /home/<you>/…/contrib/hub/setup-agent-user.sh
   ```
   The script:
   - creates `kilo` with no sudo, no docker and a locked password;
   - creates `/srv/agents` (mode 2750; you join the `kilo` group);
   - copies your authorized ssh keys so you can attach;
   - ends with isolation checks, which must all pass.
2. As the agents user, install user-level tools (the script prints these steps):
   - uv;
   - the Kilo CLI (`curl -fsSL https://kilo.ai/cli/install | bash` or `npm install -g @kilocode/cli`);
   - add `~/.kilo/bin` to `~/.profile`, because the installer only edits `~/.bashrc`, which non-interactive shells skip;
   - `kilo auth login` with the agents user's own credentials. A Gemini API key can be piped from your local keystore instead of being typed.
3. As your own user, run `git config --global --add safe.directory '/srv/agents/*'`. Without it, git refuses repositories owned by the agents user, and you could not fetch the executors' branches.
4. Clone each repository the agents work on into `/srv/agents/<repo>`, working as the agents user.

**Check:**
- `ssh kilo@<hub> 'bash -lc "kilo --version; uv --version"'`
- `ssh kilo@<hub> 'docker ps'` is denied.
- From `/srv/agents/<repo>`, a one-line `kilo run` answers.

### 2.3 GitHub/Gitea access for your user

- Verify the forge's ssh host key fingerprint against the published one before adding it to `known_hosts`.
- Integration branches and `main` are pushed by **your** user from the hub. The agents user only clones over https and never pushes.

## 3. Running executors

Everything below runs as the agents user on the hub, in `/srv/agents/<repo>`. Copy the scripts from `contrib/hub/` and keep per-run files in `<repo>/.tmp/executors/`, which must be git-excluded.

### 3.1 Task briefs

- `brief-common.md`: the executor contract.
  - Work only in the worktree; never change the host.
  - Stage explicit paths; one commit per task; no push or merge.
  - Do not edit task states or the index.
  - Run the tests (full suite only on the hub).
  - Write a mandatory Final Report into the branch.
- One short file per task: which task (its Goal and Verification are the contract) and where to write the report.

### 3.2 Launch, watch, attach

```sh
contrib/hub/launch.sh <slug> google/gemini-4-argon .tmp/executors/task-<id>.md [base-branch]
screen -ls                                                # sessions: agent-<repo>-<slug>
tail -f .tmp/executors/<slug>.log                         # live output
ssh -t kilo@<hub> screen -x agent-<repo>-<slug>           # attach from a workstation; Ctrl-a d detaches without stopping it
```

- **What `launch.sh` sets up:**
  - one git worktree per task under `<parent>/.worktrees/<repo>/<slug>`, on branch `kilo/<slug>`;
  - one screen session `agent-<repo>-<slug>`;
  - `SHELL=/bin/bash` forced, because Kilo runs its tool commands with `$SHELL`;
  - the log in `<slug>.log`, and the exit code appended to `<slug>.status`.
- **Model choice:** `google/gemini-3.8-flash` for routine work, `google/gemini-4-argon` for complex or risky work.

### 3.3 Unattended chaining

`contrib/hub/chain.sh` runs in its own screen session and needs no LLM. For each executor that exits, it:

1. requires a commit and a clean worktree;
2. runs the suite, tolerating only failures already in the baseline log;
3. merges into the integration branch, never main;
4. re-runs the suite after the merge, and undoes the merge if it is red;
5. launches the tasks whose prerequisites are merged.

The task table is `.tmp/executors/chain.tasks`:

```text
# slug             model                      brief            report path in the branch                 prereqs
19.1-config-lookup google/gemini-4-argon      task-19.1.md     tasks/<…>/notes/19.1-final-report.md      -
19.2-doctor        google/gemini-4-argon      task-19.2.md     tasks/<…>/notes/19.2-final-report.md      19.1-config-lookup
```

Make the baseline once: run the suite on `main` and save it as `.tmp/executors/baseline-tests.log`.

### 3.4 Verification and integration

- **"Merged by the chain" only means the tests are green.** Every task still needs an **independent verification**: another engine (we use Codex) reviews the diff against the task's Verification section.
- **When the verifier bounces a task**, send the findings back to the same branch: `contrib/hub/bounce.sh <slug> <model> <brief> <findings.md>`. The chain re-merges the branch when the run ends.
- **Publishing**, done by your user on the hub, when the tasks are verified:
  1. `git fetch /srv/agents/<repo> integration` (or push the integration branch to the forge);
  2. merge the integration branch into `main`;
  3. run the suite once;
  4. push.

## 4. Lessons learned (2026-10-29/30)

- **Single master:** never let two checkouts push into each other (`receive.denyCurrentBranch=updateInstead`). Use one reference repository (bare repo on the hub or the forge), `pull --ff-only` everywhere, and commits on the hub.
- **`~` in ssh commands** is expanded locally. Use absolute hub paths, or quote the whole remote command.
- **Multiplexed ssh** (`ControlMaster`) keeps the login shell and environment of the first connection. After changing them, run `ssh -O exit <hub>`.
- **Python for tests:** `uvx` may pick an old interpreter on a workstation (3.10 on macOS here, which made 194 tests fail). Always pin it: `uvx --python 3.12 …`.
- **macOS** ships GNU screen 4.00 (no `-Logfile`). The screen backend must detect it (ai-orchestration task 19.18).
- **Executors with `--auto` will change the host if allowed:** one installed `bun` globally, and a session installed zsh and changed the login shell. The agents user and the brief's "never change the host" rule exist because of this.
- **Test isolation:** tests must never write to the real `~/.config` or real projects (ai-orchestration T089: an autouse fixture plus a guard).
- **Waiting:** do not block on long suites from a workstation. The full suite runs on the hub; workstations run only targeted tests.
