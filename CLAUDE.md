# Job Journal - Claude Code Instructions

## Project Overview

Python CLI (`jj`) + optional FastAPI web dashboard for career management and TWC compliance tracking. Built with Typer, Rich, SQLite, and Google APIs.

## Virtual Environment

The `jj` CLI is installed in a project-level venv. Always activate it before running `jj` commands:
```bash
source .venv/bin/activate
```
The LaunchAgent wrapper (`scripts/monitor-launcher.sh`) handles this automatically for scheduled runs.

## Architecture

- **Entry point:** `jj/cli.py` — Typer app with 11 sub-apps (corpus, resume, email, greenhouse, app, interests, gdocs, worker, investors, monitor, notify)
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

### Resume Generation
- Resumes are generated via `generate_resume_programmatic()` from `jj/google_docs.py` — builds the Google Doc from scratch using insertText + formatting APIs (no template)
- This is the single method for both `/apply` and `/pipeline`
- **Three-tier mode system:**
  - **Disciplined** (default): Compose summary fresh, reorder/filter skills. Bullet changes via SWAP/CUT/PROMOTE/DEMOTE against corpus only. Uses `mode="strict"` for DB validation.
  - **Strict** (`--strict`): Corpus bullets verbatim, no operations. Uses `mode="strict"`.
  - **Freeform** (`--freeform`): Full rewrite, escape hatch. Uses `mode="optimized"`. Only when corpus framing can't serve the JD.
- **Integrity audit is a Python-layer gate** (`_pre_export_audit()` in google_docs.py). The function refuses to generate a PDF if any check fails: duplicate companies, SpareFoot/IBM in main Experience, non-corpus bullets (strict mode), em-dashes, missing Projects, graduation year present.
- **`custom_skills` parameter must be `dict[str, list[str]]`** — display names mapped to **lists** of skill strings, NOT comma-separated strings.
- Old template-based generation and `~/.job-apply/` pandoc workflow are deprecated

### Resume Conventions
- **Summary:** Identity-First framework (Identity → Evidence → Differentiation). No category labels.
- **Banned phrases:** "12+ years," "proven track record," "results-driven," "passionate," "deep experience in"
- **No em-dashes** anywhere in resume content. Periods, semicolons, or commas.
- **No graduation year** in education
- **All bullets** must trace verbatim to corpus (disciplined/strict modes; enforced by DB lookup)
- **No duplicate company names** in the document
- **SpareFoot and IBM** appear ONLY in Earlier Experience, never in main Experience
- **Projects section** must be present (auto-included from corpus DB)
- **Earlier Experience** loaded from `profile.yaml` `earlier_roles`
- **Role dates** must exactly match base.md corpus dates
- **GitHub URL:** github.com/dontoisme

### Things NOT to Do
- Don't invent facts, metrics, or company names not in base.md
- Don't use em-dashes in resume content
- Don't rewrite bullet text in disciplined mode — use SWAP/CUT/PROMOTE/DEMOTE only
- Don't use `--freeform` unless corpus framing genuinely can't serve the JD
- Don't bypass the integrity audit — it's a code-layer gate, not a suggestion
- Don't commit `.job-journal/` contents, credentials, or tokens
- Don't assume Gmail auth works from Claude Code — it needs a browser
- Don't use bare `except:` clauses — catch specific exceptions
- Don't add emoji to output unless the user requests it
- Don't pass `source=` to `create_application()` — column doesn't exist
- Don't count ZipRecruiter job alerts, LinkedIn listings, or newsletter emails as job activity — only actual applications, interviews, and responses count
- Don't pass strings to `custom_skills` in `generate_resume_programmatic()` — values must be `list[str]`, not `str`


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
