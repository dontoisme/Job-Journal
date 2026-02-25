# Job Journal vs. Interview Coach Skill — Deep Dive Comparison

> **Date:** 2026-02-25
> **Context:** [Noam Segal's Interview Coach Skill](https://github.com/noamseg/interview-coach-skill) was featured in [Lenny's Newsletter](https://www.lennysnewsletter.com/p/how-to-use-ai-in-your-next-job-interview) (Feb 2026). This document compares it with Job Journal (`jj`) to identify architectural differences, philosophical overlap, and concrete improvement opportunities.

---

## TL;DR

These are **complementary tools** with almost zero feature overlap. Interview Coach Skill is a **coaching brain** (pure markdown, no code, all qualitative). Job Journal is an **operations engine** (Python CLI + web dashboard, all quantitative infrastructure). Together they'd cover the full job search lifecycle. The biggest gap in Job Journal today is everything between "I submitted an application" and "I got an offer/rejection" — the *interview performance* layer.

---

## 1. Architecture Comparison

| Dimension | Job Journal | Interview Coach Skill |
|-----------|------------|----------------------|
| **Type** | Python CLI (Typer) + FastAPI web dashboard | Claude Code markdown skill (zero code) |
| **Language** | Python 3.10+, ~12,000+ lines | Markdown only (~15 reference docs) |
| **Database** | SQLite, 21 tables, 130+ query functions | Single file: `coaching_state.md` |
| **State** | Structured relational data | Flat markdown with sections |
| **Persistence** | `~/.job-journal/journal.db` | `coaching_state.md` in repo root |
| **Integrations** | Gmail, Google Docs, Google Maps, Greenhouse | None (self-contained) |
| **AI usage** | Minimal (OpenAI optional/reserved) | Claude as the entire runtime |
| **Activation** | `pip install -e .` then `jj <command>` | Rename `SKILL.md` to `CLAUDE.md` |
| **Web UI** | Full FastAPI dashboard at localhost:8000 | None |

**Key insight:** Interview Coach treats Claude as the application layer — the markdown *is* the program. Job Journal treats Claude as an assistant that operates a traditional software system.

---

## 2. Feature Coverage Matrix

### Job Search Lifecycle Stages

| Stage | Job Journal | Interview Coach | Gap Owner |
|-------|------------|----------------|-----------|
| **Company discovery** | Greenhouse polling, investor boards, geo search | `research` command (lightweight fit check) | JJ stronger |
| **Resume building** | Full corpus system, variant generation, Google Docs, drift scoring | Resume analysis at kickoff (feeds storybank) | JJ stronger |
| **Application tracking** | 21-table pipeline, status lifecycle, email pairing | Outcome Log (basic: company, result, notes) | JJ stronger |
| **TWC compliance** | Full biweekly tracking, payment requests, activity types | None | JJ only |
| **Email monitoring** | Gmail OAuth, auto-classification, confirmation pairing | None | JJ only |
| **Interview preparation** | None | `prep`, `research`, `stories`, `concerns`, `questions` | Coach only |
| **Interview practice** | None | 8-stage drill progression, `mock`, `practice` | Coach only |
| **Interview scoring** | None | 5-dimension rubric (1-5), seniority-calibrated | Coach only |
| **Post-interview debrief** | None | `debrief` (same-day rapid capture) | Coach only |
| **Negotiation** | None | `negotiate` (scripts, leverage, equity guidance) | Coach only |
| **Analytics** | Funnel stats, conversion rates, timeline, response rates | Progress trends, outcome correlation, score history | Different focus |
| **Confidence/psych prep** | None | `hype`, psychological readiness module | Coach only |
| **Thank-you/follow-up** | None | `thankyou` (multi-interviewer variants) | Coach only |

### Overlap Analysis

The two systems share exactly **one philosophical principle**: "SELECT, don't COMPOSE" — never fabricate content, always draw from the candidate's real experience. Beyond that, they occupy entirely different problem spaces.

---

## 3. What Interview Coach Does That Job Journal Doesn't

### 3.1 Storybank System
Interview Coach maintains a structured **storybank** — a collection of interview-ready stories in STAR format (Situation, Task, Action, Result) with:
- **Earned secrets** — counterintuitive insights extracted from each experience
- **Strength scoring** (1-5) per story
- **Last-used tracking** to prevent repetition across interview rounds
- **Gap analysis** by competency (leadership, data-driven, conflict resolution, etc.)
- **Rapid-retrieval drill** — 10 rapid-fire prompts to test recall under pressure
- **Narrative identity** — 2-3 core themes that define the candidate across stories

**Job Journal's corpus** has bullets but not stories. Entries are resume lines, not interview narratives. There's no STAR structure, no earned-secrets extraction, no competency mapping.

### 3.2 Five-Dimension Scoring Framework
Every answer is scored on:
1. **Substance** — Evidence quality and depth
2. **Structure** — Narrative clarity and flow
3. **Relevance** — Question fit and focus
4. **Credibility** — Believability and proof
5. **Differentiation** — Uniqueness and spiky POVs

Scores are calibrated by seniority level (early career through executive), with detailed anchors for each level. This is the most innovative part of the system — especially the **differentiation** dimension, which most prep tools ignore entirely.

### 3.3 Root Cause Diagnosis
Instead of generic "practice more" advice, the coach identifies **why** answers are weak:
- Inability to identify question core
- Reflexive "we" framing (hiding individual contribution)
- Conflict avoidance in storytelling
- Status anxiety (overselling to compensate)
- Narrative hoarding (cramming too much in)
- Fear of being wrong
- Anxiety/stress response
- Cultural/linguistic differences

Each root cause gets targeted drills, not one-size-fits-all practice.

### 3.4 Interview Loop Tracking
Tracks multi-round interview processes per company:
- Which rounds completed, what format each was
- Which stories used in which round (prevents repetition)
- Concerns surfaced by interviewers
- Interviewer intelligence (LinkedIn-based analysis)
- Predicted questions for next round

### 3.5 Progression System
An 8-stage practice ladder with gating thresholds:
1. Constraint ladder (time compression)
2. Pushback handling
3. Pivot practice
4. Gap coverage
5. Role-specific drills
6. Panel simulation
7. Stress testing
8. Technical+behavioral mix

Candidates can't skip ahead without demonstrating competence at earlier stages.

### 3.6 Psychological Readiness
- Pre-interview warmup routines and physical reset
- Mid-interview recovery scripts (handling "bomb" questions, lost thoughts)
- Post-interview processing (structured debrief instead of spiraling)
- Emotional triage based on how the candidate feels after

### 3.7 Negotiation Coaching
Full post-offer support:
- Offer analysis and market comparison
- Leverage assessment
- Exact counter-offer scripts
- Equity guidance and evaluation
- Multi-offer scenario navigation

---

## 4. What Job Journal Does That Interview Coach Doesn't

### 4.1 Production Infrastructure
- **21-table SQLite database** with 130+ query functions
- **Background worker daemon** for scheduled tasks
- **FastAPI web dashboard** with real-time analytics
- **OAuth integrations** (Gmail, Google Docs, Google Maps)

### 4.2 Resume Generation Pipeline
- Corpus of curated bullets with usage tracking and success rates
- 5 resume variants (growth, ai-agentic, health-tech, consumer, general)
- Template-based DOCX and Google Docs generation
- Resume-JD scoring rubric (summary 25pts, skills 25pts, bullets 35pts, keywords 15pts)
- Drift detection (are resume bullets still in corpus?)
- Import and validate existing resumes

### 4.3 Email Intelligence
- Gmail OAuth with read-only scope
- Automatic classification of application confirmations, rejections, interview invites
- Email-to-application pairing (confirmation + resolution lifecycle)
- Domain mapping for company identification
- Background sync with event logging

### 4.4 Job Discovery
- Greenhouse internal API polling
- 20+ VC/investor job board aggregation (a16z, Sequoia, Greylock, etc.)
- Austin-area geographic discovery via Google Maps
- ATS detection and autofill field mapping (Ashby, Greenhouse, Lever, Workday, etc.)

### 4.5 TWC Compliance Automation
- Biweekly claim period tracking (Sunday-Saturday weeks)
- 6 activity types with employer contact details
- Payment request submission tracking
- Activity date backfill from email timestamps
- Web dashboard for compliance status

### 4.6 Analytics Engine
- Application funnel (applied -> screening -> interview -> offer)
- Time-in-stage statistics
- Company response rate ranking
- Weekly activity summaries
- Pipeline visualization

---

## 5. Philosophical Differences

| Principle | Job Journal | Interview Coach |
|-----------|------------|----------------|
| **Core metaphor** | Journal / ledger | Coach / trainer |
| **Primary value** | Automation & tracking | Qualitative improvement |
| **Data model** | Structured, relational | Narrative, markdown |
| **AI role** | Tool operator (Claude runs the CLI) | The coach itself (Claude *is* the product) |
| **User interaction** | Commands produce output | Conversations produce growth |
| **Success metric** | Applications submitted, compliance met | Interview scores improved, offers received |
| **Time horizon** | Daily operations | Weeks-to-months of skill building |
| **"SELECT don't COMPOSE"** | Applied to resume bullets | Applied to interview stories |

---

## 6. Improvement Opportunities for Job Journal

Beyond coaching and interview prep (which the Interview Coach handles well as a standalone skill), here are concrete improvements inspired by the comparison:

### 6.1 Storybank Layer on Top of Corpus (High Impact)
**What:** Extend the existing corpus entries into full interview stories.

The corpus already has resume bullets — atomic achievement statements. A storybank would group related bullets into narrative arcs with STAR structure, competency tags, and usage tracking across interviews (not just resumes).

**Why it matters:** Resume bullets and interview stories serve different purposes. "Increased activation 34% through experimentation program" is a great bullet but a terrible interview answer. The story behind it — the context, the failed approaches, the insight that led to the solution — is what interviewers want.

**Implementation sketch:**
- New `stories` table: `id, title, situation, task, action, result, earned_secret, competencies (JSON), strength (1-5), last_used_at, times_used, entry_ids (JSON)`
- Link stories to corpus entries via `entry_ids` — the bullet is the punchline, the story is the context
- CLI: `jj corpus stories` to list, `jj corpus story add` to create
- Web dashboard: story browser with competency gap visualization

### 6.2 Interview Loop Tracking (High Impact)
**What:** Track multi-round interview processes within the existing application pipeline.

**Why it matters:** Job Journal already tracks applications through statuses, but an application at "interview" stage could mean phone screen, technical round, or final panel. Knowing which round you're in, what format to expect, and what stories you've already used matters.

**Implementation sketch:**
- New `interview_rounds` table: `id, application_id, round_number, format (behavioral/technical/system_design/panel/case), scheduled_at, completed_at, interviewer_name, interviewer_role, stories_used (JSON), notes, outcome`
- Extend `jj app` sub-app with `jj app rounds <app_id>` and `jj app add-round <app_id>`
- Web dashboard: timeline view per application showing round progression

### 6.3 Post-Interview Debrief Capture (Medium Impact)
**What:** A `jj app debrief <app_id>` command for structured post-interview capture.

**Why it matters:** Same-day capture of what went well, what didn't, which stories landed, and what questions surprised you is invaluable data. Currently this falls into unstructured `notes` or gets lost entirely.

**Implementation sketch:**
- New `debriefs` table: `id, application_id, round_id, debrief_date, went_well, to_improve, surprising_questions, stories_that_landed (JSON), stories_that_flopped (JSON), interviewer_signals, confidence_level (1-5), follow_up_needed`
- Claude Code slash command `/debrief` that prompts through the capture flow
- Feed debrief data back into story strength scores

### 6.4 Company Intelligence Caching (Medium Impact)
**What:** Structured company research storage beyond the current `companies` table.

The existing `companies` table has basic contact info and ATS type. Interview Coach's `research` command captures culture signals, interview format intelligence, and fit assessment — data worth persisting.

**Implementation sketch:**
- Extend `companies` table: `interview_formats (JSON), culture_signals (JSON), glassdoor_notes, fit_score (1-5), last_researched_at`
- Or new `company_intel` table for versioned research snapshots
- `jj app research <company>` to trigger and store research
- Web dashboard: company detail page with accumulated intelligence

### 6.5 Outcome Correlation Analytics (Medium Impact)
**What:** Correlate interview preparation activities with advancement outcomes.

**Why it matters:** Job Journal has the pipeline data (which applications advance, which get rejected) but doesn't connect it to preparation quality. Adding this would answer: "Do I advance further when I prep more? Which companies respond better to which resume variant?"

**Implementation sketch:**
- Extend existing analytics module with:
  - Resume variant vs. advancement rate
  - Prep time (if tracked) vs. outcome
  - Story usage frequency vs. interview success
  - Company research depth vs. response rate
- New analytics dashboard panel: "What's working?"

### 6.6 Follow-Up / Thank-You Tracking (Low Impact)
**What:** Track whether thank-you notes were sent after interviews.

**Implementation sketch:**
- Add `thank_you_sent_at` to `interview_rounds` table (if added)
- Or track in `events` table as `thank_you_sent` event type
- Dashboard reminder: "You interviewed at X yesterday — send a thank you?"

### 6.7 Negotiation State Tracking (Low Impact)
**What:** When applications reach "offer" status, track negotiation state.

**Implementation sketch:**
- New `offers` table: `id, application_id, base_salary, equity, bonus, signing_bonus, benefits_notes, deadline, counter_offer_sent, final_package, accepted_at`
- `jj app offer <app_id>` to record and compare offers
- Side-by-side comparison view in web dashboard

### 6.8 Coaching State Integration Point (Low Effort, High Strategic Value)
**What:** Add a convention for Interview Coach's `coaching_state.md` to live in `~/.job-journal/coaching_state.md`, and add a `jj coach` sub-app that reads/displays its contents.

**Why it matters:** If a user runs both tools, having the coaching state in Job Journal's data directory means the web dashboard could display interview readiness alongside pipeline status. No need to rebuild the coaching logic — just read the state file.

**Implementation sketch:**
- `jj coach status` — parse and display coaching state summary
- `jj coach scores` — show score history trend
- `jj coach stories` — list storybank entries
- Web dashboard: "Interview Readiness" panel that reads `coaching_state.md`

---

## 7. What NOT to Build (Keep Boundary Clean)

Some Interview Coach features should stay as a separate skill rather than being absorbed into Job Journal:

| Feature | Why Keep Separate |
|---------|------------------|
| **Practice drills & mocks** | Interactive coaching sessions don't fit a CLI/dashboard pattern |
| **Real-time scoring** | Requires conversational AI, not structured data |
| **Root cause diagnosis** | Qualitative coaching, not automation |
| **Psychological readiness** | Personal coaching territory |
| **Triage decision trees** | Adaptive AI behavior, not stored state |
| **Earned secrets extraction** | Deep conversational exercise |

The right boundary: **Job Journal tracks what happened and what's next. Interview Coach makes you better at what's next.** Job Journal should capture the *results* of coaching (scores, stories, readiness) but not try to *be* the coach.

---

## 8. Integration Architecture (If Both Tools Are Used)

```
┌─────────────────────────────────────────────────────┐
│                   ~/.job-journal/                     │
│                                                       │
│  ┌──────────────┐          ┌───────────────────────┐ │
│  │  journal.db   │          │  coaching_state.md     │ │
│  │  (21 tables)  │◄─reads──│  (Interview Coach)     │ │
│  │               │          │                         │ │
│  │  applications │          │  storybank              │ │
│  │  companies    │          │  score_history           │ │
│  │  entries      │          │  interview_loops         │ │
│  │  resumes      │          │  outcome_log             │ │
│  │  stories (new)│──feeds──►│  drill_progression      │ │
│  │  rounds (new) │          │  coaching_strategy       │ │
│  │  debriefs(new)│          └───────────────────────┘ │
│  └──────────────┘                                     │
│         │                            │                 │
│         ▼                            ▼                 │
│  ┌──────────────┐          ┌───────────────────────┐ │
│  │  jj CLI       │          │  Claude Code Skill     │ │
│  │  + Web Dash   │          │  (Interview Coach)     │ │
│  │               │          │                         │ │
│  │  Track        │          │  Coach                  │ │
│  │  Automate     │          │  Practice               │ │
│  │  Report       │          │  Score                  │ │
│  └──────────────┘          └───────────────────────┘ │
│                                                       │
│         ▲                            ▲                 │
│         │          shared            │                 │
│         └───── corpus entries ───────┘                 │
│                (SELECT, don't COMPOSE)                 │
└─────────────────────────────────────────────────────┘
```

**Data flows:**
1. Job Journal corpus entries seed Interview Coach storybank (bullets become story punchlines)
2. Interview Coach outcome log feeds back into Job Journal application statuses
3. Interview Coach score trends display on Job Journal web dashboard
4. Job Journal interview rounds inform Interview Coach's loop tracking
5. Both tools share the "SELECT, don't COMPOSE" philosophy — stories and bullets come from real experience

---

## 9. Priority Ranking

If implementing improvements, this is the suggested order based on impact and effort:

| Priority | Improvement | Effort | Impact | Rationale |
|----------|------------|--------|--------|-----------|
| **P0** | Coaching state integration point | Low | High | Zero-code bridge — just read the markdown file |
| **P1** | Storybank layer on corpus | Medium | High | Biggest structural gap; extends existing corpus |
| **P2** | Interview round tracking | Medium | High | Natural extension of application pipeline |
| **P3** | Post-interview debrief capture | Low | Medium | Simple table + slash command, high data value |
| **P4** | Company intelligence caching | Low | Medium | Small schema extension, big UX improvement |
| **P5** | Outcome correlation analytics | Medium | Medium | Requires data accumulation before value shows |
| **P6** | Follow-up tracking | Low | Low | Nice-to-have operational hygiene |
| **P7** | Negotiation state tracking | Low | Low | Only relevant at offer stage |

---

## 10. Summary

**Interview Coach Skill** is a brilliantly designed coaching system that treats Claude as the entire application layer. It's all qualitative: making you better at telling your story, handling pressure, and reading signals. It has no infrastructure, no database, no integrations — and it doesn't need them.

**Job Journal** is a production-grade operations engine that automates the logistics of job searching: tracking applications, syncing emails, generating resumes, meeting compliance requirements, and surfacing analytics. It's all quantitative infrastructure.

The gap between them is the **interview performance layer** — the space between "application submitted" and "outcome received." Job Journal knows *what* happened but not *how well*. Interview Coach knows *how well* but not the operational context.

The highest-leverage improvement isn't rebuilding coaching features — it's **bridging the two systems** so that coaching quality data flows into the operational pipeline, and pipeline context informs coaching priorities. A lightweight integration point (P0 above) gets 80% of the value with 10% of the effort.

---

*Sources: [noamseg/interview-coach-skill](https://github.com/noamseg/interview-coach-skill) | [How to use AI for your next job interview — Lenny's Newsletter](https://www.lennysnewsletter.com/p/how-to-use-ai-in-your-next-job-interview)*
