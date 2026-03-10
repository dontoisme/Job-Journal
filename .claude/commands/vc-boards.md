# /vc-boards - VC/Investor Job Board Monitor

Scrape VC/investor portfolio job boards for PM roles across dozens of portfolio companies, score against your corpus, and track as prospects.

## Usage

```
/vc-boards                       # Monitor all active boards due for check
/vc-boards --board "LSVP"        # Scrape a single board
/vc-boards --talent-networks     # List talent network opportunities
/vc-boards --seed                # Initialize/refresh seed data
/vc-boards --dry-run             # Scrape only, no scoring
```

## Arguments

Parse the user's input after `/vc-boards`:
- `--board "Name"` or just a firm name → single-board mode
- `--talent-networks` → show talent network info only
- `--seed` → run seed + report
- `--dry-run` → scrape + title filter only, skip JD scoring
- No args → full monitoring run for all due boards

---

## Phase 1: Setup & Board Selection

### 1a. Check Seed Data

```python
from jj.db import get_investor_boards

boards = get_investor_boards(active_only=True)
if not boards:
    # Auto-seed if no boards exist
    from jj.investor_boards_data import seed_investor_boards
    results = seed_investor_boards()
    print(f"Initialized {results['created']} investor boards.")
    boards = get_investor_boards(active_only=True)
```

If `--seed` flag is set, run seed and report results, then stop.

### 1b. Handle --talent-networks

If `--talent-networks` flag:

```python
from jj.db import get_investor_boards

boards = get_investor_boards(active_only=True)
talent_boards = [b for b in boards if b.get("has_talent_network")]
```

Display a table:

```
## Talent Networks

These firms let you submit your profile for general consideration across their portfolio:

| Firm | Talent Network URL | Notes |
|------|--------------------|-------|
| a16z | talentplace.a16z.com | — |
| Greylock | greylock.com/talent-network/ | — |
| Y Combinator | workatastartup.com | Single application covers all YC companies |
...

Consider submitting your profile to high-priority talent networks.
```

Then stop.

### 1c. Select Boards for Monitoring

```python
from jj.db import get_investor_boards_due_for_check, get_investor_board_by_name

if board_flag:
    # Single-board mode
    board = get_investor_board_by_name(board_flag)
    if not board:
        print(f"Board '{board_flag}' not found.")
        # Show available boards
        return
    due_boards = [board]
else:
    due_boards = get_investor_boards_due_for_check(hours=24)
```

Report:
```
## VC Board Monitor: YYYY-MM-DD

Checking X investor boards for PM roles...
```

If no boards are due:
```
All boards were checked in the last 24 hours. Nothing to do.
Re-run with `--board "Name"` to force-check a specific board.
```

---

## Phase 2: Scrape Boards

### 2a. Scrape Each Board

For each board in `due_boards`:

1. Use **WebFetch** on the `board_url`:
   - Prompt: "Extract all job listings from this investor/VC portfolio job board. For each job return: title, company_name, url (the link to the job posting — make it absolute), location, salary (if visible). Return as a JSON array of objects with keys: title, company_name, url, location, salary. Include ALL listings visible on the page."

2. If WebFetch fails, log a warning and continue to the next board.

3. Get known URLs for delta detection:
   ```python
   from jj.db import get_known_investor_board_job_urls
   known_urls = get_known_investor_board_job_urls(board["id"])
   ```

4. For each extracted job, record it:
   ```python
   from jj.db import record_investor_board_job, find_company_by_name, get_or_create_company

   # Try to link to existing company
   company_id = None
   if job["company_name"]:
       existing = find_company_by_name(job["company_name"], fuzzy=True)
       if existing:
           company_id = existing["id"]

   job_id, is_new = record_investor_board_job(
       board_id=board["id"],
       url=job["url"],
       title=job["title"],
       company_name=job.get("company_name"),
       location=job.get("location"),
       salary=job.get("salary"),
       company_id=company_id,
   )
   ```

5. Mark stale listings:
   ```python
   from jj.db import mark_stale_investor_board_jobs
   current_urls = {job["url"] for job in extracted_jobs}
   stale_count = mark_stale_investor_board_jobs(board["id"], current_urls)
   ```

6. Update search timestamp:
   ```python
   from jj.db import increment_investor_board_search
   increment_investor_board_search(board["id"])
   ```

### 2b. Report Scrape Results

```
### Scrape Complete

| Board | Total | New | Stale | Errors |
|-------|-------|-----|-------|--------|
| LSVP | 42 | 8 | 2 | 0 |
| a16z | 156 | 23 | 5 | 0 |
...

Total new listings: X across Y boards
```

If no new listings found, skip to Phase 5 (summary).

---

## Phase 3: Title Pre-Filter

### 3a. Filter to PM Roles

Investor boards list hundreds of roles across all functions. Aggressively filter to PM-relevant titles:

```python
from jj.db import score_title_fit

for listing in new_listings:
    result = score_title_fit(title=listing["title"], location=listing.get("location"))
    listing["title_score"] = result["total"]
    listing["title_pass"] = result["pass"]  # threshold: 50+
```

### 3b. Report Filter Results

```
### Title Pre-Filter

| # | Score | Pass | Board | Company | Title | Location |
|---|-------|------|-------|---------|-------|----------|
...

Passed: X of Y new listings (Z filtered out)
```

Only listings with `title_pass = True` proceed to scoring. This eliminates engineering, sales, marketing, ops, and design roles.

If `--dry-run`, stop here and show results.

---

## Phase 4: Score New Jobs

For each listing that passed the title pre-filter:

### 4a. Fetch Full JD

Use **WebFetch** on each job URL:
- Prompt: "Extract the full job description. Include: job title, company name, required skills, years of experience, responsibilities, qualifications, salary/compensation if listed, location/remote policy. Return all text content."

If WebFetch fails, log and skip.

### 4b. Load Corpus

```python
from jj.config import CORPUS_PATH
corpus = CORPUS_PATH.read_text()
```

If corpus doesn't exist: "No corpus found. Run `/interview` first."

### 4c. Score Each Job

Score (0-100) using the 4-category rubric:

| Category | Weight | What to Evaluate |
|----------|--------|------------------|
| **Skills Match** | 35 pts | JD required skills vs corpus skills |
| **Experience Level** | 25 pts | Seniority alignment (title, years) |
| **Domain Fit** | 25 pts | Domain tag overlap (AI/ML, growth/PLG, health-tech, platform, fintech) |
| **Location/Remote** | 15 pts | Location compatibility with profile preferences |

Assign verdict:

| Score | Verdict |
|-------|---------|
| 80-100 | Strong Fit |
| 65-79 | Good Fit |
| 50-64 | Moderate Fit |
| <50 | Stretch |

### 4d. Deduplicate Before Inserting

```python
from jj.db import find_duplicate_application

existing = find_duplicate_application(company=company_name, position=title, job_url=url)
if existing:
    # Skip — already tracked
    continue
```

### 4e. Create Company + Application Records

For new companies discovered via VC boards, create company records:

```python
from jj.db import get_or_create_company

if not company_id and company_name:
    company_id = get_or_create_company(
        company_name,
        careers_url=job_url,
    )
```

For jobs scoring 50+, create application records:

```python
from jj.db import create_application

app_id = create_application(
    company=company_name,
    position=title,
    job_url=url,
    location=location,
    salary_range=salary,
    fit_score=score,
    status="prospect",
    notes=f"[VC Board: {board_name}] Fit: {score}% ({verdict}). Skills: {skills}/35, Exp: {exp}/25, Domain: {domain}/25, Location: {loc}/15.",
    company_id=company_id,
)
```

---

## Phase 5: Summary Report

### 5a. Talent Network Reminders

If any checked boards have talent networks, display:

```
### Talent Networks to Consider

The following boards have talent networks where you can submit your profile:
- **Greylock**: greylock.com/talent-network/
- **General Catalyst**: jobs.generalcatalyst.com/talent-network
- **Y Combinator**: workatastartup.com (single app for all YC companies)

Submit your profile to expand your reach beyond specific listings.
```

### 5b. Results Summary

Use this **default table view** for all `/vc-boards` results. This is the standard output format — always include VC Board, RJ Before/After scores, Google Doc link, and Apply link.

```
## VC Board Monitor Summary

### Boards Checked: X
| Board | Jobs Found | New | Passed Filter | Scored |
|-------|------------|-----|---------------|--------|
...

### Scored Prospects (default table view)

| # | Company | Role | VC Board | RJ Before | RJ After | Delta | Google Doc | Apply |
|---|---------|------|----------|-----------|----------|-------|-----------|-------|
| 1 | **Acme AI** | Sr PM, Platform | LSVP | 50 | **92** | +42 | [Edit](doc_url) | [Apply](job_url) |
| 2 | **HealthCo** | PM, Growth | a16z | 66 | **88** | +22 | [Edit](doc_url) | [Apply](job_url) |
...

- **RJ Before**: Resume-JD match score using standard/default resume (0-100)
- **RJ After**: Resume-JD match score using targeted resume (0-100)
- **Delta**: Improvement from tailoring
- Sort by delta descending (biggest tailoring wins first)
- Google Doc and Apply links are required columns

Next steps:
- Review Google Docs and tweak before submitting
- Let me know as you apply — I'll update status + TWC tracking
- Re-run tomorrow: `/vc-boards`
```
