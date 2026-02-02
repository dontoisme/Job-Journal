"""Database operations for Job Journal."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from jj.config import DB_PATH, JJ_HOME

SCHEMA = """
-- Professional roles/positions
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    start_date TEXT,              -- YYYY-MM format
    end_date TEXT,                -- NULL = current
    is_current BOOLEAN DEFAULT 0,
    summary TEXT,                 -- High-level role summary
    tags TEXT,                    -- JSON array of tags
    interview_complete BOOLEAN DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Corpus entries (bullets + context)
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER REFERENCES roles(id),
    category TEXT,                -- 'achievement', 'responsibility', 'skill', 'story'
    text TEXT NOT NULL,           -- The bullet text
    context TEXT,                 -- Full story/context from interview
    tags TEXT,                    -- JSON array of tags
    metrics TEXT,                 -- JSON array of extracted metrics
    voice_sample BOOLEAN DEFAULT 0,  -- Good example of user's voice?
    times_used INTEGER DEFAULT 0,
    success_rate REAL,            -- Track which bullets lead to interviews
    interview_session_id INTEGER REFERENCES interview_sessions(id),
    source TEXT DEFAULT 'interview',  -- 'interview', 'import', 'manual'
    source_line INTEGER,          -- Line number if imported from base.md
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, text)
);

-- Skills and technologies
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    category TEXT,                -- 'technical', 'domain', 'leadership', 'tools'
    proficiency TEXT,             -- 'expert', 'proficient', 'familiar'
    evidence_entry_ids TEXT,      -- JSON array of entry IDs that demonstrate skill
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Education
CREATE TABLE IF NOT EXISTS education (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    degree TEXT,
    school TEXT,
    location TEXT,
    graduation_date TEXT,
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Interview sessions (for tracking progress)
CREATE TABLE IF NOT EXISTS interview_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_type TEXT,            -- 'onboarding', 'role_deep_dive', 'skill_audit'
    role_id INTEGER REFERENCES roles(id),
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    entries_added INTEGER DEFAULT 0,
    notes TEXT
);

-- Generated resumes
CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    variant TEXT,                     -- 'growth', 'ai-agentic', 'health-tech', etc.
    summary_text TEXT,                -- The composed summary (only part that's not verbatim)
    target_company TEXT,
    target_role TEXT,
    jd_url TEXT,
    rj_score INTEGER,                 -- Resume-JD match score
    drift_score INTEGER DEFAULT 0,    -- Deviation from corpus (should be 0)
    is_valid BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    validated_at TEXT
);

-- Resume-Entry junction (which bullets in which resume)
CREATE TABLE IF NOT EXISTS resume_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER NOT NULL,
    entry_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,         -- Which role this bullet appears under
    position INTEGER,                 -- Order within the role section
    FOREIGN KEY (resume_id) REFERENCES resumes(id),
    FOREIGN KEY (entry_id) REFERENCES entries(id),
    FOREIGN KEY (role_id) REFERENCES roles(id),
    UNIQUE(resume_id, entry_id)       -- Each entry only once per resume
);

-- Resume sections (skills, summary tracking)
CREATE TABLE IF NOT EXISTS resume_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER NOT NULL,
    section_type TEXT NOT NULL,       -- 'skills', 'summary'
    section_name TEXT,                -- e.g., 'Leadership', 'Growth & Experimentation'
    content TEXT NOT NULL,            -- The actual text
    position INTEGER,                 -- Order in resume
    FOREIGN KEY (resume_id) REFERENCES resumes(id)
);

-- Corpus improvement suggestions
CREATE TABLE IF NOT EXISTS corpus_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER,
    jd_url TEXT,
    gap_type TEXT,                    -- 'missing_theme', 'weak_coverage', 'variation_needed'
    theme TEXT,                       -- The JD requirement not well covered
    suggested_role_id INTEGER,        -- Which role could add this
    suggestion TEXT,                  -- Specific recommendation
    status TEXT DEFAULT 'pending',    -- 'pending', 'accepted', 'dismissed'
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (resume_id) REFERENCES resumes(id),
    FOREIGN KEY (suggested_role_id) REFERENCES roles(id)
);

-- JD analysis cache
CREATE TABLE IF NOT EXISTS jd_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    company TEXT,
    role TEXT,
    themes TEXT,                  -- JSON array
    keywords TEXT,                -- JSON array
    requirements TEXT,            -- JSON array
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Applications tracker
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    position TEXT,
    location TEXT,
    salary_range TEXT,
    ats_type TEXT,
    fit_score INTEGER,
    status TEXT DEFAULT 'prospect',  -- 'prospect', 'applied', 'screening', 'interview', 'offer', 'rejected'
    resume_id INTEGER REFERENCES resumes(id),
    job_url TEXT,
    rj_before INTEGER,
    rj_after INTEGER,
    applied_at TEXT,
    notes TEXT,
    -- Email tracking fields
    email_confirmed BOOLEAN DEFAULT 0,
    confirmed_at TEXT,               -- Date confirmation email received
    confirmation_email_id TEXT,      -- Gmail message ID
    latest_update_type TEXT,         -- 'interview', 'rejection', 'next_steps', 'assessment'
    latest_update_at TEXT,           -- Date of latest update email
    latest_update_subject TEXT,      -- Subject line of latest update
    latest_update_email_id TEXT,     -- Gmail message ID
    last_email_check TEXT,           -- When we last checked emails
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Geographic search areas for geo discovery
CREATE TABLE IF NOT EXISTS geo_areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    radius INTEGER NOT NULL,
    is_builtin BOOLEAN DEFAULT 0,
    points TEXT,                   -- JSON array of {lat, lng} for corridors
    last_discovered_at TEXT,
    company_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Discovered companies from geo search
CREATE TABLE IF NOT EXISTS geo_companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT,
    latitude REAL,
    longitude REAL,
    place_id TEXT UNIQUE,
    website TEXT,
    careers_url TEXT,
    job_count INTEGER DEFAULT 0,
    source TEXT DEFAULT 'google_maps',
    last_scraped TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Background task queue
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,           -- 'email_sync', 'job_monitor', 'workflow', etc.
    status TEXT DEFAULT 'pending',     -- 'pending', 'running', 'completed', 'failed'
    payload TEXT,                      -- JSON payload with task parameters
    result TEXT,                       -- JSON result from execution
    error TEXT,                        -- Error message if failed
    priority INTEGER DEFAULT 0,        -- Higher = more urgent
    scheduled_for TEXT,                -- When to run (NULL = immediately)
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Event log for audit trail and analytics
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,          -- 'application_status_change', 'email_received', etc.
    entity_type TEXT,                  -- 'application', 'prospect', 'task'
    entity_id INTEGER,
    old_value TEXT,                    -- JSON of previous state
    new_value TEXT,                    -- JSON of new state
    metadata TEXT,                     -- Additional JSON context
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Application email pairing (confirmation + resolution tracking)
CREATE TABLE IF NOT EXISTS application_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    email_type TEXT NOT NULL,          -- 'confirmation' | 'resolution'
    resolution_type TEXT,              -- NULL for confirmation, or: 'rejection' | 'screening' | 'interview' | 'offer'
    email_id TEXT,                     -- Gmail message ID
    sender TEXT,                       -- From address
    subject TEXT,                      -- Email subject
    received_at TEXT NOT NULL,         -- When email was received
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES applications(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_entries_role ON entries(role_id);
CREATE INDEX IF NOT EXISTS idx_entries_tags ON entries(tags);
CREATE INDEX IF NOT EXISTS idx_roles_company ON roles(company);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_geo_areas_name ON geo_areas(name);
CREATE INDEX IF NOT EXISTS idx_geo_companies_place_id ON geo_companies(place_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_scheduled ON tasks(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_resume_entries_resume ON resume_entries(resume_id);
CREATE INDEX IF NOT EXISTS idx_resume_entries_entry ON resume_entries(entry_id);
CREATE INDEX IF NOT EXISTS idx_resume_sections_resume ON resume_sections(resume_id);
CREATE INDEX IF NOT EXISTS idx_corpus_suggestions_status ON corpus_suggestions(status);
CREATE INDEX IF NOT EXISTS idx_corpus_suggestions_resume ON corpus_suggestions(resume_id);
CREATE INDEX IF NOT EXISTS idx_app_emails_app_type ON application_emails(application_id, email_type);
"""


@contextmanager
def get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_database() -> None:
    """Initialize the database with schema."""
    JJ_HOME.mkdir(exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    # Run migrations for existing databases
    migrate_database()


def migrate_database() -> None:
    """Run migrations to add new columns to existing databases."""
    migrations = [
        # Email tracking columns for applications
        ("applications", "email_confirmed", "BOOLEAN DEFAULT 0"),
        ("applications", "confirmed_at", "TEXT"),
        ("applications", "confirmation_email_id", "TEXT"),
        ("applications", "latest_update_type", "TEXT"),
        ("applications", "latest_update_at", "TEXT"),
        ("applications", "latest_update_subject", "TEXT"),
        ("applications", "latest_update_email_id", "TEXT"),
        ("applications", "last_email_check", "TEXT"),
        # Resume tracking columns
        ("resumes", "summary_text", "TEXT"),
        ("resumes", "drift_score", "INTEGER DEFAULT 0"),
        # TWC (Texas Workforce Commission) tracking columns
        ("applications", "twc_activity_type", "TEXT"),
        ("applications", "twc_result", "TEXT"),
        ("applications", "twc_result_other", "TEXT"),
        ("applications", "hired_start_date", "TEXT"),
        ("applications", "activity_date", "TEXT"),
        ("applications", "employer_phone", "TEXT"),
        ("applications", "employer_address", "TEXT"),
        ("applications", "employer_city", "TEXT"),
        ("applications", "employer_state", "TEXT"),
        ("applications", "employer_zip", "TEXT"),
        ("applications", "contact_name", "TEXT"),
        ("applications", "contact_email", "TEXT"),
        ("applications", "contact_fax", "TEXT"),
        # Google Docs tracking for resumes
        ("resumes", "google_doc_id", "TEXT"),
        # Email pairing tracking for applications
        ("applications", "pairing_status", "TEXT"),  # 'pending', 'confirmed', 'resolved', 'ghosted'
        ("applications", "days_waiting", "INTEGER"),  # Days since confirmation without resolution
    ]

    with get_connection() as conn:
        cursor = conn.cursor()

        for table, column, col_type in migrations:
            # Check if column exists
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]

            if column not in columns:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # Column already exists or other error

        # Ensure new tables exist (for existing databases)
        new_tables_sql = """
        CREATE TABLE IF NOT EXISTS resume_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resume_id INTEGER NOT NULL,
            section_type TEXT NOT NULL,
            section_name TEXT,
            content TEXT NOT NULL,
            position INTEGER,
            FOREIGN KEY (resume_id) REFERENCES resumes(id)
        );

        CREATE TABLE IF NOT EXISTS corpus_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resume_id INTEGER,
            jd_url TEXT,
            gap_type TEXT,
            theme TEXT,
            suggested_role_id INTEGER,
            suggestion TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (resume_id) REFERENCES resumes(id),
            FOREIGN KEY (suggested_role_id) REFERENCES roles(id)
        );

        CREATE INDEX IF NOT EXISTS idx_resume_entries_resume ON resume_entries(resume_id);
        CREATE INDEX IF NOT EXISTS idx_resume_entries_entry ON resume_entries(entry_id);
        CREATE INDEX IF NOT EXISTS idx_resume_sections_resume ON resume_sections(resume_id);
        CREATE INDEX IF NOT EXISTS idx_corpus_suggestions_status ON corpus_suggestions(status);
        CREATE INDEX IF NOT EXISTS idx_corpus_suggestions_resume ON corpus_suggestions(resume_id);
        CREATE INDEX IF NOT EXISTS idx_applications_activity_date ON applications(activity_date);

        -- Application email pairing table
        CREATE TABLE IF NOT EXISTS application_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            email_type TEXT NOT NULL,
            resolution_type TEXT,
            email_id TEXT,
            sender TEXT,
            subject TEXT,
            received_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (application_id) REFERENCES applications(id)
        );
        CREATE INDEX IF NOT EXISTS idx_app_emails_app_type ON application_emails(application_id, email_type);
        """
        conn.executescript(new_tables_sql)
        conn.commit()

        # Migrate resume_entries table if it has old schema (no role_id column)
        cursor.execute("PRAGMA table_info(resume_entries)")
        re_columns = [row[1] for row in cursor.fetchall()]
        if "role_id" not in re_columns:
            # Need to recreate the table with new schema
            try:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS resume_entries_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        resume_id INTEGER NOT NULL,
                        entry_id INTEGER NOT NULL,
                        role_id INTEGER NOT NULL,
                        position INTEGER,
                        FOREIGN KEY (resume_id) REFERENCES resumes(id),
                        FOREIGN KEY (entry_id) REFERENCES entries(id),
                        FOREIGN KEY (role_id) REFERENCES roles(id),
                        UNIQUE(resume_id, entry_id)
                    )
                """)
                # Copy existing data with role_id from entries table
                cursor.execute("""
                    INSERT OR IGNORE INTO resume_entries_new (resume_id, entry_id, role_id, position)
                    SELECT re.resume_id, re.entry_id, e.role_id, re.position
                    FROM resume_entries re
                    JOIN entries e ON re.entry_id = e.id
                """)
                cursor.execute("DROP TABLE resume_entries")
                cursor.execute("ALTER TABLE resume_entries_new RENAME TO resume_entries")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Table might already be correct


def get_stats() -> dict[str, int]:
    """Get corpus statistics."""
    if not DB_PATH.exists():
        return {"roles": 0, "entries": 0, "skills": 0, "resumes": 0, "applications": 0}

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM roles")
        roles = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM entries")
        entries = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM skills")
        skills = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM resumes")
        resumes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM applications")
        applications = cursor.fetchone()[0]

    return {
        "roles": roles,
        "entries": entries,
        "skills": skills,
        "resumes": resumes,
        "applications": applications,
    }


# Role operations

def create_role(
    title: str,
    company: str,
    location: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    is_current: bool = False,
    summary: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> int:
    """Create a new role and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO roles (title, company, location, start_date, end_date,
                              is_current, summary, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, company, location, start_date, end_date, is_current, summary,
             json.dumps(tags or []))
        )
        conn.commit()
        return cursor.lastrowid


def get_role(role_id: int) -> Optional[dict[str, Any]]:
    """Get a role by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE id = ?", (role_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def get_roles() -> list[dict[str, Any]]:
    """Get all roles ordered by start date (most recent first)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM roles ORDER BY start_date DESC, id DESC"
        )
        return [dict(row) for row in cursor.fetchall()]


def find_role_by_company_title(company: str, title: str) -> Optional[dict[str, Any]]:
    """Find a role by company and title."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM roles WHERE LOWER(company) = LOWER(?) AND LOWER(title) = LOWER(?)",
            (company, title)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


# Entry operations

def create_entry(
    role_id: int,
    text: str,
    category: Optional[str] = None,
    context: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metrics: Optional[list[str]] = None,
    source: str = "interview",
    source_line: Optional[int] = None,
) -> int:
    """Create a new entry and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO entries
            (role_id, text, category, context, tags, metrics, source, source_line)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (role_id, text, category, context, json.dumps(tags or []),
             json.dumps(metrics or []), source, source_line)
        )
        conn.commit()
        return cursor.lastrowid


def get_entries_for_role(role_id: int) -> list[dict[str, Any]]:
    """Get all entries for a role."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM entries WHERE role_id = ? ORDER BY id",
            (role_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_entries_by_tags(tags: list[str]) -> list[dict[str, Any]]:
    """Get entries matching any of the given tags."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Build query with OR conditions for tags
        conditions = " OR ".join(["tags LIKE ?" for _ in tags])
        params = [f'%"{tag}"%' for tag in tags]

        cursor.execute(
            f"SELECT * FROM entries WHERE {conditions} ORDER BY times_used DESC, id",
            params
        )
        return [dict(row) for row in cursor.fetchall()]


# Skill operations

def create_skill(
    name: str,
    category: Optional[str] = None,
    proficiency: Optional[str] = None,
) -> int:
    """Create a new skill and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO skills (name, category, proficiency)
            VALUES (?, ?, ?)
            """,
            (name, category, proficiency)
        )
        conn.commit()
        return cursor.lastrowid


def get_skills() -> list[dict[str, Any]]:
    """Get all skills."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM skills ORDER BY category, name")
        return [dict(row) for row in cursor.fetchall()]


# Application operations

def create_application(
    company: str,
    position: str,
    **kwargs
) -> int:
    """Create a new application record."""
    with get_connection() as conn:
        cursor = conn.cursor()

        fields = ["company", "position"] + list(kwargs.keys())
        placeholders = ", ".join(["?" for _ in fields])
        field_names = ", ".join(fields)
        values = [company, position] + list(kwargs.values())

        cursor.execute(
            f"INSERT INTO applications ({field_names}) VALUES ({placeholders})",
            values
        )
        conn.commit()
        return cursor.lastrowid


def get_applications(status: Optional[str] = None, include_skipped: bool = False) -> list[dict[str, Any]]:
    """Get applications, optionally filtered by status. Excludes 'skipped' by default."""
    with get_connection() as conn:
        cursor = conn.cursor()

        if status:
            cursor.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY applied_at DESC, created_at DESC",
                (status,)
            )
        elif include_skipped:
            cursor.execute("SELECT * FROM applications ORDER BY applied_at DESC, created_at DESC")
        else:
            cursor.execute("SELECT * FROM applications WHERE status != 'skipped' ORDER BY applied_at DESC, created_at DESC")

        return [dict(row) for row in cursor.fetchall()]


def get_application(app_id: int) -> Optional[dict[str, Any]]:
    """Get a single application by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def update_application(app_id: int, **kwargs) -> bool:
    """Update application fields. Returns True if successful."""
    if not kwargs:
        return False

    with get_connection() as conn:
        cursor = conn.cursor()

        # Build SET clause
        set_parts = [f"{key} = ?" for key in kwargs.keys()]
        set_parts.append("updated_at = CURRENT_TIMESTAMP")
        set_clause = ", ".join(set_parts)

        values = list(kwargs.values()) + [app_id]

        cursor.execute(
            f"UPDATE applications SET {set_clause} WHERE id = ?",
            values
        )
        conn.commit()
        return cursor.rowcount > 0


def get_pipeline_stats() -> dict[str, Any]:
    """Get pipeline statistics: count and avg days per status."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Count by status with average days
        cursor.execute("""
            SELECT
                status,
                COUNT(*) as count,
                ROUND(AVG(julianday('now') - julianday(COALESCE(applied_at, created_at))), 1) as avg_days
            FROM applications
            WHERE status NOT IN ('skipped', 'prospect')
            GROUP BY status
            ORDER BY
                CASE status
                    WHEN 'applied' THEN 1
                    WHEN 'screening' THEN 2
                    WHEN 'interview' THEN 3
                    WHEN 'offer' THEN 4
                    WHEN 'rejected' THEN 5
                    ELSE 6
                END
        """)

        stats = {}
        for row in cursor.fetchall():
            stats[row["status"]] = {
                "count": row["count"],
                "avg_days": row["avg_days"] or 0
            }

        # Count stale applications (applied > 7 days, screening > 14 days)
        cursor.execute("""
            SELECT COUNT(*) as stale_count FROM applications
            WHERE (
                (status = 'applied' AND julianday('now') - julianday(applied_at) > 7)
                OR (status = 'screening' AND julianday('now') - julianday(updated_at) > 14)
            )
        """)
        stale_row = cursor.fetchone()
        stats["stale_count"] = stale_row["stale_count"] if stale_row else 0

        # Prospect count
        cursor.execute("SELECT COUNT(*) as count FROM applications WHERE status = 'prospect'")
        prospect_row = cursor.fetchone()
        stats["prospect"] = {"count": prospect_row["count"] if prospect_row else 0}

        return stats


def get_stale_applications(days_threshold: int = 7) -> list[dict[str, Any]]:
    """Get applications needing follow-up."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *,
                ROUND(julianday('now') - julianday(COALESCE(applied_at, created_at)), 0) as days_since
            FROM applications
            WHERE (
                (status = 'applied' AND julianday('now') - julianday(applied_at) > ?)
                OR (status = 'screening' AND julianday('now') - julianday(updated_at) > ?)
            )
            ORDER BY days_since DESC
        """, (days_threshold, days_threshold * 2))

        return [dict(row) for row in cursor.fetchall()]


def update_application_email_confirmation(
    app_id: int,
    confirmed: bool,
    confirmed_at: Optional[str] = None,
    email_id: Optional[str] = None,
) -> bool:
    """Update email confirmation status for an application."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE applications SET
                email_confirmed = ?,
                confirmed_at = ?,
                confirmation_email_id = ?,
                last_email_check = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (confirmed, confirmed_at, email_id, app_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def update_application_latest_update(
    app_id: int,
    update_type: str,
    update_at: str,
    subject: str,
    email_id: str,
) -> bool:
    """Update latest email update info for an application."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE applications SET
                latest_update_type = ?,
                latest_update_at = ?,
                latest_update_subject = ?,
                latest_update_email_id = ?,
                last_email_check = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (update_type, update_at, subject, email_id, app_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_applications_missing_confirmation() -> list[dict[str, Any]]:
    """Get applied applications that don't have email confirmation yet."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM applications
            WHERE status = 'applied'
              AND (email_confirmed = 0 OR email_confirmed IS NULL)
            ORDER BY applied_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_applications_for_update_check(since_days: int = 7) -> list[dict[str, Any]]:
    """Get applications that should be checked for email updates."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM applications
            WHERE status NOT IN ('rejected', 'offer', 'skipped', 'prospect')
              AND (
                  last_email_check IS NULL
                  OR julianday('now') - julianday(last_email_check) > 1
              )
            ORDER BY applied_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


# Task queue operations

def create_task(
    task_type: str,
    payload: Optional[dict] = None,
    priority: int = 0,
    scheduled_for: Optional[str] = None,
) -> int:
    """Create a new background task."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tasks (task_type, payload, priority, scheduled_for)
            VALUES (?, ?, ?, ?)
            """,
            (task_type, json.dumps(payload or {}), priority, scheduled_for)
        )
        conn.commit()
        return cursor.lastrowid


def get_pending_tasks(limit: int = 10) -> list[dict[str, Any]]:
    """Get pending tasks that are ready to run."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM tasks
            WHERE status = 'pending'
              AND (scheduled_for IS NULL OR scheduled_for <= datetime('now'))
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_task(task_id: int) -> Optional[dict[str, Any]]:
    """Get a task by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def update_task_status(
    task_id: int,
    status: str,
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> bool:
    """Update task status and results."""
    with get_connection() as conn:
        cursor = conn.cursor()

        if status == 'running':
            cursor.execute(
                "UPDATE tasks SET status = ?, started_at = datetime('now') WHERE id = ?",
                (status, task_id)
            )
        elif status in ('completed', 'failed'):
            cursor.execute(
                """UPDATE tasks SET
                    status = ?,
                    result = ?,
                    error = ?,
                    completed_at = datetime('now')
                WHERE id = ?""",
                (status, json.dumps(result) if result else None, error, task_id)
            )
        else:
            cursor.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))

        conn.commit()
        return cursor.rowcount > 0


def get_recent_tasks(limit: int = 20) -> list[dict[str, Any]]:
    """Get recent tasks for monitoring."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM tasks
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_task_stats() -> dict[str, int]:
    """Get task queue statistics."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM tasks
            WHERE created_at > datetime('now', '-24 hours')
            GROUP BY status
        """)
        stats = {row['status']: row['count'] for row in cursor.fetchall()}
        return {
            'pending': stats.get('pending', 0),
            'running': stats.get('running', 0),
            'completed': stats.get('completed', 0),
            'failed': stats.get('failed', 0),
        }


def cleanup_old_tasks(days: int = 30) -> int:
    """Remove completed/failed tasks older than specified days."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM tasks
            WHERE status IN ('completed', 'failed')
              AND created_at < datetime('now', ?)
        """, (f'-{days} days',))
        conn.commit()
        return cursor.rowcount


# Event logging operations

def log_event(
    event_type: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> int:
    """Log an event for audit/analytics."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (event_type, entity_type, entity_id, old_value, new_value, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                entity_type,
                entity_id,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None,
                json.dumps(metadata) if metadata else None,
            )
        )
        conn.commit()
        return cursor.lastrowid


def get_events(
    event_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    since: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get events with optional filtering."""
    with get_connection() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM events WHERE 1=1"
        params = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)
        if since:
            query += " AND created_at >= ?"
            params.append(since)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


# Resume operations

def create_resume(
    filename: str,
    filepath: str,
    variant: Optional[str] = None,
    summary_text: Optional[str] = None,
    target_company: Optional[str] = None,
    target_role: Optional[str] = None,
    jd_url: Optional[str] = None,
    rj_score: Optional[int] = None,
    drift_score: int = 0,
    is_valid: bool = True,
    google_doc_id: Optional[str] = None,
) -> int:
    """Create a new resume record and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO resumes (filename, filepath, variant, summary_text, target_company,
                                target_role, jd_url, rj_score, drift_score, is_valid, google_doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (filename, filepath, variant, summary_text, target_company,
             target_role, jd_url, rj_score, drift_score, is_valid, google_doc_id)
        )
        conn.commit()
        return cursor.lastrowid


def get_resume(resume_id: int) -> Optional[dict[str, Any]]:
    """Get a resume by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def get_resumes(
    variant: Optional[str] = None,
    company: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get resumes with optional filtering."""
    with get_connection() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM resumes WHERE 1=1"
        params = []

        if variant:
            query += " AND variant = ?"
            params.append(variant)
        if company:
            query += " AND target_company LIKE ?"
            params.append(f"%{company}%")

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_resume_by_filepath(filepath: str) -> Optional[dict[str, Any]]:
    """Get a resume by its filepath."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM resumes WHERE filepath = ?", (filepath,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def update_resume(resume_id: int, **kwargs) -> bool:
    """Update resume fields. Returns True if successful."""
    if not kwargs:
        return False

    with get_connection() as conn:
        cursor = conn.cursor()

        set_parts = [f"{key} = ?" for key in kwargs.keys()]
        set_clause = ", ".join(set_parts)

        values = list(kwargs.values()) + [resume_id]

        cursor.execute(
            f"UPDATE resumes SET {set_clause} WHERE id = ?",
            values
        )
        conn.commit()
        return cursor.rowcount > 0


def validate_resume(resume_id: int, is_valid: bool, drift_score: int = 0) -> bool:
    """Mark a resume as validated with drift score."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE resumes SET
                is_valid = ?,
                drift_score = ?,
                validated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (is_valid, drift_score, resume_id)
        )
        conn.commit()
        return cursor.rowcount > 0


# Resume Entry operations

def create_resume_entry(
    resume_id: int,
    entry_id: int,
    role_id: int,
    position: Optional[int] = None,
) -> int:
    """Link an entry to a resume and return the ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO resume_entries (resume_id, entry_id, role_id, position)
            VALUES (?, ?, ?, ?)
            """,
            (resume_id, entry_id, role_id, position)
        )
        conn.commit()
        return cursor.lastrowid


def get_resume_entries(resume_id: int) -> list[dict[str, Any]]:
    """Get all entries for a resume with full entry and role details."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT re.*, e.text, e.category, e.tags as entry_tags,
                   r.title as role_title, r.company as role_company
            FROM resume_entries re
            JOIN entries e ON re.entry_id = e.id
            JOIN roles r ON re.role_id = r.id
            WHERE re.resume_id = ?
            ORDER BY re.position
            """,
            (resume_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_resume_entries(resume_id: int) -> int:
    """Delete all entries for a resume. Returns count deleted."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM resume_entries WHERE resume_id = ?", (resume_id,))
        conn.commit()
        return cursor.rowcount


def increment_entry_usage(entry_id: int) -> bool:
    """Increment the times_used counter for an entry."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE entries SET times_used = times_used + 1 WHERE id = ?",
            (entry_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


# Resume Section operations

def create_resume_section(
    resume_id: int,
    section_type: str,
    content: str,
    section_name: Optional[str] = None,
    position: Optional[int] = None,
) -> int:
    """Create a resume section and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO resume_sections (resume_id, section_type, section_name, content, position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (resume_id, section_type, section_name, content, position)
        )
        conn.commit()
        return cursor.lastrowid


def get_resume_sections(resume_id: int) -> list[dict[str, Any]]:
    """Get all sections for a resume."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM resume_sections WHERE resume_id = ? ORDER BY position",
            (resume_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_resume_sections(resume_id: int) -> int:
    """Delete all sections for a resume. Returns count deleted."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM resume_sections WHERE resume_id = ?", (resume_id,))
        conn.commit()
        return cursor.rowcount


# Corpus Suggestion operations

def create_corpus_suggestion(
    gap_type: str,
    theme: str,
    suggestion: str,
    resume_id: Optional[int] = None,
    jd_url: Optional[str] = None,
    suggested_role_id: Optional[int] = None,
) -> int:
    """Create a corpus improvement suggestion and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO corpus_suggestions
            (resume_id, jd_url, gap_type, theme, suggested_role_id, suggestion)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (resume_id, jd_url, gap_type, theme, suggested_role_id, suggestion)
        )
        conn.commit()
        return cursor.lastrowid


def get_corpus_suggestions(
    status: Optional[str] = None,
    gap_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get corpus suggestions with optional filtering."""
    with get_connection() as conn:
        cursor = conn.cursor()

        query = """
            SELECT cs.*, r.company as suggested_company, r.title as suggested_role_title
            FROM corpus_suggestions cs
            LEFT JOIN roles r ON cs.suggested_role_id = r.id
            WHERE 1=1
        """
        params = []

        if status:
            query += " AND cs.status = ?"
            params.append(status)
        if gap_type:
            query += " AND cs.gap_type = ?"
            params.append(gap_type)

        query += " ORDER BY cs.created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def update_corpus_suggestion_status(suggestion_id: int, status: str) -> bool:
    """Update the status of a corpus suggestion."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE corpus_suggestions SET status = ? WHERE id = ?",
            (status, suggestion_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def dismiss_corpus_suggestions_for_theme(theme: str) -> int:
    """Dismiss all pending suggestions for a theme. Returns count updated."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE corpus_suggestions SET status = 'dismissed' WHERE theme = ? AND status = 'pending'",
            (theme,)
        )
        conn.commit()
        return cursor.rowcount


# Entry query operations

def get_entry(entry_id: int) -> Optional[dict[str, Any]]:
    """Get an entry by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def get_all_entries() -> list[dict[str, Any]]:
    """Get all entries with their role info."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.*, r.company, r.title as role_title
            FROM entries e
            JOIN roles r ON e.role_id = r.id
            ORDER BY r.start_date DESC, e.id
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def search_entries(
    query: Optional[str] = None,
    tags: Optional[list[str]] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Search entries with various filters."""
    with get_connection() as conn:
        cursor = conn.cursor()

        sql = """
            SELECT e.*, r.company, r.title as role_title
            FROM entries e
            JOIN roles r ON e.role_id = r.id
            WHERE 1=1
        """
        params = []

        if query:
            sql += " AND e.text LIKE ?"
            params.append(f"%{query}%")

        if tags:
            tag_conditions = " OR ".join(["e.tags LIKE ?" for _ in tags])
            sql += f" AND ({tag_conditions})"
            params.extend([f'%"{tag}"%' for tag in tags])

        if category:
            sql += " AND e.category = ?"
            params.append(category)

        if source:
            sql += " AND e.source = ?"
            params.append(source)

        sql += " ORDER BY e.times_used DESC, e.id"

        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def find_entry_by_text(text: str, exact: bool = True) -> Optional[dict[str, Any]]:
    """Find an entry by its text content."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if exact:
            cursor.execute("SELECT * FROM entries WHERE text = ?", (text,))
        else:
            cursor.execute("SELECT * FROM entries WHERE text LIKE ?", (f"%{text}%",))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def update_entry(entry_id: int, **kwargs) -> bool:
    """Update entry fields. Returns True if successful."""
    if not kwargs:
        return False

    with get_connection() as conn:
        cursor = conn.cursor()

        set_parts = [f"{key} = ?" for key in kwargs.keys()]
        set_parts.append("updated_at = CURRENT_TIMESTAMP")
        set_clause = ", ".join(set_parts)

        values = list(kwargs.values()) + [entry_id]

        cursor.execute(
            f"UPDATE entries SET {set_clause} WHERE id = ?",
            values
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_entries_by_source(source: str) -> int:
    """Delete all entries from a specific source. Returns count deleted."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM entries WHERE source = ?", (source,))
        conn.commit()
        return cursor.rowcount


# Today's Focus queries

def get_todays_focus() -> dict[str, Any]:
    """Get items needing attention for the Today's Focus dashboard card."""
    with get_connection() as conn:
        cursor = conn.cursor()
        focus = {
            'unconfirmed_emails': [],
            'stale_applications': [],
            'recent_updates': [],
            'high_fit_prospects': [],
            'interview_prep': [],
        }

        # Unconfirmed emails (applied but no confirmation)
        cursor.execute("""
            SELECT id, company, position, applied_at,
                ROUND(julianday('now') - julianday(applied_at), 0) as days_ago
            FROM applications
            WHERE status = 'applied'
              AND (email_confirmed = 0 OR email_confirmed IS NULL)
              AND applied_at IS NOT NULL
            ORDER BY applied_at DESC
            LIMIT 5
        """)
        focus['unconfirmed_emails'] = [dict(row) for row in cursor.fetchall()]

        # Stale applications (need follow-up)
        cursor.execute("""
            SELECT id, company, position, status, applied_at, updated_at,
                ROUND(julianday('now') - julianday(COALESCE(updated_at, applied_at)), 0) as days_stale
            FROM applications
            WHERE (
                (status = 'applied' AND julianday('now') - julianday(applied_at) > 7)
                OR (status = 'screening' AND julianday('now') - julianday(COALESCE(updated_at, applied_at)) > 14)
            )
            ORDER BY days_stale DESC
            LIMIT 5
        """)
        focus['stale_applications'] = [dict(row) for row in cursor.fetchall()]

        # Recent email updates (last 7 days)
        cursor.execute("""
            SELECT id, company, position, latest_update_type, latest_update_at,
                   latest_update_subject, latest_update_email_id
            FROM applications
            WHERE latest_update_at IS NOT NULL
              AND julianday('now') - julianday(latest_update_at) <= 7
            ORDER BY latest_update_at DESC
            LIMIT 5
        """)
        focus['recent_updates'] = [dict(row) for row in cursor.fetchall()]

        # High-fit prospects not yet applied
        cursor.execute("""
            SELECT id, company, position, fit_score, job_url, created_at
            FROM applications
            WHERE status = 'prospect'
              AND fit_score >= 70
            ORDER BY fit_score DESC
            LIMIT 5
        """)
        focus['high_fit_prospects'] = [dict(row) for row in cursor.fetchall()]

        # Applications in interview stage (prep needed)
        cursor.execute("""
            SELECT id, company, position, updated_at, notes
            FROM applications
            WHERE status = 'interview'
            ORDER BY updated_at DESC
            LIMIT 5
        """)
        focus['interview_prep'] = [dict(row) for row in cursor.fetchall()]

        return focus


def get_focus_counts() -> dict[str, int]:
    """Get counts for Today's Focus items."""
    with get_connection() as conn:
        cursor = conn.cursor()

        counts = {}

        # Unconfirmed emails
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE status = 'applied'
              AND (email_confirmed = 0 OR email_confirmed IS NULL)
        """)
        counts['unconfirmed'] = cursor.fetchone()[0]

        # Stale applications
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE (
                (status = 'applied' AND julianday('now') - julianday(applied_at) > 7)
                OR (status = 'screening' AND julianday('now') - julianday(COALESCE(updated_at, applied_at)) > 14)
            )
        """)
        counts['stale'] = cursor.fetchone()[0]

        # Recent updates (last 7 days)
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE latest_update_at IS NOT NULL
              AND julianday('now') - julianday(latest_update_at) <= 7
        """)
        counts['recent_updates'] = cursor.fetchone()[0]

        # High-fit prospects
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE status = 'prospect' AND fit_score >= 70
        """)
        counts['high_fit'] = cursor.fetchone()[0]

        # Interview prep
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE status = 'interview'
        """)
        counts['interviews'] = cursor.fetchone()[0]

        counts['total'] = (
            counts['unconfirmed'] + counts['stale'] +
            counts['recent_updates'] + counts['high_fit'] + counts['interviews']
        )

        return counts


# TWC (Texas Workforce Commission) operations

def get_twc_week_boundaries(week_start: Optional[str] = None) -> tuple[str, str]:
    """
    Get the start (Sunday) and end (Saturday) dates for a TWC week.
    If week_start is None, returns the current week.
    Returns tuple of (sunday_date, saturday_date) in YYYY-MM-DD format.
    """
    from datetime import datetime, timedelta

    if week_start:
        start = datetime.strptime(week_start, "%Y-%m-%d")
    else:
        # Get current date and find the most recent Sunday
        today = datetime.now()
        # weekday() returns 0=Monday, so Sunday=6
        days_since_sunday = (today.weekday() + 1) % 7
        start = today - timedelta(days=days_since_sunday)

    # Ensure start is a Sunday
    days_since_sunday = (start.weekday() + 1) % 7
    start = start - timedelta(days=days_since_sunday)

    # Saturday is 6 days after Sunday
    end = start + timedelta(days=6)

    return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


def get_twc_activities_for_week(week_start: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Get all work search activities for a specific TWC week (Sunday-Saturday).
    Activities are applications with status != 'prospect' and != 'skipped'.
    """
    sunday, saturday = get_twc_week_boundaries(week_start)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT *,
                COALESCE(activity_date, DATE(applied_at), DATE(created_at)) as effective_date,
                CASE status
                    WHEN 'offer' THEN COALESCE(twc_result, 'hired')
                    WHEN 'rejected' THEN COALESCE(twc_result, 'not_hiring')
                    ELSE COALESCE(twc_result, 'application_filed')
                END as derived_twc_result
            FROM applications
            WHERE status NOT IN ('prospect', 'skipped')
              AND COALESCE(activity_date, DATE(applied_at), DATE(created_at)) BETWEEN ? AND ?
            ORDER BY COALESCE(activity_date, DATE(applied_at), DATE(created_at)) ASC
        """, (sunday, saturday))
        return [dict(row) for row in cursor.fetchall()]


def get_twc_week_summary(week_start: Optional[str] = None) -> dict[str, Any]:
    """
    Get summary statistics for a TWC week.
    Returns activity counts, completeness status, etc.
    """
    sunday, saturday = get_twc_week_boundaries(week_start)
    activities = get_twc_activities_for_week(week_start)

    # Group by day
    from collections import defaultdict
    by_day = defaultdict(list)
    for act in activities:
        day = act.get('effective_date') or act.get('activity_date') or act.get('applied_at', '')[:10]
        by_day[day].append(act)

    # Count by activity type
    by_type = defaultdict(int)
    for act in activities:
        act_type = act.get('twc_activity_type') or 'applied'
        by_type[act_type] += 1

    # TWC requires minimum 3 work search activities per week
    required = 3
    total = len(activities)

    return {
        'week_start': sunday,
        'week_end': saturday,
        'total_activities': total,
        'required_activities': required,
        'is_complete': total >= required,
        'activities_by_day': dict(by_day),
        'activities_by_type': dict(by_type),
    }


def update_twc_fields(app_id: int, **kwargs) -> bool:
    """
    Update TWC-specific fields for an application.
    Valid fields: twc_activity_type, twc_result, twc_result_other, hired_start_date,
                  activity_date, employer_phone, employer_address, employer_city,
                  employer_state, employer_zip, contact_name, contact_email, contact_fax
    """
    valid_fields = {
        'twc_activity_type', 'twc_result', 'twc_result_other', 'hired_start_date',
        'activity_date', 'employer_phone', 'employer_address', 'employer_city',
        'employer_state', 'employer_zip', 'contact_name', 'contact_email', 'contact_fax'
    }

    # Filter to only valid TWC fields
    twc_updates = {k: v for k, v in kwargs.items() if k in valid_fields}

    if not twc_updates:
        return False

    return update_application(app_id, **twc_updates)


def backfill_activity_dates() -> int:
    """
    Backfill activity_date from applied_at for existing applications.
    Returns count of records updated.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE applications
            SET activity_date = DATE(applied_at)
            WHERE activity_date IS NULL
              AND applied_at IS NOT NULL
              AND status NOT IN ('prospect', 'skipped')
        """)
        conn.commit()
        return cursor.rowcount


def get_twc_activity_types() -> list[dict[str, str]]:
    """Return the list of valid TWC activity types with labels."""
    return [
        {'value': 'applied', 'label': 'Applied for job'},
        {'value': 'resume', 'label': 'Submitted resume'},
        {'value': 'interview', 'label': 'Interviewed'},
        {'value': 'job_fair', 'label': 'Attended job fair'},
        {'value': 'workforce_center', 'label': 'Used Workforce Center'},
        {'value': 'online_search', 'label': 'Searched online'},
    ]


def get_twc_result_types() -> list[dict[str, str]]:
    """Return the list of valid TWC result types with labels."""
    return [
        {'value': 'application_filed', 'label': 'Application filed'},
        {'value': 'hired', 'label': 'Hired'},
        {'value': 'not_hiring', 'label': 'Not hiring'},
        {'value': 'other', 'label': 'Other'},
    ]


def derive_twc_result(status: str) -> str:
    """Derive TWC result from application status."""
    mapping = {
        'applied': 'application_filed',
        'screening': 'application_filed',
        'interview': 'application_filed',
        'offer': 'hired',
        'rejected': 'not_hiring',
    }
    return mapping.get(status, 'application_filed')


# Corpus data assembly operations

def get_roles_ordered_by_date(limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Get roles ordered by start_date DESC (most recent first)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT * FROM roles
            ORDER BY
                CASE WHEN is_current = 1 THEN 0 ELSE 1 END,
                start_date DESC,
                id DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]


def get_entries_for_role_ordered(role_id: int, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Get entries for a role ordered by times_used DESC."""
    with get_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT * FROM entries
            WHERE role_id = ?
            ORDER BY times_used DESC, id ASC
        """
        if limit:
            query += f" LIMIT {limit}"
        cursor.execute(query, (role_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_skills_by_category() -> dict[str, list[str]]:
    """Get skills grouped by category."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, category FROM skills
            WHERE category IS NOT NULL AND category != ''
            ORDER BY category, name
        """)

        skills_by_cat: dict[str, list[str]] = {}
        for row in cursor.fetchall():
            cat = row['category']
            if cat not in skills_by_cat:
                skills_by_cat[cat] = []
            skills_by_cat[cat].append(row['name'])

        return skills_by_cat


# Application Email Pairing operations

def add_application_email(
    application_id: int,
    email_type: str,  # 'confirmation' or 'resolution'
    received_at: str,
    email_id: Optional[str] = None,
    sender: Optional[str] = None,
    subject: Optional[str] = None,
    resolution_type: Optional[str] = None,  # For resolution: 'rejection', 'screening', 'interview', 'offer'
) -> int:
    """Add an email to the application_emails table."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO application_emails
            (application_id, email_type, resolution_type, email_id, sender, subject, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (application_id, email_type, resolution_type, email_id, sender, subject, received_at)
        )
        conn.commit()
        return cursor.lastrowid


def get_application_emails(app_id: int) -> list[dict[str, Any]]:
    """Get all emails for an application."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM application_emails
            WHERE application_id = ?
            ORDER BY received_at ASC
            """,
            (app_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_confirmation_email(app_id: int) -> Optional[dict[str, Any]]:
    """Get the confirmation email for an application (first one if multiple)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM application_emails
            WHERE application_id = ? AND email_type = 'confirmation'
            ORDER BY received_at ASC
            LIMIT 1
            """,
            (app_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def get_resolution_email(app_id: int) -> Optional[dict[str, Any]]:
    """Get the resolution email for an application (most recent if multiple)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM application_emails
            WHERE application_id = ? AND email_type = 'resolution'
            ORDER BY received_at DESC
            LIMIT 1
            """,
            (app_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def compute_pairing_status(app_id: int) -> tuple[str, int]:
    """
    Compute the pairing status and days waiting for an application.
    Returns (status, days_waiting) where status is one of:
    - 'pending': No confirmation email yet
    - 'confirmed': Has confirmation but no resolution
    - 'resolved': Has both confirmation and resolution
    - 'ghosted': Has confirmation but no resolution for 14+ days
    - 'unconfirmed': Applied 3+ days ago with no confirmation
    """
    from datetime import datetime

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get application info
        cursor.execute(
            "SELECT applied_at, created_at FROM applications WHERE id = ?",
            (app_id,)
        )
        app_row = cursor.fetchone()
        if not app_row:
            return ('pending', 0)

        applied_at = app_row['applied_at'] or app_row['created_at']

        # Get confirmation email
        confirmation = get_confirmation_email(app_id)

        # Get resolution email
        resolution = get_resolution_email(app_id)

        # Calculate days
        now = datetime.now()
        days_since_applied = 0
        days_since_confirmation = 0

        if applied_at:
            try:
                applied_date = datetime.fromisoformat(applied_at.replace('Z', '+00:00'))
                if applied_date.tzinfo:
                    applied_date = applied_date.replace(tzinfo=None)
                days_since_applied = (now - applied_date).days
            except (ValueError, TypeError):
                pass

        if confirmation and confirmation.get('received_at'):
            try:
                conf_date = datetime.fromisoformat(confirmation['received_at'].replace('Z', '+00:00'))
                if conf_date.tzinfo:
                    conf_date = conf_date.replace(tzinfo=None)
                days_since_confirmation = (now - conf_date).days
            except (ValueError, TypeError):
                pass

        # Determine status
        if resolution:
            return ('resolved', 0)
        elif confirmation:
            if days_since_confirmation >= 14:
                return ('ghosted', days_since_confirmation)
            else:
                return ('confirmed', days_since_confirmation)
        elif days_since_applied >= 3:
            return ('unconfirmed', days_since_applied)
        else:
            return ('pending', days_since_applied)


def update_application_pairing_status(app_id: int) -> bool:
    """Update the pairing_status and days_waiting for an application."""
    status, days_waiting = compute_pairing_status(app_id)
    return update_application(app_id, pairing_status=status, days_waiting=days_waiting)


def get_applications_with_pairing_status(
    status_filter: Optional[str] = None,
    include_resolved: bool = True,
) -> list[dict[str, Any]]:
    """
    Get applications with computed pairing status.

    Args:
        status_filter: Filter by pairing status ('pending', 'confirmed', 'resolved', 'ghosted')
        include_resolved: If False, exclude resolved applications
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        query = """
            SELECT a.*,
                (SELECT COUNT(*) FROM application_emails ae
                 WHERE ae.application_id = a.id AND ae.email_type = 'confirmation') as has_confirmation,
                (SELECT COUNT(*) FROM application_emails ae
                 WHERE ae.application_id = a.id AND ae.email_type = 'resolution') as has_resolution,
                (SELECT ae.resolution_type FROM application_emails ae
                 WHERE ae.application_id = a.id AND ae.email_type = 'resolution'
                 ORDER BY ae.received_at DESC LIMIT 1) as latest_resolution_type,
                (SELECT ae.received_at FROM application_emails ae
                 WHERE ae.application_id = a.id AND ae.email_type = 'confirmation'
                 ORDER BY ae.received_at ASC LIMIT 1) as confirmation_date,
                (SELECT ae.received_at FROM application_emails ae
                 WHERE ae.application_id = a.id AND ae.email_type = 'resolution'
                 ORDER BY ae.received_at DESC LIMIT 1) as resolution_date
            FROM applications a
            WHERE a.status NOT IN ('prospect', 'skipped')
            ORDER BY a.applied_at DESC, a.created_at DESC
        """

        cursor.execute(query)
        results = []

        for row in cursor.fetchall():
            app = dict(row)

            # Compute pairing status from query results
            has_conf = app.get('has_confirmation', 0) > 0
            has_res = app.get('has_resolution', 0) > 0

            # Calculate days
            from datetime import datetime
            now = datetime.now()
            days_waiting = 0

            if has_res:
                pairing_status = 'resolved'
            elif has_conf:
                conf_date_str = app.get('confirmation_date')
                if conf_date_str:
                    try:
                        conf_date = datetime.fromisoformat(conf_date_str.replace('Z', '+00:00'))
                        if conf_date.tzinfo:
                            conf_date = conf_date.replace(tzinfo=None)
                        days_waiting = (now - conf_date).days
                    except (ValueError, TypeError):
                        pass

                if days_waiting >= 14:
                    pairing_status = 'ghosted'
                else:
                    pairing_status = 'confirmed'
            else:
                applied_at = app.get('applied_at') or app.get('created_at')
                if applied_at:
                    try:
                        applied_date = datetime.fromisoformat(applied_at.replace('Z', '+00:00'))
                        if applied_date.tzinfo:
                            applied_date = applied_date.replace(tzinfo=None)
                        days_waiting = (now - applied_date).days
                    except (ValueError, TypeError):
                        pass

                if days_waiting >= 3:
                    pairing_status = 'unconfirmed'
                else:
                    pairing_status = 'pending'

            app['computed_pairing_status'] = pairing_status
            app['computed_days_waiting'] = days_waiting

            # Apply filter
            if status_filter and pairing_status != status_filter:
                continue
            if not include_resolved and pairing_status == 'resolved':
                continue

            results.append(app)

        return results


def get_ghosted_applications(days_threshold: int = 14) -> list[dict[str, Any]]:
    """Get applications that are ghosted (confirmed but no resolution for N+ days)."""
    return [
        app for app in get_applications_with_pairing_status()
        if app.get('computed_pairing_status') == 'ghosted'
        and app.get('computed_days_waiting', 0) >= days_threshold
    ]


def get_unconfirmed_applications(days_threshold: int = 3) -> list[dict[str, Any]]:
    """Get applications that haven't received confirmation email after N days."""
    return [
        app for app in get_applications_with_pairing_status()
        if app.get('computed_pairing_status') == 'unconfirmed'
        and app.get('computed_days_waiting', 0) >= days_threshold
    ]


def get_application_timeline(company: str) -> list[dict[str, Any]]:
    """
    Get full email timeline for applications from a company.
    Returns chronologically ordered events (application, confirmation, resolution).
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get applications for this company
        cursor.execute(
            """
            SELECT id, company, position, applied_at, created_at, status
            FROM applications
            WHERE LOWER(company) LIKE LOWER(?)
            ORDER BY applied_at DESC, created_at DESC
            """,
            (f"%{company}%",)
        )
        applications = [dict(row) for row in cursor.fetchall()]

        timeline = []

        for app in applications:
            # Add application event
            applied_date = app.get('applied_at') or app.get('created_at')
            if applied_date:
                timeline.append({
                    'date': applied_date[:10] if applied_date else None,
                    'event_type': 'applied',
                    'company': app['company'],
                    'position': app['position'],
                    'application_id': app['id'],
                    'details': f"Applied to {app['position']} at {app['company']}",
                })

            # Get emails for this application
            emails = get_application_emails(app['id'])
            for email in emails:
                event_type = email['email_type']
                if event_type == 'resolution':
                    event_type = email.get('resolution_type') or 'resolution'

                timeline.append({
                    'date': email.get('received_at', '')[:10] if email.get('received_at') else None,
                    'event_type': event_type,
                    'company': app['company'],
                    'position': app['position'],
                    'application_id': app['id'],
                    'email_id': email.get('email_id'),
                    'sender': email.get('sender'),
                    'subject': email.get('subject'),
                    'details': email.get('subject') or f"{event_type.title()} email",
                })

        # Sort by date
        timeline.sort(key=lambda x: x.get('date') or '9999-99-99')

        return timeline


def email_already_recorded(email_id: str) -> bool:
    """Check if an email has already been recorded in application_emails."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM application_emails WHERE email_id = ? LIMIT 1",
            (email_id,)
        )
        return cursor.fetchone() is not None


def get_pairing_stats() -> dict[str, Any]:
    """Get statistics about email pairing status across all applications."""
    apps = get_applications_with_pairing_status()

    stats = {
        'total': len(apps),
        'pending': 0,
        'confirmed': 0,
        'resolved': 0,
        'ghosted': 0,
        'unconfirmed': 0,
        'by_resolution_type': {
            'rejection': 0,
            'screening': 0,
            'interview': 0,
            'offer': 0,
        }
    }

    for app in apps:
        status = app.get('computed_pairing_status')
        if status in stats:
            stats[status] += 1

        # Count resolution types
        res_type = app.get('latest_resolution_type')
        if res_type and res_type in stats['by_resolution_type']:
            stats['by_resolution_type'][res_type] += 1

    return stats
