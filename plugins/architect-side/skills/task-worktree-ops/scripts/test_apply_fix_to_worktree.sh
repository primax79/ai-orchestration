#!/usr/bin/env bash
# Regression test for apply_fix_to_worktree.sh, in particular the clean-worktree
# case that used to die under `set -e`/`pipefail` (grep finding no dirty paths
# to exclude exits 1, which used to propagate and abort the script - see the
# DIRTY_COUNT comment in the script itself) and the substring false-negative
# on a TARGET_PATH that's a prefix of another untracked file (e.g. .bak).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/apply_fix_to_worktree.sh"
TMP="$(mktemp -d)"
REPO="$TMP/repo"
mkdir -p "$REPO"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }

# --- setup: a small repo with one committed file. Fixed-content files live
# outside the repo dir, or they'd show up as untracked and pollute the very
# dirty-count check this test is exercising. ---
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t.com
git -C "$REPO" config user.name t
mkdir -p "$REPO/src"
echo "old" > "$REPO/src/db.py"
git -C "$REPO" -c commit.gpgsign=false add src/db.py
git -C "$REPO" -c commit.gpgsign=false commit -qm init

echo "new" > "$TMP/fixed.txt"

echo "=== test 1: clean worktree must not abort ==="
"$SCRIPT" "$REPO" src/db.py "$TMP/fixed.txt" > /dev/null \
  || fail "script exited non-zero on a clean worktree"
[ "$(cat "$REPO/src/db.py")" = "new" ] || fail "content wasn't applied"
echo "ok"

echo "=== test 2: an untracked file sharing TARGET_PATH as a prefix must not be hidden from the dirty count ==="
git -C "$REPO" -c commit.gpgsign=false commit -qam checkpoint
echo "backup" > "$REPO/src/db.py.bak"
echo "new2" > "$TMP/fixed2.txt"
OUTPUT="$("$SCRIPT" "$REPO" src/db.py "$TMP/fixed2.txt" 2>&1)"
echo "$OUTPUT" | grep -q "Warning: 1 other path" \
  || fail "expected a dirty-count warning for src/db.py.bak, got: $OUTPUT"
echo "ok"

echo
echo "All tests passed."
