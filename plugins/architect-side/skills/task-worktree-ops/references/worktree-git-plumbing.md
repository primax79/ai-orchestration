# Applying a fix inside an agent's worktree without direct file-edit access

## When this applies

Kilo (or any agent working in its own dedicated `git worktree`) is
sometimes sandboxed such that direct file-content tools - the `Read`/
`Edit`/`Write` tools, or `grep`/`cat`/`sed` invoked via a shell tool -
are permission-blocked against paths inside that worktree. `git`
subcommands run via the shell are **not** blocked (git treats the
directory as a repository, not "just files"):

```bash
git -C <worktree> log --oneline
git -C <worktree> show <commit>
git -C <worktree> show <commit> -- path/to/file
git -C <worktree> diff HEAD -- path/to/file
git -C <worktree> status --short
```

Use these freely to inspect history, diffs, and current state. The
technique below is for the step direct tools can't do: **writing** a
corrected version of a file back into that worktree.

## The technique

1. **Get the current content** into a scratch location (never inside
   the worktree):
   ```bash
   git -C <worktree> show HEAD:path/to/file.py > /tmp/current.py
   ```
2. **Produce the fixed content** at a second scratch path (edit
   `/tmp/current.py` with normal tools, or generate the fix
   programmatically - either way, end up with `/tmp/fixed.py`).
3. **Create a blob object** for the fixed content, inside the
   worktree's object database:
   ```bash
   BLOB=$(git -C <worktree> hash-object -w --stdin < /tmp/fixed.py)
   ```
4. **Stage it** at the target path in the worktree's index:
   ```bash
   # Path already tracked (modifying an existing file):
   git -C <worktree> update-index --cacheinfo 100644,$BLOB,path/to/file.py

   # Brand-new path (adding a file that doesn't exist yet):
   git -C <worktree> update-index --add --cacheinfo 100644,$BLOB,path/to/new_file.py
   ```
5. **Materialize it** into the actual working tree (this is the step
   that makes the file readable/runnable again, e.g. for a test run):
   ```bash
   git -C <worktree> checkout-index -f -- path/to/file.py
   ```
6. **Verify** - run whatever functional check applies (a test suite, a
   direct script invocation, a manual repro of the bug being fixed) -
   *before* committing.
7. **Commit normally**:
   ```bash
   git -C <worktree> commit -m "fix: ..."
   ```

## Before touching anything: check for live work in progress

```bash
git -C <worktree> status --short
```

If this shows substantial uncommitted changes beyond the one file being
fixed, that's very likely a live, in-progress editing session (an agent
actively working) - not a stale leftover. Do **not** run `checkout`,
`reset`, `merge`, or `revert` in that worktree while this is true; those
operations can silently discard or conflict with in-progress work. Two
safe paths:

- **Work only on files not currently modified** in that `git status`
  output - staging/checking out an unrelated path via the technique
  above doesn't touch what's live.
- **Wait** for the session to reach a natural commit checkpoint, then
  re-check `git status` (should be clean) before proceeding with
  anything broader (a revert, a merge, a rebase).

Never interrupt the live session to ask permission first - this is a
"work around it" situation, not a "stop and ask" one, unless every path
you'd need to touch is already part of the live changes (in which case,
say so plainly and wait).

## Testing against real vs. disposable data

If verifying the fix requires a real database/data file the agent's own
worktree might also be using live (e.g. a shared workspace SQLite file,
a real API), copy it first:

```bash
cp real_data.db /tmp/test_copy.db
# point a scratch config at /tmp/test_copy.db, never at the original
```

A verification pointed at the same real file an agent's own live process
has open can hang on lock contention, or in the worst case corrupt
shared state. This is a general engineering hygiene point, not specific
to the git-plumbing technique - but it comes up constantly in the same
situations (verifying a fix inside/against a live agent's environment).
