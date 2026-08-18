# Background Services (LaunchAgents)

Status snapshot as of **2026-08-18**. **All services are OFF.** Every plist is
booted out of launchd *and* disabled, so nothing restarts at login or reboot.
The plists remain on disk in `~/Library/LaunchAgents/` — turning a service back
on is a two-command operation (see Toggling).

| Service | Plist | What it does | Schedule | Status |
|---|---|---|---|---|
| Slack bot | `com.jj.slack-bot` | Socket Mode listener for the `/score` slash command and message buttons (score worker + `/slack-apply` spawns). Responds only — sends no proactive pings. | Always on (`KeepAlive` on crash) | **OFF** — 2026-08-18 |
| Dashboard | `com.jj.dashboard` | Local FastAPI web dashboard (`jj serve`) | Always on | **OFF** — 2026-08-18 |
| Email sync | `com.jj.email-sync` | `jj email pair` — Gmail classification/pairing. No Slack pings. | Every 2h | **OFF** — 2026-08-18 |
| Job monitor | `com.jj.monitor` | Discovers + scores new roles, stages apply-ready ones (`monitor-launcher.sh`) | 9:00 / 12:00 / 15:00 daily | **OFF** — 2026-08-18 |
| Daily digest | `com.jj.daily-digest` | `jj monitor digest` — Slack ping with top new + backlog prospects | 8:00 daily | **OFF** — 2026-08-18 |

## What still works with everything off

Nothing runs on its own anymore — no Slack pings, no Gmail sync, no scheduled
discovery, no dashboard on localhost. Every CLI command and every Claude Code
skill (`/score`, `/apply`, `/hunt`, `/twc`, …) still works on demand; they just
have to be invoked manually. The Slack `/score` slash command and the message
buttons will **not** respond while `com.jj.slack-bot` is off, since there is no
listener attached to the socket.

## Notes

- `bootout` alone only stops the current schedule — the plist reloads at next
  login. `disable` is what makes the shutdown survive a reboot, and it is sticky
  per-label until explicitly re-enabled.
- The monitor and the digest are independent: with the monitor off, the digest
  re-sends the same stale prospect list every morning, so they should be turned
  back on together or not at all.
- The "apply to new roles" Slack pings came from the **daily digest**, not the
  monitor.
- Email sync is the one worth restarting first if the search picks back up —
  it backfills application status from Gmail and feeds `jj funnel`.

## Toggling

```bash
# Turn a service ON (both steps needed — disable is sticky)
launchctl enable gui/501/com.jj.<name>
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.jj.<name>.plist

# Turn a service OFF (both steps needed to survive a reboot)
launchctl bootout gui/501/com.jj.<name>
launchctl disable gui/501/com.jj.<name>

# See what's loaded / what's disabled
launchctl list | grep com.jj
launchctl print-disabled gui/501 | grep com.jj
```

Logs: `~/.job-journal/logs/<name>.log`
