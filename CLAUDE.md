# Job Journal - Claude Code Instructions

> **Detailed resume, Gmail, and TWC conventions live in `docs/conventions.md`** — load that file when working on resume generation, Gmail/email sync, or TWC compliance. They were moved out of this always-loaded file so headless scoring/monitoring runs (`/score`, `/slack-apply`, `/monitor`, `/research-brief` via `claude -p`) don't pay to load them every spawn. Resume integrity is enforced in code by `_pre_export_audit()` in `jj/google_docs.py`, so those rules don't need to be in context to hold.

## Project Overview

Python CLI (`jj`) + optional FastAPI web dashboard for career management and TWC compliance tracking. Built with Typer, Rich, SQLite, and Google APIs.

## Virtual Environment

The `jj` CLI is installed in a project-level venv. Always activate it before running `jj` commands:
```bash
source .venv/bin/activate
```
The LaunchAgent wrapper (`scripts/monitor-launcher.sh`) handles this automatically for scheduled runs.

## Architecture

- **Entry point:** `jj/cli.py` — Typer app with 12 sub-apps (corpus, resume, email, greenhouse, app, interests, gdocs, worker, investors, monitor, notify, judgments)
- **Database:** `jj/db.py` — SQLite with 25 tables, context-manager connections, `sqlite3.Row` factory
- **Config:** YAML-based (`~/.job-journal/profile.yaml`, `config.yaml`), loaded via `jj/config.py`
- **Data path:** `~/.job-journal/` (DB, config, credentials, corpus)
- **Skills:** `.claude/commands/*.md` — 22 skill files defining `/interview`, `/apply`, `/jobs`, `/twc`, etc.
- **Judging tiers:** `score_title_fit` (deterministic rule, free) -> `jj/quick_screen.py` (one cheap batched model call per 50-100 listings, plain facts only) -> full score (`jj/scoring.py` spawning `/slack-apply`). Verdicts are the four words in `jj/prompts.py` (`no`, `weak`, `fair`, `strong`) stored in `judgments` with reasoning and `judged_by`; a person's verdict outranks the model's. See `docs/quick-screen.md`.
- **Prompts:** `jj/prompts.py` holds the verdict scale, the reserved profile document names and the quick-screen instructions (`PROMPT_VERSION` is bumped by hand when text changes). `~/.job-journal/quick-screen-prompt.md` replaces the shipped screen prompt whole.
- **Profile documents:** `~/.job-journal/constraints.md`, `preferences.md`, `background.md` are read by the quick screen (constraints are a hard veto). Missing ones are reported in the run summary, never silently skipped.

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
- Verdicts: `record_judgment(url, verdict, reasoning, judged_by=...)` upserts per (url, judged_by); `get_best_judgment(url)` applies precedence user > model-quick. Raises `ValueError` on a bad word so typos are loud.
- Report coverage before exclusions: "148/175 companies returned a board", then the list of what was left out and why (`scan_all_api_companies` summary `coverage` + `zero_yield`; quick screen `coverage` + `dropped`).
- New commands that return rows take `--json` (one object on stdout, prose to `err_console`); prefer `jj ... --json` over inline `from jj.db import ...` in new skills.

### Gmail / TWC / Resume conventions
Moved to `docs/conventions.md` (Gmail OAuth + auth pitfalls, TWC compliance + adding TWC applications, resume generation/conventions/archetypes). Load that file when working on those features.

## Common Pitfalls

### File Paths
- `JJ_HOME = Path.home() / ".job-journal"` — all user data lives here
- `CREDENTIALS_PATH = JJ_HOME / "credentials.json"` — do NOT commit
- `TOKEN_PATH = JJ_HOME / "gmail_token.json"` — do NOT commit
- Generated resumes go to `~/Documents/Resumes/`

### Things NOT to Do (operational)
- Don't commit `.job-journal/` contents, credentials, or tokens
- Don't use bare `except:` clauses — catch specific exceptions
- Don't add emoji to output unless the user requests it
- Don't pass `source=` to `create_application()` — column doesn't exist
- Resume/Gmail/TWC-specific "don'ts" (em-dashes, freeform, integrity audit, job-activity filtering, `custom_skills` typing): see `docs/conventions.md`


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
