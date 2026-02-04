# Job Journal System Overview

A complete reference for the Job Journal CLI and its components.

---

## Core Components

### 1. Resume Corpus (Your Experience Database)

**Tables:**
| Table | Purpose |
|-------|---------|
| `roles` | Job history (company, title, dates) |
| `entries` | Individual bullet points tied to roles |
| `skills` | Skills with categories |
| `tags` | Labels for filtering entries |

**Principle:** "SELECT, don't COMPOSE" — resumes pull verbatim bullets from the corpus, never invented.

**Build it:** Use `/interview` skill for guided Q&A about past experiences.

---

### 2. Companies (Target List)

**Key fields:** name, industry, ats_type, careers_url, board_token, target_priority

**Purpose:** Track companies you're interested in, with metadata for job discovery.

**Future:** ATS job monitoring to auto-discover new postings (see `jj/notes/ats-job-monitoring.md`)

---

### 3. Job Sourcing / Discovery

| Method | Skill | Status |
|--------|-------|--------|
| Greenhouse search | `/greenhouse` | Working |
| Browse jobs | `/jobs` | Working |
| Manual entry | — | Working |
| ATS auto-poll | — | Planned |

**Flow:** Discovery → Prospect → Application

---

### 4. Prospects & Applications

**Prospect fields:** company, position, job_url, job_description, fit_score, notes

**Application lifecycle:**
```
prospect → applied → recruiter_screen → hiring_manager → interview → offer
                                                                   ↓
                                                              (or rejected at any stage)
```

**Tracking tables:**
- `applications` — Status, dates, notes, resume used
- `application_events` — Timeline of status changes
- `application_contacts` — People you've talked to

---

### 5. JD Scoring

**Rubric (from `/resume-workflow`):**

| Category | Points | What's Evaluated |
|----------|--------|------------------|
| Summary alignment | 25 | Does summary use JD's key terms? |
| Skills coverage | 25 | Do skills match JD requirements? |
| Bullet relevance | 35 | Do lead bullets demonstrate JD requirements? |
| Keyword density | 15 | Are JD keywords present throughout? |

**Target:** 80+ before submitting

---

### 6. Resume Customization

**Levers:**
1. `custom_summary` — Mini cover letter tailored to role (3-4 sentences)
2. `skill_categories` — Reorder categories for JD fit
3. Bullet selection — (future) Select most relevant entries

**Generation:** `jj/google_docs.py` → Google Docs API → PDF

**Workflow:** `/resume-workflow` skill

---

### 7. Skills Table

Skills are stored separately from experience entries, organized by category.

**Categories available:**
| Category | Example Skills |
|----------|---------------|
| product-management | Product Strategy, Product Vision, Roadmap Planning |
| technical | API Design, API Integrations, Event-Driven Architecture |
| leadership | Executive Communication, Cross-Functional Collaboration |
| analytics-&-tools | SQL, Amplitude, Mixpanel, PostHog, Segment CDP |
| growth-&-experimentation | Growth Strategy, Growth Loops, Funnel Optimization |
| health-tech | EHR Integration, Pharmacy Operations, Clinical Workflows |
| ai-&-orchestration | Agentic AI, Multi-Agent Systems, Workflow Automation |

---

## Available Skills (Commands)

| Skill | Purpose |
|-------|---------|
| `/interview` | Build corpus through guided Q&A |
| `/jobs` | Browse and manage job prospects |
| `/apply` | Full application workflow |
| `/greenhouse` | Search Greenhouse job boards |
| `/resume-workflow` | Generate tailored resume with scoring |
| `/score` | Score resume against JD |
| `/hunt` | Find new roles to apply to |

---

## Database Schema

**16 total tables:**

**Corpus:**
- `roles` — Work history
- `entries` — Experience bullets
- `skills` — Skills by category
- `tags` — Labels for entries
- `entry_tags` — Many-to-many junction

**Companies & Jobs:**
- `companies` — Target company list
- `prospects` — Jobs under consideration

**Applications:**
- `applications` — Active applications
- `application_events` — Status history
- `application_contacts` — People involved

**Resumes:**
- `resumes` — Generated resumes
- `resume_entries` — Bullets used per resume

---

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.job-journal/config.yaml` | Output settings, Google Docs template ID, variants |
| `~/.job-journal/profile.yaml` | Contact info, variant summaries, defaults |
| `~/.job-journal/job-journal.db` | SQLite database |

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        CORPUS (Your Data)                        │
│  ┌─────────┐  ┌─────────┐  ┌────────┐  ┌─────────┐             │
│  │  roles  │──│ entries │──│  tags  │  │ skills  │             │
│  └─────────┘  └─────────┘  └────────┘  └─────────┘             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DISCOVERY & TARGETING                       │
│  ┌───────────┐  ┌───────────┐  ┌─────────────┐                 │
│  │ companies │  │ /greenhouse│  │  prospects  │                 │
│  │ (targets) │  │ /jobs      │  │ (reviewing) │                 │
│  └───────────┘  └───────────┘  └─────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     RESUME GENERATION                            │
│  ┌────────────────┐  ┌─────────────┐  ┌──────────────┐         │
│  │ /resume-workflow│──│ Google Docs │──│ Score vs JD  │         │
│  │ custom_summary  │  │   API       │  │ Optimize     │         │
│  │ skill_categories│  └─────────────┘  └──────────────┘         │
│  └────────────────┘                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     APPLICATION TRACKING                         │
│  ┌──────────────┐  ┌─────────────────┐  ┌────────────────┐     │
│  │ applications │──│ application_    │──│ application_   │     │
│  │              │  │ events          │  │ contacts       │     │
│  └──────────────┘  └─────────────────┘  └────────────────┘     │
│                                                                  │
│  Status: applied → recruiter_screen → interview → offer          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Related Documentation

| Doc | Location |
|-----|----------|
| ATS Job Monitoring | `jj/notes/ats-job-monitoring.md` |
| Resume Workflow | `~/.claude/commands/resume-workflow.md` |
| Greenhouse Integration | `docs/greenhouse.md` |
