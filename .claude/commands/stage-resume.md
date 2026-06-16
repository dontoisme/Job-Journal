# /stage-resume - Headless Disciplined Resume Tailor

Generate a disciplined, per-JD tailored resume for ONE tracked application and
persist it (resume_id + staged_resume_path) so it is ready before the apply-ready
Slack notification. Browser-free; spawned headlessly by `prep_apply_packages`
for high-fit (>= 85) apply-ready prospects. Lower-fit prospects get a plain
archetype copy instead and do not invoke this skill.

## Usage

```
/stage-resume --id <application_id>
```

## 1. Load context (read once)

```python
import sqlite3
from jj.config import DB_PATH, CORPUS_PATH
APP_ID = <id>
conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
app = dict(conn.execute(
    "SELECT id, company, position, job_url, notes, research_brief, fit_score FROM applications WHERE id=?",
    (APP_ID,)).fetchone())
corpus = CORPUS_PATH.read_text()
```

- JD: prefer the application's stored context; if you need the live text, WebFetch
  `app['job_url']` (no browser — WebFetch only; on a JS shell, proceed from the
  `research_brief` + title rather than blocking).
- Archetype variant: parse `Archetype: <variant>` from `app['notes']` (default
  `general`). This is the summary variant + base.

## 2. Compose the tailor (disciplined mode — SELECT, don't COMPOSE)

Same bar as the HireVue/Maven tailors:
- **Summary** composed fresh (Identity -> Evidence -> Differentiation), grounded
  only in corpus/profile/brief. No em-dashes, no banned phrases.
- **Skills** reordered/filtered to lead with the JD's top categories.
- **Bullets** SELECTED verbatim from the corpus, ranked by JD relevance. Never
  rewrite, merge, or invent. Pull the corpus bullets from the DB
  (`roles`/`entries` tables) so they match exactly; `mode="strict"` re-checks
  them against the corpus and the code-level integrity audit refuses to export
  on any violation (non-corpus bullet, em-dash, duplicate company, SpareFoot/IBM
  in main Experience, missing Projects, graduation year).
- Reverse-chronological roles; SpareFoot/IBM stay in `earlier_roles`.

## 3. Generate + persist

```python
from datetime import date
from pathlib import Path
from jj.google_docs import generate_resume_programmatic
from jj.db import update_application

result = generate_resume_programmatic(
    company=app["company"],
    position=app["position"],
    variant="<archetype>",
    mode="strict",
    custom_summary="<composed summary>",
    custom_skills=<dict[str, list[str]]>,   # display name -> list of skills
    role_bullets=<dict[str, list[str]]>,    # company -> verbatim corpus bullets
    earlier_roles=<from profile.yaml earlier_roles>,
    jd_text="<JD or research_brief context>",
    output_dir=Path.home() / "Documents" / "Resumes" / date.today().isoformat(),
    auto_open=False, keep_google_doc=True, export_pdf=True,
)

update_application(
    APP_ID,
    resume_id=getattr(result, "resume_id", None),
    staged_resume_path=str(getattr(result, "pdf_path", "") or ""),
)
print("STAGED:", getattr(result, "pdf_path", None))
```

## 4. Output

Print `STAGED: <pdf_path>` on success. If generation fails (e.g. Google Docs
auth), print the error and exit non-zero WITHOUT writing `staged_resume_path` --
the caller (`prep_apply_packages`) then falls back to an archetype copy so the
Slack notification still carries a resume.

## Guardrails

- Browser-free and unattended: no prompts, no Submit, no form filling.
- Never fabricate; every bullet traces verbatim to the corpus. Integrity audit is
  a hard gate, not a suggestion.
- One application per invocation.
