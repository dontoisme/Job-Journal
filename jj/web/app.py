"""Job Journal Web Dashboard - FastAPI Application."""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jj.analytics import get_all_analytics, get_funnel_stats, get_weekly_summary
from jj.config import CORPUS_PATH, JJ_HOME, load_profile
from jj.db import (
    DB_PATH,
    backfill_activity_dates,
    create_task,
    get_all_twc_claim_periods,
    get_application,
    get_applications,
    get_applications_with_pairing_status,
    get_entries_for_role,
    get_focus_counts,
    # Email pairing functions
    get_pairing_stats,
    get_pipeline_stats,
    get_recent_tasks,
    get_resumes_with_applications,
    get_roles,
    get_skills,
    get_stale_applications,
    get_stats,
    get_task_stats,
    get_todays_focus,
    get_twc_activities_for_week,
    get_twc_activity_types,
    get_twc_result_types,
    # TWC functions
    get_twc_week_boundaries,
    get_twc_week_summary,
    log_event,
    mark_twc_payment_submitted,
    update_application,
    update_twc_fields,
)
from jj.geo import (
    AREAS,
    discover_companies_for_area,
    get_all_companies,
    run_enrichment_pipeline,
    save_companies,
)

# App setup
app = FastAPI(
    title="Job Journal",
    description="Interview your career, customize your resume",
    version="0.1.0",
)

# Static files and templates
WEB_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")

# Add custom Jinja2 filters

def parse_tags(value):
    """Parse JSON tags string into a list."""
    if not value:
        return []
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

templates.env.filters["parse_tags"] = parse_tags


def format_relative_date(value):
    """Format a date as relative time (e.g., '2 days ago')."""
    if not value:
        return ''
    try:
        if isinstance(value, str):
            # Parse ISO format, handle various timezone formats
            clean_value = value.replace('Z', '+00:00')
            dt = datetime.fromisoformat(clean_value)
        else:
            dt = value

        now = datetime.now()
        # Strip timezone for comparison
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)

        diff = now - dt
        total_seconds = diff.total_seconds()

        # Handle future dates (timezone issues)
        if total_seconds < 0:
            return "today"

        days = diff.days

        if days == 0:
            hours = int(total_seconds // 3600)
            if hours == 0:
                minutes = int(total_seconds // 60)
                return f"{minutes}m ago" if minutes > 0 else "just now"
            return f"{hours}h ago"
        elif days == 1:
            return "yesterday"
        elif days < 7:
            return f"{days}d ago"
        elif days < 30:
            weeks = days // 7
            return f"{weeks}w ago"
        else:
            return dt.strftime("%b %d")
    except Exception:
        return str(value)[:10] if value else ''


templates.env.filters["relative_date"] = format_relative_date


# --------------------------------------------------------------------------
# Helper functions
# --------------------------------------------------------------------------

# Precompiled regexes for parsing application.notes
_RE_TITLE_NOTES = re.compile(r"^Title Fit:\s*(\d+)\.\s*(.*)$", re.IGNORECASE)
_RE_CORPUS_NOTES = re.compile(
    r"^Fit:\s*(\d+)%?\s*\(([^)]+)\)\.\s*"
    r"(?:Archetype:\s*([^.]+)\.\s*)?"  # optional — added by WIP /score
    r"Skills:\s*(\d+)/(\d+),\s*"
    r"Exp(?:erience)?:\s*(\d+)/(\d+),\s*"
    r"Domain:\s*(\d+)/(\d+),\s*"
    r"Location:\s*(\d+)/(\d+)\.\s*"
    r"(.*)$",
    re.IGNORECASE,
)


def classify_score(notes: str, fit_score: int | None) -> dict:
    """Parse an application.notes field into structured score info.

    Returns a dict with:
      - score_type: 'title' | 'corpus' | 'unknown'
      - total: int | None        (the numeric fit score)
      - verdict: str | None      ('Strong Fit' / 'Good Fit' / 'Moderate' / 'Stretch')
      - source: str | None       (e.g., 'Via API scan.')
      - archetype: str | None    (only for corpus, only if /score-WIP wrote it)
      - breakdown: dict | None   (only for corpus — skills/experience/domain/location)
      - is_scored: bool          (True if a real /score run has been done)

    Title-only rows (from the hourly scan-apis monitor) have notes like:
        "Title Fit: 100. Via API scan."
    Corpus-scored rows (from /score) have notes like:
        "Fit: 82% (Strong Fit). Skills: 30/35, Exp: 23/25, Domain: 22/25, Location: 10/15. ..."
    """
    result = {
        "score_type": "unknown",
        "total": fit_score,
        "verdict": None,
        "source": None,
        "archetype": None,
        "breakdown": None,
        "is_scored": False,
    }
    if not notes:
        return result

    notes_text = notes.strip()

    m = _RE_CORPUS_NOTES.match(notes_text)
    if m:
        total = int(m.group(1))
        verdict = m.group(2).strip()
        archetype = m.group(3).strip() if m.group(3) else None
        skills = (int(m.group(4)), int(m.group(5)))
        experience = (int(m.group(6)), int(m.group(7)))
        domain = (int(m.group(8)), int(m.group(9)))
        location = (int(m.group(10)), int(m.group(11)))
        source = m.group(12).strip() or None
        result.update({
            "score_type": "corpus",
            "total": total,
            "verdict": verdict,
            "archetype": archetype,
            "breakdown": {
                "skills":     {"score": skills[0],     "max": skills[1],     "weight_pct": 35},
                "experience": {"score": experience[0], "max": experience[1], "weight_pct": 25},
                "domain":     {"score": domain[0],     "max": domain[1],     "weight_pct": 25},
                "location":   {"score": location[0],   "max": location[1],   "weight_pct": 15},
            },
            "source": source,
            "is_scored": True,
        })
        return result

    m = _RE_TITLE_NOTES.match(notes_text)
    if m:
        total = int(m.group(1))
        source = m.group(2).strip() or None
        result.update({
            "score_type": "title",
            "total": total,
            "source": source,
            "is_scored": False,
        })
        return result

    # Unknown format — treat as scored if notes is non-empty and doesn't
    # start with "Title Fit:" (matches the bot's own heuristic)
    result["is_scored"] = not notes_text.startswith("Title Fit:")
    return result


def get_prospects_from_db(unapplied_only=False, include_stale=False):
    """Get prospects from applications table (status='prospect').

    Sorted by most recently updated first so the latest /score run
    surfaces at the top. Each row is decorated with:
      - classify_score() results (score_type, verdict, breakdown, ...)
      - resume info (resume_filename, resume_variant, resume_rj_score) via
        LEFT JOIN to the resumes table when applications.resume_id is set

    The 'archived' filter corresponds to status='stale'. The 'all' filter
    returns active prospects only (no time cutoff — we want the latest
    corpus-scored item to show even if the original title-fit row is old).
    """
    import sqlite3
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    base_query = """
        SELECT
            a.*,
            r.filename    AS resume_filename,
            r.filepath    AS resume_filepath,
            r.variant     AS resume_variant,
            r.rj_score    AS resume_rj_score,
            r.created_at  AS resume_created_at
        FROM applications a
        LEFT JOIN resumes r ON a.resume_id = r.id
        WHERE a.status {status_filter}
        ORDER BY COALESCE(a.updated_at, a.created_at) DESC
    """
    if include_stale:
        query = base_query.format(status_filter="IN ('prospect', 'stale')")
    else:
        query = base_query.format(status_filter="= 'prospect'")

    cursor.execute(query)
    rows = []
    for row in cursor.fetchall():
        r = dict(row)
        # Map applications fields to prospect template fields
        r['role'] = r.get('position', '')
        r['date_added'] = r.get('created_at', '')
        r['url'] = r.get('job_url', '')
        # Attach structured score info so templates can render Title vs Corpus
        r['score_info'] = classify_score(r.get('notes', ''), r.get('fit_score'))
        rows.append(r)

    # Also include legacy prospects table if it exists
    # (legacy schema uses date_added/date_applied instead of created_at/updated_at)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='prospects'")
    if cursor.fetchone():
        cursor.execute("SELECT * FROM prospects ORDER BY date_added DESC")
        for row in cursor.fetchall():
            r = dict(row)
            r['score_info'] = classify_score(r.get('notes', ''), r.get('fit_score'))
            rows.append(r)

    # Re-sort merged list by most recent timestamp (updated_at for the
    # main applications table, date_added for legacy prospects)
    def _sort_key(x: dict) -> str:
        return (
            x.get('updated_at')
            or x.get('created_at')
            or x.get('date_added')
            or ''
        )
    rows.sort(key=_sort_key, reverse=True)

    conn.close()
    return rows


def get_stale_prospects_count():
    """Count archived prospects (status='stale' or prospect older than 7 days)."""
    import sqlite3
    if not DB_PATH.exists():
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM applications
        WHERE status = 'stale'
           OR (status = 'prospect' AND created_at < datetime('now', '-7 days'))
    """)
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_applications_from_csv():
    """Get applications from CSV file (fallback/supplement to DB)."""
    import csv
    csv_path = JJ_HOME / "applications.csv"
    if not csv_path.exists():
        # Also check ~/.job-apply for legacy
        csv_path = Path.home() / ".job-apply" / "applications.csv"
        if not csv_path.exists():
            return []

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        return list(reader)


def get_recent_activity(limit: int = 10):
    """Get recent activity for dashboard."""
    activities = []

    # Get recent applications
    apps = get_applications()[:limit]
    for app in apps:
        activities.append({
            "type": "application",
            "company": app.get("company"),
            "position": app.get("position"),
            "status": app.get("status"),
            "date": app.get("applied_at") or app.get("created_at"),
        })

    return activities[:limit]


def get_application_counts():
    """Get counts by status for dashboard."""
    apps = get_applications()
    counts = {
        "applied": 0,
        "recruiter_screen": 0,
        "screening": 0,  # Legacy, maps to recruiter_screen
        "hiring_manager": 0,
        "interview": 0,
        "technical": 0,
        "offer": 0,
        "accepted": 0,
        "rejected": 0,
        "withdrawn": 0,
        "total": len(apps),
    }

    for app in apps:
        status = app.get("status", "applied")
        if status in counts:
            counts[status] += 1
        # Map legacy 'screening' to recruiter_screen count
        if status == 'screening':
            counts['recruiter_screen'] += 1

    return counts


def get_email_stats():
    """Get email confirmation, update stats, and pairing stats."""
    import sqlite3
    if not DB_PATH.exists():
        return {
            "confirmed": 0, "unconfirmed": 0, "with_updates": 0, "last_check": None,
            "pairing": {"total": 0, "resolved": 0, "confirmed": 0, "ghosted": 0, "pending": 0, "unconfirmed": 0}
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Count confirmed
    cursor.execute("SELECT COUNT(*) FROM applications WHERE email_confirmed = 1")
    confirmed = cursor.fetchone()[0]

    # Count unconfirmed (applied status only)
    cursor.execute("""
        SELECT COUNT(*) FROM applications
        WHERE status = 'applied' AND (email_confirmed = 0 OR email_confirmed IS NULL)
    """)
    unconfirmed = cursor.fetchone()[0]

    # Count with updates
    cursor.execute("SELECT COUNT(*) FROM applications WHERE latest_update_type IS NOT NULL")
    with_updates = cursor.fetchone()[0]

    # Last check time
    cursor.execute("SELECT MAX(last_email_check) FROM applications")
    last_check = cursor.fetchone()[0]

    # Get recent updates
    cursor.execute("""
        SELECT company, position, latest_update_type, latest_update_at, latest_update_subject
        FROM applications
        WHERE latest_update_type IS NOT NULL
        ORDER BY latest_update_at DESC
        LIMIT 5
    """)
    recent_updates = [dict(row) for row in cursor.fetchall()]

    conn.close()

    # Get pairing stats from the new system
    pairing = get_pairing_stats()

    return {
        "confirmed": confirmed,
        "unconfirmed": unconfirmed,
        "with_updates": with_updates,
        "last_check": last_check,
        "recent_updates": recent_updates,
        "pairing": pairing,
    }


def get_db_tables():
    """Get list of all database tables and their row counts."""
    import sqlite3
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = []
    for row in cursor.fetchall():
        table_name = row[0]
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        tables.append({"name": table_name, "count": count})

    conn.close()
    return tables


def get_table_data(table_name: str, limit: int = 100, offset: int = 0):
    """Get data from a specific table."""
    import sqlite3
    if not DB_PATH.exists():
        return [], []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get column names
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]

    # Get data
    cursor.execute(f"SELECT * FROM {table_name} LIMIT ? OFFSET ?", (limit, offset))
    rows = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return columns, rows


# --------------------------------------------------------------------------
# Geo helper functions
# --------------------------------------------------------------------------

def _get_geo_areas() -> list[dict]:
    """Get all geo areas, seeding built-ins if needed."""
    import json as json_module
    import sqlite3
    from datetime import datetime
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='geo_areas'")
    if not cursor.fetchone():
        conn.close()
        return []

    # Check if we need to seed built-in areas
    cursor.execute("SELECT COUNT(*) FROM geo_areas WHERE is_builtin = 1")
    if cursor.fetchone()[0] == 0:
        for name, data in AREAS.items():
            cursor.execute("""
                INSERT OR IGNORE INTO geo_areas (name, latitude, longitude, radius, is_builtin, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
            """, (name, data["lat"], data["lng"], data["radius"], datetime.now().isoformat()))
        conn.commit()

    cursor.execute("SELECT * FROM geo_areas ORDER BY is_builtin DESC, name")
    areas = []
    for row in cursor.fetchall():
        area = dict(row)
        # Parse points JSON if present
        if area.get("points"):
            area["points"] = json_module.loads(area["points"])
        areas.append(area)
    conn.close()
    return areas


def _get_geo_area_by_id(area_id: int) -> dict | None:
    """Get a single geo area by ID."""
    import sqlite3
    if not DB_PATH.exists():
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM geo_areas WHERE id = ?", (area_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        area = dict(row)
        # Keep points as JSON string for discovery (it re-parses)
        return area
    return None


def _create_geo_area(name: str, lat: float, lng: float, radius: int) -> int:
    """Create a custom geo area."""
    import sqlite3
    from datetime import datetime
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO geo_areas (name, latitude, longitude, radius, is_builtin, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
    """, (name, lat, lng, radius, datetime.now().isoformat()))
    conn.commit()
    area_id = cursor.lastrowid
    conn.close()
    return area_id


def _delete_geo_area(area_id: int) -> bool:
    """Delete a custom geo area (only non-builtin)."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM geo_areas WHERE id = ? AND is_builtin = 0", (area_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def _create_corridor(name: str, lat: float, lng: float, radius: int, points: list) -> int:
    """Create a corridor area with multiple points."""
    import json as json_module
    import sqlite3
    from datetime import datetime
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO geo_areas (name, latitude, longitude, radius, is_builtin, points, created_at)
        VALUES (?, ?, ?, ?, 0, ?, ?)
    """, (name, lat, lng, radius, json_module.dumps(points), datetime.now().isoformat()))
    conn.commit()
    area_id = cursor.lastrowid
    conn.close()
    return area_id


def _update_area_stats(area_id: int, company_count: int):
    """Update area discovery stats."""
    import sqlite3
    from datetime import datetime
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE geo_areas SET company_count = ?, last_discovered_at = ? WHERE id = ?
    """, (company_count, datetime.now().isoformat(), area_id))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Page routes
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    stats = get_stats()
    profile = load_profile()
    counts = get_application_counts()
    prospects = get_prospects_from_db(unapplied_only=True)[:5]  # Top 5 unapplied prospects
    activity = get_recent_activity(5)
    pipeline = get_pipeline_stats()
    stale = get_stale_applications(days_threshold=7)
    email_stats = get_email_stats()

    # Today's Focus data
    focus = get_todays_focus()
    focus_counts = get_focus_counts()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "profile": profile,
        "counts": counts,
        "prospects": prospects,
        "activity": activity,
        "pipeline": pipeline,
        "stale": stale,
        "email_stats": email_stats,
        "focus": focus,
        "focus_counts": focus_counts,
    })


@app.get("/applications", response_class=HTMLResponse)
async def applications_page(request: Request, status: str = None, pairing: str = None):
    """Applications tracker page."""
    # If filtering by pairing status, use the new pairing function
    if pairing:
        apps = get_applications_with_pairing_status(status_filter=pairing, include_resolved=True)
    else:
        # Try database first, fall back to CSV
        apps = get_applications(status)
        if not apps:
            apps = get_applications_from_csv()
            if status:
                apps = [a for a in apps if a.get("status") == status]

        # Add pairing status to each app
        apps_with_pairing = get_applications_with_pairing_status(include_resolved=True)
        pairing_map = {a['id']: a for a in apps_with_pairing}
        for app in apps:
            paired = pairing_map.get(app.get('id'), {})
            app['computed_pairing_status'] = paired.get('computed_pairing_status', 'unknown')
            app['computed_days_waiting'] = paired.get('computed_days_waiting', 0)
            app['confirmation_date'] = paired.get('confirmation_date')
            app['resolution_date'] = paired.get('resolution_date')
            app['latest_resolution_type'] = paired.get('latest_resolution_type')

    counts = get_application_counts()
    pairing_stats = get_pairing_stats()

    return templates.TemplateResponse("applications.html", {
        "request": request,
        "applications": apps,
        "counts": counts,
        "current_status": status,
        "current_pairing": pairing,
        "pairing_stats": pairing_stats,
    })


@app.get("/email-activity", response_class=HTMLResponse)
async def email_activity_page(request: Request, days: int = 30):
    """Email sync activity feed — shows discovered emails grouped by day."""
    from itertools import groupby
    from jj.db import get_email_sync_feed

    feed = get_email_sync_feed(days=days)

    # Group by discovery date (created_at day)
    def day_key(item):
        return (item.get("created_at") or "")[:10]

    days_grouped = []
    for day, items in groupby(feed, key=day_key):
        day_items = list(items)
        days_grouped.append({
            "date": day,
            "emails": day_items,
            "count": len(day_items),
        })

    return templates.TemplateResponse("email_activity.html", {
        "request": request,
        "days_grouped": days_grouped,
        "total_count": len(feed),
        "days_param": days,
    })


@app.get("/prospects/{app_id}", response_class=HTMLResponse)
async def prospect_detail_page(request: Request, app_id: int):
    """Per-prospect detail page with score breakdown, resume info, JD link."""
    import sqlite3
    if not DB_PATH.exists():
        return templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT
            a.*,
            r.filename   AS resume_filename,
            r.filepath   AS resume_filepath,
            r.variant    AS resume_variant,
            r.rj_score   AS resume_rj_score,
            r.jd_url     AS resume_jd_url,
            r.created_at AS resume_created_at
        FROM applications a
        LEFT JOIN resumes r ON a.resume_id = r.id
        WHERE a.id = ?
        """,
        (app_id,),
    ).fetchone()

    if not row:
        conn.close()
        return templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404
        )

    prospect = dict(row)
    prospect["score_info"] = classify_score(
        prospect.get("notes", ""), prospect.get("fit_score")
    )

    # If the WIP /score has written an evaluation_reports row, prefer it
    # over the notes-parsed breakdown (it's the source of truth).
    report_row = conn.execute(
        """
        SELECT * FROM evaluation_reports
        WHERE application_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (app_id,),
    ).fetchone()
    conn.close()

    evaluation_report = dict(report_row) if report_row else None

    return templates.TemplateResponse(
        "prospect_detail.html",
        {
            "request": request,
            "prospect": prospect,
            "evaluation_report": evaluation_report,
        },
    )


@app.get("/prospects", response_class=HTMLResponse)
async def prospects_page(request: Request, show: str = "active"):
    """Prospects board page."""
    if show == "archived":
        all_p = get_prospects_from_db(include_stale=True)
        active_p = get_prospects_from_db(include_stale=False)
        active_ids = {p.get('id') for p in active_p}
        prospects = [p for p in all_p if p.get('id') not in active_ids]
    elif show == "all":
        prospects = get_prospects_from_db(include_stale=True)
    else:
        # Default: active (non-stale) prospects
        prospects = get_prospects_from_db(include_stale=False)

    # Counts
    active_count = len(get_prospects_from_db(include_stale=False))
    stale_count = get_stale_prospects_count()
    total_count = active_count + stale_count

    return templates.TemplateResponse("prospects.html", {
        "request": request,
        "prospects": prospects,
        "show": show,
        "active_count": active_count,
        "stale_count": stale_count,
        "total_count": total_count,
    })


@app.get("/companies", response_class=HTMLResponse)
async def companies_page(request: Request, filter: str = None):
    """Companies tracking page."""
    from jj.db import get_all_companies, get_companies_with_applications

    all_companies = get_all_companies()
    companies_with_apps = get_companies_with_applications()

    # Build a lookup for application counts
    app_counts = {c['id']: c for c in companies_with_apps}

    # Merge counts into all companies
    for company in all_companies:
        if company['id'] in app_counts:
            company['application_count'] = app_counts[company['id']]['application_count']
            company['active_count'] = app_counts[company['id']]['active_count']
            company['latest_applied_at'] = app_counts[company['id']]['latest_applied_at']
        else:
            company['application_count'] = 0
            company['active_count'] = 0
            company['latest_applied_at'] = None

    # Filter if requested
    show_with_apps = filter == 'with_apps'
    if show_with_apps:
        companies = [c for c in all_companies if c['application_count'] > 0]
    else:
        companies = all_companies

    # Sort by application count desc, then name
    companies.sort(key=lambda c: (-c['application_count'], c['name'].lower()))

    # Stats
    multi_app = [c for c in all_companies if c['application_count'] > 1]

    return templates.TemplateResponse("companies.html", {
        "request": request,
        "companies": companies,
        "total_count": len(all_companies),
        "with_apps_count": len(companies_with_apps),
        "multi_app_count": len(multi_app),
        "show_with_apps": show_with_apps,
    })


@app.get("/corpus", response_class=HTMLResponse)
async def corpus_page(request: Request):
    """Corpus browser page."""
    roles = get_roles()
    stats = get_stats()

    # Load corpus markdown if it exists
    corpus_text = ""
    if CORPUS_PATH.exists():
        corpus_text = CORPUS_PATH.read_text()

    # Get entries for each role
    roles_with_entries = []
    for role in roles:
        entries = get_entries_for_role(role["id"])
        roles_with_entries.append({
            **role,
            "entries": entries,
            "entry_count": len(entries),
        })

    return templates.TemplateResponse("corpus.html", {
        "request": request,
        "roles": roles_with_entries,
        "stats": stats,
        "corpus_text": corpus_text,
    })


@app.get("/corpus/role/{role_id}", response_class=HTMLResponse)
async def role_detail_page(request: Request, role_id: int):
    """Role detail page with entries."""
    from jj.db import get_role

    role = get_role(role_id)
    if not role:
        return templates.TemplateResponse("404.html", {
            "request": request,
            "message": "Role not found",
        }, status_code=404)

    entries = get_entries_for_role(role_id)

    return templates.TemplateResponse("role_detail.html", {
        "request": request,
        "role": role,
        "entries": entries,
    })


@app.get("/map", response_class=HTMLResponse)
async def map_page(request: Request):
    """Interactive map for geo-targeted job discovery."""
    areas = _get_geo_areas()
    companies = get_all_companies()

    return templates.TemplateResponse("map.html", {
        "request": request,
        "areas": areas,
        "companies": companies,
        "default_center": {"lat": 30.2672, "lng": -97.7431},  # Austin
        "default_zoom": 11,
    })


@app.get("/db", response_class=HTMLResponse)
async def db_viewer_page(request: Request, table: str = None, limit: int = 100, offset: int = 0):
    """Simple database viewer page."""
    tables = get_db_tables()
    columns = []
    rows = []
    total_count = 0

    if table:
        columns, rows = get_table_data(table, limit=limit, offset=offset)
        # Get total count for pagination
        for t in tables:
            if t["name"] == table:
                total_count = t["count"]
                break

    return templates.TemplateResponse("db_viewer.html", {
        "request": request,
        "tables": tables,
        "current_table": table,
        "columns": columns,
        "rows": rows,
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
    })


# --------------------------------------------------------------------------
# API routes (for htmx partial updates)
# --------------------------------------------------------------------------

@app.get("/api/stats")
async def api_stats():
    """Get corpus statistics."""
    return get_stats()


@app.get("/api/applications")
async def api_applications(status: str = None):
    """Get applications list."""
    return get_applications(status)


@app.get("/api/prospects")
async def api_prospects(include_stale: bool = False):
    """Get prospects list."""
    return get_prospects_from_db(include_stale=include_stale)


@app.post("/api/prospects/{app_id}/archive")
async def api_archive_prospect(app_id: int):
    """Archive a prospect by setting status to 'stale'."""
    from jj.db import update_application
    success = update_application(app_id, status="stale")
    if success:
        return {"ok": True}
    return JSONResponse(status_code=404, content={"error": "Not found"})


@app.post("/api/prospects/{app_id}/applied")
async def api_mark_applied(app_id: int):
    """Mark a prospect as applied."""
    from datetime import datetime
    from jj.db import update_application
    success = update_application(
        app_id,
        status="applied",
        applied_at=datetime.now().isoformat(),
    )
    if success:
        return {"ok": True}
    return JSONResponse(status_code=404, content={"error": "Not found"})


@app.get("/api/roles")
async def api_roles():
    """Get all roles."""
    return get_roles()


@app.get("/api/roles/{role_id}/entries")
async def api_role_entries(role_id: int):
    """Get entries for a role."""
    return get_entries_for_role(role_id)


@app.get("/api/skills")
async def api_skills():
    """Get all skills."""
    return get_skills()


# --------------------------------------------------------------------------
# Geo API routes
# --------------------------------------------------------------------------

@app.get("/api/geo/areas")
async def api_geo_areas():
    """Get all geographic search areas."""
    return _get_geo_areas()


@app.post("/api/geo/areas")
async def api_create_geo_area(request: Request):
    """Create a new custom search area."""
    form = await request.form()
    name = form.get("name")
    latitude = float(form.get("latitude"))
    longitude = float(form.get("longitude"))
    radius = int(form.get("radius"))

    area_id = _create_geo_area(name, latitude, longitude, radius)
    return {"id": area_id, "status": "created"}


@app.delete("/api/geo/areas/{area_id}")
async def api_delete_geo_area(area_id: int):
    """Delete a custom search area."""
    deleted = _delete_geo_area(area_id)
    if deleted:
        return {"status": "deleted"}
    return {"status": "not_found_or_builtin"}


@app.post("/api/geo/corridors")
async def api_create_corridor(request: Request):
    """Create a corridor (multiple points as single area)."""
    import json as json_module
    form = await request.form()
    name = form.get("name")
    radius = int(form.get("radius"))
    points_json = form.get("points")  # JSON array of {lat, lng}

    points = json_module.loads(points_json)
    if not points:
        return {"status": "error", "message": "No points provided"}

    # Use first point as the "center" for display, store all points
    first = points[0]
    area_id = _create_corridor(name, first["lat"], first["lng"], radius, points)
    return {"id": area_id, "status": "created"}


@app.get("/api/geo/companies")
async def api_geo_companies():
    """Get all discovered companies with coordinates."""
    return get_all_companies()


@app.post("/api/geo/discover/{area_id}", response_class=HTMLResponse)
async def api_trigger_discovery(request: Request, area_id: int):
    """Trigger company discovery for an area (HTMX partial response)."""
    import json as json_module
    area = _get_geo_area_by_id(area_id)
    if not area:
        return HTMLResponse("<div class='error'>Area not found</div>", status_code=404)

    # Check if this is a corridor (has multiple points)
    points_json = area.get("points")
    all_companies = []

    if points_json:
        # Corridor: search each point
        points = json_module.loads(points_json)
        for point in points:
            point_area = {
                "latitude": point["lat"],
                "longitude": point["lng"],
                "radius": area["radius"]
            }
            companies = discover_companies_for_area(point_area)
            all_companies.extend(companies)
        # Dedupe by place_id
        seen = set()
        unique = []
        for c in all_companies:
            if c.place_id not in seen:
                seen.add(c.place_id)
                unique.append(c)
        all_companies = unique
    else:
        # Single point area
        all_companies = discover_companies_for_area(area)

    added = save_companies(all_companies)

    # Update area stats
    _update_area_stats(area_id, len(all_companies))

    # Return HTMX partial with results
    return templates.TemplateResponse("partials/discovery_result.html", {
        "request": request,
        "area": area,
        "found": len(all_companies),
        "added": added,
    })


@app.post("/api/geo/enrich/{area_id}", response_class=HTMLResponse)
async def api_enrich_area(request: Request, area_id: int):
    """Run enrichment pipeline for companies in an area (HTMX partial response)."""
    area = _get_geo_area_by_id(area_id)
    if not area:
        return HTMLResponse("<div class='error'>Area not found</div>", status_code=404)

    # Run the enrichment pipeline
    stats = run_enrichment_pipeline(area_id)

    # Return HTMX partial with results
    return templates.TemplateResponse("partials/enrichment_result.html", {
        "request": request,
        "area": area,
        "stats": stats,
    })


# --------------------------------------------------------------------------
# Analytics routes
# --------------------------------------------------------------------------

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Analytics dashboard page."""
    analytics = get_all_analytics()

    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "analytics": analytics,
    })


@app.get("/api/analytics")
async def api_analytics():
    """Get all analytics data."""
    return get_all_analytics()


@app.get("/api/analytics/funnel")
async def api_funnel():
    """Get funnel statistics."""
    return get_funnel_stats()


@app.get("/api/analytics/weekly")
async def api_weekly():
    """Get weekly summary."""
    return get_weekly_summary()


# --------------------------------------------------------------------------
# Quick Actions API
# --------------------------------------------------------------------------

@app.post("/api/applications/{app_id}/status")
async def update_application_status(
    app_id: int,
    status: str = Form(...),
    reason: str = Form(None),
):
    """Update application status via quick action."""
    from jj.db import ALL_STATUSES, transition_application_status

    valid_statuses = list(ALL_STATUSES) + ['skipped', 'screening']  # Include legacy
    if status not in valid_statuses:
        return JSONResponse(
            {"error": f"Invalid status. Must be one of: {valid_statuses}"},
            status_code=400
        )

    # Get current state
    app = get_application(app_id)
    if not app:
        return JSONResponse({"error": "Application not found"}, status_code=404)

    old_status = app.get('status')

    # Use transition function to update status and log event atomically
    success = transition_application_status(
        app_id,
        status,
        reason=reason or "Manual update via dashboard",
        source='web'
    )

    if success:
        return {"success": True, "old_status": old_status, "new_status": status}
    else:
        return JSONResponse({"error": "Failed to update"}, status_code=500)


@app.post("/api/applications/{app_id}/archive")
async def archive_application(app_id: int):
    """Archive (skip) an application."""
    app = get_application(app_id)
    if not app:
        return JSONResponse({"error": "Application not found"}, status_code=404)

    old_status = app.get('status')
    success = update_application(app_id, status='skipped')

    if success:
        log_event(
            'application_archived',
            entity_type='application',
            entity_id=app_id,
            old_value={'status': old_status},
            new_value={'status': 'skipped'},
        )
        return {"success": True}
    return JSONResponse({"error": "Failed to archive"}, status_code=500)


@app.post("/api/applications/{app_id}/notes")
async def update_application_notes(
    app_id: int,
    notes: str = Form(...),
):
    """Update application notes."""
    success = update_application(app_id, notes=notes)
    if success:
        return {"success": True}
    return JSONResponse({"error": "Failed to update notes"}, status_code=500)


@app.get("/api/applications/{app_id}")
async def api_get_application(app_id: int):
    """Get a single application."""
    app = get_application(app_id)
    if app:
        return app
    return JSONResponse({"error": "Application not found"}, status_code=404)


# --------------------------------------------------------------------------
# Today's Focus API
# --------------------------------------------------------------------------

@app.get("/api/focus")
async def api_focus():
    """Get Today's Focus data."""
    return {
        "focus": get_todays_focus(),
        "counts": get_focus_counts(),
    }


@app.get("/api/focus/partial", response_class=HTMLResponse)
async def api_focus_partial(request: Request):
    """Get Today's Focus as HTMX partial."""
    focus = get_todays_focus()
    focus_counts = get_focus_counts()

    return templates.TemplateResponse("partials/todays_focus.html", {
        "request": request,
        "focus": focus,
        "focus_counts": focus_counts,
    })


# --------------------------------------------------------------------------
# Worker/Task API
# --------------------------------------------------------------------------

@app.get("/api/tasks")
async def api_tasks():
    """Get recent tasks."""
    return {
        "tasks": get_recent_tasks(limit=20),
        "stats": get_task_stats(),
    }


@app.post("/api/tasks/email-sync")
async def trigger_email_sync():
    """Trigger an email sync task."""
    task_id = create_task('email_sync', priority=10)
    return {"task_id": task_id, "status": "queued"}


# --------------------------------------------------------------------------
# Server-Sent Events for real-time updates
# --------------------------------------------------------------------------

async def event_generator() -> AsyncGenerator[str, None]:
    """Generate SSE events for real-time dashboard updates."""
    while True:
        # Send focus counts every 30 seconds
        try:
            counts = get_focus_counts()
            data = json.dumps({"type": "focus_update", "counts": counts})
            yield f"data: {data}\n\n"
        except Exception:
            pass

        await asyncio.sleep(30)


@app.get("/api/events")
async def sse_events():
    """Server-Sent Events endpoint for real-time updates."""
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# --------------------------------------------------------------------------
# Resumes routes
# --------------------------------------------------------------------------

def extract_vc_board(notes: str | None) -> str:
    """Extract VC/investor board name from notes field."""
    if not notes:
        return ""
    # Try [VC Board: NAME] pattern first
    match = re.search(r'\[VC Board:\s*(.+?)\]', notes)
    if match:
        return match.group(1)
    # Try "Fund portfolio" pattern (e.g. "a16z portfolio", "Sequoia portfolio")
    match = re.search(r'(\w[\w\s]*?)\s+portfolio\b', notes, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


@app.get("/resumes", response_class=HTMLResponse)
async def resumes_page(request: Request, days: int = 30):
    """Resumes dashboard - generated resumes with application data."""
    rows = get_resumes_with_applications(days=days)

    # Enrich rows and group by date
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        row["vc_board"] = extract_vc_board(row.get("notes"))
        rj_before = row.get("rj_before")
        rj_after = row.get("rj_after")
        if rj_before is not None and rj_after is not None:
            row["delta"] = rj_after - rj_before
        else:
            row["delta"] = None

        if row.get("google_doc_id"):
            row["doc_url"] = f"https://docs.google.com/document/d/{row['google_doc_id']}/edit"
        else:
            row["doc_url"] = None

        date_key = row["created_at"][:10] if row.get("created_at") else "Unknown"
        grouped.setdefault(date_key, []).append(row)

    return templates.TemplateResponse("resumes.html", {
        "request": request,
        "grouped_resumes": grouped,
        "days": days,
        "total_count": len(rows),
    })


# --------------------------------------------------------------------------
# TWC (Texas Workforce Commission) routes
# --------------------------------------------------------------------------

@app.get("/twc", response_class=HTMLResponse)
async def twc_page(request: Request):
    """TWC Work Search Activity Log - all claim periods."""
    claim_periods = get_all_twc_claim_periods()
    return templates.TemplateResponse("twc.html", {
        "request": request,
        "claim_periods": claim_periods,
    })


@app.get("/twc/week/{week_start}", response_class=HTMLResponse)
async def twc_week_detail(request: Request, week_start: str):
    """TWC weekly detail view - activities by day with edit forms."""
    from datetime import datetime, timedelta

    sunday, saturday = get_twc_week_boundaries(week_start)
    week_start_dt = datetime.strptime(sunday, "%Y-%m-%d")

    prev_week = (week_start_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    next_week = (week_start_dt + timedelta(days=7)).strftime("%Y-%m-%d")

    today = datetime.now()
    is_current_week = week_start_dt <= today <= (week_start_dt + timedelta(days=6))
    is_future_week = week_start_dt > today

    activities = get_twc_activities_for_week(sunday)
    summary = get_twc_week_summary(sunday)

    days_of_week = []
    for i in range(7):
        day_date = week_start_dt + timedelta(days=i)
        day_str = day_date.strftime("%Y-%m-%d")
        day_activities = [a for a in activities if (a.get('effective_date') or a.get('activity_date', '')[:10]) == day_str]
        days_of_week.append({
            'date': day_str,
            'day_name': day_date.strftime("%A"),
            'display_date': day_date.strftime("%b %d"),
            'activities': day_activities,
        })

    return templates.TemplateResponse("twc_detail.html", {
        "request": request,
        "week_start": sunday,
        "week_end": saturday,
        "week_display": f"{week_start_dt.strftime('%b %d')} - {datetime.strptime(saturday, '%Y-%m-%d').strftime('%b %d, %Y')}",
        "prev_week": prev_week,
        "next_week": next_week,
        "is_current_week": is_current_week,
        "is_future_week": is_future_week,
        "days_of_week": days_of_week,
        "summary": summary,
        "activity_types": get_twc_activity_types(),
        "result_types": get_twc_result_types(),
    })


@app.get("/twc/print", response_class=HTMLResponse)
async def twc_print_page(request: Request, week: str = None):
    """Printable TWC Work Search Activity Log."""
    from datetime import datetime, timedelta

    sunday, saturday = get_twc_week_boundaries(week)
    week_start = datetime.strptime(sunday, "%Y-%m-%d")

    activities = get_twc_activities_for_week(week)
    summary = get_twc_week_summary(week)

    # Group activities by day
    days_of_week = []
    for i in range(7):
        day_date = week_start + timedelta(days=i)
        day_str = day_date.strftime("%Y-%m-%d")
        day_activities = [a for a in activities if (a.get('effective_date') or a.get('activity_date', '')[:10]) == day_str]
        days_of_week.append({
            'date': day_str,
            'day_name': day_date.strftime("%A"),
            'display_date': day_date.strftime("%b %d"),
            'activities': day_activities,
        })

    return templates.TemplateResponse("twc_print.html", {
        "request": request,
        "week_start": sunday,
        "week_end": saturday,
        "week_display": f"{week_start.strftime('%b %d')} - {datetime.strptime(saturday, '%Y-%m-%d').strftime('%b %d, %Y')}",
        "days_of_week": days_of_week,
        "summary": summary,
        "activities": activities,
    })


@app.get("/api/twc/week", response_class=HTMLResponse)
async def api_twc_week_partial(request: Request, week: str = None):
    """Get TWC activities for a week as HTMX partial."""
    from datetime import datetime, timedelta

    sunday, saturday = get_twc_week_boundaries(week)
    week_start = datetime.strptime(sunday, "%Y-%m-%d")

    activities = get_twc_activities_for_week(week)
    summary = get_twc_week_summary(week)

    # Group activities by day
    days_of_week = []
    for i in range(7):
        day_date = week_start + timedelta(days=i)
        day_str = day_date.strftime("%Y-%m-%d")
        day_activities = [a for a in activities if (a.get('effective_date') or a.get('activity_date', '')[:10]) == day_str]
        days_of_week.append({
            'date': day_str,
            'day_name': day_date.strftime("%A"),
            'display_date': day_date.strftime("%b %d"),
            'activities': day_activities,
        })

    return templates.TemplateResponse("partials/twc_week_view.html", {
        "request": request,
        "days_of_week": days_of_week,
        "summary": summary,
    })


@app.post("/api/twc/{app_id}")
async def api_update_twc_fields(
    app_id: int,
    twc_activity_type: str = Form(None),
    twc_result: str = Form(None),
    twc_result_other: str = Form(None),
    hired_start_date: str = Form(None),
    activity_date: str = Form(None),
    employer_phone: str = Form(None),
    employer_address: str = Form(None),
    employer_city: str = Form(None),
    employer_state: str = Form(None),
    employer_zip: str = Form(None),
    contact_name: str = Form(None),
    contact_email: str = Form(None),
    contact_fax: str = Form(None),
):
    """Update TWC-specific fields for an application."""
    # Build kwargs from non-None values
    updates = {}
    if twc_activity_type is not None:
        updates['twc_activity_type'] = twc_activity_type
    if twc_result is not None:
        updates['twc_result'] = twc_result
    if twc_result_other is not None:
        updates['twc_result_other'] = twc_result_other
    if hired_start_date is not None:
        updates['hired_start_date'] = hired_start_date
    if activity_date is not None:
        updates['activity_date'] = activity_date
    if employer_phone is not None:
        updates['employer_phone'] = employer_phone
    if employer_address is not None:
        updates['employer_address'] = employer_address
    if employer_city is not None:
        updates['employer_city'] = employer_city
    if employer_state is not None:
        updates['employer_state'] = employer_state
    if employer_zip is not None:
        updates['employer_zip'] = employer_zip
    if contact_name is not None:
        updates['contact_name'] = contact_name
    if contact_email is not None:
        updates['contact_email'] = contact_email
    if contact_fax is not None:
        updates['contact_fax'] = contact_fax

    if not updates:
        return JSONResponse({"error": "No fields to update"}, status_code=400)

    success = update_twc_fields(app_id, **updates)
    if success:
        return {"success": True, "updated_fields": list(updates.keys())}
    return JSONResponse({"error": "Failed to update"}, status_code=500)


@app.post("/api/twc/backfill")
async def api_twc_backfill():
    """Backfill activity_date from applied_at for existing applications."""
    count = backfill_activity_dates()
    return {"success": True, "records_updated": count}


@app.get("/api/twc/summary")
async def api_twc_summary(week: str = None):
    """Get TWC week summary as JSON."""
    return get_twc_week_summary(week)


@app.post("/api/twc/payment/{week_start}")
async def api_twc_payment(week_start: str, request: Request):
    """Toggle TWC payment request submission status for a week."""
    form = await request.form()
    submitted = form.get("submitted") == "true"
    summary = get_twc_week_summary(week_start)
    mark_twc_payment_submitted(week_start, submitted, summary['total_activities'])
    return {"ok": True, "submitted": submitted}


# --------------------------------------------------------------------------
# Health check
# --------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "jj_home": str(JJ_HOME), "initialized": JJ_HOME.exists()}
