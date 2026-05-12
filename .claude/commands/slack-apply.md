# /slack-apply - Headless Score + Apply (Slack-Triggered)

Autonomous score-and-apply workflow triggered by Slack button clicks. Runs headlessly with no user prompts or approval gates. Scores the job, then links the matching archetype master resume.

## Critical: Headless Mode Rules

- Do NOT prompt the user for input or approval at any point
- If any step fails, report the error clearly and exit
- Master archetype resumes live in `~/Documents/Resumes/archetypes/`

## Usage

```
/slack-apply <url>
```

Single URL only (one Slack button = one job).

## Archetype Resume System

Instead of generating per-JD resumes, this skill selects from 4 pre-built master resumes stored in `~/.job-journal/archetypes.yaml`:

- **growth**: Growth/PLG, experimentation, funnels, conversion
- **ai-agentic**: AI/ML, multi-agent systems, orchestration, platform
- **health-tech**: Healthcare, EHR, clinical workflows, patient experience
- **general**: Fallback for roles that don't match a specific archetype

Each archetype has a Google Doc + PDF in `~/Documents/Resumes/archetypes/`.

## Workflow

### Phase 1: Score

Follow the exact same workflow as `/score` Steps 1-6, adapted for a single URL:

#### Step 1: Fetch JD

1. Use **WebFetch** to fetch the full job description
   - Prompt: "Extract the full job description. Include: job title, company name, required skills, years of experience, responsibilities, qualifications, salary/compensation if listed, location/remote policy. Return all text content."
2. Detect ATS type:
   ```python
   from jj.db import detect_ats_type
   ats_type = detect_ats_type(url)
   ```
3. Extract: company name, job title, location, salary (if visible)

If WebFetch fails, report the error and exit.

#### Step 2: Deduplicate

```python
from jj.config import DB_PATH
import sqlite3

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
existing = conn.execute(
    "SELECT id, company, position, status, fit_score, notes, resume_id FROM applications WHERE job_url = ?",
    (url,)
).fetchone()

# Check if a pipeline run already exists for this application
pipeline_exists = False
if existing:
    pipeline_row = conn.execute(
        "SELECT pipeline_status FROM pipeline_runs WHERE application_id = ? ORDER BY started_at DESC LIMIT 1",
        (existing["id"],)
    ).fetchone()
    pipeline_exists = pipeline_row and pipeline_row["pipeline_status"] in ("completed", "archetype", "degraded_phase2", "degraded_phase3", "degraded_phase4")
conn.close()
```

**Four states:**

1. **No existing row** -- proceed to scoring.

2. **Existing row with `notes` starting with `"Title Fit:"`** -- bare title pre-filter from monitor. Keep `existing["id"]` and proceed. Will UPDATE in place.

3. **Existing row with a completed pipeline_run** -- already fully processed through the 4-phase pipeline. Report and exit:
   ```
   Already processed: [Company] - [Position] (app #ID, fit: X%, pipeline complete)
   ```

4. **Existing row with score but no completed pipeline** -- re-run is allowed (old single-pass result or incomplete pipeline). Keep `existing["id"]`, skip re-scoring if `fit_score` is already set and >= 65, proceed to Phase 3. If `fit_score < 65`, report and exit.

#### Step 3: Detect Archetype

Classify the JD against resume variant keywords from `~/.job-journal/config.yaml`:

```python
from jj.config import load_config

config = load_config()
variants = config.get("variants", {})
```

Count keyword matches per variant. Pick the highest overlap (minimum 2 hits, else `general`).

#### Step 4: Score Fit

Read corpus:

```python
from jj.config import CORPUS_PATH
corpus = CORPUS_PATH.read_text()
```

Score (0-100) using the 4-category rubric:

| Category | Weight | What to Evaluate |
|----------|--------|------------------|
| **Skills Match** | 35 pts | JD required skills vs corpus skills |
| **Experience Level** | 25 pts | Seniority alignment (title, years) |
| **Domain Fit** | 30 pts | Domain tag overlap |
| **Location/Remote** | 10 pts | Location compatibility with profile |

Assign verdict:

| Score | Verdict |
|-------|---------|
| 80-100 | Strong Fit |
| 65-79 | Good Fit |
| 50-64 | Moderate Fit |
| <50 | Stretch |

#### Step 5: Insert or Update Prospect

```python
from jj.db import create_application, update_application

notes_text = (
    f"Fit: {score}% ({verdict}). Archetype: {archetype}. "
    f"Skills: {skills_score}/35, Exp: {exp_score}/25, "
    f"Domain: {domain_score}/30, Location: {loc_score}/10. "
    f"{brief_reasoning}"
)

if existing and (existing.get("notes") or "").startswith("Title Fit:"):
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

#### Step 6: Evaluation Report + Stories (65+ only)

For jobs scoring 65+, generate the evaluation report and STAR+R stories (same as `/score` Steps 5b-5d):

- Comp research via WebSearch (if salary not in JD)
- 3-block evaluation report (Role Summary, Match Analysis, Interview Prep)
- Save STAR+R stories to story bank (deduplicate by `source_entry_ids`)

```python
from jj.db import create_evaluation_report, create_story, get_stories

report_id = create_evaluation_report(
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

### Phase 2: Apply Gate

- **If `fit_score < 65`:** STOP. Report score only and exit:
  ```
  RESULT: SCORE_ONLY
  Score: XX% (Verdict)
  Company: [company]
  Position: [position]
  Archetype: [archetype]
  App ID: [app_id]
  ```

- **If `fit_score >= 65`:** Proceed to Phase 3.

### Phase 3: Archetype Resume Selection

Select the pre-built master resume matching the detected archetype.

#### Step 1: Load Archetype Resume

```python
from jj.config import load_archetypes
from jj.db import get_archetype_resume, update_application
from pathlib import Path

archetypes = load_archetypes()
archetype_def = archetypes.get("archetypes", {}).get(archetype)

if not archetype_def or not archetype_def.get("resume_id"):
    archetype_def = archetypes.get("archetypes", {}).get("general")

resume_id = archetype_def["resume_id"]
pdf_path = archetype_def.get("pdf_path", "")
google_doc_id = archetype_def.get("google_doc_id", "")
```

#### Step 2: Verify Resume Exists

```python
resume = get_archetype_resume(archetype)
if not resume:
    resume = get_archetype_resume("general")
    archetype_used = "general"
else:
    archetype_used = archetype

if not resume:
    print("ERROR: No archetype resumes found. Run archetype generation first.")
    exit(1)

resume_id = resume["id"]
pdf_path = archetype_def.get("pdf_path", resume.get("filepath", ""))
```

#### Step 3: Link Application to Archetype Resume

```python
update_application(app_id, resume_id=resume_id)
```

#### Step 4: Create Pipeline Run (for tracking continuity)

```python
from jj.db import create_pipeline_run, update_pipeline_run
from datetime import datetime

run_id = create_pipeline_run(application_id=app_id)
update_pipeline_run(
    run_id,
    resume_final_id=resume_id,
    pipeline_status="archetype",
    phase_reached=0,
    completed_at=datetime.now().isoformat(),
)
```

### Phase 4: Report

Output a structured result summary. This is what the Slack bot parses from stdout.

**If score < 65 (no resume):**
```
RESULT: SCORE_ONLY
Score: XX% (Verdict)
Company: [company]
Position: [position]
Archetype: [archetype]
App ID: [app_id]
```

**If score >= 65 (archetype resume linked):**
```
RESULT: ARCHETYPE_APPLIED
Score: XX% (Verdict)
Company: [company]
Position: [position]
Archetype: [archetype]
App ID: [app_id]
Resume ID: [resume_id]
PDF: [pdf_path]
Google Doc: https://docs.google.com/document/d/[google_doc_id]
```

## Error Handling

| Situation | Response |
|-----------|----------|
| URL not accessible | Report error, exit with non-zero |
| No corpus found | Report "Run /interview first", exit |
| No archetype resume found | Report error, suggest running archetype generation |
| Archetype variant not found | Fall back to "general" archetype |

## What This Skill Does NOT Do

- No per-JD resume generation (uses pre-built archetype resumes)
- No cover letter generation (interactive only, via `/apply`)
- No custom Q&A answers (interactive only, via `/apply`)
- No user approval gates (fully autonomous)
- No batch processing (single URL per invocation)
- No form-filling or ATS submission
