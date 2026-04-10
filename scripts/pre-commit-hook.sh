#!/usr/bin/env bash
# ClawX pre-commit hook: runs the test suite before allowing a commit.
#
# Install with:  bash scripts/install-hooks.sh
# Bypass with:   git commit --no-verify  (not recommended)

set -u
cd "$(git rev-parse --show-toplevel)"

echo "[pre-commit] Running ClawX test suite..."

python3 -m pytest tests/ -q
result=$?

if [ $result -ne 0 ]; then
    echo ""
    echo "[pre-commit] ❌ Tests failed — commit aborted"
    echo "[pre-commit] Fix the failing tests, then commit again."
    echo "[pre-commit] To bypass (not recommended): git commit --no-verify"
    exit 1
fi

echo "[pre-commit] ✅ Tests passed — proceeding with commit"
exit 0
