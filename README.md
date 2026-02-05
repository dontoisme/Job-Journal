# Job Journal

**Interview your career, customize your resume.**

Job Journal is a local-first CLI tool that helps you build a rich corpus of your professional experience through conversational interviews, then uses that corpus to generate tailored resumes in your own voice. Every resume bullet is selected from your corpus -- never fabricated by AI.

Built for [Claude Code](https://claude.ai/claude-code) as a first-class interface.

## Quick Start

```bash
# Clone and install
git clone https://github.com/donhogan/job-journal
cd job-journal
pip install -e .

# Initialize
jj init

# Start building your corpus (best with Claude Code)
jj interview
```

### Optional Dependencies

```bash
pip install -e ".[web]"      # FastAPI web dashboard
pip install -e ".[gmail]"    # Gmail email tracking
pip install -e ".[dev]"      # Testing and linting
```

## How It Works

1. **Interview** -- Job Journal walks through your career year-by-year, role-by-role, extracting achievements, skills, and stories in your own words.

2. **Corpus** -- Your experiences are stored in a searchable corpus (`~/.job-journal/corpus.md`) that you can edit and refine.

3. **Discover** -- Search job boards (Greenhouse, Lever, Ashby) and score opportunities against your corpus.

4. **Apply** -- Job Journal matches your corpus against the job description and generates a tailored resume. Every bullet is selected verbatim from your corpus.

5. **Track** -- Monitor application status, track email responses via Gmail, and view pipeline analytics.

## With Claude Code

Job Journal is designed around Claude Code slash commands as the primary interface:

| Skill | Purpose |
|-------|---------|
| `/interview` | Conversational interview to build your corpus |
| `/apply <url>` | Full application workflow with fit scoring and resume generation |
| `/jobs [query]` | Search and score job opportunities |
| `/greenhouse` | Search Greenhouse job boards with saved auth |

## CLI Commands

### Core

| Command | Purpose |
|---------|---------|
| `jj init` | Initialize Job Journal |
| `jj interview [role]` | Start/continue building your corpus |
| `jj import-base <file>` | Import existing base.md file |
| `jj stats` | Show corpus and application statistics |
| `jj serve` | Start the web dashboard at localhost:8000 |

### Corpus Management (`jj corpus`)

| Command | Purpose |
|---------|---------|
| `jj corpus sync` | Sync entries from corpus.md to database |
| `jj corpus list` | List entries with filtering by tags, role, category |
| `jj corpus search <query>` | Full-text search across entries |
| `jj corpus stats` | Corpus statistics breakdown |
| `jj corpus suggestions` | View improvement suggestions from JD gap analysis |
| `jj corpus edit` | Open corpus.md in your editor |

### Resume Generation (`jj resume`, `jj gdocs`)

| Command | Purpose |
|---------|---------|
| `jj resume list` | List all generated resumes |
| `jj resume show <id>` | Display a specific resume |
| `jj resume validate` | Validate resume bullets against corpus |
| `jj gdocs generate <variant>` | Generate tailored resume via Google Docs |
| `jj gdocs setup` | Configure Google Docs API |

### Job Discovery (`jj greenhouse`)

| Command | Purpose |
|---------|---------|
| `jj greenhouse setup <har>` | Import auth from HAR file |
| `jj greenhouse poll` | Search for matching jobs |
| `jj greenhouse config` | Configure search defaults |

### Application Tracking (`jj app`, `jj email`)

| Command | Purpose |
|---------|---------|
| `jj app status` | Show current application pipeline |
| `jj app timeline` | Application timeline over time |
| `jj email setup` | Configure Gmail API |
| `jj email sync` | Full sync: confirmations + updates + pairing |
| `jj email verify` | Check for application confirmation emails |
| `jj email updates` | Check for interview/rejection emails |
| `jj email pair` | Match emails to applications |

### Background Worker (`jj worker`)

| Command | Purpose |
|---------|---------|
| `jj worker start` | Start background sync daemon |
| `jj worker status` | Show worker status |
| `jj worker run-task <type>` | Execute a specific task |

## Resume-JD Scoring

When applying, resumes are scored against the job description on a 100-point rubric:

| Category | Weight |
|----------|--------|
| Summary alignment | 25 pts |
| Skills coverage | 25 pts |
| Bullet relevance | 35 pts |
| Keyword density | 15 pts |

Target: 80+ before submitting.

## Data Location

All data stays on your machine in `~/.job-journal/`:

```
~/.job-journal/
├── profile.yaml      # Your contact info and preferences
├── config.yaml       # Settings and variant definitions
├── corpus.md         # Your professional corpus (human-readable, editable)
├── journal.db        # SQLite database (16 tables)
├── applications.csv  # Application tracking export
├── templates/        # Resume templates (docx)
└── resumes/          # Generated resumes
```

## Integrations

| Service | Purpose | Setup |
|---------|---------|-------|
| **Google Docs** | Resume generation + PDF export | `jj gdocs setup` |
| **Gmail** | Application email tracking | `jj email setup` |
| **Greenhouse** | Job board search | `jj greenhouse setup` |
| **Google Maps** | Geographic company discovery | Config API key |

## Philosophy

- **Your voice matters**: Job Journal captures how *you* describe your work, not generic resume-speak.
- **SELECT, don't COMPOSE**: Every resume bullet comes verbatim from your corpus. No AI fabrication.
- **Slow and thorough**: Building a good corpus takes time. Each role gets a dedicated interview session.
- **Local-first**: Your career data stays on your machine in human-readable formats.
- **AI-assisted, human-controlled**: Claude helps extract and organize, but you approve everything.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
