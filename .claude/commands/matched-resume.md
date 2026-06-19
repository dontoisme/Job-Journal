# /matched-resume - JD-Mirroring "Matched" Resume Format

Generate the **matched** resume format for ONE role: a tight resume engineered to
read as a no-brainer "this candidate needs to talk to us." It mirrors the JD's
exact skill wording, orders bullets to tell a matching story, and compresses the
main Experience section to the last ~5 years (older roles fall back to Earlier
Experience and lend their skills to the skills section). Additive format — it does
not change disciplined/strict/freeform. Bullets stay corpus-verbatim; the
integrity audit is the same hard gate.

## Usage

```
/matched-resume <job_url>
/matched-resume --id <application_id>
```

## 1. Load context (read once)

```python
import sqlite3, yaml
from jj.config import DB_PATH, CORPUS_PATH, PROFILE_PATH
APP_ID = <id>            # resolve from --id, or look up by job_url
conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
app = dict(conn.execute(
    "SELECT id, company, position, job_url, notes, research_brief, fit_score FROM applications WHERE id=?",
    (APP_ID,)).fetchone())
corpus = CORPUS_PATH.read_text()
profile = yaml.safe_load(PROFILE_PATH.read_text())
```

- JD: prefer the stored `research_brief` + `notes`; for live text WebFetch
  `app['job_url']` (WebFetch only, no browser; for a JS shell or a blocked
  financial domain like a bank, proceed from `research_brief` + title). The
  Greenhouse/Ashby public APIs are good structured fallbacks.
- Archetype variant: parse `Archetype: <variant>` from `app['notes']` (default
  `general`) — this is the summary base + bullet pool.

## 2. Read the JD into two lists (this is the matched format's core input)

From the JD, extract — in the JD's **exact wording**:
1. **`jd_skill_terms`**: the required + preferred skills/keywords, most-important
   first (e.g. `["PLG", "funnel optimization", "experimentation", "GTM partnerships"]`).
2. **`jd_requirements`**: the role's top responsibility themes in priority order
   (e.g. `["own the acquisition funnel", "partner with sales on enterprise deals"]`).

Do not invent. These come straight from the JD text.

## 3. Compress to the last ~5 years (code helpers do the deterministic part)

```python
from datetime import datetime
from jj.db import get_roles_ordered_by_date, get_skills_by_category
from jj.google_docs import (
    split_roles_by_window, roles_to_earlier_dicts,
    collect_skill_pool_from_roles, build_matched_skills,
)

roles = [r for r in get_roles_ordered_by_date(limit=None)
         if "project" not in (r.get("company") or "").lower()]
main_window, earlier = split_roles_by_window(
    roles, datetime.now(), max_years_lookback=5, min_roles=4)
```

- `main_window` = roles inside the 5-year window (floored to 4 so a strong
  near-cutoff role survives). If `len(main_window) > 5`, **you** drop the least
  JD-relevant in-window roles (e.g. a 1-month stint or an off-domain side role),
  keeping the resume tight and reverse-chronological. The kept companies, in
  date-desc order, become `role_companies`.
- Build Earlier Experience, **deduped against `profile.earlier_roles`** (the
  profile entries have clean dates and cover SpareFoot/IBM; the audit rejects
  duplicate company names, so profile entries win):

```python
profile_earlier = profile.get("earlier_roles", []) or []
profile_companies = {e["company"] for e in profile_earlier}
db_earlier = [d for d in roles_to_earlier_dicts(earlier)
              if d["company"] not in profile_companies]
earlier_roles = db_earlier + profile_earlier
```

## 4. Skills section — mirror the JD, substantiated only

```python
dropped_pool = collect_skill_pool_from_roles([r["id"] for r in earlier])
matched_skills = build_matched_skills(
    jd_skill_terms, get_skills_by_category(), extra_skill_pool=dropped_pool)
```

- `build_matched_skills` emits a JD term **only when Don genuinely has it**
  (canonical skills + skills demonstrated by the demoted older roles), in the
  JD's exact wording. A term with no corpus backing is dropped — never stuff
  keywords Don can't substantiate.
- You may rename/merge the returned category labels to clean,
  industry-standard headers (e.g. fold a "Core Skills" bucket into the right
  named category) and reorder to lead with the JD's top priority. Keep the JD's
  exact skill wording. Cap at 5 categories.

## 5. Bullets — select verbatim, order to tell the story

For each company in `role_companies`, get the JD-ranked corpus bullets, then
order them to lead with the JD's #1 requirement:

```python
from jj.google_docs import assemble_template_data, order_bullets_for_story
data = assemble_template_data(max_roles=len(role_companies),
                              max_bullets_per_role=5,
                              jd_text=jd_text, role_companies=role_companies)
role_bullets = {}
for r in data.roles:
    role_bullets[r.company] = order_bullets_for_story(r.bullets, jd_requirements)
```

Bullets are SELECTED verbatim from the corpus and only REORDERED — never
rewritten, merged, or invented.

## 6. Summary + generate

- **Summary** composed fresh (Identity -> Evidence -> Differentiation), grounded
  only in corpus/profile/brief, angled at the JD. No em-dashes, no banned phrases
  ("12+ years", "proven track record", "results-driven", "passionate", "deep
  experience in").

```python
from datetime import date
from pathlib import Path
from jj.google_docs import generate_resume_programmatic
from jj.db import update_application

result = generate_resume_programmatic(
    company=app["company"], position=app["position"], variant="<archetype>",
    mode="strict",                       # bullets re-checked against corpus + audit
    generation_mode="matched",
    custom_summary="<composed summary>",
    custom_skills=matched_skills,
    role_bullets=role_bullets,           # company -> story-ordered verbatim bullets
    role_companies=[r.company for r in data.roles],   # 5yr main set, date-desc
    earlier_roles=earlier_roles,
    jd_text=jd_text,
    output_dir=Path.home() / "Documents" / "Resumes" / date.today().isoformat(),
    auto_open=False, keep_google_doc=True, export_pdf=True,
)
update_application(APP_ID, resume_id=getattr(result, "resume_id", None),
                   staged_resume_path=str(getattr(result, "pdf_path", "") or ""))
print("MATCHED:", getattr(result, "pdf_path", None))
```

## 7. Output — show what changed (for Don's review)

Print the path, then a short diff for review:
- **Skills** relabeled to the JD's exact terms (and any term you dropped as
  unsubstantiated).
- **Roles moved** to Earlier Experience by the 5-year cut.
- **Bullet order** changes per role (which requirement each now leads with).

Never auto-submit. If generation fails (e.g. Google Docs auth), print the error
and exit non-zero without writing `staged_resume_path`.

## Guardrails

- Bullets corpus-verbatim only (`mode="strict"` + `_pre_export_audit` are hard
  gates). Skills use the JD's exact wording **only when substantiated** by the
  corpus — no keyword stuffing.
- No invented metrics/companies, no em-dashes, no banned phrases, no graduation
  year. SpareFoot/IBM stay in Earlier Experience.
- One application per invocation; browser-free; no Submit.
