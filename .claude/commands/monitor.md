# /monitor - Headless Job Monitor (Automated Discovery + Slack Notification)

Designed for non-interactive, scheduled execution via `claude -p`. Scrapes target company career pages and VC boards, detects new listings (delta detection), runs title pre-filter, and sends Slack notification for new finds. NO resume generation, NO full JD scoring, NO user prompts.

## Critical: Headless Mode Rules

- Do NOT prompt the user for input or approval at any point
- Do NOT generate resumes or score full JDs
- Do NOT use Task subagents (keep the session short and simple)
- Do NOT run discovery mode (that requires user approval)
- Process companies sequentially (avoid parallel complexity in headless mode)
- If any step fails, log the error and continue to the next item
- Complete all phases, then exit

---

## Phase 1: Initialize

### 1a. Initialize Database

```bash
python3 -c "
from jj.db import init_database, create_monitor_run
init_database()
run_id = create_monitor_run('full')
print(f'MONITOR_RUN_ID={run_id}')
"
```

Capture the `MONITOR_RUN_ID` for later.

### 1b. Load Target Companies Due for Check

```bash
python3 -c "
import json
from jj.db import get_companies_due_for_check
companies = get_companies_due_for_check(hours=12)
print(json.dumps([{'id': c['id'], 'name': c['name'], 'careers_url': c['careers_url'], 'ats_type': c.get('ats_type')} for c in companies]))
"
```

### 1c. Load Investor Boards Due for Check

```bash
python3 -c "
import json
from jj.db import get_investor_boards_due_for_check
boards = get_investor_boards_due_for_check(hours=12)
print(json.dumps([{'id': b['id'], 'name': b['name'], 'board_url': b['board_url']} for b in boards]))
"
```

If both lists are empty, complete the monitor run and exit:
```bash
python3 -c "
from jj.db import complete_monitor_run
complete_monitor_run(MONITOR_RUN_ID, summary={'message': 'Nothing due for check'})
"
```

---

## Phase 2: Scrape Company Career Pages

For each company with a `careers_url`:

### 2a. Get Known URLs

```bash
python3 -c "
import json
from jj.db import get_known_listing_urls
urls = list(get_known_listing_urls(COMPANY_ID))
print(json.dumps(urls))
"
```

### 2b. Fetch Career Page

Use **WebFetch** on the company's `careers_url`:
- Prompt: "Extract all job listings from this career page. For each job return: title, url (absolute URL to the job posting), location, salary (if visible). Return as a JSON array of objects with keys: title, url, location, salary. Only include product management, product, program management, growth, or strategy roles. Exclude engineering-only, design-only, or sales-only roles unless the title contains 'product'."

If WebFetch fails, log the error and continue to the next company.

### 2c. Delta Detection

Compare extracted URLs against known URLs:
- URLs in current scrape NOT in known set = **NEW** listings
- Track the count of new vs already-known listings

### 2d. Record Listings

For each extracted listing, record it and track whether it's new:

```bash
python3 -c "
from jj.db import record_job_listing, increment_search_count, mark_stale_listings, detect_ats_type

# Record each listing
listing_id, is_new = record_job_listing(
    company_id=COMPANY_ID,
    url='JOB_URL',
    title='JOB_TITLE',
    location='JOB_LOCATION',
    salary='JOB_SALARY',
    ats_type=detect_ats_type('JOB_URL') or 'COMPANY_ATS_TYPE',
)
print(f'listing_id={listing_id}, is_new={is_new}')

# Mark stale (URLs we previously knew but aren't on the page anymore)
current_urls = {SET_OF_CURRENT_URLS}
stale_count = mark_stale_listings(COMPANY_ID, current_urls)

# Update search timestamp
increment_search_count(COMPANY_ID)
"
```

### 2e. Title Pre-Filter (New Listings Only)

For each NEW listing, run the title pre-filter:

```bash
python3 -c "
import json
from jj.db import score_title_fit
result = score_title_fit(title='JOB_TITLE', location='JOB_LOCATION')
print(json.dumps(result))
"
```

Only listings with `result['pass'] == True` (score >= 50) are included in the notification.

Collect all passing new listings into a list with format:
```json
{"title": "...", "company": "...", "location": "...", "score": 72, "url": "..."}
```

---

## Phase 3: Scrape VC Boards

For each investor board with a `board_url`:

### 3a. Get Known URLs

```bash
python3 -c "
import json
from jj.db import get_known_investor_board_job_urls
urls = list(get_known_investor_board_job_urls(BOARD_ID))
print(json.dumps(urls))
"
```

### 3b. Fetch Board Page

Use **WebFetch** on the board's `board_url`:
- Prompt: "Extract all job listings from this investor/VC portfolio job board. For each job return: title, company_name (the portfolio company hiring), url (absolute URL to the job posting), location, salary (if visible). Return as a JSON array of objects with keys: title, company_name, url, location, salary. Include ALL listings visible on the page."

If WebFetch fails, log and continue.

### 3c. Delta Detection + Recording

Same pattern as Phase 2: record each job, detect new vs known, mark stale.

```bash
python3 -c "
from jj.db import record_investor_board_job, increment_investor_board_search, mark_stale_investor_board_jobs

# Record each job
job_id, is_new = record_investor_board_job(
    board_id=BOARD_ID,
    url='JOB_URL',
    title='JOB_TITLE',
    company_name='COMPANY_NAME',
    location='JOB_LOCATION',
    salary='JOB_SALARY',
)

# Mark stale
current_urls = {SET_OF_CURRENT_URLS}
stale_count = mark_stale_investor_board_jobs(BOARD_ID, current_urls)

# Update search timestamp
increment_investor_board_search(BOARD_ID)
"
```

### 3d. Title Pre-Filter (New Listings Only)

Same as Phase 2e — run `score_title_fit()` on new listings, collect passing ones.

For VC board listings, include `company_name` in the collected data:
```json
{"title": "...", "company": "CompanyName (via BoardName)", "location": "...", "score": 65, "url": "..."}
```

---

## Phase 4: Notify

### 4a. Collect Results

Merge all new, title-filtered listings from Phase 2 and Phase 3 into a single list.
Sort by score descending.

### 4b. Write Results File

Write the results to a JSON file for the CLI notification command:

```bash
python3 -c "
import json
from pathlib import Path

results = {
    'new_jobs': [LIST_OF_NEW_JOBS],
    'summary': {
        'companies_checked': NUM_COMPANIES,
        'boards_checked': NUM_BOARDS,
        'timestamp': 'HH:MM',
    }
}

output = Path.home() / '.job-journal' / 'logs' / 'monitor-latest.json'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(results, indent=2))
print(f'Wrote {len(results[\"new_jobs\"])} jobs to {output}')
"
```

### 4c. Send Slack Notification

If any new listings were found (after title filter):

```bash
jj notify slack --file ~/.job-journal/logs/monitor-latest.json
```

If no new listings found, still send a brief "all clear" message:

```bash
jj notify slack --message "Job Monitor: No new listings found. Checked X companies + Y VC boards."
```

### 4d. Complete Monitor Run

```bash
python3 -c "
from jj.db import complete_monitor_run

complete_monitor_run(
    run_id=MONITOR_RUN_ID,
    companies_checked=NUM_COMPANIES,
    boards_checked=NUM_BOARDS,
    new_listings_found=NUM_NEW_LISTINGS,
    notification_sent=True,
    summary={
        'new_jobs': NUM_NEW_LISTINGS,
        'companies': NUM_COMPANIES,
        'boards': NUM_BOARDS,
    },
)
"
```

---

## Error Handling

| Situation | Response |
|-----------|----------|
| WebFetch fails on career page | Log warning, skip company, continue |
| WebFetch returns no listings | Record 0 listings, continue |
| Python script fails | Log error, continue to next item |
| No target companies or boards | Complete run with 0 counts, exit |
| Slack notification fails | Log error, still complete the run |
| Database error | Log error, continue if possible |

## Notes

- This skill is optimized for SPEED and RELIABILITY in headless mode
- No resume generation — that's for interactive `/swarm` and `/apply`
- No full JD scoring — title pre-filter is sufficient for notification
- Sequential processing (not parallel) to keep the session simple
- Each run should complete in 2-5 minutes depending on the number of targets
- Results are persisted in `monitor-latest.json` for inspection
- Run history tracked in `monitor_runs` table
