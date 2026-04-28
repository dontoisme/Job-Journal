# /apply - Job Application Assistant

Guide users through job applications with fit assessment and resume tailoring.

## Usage

```
/apply <job_url>
/apply https://job-boards.greenhouse.io/company/jobs/123
```

## Workflow

When the user invokes `/apply` with a job URL, follow these steps:

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
| **80-100%** | Use standard resume as-is | Strong alignment, tailoring adds minimal value |
| **60-79%** | Quick tailor | Summary rewrite + skill reorder only |
| **<60%** | Full tailored resume | Significant gaps, need bullet selection + full optimization |

### Step 3: Suggest Resume Variant

Based on the JD analysis, suggest which resume variant to use:

| Variant | When to Suggest |
|---------|-----------------|
| growth | PLG, experimentation, A/B testing, activation, retention, funnel optimization |
| ai-agentic | AI, multi-agent, LLM, orchestration, automation, autonomous systems |
| health-tech | Healthcare, EHR, HIPAA, telehealth, clinical, patient experience |
| general | Balanced PM roles, strategy, roadmap, cross-functional leadership |
| consumer | B2C, DTC, marketplace, e-commerce, consumer experience |

Present your suggestion with reasoning. Ask the user to confirm or override.

### Step 4: Generate Tailored Resume

#### Content Integrity Rules (CRITICAL)

**SELECT, don't COMPOSE:**
- Choose existing bullets from corpus.md VERBATIM
- Do NOT paraphrase, combine, merge, or rewrite bullets
- Do NOT add details not explicitly present in the source:
  - No client/company names unless stated in corpus
  - No metrics/numbers unless stated in corpus
  - No technologies unless stated in corpus
- When in doubt, OMIT — never guess or infer

**Only exception — Summary paragraph:**
- The Summary may be composed fresh to match the JD using the Identity-First framework
- Structure: Identity → Evidence → Differentiation
- Banned: "12+ years," "proven track record," "results-driven," "passionate," "deep experience in"
- Must ONLY reference experiences, skills, and themes present in corpus
- No invented specifics

**If corpus lacks sufficient bullets for a role:**
- Use what exists; do not fabricate alternatives
- Note to user: "Limited bullet options for [role] — consider adding more via /interview"

#### Generation Process

1. Read the profile data from `~/.job-journal/profile.yaml`
2. Read the corpus from `~/.job-journal/corpus.md`
3. Generate a tailored resume by:
   - Composing an Identity-First summary paragraph matched to the JD (3-4 sentences)
   - Selecting and reordering Skills categories to match JD keywords
   - Selecting the most relevant bullets for each role based on tags
   - Reordering Experience bullets to lead with the most relevant
4. Present key changes to the user:
   - "Summary: Emphasized X, Y, Z"
   - "Skills: Led with [category], added [keywords]"
   - "Experience: Prioritized bullets about [theme]"
5. **Source Verification** — Show which bullets were selected
6. Wait for user approval. If they request changes, iterate.

### Step 5: Generate Document

Once approved, generate the resume document:

```bash
# Create temp markdown file with tailored content
# Then convert to docx using reference template

pandoc /tmp/resume-draft.md \
  --reference-doc="$HOME/.job-journal/templates/reference.docx" \
  -o "$OUTPUT_PATH"
```

Where `$OUTPUT_PATH` follows the pattern from config.yaml.

Tell the user where the file was saved.

### Step 6: Draft Custom Question Answers

If the job posting has custom questions (e.g., "Why do you want to work at X?"):

1. Draft an answer for each question (3-4 sentences, ~100-150 words)
2. Use context from:
   - The job description
   - The user's corpus
   - Company research if needed
3. Present each Q&A for approval
4. Allow inline editing: "change X to Y" or "make it shorter"

**Always pause on salary questions** — ask the user what to put.

### Step 7: Complete Application (Manual)

Present the user with everything they need:

```
## Ready to Apply

**Resume:** [path to file]
**Custom answers:** [drafted above]

To complete the application:
1. Open: [job_url]
2. Fill standard fields with your profile info
3. Upload the resume from the path above
4. Copy the custom answers into the form
5. Review and submit

Let me know when you've submitted so I can update your tracker!
```

### Step 8: Update Application Tracker

After each application is submitted (or skipped), update the tracking database and CSV:

```python
from jj.db import create_application

create_application(
    company="COMPANY",
    position="POSITION",
    location="LOCATION",
    salary_range="SALARY",
    ats_type="ATS_TYPE",
    fit_score=FIT_SCORE,
    status="applied",  # or "skipped"
    job_url="URL",
    rj_before=RJ_BEFORE,
    rj_after=RJ_AFTER,
    notes="RJ:X→Y (+Zpts)"
)
```

Also append to `~/.job-journal/applications.csv` for compatibility:

**CSV Columns:**
| Column | Description |
|--------|-------------|
| date_applied | YYYY-MM-DD format |
| company | Company name |
| position | Job title |
| location | Location or "Remote" |
| salary_range | Salary range from JD or requested |
| ats_type | Greenhouse, Lever, Ashby, Workday, etc. |
| fit_score | Match percentage from Step 2 |
| status | applied, skipped, interviewing, rejected, offer |
| resume_variant | growth, ai-agentic, health-tech, general, consumer, standard |
| job_url | Original job posting URL |
| notes | Brief notes — e.g., "RJ:63→87 (+24pts)" |
| rj_before | Resume-JD score BEFORE tailoring |
| rj_after | Resume-JD score AFTER tailoring |

**Always update tracking** — even if the user skips an application, log it with status "skipped".

---

## Data Files

| File | Purpose |
|------|---------|
| `~/.job-journal/journal.db` | SQLite database with all data |
| `~/.job-journal/applications.csv` | Application tracker (CSV export) |
| `~/.job-journal/corpus.md` | Professional corpus (editable) |
| `~/.job-journal/profile.yaml` | Contact info, links, work authorization |
| `~/.job-journal/config.yaml` | Settings and preferences |

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
