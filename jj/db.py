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
) -> int:
    """Create a new resume record and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO resumes (filename, filepath, variant, summary_text, target_company,
                                target_role, jd_url, rj_score, drift_score, is_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (filename, filepath, variant, summary_text, target_company,
             target_role, jd_url, rj_score, drift_score, is_valid)
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
