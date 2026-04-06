# ClaudexClaw

A Claude Code supervisor daemon — manages, monitors, and schedules long-running Claude Code sessions with a soul.

## What's Inside

```
ClaudexClaw/
├── clawx.py              # Supervisor daemon
├── config.json           # Launch & schedule config
├── CLAUDE.md             # Bootstrap — the entry point that boots everything
├── AGENTS.md             # Agent behavior rules & memory system
├── SOUL.md               # Agent personality & values
├── USER.md               # About your human (fill this in)
├── HEARTBEAT.md          # Periodic check items
├── MEMORY.md             # Long-term memory index
├── memory/               # Daily memory logs
├── README.md             # English docs
└── README_zh.md          # 中文文件
```

## How It Works

When Claude Code starts, it reads `CLAUDE.md` first. This file bootstraps the entire system:

1. `CLAUDE.md` → tells Claude to read `AGENTS.md`
2. `AGENTS.md` → tells Claude to read `SOUL.md`, `USER.md`, and memory files
3. The agent wakes up with full context: who it is, who you are, and what happened recently
4. Heartbeat starts, scheduled tasks run, the agent is alive

`clawx.py` is the supervisor that keeps this session running — auto-restart, health checks, cron scheduling.

## Setup

### Option A: Use this repo as your project directory

Clone this repo and point your agent here. Fill in `USER.md` with your info, customize `HEARTBEAT.md` with your checks, and go.

```bash
git clone https://github.com/ryansoq/ClaudexClaw.git
cd ClaudexClaw

# Edit USER.md with your info
# Edit config.json (set project_dir, model, etc.)

pip install apscheduler
python clawx.py
```

### Option B: Copy soul files into an existing project

If you already have a project directory (e.g. an OpenClaw workspace), copy the soul files there and keep `clawx.py` as the launcher:

```bash
# Copy soul files into your existing project
cp CLAUDE.md AGENTS.md SOUL.md USER.md HEARTBEAT.md MEMORY.md /path/to/your/project/
mkdir -p /path/to/your/project/memory

# Update config.json to point to your project
# "project_dir": "/path/to/your/project"

python clawx.py
```

### Option C: Copy clawx.py into your existing project

Alternatively, move `clawx.py` and `config.json` into your project that already has `CLAUDE.md`:

```bash
cp clawx.py config.json /path/to/your/project/
cd /path/to/your/project

# Edit config.json: set "project_dir": "./"
python clawx.py
```

The key is that `CLAUDE.md` must exist in the project directory — it's the entry point that boots the agent's soul.

## Quick Start

```bash
# Install dependencies (required for scheduling)
pip install apscheduler

# Start daemon (auto-launches a Claude CLI session)
python clawx.py

# One-shot command (no daemon needed)
python clawx.py prompt "run morning report"

# Check status
python clawx.py status

# Stop
python clawx.py stop
```

## Architecture

```
ClaudexClaw (supervisor)
├── Lifecycle management: start / monitor / auto-restart Claude CLI
├── Scheduler: cron-based, session-independent (apscheduler)
├── Command injection: send prompts to a running session
└── Logging: all session output saved to logs/

Claude CLI (worker)
├── CLAUDE.md bootstrap → AGENTS.md → SOUL.md + USER.md
├── MCP plugins (Telegram, etc.)
├── Heartbeat checks
└── Daily tasks & memory management
```

## Configuration: config.json

- `claude`: CLI path, project directory, model, permission mode, extra args (e.g. `--channels`)
- `session`: auto-restart strategy, health check interval
- `schedule`: cron jobs (morning reports, heartbeats, etc.)
- `logging`: log directory, size limits, rotation

## Telegram Integration

Add `--channels plugin:telegram@claude-plugins-official` to `extra_args` in config.json (already included by default). See `CLAUDE.md` for full Telegram setup instructions.

## TODO

- [ ] IPC socket: allow `clawx.py send` to communicate with the running daemon
- [ ] Web dashboard: simple status page
- [ ] Context management: detect context window nearing limit, graceful restart
- [ ] Multi-session support: manage multiple agents simultaneously
- [ ] Windows service / systemd unit
