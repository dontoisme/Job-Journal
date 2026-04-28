# /apply - Job Application Assistant

Guide users through job applications with fit assessment and resume tailoring.

## Usage

```
/apply <job_url>
/apply <job_url> --strict
/apply https://job-boards.greenhouse.io/company/jobs/123
```

## Resume Generation Modes

| Mode | Flag | Python `mode=` | Behavior |
|------|------|----------------|----------|
| **Disciplined** (default) | _(none)_ | `"strict"` | Compose summary fresh. Reorder/filter skills. Bullet changes limited to SWAP/CUT/PROMOTE/DEMOTE against corpus. DB-validated output. |
| **Strict** | `--strict` | `"strict"` | Corpus bullets verbatim, no operations of any kind. |
| **Freeform** | `--freeform` | `"optimized"` | Full rewrite (old behavior). Only when corpus framing genuinely can't serve the JD. All facts must still trace to base.md. |

**When to use freeform:** Only when a specific JD requires framing that SWAP operations can't achieve (e.g., healthcare experience described in fintech terms, or corpus has the right facts but wrong emphasis that reordering can't fix). Never use freeform as the default.

### Disciplined Mode (Default)

**Composed fresh (Claude writes):**
- Summary paragraph — Identity-First framework, all facts from base.md

**Reordered and filtered (not composed):**
- Skills section — categories selected and reordered for JD; items from base.md only

**Mechanical operations only (for bullets):**

| Operation | Syntax | Constraint |
|-----------|--------|------------|
| **SWAP** | `SWAP <current> FOR <corpus_bullet>` | Both must exist in corpus for the same role |
| **CUT** | `CUT <bullet>` | Role must retain 2+ bullets after cut |
| **PROMOTE** | `PROMOTE <bullet> to position N` | Within same role only |
| **DEMOTE** | `DEMOTE <bullet> to position N` | Within same role only |

If CUT would drop a role below 2 bullets, use SWAP instead (replace the weak bullet with a stronger corpus alternative).

**Claude must NOT in disciplined mode:**
- Rewrite, paraphrase, merge, or rephrase any bullet text
- Add words, metrics, or details not in the corpus bullet
- Move bullets between roles
- Make any change that doesn't fit SWAP/CUT/PROMOTE/DEMOTE

**Auto-included sections:**
- Projects — from corpus DB (roles with "project" in company name)
- Earlier Experience — from `profile.yaml` `earlier_roles`
- Education — no graduation year

## Workflow

When the user invokes `/apply` with a job URL, follow these steps:

### Step 0: Duplicate Check

Before doing anything, check if this company/role has been seen before:

```python
from jj.db import DB_PATH
import sqlite3

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Check applications (applied before?)
apps = conn.execute(
    "SELECT company, position, status, applied_at FROM applications WHERE company LIKE ? OR job_url = ?",
    (f"%{company}%", job_url)
).fetchall()

# Check prospects (evaluated before?)
prospects = conn.execute(
    "SELECT company, role, fit_score, date_added FROM prospects WHERE company LIKE ? OR url = ?",
    (f"%{company}%", job_url)
).fetchall()
```

**If matches found, present them:**
```
## Previous History: [Company]

**Applications:**
- [Position] — [status] on [date] (fit: X%)

**Prospects:**
- [Role] — scored X% on [date]

Continue with this application? [Y/n]
```

If no matches, proceed silently.

### Step 1: Fetch and Analyze Job Description

1. Use WebFetch to retrieve the job posting page
2. Extract:
   - Job title
   - Company name
   - Location/remote status
   - Key requirements and qualifications
   - Any custom application questions visible on the page
3. Detect ATS type from URL pattern:
   - `greenhouse.io` or `boards.greenhouse.io` → Greenhouse
   - `jobs.lever.co` → Lever
   - `ashbyhq.com` → Ashby
   - Other → Note the ATS type for manual apply

### Step 1b: Log as Prospect

Immediately after extracting JD data, log this role as a prospect so it's tracked regardless of whether the user proceeds:

```python
from jj.db import DB_PATH
import sqlite3
from datetime import date

conn = sqlite3.connect(DB_PATH)
conn.execute(
    """INSERT OR IGNORE INTO prospects (company, role, location, salary_range, ats_type, url, source, date_added)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
    (company, position, location, salary_range, ats_type, job_url, source, date.today().isoformat())
)
conn.commit()
```

This ensures every JD you evaluate is trackable. The fit_score, recommendation, and notes get updated after Step 2.

### Step 2: Assess Job Fit

Evaluate the match between the JD and the user's corpus. Present a structured assessment:

**Format:**
```
## Fit Assessment

**Match Score:** [X]% — [Verdict]

### Strengths
- [Key alignment point 1]
- [Key alignment point 2]
- [Key alignment point 3]

### Gaps/Considerations
- [Gap or concern 1]
- [Gap or concern 2]

### Recommendation
[One of the verdicts below with brief rationale]
```

**Scoring Guide:**

| Score | Verdict | Description |
|-------|---------|-------------|
| 85-100% | Strong Fit | Core requirements align well, minor gaps at most |
| 70-84% | Good Fit | Solid alignment with transferable experience covering gaps |
| 55-69% | Moderate Fit | Some alignment, notable gaps but addressable |
| 40-54% | Stretch | Significant gaps, but compelling angles exist |
| <40% | Long Shot | Major misalignment, unlikely to progress |

**Recommendation Options:**

| Recommendation | When to Use |
|----------------|-------------|
| **Apply with tailored resume** | 70%+ match, good story to tell |
| **Apply with standard resume** | 55-69% match, worth a shot without heavy customization |
| **Consider carefully** | 40-54% match, only if company/role is compelling |
| **Skip** | <40% match, time better spent elsewhere |

**After presenting the assessment:**
- If Skip recommended, ask: "Want me to proceed anyway, or save this one for later?"
- Otherwise, proceed to Resume-JD scoring

### Step 2b: Resume-JD Match Score

Before generating a tailored resume, score the **standard resume** against the JD to determine if tailoring is actually needed.

#### Scoring Categories (100 points total)

| Category | Points | What to Evaluate |
|----------|--------|------------------|
| **Summary alignment** | 25 | Does current summary emphasize JD's key themes? |
| **Skills coverage** | 25 | Are JD's top 5 required skills listed prominently? |
| **Bullet relevance** | 35 | Do lead bullets at recent roles match JD priorities? |
| **Keyword density** | 15 | Key terms from JD present throughout resume? |

#### Scoring Process

1. **Extract JD requirements** — List the top 5-7 must-have skills/experiences from JD
2. **Check corpus** — Compare against `~/.job-journal/corpus.md`
3. **Score each category:**
   - Full points: Strong alignment, no changes needed
   - Partial points: Present but not prominent/optimized
   - Zero points: Missing or buried

4. **Present scoring table:**
   ```
   ## Resume-JD Match Score: [Company] [Role]

   | Category | Score | Notes |
   |----------|-------|-------|
   | Summary alignment | X/25 | [Brief note] |
   | Skills coverage | X/25 | [Brief note] |
   | Bullet relevance | X/35 | [Brief note] |
   | Keyword density | X/15 | [Brief note] |
   | **Total** | **X/100** | |
   ```

#### Decision Thresholds

| Resume Score | Action | Rationale |
|--------------|--------|-----------|
| **85-100%** | Use standard resume as-is | Strong alignment, tailoring adds minimal value |
| **<85%** | Full custom tailor | Tailor summary, skills, and bullet selection to match JD |

### Step 3: Generate Tailored Resume

#### Content Integrity Rules (CRITICAL)

**All modes:**
- No em-dashes anywhere in the resume. Periods, semicolons, or commas.
- Role dates must exactly match base.md corpus dates
- No invented specifics (metrics, company names, technologies)
- GitHub URL: github.com/dontoisme
- No graduation year in education
- SpareFoot and IBM appear ONLY in Earlier Experience, never in main Experience

**Disciplined mode (additional):**
- Every bullet must be exact corpus text (enforced by `mode="strict"` DB lookup)
- Bullet changes stated explicitly as SWAP/CUT/PROMOTE/DEMOTE before generation
- If a change doesn't fit these operations, present it to the user for manual review

**Freeform mode (additional):**
- Rewording to mirror JD language is allowed; combining same-role bullets allowed
- All facts/metrics/company names must trace to base.md
- Integrity audit check: every bullet's metrics, employer, dates, and technologies trace to a corpus source (rewording allowed, factual claims must match)

**Summary exception (all modes):**
- The Summary may be composed fresh using the Identity-First framework
- Must ONLY reference experiences, skills, and themes present in corpus
- No invented specifics

#### Summary Composition (Identity-First)

Structure: **Identity → Evidence → Differentiation**

1. **Identity line** — Open with what the candidate IS, anchored to a specific corpus achievement that maps to the JD's primary need. Not "Growth PM with 12+ years" but "Growth PM who scaled experimentation velocity 250%."
2. **Evidence line** — 1-2 metrics from corpus proving the identity claim.
3. **Differentiation line** — The compound advantage that separates this candidate from others with similar experience.

**Banned phrases:** "12+ years" (or any "X+ years"), "proven track record", "results-driven", "passionate", "deep experience in", "thrives in", "combines"

**Format:** Periods (not em-dashes). Max 3-4 sentences. All facts from base.md. See base.md SUMMARY section for theme-specific examples.

#### Generation Process (Disciplined Mode)

1. Read profile.yaml (includes `earlier_roles`) and base.md
2. Call `assemble_template_data(jd_text=jd_text)` for JD-ranked bullet selection
3. **Compose:** Summary (Identity-First). **Reorder/filter:** Skills for JD.
4. **Review auto-ranked bullets.** State operations per role:
   ```
   ## Bullet Operations
   **ZenBusiness:**
   - SWAP "Owned product roadmap..." FOR "Built new self-serve acquisition funnels..."
   - PROMOTE "Integrated AI capabilities (Velo)..." to position 2
   - CUT "Balanced short-term growth improvements..."
   **Mattermost:** (no changes)
   ```
   Use "(no changes)" shorthand when auto-ranked selection is acceptable.
5. Present changelist + summary + skills for user approval
6. Build `role_bullets` dict with final corpus bullet text
7. Call `generate_resume_programmatic(mode="strict", ...)`
8. **Integrity audit runs automatically in Python.** If it fails, fix and retry. The function will not produce a PDF until all checks pass.

#### Calling the Generator

```python
from jj.google_docs import generate_resume_programmatic

result = generate_resume_programmatic(
    company=company,
    position=position,
    variant="custom",
    mode="strict",             # disciplined mode: DB-validated corpus bullets
    custom_summary=summary,    # Identity-First composed summary
    custom_skills=skills,      # dict[str, list[str]] — display name -> skill list
    role_bullets=bullets,      # dict[str, list[str]] — company -> verbatim corpus bullets
    earlier_roles=earlier,     # list[dict] — from profile.yaml earlier_roles
    max_roles=6,
    max_bullets_per_role=6,
    jd_text=jd_text,
    output_dir=output_dir,
)

# For freeform mode (--freeform):
# mode="optimized" — bullets used verbatim from caller, no DB validation
```

### Step 3b: Score Tailored Resume (BEFORE Document Generation)

**After tailoring content (Step 3) and getting user approval, re-score the tailored resume against the JD** to verify improvement before generating the document. This gates document generation on actual score improvement — no point generating a file if tailoring didn't help.

#### Scoring Process

Using the same categories from Step 2b, score the **tailored** content:

```
## Tailored Resume Score: [Company] [Role]

| Category | Before | After | Delta | Notes |
|----------|--------|-------|-------|-------|
| Summary alignment | X/25 | Y/25 | +Z | [What improved] |
| Skills coverage | X/25 | Y/25 | +Z | [What improved] |
| Bullet relevance | X/35 | Y/35 | +Z | [What improved] |
| Keyword density | X/15 | Y/15 | +Z | [What improved] |
| **Total** | **X/100** | **Y/100** | **+Z** | |
```

#### Minimum Threshold: 85+

The tailored resume must score **85 or higher** to proceed to document generation. If below 85:

1. **Check keyword gaps** — What JD terms are still missing?
2. **Review bullet selection** — Are the most relevant bullets leading?
3. **Revisit summary** — Does it hit the JD's key themes?
4. **Consider different bullets** — Are there better options in corpus?

Iterate and re-score until 85+ is reached. Present the before/after comparison to the user. Only proceed to Step 4 if the score meets the threshold.

#### Tracking

Record both scores for Step 8:
- `rj_before` — Standard resume score
- `rj_after` — Tailored resume score
- `notes` — Include "RJ:X→Y (+Zpts)"

### Step 4: Generate Document

Once the tailored resume score meets 85+, generate the resume document using Google Docs:

```python
from jj.google_docs import generate_resume_programmatic

result = generate_resume_programmatic(
    company=company,
    position=position,
    variant="custom",  # tracking label
    custom_summary=tailored_summary,  # The summary composed in Step 3
    custom_skills={
        "Display Category Name": ["Skill 1", "Skill 2", "Skill 3"],
        # ... reordered/selected skill categories from Step 4
    },
    role_bullets={
        "Company Name": [
            "Bullet text verbatim from corpus...",
            "Second bullet verbatim from corpus...",
        ],
        # ... for each role, ordered by relevance
    },
    max_roles=5,
    max_bullets_per_role=6,
    auto_open=True,
)
```

**What this does:**
1. Copies the Google Docs resume template
2. Replaces all placeholders (summary, skills, role bullets) with tailored content
3. Cleans up any empty sections
4. Bolds skill category names
5. Exports a PDF to `~/Documents/Resumes/`
6. Tracks the resume in the database (resume record + entries + times_used)

**Output:**
- `result.doc_url` — Google Doc URL (editable)
- `result.pdf_path` — PDF path for uploading to ATS
- `result.doc_id` — Google Doc ID

Tell the user both the Google Doc URL and the PDF path.

### Step 5: Draft Custom Question Answers

If the job posting has custom questions (e.g., "Why do you want to work at X?"):

1. **Check the story bank** for relevant STAR+R stories:
   ```python
   from jj.db import get_stories, increment_story_usage

   # Extract key themes/requirements from JD
   jd_themes = [...]  # e.g., ["leadership", "growth", "experimentation"]

   relevant_stories = get_stories(requirement_tags=jd_themes)
   ```

2. Draft an answer for each question (3-4 sentences, ~100-150 words)
3. Use context from:
   - **STAR+R stories from the story bank** (prefer these — they're pre-structured and validated)
   - The job description
   - The user's corpus
   - Company research if needed
4. When using a story from the bank, note which one and increment its usage:
   ```python
   increment_story_usage(story_id)
   ```
5. Present each Q&A for approval. If a story bank story was used, show which one:
   ```
   **Q: Tell us about a time you scaled a process.**
   A: [Answer incorporating STAR+R story #3: "Scaled experimentation velocity at ZenBusiness"]
   ```
6. Allow inline editing: "change X to Y" or "make it shorter"

**Always pause on salary questions** — ask the user what to put.

**For behavioral questions specifically**, present the relevant STAR+R story in full before drafting the answer, so the user can decide which details to include.

### Step 5b: Generate Cover Letter (if applicable)

1. **Check if applicable:**
   - Did the JD analysis (Step 1) indicate the company accepts cover letters?
   - Common ATS support: Greenhouse (yes), Lever (sometimes), Ashby (yes), Workday (usually)
   - Ask user: "This posting accepts a cover letter. Want me to draft one?"
   - If user declines, skip to Step 7.

2. **Match interests to JD themes:**
   ```python
   from jj.db import get_interests_by_tags
   # Use theme tags extracted from JD in Step 1
   matching_interests = get_interests_by_tags(jd_theme_tags)
   ```
   - If matches found, pick the one with lowest `times_used` (freshness/variety)
   - If no matches, skip the interest hook and use a direct company/mission opening

3. **Compose 4 paragraphs:**
   - **P1 (Hook):** If interest match found, open with its `connection` sentence, then bridge to why this company/role specifically excites you. If no match, open with a direct statement about the company's mission or product that demonstrates genuine knowledge.
   - **P2 (Relevance):** Select 2-3 strongest achievements from the resume corpus that map directly to JD requirements. Include metrics. This is the "proof" paragraph.
   - **P3 (Scale/Alignment):** Show you've operated at their scale or in their domain. Connect your experience to their specific challenges. Reference company research.
   - **P4 (Close):** Brief, confident close. Express enthusiasm for discussing further. Keep to 2 sentences max.

   **Content rules (same as resume):**
   - SELECT achievements from corpus, don't invent new ones
   - Metrics must match what's in base.md
   - Keep total length to ~350-450 words (one page)

4. **Present draft for review:**
   Show the full letter. Allow one round of iteration:
   "Want me to adjust the tone, swap any achievements, or change the hook?"

5. **Generate document:**
   ```python
   from jj.google_docs import generate_cover_letter
   result = generate_cover_letter(
       company=company,
       position=position,
       paragraphs=[p1, p2, p3, p4],
       interest_id=matched_interest_id,  # or None
       auto_open=True,
   )
   ```
   Share the Google Doc URL and PDF path with the user.

### Step 6: Complete Application (Manual)

Present the user with everything they need:

```
## Ready to Apply

**Resume:** [path to resume file]
**Cover Letter:** [path to cover letter file] (if generated)
**Custom answers:** [drafted above]

To complete the application:
1. Open: [job_url]
2. Fill standard fields with your profile info
3. Upload the resume from the path above
4. Upload the cover letter (if applicable)
5. Copy the custom answers into the form
6. Review and submit

Let me know when you've submitted so I can update your tracker!
```

### Step 7: Update Application Tracker

After each application is submitted (or skipped), update the tracking database:

```python
import sqlite3
from datetime import datetime
from jj.config import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.execute(
    """INSERT INTO applications (company, position, location, salary_range, ats_type, fit_score, status, job_url, rj_before, rj_after, notes, applied_at, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (company, position, location, salary_range, ats_type, fit_score,
     "applied",  # or "skipped"
     job_url, rj_before, rj_after,
     "RJ:X→Y (+Zpts)",  # append "+CL" if cover letter included
     datetime.now().isoformat(), datetime.now().isoformat())
)
conn.commit()
```

**Database is the single source of truth** — do NOT write to CSV files. The `applications` table in `journal.db` is what the email checker, dashboard, and all other tools query.

**Always update tracking** — even if the user skips an application, log it with status "skipped".
Note in the `notes` field whether a cover letter was included (append "+CL").

---

## Data Files

| File | Purpose |
|------|---------|
| `~/.job-journal/journal.db` | SQLite database — single source of truth for all data |
| `~/.job-journal/corpus.md` | Professional corpus (editable) |
| `~/.job-journal/profile.yaml` | Contact info, links, work authorization |
| `~/.job-journal/config.yaml` | Settings and preferences |

**Note:** Do NOT write to CSV files. All tracking goes to `journal.db` only.

## Profile Data (from profile.yaml)

When filling forms, use these values:
- First name, last name, email, phone, location
- LinkedIn URL
- Work authorization status
- Default answers for common questions

## Error Handling

| Situation | Response |
|-----------|----------|
| URL not accessible | "Couldn't fetch that URL. Is it correct? Try pasting it again." |
| No corpus yet | "No corpus found. Run '/interview' first to build your professional story." |
| User rejects resume draft | Iterate based on feedback |

## Notes

- Always show the user what you're doing at each step
- Never submit without explicit user confirmation
- Keep custom answers concise and genuine — avoid corporate buzzwords
- When in doubt, ask the user
- This is a guided workflow — automation comes in a future phase
