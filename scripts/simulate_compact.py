#!/usr/bin/env python3
"""
Simulate a Claude Code auto-compact event for manual CompactWatcher testing.

Usage:
    python3 scripts/simulate_compact.py [--project-dir /path/to/project]

What it does:
  1. Resolves the sessions dir for the given project (or the ClawX repo root).
  2. Creates a fake session .jsonl file if none exists.
  3. Appends a single ``compact_boundary`` line to the newest .jsonl.
  4. A running ClawX with CompactWatcher will notice the append within ~2s,
     inject the AGENTS.md re-read, and (if configured) send a TG notification.

Use this to manually verify the full wire-up end-to-end without waiting for
a real ~90% context fill.
"""
import argparse
import json
import sys
import uuid as uuid_mod
from datetime import datetime, timezone
from pathlib import Path

# Make `import clawx` work when running this script directly
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import clawx  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir",
        default=str(REPO_ROOT),
        help="Project dir whose sessions to append to (default: ClawX repo)",
    )
    parser.add_argument(
        "--pre-tokens",
        type=int,
        default=188_063,
        help="Fake preTokens value (default: 188063 ~= 94%%)",
    )
    args = parser.parse_args()

    sessions_dir = clawx.CompactWatcher.resolve_sessions_dir_from_project(
        args.project_dir
    )
    sessions_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if existing:
        target = existing[-1]
        print(f"Appending to existing session file: {target.name}")
    else:
        target = sessions_dir / f"simulate-{uuid_mod.uuid4()}.jsonl"
        target.write_text("")
        print(f"Created new fake session file: {target.name}")

    event = {
        "parentUuid": None,
        "isSidechain": False,
        "type": "system",
        "subtype": "compact_boundary",
        "content": "Conversation compacted (SIMULATED)",
        "isMeta": False,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "uuid": f"sim-{uuid_mod.uuid4()}",
        "level": "info",
        "compactMetadata": {
            "trigger": "auto",
            "preTokens": args.pre_tokens,
            "preCompactDiscoveredTools": [],
        },
        "userType": "external",
        "entrypoint": "cli",
        "cwd": args.project_dir,
        "sessionId": target.stem,
        "version": "simulate",
        "gitBranch": "main",
    }

    with open(target, "a") as f:
        f.write(json.dumps(event) + "\n")

    print(f"Wrote compact_boundary event uuid={event['uuid']}")
    print(
        "If ClawX is running with CompactWatcher enabled, within ~2s it "
        "should inject the AGENTS.md re-read and send a TG notification."
    )


if __name__ == "__main__":
    main()
