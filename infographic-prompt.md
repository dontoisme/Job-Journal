# Job Journal Infographic — Gemini CLI Prompt

Run this from the job-journal directory:

```bash
gemini -p "$(cat <<'PROMPT'
Create a Python script called generate_infographic.py that uses matplotlib to generate a single high-resolution PNG infographic (2400x3200px, dark theme) saved to ./job-journal-architecture.png

The infographic should visualize the "Job Journal" system — an autonomous job search engine built as a Python CLI (jj). Use a professional dark background (#1a1a2e) with accent colors: cyan (#00d4ff), orange (#ff6b35), green (#00e676), purple (#bb86fc), and white text.

## Title
"Job Journal — Autonomous Job Search Engine"
Subtitle: "Python CLI + Claude Code Skills + Google APIs"

## Section 1: 3-Tier Pipeline (Top section, most prominent)
Show three horizontal lanes, each representing a tier:

**Tier 1 — /pipeline (Interactive Batch)**
5 phases flowing left-to-right:
  Scrape Career Pages → Title Pre-filter (50+) → [USER APPROVAL GATE] → Score vs Corpus (70+) → Generate Resume → Validate (drift=0) → Opportunity Brief
  Color: cyan

**Tier 2 — /swarm (Semi-Autonomous Daily)**
Same flow but with:
  Parallel Task Subagents (batches of 3-5) → Delta Detection → Auto-score (65+) → Auto-Resume
  Color: orange
  Note: "No approval gates in monitoring mode"

**Tier 3 — /monitor (Fully Headless, LaunchAgent)**
Phases:
  Email Sync → Scrape Companies → Delta Detect → Title Filter → Score → Resume (cap: 3/run) → Slack Notification
  Color: green
  Note: "Runs at 06:00 & 12:00 via LaunchAgent. Zero interaction."

## Section 2: Architecture Layers (Middle section)
Show three stacked horizontal layers:

**Layer 1 — Claude Code Skills** (top, purple)
  /interview, /apply, /jobs, /pipeline, /swarm, /monitor, /twc, /score, /fit, /greenhouse, /vc-boards, /start-today, /learn
  Label: "13 Skills — Prompt-driven orchestration"

**Layer 2 — Python CLI (jj)** (middle, cyan)
  11 sub-apps: corpus, resume, email, greenhouse, app, gdocs, worker, investors, monitor, notify, interests
  Label: "30+ commands via Typer + Rich"

**Layer 3 — Data Layer** (bottom, orange)
  SQLite (24 tables) | Google Docs API | Gmail API | Slack Webhook
  Label: "Single DB + 3 external integrations"

Show arrows flowing DOWN between layers: Skills → CLI → Data

## Section 3: Data Flow (Bottom-left)
Show a flowchart:
  Career Pages / VC Boards → WebFetch → job_listings (delta detect) → Score (4-category rubric) → applications (prospect)
  Gmail API → gmail_checker.py → application_emails (confirmation → resolution lifecycle)
  profile.yaml + corpus.md → generate_resume_programmatic() → Google Docs → PDF Export → ~/Documents/Resumes/
  monitor results → Slack notification (with Google Doc links)

## Section 4: Scoring System (Bottom-right)
Two scoring rubrics as small tables:

**Job Fit Score (100 pts)**
| Category | Weight |
| Skills Match | 35 |
| Experience Level | 25 |
| Domain Fit | 25 |
| Location/Remote | 15 |

**Resume-JD Match (100 pts)**
| Category | Weight |
| Summary Alignment | 25 |
| Skills Coverage | 25 |
| Bullet Relevance | 35 |
| Keyword Density | 15 |
Threshold: 85+ to generate doc

## Section 5: Key Stats (Footer bar)
Show as pill-shaped badges:
  "24 SQLite Tables" | "13 Claude Skills" | "30+ CLI Commands" | "3-Tier Pipeline" | "Zero Tests 😅"

## Design Guidelines
- Use rounded rectangles for all boxes
- Use arrows with slight curves, not straight lines
- Add subtle glow effects on accent colors
- Use a monospace font (or similar) for command names
- Add small icons or emoji where appropriate (📧 for email, 📄 for docs, 🔔 for notifications)
- Core principle callout box: "SELECT, don't COMPOSE — bullets come verbatim from corpus, never generated"
- Make it look like a premium developer/product infographic, not a basic diagram

Save to ./job-journal-architecture.png and print the file path when done.
PROMPT
"
```

## Alternative: Generate SVG instead

If matplotlib gives trouble, you can ask Gemini to generate an SVG directly:

```bash
gemini -p "Generate a single SVG file called job-journal-architecture.svg that visualizes the Job Journal architecture. [paste the same content above]"
```
