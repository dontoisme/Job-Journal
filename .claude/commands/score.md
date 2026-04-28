# /score - Quick Job Fit Scorer

Score one or more job URLs against your corpus. Inserts prospects into the database for tracking. Lightweight triage — no resume generation.

## Usage

```
/score <url>
/score <url1> <url2> <url3>
/score https://job-boards.greenhouse.io/company/jobs/123 https://jobs.lever.co/company/456
```

## Workflow

When the user invokes `/score` with one or more job URLs, follow these steps:

### Step 1: Parse URLs

Extract all URLs from the user's input. Accept any format:
- Space-separated on one line
- One per line
- Mixed with text ("check these: url1 url2")

Report: `Scoring X job(s)...`

### Step 2: Deduplicate

For each URL, check if it's already tracked:

```python
from jj.config import DB_PATH
import sqlite3

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
existing = conn.execute(
    "SELECT id, company, position, status, fit_score, notes FROM applications WHERE job_url = ?",
    (url,)
).fetchone()
conn.close()
```

**Three possible states:**

1. **No existing row** — proceed to Step 3 to create a new prospect.

2. **Existing row with `notes` starting with `"Title Fit:"`** — this is a bare
   title pre-filter from the hourly `scan-apis` monitor, not a real evaluation.
   Keep a reference to `existing["id"]` and proceed to Step 3 to re-score it.
   In Step 5, **UPDATE** the existing row via
   `update_application(existing["id"], ...)` instead of inserting a new one.

3. **Existing row with any other `notes`** — a real `/score` run has already
   been done. Report it and skip:
   ```
   Already tracked: [Company] - [Position] (app #123, status: prospect, fit: 72%)
   ```

### Step 3: Fetch JD

For each new URL:

1. Use **WebFetch** to fetch the full job description
   - Prompt: "Extract the full job description. Include: job title, company name, required skills, years of experience, responsibilities, qualifications, salary/compensation if listed, location/remote policy. Return all text content."
2. Detect ATS type from URL:
   ```python
   from jj.db import detect_ats_type
   ats_type = detect_ats_type(url)
   ```
3. Extract: company name, job title, location, salary (if visible)

If WebFetch fails, report: `Could not fetch [url] — skipping.`

### Step 4: Detect Archetype

Classify each JD against the resume variant keywords from `~/.job-journal/config.yaml`:

```python
from jj.config import load_config

config = load_config()
variants = config.get("variants", {})
# variants is a dict like:
#   growth: [PLG, experimentation, activation, retention, conversion, funnel]
#   ai-agentic: [AI, ML, LLM, agents, orchestration, machine learning]
#   health-tech: [healthcare, EHR, HIPAA, clinical, patient]
#   consumer: [B2C, marketplace, e-commerce, consumer]
#   general: []  (fallback)
```

For each JD, count keyword matches against each variant's keyword list. Pick the variant with the highest overlap as the **archetype**. If no strong match (fewer than 2 keyword hits), use `general`.

The detected archetype guides:
- Which proof points to emphasize in the scoring notes
- How to frame the Role Summary in the evaluation report
- Which resume variant to recommend if the user proceeds to `/apply`

### Step 5: Score Fit

Read the user's corpus:

```python
from jj.config import CORPUS_PATH
corpus = CORPUS_PATH.read_text()
```

If corpus doesn't exist, stop: "No corpus found. Run `/interview` first."

Score each job (0-100) using the 4-category rubric:

| Category | Weight | What to Evaluate |
|----------|--------|------------------|
| **Skills Match** | 35 pts | JD required skills vs corpus skills |
| **Experience Level** | 25 pts | Seniority alignment (title, years) |
| **Domain Fit** | 30 pts | Domain tag overlap (AI, growth, health-tech, platform, consumer) |
| **Location/Remote** | 10 pts | Location compatibility with profile preferences |

Assign verdict:

| Score | Verdict |
|-------|---------|
| 80-100 | Strong Fit |
| 65-79 | Good Fit |
| 50-64 | Moderate Fit |
| <50 | Stretch |

Write a detailed reasoning note for each category. When writing scoring notes, frame them through the detected archetype — e.g., for an `ai-agentic` archetype, the skills notes should specifically assess orchestration, agent framework, and LLM experience.

### Step 5b: Comp Research (for Good Fit or better)

For jobs scoring 65+, if `salary_range` is not already known from the JD:

1. Use **WebSearch** to search: `"{company} {position} salary glassdoor levels.fyi"`
2. Extract a salary range and source(s) from the results
3. Store in the application's `salary_range` field

If no reliable data found, note "Comp data unavailable" — do not guess.

### Step 5c: Generate Evaluation Report (for Good Fit or better)

For jobs scoring 65+, generate a structured evaluation report with 3 blocks:

**Block 1 — Role Summary:** Detected archetype, domain, seniority level, remote policy, and a 1-sentence TL;DR of what the role is really asking for.

**Block 2 — Match Analysis:** For each JD requirement, map to specific corpus entries. Identify gaps with mitigation strategies:
- Is the gap a hard blocker or a nice-to-have?
- Can adjacent experience cover it?
- What's the mitigation plan (cover letter framing, portfolio project, etc.)?

**Block 3 — Interview Prep:** Generate 3-5 STAR+R stories mapped to key JD requirements:
- **S**ituation: Context from a corpus entry
- **T**ask: What needed to be done
- **A**ction: What was done (from corpus bullets)
- **R**esult: Outcome with metrics (from corpus)
- **R**eflection: What was learned or what would be done differently

Save the report:

```python
from jj.db import create_evaluation_report

report_id = create_evaluation_report(
    application_id=app_id,
    report_type="fit",
    skills_score=skills_score,
    skills_notes=skills_notes,
    experience_score=exp_score,
    experience_notes=exp_notes,
    domain_score=domain_score,
    domain_notes=domain_notes,
    location_score=loc_score,
    location_notes=loc_notes,
    role_summary=role_summary_text,
    match_analysis=match_analysis_text,
    interview_prep=interview_prep_text,
    comp_research=comp_research_text,  # or None if not researched
    jd_url=url,
    jd_snapshot=jd_text,
)
```

### Step 5d: Save STAR+R Stories to Story Bank

For each STAR+R story generated in the evaluation report (Block 3), save it to the story bank for reuse across future evaluations and interview prep:

```python
from jj.db import create_story, get_stories

# Check for duplicates — don't create a story if one with the same source entries exists
existing_stories = get_stories()

for story in generated_stories:
    # Skip if a story with the same source_entry_ids already exists
    is_duplicate = any(
        s.get("source_entry_ids") == story["source_entry_ids"]
        for s in existing_stories
        if s.get("source_entry_ids")
    )
    if not is_duplicate:
        create_story(
            title=story["title"],
            situation=story["situation"],
            task=story["task"],
            action=story["action"],
            result=story["result"],
            reflection=story["reflection"],
            source_entry_ids=story.get("source_entry_ids"),
            jd_requirements_matched=story.get("requirements_matched"),
        )
```

### Step 6: Insert or Update Prospect

If Step 2 found an existing title-only row (notes starting with `"Title Fit:"`),
**UPDATE** that row in place so the application id is preserved. Otherwise,
**INSERT** a new prospect row.

```python
from jj.db import create_application, update_application

notes_text = (
    f"Fit: {score}% ({verdict}). Archetype: {archetype}. "
    f"Skills: {skills_score}/35, Exp: {exp_score}/25, "
    f"Domain: {domain_score}/25, Location: {loc_score}/15. "
    f"{brief_reasoning}"
)

if existing and (existing.get("notes") or "").startswith("Title Fit:"):
    # Re-scoring a row created by the hourly monitor's title pre-filter.
    # Update in place so the id stays stable.
    update_application(
        existing["id"],
        company=company,
        position=title,
        location=location,
        salary_range=salary,
        ats_type=ats_type,
        fit_score=score,
        status="prospect",
        notes=notes_text,
    )
    app_id = existing["id"]
else:
    # Brand-new prospect.
    app_id = create_application(
        company=company,
        position=title,
        job_url=url,
        location=location,
        salary_range=salary,
        ats_type=ats_type,
        fit_score=score,
        status="prospect",
        notes=notes_text,
    )
```

**Note:** Steps 5b-5d (comp research, evaluation report, story bank) run after the prospect is inserted, since they need the `app_id`. Reorder execution so `create_application()`/`update_application()` happens first for all jobs, then reports are generated for 65+ jobs.

### Step 7: Present Results

Show a summary table sorted by fit score:

```
## Score Results

| # | Score | Verdict | Archetype | Company | Role | Location | Salary |
|---|-------|---------|-----------|---------|------|----------|--------|
| 1 | 85% | Strong Fit | growth | Figma | Sr PM, Growth | Remote | $180k-$250k |
| 2 | 72% | Good Fit | ai-agentic | Stripe | PM, Dev Tools | SF/Remote | $190k-$270k |
| 3 | 48% | Stretch | consumer | Netflix | Games PM | LA | $190k-$300k |

Scored 3 jobs. 2 above 65% threshold.
All saved as prospects in your tracker.
```

For each Good Fit or better, show the evaluation report inline:

```
### #1 Figma — Sr PM, Growth (85%) [growth]

**Role Summary:** Growth PM role focused on PLG, activation funnels, and experimentation velocity. Senior IC, remote-friendly. Looking for someone who can own the full growth loop from acquisition to retention.

**Scoring Breakdown:**
- **Skills** 30/35: Strong match on growth, experimentation, PLG
- **Experience** 23/25: Seniority aligned, 12 yrs matches senior PM
- **Domain** 22/25: Growth + consumer, strong overlap
- **Location** 10/15: Remote friendly, slight preference for SF

**Salary Range:** $180k-$250k (Glassdoor, Levels.fyi)

**Top Gaps:**
- No direct PLG SaaS experience (mitigation: ZenBusiness self-serve funnels are adjacent)

**Interview Stories:**
1. "Scaled experimentation velocity at ZenBusiness" — maps to JD requirement: "experimentation culture"
2. "Built acquisition funnels driving 40% growth" — maps to: "own the growth loop"

**Next step:** `/apply https://...`
```

For Stretch jobs, keep it to one line:
```
#3 Netflix — Games PM (48%) [consumer]: Gaming domain mismatch, location barrier. Skip unless compelling.
```

### Step 8: Offer Next Steps

```
What next?
- `/apply <url>` — Full application workflow for any scored job
- `/score <more urls>` — Score additional jobs
- `/pipeline` — Run the full autonomous pipeline
- `/interview stories` — Review and refine your STAR+R story bank
```

## Error Handling

| Situation | Response |
|-----------|----------|
| URL not accessible | Log warning, skip, continue with remaining URLs |
| No corpus found | Stop: "Run `/interview` first" |
| Already tracked | Report existing record, skip |
| Not a job posting | "This URL doesn't appear to be a job posting. Skipping." |

## Notes

- **Batch-friendly** — paste as many URLs as you want, they all get scored in one pass
- **Database is truth** — all prospects go into `applications` table with status "prospect"
- **No resume generation** — this is triage only. Use `/apply` to execute on winners
- **Same rubric as /pipeline** — scores are directly comparable across tools
- **Dedup is by URL** — same job from different sources may not be caught
