# Job Journal

**Interview your career, customize your resume.**

Job Journal is a CLI tool that helps you build a rich corpus of your professional experience through conversational interviews, then uses that corpus to generate tailored resumes in your own voice.

## Quick Start

```bash
# Clone and install
git clone https://github.com/donhogan/job-journal
cd job-journal
pip install -e .

# Initialize
jj init

# Start building your corpus
jj interview
```

## How It Works

1. **Interview**: Job Journal walks through your career year-by-year, role-by-role, extracting achievements, skills, and stories in your own words.

2. **Corpus**: Your experiences are stored in a searchable corpus (`~/.job-journal/corpus.md`) that you can edit and refine.

3. **Apply**: When applying to jobs, Job Journal matches your corpus against the job description and generates a tailored resume emphasizing the most relevant experience.

## Commands

| Command | Purpose |
|---------|---------|
| `jj init` | Initialize Job Journal |
| `jj interview` | Start/continue building your corpus |
| `jj interview [role]` | Deep-dive on a specific role |
| `jj corpus` | View your corpus |
| `jj corpus --edit` | Edit corpus in your editor |
| `jj import-base <file>` | Import existing base.md file |
| `jj stats` | Show corpus statistics |

## With Claude Code

Job Journal is designed to work with [Claude Code](https://claude.ai/claude-code). Use these slash commands for the full experience:

- `/interview` - Conversational interview to build your corpus
- `/apply <url>` - Full application workflow with fit scoring
- `/jobs` - Search for job opportunities

## Data Location

Your data is stored in `~/.job-journal/`:

```
~/.job-journal/
├── profile.yaml      # Your contact info and preferences
├── config.yaml       # Settings
├── corpus.md         # Your professional corpus (editable)
├── journal.db        # SQLite database
├── applications.csv  # Application tracking
└── resumes/          # Generated resumes
```

## Migration from ~/.job-apply

If you have an existing `~/.job-apply/` installation, Job Journal can migrate your data:

```bash
jj init  # Will detect and offer to migrate
```

Or import just your base.md:

```bash
jj import-base ~/.job-apply/resume/base.md
```

## Philosophy

- **Your voice matters**: Job Journal captures how *you* describe your work, not generic resume-speak.
- **Slow and thorough**: Building a good corpus takes time. Each role gets a dedicated interview session.
- **Local-first**: Your career data stays on your machine in human-readable formats.
- **AI-assisted, human-controlled**: Claude helps extract and organize, but you approve everything.

## License

MIT
