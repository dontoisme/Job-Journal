# /pipeline - Autonomous Job Search Pipeline

Discover jobs at target companies, score fit, auto-generate tailored resumes for 70+ fits, validate content integrity, and update the application tracker -- all in one run.

## Usage

```
/pipeline                              # Run full pipeline against all target companies
/pipeline --company "Figma"            # Run for a single company
/pipeline --phase 2                    # Resume from a specific phase (if prior phases completed)
/pipeline --output-dir ~/Desktop/batch # Override default output folder
/pipeline --threshold 80               # Override auto-resume threshold (default: 70)
```

## Overview

This skill orchestrates 5 sequential phases:

1. **Scrape** - Fetch job listings from target company career pages
2. **Score** - Assess fit for each new job against your corpus
3. **Resume** - Auto-generate tailored resumes for all jobs scoring at or above the threshold (default 70+)
4. **Validate** - Verify no fabricated content in generated resumes
5. **Track** - Update the application database, generate a run summary, and produce a markdown brief

Approval gate pauses between Phase 1→2 for user review. Phase 2→3 is **automatic** for all jobs at or above the threshold (default 70). A markdown brief with JD links, fit rationale, and posting age is saved alongside the resumes.

### Output Folder

All resumes and the summary brief are saved to a **dated folder** by default:

```
~/Documents/Resumes/YYYY-MM-DD/
```

Override with `--output-dir <path>`. The folder is created automatically if it doesn't exist.

---

## Phase 1: Scrape (Career Pages)

### 1a. Load Target Companies

Query active target companies from the database:

```python
from jj.config import DB_PATH
import sqlite3

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
targets = conn.execute("""
    SELECT id, name, careers_url, ats_type
    FROM companies
    WHERE is_target = 1 AND careers_url IS NOT NULL
    ORDER BY target_priority DESC, name
""").fetchall()
conn.close()
```

If the user passed `--company`, filter to just that company.

Report how many targets have career URLs:
```
## Phase 1: Scrape

Checking career pages for X target companies...
```

Create a TodoWrite task: `"Scrape career pages for X target companies"`

### 1b. Scrape Each Career Page

For each company with a `careers_url`:

1. Use **WebFetch** to read the career page
   - Prompt: "Extract all job listings from this career page. For each job return: title, URL, location, salary (if visible). Return as a JSON array of objects with keys: title, url, location, salary."
2. If WebFetch fails or returns no jobs, log a warning and continue to the next company
3. For each extracted job, validate the URL is accessible (WebFetch quick check -- skip if 404/unreachable)

### 1c. Deduplicate Against Known Jobs

Before adding any scraped job, check if we've seen it before — in **both** `job_listings` (all previously scraped jobs, including filtered/skipped ones) **and** `applications` (jobs we're actively tracking):

```python
from jj.db import is_known_job

for job in scraped_jobs:
    known = is_known_job(job["url"])
    if known:
        # Skip — already seen (source: job_listings or applications)
        skipped_dups.append(job)
        continue
```

Skip any job where `is_known_job()` returns a match. This ensures that jobs filtered out by title pre-filter, scored but below threshold, or already tracked as prospects/applied are never reconsidered.

### 1c-ii. Record All Scraped Jobs

After dedup and before any filtering, record **every new** scraped job in `job_listings` so future runs know we've seen it:

```python
from jj.db import record_job_listing

for job in all_new_scraped_jobs:
    record_job_listing(
        company_id=job["company_id"],
        url=job["url"],
        title=job["title"],
        location=job.get("location"),
        salary=job.get("salary"),
        ats_type=job.get("ats_type"),
    )
```

This is the critical step that prevents filtered-out jobs from reappearing on subsequent runs.

### 1d. Write Scrape Results

Write results to `jobs/scraped.json`:

```json
{
  "scraped_at": "2026-02-11T10:00:00",
  "companies_checked": 15,
  "jobs_found": 42,
  "jobs_new": 28,
  "jobs_skipped_duplicate": 14,
  "jobs": [
    {
      "company": "Figma",
      "company_id": 42,
      "title": "Senior PM, Growth",
      "url": "https://...",
      "location": "Remote",
      "salary": "$180k-$250k",
      "ats_type": "greenhouse",
      "source": "careers_page"
    }
  ]
}
```

Create a TodoWrite task for each new job: `"Score: [Company] - [Title]"` (pending Phase 2).

### 1e. Title Pre-Filter

Before presenting results, run the title+location pre-filter on all new listings to remove obvious non-fits (international roles, product marketing, data analyst, wrong seniority):

```python
from jj.db import score_title_fit

for job in new_jobs:
    result = score_title_fit(title=job["title"], location=job["location"])
    job["title_score"] = result["total"]
    job["title_pass"] = result["pass"]  # threshold: 50+
```

Only listings with `title_pass = True` (score >= 50) are included in the scrape results presented to the user. Filtered-out listings are noted in a summary line.

### 1f. Approval Gate

Present results to the user:

```
## Scrape Results

| # | Company | Title | Location | Salary | ATS | Title Score |
|---|---------|-------|----------|--------|-----|-------------|
| 1 | Figma | Sr PM, Growth | Remote | $180k-$250k | greenhouse | 90 |
| 2 | Stripe | PM, Dev Tools | SF/Remote | $190k-$270k | lever | 75 |
...

**Companies checked:** 15
**Jobs found:** 42
**New (not duplicates):** 28
**Passed title filter (50+):** 22
**Filtered out:** 6 (international, product marketing, data analyst)

Proceed to scoring? [Y/n]
```

**Wait for user confirmation before proceeding to Phase 2.**

---

## Phase 2: Score (Fit Assessment)

### 2a. Load Corpus

Read the user's professional corpus for scoring context:

```python
from jj.config import CORPUS_PATH
corpus = CORPUS_PATH.read_text()
```

If corpus doesn't exist, stop: "No corpus found. Run `/interview` first to build your professional story."

### 2b. Detect Archetype & Score Each Job

For each new job from Phase 1:

1. Use **WebFetch** to fetch the full job description from the job URL

2. **Detect archetype:** Classify the JD against `config.variants` keyword lists (growth, ai-agentic, health-tech, consumer, general). Pick the variant with the highest keyword overlap. This determines how scoring notes are framed and which resume variant is auto-selected in Phase 3.

3. Score fit (0-100) using the 4-category rubric:

| Category | Weight | What to Evaluate |
|----------|--------|------------------|
| **Skills Match** | 35 pts | JD required skills vs corpus skills |
| **Experience Level** | 25 pts | Seniority alignment (title, years) |
| **Domain Fit** | 25 pts | Domain tag overlap (AI, growth, health-tech, platform, consumer) |
| **Location/Remote** | 15 pts | Location compatibility with profile preferences |

4. Assign verdict:

| Score | Verdict |
|-------|---------|
| 80-100 | Strong Fit |
| 65-79 | Good Fit |
| 50-64 | Moderate Fit |
| <50 | Stretch |

5. Write detailed reasoning for each category (score, max, notes). Frame notes through the detected archetype — e.g., for `ai-agentic`, specifically assess orchestration, agent framework, and LLM experience in the skills assessment.

6. **For jobs scoring 65+**, generate additional analysis:

   **Comp research:** If salary not known from JD, use WebSearch for `"{company} {position} salary glassdoor levels.fyi"`. Store in `salary_range`.

   **Evaluation report:** Generate a structured 3-block report:
   - Block 1 (Role Summary): Archetype, domain, seniority, remote policy, TL;DR
   - Block 2 (Match Analysis): JD requirements mapped to corpus entries, gaps with mitigation strategies
   - Block 3 (Interview Prep): 3-5 STAR+R stories mapped to key JD requirements

   Save the report:
   ```python
   from jj.db import create_evaluation_report
   create_evaluation_report(
       application_id=app_id,
       report_type="fit",
       skills_score=skills_score, skills_notes=skills_notes,
       experience_score=exp_score, experience_notes=exp_notes,
       domain_score=domain_score, domain_notes=domain_notes,
       location_score=loc_score, location_notes=loc_notes,
       role_summary=role_summary_text,
       match_analysis=match_analysis_text,
       interview_prep=interview_prep_text,
       comp_research=comp_research_text,
       jd_url=url, jd_snapshot=jd_text,
   )
   ```

   **Story bank:** Save new STAR+R stories (deduplicate by `source_entry_ids`):
   ```python
   from jj.db import create_story, get_stories
   existing = get_stories()
   for story in generated_stories:
       is_dup = any(s.get("source_entry_ids") == story["source_entry_ids"] for s in existing if s.get("source_entry_ids"))
       if not is_dup:
           create_story(
               title=story["title"], situation=story["situation"],
               task=story["task"], action=story["action"],
               result=story["result"], reflection=story["reflection"],
               source_entry_ids=story.get("source_entry_ids"),
               jd_requirements_matched=story.get("requirements_matched"),
           )
   ```

### 2c. Deduplicate Before Inserting

Before creating a new application, check for existing duplicates:

```python
from jj.db import find_duplicate_application

existing = find_duplicate_application(company=job["company"], position=job["title"], job_url=job["url"])
if existing:
    # Skip — already tracked as app #{existing['id']} ({existing['status']}, fit: {existing['fit_score']}%)
    continue
```

### 2d. Insert Prospects

For each scored job (that passed dedup), insert a prospect record:

```python
from jj.db import create_application

app_id = create_application(
    company=job["company"],
    position=job["title"],
    job_url=job["url"],
    location=job["location"],
    salary_range=job["salary"],
    ats_type=job["ats_type"],
    fit_score=score,
    status="prospect",
    notes=f"Fit: {score}% ({verdict}). Archetype: {archetype}. {reasoning_summary}",
)
```

Record the `app_id` for later updates. **Note:** Evaluation reports and story bank entries (from Step 2b item 6) are generated after this insert, since they need the `app_id`.

### 2e. Write Scored Results

Write results to `jobs/scored.json`:

```json
{
  "scored_at": "2026-02-11T10:30:00",
  "total_scored": 28,
  "above_threshold": 8,
  "jobs": [
    {
      "company": "Figma",
      "title": "Senior PM, Growth",
      "url": "...",
      "fit_score": 85,
      "verdict": "Strong Fit",
      "reasoning": {
        "skills_match": {"score": 30, "max": 35, "notes": "..."},
        "experience_level": {"score": 22, "max": 25, "notes": "..."},
        "domain_fit": {"score": 20, "max": 25, "notes": "..."},
        "location": {"score": 13, "max": 15, "notes": "..."}
      },
      "application_id": 162
    }
  ]
}
```

Update TodoWrite tasks (mark scoring tasks complete, create resume generation tasks for 70+ scores).

### 2f. Present Scoring Results & Auto-Proceed

Present scored results sorted by fit score:

```
## Scoring Results

| # | Score | Verdict | Company | Role | Location |
|---|-------|---------|---------|------|----------|
| 1 | 85% | Strong Fit | Figma | Sr PM, Growth | Remote |
| 2 | 82% | Strong Fit | Stripe | PM, Dev Tools | SF/Remote |
| 3 | 74% | Good Fit | Notion | PM, AI | SF |
| 4 | 68% | Good Fit | Vercel | Sr PM | Remote |
| 5 | 55% | Moderate | Coinbase | PM, Growth | Remote |
...

**Strong Fit (80+):** 3 jobs
**Good Fit (65-79):** 5 jobs
**Moderate (50-64):** 12 jobs
**Stretch (<50):** 8 jobs

Auto-generating resumes for X jobs scoring 70+...
```

**No approval gate here.** Automatically proceed to Phase 3 for all jobs at or above the threshold (default 70, overridable with `--threshold`). The user already approved which jobs to score in Phase 1.

---

## Phase 3: Resume Generation

### 3.0 Create Output Folder

Create the dated output folder if it doesn't exist:

```python
from pathlib import Path
from datetime import date

if output_dir_flag:
    output_dir = Path(output_dir_flag).expanduser()
else:
    output_dir = Path(f"~/Documents/Resumes/{date.today().isoformat()}").expanduser()

output_dir.mkdir(parents=True, exist_ok=True)
```

All resumes for this run are saved to this single folder.

For each job scoring at or above the threshold (default 70+):

### 3a. Select Resume Variant

Use the **archetype detected in Phase 2b** as the resume variant. The archetype was already determined during scoring by matching JD keywords against `config.variants`. No need to re-classify — just use the stored archetype value.

If for some reason the archetype wasn't stored, fall back to keyword matching:

| Variant | Match Keywords |
|---------|---------------|
| growth | PLG, experimentation, activation, retention, conversion, funnel |
| ai-agentic | AI, ML, LLM, agents, orchestration, machine learning |
| health-tech | healthcare, EHR, HIPAA, clinical, patient |
| consumer | B2C, marketplace, e-commerce, consumer |
| general | (fallback if no strong keyword match) |

### 3b. Tailor Content

Following the same process as `/apply` Step 3:

1. Read the corpus from `~/.job-journal/corpus.md`
2. **SELECT, don't COMPOSE** -- choose existing bullets VERBATIM from corpus
3. Reorder bullets to lead with JD-relevant content at each role
4. Select skill categories matching JD emphasis, reorder to lead with strongest matches
5. Compose a targeted summary paragraph using the Identity-First framework (Identity → Evidence → Differentiation). This is the ONLY content that may be freshly written, and must reference only experiences/skills present in corpus. Never use "12+ years," "proven track record," or category-label openings. See base.md SUMMARY section for structure and examples.

**Content Integrity Rules (CRITICAL):**
- Do NOT paraphrase, combine, merge, or rewrite bullets
- Do NOT add details not explicitly present in the source (no invented metrics, clients, technologies)
- When in doubt, OMIT -- never guess or infer

### 3c. Score Before Generating

Score the tailored content against the JD using the Resume-JD rubric from `/apply` Step 2b:

| Category | Points | What to Evaluate |
|----------|--------|------------------|
| Summary alignment | 25 | Does tailored summary emphasize JD's key themes? |
| Skills coverage | 25 | Are JD's top 5 required skills listed prominently? |
| Bullet relevance | 35 | Do lead bullets at recent roles match JD priorities? |
| Keyword density | 15 | Key terms from JD present throughout resume? |

Record as `rj_before` (standard resume score) and `rj_after` (tailored score). The tailored resume must score **85+** before generating the document. If below 85, iterate on bullet selection and summary until threshold is met.

### 3d. Generate Document

```python
from jj.google_docs import generate_resume_programmatic

result = generate_resume_programmatic(
    company=job["company"],
    position=job["title"],
    variant=best_variant,
    custom_summary=tailored_summary,
    custom_skills=prioritized_skills,        # dict[str, list[str]]
    role_bullets=reordered_bullets,           # dict[str, list[str]]
    max_roles=5,
    max_bullets_per_role=6,
    output_dir=output_dir,     # Dated folder from Phase 3.0
    auto_open=False,           # Don't open each one during batch
    keep_google_doc=True,
)
```

`result` is a `ResumeGenerationResult` with:
- `result.success` -- whether generation succeeded
- `result.doc_url` -- Google Doc URL
- `result.pdf_path` -- exported PDF path
- `result.resume_id` -- database resume record ID

If `result.success` is False, log the error and continue to the next job.

### 3e. Update Application Record

```python
from jj.db import update_application

update_application(
    app_id=application_id,
    resume_id=result.resume_id,
    rj_before=rj_before_score,
    rj_after=rj_after_score,
    notes=f"RJ:{rj_before_score}→{rj_after_score} (+{rj_after_score - rj_before_score}pts), variant={best_variant}",
)
```

Update TodoWrite: mark resume task complete, create validation task.

---

## Phase 4: Validation

For each generated resume:

### 4a. Extract and Validate Bullets

Extract all bullet texts from the generated resume content (the same `role_bullets` dict used in generation).

Run corpus validation:

```python
from jj.resume_gen import validate_resume_content

is_valid, drift_score, results = validate_resume_content(
    bullets=all_bullet_texts,   # flat list of all bullet strings
    fail_fast=False,            # Check all, don't stop on first failure
)
```

### 4b. Report Results

For each resume, report:

```
## Validation: [Company] - [Role]

- Bullets checked: 24
- Valid: 24 (100%)
- Drift score: 0 (perfect corpus alignment)
- Status: PASSED
```

### 4c. Handle Failures

If ANY bullet fails validation:

1. Flag it with the exact text and closest corpus match
2. **Block** that resume from proceeding to "ready to apply"
3. Log to `pipeline-log.md` as a fabrication alert:

```
### FABRICATION ALERT: [Company] - [Role]
- Invalid bullet: "Led cross-functional team of 12..."
- Closest corpus match: "Led cross-functional initiative..."
- Drift score: 15
- Action: BLOCKED -- resume requires manual review
```

4. Report to user:
```
WARNING: Resume for [Company] - [Role] failed validation.
[N] bullets did not match corpus content. This resume is BLOCKED.
Review the flagged bullets above and either:
1. Fix the content manually in the Google Doc
2. Re-run /apply for this job individually
```

### 4d. Update Database

```python
from jj.db import validate_resume

validate_resume(
    resume_id=result.resume_id,
    is_valid=is_valid,
    drift_score=drift_score,
)
```

For passing resumes, transition status:

```python
from jj.db import transition_application_status

transition_application_status(
    app_id=application_id,
    new_status="prospect",  # remains prospect until user actually applies
    reason="Pipeline: resume generated and validated",
    source="pipeline",
    metadata={"drift_score": drift_score, "rj_after": rj_after_score},
)
```

---

## Phase 5: Tracker (Summary & Brief)

### 5a. Generate Opportunity Brief (Markdown)

Create a markdown file in the output folder summarizing all generated resumes with JD context:

```python
from pathlib import Path
from datetime import date

brief_path = output_dir / f"pipeline-brief-{date.today().isoformat()}.md"
```

Write the brief with this structure:

```markdown
# Pipeline Brief — YYYY-MM-DD

X resumes generated from Y jobs scored across Z companies.

---

## Opportunities

### 1. [Company] — [Role] (Score: XX%)

**Verdict:** Strong Fit | **Location:** Remote | **Salary:** $XXXk-$XXXk
**Posted:** ~X days ago _(or "Unknown" if not available)_

**JD:** [Full job posting](https://job-url-here)
**Resume:** [Google Doc](https://docs.google.com/document/d/XXX/edit) | [PDF](filename.pdf)

**Archetype:** [detected archetype from Phase 2b]

**Why this is a good fit:**
- [2-3 bullet summary of why the corpus aligns with this JD]
- [E.g., "Direct multi-agent AI orchestration experience matches core requirement"]
- [E.g., "Health-tech background (Wellcore, AI Health-Tech Startup) covers domain expertise"]

**Key JD requirements matched:**
- [Requirement from JD] → [Matching corpus experience]
- [Requirement from JD] → [Matching corpus experience]

**Top Gaps:** [from evaluation report match_analysis, if report was generated]

**Interview Stories:** [1-2 line summary of STAR+R stories from evaluation report, if generated]

---

### 2. [Next company...]

...

---

## Summary Table

| # | Score | Company | Role | Variant | Location | Posted | Resume |
|---|-------|---------|------|---------|----------|--------|--------|
| 1 | 91% | Sully.ai | Senior PM | ai-agentic | Remote | ~3d ago | [PDF](file) |
...

## Next Steps
- Review resumes in Google Docs before applying
- Run `/apply --company "Company"` for ATS submission
- Re-run `/pipeline` tomorrow to check for new postings
```

**Posting age:** Extract from the JD page if available (look for "posted X days ago", date strings, or Greenhouse/Lever/Ashby metadata). If the JD page doesn't include a posting date, write "Unknown". Do NOT guess.

### 5b. Generate Run Summary

Append a run summary to `pipeline-log.md`:

```markdown
## Pipeline Run: YYYY-MM-DD HH:MM

### Scrape Results
- Companies checked: X (of Y targets with career URLs)
- New jobs found: X
- Duplicates skipped: X

### Scoring Results
- Jobs scored: X
- Strong Fit (80+): X
- Good Fit (65-79): X
- Moderate (50-64): X
- Stretch (<50): X

### Resumes Generated
- Attempted: X
- Passed validation: X
- Blocked (fabrication): X

### Top Opportunities
| Company | Role | Score | Resume | Brief |
|---------|------|-------|--------|-------|
| Figma | Sr PM, Growth | 85% | Generated | [Brief](~/Documents/Resumes/YYYY-MM-DD/pipeline-brief-YYYY-MM-DD.md) |
| Stripe | PM, Dev Tools | 82% | Generated | ↑ |

### Errors & Warnings
- [List any errors encountered, or "None"]
```

### 5c. Present Final Summary to User

Show the full summary table plus actionable next steps:

```
## Pipeline Complete

[Summary table from above]

### Output
- **Resumes folder:** ~/Documents/Resumes/YYYY-MM-DD/ (X PDFs)
- **Opportunity brief:** ~/Documents/Resumes/YYYY-MM-DD/pipeline-brief-YYYY-MM-DD.md

### Next Steps
- **Review brief:** Open the opportunity brief to see JD links and fit rationale
- **Apply now:** Run `/apply <url>` for any ready_to_apply job
- **Review resumes:** Open the Google Doc links in the brief to review before applying
- **View all prospects:** Run `jj prospects list` to see all tracked jobs
- **Re-run pipeline:** Run `/pipeline` again to check for new postings
```

### 5d. Complete TodoWrite Tasks

Mark all remaining TodoWrite tasks as completed.

---

## Data Files

| File | Purpose |
|------|---------|
| `~/.job-journal/journal.db` | SQLite database -- single source of truth |
| `~/.job-journal/corpus.md` | Professional corpus for scoring and bullet selection |
| `~/.job-journal/profile.yaml` | Contact info, location preferences |
| `~/.job-journal/config.yaml` | Resume variants, generation settings |
| `jobs/scraped.json` | Latest scrape results (overwritten each run) |
| `jobs/scored.json` | Latest scoring results (overwritten each run) |
| `pipeline-log.md` | Append-only run history log |
| `~/Documents/Resumes/YYYY-MM-DD/` | Dated output folder (PDFs + brief) |
| `~/Documents/Resumes/YYYY-MM-DD/pipeline-brief-YYYY-MM-DD.md` | Opportunity brief with JD links, fit rationale, posting age |

**Database is the single source of truth** -- JSON files are ephemeral outputs for review. The `applications` table tracks pursued jobs; the `job_listings` table tracks every job URL ever scraped (including filtered/skipped ones). Together they prevent re-processing the same listings across pipeline runs. Use `is_known_job(url)` to check both tables in one call.

## Error Handling

| Situation | Response |
|-----------|----------|
| Career page unreachable | Log warning, skip company, continue |
| Job URL returns 404 | Skip that job, note in scrape results |
| No corpus found | Stop pipeline: "Run `/interview` first" |
| WebFetch fails on JD | Score as "Unable to fetch" with score 0, skip |
| Resume generation fails | Log error, continue to next job |
| Validation finds fabrication | Block resume, alert user, continue pipeline |
| No target companies found | Stop: "No target companies configured. Add companies first." |
| All jobs are duplicates | Report "No new jobs found" and end pipeline |

## Notes

- **Approval gate on Phase 1 only** -- pause for user confirmation between Scrape→Score. Phase 2→3 proceeds automatically for all jobs at or above threshold (default 70+)
- **Auto-resume generation** -- all jobs scoring at or above the threshold get resumes generated without asking. Override threshold with `--threshold`
- **Dated output folder** -- resumes default to `~/Documents/Resumes/YYYY-MM-DD/` unless overridden with `--output-dir`
- **Opportunity brief** -- a markdown file with JD links, fit rationale, and posting age is always generated alongside the resumes
- **Content integrity is non-negotiable** -- Phase 4 validation exists because SELECT-don't-COMPOSE must be enforced
- **Database writes use existing functions** -- always use `create_application()`, `update_application()`, `transition_application_status()` rather than raw SQL for applications
- **One pipeline run per session** -- don't loop. If user wants to re-run, they invoke `/pipeline` again
- **Respect rate limits** -- when scraping many career pages, pace WebFetch calls (don't fire 20+ simultaneously)
- **Show progress** -- at each phase, report what you're doing: "Scraping Figma career page...", "Scoring job 3 of 28..."
- **The `/apply` skill is the gold standard** -- this pipeline automates the same workflow but in batch. When in doubt about how to score, tailor, or validate, follow `/apply`'s process
