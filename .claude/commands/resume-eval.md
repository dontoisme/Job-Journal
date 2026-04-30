# /resume-eval - Opus 4.7 Resume Evaluation Agent

Specialized evaluation agent that compares candidate resumes against a job description and company context. Run with `--model opus` for Opus 4.7.

## Critical: Headless Mode Rules

- Do NOT prompt the user for input or approval at any point
- Make all decisions autonomously
- If any step fails, report the error clearly and exit
- Write all results to the `pipeline_runs` DB table

## Usage

```
/resume-eval <app_id>            # Phase 2: Compare strict vs freeform
/resume-eval <app_id> --final    # Phase 4: Score the final refined resume
```

## Phase 2: Comparative Evaluation (default)

### Step 1: Load Pipeline Context

```python
from jj.db import get_pipeline_run_by_app, get_resume, get_evaluation_report
from jj.config import DB_PATH
import sqlite3

pipeline = get_pipeline_run_by_app(app_id)
if not pipeline:
    print("ERROR: No pipeline run found for app", app_id)
    exit(1)

run_id = pipeline["id"]
strict_resume = get_resume(pipeline["resume_strict_id"])
freeform_resume = get_resume(pipeline["resume_freeform_id"]) if pipeline.get("resume_freeform_id") else None
eval_report = get_evaluation_report(app_id)
jd_text = eval_report["jd_snapshot"] if eval_report else None
```

If `jd_text` is None, fetch the JD via WebFetch using the application's `job_url`.

### Step 2: Read Resume Content

Reconstruct both resumes from the DB (more reliable than Google Docs API in headless mode):

```python
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

def _reconstruct_resume(resume_id):
    """Reconstruct resume text from DB tables."""
    summary = conn.execute(
        "SELECT content FROM resume_sections WHERE resume_id = ? AND section_type = 'summary' LIMIT 1",
        (resume_id,)
    ).fetchone()

    skills = conn.execute(
        "SELECT section_name, content FROM resume_sections WHERE resume_id = ? AND section_type = 'skills' ORDER BY position",
        (resume_id,)
    ).fetchall()

    bullets = conn.execute(
        "SELECT r.company, r.title, e.text, re.position FROM resume_entries re "
        "JOIN entries e ON re.entry_id = e.id JOIN roles r ON re.role_id = r.id "
        "WHERE re.resume_id = ? ORDER BY re.role_id, re.position",
        (resume_id,)
    ).fetchall()

    parts = []
    if summary:
        parts.append(f"SUMMARY:\n{dict(summary)['content']}\n")
    if skills:
        parts.append("SKILLS:")
        for s in skills:
            s = dict(s)
            parts.append(f"  {s['section_name']}: {s['content']}")
        parts.append("")
    if bullets:
        current_company = None
        for b in bullets:
            b = dict(b)
            if b["company"] != current_company:
                current_company = b["company"]
                parts.append(f"EXPERIENCE: {b['title']} @ {b['company']}")
            parts.append(f"  - {b['text']}")
    return "\n".join(parts)

strict_text = _reconstruct_resume(pipeline["resume_strict_id"])
freeform_text = _reconstruct_resume(pipeline["resume_freeform_id"]) if pipeline.get("resume_freeform_id") else None
conn.close()
```

If DB reconstruction returns empty text, fall back to Google Docs API:

```python
if not strict_text.strip():
    from jj.google_docs import GoogleDocsClient
    client = GoogleDocsClient()
    client.authenticate()
    strict_text = client.get_document_text(strict_resume["google_doc_id"])
    if freeform_resume and not (freeform_text or "").strip():
        freeform_text = client.get_document_text(freeform_resume["google_doc_id"])
```

### Step 3: Research the Company

Use **WebSearch** to research the company:

1. Company overview: what they do, their products/services
2. Culture and values: Glassdoor, company blog, recent press
3. Recent news: funding, product launches, leadership changes
4. Role context: what success looks like for this position, team structure if available

Synthesize into a 2-3 paragraph company context that informs resume evaluation.

### Step 4: Evaluate Both Resumes

Score each resume (0-100) using the RJ rubric. **Read `docs/pipeline-refinement-notes.md` for calibration context.**

#### Positive scoring (up to 100)

| Category | Points | What to Evaluate |
|----------|--------|------------------|
| Summary alignment | 25 | Does the summary convey relevant identity and evidence without parroting the JD? |
| Skills coverage | 25 | Are the JD's top 5 required skills present? Use industry-standard category names, not unusual JD-specific phrasing. |
| Bullet relevance | 35 | Do lead bullets at recent roles demonstrate relevant outcomes? Do they read as natural descriptions of past work? |
| Natural keyword presence | 15 | Are key JD terms present organically, or do they feel injected? |

#### Over-tailoring deductions (CRITICAL)

Recruiters at high-prestige companies in 2026 have seen hundreds of AI-tailored resumes. Resumes that mirror JD language tightly are now correlated with low-effort applications. Apply these deductions AFTER positive scoring:

**Hard deductions (score floor 60 if ANY present):**
- Bullets that name the target company's product areas, teams, or org structure (e.g. "Lattice's Reviews, Grow, and Calibration teams")
- Bullets describing past roles using forward-looking JD framing (e.g. "the pattern X needs to ship Y")
- Verbatim JD phrases of 5+ consecutive words appearing in resume bullets
- Grammar errors: stacked prepositions, redundant modifiers, unclear referents, run-on clauses from vocabulary injection

**Soft deductions (5-10 point reduction each):**
- Sentences that paraphrase JD phrasing back with light rewording
- Skill category names that mirror unusual JD phrasing rather than industry-standard taxonomy
- Summary containing more than 3 distinct JD keyword phrases
- Any bullet exceeding 35 words (suggests clause-stacking from injection)

**The key calibration question:** "Would this resume earn a screen from a human reviewer who has seen 200 AI-tailored resumes this month?" If a bullet reads as transparently model-generated alignment text, the resume fails regardless of keyword density.

For each resume, provide:
- Total score (0-100, after deductions)
- Category breakdown with specific notes
- Over-tailoring flags (list any hard/soft deduction triggers found)
- Strengths (what works well for this specific JD + company)
- Weaknesses (what's missing, misaligned, or could be stronger)

### Step 5: Recommend Base and Improvements

1. **Choose the better base**: "strict" or "freeform"
2. **Generate structured improvement directives** (JSON array):

```json
[
  {
    "type": "SUMMARY",
    "instruction": "Rewrite to emphasize [specific JD theme]. Lead with [specific identity framing].",
    "new_text": "Full replacement summary text here.",
    "rationale": "The JD emphasizes X but the current summary leads with Y."
  },
  {
    "type": "BULLET_SWAP",
    "company": "ZenBusiness",
    "old_prefix": "Led cross-functional",
    "corpus_bullet_prefix": "Drove experimentation framework",
    "rationale": "Swap to a corpus bullet that better demonstrates [JD requirement]. The replacement bullet exists in the corpus for this role."
  },
  {
    "type": "BULLET_PROMOTE",
    "company": "WellSky",
    "bullet_prefix": "Designed care coordination",
    "rationale": "This bullet directly addresses the JD's requirement for [X]."
  },
  {
    "type": "BULLET_CUT",
    "company": "Relatient",
    "bullet_prefix": "Maintained documentation",
    "rationale": "Low relevance to the JD; space better used for [Y]."
  },
  {
    "type": "SKILLS_REORDER",
    "new_order": ["AI & Orchestration", "Product & Analytics", "Growth & Experimentation"],
    "rationale": "JD leads with AI/ML requirements."
  },
  {
    "type": "SKILLS_RENAME",
    "old_name": "Growth & Experimentation",
    "new_name": "Experimentation & Optimization",
    "rationale": "Matches JD's terminology for this competency area."
  }
]
```

**Rules for improvement directives (disciplined mode ONLY):**
- BULLET_SWAP must reference existing corpus bullets (use prefix matching against the corpus DB). Do NOT generate new bullet text.
- Do NOT inject target company product names, team names, or org structure into any bullet
- Do NOT substitute words inside corpus bullets to match JD vocabulary
- Do NOT restructure document layout (bullet counts per role, section ordering beyond skills)
- Skill category names must use industry-standard taxonomy, not unusual JD-specific phrasing
- Maximum 8 improvement directives (focus on reordering and selection, not rewriting)
- Every directive must have a rationale tied to the specific JD or company context
- The refinement phase operates under disciplined-mode constraints: SWAP/CUT/PROMOTE/DEMOTE + fresh summary only

### Step 6: Write Results to DB

```python
from jj.db import update_pipeline_run
import json

update_pipeline_run(
    run_id,
    eval_recommended_base=recommended_base,     # "strict" or "freeform"
    eval_score_strict=score_strict,
    eval_score_freeform=score_freeform,
    eval_company_context=company_context_text,
    eval_improvements=improvements_list,         # JSON-serialized automatically
    eval_assessment=assessment_text,             # Free-text evaluation narrative
    pipeline_status="phase2",
    phase_reached=2,
)
```

### Step 7: Report

```
RESULT: EVAL_COMPLETE
App ID: [app_id]
Pipeline Run: [run_id]
Score Strict: [score_strict]
Score Freeform: [score_freeform]
Recommended Base: [strict|freeform]
Improvements: [count]
```

---

## Phase 4: Final Evaluation (`--final` flag)

When invoked with `--final`, evaluate only the final refined resume.

### Step 1: Load Pipeline Context

```python
pipeline = get_pipeline_run_by_app(app_id)
final_resume = get_resume(pipeline["resume_final_id"])
```

If `resume_final_id` is None, report error and exit.

### Step 2: Read Final Resume

Reconstruct the final resume from DB using the same `_reconstruct_resume()` approach as Phase 2 Step 2. Fall back to `GoogleDocsClient.get_document_text()` if DB reconstruction is empty.

### Step 3: Load Cached Company Context

Use the company context already stored from Phase 2 -- no need to re-research:

```python
company_context = pipeline["eval_company_context"]
jd_text = eval_report["jd_snapshot"]
```

### Step 4: Score Final Resume

Score using the same RJ rubric (0-100) including all over-tailoring deductions from Phase 2 Step 4. The same hard and soft deduction rules apply. Compare against Phase 2 scores:

- `improvement_vs_strict = final_score - pipeline["eval_score_strict"]`
- `improvement_vs_freeform = final_score - pipeline["eval_score_freeform"]`

Assign verdict:

| Score | Verdict |
|-------|---------|
| 80-100 | Strong Fit |
| 65-79 | Good Fit |
| 50-64 | Moderate Fit |
| <50 | Stretch |

Flag any regressions (final score lower than either candidate).

### Step 5: Identify Remaining Gaps

Note any JD requirements that are still not well-addressed, for awareness (not for another iteration).

### Step 6: Write Results to DB

```python
update_pipeline_run(
    run_id,
    final_score=final_score,
    final_verdict=verdict,
    final_assessment=assessment_text,
    final_remaining_gaps=remaining_gaps_text,
    pipeline_status="completed",
    phase_reached=4,
    completed_at=datetime.now().isoformat(),
)
```

### Step 7: Report

```
RESULT: FINAL_EVAL_COMPLETE
App ID: [app_id]
Pipeline Run: [run_id]
Final Score: [final_score]
Verdict: [verdict]
vs Strict: [+/- N]
vs Freeform: [+/- N]
```

## Error Handling

| Situation | Response |
|-----------|----------|
| No pipeline_run found | Report error, exit non-zero |
| Google Docs API failure | Fall back to DB reconstruction of resume content |
| WebSearch failure | Evaluate without company context; note this in assessment |
| No JD snapshot available | Fetch JD via WebFetch from application's job_url |
