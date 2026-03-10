# /monitor - Headless Job Monitor (Automated Discovery + Slack Notification)

Autonomous job engine that runs headlessly via LaunchAgent. Scrapes company career pages and VC boards, syncs email status updates, creates prospect records, scores JDs against corpus, generates resumes for strong fits, and sends enriched Slack notifications.

## Critical: Headless Mode Rules

- Do NOT prompt the user for input or approval at any point
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

## Phase 1.5: Email Sync

Sync application emails to detect status changes (rejections, interviews, offers). This uses existing infrastructure and runs before scraping.

### 1.5a. Check Gmail Token

```bash
python3 -c "
from pathlib import Path
token = Path.home() / '.job-journal' / 'gmail_token.json'
print(f'TOKEN_EXISTS={token.exists()}')
"
```

If `TOKEN_EXISTS=False`, skip email sync entirely and log: "Email sync skipped: no Gmail token". Continue to Phase 2.

### 1.5b. Sync Emails

```bash
python3 -c "
import json
from jj.db import get_applications
from jj.gmail_checker import sync_application_emails

# Get all non-terminal applications
apps = get_applications()
active = [a for a in apps if a.get('status') not in ('rejected', 'withdrawn', 'offer', 'skipped')]
result = sync_application_emails(active, verbose=False)
print(json.dumps({
    'applications_checked': result.get('applications_checked', 0),
    'confirmations_found': result.get('confirmations_found', 0),
    'resolutions_found': result.get('resolutions_found', 0),
}))
"
```

Wrap the entire 1.5b step in try/except. If it fails (token expired, network error, etc.), log the error and continue to Phase 2. Email sync must NEVER block the monitor.

Capture the result as `EMAIL_SYNC_RESULT` for inclusion in the Slack notification later.

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
{"title": "...", "company": "...", "location": "...", "score": 72, "url": "...", "score_type": "Title Fit"}
```

### 2f. Auto-Prospect Creation (New Listings Passing Title Filter)

For each new listing that passed the title filter (score >= 50):

1. Check for duplicates:
```bash
python3 -c "
import json
from jj.db import find_duplicate_application
dup = find_duplicate_application(company='COMPANY_NAME', position='JOB_TITLE', job_url='JOB_URL')
print(json.dumps({'duplicate': True, 'id': dup['id']} if dup else {'duplicate': False}))
"
```

**If a duplicate is found, REMOVE this listing from the notification list.** Do NOT include existing prospects or applications in the Slack message. Only genuinely new discoveries should be notified.

2. If no duplicate, create a prospect:
```bash
python3 -c "
from jj.db import create_application
app_id = create_application(
    company='COMPANY_NAME',
    position='JOB_TITLE',
    status='prospect',
    fit_score=TITLE_SCORE,
    job_url='JOB_URL',
    location='JOB_LOCATION',
    company_id=COMPANY_ID,
    notes='[Monitor] Title fit: SCORE/100',
)
print(f'APP_ID={app_id}')
"
```

Track `APP_ID` for JD scoring in Phase 2g. Track `PROSPECTS_CREATED` count for summary.

### 2g. Full JD Scoring (New Prospects Only)

For each new prospect created in 2f, score the full JD against the corpus.

**Load corpus once** (reuse for all listings in this run):
```bash
python3 -c "
from pathlib import Path
corpus = (Path.home() / '.job-journal' / 'corpus.md').read_text()
print(corpus[:100])  # Verify loaded
"
```

For each new prospect:

1. **WebFetch** the listing URL to get the full JD text
2. Score the JD against the corpus using the 4-category rubric:
   - Skills Match (35 points): Technical skills, tools, methodologies
   - Experience Alignment (25 points): Years, domain depth, role types
   - Domain Relevance (25 points): Industry, vertical, problem space
   - Location/Logistics (15 points): Remote, hybrid, relocation

   Produce a score 0-100 and a one-line verdict.

3. Update the application record:
```bash
python3 -c "
from jj.db import update_application
update_application(APP_ID, fit_score=CORPUS_SCORE, notes='[Monitor] Corpus fit: SCORE/100 — VERDICT')
"
```

4. Update the notification data for this listing:
   - Replace `score` with `CORPUS_SCORE`
   - Set `score_type` to `"Corpus Fit"`
   - Add `verdict` field (e.g., "Strong Fit", "Good Fit", "Moderate")

If WebFetch fails on any JD, keep the title-fit score and `score_type: "Title Fit"`.

### 2h. Auto-Resume Generation (Corpus Fit 65+)

For new prospects scoring **65+ on corpus fit**, generate a tailored resume. Cap at **3 resumes per monitor run** to stay within runtime budget.

For each qualifying prospect (highest scores first, up to 3):

1. Read the JD text (already fetched in 2g)
2. Select the best variant by matching JD keywords against known variant definitions
3. Use Claude's reasoning to:
   - SELECT the most relevant bullets from corpus for each role (do NOT generate new bullets)
   - Compose a tailored summary paragraph
   - Reorder skill categories to match JD emphasis
4. Score the tailored resume against the JD — must reach **85+** before generating
5. Generate the resume:
```bash
python3 -c "
import json
from pathlib import Path
from jj.google_docs import generate_resume_programmatic

result = generate_resume_programmatic(
    company='COMPANY_NAME',
    position='JOB_TITLE',
    variant='SELECTED_VARIANT',
    custom_summary='TAILORED_SUMMARY',
    custom_skills=CUSTOM_SKILLS_DICT,
    role_bullets=ROLE_BULLETS_DICT,
    jd_text='''JD_TEXT''',
    auto_open=False,
    keep_google_doc=True,
)
print(json.dumps({
    'pdf_path': str(result.pdf_path) if result.pdf_path else None,
    'doc_url': result.doc_url if hasattr(result, 'doc_url') else None,
    'doc_id': result.doc_id if hasattr(result, 'doc_id') else None,
}))
"
```

6. Validate resume content:
```bash
python3 -c "
import json
from jj.resume_gen import validate_resume_content
valid, count, issues = validate_resume_content(SELECTED_BULLETS)
print(json.dumps({'valid': valid, 'bullet_count': count, 'issues': issues}))
"
```

7. Update application record:
```bash
python3 -c "
from jj.db import update_application
update_application(APP_ID,
    resume_id=RESUME_ID,
    rj_before=RJ_BEFORE_SCORE,
    rj_after=RJ_AFTER_SCORE,
)
"
```

8. Add resume info to notification data:
   - Set `doc_url` on the job entry for Slack link
   - If validation flagged fabrication, add `fabrication_warning: True`

Track `RESUMES_GENERATED` count for summary.

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
{"title": "...", "company": "CompanyName (via BoardName)", "location": "...", "score": 65, "url": "...", "score_type": "Title Fit"}
```

### 3e. Auto-Prospect Creation (New VC Board Listings Passing Title Filter)

Same logic as Phase 2f. For each new listing passing title filter:

1. Call `find_duplicate_application()` with `company=COMPANY_NAME`, `position=JOB_TITLE`, `job_url=JOB_URL`
2. **If a duplicate is found, REMOVE this listing from the notification list.** Do NOT include existing prospects or applications in Slack.
3. If no duplicate, call `create_application()` with `status="prospect"`, `fit_score=TITLE_SCORE`, `notes="[Monitor] VC board: BOARD_NAME. Title fit: SCORE/100"`, `job_url=JOB_URL`

Track `APP_ID` for JD scoring in 3f.

### 3f. Full JD Scoring (New VC Board Prospects)

Same logic as Phase 2g. For each new prospect:
1. WebFetch full JD
2. Score against corpus (reuse corpus loaded earlier)
3. Update application record with corpus score
4. Update notification data with `score_type: "Corpus Fit"` and verdict

If WebFetch fails, keep title-fit score.

### 3g. Auto-Resume Generation (VC Board Prospects with Corpus Fit 65+)

Same logic as Phase 2h. Shares the **same cap of 3 total resumes per run** across both company and VC board prospects. If 3 resumes were already generated in Phase 2h, skip this phase.

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
        'prospects_created': PROSPECTS_CREATED,
        'resumes_generated': RESUMES_GENERATED,
        'timestamp': 'HH:MM',
    },
    'email_sync': EMAIL_SYNC_RESULT,
}

output = Path.home() / '.job-journal' / 'logs' / 'monitor-latest.json'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(results, indent=2))
print(f'Wrote {len(results[\"new_jobs\"])} jobs to {output}')
"
```

Each job in `new_jobs` should have these fields:
```json
{
    "title": "...",
    "company": "...",
    "location": "...",
    "score": 85,
    "score_type": "Corpus Fit",
    "verdict": "Strong Fit",
    "url": "...",
    "doc_url": "https://docs.google.com/...",
    "fabrication_warning": false
}
```

- `score_type`: Either `"Title Fit"` (from 2e/3d) or `"Corpus Fit"` (from 2g/3f)
- `verdict`: Only present when `score_type` is `"Corpus Fit"` — one of "Strong Fit", "Good Fit", "Moderate"
- `doc_url`: Only present when a resume was generated (from 2h/3g)
- `fabrication_warning`: Only present and `true` if resume validation flagged issues

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
        'prospects_created': PROSPECTS_CREATED,
        'resumes_generated': RESUMES_GENERATED,
        'email_sync': EMAIL_SYNC_RESULT,
        'scrape_failures': SCRAPE_FAILURE_COUNT,
        'scoring_failures': SCORING_FAILURE_COUNT,
        'resume_failures': RESUME_FAILURE_COUNT,
        'duration_seconds': DURATION_SECONDS,
    },
)
"
```

---

## Error Handling

| Situation | Response |
|-----------|----------|
| Gmail token missing | Skip email sync, log warning, continue |
| Gmail token expired | Skip email sync, log warning, continue |
| Email sync throws any exception | Log error, continue to Phase 2 |
| WebFetch fails on career page | Log warning, skip company, continue |
| WebFetch returns no listings | Record 0 listings, continue |
| WebFetch fails on JD page | Keep title-fit score, continue |
| JD scoring fails | Keep title-fit score, continue |
| Resume generation fails | Log error, skip resume, continue |
| Resume validation fails | Flag in notification, continue |
| Python script fails | Log error, continue to next item |
| No target companies or boards | Complete run with 0 counts, exit |
| Slack notification fails | Log error, still complete the run |
| Database error | Log error, continue if possible |

## Runtime Budget

| Phase | Expected Time |
|-------|--------------|
| Phase 1 (Initialize) | ~2s |
| Phase 1.5 (Email Sync) | ~30-60s |
| Phase 2a-2f (Scrape + Prospects) | ~3-5 min |
| Phase 2g (JD Scoring) | ~2-3 min (30-45s per new listing) |
| Phase 2h (Resume Gen) | ~3-5 min (up to 3 resumes) |
| Phase 3 (VC Boards) | ~2-3 min |
| Phase 4 (Notify) | ~5s |
| **Total** | **~10-15 min** |

## Notes

- Email sync runs BEFORE scraping so status changes are current in notifications
- Prospects are created automatically — visible immediately via `jj app list --status prospect`
- JD scoring uses the same 4-category rubric as `/pipeline` and `/score`
- Resume generation is capped at 3 per run to keep runtime reasonable
- Corpus is loaded ONCE and reused across all JD scoring
- `score_type` field in notification data distinguishes title-fit from corpus-fit scores
- Each run should complete in 10-15 minutes depending on new listings
- Results are persisted in `monitor-latest.json` for inspection
- Run history tracked in `monitor_runs` table with enriched summary
