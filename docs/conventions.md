# Job Journal — Detailed Conventions (on-demand)

This file holds the resume, Gmail, and TWC conventions that used to live in
`CLAUDE.md`. They were moved here so the high-frequency headless paths
(`/score`, `/slack-apply`, `/monitor`, `/research-brief` spawned via
`claude -p`) do not pay to load them on every invocation. Load this file when
working on resume generation, Gmail/email sync, or TWC compliance.

**Resume integrity is enforced in code** by `_pre_export_audit()` in
`jj/google_docs.py` — it refuses to export a PDF if any rule below is violated,
regardless of what the model has read. These conventions are the human-facing
statement of those same guarantees plus workflow guidance.

## Gmail Integration

- OAuth 2.0 with `credentials.json` (from Google Cloud Console) and `gmail_token.json` (generated)
- Read-only scope: `gmail.readonly`
- Token refresh can fail if revoked — the authenticate method now handles this gracefully by deleting the stale token and re-triggering the browser OAuth flow
- Browser-based OAuth (`run_local_server`) does NOT work from Claude Code's sandbox — user must run `jj email setup` from their own terminal
- Email pairing system matches emails to applications (confirmation + resolution lifecycle)

### Gmail Auth pitfalls
- **Expired/revoked tokens:** If `jj email sync` fails with `invalid_grant`, the user needs to run `jj email setup` from their terminal (not from Claude Code) to complete browser OAuth
- The fix in `gmail_checker.py:authenticate()` catches refresh failures and falls through to new OAuth flow, but `run_local_server()` still requires a real browser

### Finding Untracked Job Activity in Gmail
When the user asks to find job emails not yet in Job Journal:
1. Run `jj email sync --days N --verbose` first to check existing applications
2. Then search Gmail broadly with the GmailClient API for application confirmations, interviews, rejections
3. Read email bodies (`jj email read <message_id>`) to confirm job relevance
4. Filter out newsletters, alerts, and marketing (ZipRecruiter alerts, LinkedIn job listings, Built In, Maven, Substack)
5. Look for: SmartRecruiters confirmations, ATS confirmations, recruiter correspondence, interview scheduling
6. Create new application records for genuine activity; update existing ones for status changes

## TWC Compliance

- Texas Workforce Commission requires 3 work search activities per week
- Activities tracked via `applications` table with `activity_date` and `twc_activity_type`
- Valid activity types: applied, resume, interview, job_fair, workforce_center, online_search
- Biweekly claim periods run Sunday-Saturday; use `get_twc_week_boundaries()` for date math
- `/twc` skill: syncs email, shows compliance summary, opens web dashboard

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

## Resume Generation

- Resumes are generated via `generate_resume_programmatic()` from `jj/google_docs.py` — builds the Google Doc from scratch using insertText + formatting APIs (no template)
- This is the single method for both `/apply` and `/pipeline`
- **Three-tier mode system:**
  - **Disciplined** (default): Compose summary fresh, reorder/filter skills. Bullet changes via SWAP/CUT/PROMOTE/DEMOTE against corpus only. Uses `mode="strict"` for DB validation.
  - **Strict** (`--strict`): Corpus bullets verbatim, no operations. Uses `mode="strict"`.
  - **Freeform** (`--freeform`): Full rewrite, escape hatch. Uses `mode="optimized"`. Only when corpus framing can't serve the JD.
- **Matched format** (additive, via the `/matched-resume` skill; `generation_mode="matched"`, runs on `mode="strict"`): a JD-mirroring variant tuned to read as "this candidate needs to talk to us." Three differences from disciplined, all SELECT/REORDER only (bullets stay corpus-verbatim, audit unchanged):
  - **Skills mirror the JD's exact wording**, emitted only when substantiated by the corpus (canonical skills + skills demonstrated by demoted older roles). A JD term with no corpus backing is dropped — never keyword-stuff. Helper: `build_matched_skills()`.
  - **Bullets are ordered to tell a matching story** — within each role, lead with the bullet that best answers the JD's top requirement. Helper: `order_bullets_for_story()` (returns a permutation; never rewrites).
  - **Main Experience is compressed to the last ~5 years** with a minimum-role floor (a strong near-cutoff role survives); older roles drop to Earlier Experience and lend their skills to the skills section. Helpers: `split_roles_by_window()`, `roles_to_earlier_dicts()`, `collect_skill_pool_from_roles()`; role selection via the `role_companies` param on `generate_resume_programmatic()`/`assemble_template_data()`. Earlier Experience is deduped against `profile.earlier_roles` (profile entries win, so SpareFoot/IBM keep clean dates).
- **Integrity audit is a Python-layer gate** (`_pre_export_audit()` in google_docs.py). The function refuses to generate a PDF if any check fails: duplicate companies, SpareFoot/IBM in main Experience, non-corpus bullets (strict mode), em-dashes, missing Projects, graduation year present.
- **`custom_skills` parameter must be `dict[str, list[str]]`** — display names mapped to **lists** of skill strings, NOT comma-separated strings.
- Old template-based generation and `~/.job-apply/` pandoc workflow are deprecated

## Resume Conventions

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

## Archetype Master Resumes

- 4 pre-built resumes stored in `~/.job-journal/archetypes.yaml`: growth, ai-agentic, health-tech, general
- PDFs and Google Docs in `~/Documents/Resumes/archetypes/`
- `resumes` table has `is_archetype=1` flag; query via `get_archetype_resume(variant)`
- `/slack-apply` defaults to archetype lookup (no per-JD generation)
- `/apply` offers archetype as default, with per-JD tailoring as opt-in escape hatch
- Config helpers: `load_archetypes()` / `save_archetypes()` in `jj/config.py`
- To regenerate: update `archetypes.yaml` bullet/skill selections, then call `generate_resume_programmatic()` with `generation_mode="archetype"` and set `is_archetype=1`

## Resume/Gmail/TWC "Things NOT to Do"

- Don't invent facts, metrics, or company names not in base.md
- Don't use em-dashes in resume content
- Don't rewrite bullet text in disciplined mode — use SWAP/CUT/PROMOTE/DEMOTE only
- Don't use `--freeform` unless corpus framing genuinely can't serve the JD
- Don't bypass the integrity audit — it's a code-layer gate, not a suggestion
- Don't assume Gmail auth works from Claude Code — it needs a browser
- Don't count ZipRecruiter job alerts, LinkedIn listings, or newsletter emails as job activity — only actual applications, interviews, and responses count
- Don't pass strings to `custom_skills` in `generate_resume_programmatic()` — values must be `list[str]`, not `str`
