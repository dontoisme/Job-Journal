"""Geo-targeted job discovery for Austin corridors."""

import json
import re
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from jj.config import DB_PATH, JJ_HOME

# Austin area definitions
AREAS = {
    "downtown": {"lat": 30.2672, "lng": -97.7431, "radius": 2000},
    "south_mopac": {"lat": 30.2500, "lng": -97.7700, "radius": 2500},
    "domain": {"lat": 30.4020, "lng": -97.7250, "radius": 2500},
    "east": {"lat": 30.2650, "lng": -97.7200, "radius": 2000},
}

# Keywords for tech company search
SEARCH_KEYWORDS = [
    "software company",
    "tech startup",
    "technology company",
    "saas company",
]

# PM role keywords for filtering
PM_KEYWORDS = [
    "product manager",
    "product lead",
    "head of product",
    "director of product",
    "vp product",
    "chief product",
    "pm ",
    "senior pm",
    "staff pm",
    "principal pm",
]


@dataclass
class Company:
    """Represents a discovered company."""
    name: str
    address: str
    place_id: str
    latitude: float
    longitude: float
    website: Optional[str] = None
    careers_url: Optional[str] = None


def get_api_key() -> str:
    """Load Google Maps API key from config."""
    config_path = JJ_HOME / "config.yaml"
    if not config_path.exists():
        raise ValueError("Config file not found. Run 'jj init' first.")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    key = config.get("google_maps_api_key", "")
    if not key:
        raise ValueError("google_maps_api_key not found in config.yaml")

    return key


def discover_companies(area: str = "downtown", keywords: list[str] = None) -> list[Company]:
    """
    Discover companies in an Austin area using Google Maps Places API.

    Args:
        area: One of 'downtown', 'south_mopac', 'domain', 'east'
        keywords: Search keywords (defaults to SEARCH_KEYWORDS)

    Returns:
        List of discovered companies
    """
    if area not in AREAS:
        raise ValueError(f"Unknown area: {area}. Choose from: {list(AREAS.keys())}")

    api_key = get_api_key()
    location = AREAS[area]
    keywords = keywords or SEARCH_KEYWORDS

    all_companies = {}

    for keyword in keywords:
        url = (
            f"https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            f"?location={location['lat']},{location['lng']}"
            f"&radius={location['radius']}"
            f"&keyword={urllib.parse.quote(keyword)}"
            f"&key={api_key}"
        )

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            if data.get("status") != "OK":
                print(f"  Warning: {keyword} - {data.get('status')}")
                continue

            for place in data.get("results", []):
                place_id = place.get("place_id")
                if place_id and place_id not in all_companies:
                    all_companies[place_id] = Company(
                        name=place.get("name", "Unknown"),
                        address=place.get("vicinity", ""),
                        place_id=place_id,
                        latitude=place.get("geometry", {}).get("location", {}).get("lat", 0),
                        longitude=place.get("geometry", {}).get("location", {}).get("lng", 0),
                    )
        except Exception as e:
            print(f"  Error searching '{keyword}': {e}")

    return list(all_companies.values())


def get_place_details(place_id: str) -> dict:
    """Get detailed info about a place including website."""
    api_key = get_api_key()
    url = (
        f"https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place_id}"
        f"&fields=name,website,formatted_address,formatted_phone_number"
        f"&key={api_key}"
    )

    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())

        if data.get("status") == "OK":
            return data.get("result", {})
    except Exception as e:
        print(f"  Error getting details for {place_id}: {e}")

    return {}


def save_companies(companies: list[Company], source: str = "google_maps") -> int:
    """
    Save discovered companies to database.

    Returns:
        Number of new companies added
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    added = 0
    for company in companies:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO geo_companies
                (name, address, latitude, longitude, place_id, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                company.name,
                company.address,
                company.latitude,
                company.longitude,
                company.place_id,
                source,
                datetime.now().isoformat(),
            ))
            if cursor.rowcount > 0:
                added += 1
        except Exception as e:
            print(f"  Error saving {company.name}: {e}")

    conn.commit()
    conn.close()
    return added


def enrich_companies_with_websites() -> int:
    """
    Fetch websites for companies that don't have one yet.
    Uses Place Details API.

    Returns:
        Number of companies enriched
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, place_id FROM geo_companies
        WHERE website IS NULL AND place_id IS NOT NULL
    """)
    companies = cursor.fetchall()

    enriched = 0
    for company in companies:
        details = get_place_details(company["place_id"])
        website = details.get("website")

        if website:
            cursor.execute("""
                UPDATE geo_companies SET website = ? WHERE id = ?
            """, (website, company["id"]))
            enriched += 1
            print(f"  + {company['name']}: {website}")

    conn.commit()
    conn.close()
    return enriched


def guess_careers_url(website: str) -> list[str]:
    """Generate possible careers page URLs from a website."""
    if not website:
        return []

    # Normalize
    website = website.rstrip("/")
    domain = urllib.parse.urlparse(website).netloc
    base_domain = ".".join(domain.split(".")[-2:])  # e.g., "company.com"

    return [
        f"{website}/careers",
        f"{website}/jobs",
        f"{website}/career",
        f"{website}/about/careers",
        f"{website}/company/careers",
        f"https://jobs.{base_domain}",
        f"https://careers.{base_domain}",
    ]


def detect_ats_url(company_name: str) -> list[str]:
    """Generate possible ATS URLs based on company name."""
    slug = re.sub(r"[^a-z0-9]", "", company_name.lower())

    return [
        f"https://boards.greenhouse.io/{slug}",
        f"https://jobs.lever.co/{slug}",
        f"https://jobs.ashbyhq.com/{slug}",
        f"https://{slug}.greenhouse.io",
    ]


def get_companies_for_careers_discovery() -> list[dict]:
    """Get companies that have websites but no careers URL yet."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, website FROM geo_companies
        WHERE website IS NOT NULL AND careers_url IS NULL
    """)

    result = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return result


def update_careers_url(company_id: int, careers_url: str):
    """Update a company's careers URL."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE geo_companies SET careers_url = ?, last_scraped = ? WHERE id = ?
    """, (careers_url, datetime.now().isoformat(), company_id))
    conn.commit()
    conn.close()


def get_all_companies() -> list[dict]:
    """Get all discovered companies."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM geo_companies ORDER BY name")
    result = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return result


def get_companies_with_careers() -> list[dict]:
    """Get companies that have careers URLs for job scraping."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM geo_companies
        WHERE careers_url IS NOT NULL
        ORDER BY name
    """)
    result = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return result


def is_pm_role(title: str) -> bool:
    """Check if a job title is a PM role."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in PM_KEYWORDS)


def find_careers_page(company: dict) -> Optional[str]:
    """
    Try common careers URL patterns to find a working careers page.

    Args:
        company: Dict with 'name' and optionally 'website' keys

    Returns:
        First working careers URL or None
    """
    import ssl

    # Create a context that doesn't verify SSL (for speed, these are just probes)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    urls_to_try = []

    # Try website-based URLs first
    website = company.get("website")
    if website:
        urls_to_try.extend(guess_careers_url(website))

    # Try ATS-based URLs
    urls_to_try.extend(detect_ats_url(company.get("name", "")))

    for url in urls_to_try:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; JobJournal/1.0)"},
                method="HEAD"
            )
            with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                if response.status == 200:
                    return url
        except Exception:
            # Try GET if HEAD fails
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; JobJournal/1.0)"}
                )
                with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                    if response.status == 200:
                        return url
            except Exception:
                continue

    return None


def get_companies_in_area(area_id: int) -> list[dict]:
    """Get all companies within a geo area by ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get the area info
    cursor.execute("SELECT * FROM geo_areas WHERE id = ?", (area_id,))
    area = cursor.fetchone()
    if not area:
        conn.close()
        return []

    area = dict(area)

    # Get all companies
    cursor.execute("SELECT * FROM geo_companies")
    all_companies = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # Filter by distance
    from math import radians, sin, cos, sqrt, atan2

    def haversine(lat1, lng1, lat2, lng2):
        R = 6371000  # Earth's radius in meters
        lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
        return 2 * R * atan2(sqrt(a), sqrt(1-a))

    radius = area["radius"]
    companies_in_area = []

    # Check if corridor (has points)
    if area.get("points"):
        points = json.loads(area["points"])
        for company in all_companies:
            if not company.get("latitude") or not company.get("longitude"):
                continue
            for pt in points:
                dist = haversine(pt["lat"], pt["lng"], company["latitude"], company["longitude"])
                if dist <= radius:
                    companies_in_area.append(company)
                    break
    else:
        # Single point area
        for company in all_companies:
            if not company.get("latitude") or not company.get("longitude"):
                continue
            dist = haversine(area["latitude"], area["longitude"], company["latitude"], company["longitude"])
            if dist <= radius:
                companies_in_area.append(company)

    return companies_in_area


def run_enrichment_pipeline(area_id: int) -> dict:
    """
    Run immediate enrichment for companies in an area.

    1. Get websites from Google Places API
    2. Probe for careers pages

    Returns:
        Dict with stats: {total, websites_found, careers_found}
    """
    companies = get_companies_in_area(area_id)

    stats = {
        "total": len(companies),
        "websites_found": 0,
        "careers_found": 0,
        "already_had_website": 0,
        "already_had_careers": 0,
    }

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for company in companies:
        # Step 1: Get website if missing
        if not company.get("website") and company.get("place_id"):
            details = get_place_details(company["place_id"])
            website = details.get("website")
            if website:
                cursor.execute(
                    "UPDATE geo_companies SET website = ? WHERE id = ?",
                    (website, company["id"])
                )
                company["website"] = website
                stats["websites_found"] += 1
        elif company.get("website"):
            stats["already_had_website"] += 1

        # Step 2: Find careers page if missing
        if not company.get("careers_url") and (company.get("website") or company.get("name")):
            careers_url = find_careers_page(company)
            if careers_url:
                cursor.execute(
                    "UPDATE geo_companies SET careers_url = ? WHERE id = ?",
                    (careers_url, company["id"])
                )
                stats["careers_found"] += 1
        elif company.get("careers_url"):
            stats["already_had_careers"] += 1

    conn.commit()
    conn.close()

    return stats


def update_company_job_count(company_id: int, job_count: int):
    """Update the job count for a company."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE geo_companies SET job_count = ?, last_scraped = ? WHERE id = ?",
        (job_count, datetime.now().isoformat(), company_id)
    )
    conn.commit()
    conn.close()


def discover_companies_for_area(area: dict, keywords: list[str] = None) -> list[Company]:
    """
    Discover companies in a custom area (from database).

    Args:
        area: Dict with 'latitude', 'longitude', 'radius' keys
        keywords: Search keywords (defaults to SEARCH_KEYWORDS)

    Returns:
        List of discovered companies
    """
    api_key = get_api_key()
    keywords = keywords or SEARCH_KEYWORDS

    all_companies = {}

    for keyword in keywords:
        url = (
            f"https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            f"?location={area['latitude']},{area['longitude']}"
            f"&radius={area['radius']}"
            f"&keyword={urllib.parse.quote(keyword)}"
            f"&key={api_key}"
        )

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            if data.get("status") != "OK":
                continue

            for place in data.get("results", []):
                place_id = place.get("place_id")
                if place_id and place_id not in all_companies:
                    all_companies[place_id] = Company(
                        name=place.get("name", "Unknown"),
                        address=place.get("vicinity", ""),
                        place_id=place_id,
                        latitude=place.get("geometry", {}).get("location", {}).get("lat", 0),
                        longitude=place.get("geometry", {}).get("location", {}).get("lng", 0),
                    )
        except Exception as e:
            print(f"  Error searching '{keyword}': {e}")

    return list(all_companies.values())


# CLI entry point for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m jj.geo <command>")
        print("Commands: discover, enrich, list")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "discover":
        area = sys.argv[2] if len(sys.argv) > 2 else "downtown"
        print(f"Discovering companies in {area}...")
        companies = discover_companies(area)
        print(f"Found {len(companies)} companies")
        added = save_companies(companies)
        print(f"Added {added} new companies to database")

    elif cmd == "enrich":
        print("Enriching companies with websites...")
        enriched = enrich_companies_with_websites()
        print(f"Enriched {enriched} companies")

    elif cmd == "list":
        companies = get_all_companies()
        print(f"Total companies: {len(companies)}")
        for c in companies:
            print(f"  - {c['name']}: {c.get('website', 'no website')}")
