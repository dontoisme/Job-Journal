# ATS Job Monitoring - Future Implementation

Track recently posted jobs from target companies by polling their ATS job board APIs.

## Concept

Since the `companies` table already tracks `ats_type` (greenhouse, lever, ashby, etc.), we can leverage known public API patterns to poll for new job postings without web scraping.

## ATS Public APIs (No Auth Required)

| ATS | API Endpoint Pattern | Response | Notes |
|-----|---------------------|----------|-------|
| **Greenhouse** | `https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs` | JSON with `updated_at` | Most common. Board token is company slug. |
| **Lever** | `https://api.lever.co/v0/postings/{company}` | JSON array | Company is URL slug |
| **Ashby** | `https://jobs.ashbyhq.com/api/non-user-graphql` | GraphQL | Requires company ID discovery |
| **SmartRecruiters** | `https://api.smartrecruiters.com/v1/companies/{id}/postings` | JSON | Need company ID |
| **Workday** | Varies by tenant | JSON | Pattern: `{company}.wd5.myworkdayjobs.com/wday/cxs/{company}/External/jobs` |

### Greenhouse Example

```bash
# List all jobs for Stripe
curl "https://boards-api.greenhouse.io/v1/boards/stripe/jobs" | jq '.jobs[] | {id, title, updated_at}'

# Get job details including created timestamp
curl "https://boards-api.greenhouse.io/v1/boards/stripe/jobs/123456"
```

Response includes:
- `id` - Job ID
- `title` - Job title
- `updated_at` - ISO timestamp
- `location.name` - Location string
- `departments[].name` - Department
- `absolute_url` - Direct link to apply

### Lever Example

```bash
# List all jobs for a company
curl "https://api.lever.co/v0/postings/cloudflare" | jq '.[] | {id, text, createdAt}'
```

## Database Changes

Add to `companies` table:
```sql
ALTER TABLE companies ADD COLUMN board_token TEXT;        -- e.g., "stripe" for greenhouse
ALTER TABLE companies ADD COLUMN last_job_check TEXT;     -- ISO timestamp
ALTER TABLE companies ADD COLUMN job_check_interval INTEGER DEFAULT 21600;  -- 6 hours in seconds
```

Add new table for discovered jobs:
```sql
CREATE TABLE IF NOT EXISTS company_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    external_job_id TEXT NOT NULL,           -- ID from ATS
    title TEXT NOT NULL,
    location TEXT,
    department TEXT,
    job_url TEXT,
    created_at_ats TEXT,                     -- When job was posted (from ATS)
    updated_at_ats TEXT,                     -- When job was updated (from ATS)
    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
    is_new BOOLEAN DEFAULT 1,                -- Unseen by user
    is_relevant BOOLEAN,                     -- Matches search criteria
    application_id INTEGER REFERENCES applications(id),  -- If we applied
    UNIQUE(company_id, external_job_id)
);
```

## Implementation Approach

### 1. ATS Fetcher Module (`jj/ats_fetcher.py`)

```python
from dataclasses import dataclass
from typing import Protocol, Optional
import httpx
from datetime import datetime, timedelta

@dataclass
class JobPosting:
    external_id: str
    title: str
    location: Optional[str]
    department: Optional[str]
    url: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

class ATSFetcher(Protocol):
    def fetch_jobs(self, board_token: str) -> list[JobPosting]: ...

class GreenhouseFetcher:
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    def fetch_jobs(self, board_token: str) -> list[JobPosting]:
        url = f"{self.BASE_URL}/{board_token}/jobs"
        response = httpx.get(url, params={"content": "true"})
        response.raise_for_status()

        jobs = []
        for job in response.json().get("jobs", []):
            jobs.append(JobPosting(
                external_id=str(job["id"]),
                title=job["title"],
                location=job.get("location", {}).get("name"),
                department=job.get("departments", [{}])[0].get("name"),
                url=job.get("absolute_url", ""),
                created_at=None,  # Requires individual job fetch
                updated_at=datetime.fromisoformat(job["updated_at"].replace("Z", "+00:00")),
            ))
        return jobs

class LeverFetcher:
    BASE_URL = "https://api.lever.co/v0/postings"

    def fetch_jobs(self, board_token: str) -> list[JobPosting]:
        url = f"{self.BASE_URL}/{board_token}"
        response = httpx.get(url)
        response.raise_for_status()

        jobs = []
        for job in response.json():
            jobs.append(JobPosting(
                external_id=job["id"],
                title=job["text"],
                location=job.get("categories", {}).get("location"),
                department=job.get("categories", {}).get("team"),
                url=job["hostedUrl"],
                created_at=datetime.fromtimestamp(job["createdAt"] / 1000),
                updated_at=None,
            ))
        return jobs

# Factory
FETCHERS = {
    "greenhouse": GreenhouseFetcher(),
    "lever": LeverFetcher(),
    # Add more as discovered
}

def get_fetcher(ats_type: str) -> Optional[ATSFetcher]:
    return FETCHERS.get(ats_type)
```

### 2. Background Task Integration

Register with existing worker system:

```python
# In worker.py
from jj.ats_fetcher import get_fetcher, JobPosting
from jj.db import get_companies_due_for_check, upsert_company_job, mark_company_checked

@register_task("job_monitor")
def job_monitor_task(payload: dict) -> dict:
    """Check target companies for new job postings."""
    companies = get_companies_due_for_check()
    results = {"checked": 0, "new_jobs": 0, "errors": []}

    for company in companies:
        fetcher = get_fetcher(company["ats_type"])
        if not fetcher or not company["board_token"]:
            continue

        try:
            jobs = fetcher.fetch_jobs(company["board_token"])
            for job in jobs:
                is_new = upsert_company_job(company["id"], job)
                if is_new:
                    results["new_jobs"] += 1
            mark_company_checked(company["id"])
            results["checked"] += 1
        except Exception as e:
            results["errors"].append(f"{company['name']}: {e}")

    return results
```

### 3. CLI Commands

```bash
# Manual check for a specific company
jj company check "Stripe"

# Check all due companies
jj company check --all

# Show recent jobs (past 24h)
jj company jobs --recent 24h

# Show new/unseen jobs
jj company jobs --new

# Mark job as seen or create prospect
jj company jobs apply 12345
```

## Discovery: Finding Board Tokens

The tricky part is mapping company names to their ATS board tokens. Approaches:

### 1. Manual Entry
User provides when adding company:
```bash
jj company add "Stripe" --careers-url "https://stripe.com/jobs" --ats greenhouse --board-token stripe
```

### 2. Auto-Discovery from Careers URL
Parse known patterns:
- `boards.greenhouse.io/{token}` → token
- `jobs.lever.co/{token}` → token
- `{company}.ashbyhq.com` → company

### 3. Scrape Careers Page (fallback)
If careers_url provided but ATS unknown, fetch page and look for:
- iframe src containing greenhouse/lever/etc
- Links to known ATS domains
- Script tags loading ATS widgets

## Filtering & Relevance

Apply filters to mark jobs as relevant:

```python
RELEVANT_KEYWORDS = [
    "product manager", "pm", "product lead", "product director",
    "growth", "platform", "technical pm", "senior pm"
]

EXCLUDE_KEYWORDS = [
    "intern", "associate", "new grad", "entry level"
]

def is_relevant(job: JobPosting) -> bool:
    title_lower = job.title.lower()
    has_keyword = any(kw in title_lower for kw in RELEVANT_KEYWORDS)
    has_exclude = any(kw in title_lower for kw in EXCLUDE_KEYWORDS)
    return has_keyword and not has_exclude
```

## Notification Options

When new relevant jobs are found:

1. **CLI notification** - Show on next `jj` command
2. **Desktop notification** - Use `notify-send` or macOS notifications
3. **Email digest** - Send daily/hourly summary
4. **Webhook** - POST to Slack/Discord

## Rate Limiting

Be respectful:
- Max 1 request per company per 6 hours
- Add jitter to avoid thundering herd
- Exponential backoff on errors
- Respect `Retry-After` headers

## Open Questions

1. **RSS feeds** - Some ATS expose RSS. Worth checking? Lower overhead but less metadata.
2. **Job detail fetching** - Greenhouse requires separate call for `created_at`. Worth the extra requests?
3. **Historical tracking** - Keep jobs after they're removed? Useful for market analysis.
4. **Duplicate detection** - Same job posted multiple times with different IDs?

## Priority

This feature would be most valuable for:
- High-priority target companies (`target_priority = 1`)
- Companies with known ATS types
- PM/Growth roles (filtered by keywords)

Start with Greenhouse and Lever (most common in tech), add others as needed.
