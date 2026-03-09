# /fit - Resume-JD Fit Evaluator

Evaluate how well your resume matches a job description, generate a JD-optimized resume, and measure the improvement. Combines scoring, summary customization, and JD-aware bullet ranking into a single workflow.

## Usage

```
/fit <url>
/fit <url> (with JD text already pasted)
```

## Workflow

When the user invokes `/fit` with a job URL, follow these steps:

### Step 1: Fetch JD

1. Use **WebFetch** to fetch the full job description
   - Prompt: "Extract the full job description. Include: job title, company name, required skills, years of experience, responsibilities, qualifications, salary/compensation if listed, location/remote policy. Return all text content."
   - If WebFetch fails (403, etc.), try the browser tools (`mcp__claude-in-chrome__navigate` + `mcp__claude-in-chrome__get_page_text`)
   - If both fail, ask the user to paste the JD text
2. Save the JD text to a temp file for the `--jd` flag:
   ```python
   import tempfile
   jd_path = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, prefix='jd-')
   jd_path.write(jd_text)
   jd_path.close()
   ```
3. Extract: company name, job title, location, salary (if visible)

### Step 2: Check Existing Tracking

```python
from jj.config import DB_PATH
import sqlite3

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
existing = conn.execute(
    "SELECT id, company, position, status, fit_score FROM applications WHERE job_url = ?",
    (url,)
).fetchone()
conn.close()
```

If already tracked, report it but continue (the user wants to evaluate fit, not just triage).

### Step 3: Score Standard Resume (Before)

Read the corpus and profile:

```python
from jj.config import JJ_HOME
corpus_path = JJ_HOME / 'corpus.md'
corpus = corpus_path.read_text()
```

Also get the standard resume bullets (what would generate without JD):

```python
from jj.google_docs import assemble_template_data

data_standard = assemble_template_data(variant='general', max_roles=5, max_bullets_per_role=4)
```

Score the standard resume against the JD using the **Resume-JD Match rubric** (100 points):

| Category | Weight | What to Evaluate |
|----------|--------|------------------|
| **Summary alignment** | 25 pts | Does the default summary emphasize the JD's key themes? |
| **Skills coverage** | 25 pts | Are the JD's top 5 required skills listed prominently? |
| **Bullet relevance** | 35 pts | Do lead bullets at recent roles match JD priorities? |
| **Keyword density** | 15 pts | Key terms from JD present throughout the resume? |

Record the score as `rj_before`.

### Step 4: Compose Custom Summary

**This is the one place where composition (not just selection) is allowed.**

Read the available summary variants from `~/.job-journal/profile.yaml`:

```python
from jj.config import load_profile
profile = load_profile()
summaries = profile.get('summaries', {})
```

Compose a custom 2-3 sentence summary that:
1. **Leads with the JD's primary theme** (growth, platform, AI, health-tech, etc.)
2. **Includes 2-3 specific proof points** that exist in the corpus (metrics, achievements)
3. **Mirrors the JD's language** where natural (e.g., if JD says "experimentation velocity" and corpus says the same, use it)
4. **Stays honest** — only reference experiences, skills, and metrics actually present in the corpus

**Rules:**
- Keep it to 2-3 sentences, single paragraph
- Do NOT invent metrics, titles, or experiences not in the corpus
- Do NOT use the JD's exact phrasing if it describes something the user hasn't done
- USE the JD's terminology when it describes something the user HAS done

Present the custom summary to the user before generating. Show what changed vs the default.

### Step 5: Preview JD-Tailored Bullets

Get the JD-aware bullet selection:

```python
data_tailored = assemble_template_data(
    variant='general',
    max_roles=5,
    max_bullets_per_role=4,
    jd_text=jd_text,
)
```

Show the user which bullets changed per role:

```
### Bullet Changes

**ZenBusiness** (2 of 4 changed):
  - KEPT: "Scaled experimentation velocity 250%..."
  + NEW: "Configured Terraform-based A/B testing infrastructure..."
  - KEPT: "Built new self-serve acquisition funnels..."
  + NEW: "Leveraged Snowflake for data querying..."

**Wellcore** (3 of 4 changed):
  ...
```

Wait for user approval. If they want to swap specific bullets, adjust.

### Step 6: Generate Tailored Resume

Once approved, generate the resume:

```python
from jj.google_docs import generate_resume_programmatic

result = generate_resume_programmatic(
    company=company,
    position=position,
    variant='general',
    custom_summary=custom_summary,
    jd_text=jd_text,
    max_roles=5,
    max_bullets_per_role=4,
    auto_open=True,
    keep_google_doc=True,
)
```

### Step 7: Score Tailored Resume (After)

Score the tailored resume (with custom summary + JD-ranked bullets) against the same JD rubric.

Record the score as `rj_after`.

### Step 8: Present Comparison

Show a before/after comparison:

```
## Fit Evaluation: [Company] — [Position]

### Before/After

| Category | Standard | Tailored | Delta |
|----------|----------|----------|-------|
| Summary alignment | 13/25 | 21/25 | +8 |
| Skills coverage | 14/25 | 14/25 | — |
| Bullet relevance | 16/35 | 27/35 | +11 |
| Keyword density | 9/15 | 13/15 | +4 |
| **Total** | **52** | **75** | **+23** |

Verdict: Moderate Fit -> Good Fit
```

If the tailored score is below 70:
- Note which gaps are **structural** (missing experience — can't be fixed by reordering) vs **presentational** (better bullets exist but weren't surfaced)
- Suggest if it's worth applying despite the gaps

### Step 9: Save to Database

If not already tracked, insert as a prospect:

```python
from jj.db import create_application

app_id = create_application(
    company=company,
    position=title,
    job_url=url,
    location=location,
    salary_range=salary,
    fit_score=rj_after,  # Use the tailored score
    status='prospect',
    notes=f"Fit: RJ {rj_before}->{rj_after} (+{rj_after - rj_before}pts). {brief_summary_of_gaps}",
)
```

If already tracked, update the fit score:

```python
from jj.db import update_application

update_application(
    existing['id'],
    fit_score=rj_after,
    notes=f"Fit: RJ {rj_before}->{rj_after} (+{rj_after - rj_before}pts). {brief_summary_of_gaps}",
)
```

### Step 10: Offer Next Steps

```
Resume saved: [pdf_path]
Google Doc: [doc_url]

What next?
- `/apply <url>` — Full application workflow (cover letter, form answers)
- `/fit <another url>` — Evaluate another job
- Open the Google Doc to make manual edits before applying
```

## Content Integrity Rules

**SELECT, don't COMPOSE** applies to everything except the summary:
- Bullets come verbatim from corpus — the `--jd` flag only changes WHICH bullets are selected and their ORDER
- Do NOT paraphrase, combine, merge, or rewrite bullets
- Do NOT add metrics, company names, or technologies not in the corpus
- Summary IS composed fresh but must only reference real corpus content

## Error Handling

| Situation | Response |
|-----------|----------|
| URL not accessible | Try browser tools, then ask user to paste JD |
| No corpus found | Stop: "Run `/interview` first" |
| Tailored score < 50 | "This is a structural mismatch — tailoring can't close the gap. Consider skipping." |
| Tailored score 50-69 | "Presentable but gaps remain. Worth applying if the company/role is compelling." |
| Tailored score 70+ | "Strong match after tailoring. Recommend applying." |

## Notes

- **Score uses same rubric as /apply Steps 2b/3b** — scores are directly comparable
- **Bullets are selected, not generated** — the JD-aware ranker uses keyword matching against bullet text + tags
- **Summary is the lever** — often the biggest score improvement comes from a JD-matched summary
- **Structural gaps can't be fixed** — if the corpus doesn't have relevant experience, no amount of reordering helps. Be honest about this.
- **Pairs with /score** — use `/score` for batch triage, `/fit` for deep evaluation of promising leads
