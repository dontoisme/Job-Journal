# Job Journal - Claude Code Instructions

## Project Overview

Python CLI (`jj`) + optional FastAPI web dashboard for career management and TWC compliance tracking. Built with Typer, Rich, SQLite, and Google APIs.

## Architecture

- **Entry point:** `jj/cli.py` — Typer app with 9 sub-apps (corpus, resume, email, greenhouse, app, interests, gdocs, worker, investors)
- **Database:** `jj/db.py` — SQLite with 16 tables, context-manager connections, `sqlite3.Row` factory
- **Config:** YAML-based (`~/.job-journal/profile.yaml`, `config.yaml`), loaded via `jj/config.py`
- **Data path:** `~/.job-journal/` (DB, config, credentials, corpus)
- **Skills:** `.claude/commands/*.md` — 9 skill files defining `/interview`, `/apply`, `/jobs`, `/twc`, etc.

## Core Conventions

### "SELECT, don't COMPOSE"
Resume bullets come verbatim from the corpus. Never generate or rewrite bullets — select existing ones.

### CLI Patterns
- Sub-apps are module-level `typer.Typer()` instances registered via `app.add_typer()`
- Use `rich.console.Console()` for all output — panels, tables, colored text
- Check `JJ_HOME.exists()` before operations; raise `typer.Exit(1)` on failure
- Optional dependencies (Gmail, FastAPI, OpenAI) use try/except imports with graceful fallback

### Database Patterns
- Always use `with get_connection() as conn:` context manager
- Return `[dict(row) for row in cursor.fetchall()]` for list queries
- Status lifecycle: prospect -> applied -> screening -> interview -> offer/rejected/withdrawn
- `ACTIVE_STATUSES` and `TERMINAL_STATUSES` constants define pipeline stages
- TWC fields on applications: `twc_activity_type`, `twc_result`, `activity_date`

### Gmail Integration
- OAuth 2.0 with `credentials.json` (from Google Cloud Console) and `gmail_token.json` (generated)
- Read-only scope: `gmail.readonly`
- Token refresh can fail if revoked — the authenticate method now handles this gracefully by deleting the stale token and re-triggering the browser OAuth flow
- Browser-based OAuth (`run_local_server`) does NOT work from Claude Code's sandbox — user must run `jj email setup` from their own terminal
- Email pairing system matches emails to applications (confirmation + resolution lifecycle)

## TWC Compliance

- Texas Workforce Commission requires 3 work search activities per week
- Activities tracked via `applications` table with `activity_date` and `twc_activity_type`
- Valid activity types: applied, resume, interview, job_fair, workforce_center, online_search
- Biweekly claim periods run Sunday-Saturday; use `get_twc_week_boundaries()` for date math
- `/twc` skill: syncs email, shows compliance summary, opens web dashboard

## Common Pitfalls

### Gmail Auth
- **Expired/revoked tokens:** If `jj email sync` fails with `invalid_grant`, the user needs to run `jj email setup` from their terminal (not from Claude Code) to complete browser OAuth
- The fix in `gmail_checker.py:authenticate()` catches refresh failures and falls through to new OAuth flow, but `run_local_server()` still requires a real browser

### File Paths
- `JJ_HOME = Path.home() / ".job-journal"` — all user data lives here
- `CREDENTIALS_PATH = JJ_HOME / "credentials.json"` — do NOT commit
- `TOKEN_PATH = JJ_HOME / "gmail_token.json"` — do NOT commit
- Generated resumes go to `~/Documents/Resumes/`

### Adding Applications for TWC
- Use `create_application(company, position, **kwargs)` from `jj/db.py`
- Set `activity_date` to the date the activity occurred (YYYY-MM-DD)
- Set `twc_activity_type` to classify the activity (default: "applied")
- Set `status` appropriately (usually "applied" for new applications)
- Set `applied_at` to the datetime of application
- The `applications` table has NO `source` column — store source info in `notes` instead
- For rejections, update existing records: `update_application(id, status="rejected", activity_date="...", twc_result="not_hiring")`
- TWC weeks run **Sunday-Saturday**, use `get_twc_week_boundaries(sunday_date)` for boundaries
- Each week requires 3 activities; check with `get_twc_week_summary(week_start)`

### Finding Untracked Job Activity in Gmail
When the user asks to find job emails not yet in Job Journal:
1. Run `jj email sync --days N --verbose` first to check existing applications
2. Then search Gmail broadly with the GmailClient API for application confirmations, interviews, rejections
3. Read email bodies (`jj email read <message_id>`) to confirm job relevance
4. Filter out newsletters, alerts, and marketing (ZipRecruiter alerts, LinkedIn job listings, Built In, Maven, Substack)
5. Look for: SmartRecruiters confirmations, ATS confirmations, recruiter correspondence, interview scheduling
6. Create new application records for genuine activity; update existing ones for status changes

### Things NOT to Do
- Don't generate resume bullets — select from corpus
- Don't commit `.job-journal/` contents, credentials, or tokens
- Don't assume Gmail auth works from Claude Code — it needs a browser
- Don't use bare `except:` clauses — catch specific exceptions
- Don't add emoji to output unless the user requests it
- Don't pass `source=` to `create_application()` — column doesn't exist
- Don't count ZipRecruiter job alerts, LinkedIn listings, or newsletter emails as job activity — only actual applications, interviews, and responses count
