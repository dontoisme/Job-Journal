# /apply - Job Application Assistant

Evaluate a specific job link (e.g. one a friend or recruiter sends), score the
fit against the corpus, track it as a prospect, and — if it qualifies — chain
straight into `/apply-assist` to autofill the application. Built on the current
`jj` / `~/.job-journal` system (NOT the deprecated `~/.job-apply` pandoc/CSV
workflow).

## Usage

```
/apply <job_url>
/apply --id <prospect_id>     # re-run on an already-tracked prospect
```

## System context (read once)

- Corpus (source of truth for "why me"): `~/.job-journal/corpus.md`
- Profile (contact, work auth, defaults): `~/.job-journal/profile.yaml`
- Tracking + scoring live in `~/.job-journal/journal.db` via `jj.db`.
- Resumes are the 4 archetypes (`growth`, `ai-agentic`, `health-tech`,
  `general`) in `~/.job-journal/archetypes.yaml`; generation goes through
  `generate_resume_programmatic` with the code-level integrity audit.
- Downstream skills: `/research-brief --id N` (cited why-now/why-me) and
  `/apply-assist --id N` (browser autofill, stops at Submit).

## Workflow

### 1. Fetch the JD

WebFetch the URL. Detect the ATS from the host: `greenhouse`, `lever`,
`ashby`, `teamtailor`, `workday`, `amazon.jobs`, or custom. If WebFetch returns
nothing (JS-rendered SPA) or a cross-host redirect, retry the redirect URL, then
fall back to browser tools or ask the user to paste the JD. Capture title,
company, location/remote, salary, responsibilities, and required quals.

### 2. Score the fit (vs the corpus)

Read `corpus.md` + `profile.yaml`. Score against the standard rubric and present
a structured assessment:

| Category | Pts | Evaluate |
|----------|-----|----------|
| Skills | 35 | JD must-haves present in corpus |
| Experience | 25 | Seniority + scope match |
| Domain | 30 | Industry/problem-space fit |
| Location | 10 | Remote/US/Austin-friendly |

```
## Fit Assessment — <company>, <title>
**Match Score: NN% — <Verdict>**
### Strengths   (3, each traced to a real corpus item)
### Gaps / Considerations   (honest; include comp vs the MANGO high-comp target)
### Recommendation
```

Verdicts: 85+ Strong · 70–84 Good · 55–69 Moderate · 40–54 Stretch · <40 Long shot.
"Why me" must trace to the corpus — no invented experience, metrics, or skills.

### 3. Track it as a prospect

```python
from jj.db import find_duplicate_application, create_application
# skip if find_duplicate_application(company, position, job_url) returns a row
create_application(company, position, job_url=url, location=..., status="prospect",
    fit_score=NN, ats_type=<ats>, salary_range=<lo-hi or "">,
    notes="Fit: NN% (<Verdict>). Archetype: <variant>. <one-line rationale>.")
```
No `source` column — put provenance (e.g. "via referral") in `notes`. Set
`twc_activity_type`/`applied_at` only once actually submitted (in step 5).

### 4. Pick the archetype

Map the JD to one variant: `growth` (PLG/experimentation/monetization/activation),
`ai-agentic` (AI/agents/LLM/MCP/orchestration), `health-tech` (clinical/EHR/
patient/payer), `general` (balanced). State the pick and reasoning.

### 5. Chain by qualification

| Fit | Action |
|-----|--------|
| **≥ 80** | **Qualifies — chain `/apply-assist --id N`** (it generates the research brief, stages the dated archetype resume, autofills the form, stops at Submit). |
| 65–79 | Offer `/apply-assist`; link the archetype resume regardless. |
| < 65 | Track only; recommend skip or manual review. Ask before proceeding. |

When chaining, note the ATS reality: account-walled portals (Amazon, Workday,
some TeamTailor) require the user to log in first — fill what's reachable, hand
off the login, never authenticate as the user. After the user confirms they
submitted, mark applied:

```python
from datetime import datetime
from jj.db import transition_application_status, update_application
transition_application_status(app_id, 'applied', reason='Submitted via apply-assist', source='manual')
update_application(app_id, applied_at=datetime.now().isoformat(),
    activity_date=datetime.now().strftime('%Y-%m-%d'), twc_activity_type='applied')
```

## Guardrails

- "Select, don't compose" — resume bullets trace verbatim to the corpus; the
  integrity audit is a hard gate. Summaries composed fresh, corpus-grounded.
- Never fabricate metrics, companies, or skills. No em-dashes, no banned phrases.
- `/apply-assist` fills; the human reviews and clicks Submit. Never auto-submit.
- Salary, EEO, and legal attestations are the user's. Ask before filling salary.
