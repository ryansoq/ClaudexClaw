# CLAUDE.md

## First Run

- **BLOCKING REQUIREMENT:** step by step, If `BOOTSTRAP.md` exists, that's your birth certificate. Follow it, figure out who you are, then delete it. You won't need it again.
- **BLOCKING REQUIREMENT:** Before generating ANY text response, you MUST use the Read tool to read `AGENTS.md` and follow its "Every Session" instructions completely. Do NOT speak until this is done.
- **BLOCKING REQUIREMENT:** After completing AGENTS.md setup, check heartbeat setup:
  1. Check if running under ClawX: look for `mono.fifo` in the project directory
  2. **If ClawX detected** → ClawX handles heartbeat via apscheduler, do NOT start `/loop`. Just read `heartbeat-config.json` for quiet hours reference.
  3. **If NOT in ClawX** (raw Claude CLI) → read `heartbeat-config.json`. If `enabled: true`, run `/loop {intervalMinutes}m` with the heartbeat prompt (read and execute `HEARTBEAT.md`). Do this BEFORE responding to the user.

## Telegram Setup

Let your agent chat with you on Telegram. Here's the full flow:

### What you need
- **bun** runtime installed ([bun.sh](https://bun.sh))
- A Telegram account

### Step-by-step

```
1. Install bun (if not installed)
   curl -fsSL https://bun.sh/install | bash

2. Create a Telegram bot
   → Open Telegram, find @BotFather
   → Send /newbot, follow the prompts
   → Copy the bot token (looks like: 123456:ABC-DEF...)

3. Install the Telegram plugin in Claude Code
   → Run Claude Code, type: /install-plugin telegram
   → Or search for "telegram" in the plugin list

4. Save your bot token
   → Create/edit: ~/.claude/channels/telegram/.env
   → Content: TELEGRAM_BOT_TOKEN=<your-token-here>

5. Set who can talk to the bot
   → Create/edit: ~/.claude/channels/telegram/access.json
   {
     "dmPolicy": "allowlist",
     "allowFrom": ["<your-telegram-user-id>"],
     "groups": {},
     "pending": {}
   }
   → Get your TG user ID: message @userinfobot on Telegram
   → IMPORTANT: the field is "allowFrom" (NOT "allowlist")

6. Add --channels to your launch command
   → In config.json, extra_args should include:
     "--channels", "plugin:telegram@claude-plugins-official"
   → (Already included in default config.json)

7. Launch ClawX (or Claude Code)
   python clawx.py
   → The bot should come online
   → Send it a message on Telegram to test!
```

### If bun is not in PATH
Some systems (especially WSL) don't add bun to PATH automatically.
Fix: edit `~/.claude/plugins/cache/claude-plugins-official/telegram/*/.mcp.json`
and change `"command"` to the full bun path (e.g. `~/.bun/bin/bun` or `~/.bun/bin/bun.exe`).

### Troubleshooting
| Problem | Cause | Fix |
|---------|-------|-----|
| 409 Conflict error | Another service is polling with same token | Stop the other bot or create a new token |
| bun not running | Plugin can't find bun | Set full path in .mcp.json (see above) |
| Bot runs but can't receive messages | access.json wrong format | Check `allowFrom` field (not `allowlist`) |
| Bot sends but doesn't receive | Missing --channels flag | Add to config.json extra_args |

## Heartbeat

### 環境判斷
- **ClawX 環境**（`mono.fifo` 存在）→ 心跳由 ClawX apscheduler 注入，不需要 `/loop`
- **Raw Claude CLI** → 用 `/loop` 啟動心跳

### Config file: `heartbeat-config.json`
```json
{
  "intervalMinutes": 30,
  "enabled": true,
  "quietHours": { "start": 23, "end": 8 }
}
```

### Startup Rules (Raw Claude CLI only)
1. Read `heartbeat-config.json` at session start
2. If `enabled: true`, use `/loop {intervalMinutes}m` to start periodic heartbeat
3. On each heartbeat:
   - Check if within quiet hours (`quietHours`), skip if so
   - Read `HEARTBEAT.md` and execute check items in order
   - Update `memory/heartbeat-state.json` with check timestamps
4. If `enabled: false`, do not start heartbeat

### Check Items
See `HEARTBEAT.md` for details.
