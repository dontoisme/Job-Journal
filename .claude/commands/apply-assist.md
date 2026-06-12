# /apply-assist - Browser-Assisted Application Autofill

Fill an ATS application form in Don's Chrome from his profile, attach the right
archetype resume, draft screening answers in-place, and STOP at the Submit
button for his review. Don clicks Submit — never the assistant.

## Usage

```
/apply-assist <job_url>
/apply-assist <job_url> --archetype health-tech
/apply-assist --id 1234        (prospect/application id from the tracker)
```

Archetype variants: `growth`, `ai-agentic`, `health-tech`, `general` (default).
If the role is obviously health-tech or growth and no archetype was given,
suggest the better variant before filling.

## Flow

### 1. Gather the payload

```bash
source .venv/bin/activate
jj app prep --url "<job_url>" --archetype <variant>
```

This returns JSON with `name`, `contact`, `links`, `work_authorization`,
`education`, `defaults`, `screening_answers`, `archetype.pdf_path`, and the
tracker record if the URL is already known.

### 2. Open and read the form

Load the Chrome tools via ToolSearch in ONE call (tabs_context_mcp, navigate,
computer, read_page, tabs_create_mcp, form_input, file_upload). Call
`tabs_context_mcp` first; open the job URL in a NEW tab.

Click "Apply" / scroll to the application form. Read the full form before
filling anything — know every field and required marker up front.

### 3. Fill standard fields

Greenhouse typeahead/combobox gotchas (learned on a live form):
- `form_input` on a React combobox sets the text but does NOT commit the
  value. Click the field, type the value, wait ~2s, then CLICK the matching
  option in the dropdown. Verify the field shows the committed value (an "x"
  clear button appears next to committed selections).
- The phone Country selector is its own combobox and is required — search
  "United States" and click the option; the phone number reformats when
  committed.
- Education School/Degree/Discipline are typeaheads with canonical options
  ("University of Oklahoma", "Bachelor's Degree", "Finance"). Leave "End
  date year" blank (no graduation year, same rule as resumes).

Map payload values onto the form:

| Form field | Payload source |
|---|---|
| First/Last/Full/Preferred name | `name.*` |
| Email / Phone | `contact.email` / `contact.phone` |
| Location / City | `contact.location` |
| LinkedIn / GitHub / Website | `links.*` |
| Current company / title | `current_company` / `current_title` |
| Years of experience | `years_experience` |
| Work authorization / sponsorship | `work_authorization` / `defaults.requires_sponsorship` |
| How did you hear | `defaults.hear_about_us` |
| Relocation / prior employee / pronouns | `defaults.*` |
| Education fields | `education.*` (NEVER enter a graduation year) |

Use `form_input` for fields and dropdowns. Verify each section visually after
filling (read_page or screenshot) — ATS widgets (React selects, typeaheads)
sometimes swallow values.

### 4. Upload the resume

Try `file_upload` with `archetype.pdf_path`. Some Chrome client versions
reject host filesystem paths ("no longer accepts host filesystem paths") —
when that happens, do NOT click the Attach button (it opens a native picker
the assistant cannot see). Instead leave the attach for Don and put the exact
PDF path in the final summary so he can pick it in one click:
`~/Documents/Resumes/archetypes/...`. If the form also asks to paste a resume
as text, skip it when optional; if required, say so to Don rather than
pasting a degraded version.

### 5. Screening questions

- Standard questions: answer verbatim from `screening_answers` / `defaults`.
- **Salary**: if `screening_answers.salary_expectation` is empty, ASK DON
  before filling anything. Never invent a number.
- **EEO self-identification** (gender, race, veteran, disability): leave blank
  and point them out to Don at the end — they are his to answer.
- Novel questions ("Why {company}?", role-specific prompts): draft a short
  answer grounded ONLY in the corpus/resume facts (no invented metrics,
  no em-dashes, no banned phrases per resume conventions), fill it in, and
  flag it for Don's review in the summary.
- Cover letter field: if required, draft per /apply conventions (Identity ->
  Evidence -> Differentiation, interests table for hooks) and flag for review.

### 6. HARD STOP before submit

NEVER click Submit/Send/Apply-final. End with a summary message:
- Fields filled (count) and resume attached (variant)
- Drafted answers that need his eyes (quote them)
- Anything left blank and why (EEO, salary)
- "Review the tab and click Submit when happy."

Leave the tab open and untouched.

### 7. After Don confirms he submitted

Record it (CRITICAL for tracking + TWC):

```python
from datetime import datetime
from jj.db import create_application, get_connection, transition_application_status, update_application

# If a tracker record exists (payload.application.id):
transition_application_status(app_id, 'applied', reason='Submitted via apply-assist', source='manual')
update_application(app_id, applied_at=datetime.now().isoformat(),
                   activity_date=datetime.now().strftime('%Y-%m-%d'),
                   twc_activity_type='applied', resume_id=None)

# Otherwise create one:
create_application(company, position, status='applied', job_url=url,
                   applied_at=datetime.now().isoformat(),
                   activity_date=datetime.now().strftime('%Y-%m-%d'),
                   twc_activity_type='applied')
```

Confirm to Don: "Tracked. The email sync will pair the confirmation
automatically."

## Guardrails

- Don clicks Submit. No exceptions, including "just this once".
- Never fabricate: no invented salary, metrics, or facts not in corpus/profile.
- Workday/Taleo forms with account walls: fill what's reachable, then hand off
  honestly ("this one needs your login").
- If the form fights automation (canvas widgets, heavy JS), fall back to
  filling what works and listing the rest for manual entry — partial help
  beats a broken page.
- One application per invocation; don't chain to a second URL unprompted.
