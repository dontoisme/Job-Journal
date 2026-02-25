"""Greenhouse job board integration for Job Journal.

This module enables polling my.greenhouse.io for job listings using the
internal API discovered from HAR file analysis.

Authentication Flow:
1. User exports HAR from browser after searching my.greenhouse.io
2. `jj greenhouse setup --har ~/Downloads/my.greenhouse.io.har`
3. Extracts: x-csrf-token, x-inertia-version, cookies
4. Stores in ~/.job-journal/greenhouse_auth.yaml

Usage:
    from jj.greenhouse import GreenhouseClient, extract_auth_from_har

    # Setup from HAR file
    auth = extract_auth_from_har("~/Downloads/my.greenhouse.io.har")

    # Search for jobs
    client = GreenhouseClient(auth)
    jobs = client.search_jobs(query="Product Manager", location="Austin, Texas")
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from jj.config import JJ_HOME, load_config, load_yaml, save_config, save_yaml

# Path for greenhouse auth storage
GREENHOUSE_AUTH_PATH = JJ_HOME / "greenhouse_auth.yaml"


@dataclass
class GreenhouseAuth:
    """Authentication credentials for Greenhouse API.

    Attributes:
        csrf_token: x-csrf-token header value
        inertia_version: x-inertia-version header value
        cookies: Session cookies as a dict
    """
    csrf_token: str
    inertia_version: str
    cookies: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML storage."""
        return {
            "csrf_token": self.csrf_token,
            "inertia_version": self.inertia_version,
            "cookies": self.cookies,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GreenhouseAuth":
        """Create from dictionary (YAML load)."""
        return cls(
            csrf_token=data.get("csrf_token", ""),
            inertia_version=data.get("inertia_version", ""),
            cookies=data.get("cookies", {}),
        )

    def cookie_header(self) -> str:
        """Format cookies as HTTP header value."""
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())


@dataclass
class GreenhouseJob:
    """Represents a job posting from Greenhouse.

    Attributes:
        id: Greenhouse job ID
        title: Job title
        company_name: Company name
        location: Job location
        public_url: Public job posting URL
        first_published: When the job was first posted
        raw_data: Original API response data
    """
    id: int
    title: str
    company_name: str
    location: str
    public_url: str
    first_published: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: dict) -> "GreenhouseJob":
        """Create from API response data."""
        return cls(
            id=data.get("id", 0),
            title=data.get("title", ""),
            company_name=data.get("companyName", ""),
            location=data.get("location", ""),
            public_url=data.get("publicUrl", ""),
            first_published=data.get("firstPublished"),
            raw_data=data,
        )


def extract_auth_from_har(har_path: str | Path) -> GreenhouseAuth:
    """Extract Greenhouse authentication from a HAR file.

    Parses a HAR (HTTP Archive) file exported from browser DevTools
    to find the necessary authentication headers and cookies.

    Args:
        har_path: Path to the HAR file

    Returns:
        GreenhouseAuth with extracted credentials

    Raises:
        ValueError: If required auth data not found in HAR
        FileNotFoundError: If HAR file doesn't exist
    """
    har_path = Path(har_path).expanduser()

    if not har_path.exists():
        raise FileNotFoundError(f"HAR file not found: {har_path}")

    with open(har_path, "r", encoding="utf-8") as f:
        har_data = json.load(f)

    # Find requests to my.greenhouse.io
    entries = har_data.get("log", {}).get("entries", [])

    csrf_token = None
    csrf_token_partial = None  # Prefer CSRF from partial data request
    inertia_version = None
    cookies: dict[str, str] = {}

    for entry in entries:
        request = entry.get("request", {})
        url = request.get("url", "")

        # Look for requests to my.greenhouse.io
        if "my.greenhouse.io" not in url:
            continue

        headers = {h["name"].lower(): h["value"] for h in request.get("headers", [])}

        # Check if this is a partial data request (the actual job search API)
        is_partial = "x-inertia-partial-data" in headers

        # Extract CSRF token - prefer the one from partial data requests
        if "x-csrf-token" in headers:
            if is_partial:
                csrf_token_partial = headers["x-csrf-token"]
            elif not csrf_token:
                csrf_token = headers["x-csrf-token"]

        # Extract Inertia version
        if not inertia_version and "x-inertia-version" in headers:
            inertia_version = headers["x-inertia-version"]

        # Extract cookies
        if "cookie" in headers:
            cookie_str = headers["cookie"]
            for pair in cookie_str.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    # Only keep session-related cookies
                    if key.strip() in ("_session_id", "_job_board_session", "__cf_bm"):
                        cookies[key.strip()] = value.strip()

    # Use partial request CSRF token if available, otherwise fall back to any CSRF token
    csrf_token = csrf_token_partial or csrf_token

    if not csrf_token:
        raise ValueError("Could not find x-csrf-token in HAR file. "
                        "Make sure to capture a search request on my.greenhouse.io")

    if not inertia_version:
        raise ValueError("Could not find x-inertia-version in HAR file. "
                        "Make sure to capture a search request on my.greenhouse.io")

    return GreenhouseAuth(
        csrf_token=csrf_token,
        inertia_version=inertia_version,
        cookies=cookies,
    )


def save_auth(auth: GreenhouseAuth) -> None:
    """Save Greenhouse auth to config file."""
    save_yaml(GREENHOUSE_AUTH_PATH, auth.to_dict())


def load_auth() -> Optional[GreenhouseAuth]:
    """Load Greenhouse auth from config file."""
    if not GREENHOUSE_AUTH_PATH.exists():
        return None
    data = load_yaml(GREENHOUSE_AUTH_PATH)
    if not data:
        return None
    return GreenhouseAuth.from_dict(data)


class GreenhouseClient:
    """Client for the Greenhouse job search API.

    Uses the internal Inertia API discovered from browser traffic.

    Example:
        auth = load_auth()
        client = GreenhouseClient(auth)
        jobs = client.search_jobs(query="Product Manager", location="Austin, TX")
        for job in jobs:
            print(f"{job.title} at {job.company_name}")
    """

    BASE_URL = "https://my.greenhouse.io/jobs"

    def __init__(self, auth: GreenhouseAuth):
        """Initialize client with authentication.

        Args:
            auth: GreenhouseAuth credentials
        """
        self.auth = auth

    def _build_headers(self) -> dict[str, str]:
        """Build request headers for API calls."""
        headers = {
            "Accept": "text/html, application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Referer": "https://my.greenhouse.io/jobs",
            "x-csrf-token": self.auth.csrf_token,
            "x-inertia": "true",
            "x-inertia-version": self.auth.inertia_version,
            "x-inertia-partial-component": "job_search",
            "x-inertia-partial-data": "browsing,page,moreResultsAvailable,jobPosts,trackingData",
            "x-requested-with": "XMLHttpRequest",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        }
        if self.auth.cookies:
            headers["Cookie"] = self.auth.cookie_header()
        return headers

    def search_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        date_posted: Optional[str] = None,
        page: int = 1,
    ) -> tuple[list[GreenhouseJob], bool]:
        """Search for jobs on Greenhouse.

        Args:
            query: Job title or keyword search
            location: Location string (e.g., "Austin, Texas, United States")
            lat: Latitude for location-based search
            lon: Longitude for location-based search
            date_posted: Filter by date ("past_day", "past_week", "past_month")
            page: Page number for pagination

        Returns:
            Tuple of (list of GreenhouseJob, has_more_results)

        Raises:
            urllib.error.HTTPError: If API request fails
        """
        # Build query parameters
        params: dict[str, Any] = {"page": page}

        if query:
            params["query"] = query
        if location:
            params["location"] = location
        if lat is not None:
            params["lat"] = lat
        if lon is not None:
            params["lon"] = lon
        if date_posted:
            params["date_posted"] = date_posted

        # Build URL
        query_string = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}?{query_string}"

        # Make request
        request = urllib.request.Request(url, headers=self._build_headers())

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401 or e.code == 403:
                raise ValueError(
                    "Authentication failed. Your session may have expired.\n"
                    "Re-run: jj greenhouse setup --har <new-har-file>"
                ) from e
            raise

        # Parse Inertia response
        props = data.get("props", {})
        job_posts = props.get("jobPosts", [])
        more_available = props.get("moreResultsAvailable", False)

        jobs = [GreenhouseJob.from_api_response(jp) for jp in job_posts]

        return jobs, more_available

    def search_all_pages(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        date_posted: Optional[str] = None,
        max_pages: int = 5,
    ) -> list[GreenhouseJob]:
        """Search all pages for jobs.

        Args:
            query: Job title or keyword search
            location: Location string
            lat: Latitude for location-based search
            lon: Longitude for location-based search
            date_posted: Filter by date
            max_pages: Maximum pages to fetch (default 5)

        Returns:
            Combined list of all jobs across pages
        """
        all_jobs: list[GreenhouseJob] = []
        page = 1

        while page <= max_pages:
            jobs, has_more = self.search_jobs(
                query=query,
                location=location,
                lat=lat,
                lon=lon,
                date_posted=date_posted,
                page=page,
            )

            all_jobs.extend(jobs)

            if not has_more or not jobs:
                break

            page += 1

        return all_jobs


def import_jobs_as_prospects(jobs: list[GreenhouseJob]) -> dict[str, int]:
    """Import Greenhouse jobs as prospects into the applications table.

    Args:
        jobs: List of GreenhouseJob objects to import

    Returns:
        Dict with counts: {"imported": N, "skipped": N, "total": N}
    """
    from jj.db import get_connection

    imported = 0
    skipped = 0

    with get_connection() as conn:
        cursor = conn.cursor()

        for job in jobs:
            # Check if job already exists (by URL)
            cursor.execute(
                "SELECT id FROM applications WHERE job_url = ?",
                (job.public_url,)
            )
            existing = cursor.fetchone()

            if existing:
                skipped += 1
                continue

            # Insert as prospect
            cursor.execute(
                """
                INSERT INTO applications
                (company, position, location, job_url, ats_type, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.company_name,
                    job.title,
                    job.location,
                    job.public_url,
                    "greenhouse",
                    "prospect",
                    datetime.now().isoformat(),
                )
            )
            imported += 1

        conn.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "total": len(jobs),
    }


def get_search_config() -> dict[str, Any]:
    """Get Greenhouse search configuration from config file."""
    config = load_config()
    return config.get("greenhouse", {})


def save_search_config(
    query: Optional[str] = None,
    location: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    date_posted: Optional[str] = None,
) -> None:
    """Save Greenhouse search configuration."""
    config = load_config()

    greenhouse_config = config.get("greenhouse", {})

    if query is not None:
        greenhouse_config["query"] = query
    if location is not None:
        greenhouse_config["location"] = location
    if lat is not None:
        greenhouse_config["lat"] = lat
    if lon is not None:
        greenhouse_config["lon"] = lon
    if date_posted is not None:
        greenhouse_config["date_posted"] = date_posted

    config["greenhouse"] = greenhouse_config
    save_config(config)
