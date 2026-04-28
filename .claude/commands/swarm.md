# /swarm - Daily Job Monitoring with Delta Detection

Parallel per-company agents scrape career pages, detect NEW listings (delta between yesterday and today), auto-score, and generate resumes for 65+ matches -- no approval gates for the monitoring flow.

## Usage

```
/swarm                    # Run daily monitoring for all due companies
/swarm --company "Figma"  # Monitor a single company
/swarm --discover         # Find new target companies to add
/swarm --dry-run          # Scrape + score only, no resume generation
```

## Arguments

Parse the user's input after `/swarm`:
- `--company "Name"` or just a company name → single-company mode
- `--discover` → discovery mode (Phase 6)
- `--dry-run` → skip Phase 4 (resume generation)
- No args → full monitoring run for all due companies

---

## Phase 1: Company Selection

### 1a. Load Due Companies

Get target companies not checked in the last 24 hours:

```python
from jj.db import get_companies_due_for_check, get_target_companies

due_companies = get_companies_due_for_check(hours=24)
```

If `--company` flag is set, filter to just that company (use `get_target_companies()` and filter by name match).

### 1b. Report

```
## Swarm Monitoring: YYYY-MM-DD

Monitoring X companies for new listings (Y skipped — checked recently)...
```

If no companies are due:
```
All target companies were checked in the last 24 hours. Nothing to do.
Re-run with `--company "Name"` to force-check a specific company.
```

---

## Phase 2: Parallel Scrape + Delta Detection

### 2a. Batch Companies

Split due companies into batches of 3-5 for parallel execution. Each batch will be processed by a separate Task subagent.

### 2b. Launch Parallel Subagents

For each batch, launch a **Task** subagent (subagent_type=`general-purpose`) with:

**Subagent prompt template:**

```
You are a career page scraper agent. For each company below, scrape the career page, extract job listings, and perform delta detection.

Companies to check:
[List of companies with id, name, careers_url, ats_type]

For EACH company:

1. Use WebFetch on the careers_url with prompt: "Extract all job listings from this career page. For each job return: title, URL, location, salary (if visible). Return as a JSON array of objects with keys: title, url, location, salary. Only include product management, product, program management, or strategy roles. Exclude engineering-only, design-only, or sales-only roles unless the title contains 'product'."

2. If WebFetch fails, log the error and move to the next company.

3. For delta detection, I'll provide the set of previously known URLs for each company. Compare:
   - URLs in current scrape NOT in known set → NEW listings
   - URLs in known set NOT in current scrape → STALE (removed)

4. For each listing found, call:
   ```python
   from jj.db import record_job_listing, increment_search_count

   listing_id, is_new = record_job_listing(
       company_id=company["id"],
       url=job_url,
       title=job_title,
       location=job_location,
       salary=job_salary,
       ats_type=company.get("ats_type") or detect_ats_type(job_url),
   )
   ```

5. Mark stale listings:
   ```python
   from jj.db import mark_stale_listings
   stale_count = mark_stale_listings(company["id"], set_of_current_urls)
   ```

6. Update search timestamp:
   ```python
   from jj.db import increment_search_count
   increment_search_count(company["id"])
   ```

Return a structured summary for each company:
- company_name, company_id
- total_listings_found (count)
- new_listings: [{title, url, location, salary}]
- stale_count
- errors (if any)
```

Also pass the known URLs for each company (fetched before launching subagents):

```python
from jj.db import get_known_listing_urls

for company in batch:
    known_urls = get_known_listing_urls(company["id"])
    # Include in subagent prompt
```

### 2c. Collect Results

Wait for all subagents to return. Merge results into a single list of new listings across all companies.

Report progress:
```
### Scrape Complete

- Companies checked: X
- Career pages failed: Y
- New listings discovered: Z
- Listings gone (removed): W
- Already tracked: V
```

If no new listings found, skip to Phase 5 (summary).

### 2d. Title Pre-Filter

Before fetching full JDs (expensive), run the title+location pre-filter on all new listings:

```python
from jj.db import score_title_fit

for listing in new_listings:
    result = score_title_fit(title=listing["title"], location=listing["location"])
    listing["title_score"] = result["total"]
    listing["title_pass"] = result["pass"]  # threshold: 50+
```

Report the filter results:
```
### Title Pre-Filter

| # | Score | Pass | Company | Title | Location | Seniority | Role Type | Location Fit |
|---|-------|------|---------|-------|----------|-----------|-----------|-------------|
...

Passed: X of Y new listings (Z filtered out)
Filtered out: [list of company - title that failed]
```

Only listings with `title_pass = True` (score >= 50) proceed to Phase 3 scoring. This avoids fetching JDs for international roles, product marketing, data analyst roles, and other poor fits.

---

## Phase 3: Score New Listings

For each **new** listing that **passed the title pre-filter** in Phase 2d:

### 3a. Fetch Full JD

Use **WebFetch** to get the full job description from each listing URL:
- Prompt: "Extract the full job description. Include: job title, company name, required skills, years of experience, responsibilities, qualifications, salary/compensation if listed, location/remote policy. Return all text content."

If WebFetch fails, log and skip (score = 0, verdict = "Unable to fetch").

### 3b. Load Corpus

```python
from jj.config import CORPUS_PATH
corpus = CORPUS_PATH.read_text()
```

If corpus doesn't exist, stop: "No corpus found. Run `/interview` first to build your professional story."

### 3c. Score Each Job

Score (0-100) using the 4-category rubric:

| Category | Weight | What to Evaluate |
|----------|--------|------------------|
| **Skills Match** | 35 pts | JD required skills vs corpus skills |
| **Experience Level** | 25 pts | Seniority alignment (title, years) |
| **Domain Fit** | 25 pts | Domain tag overlap (AI, growth, health-tech, platform, consumer) |
| **Location/Remote** | 15 pts | Location compatibility with profile preferences |

Assign verdict:

| Score | Verdict |
|-------|---------|
| 80-100 | Strong Fit |
| 65-79 | Good Fit |
| 50-64 | Moderate Fit |
| <50 | Stretch |

### 3d. Deduplicate Before Inserting

Before creating a new application, check for existing duplicates:

```python
from jj.db import find_duplicate_application

existing = find_duplicate_application(company=company_name, position=title, job_url=url)
if existing:
    # Skip — already tracked as app #{existing['id']} ({existing['status']}, fit: {existing['fit_score']}%)
    continue
```

### 3e. Insert Prospects

For each scored job (that passed dedup), create an application record and link it to the listing:

```python
from jj.db import create_application

app_id = create_application(
    company=company_name,
    position=title,
    job_url=url,
    location=location,
    salary_range=salary,
    ats_type=ats_type,
    fit_score=score,
    status="prospect",
    notes=f"[Swarm] Fit: {score}% ({verdict}). Skills: {skills}/35, Exp: {exp}/25, Domain: {domain}/25, Location: {loc}/15.",
    company_id=company_id,
)
```

Update the job_listings record to link the application:

```python
from jj.config import DB_PATH
import sqlite3

conn = sqlite3.connect(DB_PATH)
conn.execute(
    "UPDATE job_listings SET application_id = ?, scored_at = CURRENT_TIMESTAMP WHERE id = ?",
    (app_id, listing_id)
)
conn.commit()
conn.close()
```

### 3f. Report Scores

```
### Scoring Complete

| # | Score | Verdict | Company | Role | Location |
|---|-------|---------|---------|------|----------|
| 1 | 85% | Strong Fit | Figma | Sr PM, Growth | Remote |
| 2 | 72% | Good Fit | Stripe | PM, Dev Tools | SF/Remote |
...

Strong Fit (80+): X
Good Fit (65-79): Y
Moderate (50-64): Z
Stretch (<50): W
```

If `--dry-run`, skip to Phase 5.

---

## Phase 4: Auto-Generate Resumes (65+ threshold)

**No approval gate.** For each new listing scoring **65 or above** (Good Fit / Strong Fit), automatically generate a tailored resume.

### 4a. Select Resume Variant

Read `~/.job-journal/config.yaml` for variant definitions. Match JD keywords:

| Variant | Match Keywords |
|---------|---------------|
| growth | PLG, experimentation, activation, retention, conversion, funnel |
| ai-agentic | AI, ML, LLM, agents, orchestration, machine learning |
| health-tech | healthcare, EHR, HIPAA, clinical, patient |
| consumer | B2C, marketplace, e-commerce, consumer |
| general | (fallback if no strong keyword match) |

### 4b. Tailor Content

Following the same process as `/apply` Step 3:

1. Read the corpus from `~/.job-journal/corpus.md`
2. **SELECT, don't COMPOSE** -- choose existing bullets VERBATIM from corpus
3. Reorder bullets to lead with JD-relevant content at each role
4. Select skill categories matching JD emphasis
5. Compose a targeted summary paragraph using the Identity-First framework (Identity → Evidence → Differentiation). The ONLY freshly written content; must reference only corpus experiences/skills. Never use "12+ years," "proven track record," or category-label openings. See base.md SUMMARY section for structure and examples.

**Content Integrity Rules (CRITICAL):**
- Do NOT paraphrase, combine, merge, or rewrite bullets
- Do NOT add details not explicitly present in the source
- When in doubt, OMIT -- never guess or infer

### 4c. Score Before Generating

Score the tailored content against the JD:

| Category | Points | What to Evaluate |
|----------|--------|------------------|
| Summary alignment | 25 | Does tailored summary emphasize JD's key themes? |
| Skills coverage | 25 | Are JD's top 5 required skills listed prominently? |
| Bullet relevance | 35 | Do lead bullets at recent roles match JD priorities? |
| Keyword density | 15 | Key terms from JD present throughout resume? |

Record `rj_before` (standard resume) and `rj_after` (tailored). Tailored must reach **85+** before generating. If below, iterate on bullet selection and summary.

### 4d. Generate Document

```python
from jj.google_docs import generate_resume_programmatic

result = generate_resume_programmatic(
    company=company_name,
    position=title,
    variant=best_variant,
    custom_summary=tailored_summary,
    custom_skills=prioritized_skills,
    role_bullets=reordered_bullets,
    max_roles=5,
    max_bullets_per_role=6,
    auto_open=False,
    keep_google_doc=True,
)
```

### 4e. Validate

```python
from jj.resume_gen import validate_resume_content

is_valid, drift_score, results = validate_resume_content(
    bullets=all_bullet_texts,
    fail_fast=False,
)
```

### 4f. Update Records

```python
from jj.db import update_application, validate_resume

update_application(
    app_id=application_id,
    resume_id=result.resume_id,
    rj_before=rj_before_score,
    rj_after=rj_after_score,
    notes=f"[Swarm] RJ:{rj_before}→{rj_after} (+{rj_after - rj_before}pts), variant={best_variant}",
)

validate_resume(
    resume_id=result.resume_id,
    is_valid=is_valid,
    drift_score=drift_score,
)
```

If validation fails, **BLOCK** the resume -- do NOT mark as ready:

```
### FABRICATION ALERT: [Company] - [Role]
- Invalid bullet: "[text]"
- Closest corpus match: "[text]"
- Drift score: X
- Action: BLOCKED -- resume requires manual review
```

---

## Phase 5: Summary Report

### 5a. Present Results

```
## Swarm Report: YYYY-MM-DD

### Monitoring
- Companies checked: X (Y skipped — checked recently)
- Career pages failed: Z (JS-rendered, 404, etc.)

### New Listings Discovered
| Company | Title | Location | Score | Verdict | Resume |
|---------|-------|----------|-------|---------|--------|
| Figma | Sr PM, Growth | Remote | 78% | Good Fit | Generated |
| Stripe | PM, Billing | SF | 62% | Moderate | Skipped |

### Delta Summary
- New listings found: X
- Listings gone (removed): Y
- Already tracked: Z

### Resumes Generated (65+ auto-threshold)
- Generated: X
- Passed validation: Y
- Blocked (fabrication): Z

### Next Steps
- `/apply <url>` for any generated resume to complete the application
- `/score <url>` to manually score a moderate-fit job
- `/swarm --discover` to find new companies to track
- `/swarm` again tomorrow for the next delta check
```

### 5b. Append to Log

Append the full report to `pipeline-log.md` for history.

---

## Phase 6: Discovery Mode (`--discover`)

Only runs when invoked with `--discover`. This is the ONE phase that requires user approval.

### 6a. Search for New Companies

Use **WebSearch** to find companies hiring PM roles in target domains:

```
Search queries:
- "product manager growth remote 2026 hiring"
- "product manager AI developer tools hiring 2026"
- "product manager health-tech Austin hiring 2026"
- "senior product manager startup hiring remote 2026"
```

### 6b. Cross-Reference

Check each discovered company against the existing `companies` table:

```python
from jj.db import get_all_companies

existing = get_all_companies()
existing_names = {c["name"].lower() for c in existing}
```

Filter out companies already tracked.

### 6c. Detect Career Pages

For each genuinely new company:
1. WebSearch for "[company] careers page"
2. WebFetch the result to verify it's a real careers page
3. Detect ATS type from the URL:
   ```python
   from jj.db import detect_ats_type
   ats_type = detect_ats_type(careers_url)
   ```

### 6d. Present for Approval

**This is the one phase that requires user approval.**

```
## New Companies Discovered

| # | Company | Industry | Careers URL | ATS | PM Roles Visible |
|---|---------|----------|-------------|-----|------------------|
| 1 | Acme Corp | AI/ML | https://acme.com/careers | greenhouse | 3 |
| 2 | BetaCo | Health-tech | https://betaco.com/jobs | lever | 1 |

Add any of these as targets? (Give numbers, "all", or "none")
```

### 6e. Insert Approved Companies

For user-approved companies, insert directly:

```python
from jj.config import DB_PATH
import sqlite3

conn = sqlite3.connect(DB_PATH)
conn.execute("""
    INSERT INTO companies (name, name_normalized, careers_url, ats_type, industry, is_target, target_priority)
    VALUES (?, ?, ?, ?, ?, 1, 0)
""", (name, name.lower().strip(), careers_url, ats_type, industry))
conn.commit()
conn.close()
```

Report: "Added X new target companies. They'll be included in the next `/swarm` run."

---

## Error Handling

| Situation | Response |
|-----------|----------|
| Career page unreachable | Log warning, skip company, continue |
| Job URL returns 404 | Skip that listing, continue |
| No corpus found | Stop: "Run `/interview` first" |
| WebFetch fails on JD | Score as 0, skip resume generation |
| Resume generation fails | Log error, continue to next job |
| Validation finds fabrication | Block resume, alert user, continue |
| No target companies found | Stop: "No target companies configured. Add companies first." |
| All companies checked recently | Report "Nothing to do" and suggest `--company` flag |
| No new listings found | Report "0 new listings" and show delta summary only |
| Rate limit / too many WebFetch | Reduce batch size, add delays between requests |

## Key Differences from /pipeline

| Aspect | /pipeline | /swarm |
|--------|-----------|--------|
| Execution | Sequential, single-threaded | Parallel Task subagents |
| Delta detection | None (full scrape each time) | `job_listings` table tracks seen URLs |
| Approval gates | 2 (after scrape, after score) | 0 for monitoring, 1 for discovery |
| Resume threshold | User selects from 70+ | Auto-generate at 65+ |
| Memory | `scraped.json`/`scored.json` overwritten | `job_listings` table persists |
| Frequency | Ad-hoc | Designed for daily runs |

## Notes

- **Parallel by design** -- use Task subagents for scraping batches, not sequential WebFetch calls
- **Delta detection is the core value** -- the `job_listings` table makes re-runs fast (only process genuinely new listings)
- **65+ threshold is deliberate** -- lower than /pipeline's user-selected 70+ to catch more Good Fit opportunities in automated mode
- **Content integrity is non-negotiable** -- Phase 4 validation runs on every generated resume
- **Database writes use existing functions** -- always use `create_application()`, `update_application()`, `record_job_listing()` rather than raw SQL for applications and listings
- **Discovery is the exception** -- it's the only phase that pauses for user approval (adding new companies to track)
- **One swarm run per session** -- don't loop. If user wants to re-run, they invoke `/swarm` again
- **Respect rate limits** -- batch companies 3-5 per subagent to avoid overwhelming WebFetch
