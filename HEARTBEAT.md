# HEARTBEAT.md

## Heartbeat Check Items

Add your periodic checks here. The agent will read this file on each heartbeat and execute the items in order.

### Example checks (customize to your needs):

- **Disk space**: `df -h / | tail -1` — alert if usage exceeds threshold
- **Connectivity**: check if key services are running
- **Notifications**: check email, calendar, mentions
- **Monitoring**: track prices, metrics, or any data you care about

---

Use `cron list` to view all scheduled tasks.
