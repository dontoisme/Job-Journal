# Background Services (LaunchAgents)

Status as of **2026-08-18**: **everything is off, intentionally and for the long
term.** Don is not actively job searching, so every automated process that
supported the search has been stopped.

The shutdown is belt-and-suspenders, because a single `bootout` only lasts until
the next login:

1. **Booted out** of launchd — `launchctl bootout gui/501/com.jj.<name>`
2. **Disabled** — `launchctl disable gui/501/com.jj.<name>`, which survives
   reboot and is sticky until explicitly re-enabled
3. **Plists archived** out of `~/Library/LaunchAgents/` to
   `~/.job-journal/launchagents-archive/`, so nothing at login or a stray
   `launchctl load` can pick them back up

| Service | Plist | What it did | Schedule when on |
|---|---|---|---|
| Slack bot | `com.jj.slack-bot` | Socket Mode listener for the `/score` slash command and message buttons (score worker + `/slack-apply` spawns). Responded only — sent no proactive pings. | Always on (`KeepAlive` on crash) |
| Dashboard | `com.jj.dashboard` | Local FastAPI web dashboard (`jj serve`) | Always on |
| Email sync | `com.jj.email-sync` | `jj email pair` — Gmail classification/pairing | Every 2h |
| Job monitor | `com.jj.monitor` | Discovered + scored new roles, staged apply-ready ones | 9:00 / 12:00 / 15:00 daily |
| Daily digest | `com.jj.daily-digest` | `jj monitor digest` — Slack ping with top new + backlog prospects | 8:00 daily |

## What this means day to day

Nothing runs on its own: no Slack pings, no Gmail sync, no scheduled discovery,
no dashboard on localhost. The Slack `/score` command and the message buttons do
not respond — there is no listener on the socket.

Every CLI command and Claude Code skill (`/score`, `/apply`, `/hunt`, `/twc`, …)
still works fine on demand. The system is manual-only, not dismantled.

**Not affected:** the shared Dolt server at `~/.beads/shared-server` (port 3308)
is still running. It is the `bd` issue-tracker backend for *all* of Don's repos,
not a job-search service — killing it would break `bd` in agent-commerce,
squabble-react-native, and seven other workspaces.

## Turning a service back on

Two paths. Either way, **`launchctl enable` is required first** — the disable is
sticky, and `bootstrap` silently no-ops while it is set.

```bash
# Path A — restore the archived plist (keeps the exact old config)
cp ~/.job-journal/launchagents-archive/com.jj.<name>.plist ~/Library/LaunchAgents/
launchctl enable gui/501/com.jj.<name>
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.jj.<name>.plist

# Path B — regenerate from the CLI (writes a fresh plist, then loads it)
jj monitor install               # com.jj.monitor
jj monitor install-digest        # com.jj.daily-digest
jj monitor install-email-sync    # com.jj.email-sync
jj monitor install-bot           # com.jj.slack-bot
jj monitor install-dashboard     # com.jj.dashboard
```

Path B still needs the `launchctl enable` first: those commands use the legacy
`launchctl load`, which will not override a disabled label.

If the search restarts, **email sync is the one to bring back first** — it
backfills application status from Gmail and feeds `jj funnel`. Monitor and
digest should come back together or not at all: with the monitor off, the digest
re-sends the same stale prospect list every morning.

## Checking state

```bash
launchctl list | grep com.jj                  # what is loaded (expect nothing)
launchctl print-disabled gui/501 | grep com.jj  # expect all five => disabled
ls ~/Library/LaunchAgents | grep jj           # expect nothing
```

Logs (historical): `~/.job-journal/logs/<name>.log`
