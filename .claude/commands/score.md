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
    "SELECT id, company, position, status, fit_score FROM applications WHERE job_url = ?",
    (url,)
).fetchone()
conn.close()
```

If already tracked, report it and skip:
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

### Step 4: Score Fit

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
| **Domain Fit** | 25 pts | Domain tag overlap (AI, growth, health-tech, platform, consumer) |
| **Location/Remote** | 15 pts | Location compatibility with profile preferences |

Assign verdict:

| Score | Verdict |
|-------|---------|
| 80-100 | Strong Fit |
| 65-79 | Good Fit |
| 50-64 | Moderate Fit |
| <50 | Stretch |

Write a brief reasoning note for each category.

### Step 5: Insert Prospect

For each scored job, create an application record:

```python
from jj.db import create_application

app_id = create_application(
    company=company,
    position=title,
    job_url=url,
    location=location,
    salary_range=salary,
    ats_type=ats_type,
    fit_score=score,
    status="prospect",
    notes=f"Fit: {score}% ({verdict}). Skills: {skills_score}/35, Exp: {exp_score}/25, Domain: {domain_score}/25, Location: {loc_score}/15. {brief_reasoning}",
)
```

### Step 6: Present Results

Show a summary table sorted by fit score:

```
## Score Results

| # | Score | Verdict | Company | Role | Location | Salary |
|---|-------|---------|---------|------|----------|--------|
| 1 | 85% | Strong Fit | Figma | Sr PM, Growth | Remote | $180k-$250k |
| 2 | 72% | Good Fit | Stripe | PM, Dev Tools | SF/Remote | $190k-$270k |
| 3 | 48% | Stretch | Netflix | Games PM | LA | $190k-$300k |

Scored 3 jobs. 2 above 65% threshold.
All saved as prospects in your tracker.
```

For each Good Fit or better, show a brief breakdown:

```
### #1 Figma — Sr PM, Growth (85%)
- **Skills** 30/35: Strong match on growth, experimentation, PLG
- **Experience** 23/25: Seniority aligned, 12 yrs matches senior PM
- **Domain** 22/25: Growth + consumer, strong overlap
- **Location** 10/15: Remote friendly, slight preference for SF
**Next step:** `/apply https://...`
```

For Stretch jobs, keep it to one line:
```
#3 Netflix — Games PM (48%): Gaming domain mismatch, location barrier. Skip unless compelling.
```

### Step 7: Offer Next Steps

```
What next?
- `/apply <url>` — Full application workflow for any scored job
- `/score <more urls>` — Score additional jobs
- `/pipeline` — Run the full autonomous pipeline
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
