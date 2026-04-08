#!/usr/bin/env bash
# Install ClawX git hooks into the local .git/hooks/ directory.
#
# Run once after cloning the repo:
#   bash scripts/install-hooks.sh

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_SRC="$REPO_ROOT/scripts/pre-commit-hook.sh"
HOOK_DEST="$REPO_ROOT/.git/hooks/pre-commit"

if [ ! -f "$HOOK_SRC" ]; then
    echo "❌ Source hook not found: $HOOK_SRC"
    exit 1
fi

mkdir -p "$REPO_ROOT/.git/hooks"
cp "$HOOK_SRC" "$HOOK_DEST"
chmod +x "$HOOK_DEST"

echo "✅ Pre-commit hook installed: $HOOK_DEST"
echo ""
echo "From now on, every 'git commit' will run the test suite first."
echo "If tests fail, the commit will be aborted."
echo ""
echo "To uninstall:  rm $HOOK_DEST"
echo "To bypass:     git commit --no-verify"
