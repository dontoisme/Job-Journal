# Changelog

All notable changes to Job Journal will be documented in this file.

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
