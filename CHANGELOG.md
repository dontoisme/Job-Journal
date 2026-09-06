# Changelog

All notable changes to Job Journal will be documented in this file.

## [Unreleased]

### Added
- Batched quick-screen tier (`jj monitor quick-screen`, `jj monitor scan-apis --quick-screen`): one cheap model call per 50-100 new listings on their plain facts, four-word verdicts with reasoning, fair/strong become prospects that `score-new` reads first. The title rule is now a ranking, not a gate.
- `judgments` table and `jj judgments list|put`: verdicts keyed by url and source (`user`, `model-quick`); a person's verdict outranks the model's and keeps a posting out of later runs.
- `jj/prompts.py`: the verdict scale and quick-screen instructions defined once and versioned; `~/.job-journal/quick-screen-prompt.md` overrides the shipped screen prompt.
- Reserved profile documents `~/.job-journal/constraints.md`, `preferences.md`, `background.md`; constraints are a hard veto and missing documents are reported.
- Coverage reporting on API scans: "N/M companies returned at least one job" plus the zero-yield list with a reason (HTTP 404 slug, empty board, no slug, error).
- Spend preview: `jj monitor score-new --preview` and `quick-screen --preview` say what a run would send and how much of the daily budget it would use, and call nothing.
- `--json` on `jj monitor score-new`, `jj monitor quick-screen`, and `jj judgments` commands.
- `job_listings.title_score` column; `record_job_listing(..., title_score=)`.
- Test fixtures for an isolated DB (`tests/conftest.py`) and tests for prompts, judgments, the quick screen, and scanner coverage.
- `docs/comparison-pinloop-cli.md` and `docs/quick-screen.md`.

### Changed
- `score_new_prospects` selects quick-screened prospects (strong first) before the title-rule picks; `--quick-only` disables the fallback.
- `scripts/monitor-launcher.sh` passes `--quick-screen` (set `JJ_QUICK_SCREEN=0` to skip).

## [0.1.0] - 2026-02-05

### Added
- Core CLI (`jj`) with Typer framework
- Corpus building via `/interview` Claude Code skill
- Resume generation with docx XML template manipulation
- Google Docs API integration for resume creation and PDF export
- Gmail API integration for application email tracking and classification
- Email-to-application pairing with ATS domain detection
- Greenhouse job board search via HAR-based authentication
- Geographic company discovery via Google Maps API
- Application lifecycle tracking (prospect through offer)
- Application pipeline analytics and funnel reporting
- Background worker with task queue for email sync and job polling
- ATS form detection utilities
- FastAPI web dashboard with application pipeline visualization
- Skill category reordering for JD-targeted resumes
- Auto-bold skill category names in generated resumes
- Corpus sync, fuzzy matching, and validation
- Resume-JD scoring (100-point rubric)
- Multiple resume variants (growth, ai-agentic, health-tech, consumer, general)
- System documentation (`docs/`)
