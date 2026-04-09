"""Direct ATS API scanner for Greenhouse, Lever, and Ashby.

Hits public JSON APIs directly — no browser, no scraping, no WebFetch.
Returns structured job data for dedup and title scoring.

API Endpoints (all public, no auth required):
  Greenhouse: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
  Lever:      GET https://api.lever.co/v0/postings/{company}
  Ashby:      GET https://api.ashbyhq.com/posting-api/job-board/{slug}
"""

import json
import logging
import re
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("jj.ats_scanner")

# Timeout for API requests (seconds)
REQUEST_TIMEOUT = 15


def extract_ats_slug(careers_url: str, ats_type: str) -> Optional[str]:
    """Extract the company slug from a careers URL for API calls.

    Examples:
        https://boards.greenhouse.io/affirm → affirm
        https://boards.greenhouse.io/affirm/jobs/12345 → affirm
        https://job-boards.greenhouse.io/affirm → affirm
        https://jobs.lever.co/handoff → handoff
        https://jobs.lever.co/handoff/abc-123 → handoff
        https://jobs.ashbyhq.com/safelease → safelease
        https://jobs.ashbyhq.com/sully-ai/d5b5c8d6-... → sully-ai
    """
    if not careers_url:
        return None

    ats_lower = ats_type.lower() if ats_type else ""

    if ats_lower == "greenhouse":
        # Match: boards.greenhouse.io/{slug} or job-boards.greenhouse.io/{slug}
        m = re.search(r"greenhouse\.io/([^/?#]+)", careers_url)
        if m:
            return m.group(1)

    elif ats_lower == "lever":
        # Match: jobs.lever.co/{slug}
        m = re.search(r"lever\.co/([^/?#]+)", careers_url)
        if m:
            return m.group(1)

    elif ats_lower == "ashby":
        # Match: jobs.ashbyhq.com/{slug}
        m = re.search(r"ashbyhq\.com/([^/?#]+)", careers_url)
        if m:
            return m.group(1)

    return None


def _fetch_json(url: str) -> Any:
    """Fetch JSON from a URL. Returns parsed JSON or None on error."""
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "jj-scanner/1.0"})
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as e:
        logger.debug("API request failed: %s — %s", url, e)
        return None


def scan_greenhouse(slug: str) -> list[dict[str, Any]]:
    """Hit Greenhouse boards API. Returns normalized job list.

    API: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
    Response: {"jobs": [{"id": 123, "title": "...", "location": {"name": "..."}, "absolute_url": "..."}]}
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    data = _fetch_json(url)
    if not data or "jobs" not in data:
        return []

    results = []
    for job in data["jobs"]:
        location = job.get("location", {})
        loc_name = location.get("name", "") if isinstance(location, dict) else str(location)
        results.append({
            "title": job.get("title", ""),
            "url": job.get("absolute_url", ""),
            "location": loc_name,
            "ats_job_id": str(job.get("id", "")),
            "ats_type": "greenhouse",
            "updated_at": job.get("updated_at"),
        })
    return results


def scan_lever(slug: str) -> list[dict[str, Any]]:
    """Hit Lever postings API. Returns normalized job list.

    API: GET https://api.lever.co/v0/postings/{company}
    Response: [{"id": "abc", "text": "...", "categories": {"location": "..."}, "hostedUrl": "..."}]
    """
    url = f"https://api.lever.co/v0/postings/{slug}"
    data = _fetch_json(url)
    if not data or not isinstance(data, list):
        return []

    results = []
    for job in data:
        categories = job.get("categories", {})
        location = categories.get("location", "") if isinstance(categories, dict) else ""
        results.append({
            "title": job.get("text", ""),
            "url": job.get("hostedUrl", ""),
            "location": location,
            "ats_job_id": str(job.get("id", "")),
            "ats_type": "lever",
            "updated_at": None,
        })
    return results


def scan_ashby(slug: str) -> list[dict[str, Any]]:
    """Hit Ashby posting API. Returns normalized job list.

    API: GET https://api.ashbyhq.com/posting-api/job-board/{slug}
    Response: {"jobs": [{"id": "abc", "title": "...", "location": "...", "jobUrl": "..."}]}
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = _fetch_json(url)
    if not data:
        return []

    # Ashby response can have jobs at top level or nested
    jobs = data.get("jobs", [])
    if not jobs and isinstance(data, list):
        jobs = data

    results = []
    for job in jobs:
        location = job.get("location", "")
        if isinstance(location, dict):
            location = location.get("name", "")
        job_url = job.get("jobUrl", "") or job.get("hostedUrl", "")
        # Build URL if only ID available
        if not job_url and job.get("id"):
            job_url = f"https://jobs.ashbyhq.com/{slug}/{job['id']}"
        results.append({
            "title": job.get("title", ""),
            "url": job_url,
            "location": location,
            "ats_job_id": str(job.get("id", "")),
            "ats_type": "ashby",
            "updated_at": job.get("updatedAt"),
        })
    return results


# Scanner dispatch table
_SCANNERS = {
    "greenhouse": scan_greenhouse,
    "lever": scan_lever,
    "ashby": scan_ashby,
}


def scan_company(company: dict[str, Any]) -> list[dict[str, Any]]:
    """Scan a single company via its ATS API.

    Args:
        company: Dict with keys: id, name, careers_url, ats_type

    Returns:
        List of normalized job dicts with company_id and company_name added.
    """
    ats_type = (company.get("ats_type") or "").lower()
    scanner = _SCANNERS.get(ats_type)
    if not scanner:
        return []

    slug = extract_ats_slug(company.get("careers_url", ""), ats_type)
    if not slug:
        logger.warning("Could not extract slug for %s (%s): %s",
                        company.get("name"), ats_type, company.get("careers_url"))
        return []

    logger.info("Scanning %s via %s API (slug: %s)", company.get("name"), ats_type, slug)
    jobs = scanner(slug)

    # Attach company info to each job
    for job in jobs:
        job["company_id"] = company.get("id")
        job["company_name"] = company.get("name", "")

    return jobs


def scan_all_api_companies(companies: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Scan all API-compatible companies sequentially.

    Args:
        companies: List of company dicts from DB (must have id, name, careers_url, ats_type)

    Returns:
        Dict mapping company_id to list of jobs found.
        Also includes a "_summary" key with scan stats.
    """
    results: dict[int, list[dict[str, Any]]] = {}
    total_jobs = 0
    scanned = 0
    errors = 0

    for company in companies:
        company_id = company.get("id")
        if not company_id:
            continue

        try:
            jobs = scan_company(company)
            if jobs:
                results[company_id] = jobs
                total_jobs += len(jobs)
            scanned += 1
        except Exception as e:
            logger.error("Error scanning %s: %s", company.get("name"), e)
            errors += 1

    results["_summary"] = {
        "companies_scanned": scanned,
        "companies_with_errors": errors,
        "total_jobs_found": total_jobs,
    }
    return results


def get_api_scannable_companies() -> list[dict[str, Any]]:
    """Load target companies that can be scanned via ATS APIs.

    Returns companies where ats_type is greenhouse, lever, or ashby
    and careers_url is set.
    """
    from jj.db import get_connection

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, careers_url, ats_type
            FROM companies
            WHERE is_target = 1
              AND careers_url IS NOT NULL
              AND LOWER(ats_type) IN ('greenhouse', 'lever', 'ashby')
            ORDER BY target_priority DESC, name
        """)
        return [dict(row) for row in cursor.fetchall()]


# --- Investor board scanning ---


def _extract_board_slugs(board_url: str, short_name: str = None) -> list[str]:
    """Extract potential ATS slugs from a board URL for API probing."""
    from urllib.parse import urlparse

    slugs = []
    parsed = urlparse(board_url)
    host = parsed.hostname or ""
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    # Standard ATS URLs — extract slug directly
    if "greenhouse.io" in host and path_parts:
        slugs.append(path_parts[0])
    elif "lever.co" in host and path_parts:
        slugs.append(path_parts[0])
    elif "ashbyhq.com" in host and path_parts:
        slugs.append(path_parts[0])
    else:
        # Custom domain: jobs.X.com or careers.X.com → try X
        parts = host.split(".")
        if len(parts) >= 3 and parts[0] in ("jobs", "careers", "talent", "boards"):
            slugs.append(parts[1])
        elif len(parts) >= 2:
            slugs.append(parts[-2])

    # Also try short_name variants
    if short_name:
        name_lower = short_name.lower()
        for variant in [name_lower.replace(" ", "-"), name_lower.replace(" ", "")]:
            if variant not in slugs:
                slugs.append(variant)

    return slugs


def probe_board_ats_type(board_url: str, short_name: str = None) -> tuple[Optional[str], Optional[str]]:
    """Probe a board URL to detect which ATS platform powers it.

    Tries Ashby, Greenhouse, and Lever APIs with candidate slugs.
    Returns (ats_type, working_slug) or (None, None) if undetectable.
    """
    from urllib.parse import urlparse

    parsed = urlparse(board_url)
    host = parsed.hostname or ""

    # If it's already a known ATS domain, extract directly
    if "greenhouse.io" in host:
        slug = extract_ats_slug(board_url, "greenhouse")
        return ("greenhouse", slug) if slug else (None, None)
    if "lever.co" in host:
        slug = extract_ats_slug(board_url, "lever")
        return ("lever", slug) if slug else (None, None)
    if "ashbyhq.com" in host:
        slug = extract_ats_slug(board_url, "ashby")
        return ("ashby", slug) if slug else (None, None)

    # Custom domain — probe each ATS API with candidate slugs
    slugs = _extract_board_slugs(board_url, short_name)

    for slug in slugs:
        # Ashby first (most common for VC boards with custom domains)
        data = _fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if data and "jobs" in data:
            return "ashby", slug

        # Greenhouse
        data = _fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if data and "jobs" in data:
            return "greenhouse", slug

        # Lever
        data = _fetch_json(f"https://api.lever.co/v0/postings/{slug}")
        if data and isinstance(data, list):
            return "lever", slug

    return None, None


def get_api_scannable_boards() -> list[dict[str, Any]]:
    """Load active investor boards for API scanning."""
    from jj.db import get_connection

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, short_name, board_url, ats_type
            FROM investor_boards
            WHERE is_active = 1
              AND board_url IS NOT NULL
            ORDER BY priority DESC, name
        """)
        return [dict(row) for row in cursor.fetchall()]


def scan_investor_board(board: dict[str, Any]) -> list[dict[str, Any]]:
    """Scan a single investor board via ATS API.

    If ats_type is unknown, probes to detect it and caches the result.
    Returns normalized job list with board_id and board_name attached.
    """
    from jj.db import update_investor_board

    board_id = board.get("id")
    board_url = board.get("board_url", "")
    short_name = board.get("short_name")
    ats_type = (board.get("ats_type") or "").lower()

    slug = None

    # If ATS type unknown, probe to detect
    if ats_type not in _SCANNERS:
        detected_type, detected_slug = probe_board_ats_type(board_url, short_name)
        if detected_type:
            ats_type = detected_type
            slug = detected_slug
            # Cache so we don't probe again
            update_investor_board(board_id, ats_type=ats_type)
            logger.info("Detected %s as %s (slug: %s)", board.get("name"), ats_type, slug)
        else:
            logger.info("Could not detect ATS for %s (%s)", board.get("name"), board_url)
            return []

    scanner = _SCANNERS.get(ats_type)
    if not scanner:
        return []

    if not slug:
        slug = extract_ats_slug(board_url, ats_type)
        if not slug:
            slugs = _extract_board_slugs(board_url, short_name)
            slug = slugs[0] if slugs else None

    if not slug:
        return []

    logger.info("Scanning board %s via %s API (slug: %s)", board.get("name"), ats_type, slug)
    jobs = scanner(slug)

    for job in jobs:
        job["board_id"] = board_id
        job["board_name"] = board.get("name", "")

    return jobs


def scan_all_api_boards(boards: list[dict[str, Any]]) -> dict[str, Any]:
    """Scan all investor boards via ATS APIs.

    Returns dict mapping board_id to job lists, plus a _summary key.
    """
    results: dict[int, list[dict[str, Any]]] = {}
    total_jobs = 0
    scanned = 0
    probed = 0
    errors = 0

    for board in boards:
        board_id = board.get("id")
        if not board_id:
            continue

        if not board.get("ats_type"):
            probed += 1

        try:
            jobs = scan_investor_board(board)
            if jobs:
                results[board_id] = jobs
                total_jobs += len(jobs)
            scanned += 1
        except Exception as e:
            logger.error("Error scanning board %s: %s", board.get("name"), e)
            errors += 1

    results["_summary"] = {
        "boards_scanned": scanned,
        "boards_probed": probed,
        "boards_with_errors": errors,
        "total_jobs_found": total_jobs,
    }
    return results
