# Contributing to Job Journal

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/donhogan/job-journal
cd job-journal

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode with all optional deps
pip install -e ".[dev,web,gmail]"

# Verify installation
jj --version
```

## Running Tests

```bash
pytest
pytest --cov=jj              # with coverage
```

## Linting

```bash
ruff check jj/
ruff format jj/ --check      # check formatting
ruff format jj/               # auto-format
```

## Project Structure

```
jj/
  cli.py           # Typer CLI entry point (all commands)
  db.py            # SQLite schema, migrations, queries
  config.py        # Profile and config management
  corpus.py        # Corpus sync, search, validation
  resume_gen.py    # Docx template-based resume generation
  google_docs.py   # Google Docs API integration
  gmail_checker.py # Gmail API for email tracking
  greenhouse.py    # Greenhouse job board integration
  analytics.py     # Application pipeline analytics
  geo.py           # Geographic company discovery
  worker.py        # Background task queue
  autofill.py      # ATS form detection
  parser.py        # base.md parsing
  web/app.py       # FastAPI web dashboard
```

## Key Principles

- **"SELECT, don't COMPOSE"**: Resume bullets always come verbatim from the corpus. Never generate or fabricate achievement text.
- **Local-first**: All user data stays in `~/.job-journal/`. No cloud storage.
- **Optional dependencies**: Features that require external APIs (Gmail, Google Docs) are optional installs.

## Pull Request Process

1. Fork the repo and create a feature branch from `main`
2. Make your changes with clear, focused commits
3. Add tests for new functionality
4. Run `ruff check jj/` and `pytest` before submitting
5. Open a PR with a clear description of what changed and why

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS
