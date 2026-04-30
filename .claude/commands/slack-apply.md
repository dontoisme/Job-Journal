# /slack-apply - Headless Score + Apply (Slack-Triggered)

Autonomous score-and-apply workflow triggered by Slack button clicks. Runs headlessly with no user prompts or approval gates. Combines `/score` triage with dual-resume generation for the evaluation pipeline.

## Critical: Headless Mode Rules

- Do NOT prompt the user for input or approval at any point
- Make all tailoring decisions autonomously
- If any step fails, report the error clearly and exit
- Output resumes to `~/Documents/Resumes/YYYY-MM-DD/slack/Company/phase1/`

## Usage

```
/slack-apply <url>
```

Single URL only (one Slack button = one job).

## Resume Generation Modes

This skill generates **TWO candidate resumes** for the evaluation pipeline:

1. **Strict resume** (`mode="strict"`): Corpus-verbatim bullets, SWAP/CUT/PROMOTE/DEMOTE only. Summary composed fresh but all facts from corpus.
2. **Freeform resume** (`mode="optimized"`): Full rewrite. Summary and bullets can be reworded to mirror JD language. Facts must still trace to corpus but phrasing is free.

Both are exported as Google Docs + PDFs into `YYYY-MM-DD/slack/Company/phase1/`. The downstream `/resume-refine` step produces the final PDF in `YYYY-MM-DD/slack/Company/`.

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
    pipeline_exists = pipeline_row and pipeline_row["pipeline_status"] in ("completed", "degraded_phase2", "degraded_phase3", "degraded_phase4")
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

### Phase 3: Dual Resume Generation

Generate TWO candidate resumes for the evaluation pipeline. Both are Google Docs only (no PDF).

#### Step 1: Create Pipeline Run

```python
from jj.db import create_pipeline_run

run_id = create_pipeline_run(application_id=app_id)
```

#### Step 2: Create Output Directories

```python
from pathlib import Path
from datetime import date

today = date.today().isoformat()  # YYYY-MM-DD
phase1_dir = Path.home() / "Documents" / "Resumes" / today / "slack" / company / "phase1"
phase1_dir.mkdir(parents=True, exist_ok=True)
```

#### Step 3: Assemble Template Data

```python
from jj.google_docs import assemble_template_data

template_data = assemble_template_data(jd_text=jd_text)
```

This loads the corpus, profile, and ranks bullets by JD relevance.

#### Step 4: Tailor Content — Strict Version

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

**Content Integrity Rules (CRITICAL):**
- No em-dashes anywhere
- Role dates must exactly match base.md corpus dates
- No invented specifics (metrics, company names, technologies)
- GitHub URL: github.com/dontoisme
- No graduation year in education
- SpareFoot and IBM appear ONLY in Earlier Experience

#### Step 5: Generate Strict Resume (Doc only)

```python
from jj.google_docs import generate_resume_programmatic

result_strict = generate_resume_programmatic(
    company=company,
    position=position,
    variant=archetype,
    mode="strict",
    custom_summary=strict_summary,
    custom_skills=prioritized_skills,      # dict[str, list[str]]
    role_bullets=reordered_bullets,         # dict[str, list[str]]
    earlier_roles=earlier_roles,           # from profile.yaml
    max_roles=5,
    max_bullets_per_role=6,
    jd_text=jd_text,
    output_dir=phase1_dir,                  # YYYY-MM-DD/slack/Company/phase1/
    auto_open=False,
    keep_google_doc=True,
    export_pdf=True,                        # PDF for comparison
    generation_mode="strict",
    pipeline_run_id=run_id,
)
```

If `result_strict.success` is False, report the error and exit.

#### Step 6: Tailor Content — Freeform Version

Now create a second, more aggressive version:

**Summary (freeform rewrite):**
- Mirror JD language and priorities directly
- Can use JD keywords and phrasing
- Still must be factually accurate to corpus/base.md
- Same banned phrases and no em-dashes rules apply

**Bullets (full rewrite allowed):**
- Can reword bullets to mirror JD language
- Can combine or restructure bullet points
- All facts, metrics, and technologies must still trace to corpus
- Do NOT invent metrics, company names, or technologies
- Aim for stronger keyword alignment with the JD

**Skills (same as strict, but can adjust naming):**
- Can rename skill categories to match JD terminology
- Can regroup skills if JD organizes them differently

#### Step 7: Generate Freeform Resume (Doc only)

```python
result_freeform = generate_resume_programmatic(
    company=company,
    position=position,
    variant=archetype,
    mode="optimized",
    custom_summary=freeform_summary,
    custom_skills=freeform_skills,         # dict[str, list[str]]
    role_bullets=freeform_bullets,          # dict[str, list[str]]
    earlier_roles=earlier_roles,
    max_roles=5,
    max_bullets_per_role=6,
    jd_text=jd_text,
    output_dir=phase1_dir,                  # YYYY-MM-DD/slack/Company/phase1/
    auto_open=False,
    keep_google_doc=True,
    export_pdf=True,                        # PDF for comparison
    generation_mode="freeform",
    pipeline_run_id=run_id,
)
```

If `result_freeform.success` is False, report the error but continue (strict resume is still available).

#### Step 8: Score Both Resumes

Score both tailored resumes against the JD using the RJ rubric:

| Category | Points | What to Evaluate |
|----------|--------|------------------|
| Summary alignment | 25 | Does tailored summary emphasize JD's key themes? |
| Skills coverage | 25 | Are JD's top 5 required skills listed prominently? |
| Bullet relevance | 35 | Do lead bullets at recent roles match JD priorities? |
| Keyword density | 15 | Key terms from JD present throughout resume? |

Record `rj_strict` and `rj_freeform` scores.

#### Step 9: Update Pipeline Run

```python
from jj.db import update_pipeline_run

update_pipeline_run(
    run_id,
    resume_strict_id=result_strict.resume_id,
    resume_freeform_id=result_freeform.resume_id if result_freeform.success else None,
    eval_score_strict=rj_strict,
    eval_score_freeform=rj_freeform if result_freeform.success else None,
    pipeline_status="phase1",
    phase_reached=1,
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

**If score >= 65 (pipeline started):**
```
RESULT: PIPELINE_PHASE1
Score: XX% (Verdict)
Company: [company]
Position: [position]
Archetype: [archetype]
App ID: [app_id]
Pipeline Run: [run_id]
Resume Strict ID: [strict_resume_id]
Resume Freeform ID: [freeform_resume_id]
RJ Strict: [rj_strict]
RJ Freeform: [rj_freeform]
```

## Error Handling

| Situation | Response |
|-----------|----------|
| URL not accessible | Report error, exit with non-zero |
| No corpus found | Report "Run /interview first", exit |
| Google Docs API failure (strict) | Report score (already saved), note resume generation failed |
| Google Docs API failure (freeform) | Continue with strict only; freeform_resume_id will be null |
| Integrity audit failure | Fix and retry once; if still failing, report the audit failures |

## What This Skill Does NOT Do

- No cover letter generation (interactive only, via `/apply`)
- No custom Q&A answers (interactive only, via `/apply`)
- No user approval gates (fully autonomous)
- No batch processing (single URL per invocation)
- No form-filling or ATS submission
- No final resume (that happens in `/resume-refine`)
