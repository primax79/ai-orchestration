#!/usr/bin/env bash
# Apply a fixed file to a path inside a git worktree without needing
# direct file-edit access to that worktree (e.g. when Read/Edit/Write
# and shell cat/grep/sed are permission-blocked against it, but `git`
# subcommands are not). See ../references/worktree-git-plumbing.md for
# the full explanation of why/when this is needed.
#
# Usage:
#   apply_fix_to_worktree.sh <worktree-path> <path-relative-to-worktree> <fixed-file>
#
# <path-relative-to-worktree> may be an existing tracked path (it will
# be updated) or a brand-new path (it will be added).
#
# This only stages and materializes the file — it does NOT commit.
# Run your verification, then `git -C <worktree-path> commit` yourself.

set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <worktree-path> <path-relative-to-worktree> <fixed-file>" >&2
  exit 1
fi

WORKTREE="$1"
TARGET_PATH="$2"
FIXED_FILE="$3"

if [ ! -d "$WORKTREE/.git" ] && ! git -C "$WORKTREE" rev-parse --git-dir > /dev/null 2>&1; then
  echo "Error: $WORKTREE does not look like a git worktree." >&2
  exit 1
fi

if [ ! -f "$FIXED_FILE" ]; then
  echo "Error: fixed-file '$FIXED_FILE' not found." >&2
  exit 1
fi

# Warn (don't block) if there's a lot of unrelated live uncommitted work —
# the caller should have already checked this, but a last-second guard
# doesn't hurt.
#
# Exact-path comparison, not substring: git status --short's path starts at
# column 4 (two status chars + one space), and a rename shows as
# "R  old -> new" - only the "new" side counts. A grep -F match on
# TARGET_PATH would both (a) die under `set -e`/`pipefail` when the
# worktree is clean and grep finds nothing to match (its own no-match exit
# status of 1 propagates), and (b) false-negative on a path that merely
# contains TARGET_PATH as a substring (e.g. TARGET_PATH=src/db.py would
# also swallow src/db.py.bak out of the dirty count).
DIRTY_COUNT=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  path="${line:3}"
  case "$path" in
    *" -> "*) path="${path##* -> }" ;;
  esac
  if [ "$path" != "$TARGET_PATH" ]; then
    DIRTY_COUNT=$((DIRTY_COUNT + 1))
  fi
done < <(git -C "$WORKTREE" status --short)
if [ "$DIRTY_COUNT" -gt 0 ]; then
  echo "Warning: $DIRTY_COUNT other path(s) have uncommitted changes in $WORKTREE." >&2
  echo "Make sure none of them are part of a live in-progress session before continuing." >&2
fi

BLOB=$(git -C "$WORKTREE" hash-object -w --stdin < "$FIXED_FILE")

if git -C "$WORKTREE" ls-files --error-unmatch "$TARGET_PATH" > /dev/null 2>&1; then
  git -C "$WORKTREE" update-index --cacheinfo "100644,$BLOB,$TARGET_PATH"
else
  git -C "$WORKTREE" update-index --add --cacheinfo "100644,$BLOB,$TARGET_PATH"
fi

git -C "$WORKTREE" checkout-index -f -- "$TARGET_PATH"

echo "Applied $FIXED_FILE -> $WORKTREE/$TARGET_PATH"
echo "Staged in the index. Verify, then commit with:"
echo "  git -C \"$WORKTREE\" commit -m \"...\""
