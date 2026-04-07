# CLAUDE.md

## First Run

- **BLOCKING REQUIREMENT:** step by step, If `BOOTSTRAP.md` exists, that's your birth certificate. Follow it, figure out who you are, then delete it. You won't need it again.
- **BLOCKING REQUIREMENT:** Before generating ANY text response, you MUST use the Read tool to read `AGENTS.md` and follow its "Every Session" instructions completely. Do NOT speak until this is done.
- **BLOCKING REQUIREMENT:** After completing AGENTS.md setup, check heartbeat setup:
  1. Check if running under ClawX: look for `mono.fifo` in the project directory
  2. **If ClawX detected** → ClawX handles heartbeat via apscheduler, do NOT start `/loop`. Just read `heartbeat-config.json` for quiet hours reference.
  3. **If NOT in ClawX** (raw Claude CLI) → read `heartbeat-config.json`. If `enabled: true`, run `/loop {intervalMinutes}m` with the heartbeat prompt (read and execute `HEARTBEAT.md`). Do this BEFORE responding to the user.

## Telegram Setup

If Telegram MCP tools are not in the available tool list, follow these steps:

### Prerequisites
- **bun** must be installed (default path: `~/.bun/bin/bun.exe`)
- If bun is not in system PATH, MCP config must use the full path
- **Launch parameter**: Claude Code must include `--channels plugin:telegram@claude-plugins-official` to **receive** TG messages (without it, you can only send but not receive)

### Setup Steps
1. **Install Telegram plugin** (if not already installed): search and install `telegram` plugin in Claude Code
2. **Bot Token**: stored in `~/.claude/channels/telegram/.env`, format: `TELEGRAM_BOT_TOKEN=<token>`
   - To create a new bot, go to `@BotFather` on TG → `/newbot`
3. **Access config**: `~/.claude/channels/telegram/access.json`
   ```json
   {
     "dmPolicy": "allowlist",
     "allowFrom": ["<user_telegram_id>"],
     "groups": {},
     "pending": {}
   }
   ```
   - **Note**: the field is `allowFrom` (string array), NOT `allowlist`
   - Get your TG user ID from `@userinfobot` or similar
4. **Fix cache `.mcp.json` path**: if bun is not in system PATH, change `command` in `~/.claude/plugins/cache/claude-plugins-official/telegram/*/.mcp.json` to the full bun path (plugin updates may overwrite it)
5. **Reload**: run `/reload-plugins`, verify bun process is running (`tasklist | grep bun`)

### Common Issues
- **409 Conflict**: another service is polling with the same bot token — switch token or stop the other side
- **bun not running**: check if cache `.mcp.json` command is the full path
- **Can't receive messages but bot is running**: check access.json format (`allowFrom` not `allowlist`)

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
