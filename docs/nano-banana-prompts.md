# Nano Banana Pro — Paste-Ready Prompts

## 1. Three-Tier Autonomous Pipeline

Create a polished dark-background infographic flow diagram.
Title: "3-Tier Job Search Pipeline"
App: Autonomous job search engine — Python CLI that discovers, scores, and applies to jobs with zero interaction.

Steps:
1. 🎯 Tier 1: /pipeline — Interactive batch. Scrape career pages → title pre-filter (50+) → USER APPROVAL → corpus score (70+) → generate resume → validate drift=0
2. 🔄 Tier 2: /swarm — Semi-auto daily. Parallel subagents (batches of 3-5) → delta detection → auto-score (65+) → auto-resume. No approval gates.
3. 🤖 Tier 3: /monitor — Fully headless LaunchAgent. Email sync → scrape → delta detect → score → resume (cap 3/run) → Slack notification. Runs 06:00 & 12:00.

Visual treatment:
- Tier 1 in cyan (#00d4ff), Tier 2 in orange (#ff6b35), Tier 3 in green (#00e676)
- Approval gates shown as diamond decision nodes
- Arrow from each tier pointing down to show increasing autonomy
- Badge on Tier 3: "Zero Human Interaction"

Style: dark background (#1a1a2e), modern sans-serif, premium tech aesthetic.
Diagram only — no photographs, no people.

---

## 2. Architecture Layers

Create a polished dark-background infographic flow diagram.
Title: "Job Journal — Architecture Stack"
App: Python CLI + Claude Code skills + Google APIs for autonomous career management.

Steps:
1. 🧠 Layer 1: Claude Code Skills — 13 prompt-driven skills (/apply, /pipeline, /swarm, /monitor, /interview, /twc, /score, /fit, /jobs, /greenhouse, /vc-boards, /start-today, /learn)
2. ⚡ Layer 2: Python CLI (jj) — 11 Typer sub-apps, 30+ commands (corpus, resume, email, greenhouse, app, gdocs, worker, investors, monitor, notify, interests)
3. 💾 Layer 3: Data — SQLite (24 tables) + Gmail API + Google Docs API + Slack webhooks

Visual treatment:
- Purple (#bb86fc) for skills layer, cyan (#00d4ff) for CLI layer, orange (#ff6b35) for data layer
- Downward arrows between layers showing: Skills orchestrate → CLI executes → Data persists
- Small icons for external APIs (envelope for Gmail, doc for Docs, bell for Slack)

Style: dark background (#1a1a2e), modern sans-serif, premium tech aesthetic.
Diagram only — no photographs, no people.

---

## 3. Resume Generation Pipeline

Create a polished dark-background infographic flow diagram.
Title: "SELECT, Don't COMPOSE — Resume Pipeline"
App: Job search engine that selects real resume bullets from a corpus — never fabricates.

Steps:
1. 📋 JD URL fetched → keywords extracted via _extract_jd_keywords()
2. 🎯 Corpus bullets scored for relevance via _score_bullet_relevance()
3. 📊 4-category fit score (Skills 35pts + Experience 25pts + Domain 25pts + Location 15pts)
4. ✅ Resume-JD match gate: 85+ required (Summary 25 + Skills 25 + Bullets 35 + Keywords 15)
5. 📄 Google Docs template copy → placeholder substitution → bold formatting → empty section removal
6. 📥 PDF export → ~/Documents/Resumes/YYYY-MM-DD/ folder
7. 🔒 Validation: drift_score must equal 0 — any fabricated bullet blocks the resume

Visual treatment:
- Accent color: teal (#00bfa5)
- Highlight the drift_score=0 validation as a red stop gate
- Show the two scoring rubrics as small embedded tables
- Badge: "Every bullet traceable to corpus"

Style: dark background (#1a1a2e), modern sans-serif, premium tech aesthetic.
Diagram only — no photographs, no people.

---

## 4. Email Pairing & Status Lifecycle

Create a polished dark-background infographic flow diagram.
Title: "Gmail Integration — Email Pairing Lifecycle"
App: Automated email classification that pairs confirmation + resolution emails to track application status.

Steps:
1. 📧 Gmail API (read-only OAuth) scans inbox using ATS domain patterns (greenhouse, lever, ashby, smartrecruiters)
2. 🔍 Email classified: confirmation vs resolution via RESOLUTION_SIGNALS keywords
3. 🔗 Paired to application record in application_emails table (one confirmation + one resolution per app)
4. 🔄 Auto-status transition: rejection email → status="rejected", interview email → status="interview"
5. 👻 Ghost detection: confirmed > 14 days with no resolution → pairing_status="ghosted"
6. 🔔 Slack notification with sync summary (confirmations found, resolutions matched)

Visual treatment:
- Accent color: coral (#ff7043)
- Show the status lifecycle as a horizontal flow: prospect → applied → screening → interview → offer/rejected/withdrawn
- Email pairing shown as two arrows converging on a single application node
- Ghost detection shown with a dashed timeout arrow

Style: dark background (#1a1a2e), modern sans-serif, premium tech aesthetic.
Diagram only — no photographs, no people.

---

## 5. Data Model Overview

Create a polished dark-background infographic flow diagram.
Title: "24-Table SQLite Schema"
App: Single-database career management engine tracking corpus, resumes, applications, jobs, and compliance.

Steps:
1. 📝 Corpus cluster: roles → entries (bullets) → skills → education
2. 📄 Resume cluster: resumes → resume_entries + resume_sections → corpus_suggestions + jd_cache
3. 💼 Application cluster: applications → application_emails, linked to companies and resumes
4. 🔎 Discovery cluster: companies → job_listings (UNIQUE on company+url for delta detection), investor_boards → investor_board_jobs
5. ⚙️ System cluster: tasks (worker queue), events (audit log), monitor_runs, twc_payment_requests, interview_sessions

Visual treatment:
- Accent color: gold (#ffd740)
- Show as 5 grouped clusters with FK arrows between them
- Highlight the delta detection mechanism (UNIQUE constraint badge on job_listings)
- Show the applications table as the central hub with most FK connections

Style: dark background (#1a1a2e), modern sans-serif, premium tech aesthetic.
Diagram only — no photographs, no people.

---

## 6. Job Journal — System Overview

Create a polished dark-background infographic flow diagram.
Title: "Job Journal — Autonomous Job Search Engine"
App: A one-person engineering project that turns job hunting into a managed pipeline. Python CLI + Claude Code AI skills + Google APIs.

Steps:
1. 🔎 DISCOVER — Scrape 50+ company career pages and VC portfolio boards. Delta detection ensures only new listings are processed.
2. 📊 SCORE — Every job scored 0-100 on a 4-category rubric: Skills Match (35), Experience (25), Domain Fit (25), Location (15).
3. 📄 GENERATE — Tailored resumes built by selecting real bullets from a corpus of past work. Zero fabrication enforced via drift validation.
4. 📧 TRACK — Gmail integration auto-classifies confirmation and rejection emails. Pairs them to applications. Detects ghosting after 14 days.
5. ✅ COMPLY — Texas Workforce Commission requires 3 activities/week. System tracks activity types, dates, and biweekly claim periods automatically.
6. 🔔 NOTIFY — Slack messages with scored jobs, resume links, and email sync summaries. Delivered twice daily by headless LaunchAgent.

Visual treatment:
- Show as a circular or hexagonal hub-and-spoke: "Job Journal" in the center, 6 spokes radiating out to each step
- Each spoke gets its own accent color: cyan (#00d4ff) Discover, orange (#ff6b35) Score, teal (#00bfa5) Generate, coral (#ff7043) Track, purple (#bb86fc) Comply, green (#00e676) Notify
- Center hub badge: "24 SQLite tables · 13 AI skills · 30+ CLI commands"
- Bottom tagline: "Built by one PM. Runs autonomously. Every bullet real."
- Key stats as small pill badges around the border: "3-Tier Pipeline", "Gmail + Google Docs + Slack", "Zero fabrication policy"

Style: dark background (#1a1a2e), modern sans-serif, premium tech aesthetic.
Diagram only — no photographs, no people.
