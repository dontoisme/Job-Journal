"""Job Journal Web Dashboard - FastAPI Application."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jj.config import JJ_HOME, load_profile, CORPUS_PATH
from jj.db import (
    get_stats, get_roles, get_applications, get_application, get_entries_for_role,
    get_skills, DB_PATH, get_pipeline_stats, get_stale_applications, get_connection,
    update_application, get_todays_focus, get_focus_counts, log_event,
    create_task, get_recent_tasks, get_task_stats,
)
from jj.geo import AREAS, get_all_companies, discover_companies_for_area, save_companies, run_enrichment_pipeline
from jj.analytics import get_all_analytics, get_funnel_stats, get_weekly_summary

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
import json

def parse_tags(value):
    """Parse JSON tags string into a list."""
    if not value:
        return []
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value
    except:
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

def get_prospects_from_db(unapplied_only=False):
    """Get prospects from SQLite database."""
    import sqlite3
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check if prospects table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='prospects'")
    if not cursor.fetchone():
        conn.close()
        return []

    if unapplied_only:
        # Filter out prospects that have been applied to (case-insensitive)
        cursor.execute("""
            SELECT * FROM prospects
            WHERE date_applied IS NULL
              AND LOWER(company) NOT IN (SELECT LOWER(company) FROM applications)
            ORDER BY fit_score DESC
        """)
    else:
        cursor.execute("SELECT * FROM prospects ORDER BY fit_score DESC")

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


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
        "screening": 0,
        "interview": 0,
        "offer": 0,
        "rejected": 0,
        "total": len(apps),
    }

    for app in apps:
        status = app.get("status", "applied")
        if status in counts:
            counts[status] += 1

    return counts


def get_email_stats():
    """Get email confirmation and update stats."""
    import sqlite3
    if not DB_PATH.exists():
        return {"confirmed": 0, "unconfirmed": 0, "with_updates": 0, "last_check": None}

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

    return {
        "confirmed": confirmed,
        "unconfirmed": unconfirmed,
        "with_updates": with_updates,
        "last_check": last_check,
        "recent_updates": recent_updates,
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
    import sqlite3
    import json as json_module
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
    import json as json_module
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
    import sqlite3
    import json as json_module
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
async def applications_page(request: Request, status: str = None):
    """Applications tracker page."""
    # Try database first, fall back to CSV
    apps = get_applications(status)
    if not apps:
        apps = get_applications_from_csv()
        if status:
            apps = [a for a in apps if a.get("status") == status]

    counts = get_application_counts()

    return templates.TemplateResponse("applications.html", {
        "request": request,
        "applications": apps,
        "counts": counts,
        "current_status": status,
    })


@app.get("/prospects", response_class=HTMLResponse)
async def prospects_page(request: Request, show: str = "unapplied"):
    """Prospects board page."""
    if show == "all":
        prospects = get_prospects_from_db(unapplied_only=False)
    else:
        prospects = get_prospects_from_db(unapplied_only=True)

    # Count totals
    all_prospects = get_prospects_from_db(unapplied_only=False)
    unapplied_count = len([p for p in all_prospects if not p.get('date_applied')])
    applied_count = len(all_prospects) - unapplied_count

    return templates.TemplateResponse("prospects.html", {
        "request": request,
        "prospects": prospects,
        "show": show,
        "unapplied_count": unapplied_count,
        "applied_count": applied_count,
        "total_count": len(all_prospects),
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
async def api_prospects():
    """Get prospects list."""
    return get_prospects_from_db()


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
    from fastapi import Form
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
):
    """Update application status via quick action."""
    valid_statuses = ['prospect', 'applied', 'screening', 'interview', 'offer', 'rejected', 'skipped']
    if status not in valid_statuses:
        return JSONResponse(
            {"error": f"Invalid status. Must be one of: {valid_statuses}"},
            status_code=400
        )

    # Get current state for logging
    app = get_application(app_id)
    if not app:
        return JSONResponse({"error": "Application not found"}, status_code=404)

    old_status = app.get('status')

    # Update the status
    success = update_application(app_id, status=status)

    if success:
        # Log the event
        log_event(
            'application_status_change',
            entity_type='application',
            entity_id=app_id,
            old_value={'status': old_status},
            new_value={'status': status},
        )
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
# Health check
# --------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "jj_home": str(JJ_HOME), "initialized": JJ_HOME.exists()}
