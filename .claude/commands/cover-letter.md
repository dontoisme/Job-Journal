# /cover-letter - Tailored Cover Letter Drafter

Draft a tailored, corpus-grounded cover letter for a tracked application, save an
attachable `.docx` plus a paste-ready `.txt` to the dated resume folder, and
present the full draft for Don's review. Used standalone, or called conditionally
by `/apply-assist` when a form has a cover letter field.

This is a **deeper-review artifact** — never submit/attach/paste it automatically.
Draft it, show it, and let Don edit and decide.

## Usage

```
/cover-letter --id <application_id>
/cover-letter <job_url>
```

## 1. Load context (read once)

- Application (`jj.db`): `company`, `position`, `job_url`, `research_brief`, `jd_snapshot`.
- Corpus: `~/.job-journal/corpus.md` — the ONLY source for "why me" facts.
- Profile: `~/.job-journal/profile.yaml` — name + contact for the letterhead.

If `research_brief` is empty and this is a real target (fit >= 80 or a priority
company), run `/research-brief --id N` first and persist it, so the why-now and
why-company claims are sourced rather than invented. Otherwise proceed but keep
company claims generic (no unsourced specifics).

## 2. Draft rules (same integrity bar as resumes and briefs)

- **Structure:** Identity-First — Identity → Evidence → Differentiation. 3-4 short
  paragraphs, ~250-350 words total.
- **Open** `Dear Hiring Team,` — never fabricate a hiring manager's name.
- **Para 1 (Identity + why-now):** who Don is and the role, anchored to a demand
  driver from `research_brief` (a sourced claim, not an invented one).
- **Para 2-3 (Evidence):** 2-3 concrete accomplishments that map to the JD's top
  needs. Every metric, company, and skill must trace **verbatim** to `corpus.md`.
  No invented numbers, clients, or technologies.
- **Para 4 (Differentiation + close):** the "why me" angle from the brief, a
  forward-looking line, then `Sincerely,` / `Don Hogan`.
- **Banned:** em-dashes anywhere; the phrases "12+ years", "proven track record",
  "results-driven", "passionate", "deep experience in"; any fact not in
  corpus/profile/brief.

## 3. Generate the files

Compose the letter, then save `.docx` (attachable) + `.txt` (paste-ready) to the
dated folder, matching the resume naming convention. `textutil` (macOS built-in)
does the HTML->docx conversion; no extra dependencies.

```python
import os, html, subprocess
from datetime import date

COMPANY  = "<company>"
POSITION = "<position>"
# Compose these — corpus-grounded, guardrails above. No em-dashes, no banned phrases.
SALUTATION = "Dear Hiring Team,"
BODY = [
    "<para 1: identity + why-now, anchored to a sourced demand driver>",
    "<para 2: evidence, corpus-verbatim accomplishment mapped to a top JD need>",
    "<para 3: evidence, second accomplishment>",
    "<para 4: differentiation + forward-looking close>",
]
CLOSE = "Sincerely,\nDon Hogan"

# Letterhead from profile (keep in sync with profile.yaml)
HEADER = ["Don Hogan", "Austin, TX  |  don.r.hogan@gmail.com  |  (281) 239-9416",
          "linkedin.com/in/dhogan"]

out_dir = os.path.expanduser(f"~/Documents/Resumes/{date.today().isoformat()}")
os.makedirs(out_dir, exist_ok=True)
base = os.path.join(out_dir, f"Don Hogan - {POSITION} - {COMPANY} - Cover Letter")

# Plain text (review + paste)
txt = "\n".join(HEADER) + "\n\n" + SALUTATION + "\n\n" + "\n\n".join(BODY) + "\n\n" + CLOSE + "\n"
with open(base + ".txt", "w") as f:
    f.write(txt)

# HTML -> .docx (attachable). textutil cannot emit PDF; docx is ATS-accepted.
def esc(s): return html.escape(s).replace("\n", "<br>")
html_doc = (
    '<html><body style="font-family:Georgia,serif;font-size:12pt;line-height:1.45">'
    + "".join(f'<p style="margin:0">{esc(h)}</p>' for h in HEADER)
    + f'<p>{esc(SALUTATION)}</p>'
    + "".join(f"<p>{esc(p)}</p>" for p in BODY)
    + f"<p>{esc(CLOSE)}</p></body></html>"
)
html_path = base + ".html"
with open(html_path, "w") as f:
    f.write(html_doc)
subprocess.run(["textutil", "-convert", "docx", html_path, "-output", base + ".docx"], check=True)
os.remove(html_path)
print("DOCX:", base + ".docx")
print("TXT :", base + ".txt")
```

## 4. Present for review (do NOT submit)

Print the full letter text inline, then the two saved paths. Tell Don:
- this is his to review and edit;
- for a **file** cover-letter field, attach the `.docx` (Chrome blocks host-path
  upload, so he attaches it himself — same as the resume);
- for a **text/paste** field, the `.txt` is ready to paste on his go-ahead.

Never attach, paste, or submit the letter without Don's explicit confirmation.
