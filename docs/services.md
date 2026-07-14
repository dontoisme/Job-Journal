# Background Services (LaunchAgents)

Status snapshot as of **2026-07-13**. All plists live in `~/Library/LaunchAgents/`
and remain on disk when unloaded — unloading only stops the schedule.

| Service | Plist | What it does | Schedule | Status |
|---|---|---|---|---|
| Slack bot | `com.jj.slack-bot` | Socket Mode listener for the `/score` slash command and message buttons (score worker + `/slack-apply` spawns). Responds only — sends no proactive pings. | Always on (`KeepAlive` on crash) | **ON** — started 2026-07-13 |
| Dashboard | `com.jj.dashboard` | Local FastAPI web dashboard | Always on | **ON** |
| Email sync | `com.jj.email-sync` | `jj email pair` — Gmail classification/pairing. No Slack pings. | Every 2h | **ON** |
| Job monitor | `com.jj.monitor` | Discovers + scores new roles, stages apply-ready ones (`monitor-launcher.sh`) | 9:00 / 12:00 / 15:00 daily | **OFF** — unloaded since 2026-07-09 |
| Daily digest | `com.jj.daily-digest` | `jj monitor digest` — Slack ping with top new + backlog prospects | 8:00 daily | **OFF** — unloaded 2026-07-13 |

## Notes

- The monitor and the digest are independent: with the monitor off, the digest
  was re-sending the same stale prospect list every morning, so both are off.
- The "apply to new roles" Slack pings came from the **daily digest**, not the
  monitor.

## Toggling

```bash
# Turn a service on
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.jj.<name>.plist

# Turn a service off
launchctl bootout gui/501/com.jj.<name>

# See what's loaded
launchctl list | grep com.jj
```

Logs: `~/.job-journal/logs/<name>.log`
