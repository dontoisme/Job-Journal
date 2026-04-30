# /resume-refine - Apply Evaluation Improvements and Generate Final Resume

Takes the evaluation agent's improvement directives and generates the final refined resume with PDF export.

## Critical: Headless Mode Rules

- Do NOT prompt the user for input or approval at any point
- Make all decisions autonomously
- If any step fails, report the error clearly and exit
- Output final resume to `~/Documents/Resumes/YYYY-MM-DD/slack/Company/`

## Usage

```
/resume-refine <app_id>
```

## Workflow

### Step 1: Load Pipeline Context

```python
from jj.db import get_pipeline_run_by_app, get_resume, get_evaluation_report
from jj.config import DB_PATH
import sqlite3

pipeline = get_pipeline_run_by_app(app_id)
if not pipeline:
    print("ERROR: No pipeline run found for app", app_id)
    exit(1)

if pipeline["pipeline_status"] != "phase2":
    print(f"ERROR: Pipeline not ready for refinement (status: {pipeline['pipeline_status']})")
    exit(1)

run_id = pipeline["id"]
recommended_base = pipeline["eval_recommended_base"]  # "strict" or "freeform"
improvements = pipeline["eval_improvements"]           # Already deserialized from JSON
base_resume_id = pipeline["resume_strict_id"] if recommended_base == "strict" else pipeline["resume_freeform_id"]
```

### Step 2: Load Base Resume Content

Load the recommended base resume's content from DB:

```python
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Get summary
summary_section = conn.execute(
    "SELECT content FROM resume_sections WHERE resume_id = ? AND section_type = 'summary' LIMIT 1",
    (base_resume_id,)
).fetchone()
base_summary = dict(summary_section)["content"] if summary_section else None

# Get skills by category
skill_sections = conn.execute(
    "SELECT section_name, content FROM resume_sections WHERE resume_id = ? AND section_type = 'skills' ORDER BY position",
    (base_resume_id,)
).fetchall()
base_skills = {dict(s)["section_name"]: dict(s)["content"].split(", ") for s in skill_sections}

# Get bullets by role
bullets_query = conn.execute(
    "SELECT r.company, e.text, re.position FROM resume_entries re "
    "JOIN entries e ON re.entry_id = e.id JOIN roles r ON re.role_id = r.id "
    "WHERE re.resume_id = ? ORDER BY re.role_id, re.position",
    (base_resume_id,)
).fetchall()
conn.close()

base_bullets = {}
for row in bullets_query:
    row = dict(row)
    company = row["company"]
    if company not in base_bullets:
        base_bullets[company] = []
    base_bullets[company].append(row["text"])
```

Also load the application details and JD:

```python
from jj.db import get_application, get_evaluation_report

app = get_application(app_id)
eval_report = get_evaluation_report(app_id)
jd_text = eval_report["jd_snapshot"] if eval_report else None
company = app["company"]
position = app["position"]
```

Load archetype from app notes (extract from "Archetype: X" in notes) and earlier_roles from profile:

```python
from jj.config import load_config
config = load_config()
profile = config.get("profile", {})
earlier_roles = profile.get("earlier_roles", [])
```

### Step 3: Apply Improvement Directives

Process each directive from the evaluation agent:

```python
refined_summary = base_summary
refined_skills = dict(base_skills)
refined_bullets = dict(base_bullets)

for directive in improvements:
    dtype = directive["type"]

    if dtype == "SUMMARY":
        refined_summary = directive["new_text"]

    elif dtype == "BULLET_SWAP":
        company_name = directive["company"]
        old_prefix = directive["old_prefix"]
        new_text = directive["new_text"]
        if company_name in refined_bullets:
            refined_bullets[company_name] = [
                new_text if b.startswith(old_prefix) else b
                for b in refined_bullets[company_name]
            ]

    elif dtype == "BULLET_PROMOTE":
        company_name = directive["company"]
        prefix = directive["bullet_prefix"]
        if company_name in refined_bullets:
            bullets = refined_bullets[company_name]
            for i, b in enumerate(bullets):
                if b.startswith(prefix) and i > 0:
                    bullets.insert(0, bullets.pop(i))
                    break

    elif dtype == "BULLET_CUT":
        company_name = directive["company"]
        prefix = directive["bullet_prefix"]
        if company_name in refined_bullets:
            refined_bullets[company_name] = [
                b for b in refined_bullets[company_name]
                if not b.startswith(prefix)
            ]

    elif dtype == "SKILLS_REORDER":
        new_order = directive["new_order"]
        reordered = {}
        for cat in new_order:
            if cat in refined_skills:
                reordered[cat] = refined_skills[cat]
        for cat, skills in refined_skills.items():
            if cat not in reordered:
                reordered[cat] = skills
        refined_skills = reordered

    elif dtype == "SKILLS_RENAME":
        old_name = directive["old_name"]
        new_name = directive["new_name"]
        if old_name in refined_skills:
            refined_skills[new_name] = refined_skills.pop(old_name)
```

### Step 4: Content Integrity Check

Before generating, verify:

- No em-dashes in `refined_summary` or any bullet
- SpareFoot and IBM not in main experience roles
- GitHub URL: github.com/dontoisme
- No graduation year in education
- If base is strict: verify all bullets exist in corpus DB

```python
# Quick em-dash check
for text in [refined_summary] + [b for bullets in refined_bullets.values() for b in bullets]:
    if "—" in text:
        text = text.replace("—", ";")  # Auto-fix
```

### Step 5: Score Refined Content

Score the refined content against the JD using the RJ rubric:

| Category | Points |
|----------|--------|
| Summary alignment | 25 |
| Skills coverage | 25 |
| Bullet relevance | 35 |
| Keyword density | 15 |

Record `rj_before` (base resume score from pipeline) and `rj_after` (refined score).

### Step 6: Generate Final Resume (Doc + PDF)

```python
from jj.google_docs import generate_resume_programmatic
from pathlib import Path
from datetime import date

today = date.today().isoformat()  # YYYY-MM-DD
output_dir = Path.home() / "Documents" / "Resumes" / today / "slack" / company
output_dir.mkdir(parents=True, exist_ok=True)

mode = "strict" if recommended_base == "strict" else "optimized"

result_final = generate_resume_programmatic(
    company=company,
    position=position,
    variant=archetype,
    mode=mode,
    custom_summary=refined_summary,
    custom_skills=refined_skills,          # dict[str, list[str]]
    role_bullets=refined_bullets,           # dict[str, list[str]]
    earlier_roles=earlier_roles,
    max_roles=5,
    max_bullets_per_role=6,
    jd_text=jd_text,
    output_dir=output_dir,                  # YYYY-MM-DD/slack/Company/
    auto_open=False,
    keep_google_doc=True,
    export_pdf=True,                        # Final gets PDF
    generation_mode="final",
    pipeline_run_id=run_id,
)
```

If `result_final.success` is False, report the error and exit.

### Step 7: Validate Content

```python
from jj.resume_gen import validate_resume_content

all_bullets = [b for bullets in refined_bullets.values() for b in bullets]
is_valid, drift_score, results = validate_resume_content(
    bullets=all_bullets,
    fail_fast=False,
)
```

### Step 8: Update Pipeline Run and Application

```python
from jj.db import update_pipeline_run, update_application

update_pipeline_run(
    run_id,
    resume_final_id=result_final.resume_id,
    pipeline_status="phase3",
    phase_reached=3,
)

rj_before = pipeline.get("eval_score_strict") if recommended_base == "strict" else pipeline.get("eval_score_freeform")

update_application(
    app_id,
    resume_id=result_final.resume_id,
    rj_before=rj_before,
    rj_after=rj_after,
    notes=f"{app.get('notes', '')} | RJ:{rj_before}→{rj_after} (+{rj_after - rj_before}pts), variant={archetype}, pipeline=refined",
)
```

### Step 9: Report

```
RESULT: REFINE_COMPLETE
App ID: [app_id]
Pipeline Run: [run_id]
Resume Final ID: [resume_id]
Base: [strict|freeform]
Improvements Applied: [count]
RJ Before: [rj_before]
RJ After: [rj_after]
PDF: [pdf_path]
Doc URL: [doc_url]
Valid: [yes/no]
Drift: [drift_score]
```

## Error Handling

| Situation | Response |
|-----------|----------|
| No pipeline_run found | Report error, exit non-zero |
| Pipeline not at phase2 | Report error with current status, exit |
| Base resume content missing | Report error, exit non-zero |
| Directive parsing failure | Skip failed directive, log warning, continue with others |
| Google Docs API failure | Report error, exit non-zero (no fallback for final resume) |
| Integrity audit failure | Fix and retry once; if still failing, report |
