# /slack-apply - Headless Score + Apply (Slack-Triggered)

Autonomous score-and-apply workflow triggered by Slack button clicks. Runs headlessly with no user prompts or approval gates. Combines `/score` triage with `/pipeline`-style resume generation.

## Critical: Headless Mode Rules

- Do NOT prompt the user for input or approval at any point
- Make all tailoring decisions autonomously
- If any step fails, report the error clearly and exit
- Output resumes to `~/Documents/Resumes/slack/`

## Usage

```
/slack-apply <url>
```

Single URL only (one Slack button = one job).

## Resume Generation Mode

Always uses **disciplined mode** (`mode="strict"`):
- Summary composed fresh (Identity-First framework)
- Skills reordered/filtered for JD emphasis
- Bullet changes limited to SWAP/CUT/PROMOTE/DEMOTE against corpus
- All output validated against corpus DB

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
conn.close()
```

**Three states:**

1. **No existing row** -- proceed to scoring.

2. **Existing row with `notes` starting with `"Title Fit:"`** -- bare title pre-filter from monitor. Keep `existing["id"]` and proceed. Will UPDATE in place.

3. **Existing row with other `notes` AND `resume_id IS NOT NULL`** -- already fully processed (scored + resume generated). Report and exit:
   ```
   Already processed: [Company] - [Position] (app #ID, fit: X%, resume generated)
   ```

4. **Existing row with other `notes` but `resume_id IS NULL`** -- scored but no resume. If `fit_score >= 65`, proceed to Phase 3 (resume generation only, skip re-scoring). If `fit_score < 65`, report and exit.

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
  Score: XX% (Verdict). Below 65 threshold -- no resume generated.
  ```

- **If `fit_score >= 65`:** Proceed to Phase 3. Report:
  ```
  Score: XX% (Verdict). Generating tailored resume...
  ```

### Phase 3: Resume Generation

Follow the `/pipeline` Phase 3 pattern for autonomous resume generation.

#### Step 1: Create Output Directory

```python
from pathlib import Path

output_dir = Path.home() / "Documents" / "Resumes" / "slack"
output_dir.mkdir(parents=True, exist_ok=True)
```

#### Step 2: Assemble Template Data

```python
from jj.google_docs import assemble_template_data

template_data = assemble_template_data(jd_text=jd_text)
```

This loads the corpus, profile, and ranks bullets by JD relevance.

#### Step 3: Tailor Content (Autonomous)

All decisions are made autonomously. No user approval gates.

**Summary (compose fresh):**
- Identity-First framework: Identity -> Evidence -> Differentiation
- All facts from base.md/corpus only
- Banned phrases: "12+ years", "proven track record", "results-driven", "passionate", "deep experience in"
- No em-dashes. Max 3-4 sentences.

**Skills (reorder/filter):**
- Select categories matching JD emphasis
- Reorder to lead with strongest matches
- Values must be `list[str]`, not comma-separated strings

**Bullets (SWAP/CUT/PROMOTE/DEMOTE only):**
- Review auto-ranked bullets from `assemble_template_data`
- Apply operations to improve JD alignment
- Every bullet must be exact corpus text
- Do NOT paraphrase, combine, merge, or rewrite
- Do NOT add invented details

**Content Integrity Rules (CRITICAL):**
- No em-dashes anywhere
- Role dates must exactly match base.md corpus dates
- No invented specifics (metrics, company names, technologies)
- GitHub URL: github.com/dontoisme
- No graduation year in education
- SpareFoot and IBM appear ONLY in Earlier Experience

#### Step 4: Score Tailored Resume

Score the tailored content against the JD:

| Category | Points | What to Evaluate |
|----------|--------|------------------|
| Summary alignment | 25 | Does tailored summary emphasize JD's key themes? |
| Skills coverage | 25 | Are JD's top 5 required skills listed prominently? |
| Bullet relevance | 35 | Do lead bullets at recent roles match JD priorities? |
| Keyword density | 15 | Key terms from JD present throughout resume? |

Record `rj_before` (standard resume score) and `rj_after` (tailored score).

**Threshold: 85+.** If below 85, iterate on bullet selection and summary up to 2 additional times. If still below 85 after iterations, generate anyway but add "(below-85 threshold)" to notes.

#### Step 5: Generate Document

```python
from jj.google_docs import generate_resume_programmatic

result = generate_resume_programmatic(
    company=company,
    position=position,
    variant=archetype,
    mode="strict",
    custom_summary=tailored_summary,
    custom_skills=prioritized_skills,      # dict[str, list[str]]
    role_bullets=reordered_bullets,         # dict[str, list[str]]
    earlier_roles=earlier_roles,           # from profile.yaml
    max_roles=5,
    max_bullets_per_role=6,
    jd_text=jd_text,
    output_dir=output_dir,                 # ~/Documents/Resumes/slack/
    auto_open=False,
    keep_google_doc=True,
)
```

If `result.success` is False, report the error and exit.

#### Step 6: Validate Content

```python
from jj.resume_gen import validate_resume_content

is_valid, drift_score, results = validate_resume_content(
    bullets=all_bullet_texts,
    fail_fast=False,
)
```

If validation fails, flag in notes but do not block (the resume is already generated and may still be useful).

#### Step 7: Update Application Record

```python
from jj.db import update_application

rj_notes = f"RJ:{rj_before}→{rj_after} (+{rj_after - rj_before}pts)"
existing_notes = current_notes or ""

update_application(
    app_id,
    resume_id=result.resume_id,
    rj_before=rj_before,
    rj_after=rj_after,
    notes=f"{existing_notes} | {rj_notes}, variant={archetype}",
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

**If score >= 65 (resume generated):**
```
RESULT: SCORE_AND_RESUME
Score: XX% (Verdict)
Company: [company]
Position: [position]
Archetype: [archetype]
App ID: [app_id]
Resume ID: [resume_id]
PDF: [pdf_path]
Doc URL: [doc_url]
RJ Before: [rj_before]
RJ After: [rj_after]
Valid: [yes/no]
Drift: [drift_score]
```

## Error Handling

| Situation | Response |
|-----------|----------|
| URL not accessible | Report error, exit with non-zero |
| No corpus found | Report "Run /interview first", exit |
| Google Docs API failure | Report score (already saved), note resume generation failed |
| Integrity audit failure | Fix and retry once; if still failing, report the audit failures |
| Validation finds fabrication | Flag in notes, report warning, but still output the resume |

## What This Skill Does NOT Do

- No cover letter generation (interactive only, via `/apply`)
- No custom Q&A answers (interactive only, via `/apply`)
- No user approval gates (fully autonomous)
- No batch processing (single URL per invocation)
- No form-filling or ATS submission
