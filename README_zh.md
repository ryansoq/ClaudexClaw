# ClaudexClaw

Claude Code supervisor daemon — 管理、監控、排程長期運行的 Claude Code sessions，帶有靈魂。

## 包含什麼

```
ClaudexClaw/
├── clawx.py              # Supervisor daemon
├── config.json           # 啟動 & 排程設定
├── CLAUDE.md             # Bootstrap — 啟動整個系統的入口
├── AGENTS.md             # Agent 行為規範 & 記憶系統
├── SOUL.md               # Agent 個性 & 價值觀
├── USER.md               # 關於你的人類（請填入資訊）
├── HEARTBEAT.md          # 定期檢查項目
├── MEMORY.md             # 長期記憶索引
├── memory/               # 每日記憶日誌
├── README.md             # English docs
└── README_zh.md          # 中文文件
```

## 運作原理

Claude Code 啟動時會先讀 `CLAUDE.md`，這個檔案會引導整個系統啟動：

1. `CLAUDE.md` → 告訴 Claude 去讀 `AGENTS.md`
2. `AGENTS.md` → 告訴 Claude 去讀 `SOUL.md`、`USER.md` 和記憶檔案
3. Agent 帶著完整 context 醒來：知道自己是誰、你是誰、最近發生了什麼
4. 心跳啟動、排程任務開始跑，agent 活起來了

`clawx.py` 是 supervisor，負責讓 session 持續運行 — 自動重啟、健康檢查、cron 排程。

## 安裝方式

### 方式 A：直接用這個 repo 當專案目錄

Clone 下來，填好 `USER.md`，自訂 `HEARTBEAT.md`，直接開跑。

```bash
git clone https://github.com/ryansoq/ClaudexClaw.git
cd ClaudexClaw

# 編輯 USER.md 填入你的資訊
# 編輯 config.json（設定 project_dir、model 等）

pip install apscheduler
python clawx.py
```

### 方式 B：把靈魂文件複製到現有專案

如果你已經有一個專案目錄（例如 OpenClaw workspace），把靈魂文件複製過去，用 `clawx.py` 當啟動器：

```bash
# 把靈魂文件複製到你的專案
cp CLAUDE.md AGENTS.md SOUL.md USER.md HEARTBEAT.md MEMORY.md /path/to/your/project/
mkdir -p /path/to/your/project/memory

# 更新 config.json 指向你的專案
# "project_dir": "/path/to/your/project"

python clawx.py
```

### 方式 C：把 clawx.py 複製到現有專案

或者把 `clawx.py` 和 `config.json` 搬到已經有 `CLAUDE.md` 的專案裡：

```bash
cp clawx.py config.json /path/to/your/project/
cd /path/to/your/project

# 編輯 config.json："project_dir": "./"
python clawx.py
```

關鍵是 `CLAUDE.md` 必須存在於專案目錄中 — 它是啟動 agent 靈魂的入口。

## 快速開始

```bash
# 安裝依賴（排程功能需要）
pip install apscheduler

# 啟動 daemon（會自動開 Claude CLI session）
python clawx.py

# 一次性指令（不需要 daemon）
python clawx.py prompt "跑晨報"

# 查看狀態
python clawx.py status

# 停止
python clawx.py stop
```

## 架構

```
ClaudexClaw (supervisor)
├── 生命週期管理：啟動 / 監控 / 自動重啟 Claude CLI
├── 排程系統：cron-based，不依賴 session（apscheduler）
├── 指令注入：送 prompt 到 running session
└── 日誌：所有 session 輸出都存 logs/

Claude CLI (worker)
├── CLAUDE.md bootstrap → AGENTS.md → SOUL.md + USER.md
├── MCP plugins (Telegram, etc.)
├── 心跳檢查
└── 日常工作 & 記憶管理
```

## 設定：config.json

- `claude`：CLI 路徑、專案目錄、model、權限模式、額外參數（如 `--channels`）
- `session`：自動重啟策略、健康檢查間隔
- `schedule`：cron 排程（晨報、心跳等）
- `logging`：log 目錄、大小限制、輪替

## Telegram 整合

在 config.json 的 `extra_args` 加上 `--channels plugin:telegram@claude-plugins-official`（預設已包含）。完整 Telegram 設定請看 `CLAUDE.md`。

## TODO

- [ ] IPC socket：讓 `clawx.py send` 能跟 running daemon 溝通
- [ ] Web dashboard：簡單的狀態頁面
- [ ] Context 管理：偵測 context 快滿 → 優雅重啟
- [ ] 多 session 支援：同時管理多個 agent
- [ ] Windows service / systemd unit
