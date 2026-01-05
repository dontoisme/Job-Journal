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
    filename TEXT UNIQUE NOT NULL,
    filepath TEXT NOT NULL,
    variant TEXT,                 -- 'growth', 'ai-agentic', 'health-tech', etc.
    target_company TEXT,
    target_role TEXT,
    jd_url TEXT,
    rj_score INTEGER,             -- Resume-JD match score
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    validated_at TEXT,
    drift_score INTEGER,
    is_valid BOOLEAN DEFAULT 1
);

-- Resume-Entry junction (which bullets in which resume)
CREATE TABLE IF NOT EXISTS resume_entries (
    resume_id INTEGER REFERENCES resumes(id),
    entry_id INTEGER REFERENCES entries(id),
    position INTEGER,             -- Order in the resume
    PRIMARY KEY (resume_id, entry_id)
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
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_entries_role ON entries(role_id);
CREATE INDEX IF NOT EXISTS idx_entries_tags ON entries(tags);
CREATE INDEX IF NOT EXISTS idx_roles_company ON roles(company);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
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


def get_applications(status: Optional[str] = None) -> list[dict[str, Any]]:
    """Get applications, optionally filtered by status."""
    with get_connection() as conn:
        cursor = conn.cursor()

        if status:
            cursor.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY created_at DESC",
                (status,)
            )
        else:
            cursor.execute("SELECT * FROM applications ORDER BY created_at DESC")

        return [dict(row) for row in cursor.fetchall()]
