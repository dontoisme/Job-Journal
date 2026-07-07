# Slack bot — setup & interactions

The `jj` Slack bot is a **Socket Mode** daemon (`jj/slack_bot.py`, run via
`jj monitor bot-run`, installed as the `com.jj.slack-bot` LaunchAgent). Because
it uses Socket Mode there is **no public HTTP endpoint and no request-signature
verification** — buttons *and* slash commands are delivered over one persistent
WebSocket.

## Config (`~/.job-journal/config.yaml`, `monitor:` section)

| Key | Value |
|-----|-------|
| `slack_bot_token` | `xoxb-…` (Web API — posts messages) |
| `slack_app_token` | `xapp-…` (Socket Mode — needs `connections:write`) |
| `slack_default_channel` | `C…` (where scheduled monitor/digest/apply-ready post) |
| `slack_authorized_users` | list of Slack user IDs allowed to click buttons / run `/score`; empty = anyone in channel |

Tokens also fall back to env `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`.

## Interactions the bot handles

**Buttons (block_actions):**
- **Go** — score a URL (runs the full `/slack-apply` pipeline). On monitor & digest posts.
- **Open & Apply** — opens the JD in Chrome + hands off to `/apply-assist`. On apply-ready posts.
- **Stage resume** — generates the archetype resume headlessly (`/stage-resume`, no research brief). On `/score` result posts.
- **Applied** — sets status `applied` (+ `applied_at`/TWC fields). On all job posts.
- **Pass** — sets status `skipped`. On all job posts.

The Applied/Pass/Stage-resume buttons carry the application id when known, else
the job URL; `_resolve_application()` handles both.

**Slash command:**
- **`/score <job url> [more urls]`** — runs the headless `/slack-apply` flow for
  each URL (score against the corpus, save as a prospect, and stage an archetype
  resume for strong fits), then posts the fit result with
  `[Stage resume] [Applied] [Pass] [View JD]` buttons. Lets you score a role from
  Slack mobile without touching the Mac. (v1 runs the full score+resume flow like
  the `[Go]` button; a lighter triage-only mode may come later.)

## One-time Slack app configuration (api.slack.com/apps → your app)

The buttons need no extra setup (they ride the existing interactivity socket).
To enable the **`/score` slash command:**

1. **OAuth & Permissions → Scopes → Bot Token Scopes:** add **`commands`**.
   (Keep the existing `chat:write` etc.) Then **Reinstall to Workspace**.
2. **Slash Commands → Create New Command:**
   - Command: `/score`
   - Short Description: `Score a job URL against my corpus and save it as a prospect`
   - Usage Hint: `<job url> [more urls]`
   - **Request URL: leave blank** — with Socket Mode enabled, Slack delivers the
     command over the WebSocket; no URL is required.
3. Make sure **Socket Mode** is ON (Settings → Socket Mode) and
   **Interactivity & Shortcuts** is ON (already required for buttons).
4. Invite the bot to whatever channel you'll run `/score` in (`/invite @yourbot`)
   so it can post results there. `/score` also works in a DM with the bot.

> Name collision: if `/score` is already taken in your workspace by another app,
> pick a different name (e.g. `/jjscore`) — the handler accepts any command name,
> so only the Slack-side command definition changes.

## Applying the code change

Restart the daemon so the new handlers load:

```bash
# foreground (for testing; tails logs inline)
jj monitor bot-run

# or reload the LaunchAgent
launchctl unload ~/Library/LaunchAgents/com.jj.slack-bot.plist
launchctl load  ~/Library/LaunchAgents/com.jj.slack-bot.plist
jj monitor bot-log -f   # tail ~/.job-journal/logs/slack-bot.log
```

## Known limitation

Headless scoring shells out to `claude -p "/slack-apply <url>"` with a restricted
toolset (`Bash,WebFetch,WebSearch,Read,Write,Grep,Glob`) — **no Chrome/browser
tools**. JS-rendered ATS pages (Ashby, Workday, google careers) that need the
browser `get_page_text` fallback will fail to fetch headlessly; the `/score`
slash command and the existing Go button both work for Greenhouse/Lever/static JD
pages. For JS-heavy pages, score from the Mac where the browser fallback is
available.
